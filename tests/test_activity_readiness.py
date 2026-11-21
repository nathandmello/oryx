"""Company objectives are checked for strategy work at the point of use."""

import unittest

import test_context_search
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


if __name__ == "__main__":
    unittest.main()
