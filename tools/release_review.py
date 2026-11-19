"""Check the recorded engineering and quality reviews for a specific release candidate."""

import json
import os
import re
import sys
from urllib.parse import urlencode


class RetryPublication(ValueError):
    """GitHub has not finished reporting the candidate or publication."""


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
    review(pr)
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
        event = json.load(stream)
    review(event["pull_request"])
    print("PM Hub release review passed.")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError) as exc:
        sys.exit(f"Release review failed: {exc}")
