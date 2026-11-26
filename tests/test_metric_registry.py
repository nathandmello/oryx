"""Verify metric definitions through the Hub's user-facing commands."""

from datetime import date, timedelta
from decimal import Decimal
import json
import subprocess
import sys
import unittest

import test_opportunities
import metric_checks


class MetricRegistryTests(unittest.TestCase):
    Fixture = test_opportunities.InitiativeTests
    setUp = Fixture.setUp
    write_legacy_register = Fixture.write_legacy_register
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

    def test_company_id_is_explicit_and_scenarios_keep_their_approved_basis(self):
        self.cli("metric", "show", "company.logo-churn", error="Choose a metric ID")
        missing = json.loads(self.cli("task-context", "--product", "example", "Use company.logo-churn for paid customer churn."))
        self.assertFalse(missing.get("metrics"))
        self.assertTrue(any("No approved definition of company.logo-churn" in warning for warning in missing["warnings"]))
        request = self.change("Finance decision 4", "Beginning paid contracts.")
        self.cli("metric", "set", "company.logo-churn", "--product", "example", value=request, error="Omit --product")
        self.cli("metric", "set", "logo-churn", "--write", value=request)
        official = self.definition(metric="company.logo-churn")
        self.assertEqual(official["revision"], self.definition()["revision"])
        self.assertEqual((official["approved_by"], official["source"], official["origin"]),
                         ("Fixture Finance owner", "Finance decision 4", "local"))
        self.cli("metric", "show", "company.logo-churn", "--as-of", "2025-06-30", error="Choose a metric ID")
        product = self.change("Product decision", "Opening accounts in the trial.", "2025-08-01")
        self.cli("metric", "set", "logo-churn", "--product", "example", "--write", value=product)
        self.assertNotEqual(self.definition("--product", "example")["denominator"], official["denominator"])
        self.assertEqual(self.definition("--product", "example", metric="company.logo-churn"), official)
        scenario = dict(self.change("PM planning review", "Customers under annual contracts.", "2025-08-02"),
                        based_on="company.logo-churn")
        self.cli("metric", "set", "scenario.annual", value=scenario, error="own display name")
        scenario["changes"]["name"] = "Annual-contract churn sensitivity"
        self.cli("metric", "set", "scenario.annual", "--product", "example", "--write", value=scenario)
        variant = self.definition("--product", "example", metric="scenario.annual")
        self.assertEqual((variant["based_on"], variant["authority"]), (official["reference"], "scenario"))
        self.assertEqual(variant["formula"], official["formula"])
        self.assertFalse(json.loads(self.cli("metric", "set", "scenario.annual", "--product", "example", "--write",
                                             value=scenario))["written"])
        self.cli("metric", "show", "scenario.annual", "--product", "elsewhere", error="Choose a metric ID")
        for prompt, expected in [("Report paid customer churn.", {"logo-churn"}),
                                 ("Report paid customer churn using company.logo-churn.", {"company.logo-churn"}),
                                 ("Use scenario.annual for paid customer churn.", {"scenario.annual"}),
                                 ("Model Annual-contract churn sensitivity.", {"scenario.annual"}),
                                 ("Compare company.logo-churn and scenario.annual.", {"company.logo-churn", "scenario.annual"})]:
            with self.subTest(prompt=prompt):
                ctx = json.loads(self.cli("task-context", "--product", "example", prompt))
                self.assertEqual({row["metric"] for row in ctx["metrics"]}, expected)
        self.cli("metric", "set", "company.logo-churn", "--write",
                 value=self.change("Finance decision 5", "Opening prepaid contracts.", "2025-09-01"))
        self.assertEqual(self.definition("--product", "example", metric="scenario.annual"), variant)
        self.assertEqual(self.definition("--as-of", "2025-08-31", metric="company.logo-churn"), official)

    def test_qualified_company_evidence_survives_product_and_company_changes(self):
        official = json.loads(self.cli("metric", "set", "company.logo-churn", "--write",
                                       value=self.change("Finance policy", "All paid accounts.")))["proposed"]
        self.submit(self.setup_event(), self.capture(), {"type": "metric", "metric": "official-churn",
                                                        "registry_metric": "company.logo-churn"})
        signed = self.ledger.read_bytes()
        self.preview({"type": "metric", "metric": "duplicate-churn", "registry_metric": "logo-churn"},
                     error="Reuse the existing")
        self.cli("metric", "set", "logo-churn", "--product", "example", "--write",
                 value=self.change("Billing exception", "Paid accounts with active usage.", "2025-08-01"))
        self.preview(dict(self.target(), metric="official-churn"))
        self.preview({"type": "metric", "metric": "product-churn", "registry_metric": "logo-churn"})
        observation = {"definition": official["reference"], "population": official["population"], "unit": "percent",
                       "start": "2025-08-01", "end": "2025-09-01", "basis": "calendar month", "complete": True,
                       "timezone": "UTC", "source": "Finance ledger", "numerator": 3, "denominator": 10,
                       "numerator_subset": True, "denominator_basis": official["denominator"]}
        payload = {"metric": "company.logo-churn", "product": "example", "kind": "proportion", "current": observation}
        checked = json.loads(self.cli("check-metric", value=payload))
        self.assertEqual(checked["definition_provenance"]["current"]["source"], "Finance policy")
        self.assertEqual(checked["value"], "30")
        self.cli("check-metric", value=dict(payload, metric="logo-churn"), error="definition differs")
        self.cli("metric", "set", "company.logo-churn", "--write",
                 value=self.change("New Finance policy", "Starting paid contracts.", "2025-09-15"))
        self.assertEqual(json.loads(self.cli("check-metric", value=payload))["metric_reference"], official["reference"])
        self.assertEqual(self.ledger.read_bytes(), signed)
        trace = json.loads(self.cli("initiative", "show", "example"))
        self.assertEqual(trace["metrics"]["official-churn"]["contract"], official)
        self.assertEqual(trace["current_metric_registry"]["official-churn"]["source"], "New Finance policy")
        self.preview(dict(self.target(), metric="official-churn"), error="under a new metric ID")

    def test_new_company_revenue_and_an_independent_forecast(self):
        revenue = {"approved_by": "Controller", "source": "Policy revision 6", "effective_on": "2025-01-01",
                   "changes": {"name": "Recognized revenue", "aliases": ["revenue"], "unit": "currency",
                               "definition": "Revenue recognized for completed services.", "formula": "Sum posted net lines.",
                               "population": "Settled customer invoices.", "period": "One closed calendar month.",
                               "denominator": "none", "notes": "Exclude deferred revenue and sales tax."}}
        self.cli("metric", "set", "company.revenue", "--write", value=revenue)
        official = self.definition(metric="company.revenue")
        self.assertEqual(official["revision"], self.definition(metric="revenue")["revision"])
        self.assertEqual(official["reference"], "company.revenue@" + official["revision"])
        scenario = {"approved_by": "Planning PM", "source": "Upside forecast", "effective_on": "2025-01-10",
                    "based_on": "company.revenue", "changes": {"name": "Upside revenue",
                                                              "formula": "Add likely renewals to recognized sales."}}
        self.cli("metric", "set", "scenario.upside", "--write", value=scenario)
        self.cli("metric", "set", "company.revenue", "--write", value=scenario, error="named scenario")
        self.cli("metric", "set", "scenario.upside", "--write", value=dict(scenario, based_on="scenario.upside"),
                 error="different definition")
        self.submit(self.setup_event(), self.capture(),
                    {"type": "metric", "metric": "revenue", "registry_metric": "company.revenue"},
                    {"type": "metric", "metric": "forecast", "registry_metric": "scenario.upside"})
        signed = self.ledger.read_bytes()
        self.cli("metric", "set", "scenario.upside", "--write",
                 value={"approved_by": "Planning PM", "source": "Quarter-end sensitivity", "effective_on": "2025-02-01",
                        "changes": {"formula": "Add contracted renewals only."}})
        self.assertEqual(self.ledger.read_bytes(), signed)
        self.assertEqual(self.definition(metric="company.revenue"), official)
        trace = json.loads(self.cli("initiative", "show", "example"))["metrics"]
        self.assertEqual(trace["revenue"]["contract"]["revision"], official["revision"])
        self.assertEqual(trace["forecast"]["contract"]["based_on"], official["reference"])
        self.assertEqual(trace["forecast"]["contract"]["formula"], scenario["changes"]["formula"])

    def test_two_studios_can_apply_the_same_finance_file(self):
        other = self.Fixture()
        other.setUp()
        self.addCleanup(other.doCleanups)
        approval = {"approved_by": "Controller", "source": "Finance decision 16", "effective_on": "2025-03-01",
                    "changes": {"name": "Revenue", "aliases": ["recognized sales"], "unit": "currency",
                                "definition": "Revenue recognized during the month.", "formula": "Sum posted sales.",
                                "population": "Posted general ledger entries.", "period": "One closed calendar month.",
                                "denominator": "none", "notes": "Exclude tax and deferred revenue."}}
        finance_file = self.parent / "finance.json"
        finance_file.write_text(json.dumps(approval), encoding="utf-8")
        other.cli("metric", "set", "company.revenue", "--write",
                  value=dict(approval, effective_on="2025-01-01",
                             changes=dict(approval["changes"], period="Reported each Friday.", reporting_window="week")))
        for studio in (self, other):
            formula = "Invoiced product lines." if studio is self else "Recognized product sales."
            studio.cli("metric", "set", "revenue", "--product", "example", "--write",
                       value=dict(approval, effective_on="2024-12-01", changes=dict(approval["changes"], formula=formula)))
        self.cli("metric", "set", "scenario.expansion", "--product", "example", "--write",
                 value=dict(approval, effective_on="2025-02-01", based_on="revenue",
                            changes={"name": "Expansion forecast", "formula": "Include planned expansion."}))
        variant = self.definition("--product", "example", metric="scenario.expansion")
        for studio in (self, other):
            with finance_file.open(encoding="utf-8") as data:
                run = subprocess.run([sys.executable, str(studio.root / "tools/pm.py"), "metric", "set",
                                      "company.revenue", "--write"], stdin=data, cwd=studio.work, env=studio.env,
                                     text=True, capture_output=True, check=True)
            self.assertTrue(json.loads(run.stdout)["written"])
        official = self.definition(metric="company.revenue")
        self.assertNotIn("reporting_window", official)
        for studio, change in ((self, "Invoiced product lines."), (other, "Recognized product sales.")):
            active = json.loads(studio.cli("metric", "show", "revenue", "--product", "example"))
            self.assertEqual(active["formula"], change)
            self.assertEqual(json.loads(studio.cli("metric", "show", "company.revenue", "--product", "example")), official)
        other.cli("metric", "show", "scenario.expansion", "--product", "example", error="Choose a metric ID")
        self.assertEqual(self.definition("--product", "example", metric="scenario.expansion"), variant)

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

    def test_check_metric_uses_the_approved_legacy_window(self):
        request = self.change("Activation measurement review", "Eligible trial accounts.", "2024-01-01")
        request["changes"]["period"] = "One closed calendar month."
        self.cli("metric", "set", "logo-churn", "--product", "example", "--write", value=request)
        definition = self.definition("--product", "example")
        monthly = {
            "definition": definition["reference"], "population": definition["population"], "unit": "percent",
            "basis": "calendar month", "start": "2024-02-01", "end": "2024-03-01", "complete": True,
            "timezone": "UTC", "source": "February reconciled cohort", "numerator": 9, "denominator": 100,
            "denominator_basis": definition["denominator"], "numerator_subset": True,
        }
        payload = {"metric": "logo-churn", "product": "example", "kind": "proportion", "current": monthly}
        report = json.loads(self.cli("check-metric", value=payload))
        self.assertEqual(report["approved_reporting_windows"], {"current": "calendar month"})
        self.assertEqual(report["value"], "9")
        daily = dict(monthly, start="2024-02-29", basis="day")
        result = json.loads(self.cli("check-metric", value=dict(payload, current=daily), error="approved reporting window"))
        self.assertEqual(result["status"], "needs_review")
        short = dict(monthly, end="2024-02-29")
        self.cli("check-metric", value=dict(payload, current=short), error="calendar month boundaries")
        incomplete = dict(monthly, complete=False)
        self.cli("check-metric", value=dict(payload, current=incomplete), error="period is complete")

    def test_typed_reporting_window_checks_both_periods_and_preserves_history(self):
        legacy = self.definition(metric="mrr")
        request = {
            "changes": {"period": "Report the end-of-month recurring revenue run rate.",
                        "reporting_window": "snapshot"},
            "approved_by": "Finance owner", "effective_on": "2025-01-01", "source": "Finance review",
        }
        self.cli("metric", "set", "mrr", "--write", value=request)
        current_definition = self.definition(metric="mrr")
        self.assertEqual(current_definition["reporting_window"], "snapshot")
        self.assertEqual(self.definition("--as-of", "2024-12-31", metric="mrr"), legacy)
        current = {
            "definition": current_definition["reference"], "population": current_definition["population"],
            "unit": "USD/month", "basis": "snapshot", "start": "2025-02-28", "end": "2025-03-01",
            "complete": True, "timezone": "UTC", "source": "Posted revenue ledger", "value": 110,
        }
        baseline = dict(current, start="2025-01-31", end="2025-02-01", value=100)
        payload = {"metric": "mrr", "kind": "growth", "current": current, "baseline": baseline}
        report = json.loads(self.cli("check-metric", value=payload))
        self.assertEqual(report["value"], "10")
        self.assertEqual(report["approved_reporting_windows"], {"current": "snapshot", "baseline": "snapshot"})
        daily = dict(payload, current=dict(current, basis="day"), baseline=dict(baseline, basis="day"))
        invalid = json.loads(self.cli("check-metric", value=daily, error="approved reporting window"))
        self.assertEqual(len(invalid["issues"]), 2)
        future_start = date.today() + timedelta(days=1)
        future = dict(current, start=future_start.isoformat(), end=(future_start + timedelta(days=1)).isoformat())
        self.cli("check-metric", value=dict(payload, current=future), error="window includes dates after")
        premature = dict(current, start="2025-02-27")
        self.cli("check-metric", value=dict(payload, current=premature), error="snapshot basis")

        different_period = dict(request, effective_on="2025-05-01",
                                changes={"period": "Report as of a product-specific cutoff."})
        self.cli("metric", "set", "mrr", value=different_period, error="confirm reporting_window")
        conflict = dict(different_period, changes={"period": "One closed calendar month.",
                                                   "reporting_window": "snapshot"})
        self.cli("metric", "set", "mrr", value=conflict, error="differs from its stated period")
        different_period["changes"]["reporting_window"] = "instant"
        self.cli("metric", "set", "mrr", value=different_period, error="choose reporting_window")
        different_period["changes"]["reporting_window"] = None
        manual = json.loads(self.cli("metric", "set", "mrr", value=different_period))["proposed"]
        self.assertNotIn("reporting_window", manual)

    def test_reading_helpers_use_pinned_metadata_and_the_recorded_date(self):
        definition = self.definition(metric="nrr")
        reading = {
            "definition": definition["reference"], "population": definition["population"], "unit": "percent",
            "basis": "calendar month", "start": "2025-02-01", "end": "2025-03-01", "complete": True,
            "timezone": "UTC", "source": "February reconciled cohort", "value": "100.01",
        }
        self.assertIsNone(metric_checks.window_basis(definition))
        self.assertEqual(metric_checks.reading_issues(reading, definition, "2025-03-01"), [])
        self.assertEqual(metric_checks.reading_value(reading), Decimal("100.01"))
        with self.assertRaisesRegex(ValueError, "finite number"):
            metric_checks.reading_value(dict(reading, value="NaN"))
        observed_early = metric_checks.reading_issues(reading, definition, "2025-02-27")
        self.assertIn("The reading window includes dates after 2025-02-27.", observed_early)
        approved_later = metric_checks.reading_issues(reading, dict(definition, effective_on="2025-03-01"), "2025-03-03")
        self.assertIn("The approved definition was not effective by the reading cutoff.", approved_later)
        invalid = metric_checks.reading_issues(dict(reading, population="Internal tenant cohort", unit="count"),
                                               definition, "2025-03-01")
        self.assertTrue(any("population differs" in issue for issue in invalid))
        self.assertTrue(any("unit" in issue for issue in invalid))

    def test_approved_snapshot_survives_a_definition_change(self):
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

    def test_legacy_signed_metric_can_adopt_a_registry_definition(self):
        self.submit(self.setup_event(), self.capture())
        payload = json.loads(self.ledger.read_text())["record"]
        old = {"type": "metric", "metric": "customer-loss", "name": "Paid customer churn", "unit": "percent",
               "definition": "Customers lost divided by all customers", "source": "Prior signed finance definition"}
        payload["events"].append(old)
        self.write_legacy_register(payload)
        before = self.ledger.read_bytes()
        self.preview(dict(self.target(), metric="customer-loss"), error="under a new metric ID")
        self.assertEqual(self.ledger.read_bytes(), before)
        proposal = self.preview({"type": "metric", "metric": "customer-loss-v2", "registry_metric": "logo-churn"},
                                dict(self.target(), metric="customer-loss-v2"))
        self.apply(proposal)
        trace = json.loads(self.cli("initiative", "show", "example"))
        self.assertEqual(trace["metrics"]["customer-loss"], old)
        self.assertIn(self.definition()["reference"], trace["metrics"]["customer-loss-v2"]["source"])
        self.assertEqual(json.loads(self.ledger.read_text())["record"]["events"][:len(payload["events"])], payload["events"])
