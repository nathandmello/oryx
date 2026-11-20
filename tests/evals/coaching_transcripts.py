"""Prepare a fictional Hub and audit the durable effects of individual coaching turns."""

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
import subprocess

from meeting_transcripts import ROOT, hub_command, pm, snapshot


CASES = json.loads(Path(__file__).with_name("coaching_cases.json").read_text(encoding="utf-8"))
STRATEGY = "workspace/strategies/billing-export.md"


def capture(hub, scope, reference, quote, day, **fields):
    entry = dict(source=1, location="Section 1", quote=quote, scope=scope, **fields)
    destination = f"context/products/{entry['product']}/overview.md"
    source = {"reference": reference, "date": day, "checked_on": day, "coverage": "read", "text": quote}
    hub_command(hub, "route-context", "--write", destination,
                data=json.dumps({"sources": [source], "entries": [entry]}))


def prepare(run, case):
    run.mkdir(parents=True, exist_ok=False)
    hub = run / "hub"
    for source in pm.inventory(ROOT):
        rel = source.relative_to(ROOT)
        if rel.parts[:2] == ("tests", "evals") or rel.parts[0] not in pm.ROOT_DIRS | pm.ROOT_FILES:
            continue
        if source.is_file() and not source.is_symlink():
            target = hub / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    subprocess.run(["git", "init", "-q", str(hub)], check=True)
    hub_command(hub, "init-workspace", "--owner", "Eval PM")
    hub_command(hub, "set-remit", data=json.dumps({"status": "confirmed", "follow": [],
                "responsibilities": [{"subject": "product/" + name, "role": "owner", "depends_on": [], "goals": []}
                                     for name in ("billing", "shipping")]}))
    hub_command(hub, "new", "company-context", "context/company/overview.md")
    day = date.today().isoformat()
    capture(hub, "product", "Ledger interviews", "Operators merge two invoice exports by hand.",
            day, product="billing", topic="offer")
    capture(hub, "product", "Billing staffing review", "A pilot would take a pod off the dispute queue.",
            day, product="billing", topic="constraints")
    capture(hub, "product", "Carrier cutoff review", "The carrier pickup cutoff is 16:00 UTC.",
            day, product="shipping", topic="constraints")
    capture(hub, "product", "Billing pilot decision", "Keep the manual pilot before investing in bulk export.",
            day, product="billing", topic="decisions", decision={"question": "Which pilot should Billing use?",
            "scope": "Billing pilot", "person": "Mira Chen", "date": day, "next_step": "Inspect the pilot audit."})
    billing = hub / "studio/context/products/billing/overview.md"
    text = billing.read_text(encoding="utf-8")
    text = text.replace("| State | draft |", "| State | active |")
    text = text.replace("| Last reviewed | not reviewed |", f"| Last reviewed | {day} |")
    text = text.replace("{{Product release, closed decision, new evidence, or a change to obligations.}}",
                        "The audit or a staffing decision changes the pilot.")
    text = text.replace("{{one concrete step}}", "Review the pilot audit.")
    billing.write_text(text, encoding="utf-8")
    hub_command(hub, "new", "strategy", STRATEGY, "--title", "Billing export")
    strategy = hub / "studio" / STRATEGY
    text = strategy.read_text(encoding="utf-8")
    text = text.replace("{{date and result}}", f"{day}. The cost to the dispute queue is still open.")
    text = text.replace("{{one concrete step}}", "Confirm pilot staffing before choosing rollout scope.")
    strategy.write_text(text, encoding="utf-8")
    print(hub_command(hub, "check").strip())
    baseline = {"case": case, "made_on": day, "resolve_on": (date.today() + timedelta(days=30)).isoformat(),
                "system": snapshot(hub), "private": snapshot(hub / "studio")}
    (run / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")


def audit(run, baseline, turn):
    hub = run / "hub"
    current = snapshot(hub / "studio")
    original = baseline["private"]
    changed = {name for name in original.keys() | current.keys() if original.get(name) != current.get(name)}
    allowed = set()
    case = baseline["case"]
    expected = True
    if case == "defer-and-resume" and turn >= 2:
        allowed = {STRATEGY}
        expected = STRATEGY in changed and STRATEGY in current
    if case == "forecast-retry" and turn >= 2:
        allowed = {p for p in current if Path(p).parent == Path("workspace/forecasts") and p.endswith(".json")}
        expected = len(allowed) == 1 and allowed == changed
        if expected:
            try:
                records = json.loads(hub_command(hub, "forecast", "list", "--product", "billing"))
            except subprocess.CalledProcessError:
                records = []
            forecast = records[0] if len(records) == 1 else {}
            expected = (forecast.get("authority", {}).get("record") == "context/products/billing/overview.md"
                        and forecast["probability"] == 75 and forecast["made_on"] == baseline["made_on"]
                        and forecast["resolve_on"] == baseline["resolve_on"]
                        and not forecast["revisions"] and forecast["resolution"] is None)
    if case in {"defer-and-resume", "forecast-retry"} and turn >= 2 and expected:
        receipt = run / "authorized-write.json"
        state = {name: current[name] for name in allowed}
        if receipt.is_file():
            expected = state == json.loads(receipt.read_text(encoding="utf-8"))
        elif turn == 2 and changed == allowed:
            receipt.write_text(json.dumps(state), encoding="utf-8")
        else:
            expected = False
    checks = {"system_intact": snapshot(hub) == baseline["system"],
              "only_authorized_changes": changed <= allowed, "expected_write": expected}
    print(json.dumps({"checks": checks, "changed": sorted(changed)}, indent=2))
    return all(checks.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    setup = sub.add_parser("prepare")
    setup.add_argument("case", choices=CASES)
    setup.add_argument("run", type=Path)
    rubric = sub.add_parser("rubric")
    rubric.add_argument("case", choices=CASES)
    for name in ("turn", "audit"):
        op = sub.add_parser(name)
        op.add_argument("run", type=Path)
        op.add_argument("number", type=int)
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare(args.run.resolve(), args.case)
    elif args.operation == "rubric":
        print("\n".join(CASES[args.case]["criteria"]))
    else:
        baseline = json.loads((args.run / "baseline.json").read_text(encoding="utf-8"))
        turns = CASES[baseline["case"]]["turns"]
        if not 1 <= args.number <= len(turns):
            parser.error(f"Choose a turn between 1 and {len(turns)}.")
        if args.operation == "turn":
            print(turns[args.number - 1].format(resolve_on=baseline["resolve_on"]))
        elif not audit(args.run, baseline, args.number):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
