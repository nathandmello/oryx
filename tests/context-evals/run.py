"""Run product-context probes against oryx and score prepared workspace-task results."""

import argparse
from datetime import date
from itertools import permutations
import json
from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from test_pm import HubTests, confirmed_decisions, legacy_inline_area, pm, records
from onboarding_fixtures import reviewed_studio


def command(root, *args):
    return subprocess.run(
        [sys.executable, "-B", str(root / "tools/pm.py"), *args],
        cwd=root, capture_output=True, text=True, check=True, timeout=45,
    ).stdout


def capture(hub, destination, entries, evidence=None, evidence_id=None):
    sources = []
    if evidence_id is not None:
        source = evidence[evidence_id]
        sources.append({
            "reference": source.get("reference") or f"[{source['title']}]({source['url']})",
            "date": source["date"], "coverage": "read", "checked_on": date.today().isoformat(),
            "text": source["text"],
        })
        entries = [
            dict(entry, source=1, quote=source["text"], location=source["title"])
            for entry in entries
        ]
    payload = {"sources": sources, "entries": entries}
    if any("decision" in entry for entry in entries):
        preview = hub.context_capture(payload)
        if preview.returncode:
            raise RuntimeError(preview.stdout or preview.stderr)
        payload = confirmed_decisions(payload, json.loads(preview.stdout))
    result = hub.context_capture(payload, "--write", destination)
    if result.returncode:
        raise RuntimeError(f"{destination}: {result.stdout or result.stderr}")
    return json.loads(result.stdout)["written"]


def headings(text):
    return re.findall(r"(?m)^## (.+)$", text)


def hook(hub, event, **extra):
    return hub.run_hook(json.dumps({"hook_event_name": event, "cwd": str(hub.root), **extra}))


