"""Scoped activity prerequisites reach the CLI and both registered prompt hooks."""

import unittest

import test_context_search
import test_conversation
import test_pm
from onboarding_fixtures import reviewed_studio
import context_capture
import layout
import records
import task_context


class StrategyPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.hub = test_context_search.RetrievalTests()
        self.hub.setUp()
        self.addCleanup(self.hub.doCleanups)
        self.hub.add("products/billing/overview", "Billing", "Operators reconcile accounts.", kind="product-context")

    def strategy(self, prompt):
        return task_context.turn_context(self.hub.private, prompt, explicit={"product": "billing"})[0]

    def test_strategy_authoring_checks_company_outcome_but_routine_work_does_not(self):
        for prompt in ("Help me work on product strategy.", "Could you revise our Billing strategy?",
                       "Help me with product strategy.", "I'm working on our product strategy.",
                       "/pm strategy brief draft workspace/strategies/billing.md"):
            with self.subTest(prompt=prompt):
                check = self.strategy(prompt)["activity_check"]
                self.assertEqual(check["status"], "clarify_if_unknown")
                self.assertIn("company outcome", check["question_if_unclear"])
        for prompt in ("Show me our Billing strategy.", "Draft the roadmap.", "Who wrote the strategy?",
                       'The transcript says "draft a product strategy".'):
            self.assertNotIn("activity_check", self.strategy(prompt))

    def test_product_facts_and_unresolved_company_claims_cannot_establish_an_objective(self):
        path = self.hub.private / "context/company/overview.md"
        goal = "Winning renewals is the company's approved objective for this period."
        company = path.read_text().replace("## Sources", "## Direction and goals\n\n- Fact: " + goal +
                                           " [S1]\n  Open question at capture: Is that priority approved?\n\n## Sources")
        path.write_text(company)
        check = self.strategy("Draft the product strategy.")["activity_check"]
        self.assertEqual(check["evidence_sections"], [])
        path.write_text(company.replace("  Open question at capture: Is that priority approved?\n", ""))
        result = self.strategy("Draft the product strategy.")
        check = result["activity_check"]
        self.assertEqual(check["status"], "check_source_and_scope")
        self.assertEqual(check["evidence_sections"], ["Direction and goals"])
        self.assertTrue(any(goal in row["text"] and row["sources"] for row in result["entries"]))
        self.assertIn("applies to this product", check["next_action"])


