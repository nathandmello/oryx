"""Prepare a disposable Hub for a transcript eval and check the agent's file changes."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import pm
from onboarding_fixtures import reviewed_studio


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in pm.inventory(root) if p.is_file() and not p.is_symlink()}


def hub_command(hub, *args, data=None):
    return subprocess.run([sys.executable, "-B", "tools/pm.py", *args], cwd=hub,
                          input=data, text=True, check=True, capture_output=True).stdout


def openedx_transcript(view):
    # The public reader wraps paragraphs in numbered lines. Rejoin them before splitting speakers.
    lines = re.findall(r"^L\d+: ?(.*)$", view, re.MULTILINE)
    rendered = " ".join(lines) if lines else " ".join(view.split())
    start = "Feanil Patel: Hello."
    _, found, body = rendered.partition("Transcript " + start)
    dialogue, end, _ = body.partition(" Meeting ended after 00:08:57")
    if not found or not end:
        raise ValueError("The saved view must include the complete October 3 transcript")
    turns = re.sub(r" (?=Feanil Patel:|Adolfo Brandes:|Sarina Canelake:|00:05:00)", "\n", start + dialogue)
    lines = turns.replace("00:05:00 ", "00:05:00\n").splitlines()
    return ("\n".join(line.strip() for line in lines) + "\n").encode("utf-8")


def prepare(case, run, source_file, source_view):
    if source_view:
        if case.get("extract") != "openedx":
            raise ValueError("--source-view applies to the Open edX wiki case")
        data = openedx_transcript(source_view.read_text(encoding="utf-8"))
    elif source_file:
        data = source_file.read_bytes()
    elif "fixture" in case:
        data = Path(__file__).with_name(case["fixture"]).read_bytes()
    elif "download" in case:
        with urlopen(case["download"], timeout=45) as response:
            data = response.read()
    else:
        raise SystemExit("Supply the Open edX public wiki reader output with --source-view (see meeting-transcripts.md)")
    if digest(data) != case["sha256"]:
        raise ValueError("Downloaded transcript differs from the reviewed revision")
    if "lines" in case:
        start, end = case["lines"]
        data = b"".join(data.splitlines(keepends=True)[start - 1:end])
    run.mkdir(parents=True, exist_ok=False)
    inputs = run / "input"
    inputs.mkdir()
    if case["input"] != "connector":
        (inputs / case["filename"]).write_bytes(data)

    hub = run / "hub"
    hub.mkdir()
    for source in pm.inventory(ROOT):
        rel = source.relative_to(ROOT)
        if rel.parts[:2] == ("tests", "evals"):
            continue
        if rel.parts[0] not in pm.ROOT_DIRS | pm.ROOT_FILES:
            continue
        if source.is_file() and not source.is_symlink():
            target = hub / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    subprocess.run(["git", "init", "-q", str(hub)], check=True)
    hub_command(hub, "init-workspace", "--owner", "Eval PM", "--delivery-system", "Fixture tracker")
    reviewed_studio(hub, hub / "studio")
    hub_command(hub, "set-remit", data=json.dumps({
        "status": "confirmed", "follow": [],
        "responsibilities": [{"subject": "product/eval-product", "role": "owner", "goals": [], "depends_on": []}]
    }))
    hub_command(hub, "new", "company-context", "context/company/overview.md", "--title", "Eval company")
    product = "context/products/eval-product/overview.md"
    hub_command(hub, "new", "product-context", product, "--title", "Eval product")
    overview = pm.layout.initiative(case["initiative"], "eval-product")
    hub_command(hub, "new", "initiative-context", overview, "--parent", product, "--title", case["title"])
    print(hub_command(hub, "check").strip())
    baseline = {"system": snapshot(hub), "private": snapshot(hub / "studio")}
    (run / "baseline.json").write_text(json.dumps(baseline, sort_keys=True))
    (run / "prompt.txt").write_text(case["prompt"] + "\n")
    print(run / "prompt.txt")


def replay(case, prior, run):
    if not prior or case["mode"] != "capture" or not check(case, prior):
        raise SystemExit("Replay needs a successful capture in --prior-run")
    if run == prior or prior in run.parents:
        raise SystemExit("Choose a separate directory for the replay")
    run.mkdir(parents=True, exist_ok=False)
    hub = run / "hub"
    shutil.copytree(prior / "hub", hub)
    shutil.copytree(prior / "input", run / "input")
    baseline = {"system": snapshot(hub), "private": snapshot(hub / "studio"), "replay": True}
    (run / "baseline.json").write_text(json.dumps(baseline, sort_keys=True))
    (run / "prompt.txt").write_text(case["prompt"] + " We may already have filed this meeting. Please check.\n")


def check(case, run):
    hub = run / "hub"
    before = json.loads((run / "baseline.json").read_text())
    after = snapshot(hub / "studio")
    changed = {p for p in before["private"].keys() | after.keys() if before["private"].get(p) != after.get(p)}
    prompt = case["prompt"]
    if before.get("replay"):
        prompt += " We may already have filed this meeting. Please check."
    tests = {"matching request": (run / "prompt.txt").read_text().strip() == prompt,
             "system intact": snapshot(hub) == before["system"]}
    if before.get("replay"):
        tests["existing evidence and note unchanged"] = not changed.difference({"README.md"})
    elif case["mode"] == "capture":
        overview = pm.records.initiative_home(hub / "studio", "eval-product", case["initiative"])
        entity = Path(overview).parent
        notes = [p for p in changed if Path(p).parent == entity and Path(p).name.startswith(case["date"] + "-")
                 and after.get(p) and (hub / "studio" / p).read_text().startswith("<!-- pm: context-note -->")]
        tests["initiative overview updated"] = overview in changed and overview in after
        tests["one dated meeting note"] = len(notes) == 1
        overview_text = (hub / "studio" / overview).read_text() if overview in after else ""
        tests["overview links to dated note"] = len(notes) == 1 and f"({Path(notes[0]).name})" in overview_text
        tests["only initiative records and checkpoint changed"] = not changed.difference(notes, [overview, "README.md"])
    elif case["mode"] == "clarify":
        tests["no filing before clarification"] = not changed
    else:
        tests["summary leaves private records intact"] = not changed
    print(hub_command(hub, "check").strip())
    print(json.dumps({"checks": tests, "changed": sorted(changed)}, indent=2))
    return all(tests.values())


if __name__ == "__main__":
    cases = json.loads(Path(__file__).with_name("meeting_cases.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "replay", "check"))
    parser.add_argument("case", choices=cases)
    parser.add_argument("run", type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source-file", type=Path, help="Use a previously downloaded transcript with the recorded hash")
    source.add_argument("--source-view", type=Path, help="Extract the Open edX transcript from a saved public wiki view")
    parser.add_argument("--prior-run", type=Path, help="Completed capture to replay in a fresh agent session")
    args = parser.parse_args()
    case = cases[args.case]
    if args.operation == "prepare":
        prepare(case, args.run.resolve(), args.source_file, args.source_view)
    elif args.operation == "replay":
        replay(case, args.prior_run.resolve() if args.prior_run else None, args.run.resolve())
    elif not check(case, args.run.resolve()):
        sys.exit(1)