def checks(hub, evidence):
    company = "context/company/overview.md"
    payments = "context/products/payments/overview.md"
    refund = evidence["stripe-total"]["text"]
    company_rule = "Verify the relevant product policy before making a customer commitment."
    company_entry = {"scope": "company", "topic": "constraints", "rule": company_rule}
    company_source = {"company": {"title": "Fixture company policy", "date": "undated",
                                  "url": "https://example.test/policy", "text": company_rule}}
    capture(hub, company, [company_entry], company_source, "company")

    topics = {
        "offer": ("The product", "Who uses checkout?"),
        "constraints": ("Constraints", "Who sets the refund cap?"),
        "goals": ("Goals, performance, and gaps", "Which refund measure is tracked?"),
    }
    expected = [label for label in headings((hub.root / "templates/product-context.md").read_text())
                if label in {heading for heading, _ in topics.values()}]
    observed = []
    for number, order in enumerate(permutations(topics), 1):
        product = f"checkout-{number}"
        path = f"context/products/{product}/overview.md"
        for topic in order:
            capture(hub, path, [{"scope": "product", "product": product, "topic": topic,
                                 "question": topics[topic][1]}])
        names = [name for name in headings((hub.work / path).read_text()) if name in expected]
        passed = names == expected
        observed.append(names)
        yield "artifact", f"capture order {number}", passed, " → ".join(names)
    yield "artifact", "one order across permutations", len({tuple(seen) for seen in observed}) == 1, (
        f"{len({tuple(seen) for seen in observed})} distinct orders for the same topics"
    )

    parents = pm.check(hub.root)
    yield "control", "captured fixtures are structurally valid", parents == [], repr(parents)
    file = hub.work / company
    original = file.read_text()
    file.write_text(original.replace("## Context controls", "## Miscellaneous\n\nPromise every refund.\n\n## Context controls"))
    errors = pm.check(hub.root)
    yield "artifact", "ad hoc uncited guidance is reported", any(company in error for error in errors), (
        "A typed context brief contains an uncited promise under Miscellaneous"
    )
    file.write_text(original)

    strategy = records.create(hub.root, "strategy", "workspace/strategies/refunds.md")
    text = strategy.read_text()
    why, who, what = (text.index(f"## {name}\n") for name in ("Why", "Who", "What"))
    strategy.write_text(text[:why] + text[who:what] + text[why:who] + text[what:])
    errors = pm.check(hub.root)
    yield "artifact", "reordered strategy is reported", any(strategy.name in error for error in errors), (
        "Who appears before Why in a typed strategy draft"
    )
    strategy.write_text(text)
    for name in ("workspace/initiatives/refunds/launch-plan.md", "workspace/backlogs/payments.md"):
        path = hub.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Work\n\nRoll out next week.\n")
        errors = pm.check(hub.root)
        yield "artifact", f"minimum working record fields for {path.name}", any(name in error for error in errors), (
            "No scope, evidence or next step"
        )
        path.unlink()

    area_entry = {"scope": "product", "product": "payments", "product_area": "refunds", "topic": "constraints",
                  "interpretation": "Check earlier partial refunds before quoting a remaining amount."}
    for product in ("payments", "slack-imports"):
        legacy_inline_area(hub.root, hub.work, product, "refunds", "Which limit applies?")
    first = capture(hub, payments, [area_entry], evidence, "stripe-total")
    before = (hub.work / payments).read_bytes()
    replay = capture(hub, payments, [area_entry], evidence, "stripe-total")
    yield "control", "source capture replay leaves the record intact", (
        first == payments and replay is None and (hub.work / payments).read_bytes() == before
    ), "Replayed identical Stripe evidence"
    other = "context/products/slack-imports/overview.md"
    other_entry = dict(area_entry, product="slack-imports",
                       interpretation="Apply the conversation cap to new unlisted installs.")
    capture(hub, other, [other_entry], evidence, "slack-limits")
    capture(hub, other, [{"scope": "product", "product": "slack-imports", "topic": "constraints",
                          "rule": evidence["slack-limits"]["text"]}], evidence, "slack-limits")
    area = json.loads(command(hub.root, "area-context", "payments", "refunds"))
    inline = json.dumps(area.get("inline_entries", []))
    yield "lookup", "qualified area returns its tagged Stripe guidance", area_entry["interpretation"] in inline, payments
    yield "lookup", "same-named sibling area stays out", (
        other not in inline and other_entry["interpretation"] not in inline
    ), other
    available = json.dumps(area)
    yield "lookup", "lookup includes inherited company guidance", company in available and company_rule in available, (
        "Product parent links to the company policy on customer commitments"
    )

    case = "Draft a support reply for a further $55 after $70 was refunded on a $120 Stripe charge."
    for event, extra in (
        ("UserPromptSubmit", {"session_id": "payments", "prompt": case}),
        ("UserPromptSubmit", {"session_id": "switched", "prompt": "Draft a plan for Slack conversations.history."}),
        ("UserPromptSubmit", {"session_id": "switched", "prompt": "Switch to Stripe refunds. " + case}),
    ):
        result = hook(hub, event, **extra)
        prompt = extra["prompt"]
        slack_task = prompt.startswith("Draft a plan")
        required_text = evidence["slack-limits"]["text"] if slack_task else refund
        excluded_text = refund if slack_task else evidence["slack-limits"]["text"]
        passed = result.returncode == 0 and required_text in result.stdout and excluded_text not in result.stdout
        detail = result.stderr.strip() if result.returncode else "Scope-specific guidance in hook output"
        yield "lookup", f"{event} | {prompt}", passed, detail

    policy = "Escalate renewal approvals to the Cloud team."
    decoy = {"policy": {"title": "Cloud Analytics Company Quarterly Retention Policy", "date": "undated",
                        "url": "https://example.test/retention", "text": policy}}
    capture(hub, "context/products/cloud/overview.md",
            [{"scope": "product", "product": "cloud", "topic": "constraints", "rule": policy}], decoy, "policy")
    analytics_rule = "Analytics renewal approvals go to the analytics owner."
    decoy["policy"]["text"] = analytics_rule
    capture(hub, "context/products/analytics/overview.md",
            [{"scope": "product", "product": "analytics", "topic": "constraints", "rule": analytics_rule}], decoy, "policy")
    for prompt, required, excluded in (
        ("Draft the Analytics quarterly retention update.", analytics_rule, policy),
        ("What about the quarterly retention policy?", analytics_rule, policy),
        ("Can you make it shorter?", analytics_rule, policy),
        ("Draft the company-wide quarterly retention update.", company_rule, policy),
    ):
        result = hook(hub, "UserPromptSubmit", session_id="explicit-scope", prompt=prompt)
        yield "lookup", prompt, result.returncode == 0 and required in result.stdout and excluded not in result.stdout, (
            "Named scope or session follow-up outranks a private source title"
        )
    result = hook(hub, "UserPromptSubmit", prompt="Draft the quarterly retention policy.")
    yield "lookup", "Unconfirmed evidence match is a scope suggestion", (
        result.returncode == 0 and "Context scope is uncertain" in result.stdout
        and analytics_rule not in result.stdout and policy not in result.stdout
    ), "Neither private rule was injected"

    note = "context/company/pricing-review.md"
    fact = "Pricing reviews occur on the first Tuesday of each quarter."
    note_source = {"pricing": {"title": "Approved pricing calendar", "date": "undated",
                               "url": "https://example.test/pricing", "text": fact}}
    capture(hub, note, [{"scope": "company", "record": {"path": note, "parent": company,
            "basis": "maintained-reference", "reason": "Keep the review calendar together.",
            "trigger": "The review calendar changes."}}], note_source, "pricing")
    for prompt in (f"Use {note} to answer when the reviews occur.", "When are company-wide pricing reviews?"):
        result = hook(hub, "UserPromptSubmit", prompt=prompt)
        yield "lookup", prompt, result.returncode == 0 and fact in result.stdout, "Retrieved the company reference note"

    custom = "Ask the analytics owner to review the account cohort before sharing it."
    decoy["policy"]["text"] = custom
    analytics = "context/products/analytics/overview.md"
    capture(hub, analytics, [{"scope": "product", "product": "analytics", "heading": "Cohort publication",
                              "lead": "Consult before publishing analytics for an account cohort.",
                              "rule": custom}], decoy, "policy")
    path = hub.work / analytics
    hidden = "Follow the deprecated exportpolicy.force rule."
    path.write_text(path.read_text().replace("## Cohort publication", f"  <!--\n- Rule: {hidden} [S1]\n  -->\n\n## Cohort publication"))
    result = hook(hub, "UserPromptSubmit", prompt="Publish the Analytics retention cohort.")
    output = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    entries = json.loads(output.splitlines()[-1])["entries"]
    yield "lookup", "Custom rules apply and hidden rules stay out", (
        pm.check(hub.root) == [] and hidden not in output and any(custom in row["text"] and row["binding"] for row in entries)
    ), "Only visible, sourced rules apply to the scoped task"
    result = hook(hub, "UserPromptSubmit", prompt="Update exportpolicy.force.")
    yield "lookup", "Hidden identifiers cannot select private scope", (
        result.returncode == 0 and custom not in result.stdout and analytics not in result.stdout
    ), "The commented identifier was unavailable to scope resolution"
    hidden_source = "| S90 | [PayPal rates](https://docs.paypal.com/rates) | undated | 2026-01-01 |"
    path.write_text(path.read_text().replace("## Work state", f"<!--\n{hidden_source}\n-->\n\n## Work state", 1))
    result = hook(hub, "UserPromptSubmit", prompt="Check PayPal rates.")
    yield "lookup", "Hidden sources cannot select private scope", (
        result.returncode == 0 and custom not in result.stdout and analytics not in result.stdout
    ), "The commented source provider was unavailable to scope resolution"

    bad_reply = "You can receive the additional $55 now."
    result = hook(hub, "Stop", session_id="payments", last_assistant_message=bad_reply)
    output = json.loads(result.stdout)
    retry = hook(hub, "Stop", session_id="payments", last_assistant_message="The amount remaining is $50.",
                 stop_hook_active=True)
    yield "application", "scoped refund reply receives a bounded review", (
        result.returncode == 0 and output.get("decision") == "block" and company in output.get("reason", "")
        and retry.returncode == 0 and json.loads(retry.stdout) == {}
    ), "Stop requests context and arithmetic review once for a simulated reply above the remaining $50"

    chrome = "context/products/chrome/overview.md"
    proposal = evidence["chrome-proposal"]["text"]
    accepted = evidence["chrome-decision"]["text"]
    entry = {"scope": "product", "product": "chrome"}
    capture(hub, chrome, [dict(entry, topic="constraints", interpretation=proposal)], evidence, "chrome-proposal")
    prompt = {"prompt": "Update the Chrome partner plan's cookie-choice dependency."}
    before = hook(hub, "UserPromptSubmit", session_id="chrome-before", **prompt)
    decision = {"question": "Will Chrome introduce a standalone cookie prompt?", "scope": "Chrome cookie choice",
                "person": "Anthony Chavez", "date": "2025-04-22", "next_step": "Use the existing settings path."}
    capture(hub, chrome, [dict(entry, topic="decisions", decision=decision)], evidence, "chrome-decision")
    view = (hub.work / chrome).read_text()
    yield "control", "proposal and accepted decision retain their separate roles", (
        proposal in (records.section(view, "Constraints") or "")
        and accepted in (records.section(view, "Decisions already closed") or "")
    ), "The public decision and the historical proposal are both recoverable"
    after = hook(hub, "UserPromptSubmit", session_id="chrome-after", **prompt)
    yield "feedback", "fresh task reflects the newly filed Chrome decision", (
        before.returncode == after.returncode == 0 and proposal in before.stdout
        and accepted not in before.stdout and accepted in after.stdout
    ), "Same task in fresh sessions before and after capture"

    review = "workspace/initiatives/ground-navigation/outcome-review.md"
    review_path = hub.work / review
    review_path.parent.mkdir(parents=True, exist_ok=True)
    rule = "Verify the impulse units end to end before accepting a trajectory data handoff."
    report = evidence["nasa-final"]
    review_path.write_text(
        "# Ground navigation outcome review\n\n"
        "## Scope\n\nTrajectory data handoffs.\n\n"
        "## Evidence\n\n"
        f"{report['text']}\n\n"
        f"Source is the [NASA Phase I report]({report['url']}).\n\n"
        f"## Next action\n\n{rule}\n"
    )
    navigation = "context/products/navigation/overview.md"
    source = {"review": {"title": "Ground navigation outcome review", "date": "undated", "text": rule,
                         "reference": f"[Ground navigation outcome review]({review})"}}
    original_review = review_path.read_bytes()
    written = capture(hub, navigation, [{"scope": "product", "product": "navigation", "topic": "constraints",
                                         "rule": rule}], source, "review")
    rendered = (hub.work / navigation).read_text()
    yield "feedback", "workspace learning is captured with its original source", (
        written == navigation and rule in rendered and f"/{review}" in rendered
        and review_path.read_bytes() == original_review and pm.check(hub.root) == []
    ), "Route an accepted workspace outcome into navigation context and follow the backlink"
    next_task = hook(hub, "UserPromptSubmit", session_id="nasa-fresh",
                     prompt="Review the ground navigation impulse data handoff for release.")
    yield "feedback", "fresh task receives the workspace-derived release rule", (
        next_task.returncode == 0 and rule in next_task.stdout
    ), "Fresh navigation task after the outcome review was captured"

    first_rule = "Use the July proposal as the provisional planning dependency."
    replacement = "Use existing Chrome settings as the planning dependency."
    first = dict(entry, topic="constraints", rule=first_rule)
    capture(hub, chrome, [first], evidence, "chrome-proposal")
    marked = dict(entry, topic="constraints", rule=replacement,
                  supersedes={"source": "S1", "entry": first_rule})
    capture(hub, chrome, [marked], evidence, "chrome-decision")
    current = command(hub.root, "task-context", "--product", "chrome", "Review the planning dependency.")
    historical = command(hub.root, "task-context", "--product", "chrome", "Review as of August 1, 2024.")
    yield "feedback", "superseded context is retained and applied by date", (
        first_rule in (hub.work / chrome).read_text() and first_rule not in current
        and replacement in current and first_rule in historical and replacement not in historical
    ), "Apply the approved replacement now and keep the earlier rule for dated historical work"

    for product in ("payments", "slack-imports"):
        destination = f"context/products/{product}/initiatives/returns/overview.md"
        initiative = {"scope": "initiative", "product": product, "initiative": "returns", "topic": "outcome",
                      "question": f"What does the {product} returns effort change?"}
        capture(hub, destination, [initiative])
    current = command(hub.root, "task-context", "--product", "payments", "--initiative", "returns")
    yield "lookup", "same initiative slug works across products", (
        "payments/initiatives/returns/overview.md" in current and "slack-imports/initiatives/returns/overview.md" not in current
    ), "Both independent initiative briefs are writable and the resolver selects the correct owner"

    claim = "Revenue is up 10%."
    claims = {"reported": {"title": "Fixture executive update", "date": "undated",
                           "url": "https://example.test/update", "text": claim}}
    capture(hub, payments, [{"scope": "product", "product": "payments", "topic": "goals"}], claims, "reported")
    numeric = hook(hub, "UserPromptSubmit", session_id="numeric", prompt="Is revenue up 10%?")
    yield "numeric", "bare growth claim stays reported and prompts validation", (
        "- Reported metric: " + claim in (hub.work / payments).read_text()
        and numeric.returncode == 0 and "playbook/numbers.md" in numeric.stdout
    ), "The source claim remains available without being asserted as a verified result"