class OutcomeAssessmentTests(unittest.TestCase):
    cli = test_conversation.ConversationTests.cli
    turn = test_conversation.ConversationTests.turn
    prompt = test_conversation.ConversationTests.prompt
    criterion = "For the ten pilot merchants, we agreed success means fewer refund-status contacts per merchant."
    adoption = "For the pilot, we also agreed to measure weekly adoption of self-service refunds."
    evidence = "Status contacts per pilot merchant fell from six in July to four in August."
    sibling_criterion = "The Receipts team measures success by email delivery time."
    parent_criterion = "The Payments team agreed to measure authorization rate across all merchants."

    def setUp(self):
        test_pm.HubTests.setUp(self)
        self.cwd = self.root
        records.create(self.root, "company-context", layout.COMPANY)
        self.payments = records.create(self.root, "product-context", layout.product("payments"), "Payments")
        self.refunds = records.create(self.root, "product-area-context", layout.area("payments", "refunds"), "Refunds")
        receipts = records.create(self.root, "product-area-context", layout.area("payments", "receipts"), "Receipts")
        self.populate(self.payments, "Goals, performance, and gaps", self.parent_criterion)
        self.populate(receipts, "Area outcomes", self.sibling_criterion)

    def populate(self, path, heading, *statements):
        body = "\n".join(f"- Fact: {statement} [S1]" for statement in statements)
        text = context_capture.edit_section(path.read_text(), heading, body)
        sources = ("| ID | Source | Source date | Checked on |\n| --- | --- | --- | --- |\n"
                   f"| S1 | {path.parent.name.title()} operating review | 2025-09-01 | 2025-09-01 |")
        path.write_text(context_capture.edit_section(text, "Sources", sources))

    def test_both_clients_reuse_the_area_measure_and_observation_after_setup(self):
        self.populate(self.refunds, "Area outcomes", self.criterion)
        self.populate(self.refunds, "Goals, performance, and gaps", self.evidence)
        original = self.refunds.read_bytes()
        query = "Did Refunds get better?"
        for client in ("Codex", "Claude"):
            pending, _ = self.prompt(client, "before-setup", query)
            self.assertEqual(pending["status"], "onboarding_required")
            self.assertNotIn("activity_check", pending)
        reviewed_studio(self.root, self.work)

        expected = self.cli("task-context", query)
        self.assertEqual(expected["scope"]["product"], "payments")
        self.assertEqual(expected["scope"]["area"], "refunds")
        self.assertEqual(expected["activity_check"]["activity"], "outcome-assessment")
        self.assertEqual(expected["activity_check"]["status"], "check_source_and_scope")
        entries = expected["entries"]
        for statement in (self.criterion, self.evidence):
            entry = next(row for row in entries if statement in row["text"])
            self.assertEqual(entry["record"], layout.area("payments", "refunds"))
            self.assertEqual(entry["sources"][0]["Source"], "Refunds operating review")
            self.assertEqual(entry["sources"][0]["Source date"], "2025-09-01")
        self.assertNotIn(self.sibling_criterion, str(expected))
        for client in ("Codex", "Claude"):
            with self.subTest(client=client):
                result, _ = self.prompt(client, "fresh-" + client, query)
                self.assertEqual(result["scope"], expected["scope"])
                self.assertEqual(result["activity_check"], expected["activity_check"])
                self.assertEqual(result["entries"], entries)
                followup, _ = self.prompt(client, "fresh-" + client, "Did it get better?")
                self.assertEqual(followup["scope"], expected["scope"])
                self.assertEqual(followup["activity_check"]["status"], "check_source_and_scope")
                self.assertIn(self.criterion, str(followup["entries"]))
                self.assertNotIn(self.sibling_criterion, str(followup))
        self.assertEqual(self.refunds.read_bytes(), original)

        for question in ("How is Refunds doing?", "Has Refunds reduced support contacts?"):
            with self.subTest(fresh_question=question):
                result = self.cli("task-context", question)
                self.assertEqual(result["scope"], expected["scope"])
                self.assertEqual(result["activity_check"]["status"], "check_source_and_scope")
                self.assertIn(self.criterion, str(result["entries"]))

    def test_missing_outcome_is_open_despite_parent_measure_or_unresolved_area_claim(self):
        reviewed_studio(self.root, self.work)
        self.populate(self.refunds, "Area outcomes", self.criterion)
        self.refunds.write_text(self.refunds.read_text().replace(self.criterion + " [S1]",
                                self.criterion + " [S1]\n  Open question at capture: Did the team agree to this?"))
        result = self.cli("task-context", "Did Refunds get better?")
        check = result["activity_check"]
        self.assertEqual(check["status"], "clarify_if_unknown")
        self.assertFalse(check["evidence_entries"])
        self.assertIn("outcome", check["question_if_unclear"].lower())
        self.assertEqual(check["question_if_unclear"].count("?"), 1)
        self.assertNotIn(self.sibling_criterion, str(result))
        for lookup in ("Show the Refunds brief.", "How does Payments issue refunds?",
                       "Does Payments work offline?"):
            with self.subTest(lookup=lookup):
                self.assertNotIn("activity_check", self.cli("task-context", lookup))

    def test_area_name_shared_by_two_products_requires_a_scope_choice(self):
        reviewed_studio(self.root, self.work)
        self.populate(self.refunds, "Area outcomes", self.criterion)
        records.create(self.root, "product-context", layout.product("commerce"), "Commerce")
        other = records.create(self.root, "product-area-context", layout.area("commerce", "refunds"), "Refunds")
        self.populate(other, "Area outcomes", self.adoption)
        for question in ("Did Refunds get better?", "Help me think through strategy for Refunds."):
            with self.subTest(ambiguous=question):
                result = self.cli("task-context", question)
                self.assertEqual(result["status"], "ambiguous")
                self.assertIn("payments", " ".join(result["choices"]))
                self.assertIn("commerce", " ".join(result["choices"]))
                self.assertFalse(result["entries"])
                self.assertNotIn("activity_check", result)
        for question in ("Did Payments Refunds get better?", "Did Refunds get better in Payments?"):
            with self.subTest(qualified=question):
                result = self.cli("task-context", question)
                self.assertEqual(result["scope"]["product"], "payments")
                self.assertEqual(result["scope"]["area"], "refunds")
                self.assertIn(self.criterion, str(result["entries"]))
                self.assertNotIn(self.adoption, str(result))

    def test_competing_area_outcomes_keep_both_sourced_candidates_for_clarification(self):
        reviewed_studio(self.root, self.work)
        self.populate(self.refunds, "Area outcomes", self.criterion, self.adoption)
        result = self.cli("task-context", "Did Refunds get better?")
        check = result["activity_check"]
        candidates = [result["entries"][number - 1] for number in check["evidence_entries"]]
        self.assertCountEqual([row["text"] for row in candidates],
                              [f"- Fact: {text} [S1]" for text in (self.criterion, self.adoption)])
        self.assertTrue(all(row["record"] == layout.area("payments", "refunds") for row in candidates))
        self.assertEqual(check["question_if_unclear"].count("?"), 1)

    def test_question_names_a_pilot_cohort_and_its_measure(self):
        reviewed_studio(self.root, self.work)
        self.populate(self.refunds, "Goals, performance, and gaps", self.evidence)
        result = self.cli("task-context", "Did the Refunds pilot reduce status contacts?")
        self.assertEqual(result["scope"]["area"], "refunds")
        self.assertIsNone(result["scope"]["initiative"])
        self.assertIn(self.evidence, str(result["entries"]))
        self.assertEqual(result["activity_check"]["status"], "check_source_and_scope")
        self.assertNotIn(self.sibling_criterion, str(result))

    def test_area_outcome_captured_inline_in_older_product_brief_keeps_its_scope(self):
        reviewed_studio(self.root, self.work)
        self.refunds.unlink()
        self.populate(self.payments, "Goals, performance, and gaps", self.parent_criterion,
                      f"Product area refunds — {self.criterion} <!-- product-area:refunds -->",
                      f"Product area receipts — {self.sibling_criterion} <!-- product-area:receipts -->")
        result = self.cli("task-context", "Did Refunds get better?")
        check = result["activity_check"]
        self.assertEqual(check["status"], "check_source_and_scope")
        candidates = [result["entries"][number - 1] for number in check["evidence_entries"]]
        self.assertEqual(len(candidates), 1)
        self.assertIn(self.criterion, candidates[0]["text"])
        self.assertEqual(candidates[0]["record"], layout.product("payments"))
        self.assertEqual(candidates[0]["sources"][0]["Source"], "Payments operating review")


if __name__ == "__main__":
    unittest.main()
