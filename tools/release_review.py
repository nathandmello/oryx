"""Check browser impact and authenticated reviews for a release candidate."""

import json
import os
import re
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BROWSER_WORKFLOW_FILES = {
    ".agents/skills/manage-initiative-work/SKILL.md",
    ".agents/skills/prioritize-roadmap/SKILL.md",
    "playbook/initiative-approvals.md",
    "playbook/initiative-views.md",
    "playbook/initiative-work.md",
    "templates/launch-checklist.json",
    "templates/prioritization.md",
    "templates/views/roadmap.json",
    "tools/customizations.py",
    "playbook/customization-defaults.json",
    "tools/initiative_events.py",
    "tools/initiative_store.py",
    "tools/initiative_views.py",
    "tools/initiative_work.py",
    "tools/initiatives_cli.py",
    "tools/layout.py",
    "tools/local_ui.py",
    "tools/pm.py",
    "tools/roadmap_edit.py",
}


class RetryPublication(ValueError):
    """GitHub has not finished reporting the candidate or publication."""


def github(path, method="GET", data=None):
    url = f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/{path}"
    request = Request(url, method=method, data=json.dumps(data).encode() if data is not None else None,
                      headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                               "Accept": "application/vnd.github+json", "Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def codex_bot(item):
    author = item.get("user") or {}
    return author.get("login") == "chatgpt-codex-connector[bot]" and author.get("id") == 199175422


def issue_items(number, resource, api):
    page = 1
    while True:
        items = api(f"issues/{number}/{resource}?per_page=100&page={page}")
        yield from items
        if len(items) < 100:
            return
        page += 1


def joint_clearance(pr, summary, api):
    # Codex documents this reaction as its combined no-findings verdict. Reactions
    # have no commit ID. Require one strictly newer than the current-head receipt.
    if "reacts with 👍 once all reviews finish with no findings" not in summary["body"]:
        return False
    reactions = [r for r in issue_items(pr["number"], "reactions", api) if codex_bot(r)]
    if any(r["content"] == "eyes" for r in reactions):
        return False
    return any(r["content"] == "+1" and r["created_at"] > summary["updated_at"] for r in reactions)


def browser_impact(pr, api):
    count = pr["changed_files"]
    files = {}
    for page in range(1, (count + 99) // 100 + 1):
        for changed in api(f"pulls/{pr['number']}/files?per_page=100&page={page}"):
            files[changed["filename"]] = changed
    if len(files) != count:
        raise ValueError("Could not verify all changed paths for the browser impact check")
    paths = files.keys() | {item["previous_filename"] for item in files.values() if item.get("previous_filename")}
    if not (paths & BROWSER_WORKFLOW_FILES or any(path.startswith("tools/local_ui/") for path in paths)):
        return

    body = (pr.get("body") or "").replace("\r\n", "\n")
    sections = re.findall(r"^## Browser impact[ \t]*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    if len(sections) != 1 or "<!--" in sections[0]:
        raise ValueError("Add one Browser impact section for the affected workflow")
    impact = re.match(r"^(Changed|Unchanged):[ \t]+\S", sections[0].strip())
    if not impact:
        raise ValueError("Start Browser impact with Changed: or Unchanged: and explain the result")
    if impact[1] == "Changed" and not any(
        path.startswith("tests/browser/") and path.endswith(".spec.js") and item["additions"] > 0
        for path, item in files.items()
    ):
        raise ValueError("Add or update a Playwright scenario for the changed browser behavior")


def review(pr, api):
    body = (pr.get("body") or "").replace("\r\n", "\n")
    for title in ("Consumer impact and recovery", "Verification limits"):
        sections = re.findall(r"^## " + title + r"[ \t]*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
        if len(sections) != 1 or not sections[0].strip() or "<!--" in sections[0]:
            raise ValueError(f"Complete the {title} section")

    head = pr["head"]["sha"]
    summaries = [item for item in issue_items(pr["number"], "comments", api)
                 if codex_bot(item) and item["body"].startswith("<!-- codex-pull-request-review-summary -->\n")]
    if not summaries:
        raise ValueError("Waiting for the Codex review summary")
    latest = max(summaries, key=lambda item: item["id"])
    match = re.search(r"^<!-- codex-review-state:v1 (.+) -->$", latest["body"], re.M)
    if not match:
        raise ValueError("Codex review state is unavailable")
    state = json.loads(match[1])
    for key in ("code_review", "security_review"):
        result = state[key]
        if result["commit_sha"] != head or result["status"] != "completed":
            raise ValueError(f"Waiting for {key} on the current PR commit")
        if result.get("has_unresolved_findings") is False:
            continue
        if key == "security_review" and result.get("has_unresolved_findings") is None:
            if joint_clearance(pr, latest, api):
                continue
            # The public summary can omit private security findings. Use the app's
            # current-commit check when it supplies the security decision separately.
            checks = api(f"commits/{head}/check-runs?filter=latest&per_page=100")
            security = [check for check in checks["check_runs"]
                        if check["head_sha"] == head and (check.get("app") or {}).get("slug") == "chatgpt-codex-connector"
                        and check["name"].casefold() in {"codex security", "codex security review"}]
            if checks["total_count"] <= 100 and security and all(check["conclusion"] == "success" for check in security):
                continue
        raise ValueError(f"{key} needs a confirmed passing result for the current PR commit")


def detached_pr_runs(pr, runs, api):
    head = pr["head"]
    repo = head.get("repo")
    branch = head.get("ref")
    opened_at = pr.get("created_at")
    if not repo or not branch or not opened_at:
        return []

    # GitHub can clear run associations after merge. Use the exact source
    # identity only when that branch has served exactly one pull request.
    candidates = [
        run for run in runs
        if not run["pull_requests"] and run.get("event") == "pull_request"
        and run.get("head_sha") == head["sha"] and run.get("head_branch") == branch
        and (run.get("head_repository") or {}).get("id") == repo["id"]
        and (run.get("created_at") or "") >= opened_at
    ]
    if not candidates:
        return []
    source = repo["owner"]["login"] + ":" + branch
    query = urlencode({"state": "all", "head": source, "per_page": 100})
    pulls = api("pulls?" + query)
    if len(pulls) != 1 or pulls[0]["number"] != pr["number"] or pulls[0]["head"]["sha"] != head["sha"]:
        raise ValueError("Cannot uniquely associate the reviewed head with this pull request")
    return candidates


def successful_run(pr, workflow, api):
    query = urlencode({"head_sha": pr["head"]["sha"], "event": "pull_request", "per_page": 100})
    runs = api(f"actions/workflows/{workflow}/runs?" + query)["workflow_runs"]
    matching = [run for run in runs if any(p["number"] == pr["number"] for p in run["pull_requests"])]
    matching.extend(detached_pr_runs(pr, runs, api))
    latest = max(matching, key=lambda run: (run["run_number"], run["run_attempt"]), default={})
    if latest and latest.get("conclusion") is None:
        raise RetryPublication(f"Waiting for the successful {workflow} run to finish")
    if latest.get("conclusion") != "success":
        raise ValueError(f"The reviewed pull request needs a successful {workflow} run")

    return latest


def publication(pr, branch, sha, api):
    review(pr, api)
    if not (pr["merged"] and pr["base"]["ref"] == branch and pr["merge_commit_sha"] == sha):
        raise ValueError("Select the merged pull request for this commit and default branch")
    tree = api("git/commits/" + sha)["tree"]["sha"]
    if api("git/commits/" + pr["head"]["sha"])["tree"]["sha"] != tree:
        raise ValueError("The merged tree differs from the reviewed tree")
    evidence = successful_run(pr, "review.yml", api)
    review_jobs = api(f"actions/runs/{evidence['id']}/jobs?filter=latest&per_page=100")["jobs"]
    if not any(job["name"] == "review" and job["conclusion"] == "success" for job in review_jobs):
        raise ValueError("Missing successful review job for this PR")
    run = successful_run(pr, "check.yml", api)
    jobs = api(f"actions/runs/{run['id']}/jobs?filter=latest&per_page=100")["jobs"]
    if not any(job["name"] == "check" and job["conclusion"] == "success"
               and any(step["name"] == "Tested tree " + tree and step["conclusion"] == "success"
                       for step in job["steps"]) for job in jobs):
        raise ValueError("Missing successful CI evidence for the merged tree")


def main():
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
        submitted = json.load(stream)["pull_request"]
    endpoint = f"pulls/{submitted['number']}"
    current = github(endpoint)
    for ref in ("base", "head"):
        if current[ref]["sha"] != submitted[ref]["sha"]:
            raise ValueError("The pull request commits changed. Run review on the current pull request")
    browser_impact(current, github)
    review(current, github)
    latest = github(endpoint)
    if (latest["head"]["sha"], latest["base"]["sha"], latest["body"]) != (
        current["head"]["sha"], current["base"]["sha"], current["body"]
    ):
        raise ValueError("The pull request changed during review. Run review again")
    print("oryx release review passed.")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError) as exc:
        sys.exit(f"Release review failed: {exc}")