def numeric_checks(root):
    common = {"definition": "Net recognized revenue", "population": "Same business units", "unit": "CAD",
              "basis": "calendar month", "timezone": "America/Toronto", "source": "Fixture close", "complete": True}
    june = dict(common, start="2026-06-01", end="2026-07-01", value=100)
    july = dict(common, start="2026-07-01", end="2026-08-01", value=110)
    rate = dict(common, start="2026-06-01", end="2026-07-01", unit="percent", numerator=100, denominator=1100,
                definition="Stripe subscriber churn", population="Stripe eligible subscribers", basis="rolling 30 days",
                denominator_basis="Active at start plus new subscribers", numerator_subset=True,
                source="https://docs.stripe.com/billing/subscriptions/analytics#subscriber-churn-rate")
    cases = [
        ("matched closed months", {"kind": "growth", "current": july, "baseline": june, "reported": 10}, None),
        ("partial month versus full", {"kind": "growth", "current": dict(july, end="2026-07-20", complete=False),
                                       "baseline": june, "reported": 10}, "period is complete"),
        ("same numbers, different currency", {"kind": "growth", "current": dict(july, unit="USD"),
                                              "baseline": june}, "unit differ"),
        ("revenue definition changed", {"kind": "growth", "current": dict(july, definition="Billed revenue"),
                                        "baseline": june}, "definition differ"),
        ("growth from zero", {"kind": "growth", "current": july, "baseline": dict(june, value=0)}, "nonpositive"),
        ("Stripe documented denominator", {"kind": "proportion", "current": rate, "reported": "9.1"}, None),
        ("incorrect Stripe churn percentage", {"kind": "proportion", "current": rate, "reported": "10.0"},
         "does not match"),
        ("churn populations cannot be compared", {"kind": "percentage_points",
                                                  "current": dict(july, unit="percent", value=9.1,
                                                                  definition=rate["definition"]),
                                                  "baseline": dict(june, unit="percent", value=10,
                                                                   definition="Paid starting-cohort-only churn")},
         "definition differ"),
        ("churn event outside the eligible cohort", {"kind": "proportion",
                                                      "current": dict(rate, numerator_subset=False)}, "eligible"),
        ("no eligible churn denominator", {"kind": "proportion",
                                           "current": dict(rate, numerator=0, denominator=0)}, "positive denominator"),
    ]
    for label, payload, issue in cases:
        proc = subprocess.run([sys.executable, "-B", str(root / "tools/pm.py"), "check-metric"],
                              input=json.dumps(payload), text=True, capture_output=True, timeout=30)
        result = json.loads(proc.stdout)
        detail = " | ".join(result["issues"])
        if issue is None:
            expected = 10 if payload["kind"] == "growth" else 9.1
            passed = proc.returncode == 0 and round(float(result["value"]), 1) == expected
        else:
            passed = proc.returncode == 1 and issue in detail
        yield "numeric", label, passed, detail or result["value"]


