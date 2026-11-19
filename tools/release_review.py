"""Check the recorded engineering and quality reviews for a specific release candidate."""

import json
import os
import re
import sys
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def review(pr):
    body = (pr.get("body") or "").replace("\r\n", "\n")
    head = pr["head"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", head) or re.findall(r"(?m)^Reviewed commit: `([0-9a-f]{40})` *$", body) != [head]:
        raise ValueError("Record both reviews for the current pull request head")
    reviewers = []
    for title in ("Engineering review", "Quality review", "Consumer impact and recovery", "Verification limits"):
        sections = re.findall(r"^## " + title + r"[ \t]*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
        if len(sections) != 1 or not sections[0].strip() or "<!--" in sections[0]:
            raise ValueError(f"Complete the {title} section")
        if title.endswith("review"):
            for field in ("Reviewer", "Decision", "Evidence"):
                values = re.findall(r"^" + field + r":[ \t]*(.+?)\s*$", sections[0], re.M)
                if len(values) != 1 or not values[0].strip() or values[0].strip().lower() in {"tbd", "pending", "todo"}:
                    raise ValueError(f"Record {field.lower()} under {title}")
                if field == "Reviewer":
                    reviewers.append(values[0].strip().casefold())
                if field == "Decision" and values[0].strip().casefold() != "pass":
                    raise ValueError(f"Resolve the outstanding {title.lower()}")
    if reviewers[0] == reviewers[1]:
        raise ValueError("Identify the independent engineering and quality reviewers")


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


def publication(event, ref, sha, api):
    branch = event["repository"]["default_branch"]
    number = event["inputs"]["release_pr"]
    if not re.fullmatch(r"[1-9][0-9]*", str(number)) or ref != "refs/heads/" + branch:
        raise ValueError("Select a merged pull request and run this check on the default branch")
    pr = api(f"pulls/{number}")
    review(pr)
    if not (pr["merged"] and pr["base"]["ref"] == branch and pr["merge_commit_sha"] == sha
            and api("git/ref/heads/" + quote(branch, safe="/"))["object"]["sha"] == sha):
        raise ValueError("The selected pull request must match the installed default branch tip")
    head = pr["head"]["sha"]
    if api("git/commits/" + head)["tree"]["sha"] != api("git/commits/" + sha)["tree"]["sha"]:
        raise ValueError("The merged tree differs from the reviewed tree")
    query = urlencode({"head_sha": head, "event": "pull_request", "per_page": 100})
    runs = api("actions/workflows/check.yml/runs?" + query)["workflow_runs"]
    matching = [run for run in runs if any(p["number"] == pr["number"] for p in run["pull_requests"])]
    matching.extend(detached_pr_runs(pr, runs, api))
    latest = max(matching, key=lambda run: (run["run_number"], run["run_attempt"]), default={})
    if latest.get("conclusion") != "success":
        raise ValueError("The reviewed pull request needs a successful PM Hub checks run")


def main():
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
        event = json.load(stream)
    if os.environ["GITHUB_EVENT_NAME"] == "pull_request":
        review(event["pull_request"])
    else:
        base = os.environ["GITHUB_API_URL"] + "/repos/" + os.environ["GITHUB_REPOSITORY"] + "/"
        def api(path):
            request = Request(base + path, headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                                                    "Accept": "application/vnd.github+json"})
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        publication(event, os.environ["GITHUB_REF"], os.environ["GITHUB_SHA"], api)
    print("PM Hub release review passed.")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError) as exc:
        sys.exit(f"Release review failed: {exc}")
