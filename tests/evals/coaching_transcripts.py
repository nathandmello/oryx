"""Prepare a fictional Hub and audit the durable effects of individual coaching turns."""

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
import subprocess

from meeting_transcripts import ROOT, hub_command, pm, reviewed_studio, snapshot


CASES = json.loads(Path(__file__).with_name("coaching_cases.json").read_text(encoding="utf-8"))
STRATEGY = "workspace/strategies/billing-export.md"
PM_PROFILE = "context/pm/context.md"
STAKEHOLDERS = "context/stakeholders/overview.md"
PRIOR_REMIT = {"status": "confirmed", "responsibilities": [], "follow": ["topic/clinic-operations"]}


def capture(hub, scope, reference, quote, day, **fields):
    entry = dict(source=1, location="Section 1", quote=quote, scope=scope, **fields)
    destination = f"context/products/{entry['product']}/overview.md"
    source = {"reference": reference, "date": day, "checked_on": day, "coverage": "read", "text": quote}
    payload = {"sources": [source], "entries": [entry]}
    if "decision" in entry:
        review = json.loads(hub_command(hub, "route-context", data=json.dumps(payload)))["entries"][0]
        entry["record_decision"] = {"revision": review["decision_revision"], "pm": "Eval PM", "date": day,
                                    "reference": "Simulated PM confirmation", "reply": "Record this decision."}
    hub_command(hub, "route-context", "--write", destination, data=json.dumps(payload))


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
    day = date.today().isoformat()
    if case == "pm-walkthrough":
        # Simulate a Studio with an accepted remit from before guided onboarding.
        pm.context_capture.write_remit(hub / "studio", PRIOR_REMIT)
        for topic in ("customers", "economics", "portfolio", "growth"):
            status = json.loads(hub_command(hub, "onboarding", "status"))
            hub_command(hub, "onboarding", "review-topic", data=json.dumps({
                "revision": status["revision"], "stage": "company", "topic": topic,
                "outcome": "open", "pm_reply": "We discussed this. Leave it open.",
            }))
    elif case not in {"company-first", "founder-company"}:
        seed_product_work(hub, day)
    print(hub_command(hub, "check").strip())
    baseline = {"case": case, "made_on": day, "resolve_on": (date.today() + timedelta(days=30)).isoformat(),
                "system": snapshot(hub), "private": snapshot(hub / "studio")}
    (run / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")


def seed_product_work(hub, day):
    reviewed_studio(hub, hub / "studio")
    hub_command(hub, "set-remit", data=json.dumps({"status": "confirmed", "follow": [],
                "responsibilities": [{"subject": "product/" + name, "role": "owner", "depends_on": [], "goals": []}
                                     for name in ("billing", "shipping")]}))
    hub_command(hub, "new", "company-context", "context/company/overview.md")
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


def company_review_checks(hub, turn):
    case = CASES["company-first"]
    status = json.loads(hub_command(hub, "company-onboarding", "status"))
    readiness = json.loads(hub_command(hub, "onboarding", "status"))
    outcomes = [("customers", "reviewed"), ("economics", "open"), ("portfolio", "not_applicable"),
                ("growth", "open"), ("tradeoffs", "open")]
    covered = max(0, turn - 5)
    company = readiness["walkthroughs"]["company"]
    complete = covered == len(outcomes)
    stage = "pm" if complete else "company"
    checks = {"setup_stage": readiness["stage"] == stage, "product_work_held": not readiness["ready"],
              "reviewed_points": company["reviewed"] == dict(outcomes[:covered]),
              "company_walkthrough_complete": company["complete"] == complete}
    if complete:
        checks["pm_walkthrough_available"] = readiness["stage_available"]
    if turn == 1:
        checks["fresh_studio"] = status["phase"] == "welcome" and status["revision"] == 0
        return checks
    if turn in (2, 3):
        plan = status["plan"] or {}
        scopes = plan.get("sources", [])
        checks["single_deck_scope"] = len(scopes) == 1 and case["source"].lower() in scopes[0].lower()
        if turn == 2:
            checks["waiting_for_approval"] = status["phase"] == "plan"
        else:
            item = status["pending"] or {}
            checks["finding_in_review"] = (status["phase"] == "review"
                                           and item.get("entry", {}).get("quote") == case["quote"])
        return checks
    path = hub / "studio/context/company/overview.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    heading = "Decisions already closed"
    decisions = []
    errors = []
    if pm.records.section(text, heading) is not None:
        decisions, errors = pm.records.table(text, heading, pm.records.CONTEXT_TABLES[heading])
    checks.update({
        "attributed_finding": all(s.lower() in text.lower() for s in
                                 (case["source"], case["quote"], "slide 4", "2026-10-15")),
        "no_product_decision": not errors and all(pm.records.PLACEHOLDER.search(row[0]) for row in decisions),
        "unresolved_priority": any("enterprise" in g["question"].lower()
                                   and "operating review" in g["resume_when"].lower()
                                   and g["next_action"].strip() for g in status["gaps"]),
        "review_finished": status["phase"] == "existing" and status["pending"] is None,
    })
    return checks


def pm_walkthrough_checks(run, turn, changed, current):
    hub = run / "hub"
    case = CASES["pm-walkthrough"]
    journey = json.loads(hub_command(hub, "onboarding", "status"))
    capture = json.loads(hub_command(hub, "pm-onboarding", "status"))
    allowed = {"workspace/onboarding/review.json"}
    if turn >= 2:
        allowed.add("workspace/onboarding/pm.json")
    if turn >= 4:
        allowed.add(PM_PROFILE)
    if turn == 10:
        allowed.add(STAKEHOLDERS)
    milestones = [(4, "role", "reviewed"), (6, "responsibilities", "reviewed"),
                  (7, "expectations", "open"), (8, "aspirations", "reviewed"),
                  (10, "stakeholders", "reviewed")]
    checks = {
        "only_authorized_changes": changed == allowed,
        "company_pass_complete": journey["walkthroughs"]["company"]["complete"],
        "setup_stage": journey["stage"] == ("product" if turn == 10 else "pm"),
        "available_step": journey["stage_available"] == (turn < 10),
        "product_work_held": not journey["ready"],
        "reviewed_points": journey["walkthroughs"]["pm"]["reviewed"] == {
            topic: outcome for milestone, topic, outcome in milestones if milestone <= turn},
        "prior_remit_preserved": pm.context_capture.read_remit(hub / "studio") == PRIOR_REMIT,
    }
    if 2 <= turn <= 9:
        plan = capture["plan"] or {}
        scopes = plan.get("sources", [])
        checks["agreed_scope"] = (set(plan.get("destinations", [])) == {PM_PROFILE, STAKEHOLDERS}
                                  and len(scopes) == 1 and case["source"].lower() in scopes[0].lower())
    if turn == 2:
        checks["awaiting_permission"] = capture["phase"] == "plan"
    if turn in (3, 9):
        reviewed = json.loads(hub_command(hub, "pm-onboarding", "status", "--pending"))
        pending = reviewed["pending"] or {}
        checks["draft_hidden_by_default"] = capture["has_pending"] and capture.get("pending") is None
        expected = ((PM_PROFILE, case["role_quote"]) if turn == 3 else (STAKEHOLDERS, case["stakeholder_quote"]))
        checks["one_scoped_preview"] = (
            capture["phase"] == "review" and (pending.get("destination"), pending.get("entry", {}).get("quote")) == expected)
    else:
        checks["no_unreviewed_proposal"] = not capture["has_pending"]
    if turn >= 4:
        path = hub / "studio" / PM_PROFILE
        profile = path.read_text() if path.is_file() else ""
        checks["sourced_role"] = all(term.lower() in profile.lower()
                                     for term in (case["role_quote"], case["source"], "2026-10-15", "My work"))
        checks["stakeholder_kept_separate"] = "Jules" not in profile
        receipt = run / "accepted-profile.json"
        if turn == 4 and all(checks.values()):
            receipt.write_text(json.dumps(current[PM_PROFILE]))
        if turn > 4:
            checks["accepted_profile_preserved"] = receipt.is_file() and json.loads(receipt.read_text()) == current.get(PM_PROFILE)
    if turn == 10:
        path = hub / "studio" / STAKEHOLDERS
        text = path.read_text() if path.is_file() else ""
        checks["sourced_stakeholder"] = all(term.lower() in text.lower()
                                            for term in (case["stakeholder_quote"], case["source"], "2026-10-15", "Review meeting"))
        checks["pm_kept_separate"] = case["role_quote"] not in text
    return checks


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
    if case == "pm-walkthrough":
        checks.update(pm_walkthrough_checks(run, turn, changed, current))
    if case == "company-first":
        # No sourced claim may reach the overview before acceptance on turn four.
        files = {"workspace/onboarding/company.json"} if turn >= 2 else set()
        if turn >= 4:
            files.add("context/company/overview.md")
        if turn >= 6:
            files.add("workspace/onboarding/review.json")
        checks["only_authorized_changes"] = changed == files
        checks.update(company_review_checks(hub, turn))
        receipt = run / "accepted-company.json"
        if turn == 4 and all(checks.values()):
            overview = "context/company/overview.md"
            receipt.write_text(json.dumps({overview: current[overview]}), encoding="utf-8")
        if turn >= 5:
            saved = json.loads(receipt.read_text()) if receipt.is_file() else {}
            checks["company_context_preserved"] = bool(saved) and all(current.get(name) == value for name, value in saved.items())
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