def typed_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(typed_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def score(case, result, evidence):
    required, forbidden = set(case["required"]), set(case["forbidden"])

    def source_ids(field):
        values = result.get(field)
        if not isinstance(values, list) or any(not isinstance(value, str) or value not in evidence for value in values):
            return False, set()
        ids = set(values)
        return len(ids) == len(values) and ids <= set(case["context"]), ids

    valid_retrieval, retrieved = source_ids("retrieved")
    valid_application, used = source_ids("used")
    facts = result.get("facts")
    return {
        "retrieval": valid_retrieval and required <= retrieved and not (forbidden & retrieved),
        "evidence_used": valid_application and required <= used <= retrieved and not (forbidden & used),
        "decision": result.get("decision") == case["decision"],
        "facts": isinstance(facts, dict) and set(facts) == set(case["facts"]) and all(
            typed_equal(facts[key], expected) for key, expected in case["facts"].items()
        ),
        "artifact_review": result.get("artifact_applies_decision") is True,
    }


def stress_scorer(cases, evidence):
    trials = []
    for case in cases:
        good = {
            "retrieved": case["required"], "used": case["required"], "decision": case["decision"],
            "facts": case["facts"], "artifact_applies_decision": True,
        }
        trials.append(all(score(case, good, evidence).values()))
        for change in (
            {"decision": "wrong_decision"},
            {"facts": {key: None for key in case["facts"]}},
            {"artifact_applies_decision": False},
            {"retrieved": ["unregistered-source"]},
            {"used": ["unregistered-source"]},
        ):
            trials.append(not all(score(case, dict(good, **change), evidence).values()))
        if case["required"]:
            trials.append(not score(case, dict(good, retrieved=[]), evidence)["retrieval"])
            trials.append(not score(case, dict(good, used=[]), evidence)["evidence_used"])
        for decoy in case["forbidden"]:
            trials.append(not score(case, dict(good, retrieved=good["retrieved"] + [decoy]), evidence)["retrieval"])
            trials.append(not score(case, dict(good, used=good["used"] + [decoy]), evidence)["evidence_used"])
        for key, value in case["facts"].items():
            if type(value) is bool:
                trials.append(not score(case, dict(good, facts=dict(case["facts"], **{key: int(value)})), evidence)["facts"])
    return sum(trials), len(trials)


def prompts(cases, evidence, include_context):
    return [
        {"id": case["id"], "task": f"Deliver a {case['artifact']}. {case['prompt']}",
         "available_evidence": {key: evidence[key] for key in case["context"]} if include_context else {}}
        for case in cases
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prompts", choices=("provided", "withheld"))
    mode.add_argument("--grade", type=Path, help="JSON results keyed by case ID")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if a probe or graded case fails")
    args = parser.parse_args()
    data = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    evidence, cases = data["evidence"], data["cases"]
    if args.prompts:
        print(json.dumps(prompts(cases, evidence, args.prompts == "provided"), indent=2, ensure_ascii=False))
        return 0
    if args.grade:
        results = json.loads(args.grade.read_text(encoding="utf-8"))
        if not isinstance(results, dict) or set(results) - {case["id"] for case in cases}:
            parser.error("Use a JSON object keyed by known case ID")
        total, passed = len(cases), 0
        for case in cases:
            result = results.get(case["id"])
            if not isinstance(result, dict):
                print(f"UNRUN {case['id']}")
                continue
            scores = score(case, result, evidence)
            passed += all(scores.values())
            print(case["id"], json.dumps(scores))
    else:
        hub = HubTests()
        try:
            hub.setUp()
            reviewed_studio(hub.root, hub.work)
            results = [*checks(hub, evidence), *numeric_checks(hub.root)]
        finally:
            hub.doCleanups()
        for category, label, passed, detail in results:
            print(f"{'PASS' if passed else 'MISS'} {category} | {label} | {detail}")
        passed, total = sum(item[2] for item in results), len(results)
        good, trials = stress_scorer(cases, evidence)
        print(f"Grader controls: {good}/{trials} correct. Prepared workspace prompts: {len(cases)}.")
        if good != trials:
            return 2
    print(f"Passed: {passed}/{total}.")
    return int(args.strict and passed != total)


if __name__ == "__main__":
    raise SystemExit(main())
