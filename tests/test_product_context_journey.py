"""Exercise the product walkthrough through the installed commands and registered prompt hooks."""

from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_conversation
import test_pm
import filing
import evidence_reviews
import pm
import records


class ProductContextJourneyTests(unittest.TestCase):
    cli = test_conversation.ConversationTests.cli
    turn = test_conversation.ConversationTests.turn
    prompt = test_conversation.ConversationTests.prompt
    product = "context/products/analytics/overview.md"
    plugin = "context/products/analytics/plugins/salesforce/overview.md"
    source = "PM conversation about Analytics"

    def setUp(self):
        test_pm.HubTests.setUp(self)
        self.cwd = self.root

    def cover(self, stage):
        state = self.cli("onboarding", "status")
        seen = []
        while state["stage"] == stage:
            topic = state["walkthroughs"][stage]["next_topic"]["id"]
            self.assertNotIn(topic, seen, "An open answer should allow the pass to advance")
            seen.append(topic)
            state = self.cli("onboarding", "review-topic", payload={
                "revision": state["revision"], "stage": stage, "topic": topic,
                "outcome": "open", "pm_reply": "We discussed it. Keep the rest open for now.",
                **({"subject": state["product_scope"]["subject"]} if stage == "product" else {}),
            })
        return seen

    def reach_product(self, subject):
        route, _ = self.prompt("Codex", "setup", "Help me decide what goes on the roadmap.")
        self.assertEqual(route["onboarding"]["stage"], "company")
        self.cover("company")
        roles = [dict(subject=subject, role="owner", goals=[], depends_on=[])] if subject else []
        saved = test_pm.HubTests.save_remit(self, dict(status="confirmed", responsibilities=roles, follow=[]))
        self.assertEqual(saved.returncode, 0, saved.stdout + saved.stderr)
        self.cover("pm")
        route, _ = self.prompt("Claude", "resume", "Can we get back to the roadmap?")
        stage = route["onboarding"]
        self.assertEqual(stage["stage"], "product")
        self.assertTrue(stage["stage_available"])
        if stage["product_scope"]["selection_required"]:
            self.cli("onboarding", "select-product", payload={
                "revision": stage["revision"], "subject": subject,
                "pm_reply": "Yes, that is my current scope." if subject else "I do not yet have an assigned product.",
            })

    def capture(self, operation, **fields):
        revision = self.cli("product-onboarding", "status")["revision"]
        return self.cli("product-onboarding", operation, payload=dict(revision=revision, **fields))

    def propose(self, sentence, topic, **scope):
        return self.capture("propose", source_scope=self.source,
                            sources=[dict(reference=self.source, checked_on="2026-01-08", date="2026-01-07",
                                          coverage="partial", text="Other private material. " + sentence)],
                            entries=[dict(scope="product", product="analytics", topic=topic, quote=sentence,
                                          source=1, location="Current state discussion", **scope)])

    def test_plugin_owner_captures_parent_and_plugin_then_can_use_them_in_a_fresh_session(self):
        subject = "product/analytics/area/salesforce"
        self.reach_product(subject)
        profile = self.work / "context/pm/context.md"
        original = profile.read_bytes()
        product_fact = "Analytics helps support teams understand account activity."
        area_fact = "The Salesforce plugin syncs renewal records for the pilot accounts."
        self.capture("plan", subject=subject, purpose="Record how the pilot works today.",
                     sources=[self.source], destinations=[self.product, self.plugin])
        self.capture("approve")
        self.propose(product_fact, "offer")
        self.assertFalse((self.work / self.product).is_file())
        self.capture("accept")
        self.propose(area_fact, "offer", product_area="salesforce")
        self.assertFalse((self.work / self.plugin).is_file())
        self.capture("accept")
        self.capture("finish")

        self.assertIn(product_fact, (self.work / self.product).read_text())
        self.assertNotIn(area_fact, (self.work / self.product).read_text())
        plugin = (self.work / self.plugin).read_text()
        self.assertIn(area_fact, plugin)
        self.assertIn(self.source, plugin)
        self.assertNotIn("Other private material", plugin)
        self.assertEqual(profile.read_bytes(), original)
        self.assertFalse((self.work / "context/products/analytics/areas/salesforce/overview.md").exists())
        self.cli("action", "portfolio", "roadmap", "show", error="onboarding_required")
        self.assertEqual(len(self.cover("product")), 6)
        self.assertTrue(self.cli("onboarding", "status")["ready"])

        for client in ("Codex", "Claude"):
            result, _ = self.prompt(client, client + "-fresh",
                                    "For Analytics Salesforce, what records does the plugin sync?")
            self.assertEqual(result["scope"]["area"], "salesforce")
            evidence = [row for row in result["entries"] if area_fact in row["text"]]
            self.assertEqual([row["record"] for row in evidence], [self.plugin])
            self.assertIn(self.source, str(evidence[0]["sources"]))
            self.assertNotIn("onboarding_required", str(result))
        self.assertEqual(profile.read_bytes(), original)

    def test_whole_product_owner_saves_a_hypothesis_at_product_scope_without_creating_an_area(self):
        subject = "product/analytics"
        self.reach_product(subject)
        self.capture("plan", subject=subject, purpose="Capture our current product hypothesis.",
                     sources=[self.source], destinations=[self.product])
        self.capture("approve")
        statement = "I think independent clinics may use Analytics to understand cancellations."
        self.propose(statement, "customers")
        self.capture("accept")
        self.capture("finish")
        self.assertEqual(len(self.cover("product")), 6)
        self.assertEqual([p.relative_to(self.work).as_posix() for p in
                          (self.work / "context/products").rglob("overview.md")], [self.product])
        query = self.cli("task-context", "--product", "analytics", "What evidence do we have about independent clinics?")
        self.assertTrue(any(statement in row["text"] and row["record"] == self.product for row in query["entries"]))

    def test_unassigned_pm_can_leave_all_six_topics_open_without_creating_a_product(self):
        self.reach_product(None)
        self.assertEqual(len(self.cover("product")), 6)
        self.assertTrue(self.cli("onboarding", "status")["ready"])
        self.assertFalse(list((self.work / "context/products").rglob("overview.md")))

    def test_recording_existing_choices_requires_separate_consent_for_the_exact_product_or_area(self):
        subject = "product/analytics/area/salesforce"
        self.reach_product(subject)
        titles = {self.product: "Analytics Suite", self.plugin: "Salesforce Connector"}
        self.capture("plan", subject=subject, purpose="Document existing pilot decisions.",
                     sources=[self.source], destinations=[self.product, self.plugin], titles=titles)
        quote = "The product council chose the January pilot window."
        decision = dict(person="Product council", date="2026-01-07", question="When will we pilot?",
                        scope="Analytics pilot window", next_step="Share the approved pilot dates.")
        entry = dict(source=1, scope="product", product="analytics", topic="decisions", decision=decision,
                     quote=quote, location="Council minute 2")
        source = dict(reference=self.source, date="2026-01-07", checked_on="2026-01-08", coverage="partial", text=quote)
        payload = dict(sources=[source], entries=[entry])
        self.cli("route-context", payload=payload, error="Approve the product source plan")
        self.capture("approve")
        progress = self.cli("onboarding", "status")
        self.cli("route-context", payload=dict(payload, entries=[entry, entry]), error="onboarding_required")
        self.cli("route-context", payload=dict(payload, sources=[dict(source, reference="Unapproved minutes")]),
                 error="outside the approved product plan")
        self.cli("route-context", payload=dict(payload, entries=[dict(entry, product="other")]), error="approved plan")
        self.cli("route-context", payload=dict(payload, entries=[dict(entry, product_area="receipts")]), error="approved plan")
        self.cli("route-context", payload=dict(payload, sources=[{k: v for k, v in source.items() if k != "text"}]),
                 error="inspected source")
        self.propose("Analytics serves the pilot teams.", "customers")
        self.cli("route-context", payload=payload, error="pending product finding")
        self.capture("discard")
        for path in (self.product, self.plugin):
            if path == self.plugin:
                quote = "The connector council chose read-only access for the trial."
                entry = dict(entry, product_area="salesforce", quote=quote,
                             decision=dict(decision, person="Connector council", question="What access does the trial use?",
                                           scope="Salesforce connector trial", next_step="Issue read-only credentials."))
                payload = dict(entries=[entry], sources=[dict(source, text=quote)])
            self.assertFalse((self.work / path).exists())
            preview = self.cli("route-context", payload=payload)
            self.assertEqual(preview["entries"][0]["destination"], path)
            self.assertFalse((self.work / path).exists())
            self.cli("route-context", "--write", path, payload=payload, error="record_decision")
            confirmed = test_pm.confirmed_decisions(payload, preview)
            wrong = dict(confirmed, entries=[dict(confirmed["entries"][0], location="Different decision minute")])
            self.cli("route-context", "--write", path, payload=wrong, error="changed")
            self.assertFalse((self.work / path).exists())
            saved = self.cli("route-context", "--write", path, payload=confirmed)
            self.assertEqual(saved["written"], path)
            raw = (self.work / path).read_bytes()
            self.assertIn(quote.encode(), raw)
            self.assertIn(f"# {titles[path]}\n".encode(), raw)
            self.cli("route-context", "--write", path, payload=confirmed)
            self.assertEqual((self.work / path).read_bytes(), raw)
        self.assertEqual(self.cli("onboarding", "status"), progress)
        self.assertNotIn(quote, (self.work / self.product).read_text())
        self.capture("finish")
        self.cli("route-context", "--write", self.plugin, payload=confirmed, error="Approve the product source plan")
        self.cover("product")
        self.capture("plan", subject=subject, purpose="Revisit the connector trial.",
                     sources=[self.source], destinations=[self.plugin])
        self.capture("approve")
        preview = self.cli("route-context", payload=payload)
        self.assertEqual(preview["entries"][0]["destination"], self.plugin)
        self.cli("route-context", "--write", self.plugin, payload=confirmed)
        self.cli("route-context", payload=dict(payload, sources=[dict(source, reference="Unapproved minutes")]),
                 error="outside the approved product plan")
        self.cli("route-context", payload=dict(payload, entries=[entry, entry]), error="with product-onboarding")

        # The approved connector brief contains an earlier decision about the same question.
        # A later decision must surface the conflict without opening the other product or the metric registry.
        protected = records.create(self.root, "product-context", "context/products/shipping/overview.md", "Shipping")
        quote = "After reaching 20% conversion, the connector council authorized full access for the trial."
        changed = dict(entries=[dict(entry, quote=quote, location="Council minute 3")],
                       sources=[dict(source, text=quote)])
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            self.assertNotEqual(path, protected, "The unrelated product is outside the approved plan")
            return original_open(path, *args, **kwargs)

        def guarded_route(data, *args):
            out = io.StringIO()
            with ExitStack() as stack:
                stack.enter_context(patch.object(pm, "ROOT", self.root))
                stack.enter_context(patch.object(sys, "argv", ["pm.py", "route-context", *args]))
                stack.enter_context(patch.object(sys, "stdin", io.StringIO(json.dumps(data))))
                stack.enter_context(redirect_stdout(out))
                stack.enter_context(patch.object(Path, "open", guarded_open))
                stack.enter_context(patch.object(pm.metric_registry, "effective", side_effect=AssertionError("Unapproved metric registry")))
                stack.enter_context(patch.object(evidence_reviews, "needs_plan_review", side_effect=AssertionError("Unapproved initiative")))
                self.assertEqual(pm.main(), 0, out.getvalue())
            return json.loads(out.getvalue())

        preview = guarded_route(changed)
        self.assertIn("potential conflict", {risk["classification"] for risk in preview["risk_preview"]})
        approved = test_pm.confirmed_decisions(changed, preview)
        self.assertEqual(guarded_route(approved, "--write", self.plugin)["written"], self.plugin)
        history = evidence_reviews.history((self.work / self.plugin).read_text())
        self.assertTrue(any(risk.get("classification") == "potential conflict" for risk in history))

    def test_existing_area_resumes_in_place_without_rewriting_parent_or_sibling(self):
        subject = "product/analytics/area/salesforce"
        previous = "context/products/analytics/areas/salesforce/overview.md"
        sibling = "context/products/analytics/areas/receipts/overview.md"
        parent = records.create(self.root, "product-context", self.product, "Analytics")
        def legacy_area(path, title):
            contract = filing.area_contract(self.work, path, self.product, None,
                                            "Support consults this integration guide.", "The integration changes.")
            return records.create(self.root, "product-area-context", path, title, filing_contract=contract)

        old = legacy_area(previous, "Salesforce")
        other = legacy_area(sibling, "Receipts")
        old.write_text(old.read_text().replace("# Salesforce", "# Salesforce\n\nPrivate legacy introduction."))
        old_id = records.work_state(old.read_text())[0]["ID"]
        original = parent.read_bytes(), other.read_bytes()

        self.reach_product(subject)
        self.capture("plan", subject=subject, purpose="Update an existing integration brief.",
                     sources=[self.source], destinations=[previous])
        self.capture("approve")
        sentence = "Our Salesforce integration reads account records each morning."
        self.propose(sentence, "offer", product_area="salesforce")
        self.capture("accept")
        self.capture("finish")
        self.cover("product")
        self.assertEqual(records.work_state(old.read_text())[0]["ID"], old_id)
        self.assertIn("Private legacy introduction.", old.read_text())
        self.assertIn(sentence, old.read_text())
        self.assertEqual((parent.read_bytes(), other.read_bytes()), original)
        self.assertFalse((self.work / self.plugin).exists())
        result = self.cli("task-context", "--product", "analytics", "--area", "salesforce",
                          "Which account records are read each morning?")
        self.assertTrue(any(row["record"] == previous and sentence in row["text"] for row in result["entries"]))
