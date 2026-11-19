"""Verify metric definitions through the Hub's user-facing commands."""

import json
import subprocess
import sys
import unittest

import test_opportunities


class MetricRegistryTests(unittest.TestCase):
    Fixture = test_opportunities.InitiativeTests
    setUp = Fixture.setUp
    make_key = Fixture.make_key
    cli = Fixture.cli
    preview = Fixture.preview
    apply = Fixture.apply
    submit = Fixture.submit
    setup_event = Fixture.setup_event
    capture = Fixture.capture
    target = Fixture.target
    company = Fixture.company
    product_context = Fixture.product_context
    today = Fixture.today

    def definition(self, *args, metric="logo-churn"):
        return json.loads(self.cli("metric", "show", metric, *args))

    @staticmethod
    def change(source, denominator, effective_on="2025-07-01"):
        return {"approved_by": "Fixture Finance owner", "effective_on": effective_on, "source": source,
                "changes": {"denominator": denominator}}

    def test_defaults_preview_and_scoped_history(self):
        definitions = json.loads(self.cli("metric", "list"))
        self.assertTrue({"mrr", "arr", "logo-churn", "nrr", "grr", "cac-payback", "ltv"} <= definitions.keys())
        default = self.definition()
        self.assertEqual(default["authority"], "industry default")
        request = self.change("June Finance approval", "Opening cohort after billing reconciliation.")
        file = self.work / "context/metrics.json"
        preview = json.loads(self.cli("metric", "set", "logo-churn", value=request))
        self.assertFalse(file.exists())
        self.assertFalse(preview["written"])
        saved = json.loads(self.cli("metric", "set", "logo-churn", "--write", value=request))
        self.assertEqual(saved["proposed"], preview["proposed"])
        self.assertEqual(self.definition()["authority"], "company")
        self.assertEqual(self.definition("--as-of", "2025-06-30")["reference"], default["reference"])
        before = file.read_bytes()
        replay = json.loads(self.cli("metric", "set", "logo-churn", "--write", value=request))
        self.assertFalse(replay["written"])
        self.assertEqual(file.read_bytes(), before)
        self.cli("metric", "set", "logo-churn", "--write",
                 value=self.change("Different approval", "Another denominator."), error="different revision")
        product = self.change("Product exception", "Opening paid accounts with recurring contracts.", "2025-08-01")
        self.cli("metric", "set", "logo-churn", "--product", "example", "--write", value=product)
        self.assertEqual(self.definition("--product", "example")["authority"], "product")
        self.assertEqual(self.definition("--product", "other")["authority"], "company")
        self.assertEqual(self.definition("--product", "example", "--as-of", "2025-07-31")["authority"], "company")
        self.assertIn("PASS", self.cli("check"))

    def test_hooks_and_arithmetic_use_the_effective_definition(self):
        default = self.definition()
        definition = self.change("PM and Finance review", "Beginning subscribers plus newly active subscribers.")
        definition["changes"].update(
            definition="Share of eligible subscribers that churn during the reporting window.",
            population="Opening subscribers and subscribers activated during the window.",
            period="Closed 30-day reporting window.",
            formula="100 × churned subscribers ÷ (beginning subscribers + new subscribers).",
            calculation="proportion",
        )
        self.cli("metric", "set", "logo-churn", "--product", "example", "--write", value=definition)
        active = self.definition("--product", "example")
        result = json.loads(self.cli("task-context", "--product", "example", "Review subscriber churn."))
        self.assertEqual(result["metrics"][0]["reference"], active["reference"])
        hook = subprocess.run([sys.executable, str(self.root / "tools/hook.py")], env=self.env, text=True,
                              input=json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
                                                "prompt": "Review product/example subscriber churn."}),
                              capture_output=True, check=True)
        self.assertIn(active["reference"], json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"])
        observation = {"definition": active["reference"], "unit": "percent", "start": "2025-07-01", "end": "2025-07-31",
                       "complete": True, "basis": "rolling 30 days", "timezone": "UTC", "source": "Billing ledger",
                       "population": active["population"], "numerator": 100, "denominator": 1100,
                       "denominator_basis": active["denominator"], "numerator_subset": True}
        payload = {"metric": "logo-churn", "product": "example", "kind": "proportion", "current": observation,
                   "reported": "9.1"}
        report = json.loads(self.cli("check-metric", value=payload))
        self.assertEqual(report["metric_reference"], active["reference"])
        wrong_cohort = dict(payload, current=dict(observation, population="New trials only"))
        self.cli("check-metric", value=wrong_cohort, error="population differs")
        observation.update(definition=default["reference"], denominator_basis=default["denominator"], denominator=1000)
        error = json.loads(self.cli("check-metric", value=payload, error="eligible denominator differs"))
        self.assertEqual(error["status"], "needs_review")

    def test_registry_operation_unit_and_period_revision(self):
        nrr = self.definition(metric="nrr")
        cac = self.definition(metric="cac")
        observation = {"definition": nrr["reference"], "population": nrr["population"], "unit": "percent",
                       "start": "2025-07-01", "end": "2025-08-01", "complete": True, "basis": "calendar month",
                       "timezone": "UTC", "source": "Billing ledger", "numerator": 120, "denominator": 100,
                       "denominator_basis": nrr["denominator"], "same_cohort": True}
        payload = {"metric": "nrr", "kind": "cohort_ratio", "current": observation, "reported": "120"}
        self.assertEqual(json.loads(self.cli("check-metric", value=payload))["value"], "120")
        self.cli("check-metric", value=dict(payload, current=dict(observation, same_cohort=False)), error="opening cohort")
        cac_observation = dict(observation, definition=cac["reference"], population=cac["population"],
                               denominator_basis=cac["denominator"], numerator=50, numerator_subset=True)
        invalid = json.loads(self.cli("check-metric", value={"metric": "cac", "kind": "proportion",
                                  "current": cac_observation}, error="approved formula"))
        self.assertTrue(any("currency/customer" in issue for issue in invalid["issues"]))

        old = self.definition()
        self.cli("metric", "set", "logo-churn", "--write", value=self.change("Finance", "Opening paid accounts."))
        new = self.definition()
        current = dict(observation, definition=new["reference"], population=new["population"], value=9)
        baseline = dict(current, start="2025-06-01", end="2025-07-01", value=8)
        payload = {"metric": "logo-churn", "kind": "percentage_points", "current": current, "baseline": baseline}
        report = json.loads(self.cli("check-metric", value=payload, error="Verify a restatement"))
        self.assertTrue(any(old["reference"] in issue for issue in report["issues"]))
        historical = dict(baseline, definition=old["reference"], population=old["population"], numerator=8,
                          denominator_basis=old["denominator"], numerator_subset=True)
        self.assertEqual(json.loads(self.cli("check-metric", value={"metric": "logo-churn", "kind": "proportion",
                                               "current": historical}))["metric_reference"], old["reference"])

    def test_signed_snapshot_survives_a_definition_change(self):
        self.submit(self.setup_event(), self.capture(), {"type": "metric", "metric": "logo-churn"})
        before = self.ledger.read_bytes()
        trace = json.loads(self.cli("initiative", "show", "example"))
        snapshot = trace["metrics"]["logo-churn"]
        self.assertIn(self.definition()["reference"], snapshot["source"])
        self.cli("metric", "set", "logo-churn", "--write",
                 value=self.change("Revised policy", "Opening paid accounts with one or more invoices."))
        self.assertEqual(self.ledger.read_bytes(), before)
        trace = json.loads(self.cli("initiative", "show", "example"))
        self.assertEqual(trace["metrics"]["logo-churn"], snapshot)
        self.assertNotIn(trace["current_metric_registry"]["logo-churn"]["reference"], snapshot["source"])
        self.preview(dict(self.target(), metric="logo-churn"), error="under a new metric ID")
        proposal = self.preview({"type": "metric", "metric": "logo-churn-v2", "registry_metric": "logo-churn"},
                                dict(self.target(), metric="logo-churn-v2"))
        self.apply(proposal)
        current = json.loads(self.cli("initiative", "show", "example", self.i))
        self.assertIn(self.definition()["reference"], current["metric_definitions"]["logo-churn-v2"]["source"])
