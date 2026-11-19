"""Publish a verified default-branch merge. All remote writes occur after verification."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from release_candidate import VERSION, candidate_version
from release_review import RetryPublication, publication
from workspace import git


def github(path, method="GET", data=None):
    url = f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/{path}"
    request = Request(url, method=method, data=json.dumps(data).encode() if data is not None else None,
                      headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                               "Accept": "application/vnd.github+json", "Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def optional(api, path):
    try:
        return api(path)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        return None


def select_candidate(event, ref, sha, api):
    branch = event["repository"]["default_branch"]
    if ref != "refs/heads/" + branch:
        raise ValueError("Publish from the default branch")
    if not api("branches/" + quote(branch, safe=""))["protected"]:
        raise ValueError("Enable the documented default-branch protections before publication")
    if "inputs" in event:
        number = event["inputs"]["release_pr"]
    else:
        if event.get("after") != sha or event.get("forced") or event.get("deleted"):
            raise ValueError("Expected a normal default-branch push")
        pulls = api(f"commits/{sha}/pulls?per_page=100")
        matches = [pr for pr in pulls if pr["merge_commit_sha"] == sha and pr["base"]["ref"] == branch]
        if not matches:
            raise RetryPublication("Waiting for GitHub to associate the pushed commit with a merged PR")
        if len(matches) != 1 or git(Path.cwd(), "rev-parse", sha + "^1") != event["before"]:
            raise ValueError("Expected one release PR in this push")
        number = matches[0]["number"]
    if not re.fullmatch(r"[1-9][0-9]*", str(number)):
        raise ValueError("Select a merged PR number")
    pr = api(f"pulls/{number}")
    merge = pr["merge_commit_sha"]
    if not merge or merge not in git(Path.cwd(), "rev-list", "--first-parent", sha).splitlines():
        raise ValueError("The release must be in the default branch's first-parent history")
    if "inputs" not in event and merge != sha:
        raise ValueError("The merged PR changed after the push")
    publication(pr, branch, merge, api)
    return pr, merge, candidate_version(merge + "^1", merge)


def release_notes(pr):
    body = pr["body"].replace("\r\n", "\n")
    parts = [f"{pr['title']} (#{pr['number']})", pr["html_url"]]
    for heading in ("Change", "Consumer impact and recovery", "Verification limits"):
        section = re.search(r"^## " + heading + r" *\n(.*?)(?=^## |\Z)", body, re.M | re.S)
        if not section:
            if heading == "Change":
                continue
            raise ValueError("Missing release notes section " + heading)
        value = re.sub(r"(?m)^Reviewed commit:.*$", "", section[1]).strip()
        if value and "<!--" not in value:
            parts.append(f"## {heading}\n\n{value}")
    return "\n\n".join(parts)


def ensure_tag(tag, sha, api):
    path = "git/ref/tags/" + tag
    ref = optional(api, path)
    if ref is None:
        obj = api("git/tags", "POST", {"tag": tag, "message": f"PM Hub {tag}", "object": sha, "type": "commit",
                                      "tagger": {"name": "github-actions[bot]",
                                                 "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                 "email": "41898282+github-actions[bot]@users.noreply.github.com"}})
        api("git/refs", "POST", {"ref": "refs/tags/" + tag, "sha": obj["sha"]})
        ref = api(path)
    if ref["object"]["type"] == "tag":
        obj = api("git/tags/" + ref["object"]["sha"])
        if obj["tag"] == tag and obj["object"]["sha"] == sha and obj["object"]["type"] == "commit":
            return
    raise ValueError(f"Existing tag {tag} does not identify the verified annotated commit")


def create_release(tag, notes):
    result = subprocess.run(["gh", "release", "create", tag, "--repo", os.environ["GITHUB_REPOSITORY"],
                    "--title", f"PM Hub {tag}", "--verify-tag", "--latest=false", "--notes-file", "-"],
                   input=notes, text=True, capture_output=True)
    if result.returncode:
        error = result.stderr.strip()
        if re.search(r"HTTP (429|5[0-9]{2})|timed? ?out|connection reset|EOF|already exists", error, re.I):
            raise RetryPublication(error)
        raise ValueError(error or "GitHub Release creation failed")


def publish(pr, sha, version, api=github, create=create_release):
    tag = "v" + version
    ensure_tag(tag, sha, api)
    path = "releases/tags/" + tag
    release = optional(api, path)
    if release is None:
        create(tag, release_notes(pr))
        release = api(path)
    if release["tag_name"] != tag or release["draft"] or release["prerelease"]:
        raise ValueError("The release must be a published stable release for " + tag)

    # All publishers share a queue. An older retry can finish after a newer release.
    versions = {}
    page = 1
    while True:
        batch = api(f"releases?per_page=100&page={page}")
        for item in batch:
            name = item["tag_name"]
            if not item["draft"] and not item["prerelease"] and name.startswith("v") and VERSION.fullmatch(name[1:]):
                versions[tuple(map(int, name[1:].split(".")))] = item
        if len(batch) < 100:
            break
        page += 1
    if tuple(map(int, version.split("."))) not in versions:
        raise RetryPublication("Waiting for the published release to appear in release history")
    highest = versions[max(versions)]
    latest = optional(api, "releases/latest")
    if latest is None or latest["id"] != highest["id"]:
        api(f"releases/{highest['id']}", "PATCH", {"make_latest": "true"})
    return release["html_url"]


def retry_publication(operation, sleep=time.sleep):
    # Re-read GitHub state from the start after any ambiguous write.
    for attempt, delay in enumerate((5, 15, 0)):
        try:
            return operation()
        except (RetryPublication, URLError, TimeoutError, ConnectionError) as exc:
            if isinstance(exc, HTTPError):
                advised = exc.headers.get("Retry-After", "")
                if exc.code not in {408, 429, 500, 502, 503, 504} and not advised:
                    raise
                if advised.isdecimal():
                    delay = max(delay, int(advised))
            if attempt == 2 or delay > 60:
                raise RetryPublication(f"Automatic publication retries exhausted: {exc}") from exc
            print(f"Retrying publication in {delay} seconds: {exc}", file=sys.stderr)
            sleep(delay)


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    def release():
        pr, sha, version = select_candidate(event, os.environ["GITHUB_REF"], os.environ["GITHUB_SHA"], github)
        return pr, sha, version, publish(pr, sha, version)
    pr, sha, version, url = retry_publication(release)
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        print(f"Published [v{version}]({url}) from PR #{pr['number']} at `{sha}`.", file=summary)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Release publication failed: {exc}")
