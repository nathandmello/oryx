"""Exercise cross-surface workspace customization using disposable product data."""

import itertools
import csv
import io
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_pm
from onboarding_fixtures import reviewed_setup

import customizations as custom
import initiative_views
import initiative_work
import overrides
import pm
import records
import roadmap_edit


class CustomizationTests(unittest.TestCase):
    setUp = reviewed_setup

    def change(self, config):
        return custom.apply(self.root, {"revision": custom.snapshot(self.root)["revision"], "config": config})

    def test_all_markdown_templates_keep_their_contracts(self):
        self.change({"templates": {kind: {"Decision notes": {"prompt": "Record the reasoning."}} for kind in records.KINDS}})
        for kind in records.KINDS:
            with self.subTest(kind=kind):
                source = (self.root / "templates" / (kind + ".md")).read_text()
                draft = custom.draft_template(self.root, kind, self.work / "workspace" / "draft.md", source)
                self.assertIn("## Decision notes", draft)
                self.assertEqual(records.structure_errors(kind, draft, records.heading_order(kind, source)), [])
                self.assertEqual([key for key, *_ in records.section_blocks(draft) if key != "Decision notes"],
                                 [key for key, *_ in records.section_blocks(source)])
        before = custom.snapshot(self.root)
        with self.assertRaises(ValueError):
            self.change({"templates": {"initiative-brief": {"Parent initiative": {"mode": "replace", "prompt": "Changed"}}}})
        with self.assertRaisesRegex(ValueError, "Indent example headings"):
            self.change({"templates": {"discovery-brief": {"Notes": {"content": "~~~md\n## Example\n~~~"}}}})
        self.assertEqual(custom.snapshot(self.root), before)

    def test_direct_core_template_adoption_preserves_position(self):
        self.change({"templates": {"goal": {"Stakeholder signoff": {"before": "Alignment", "prompt": "Record signoff."}}}})
        source = self.root / "templates/goal.md"
        original = source.read_text()
        addition = "## Stakeholder signoff\n\n{{Record signoff.}}\n\n"
        target = self.work / "workspace/goals/signoff.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(records.draft_text(self.root, "goal", target))
        original_draft = target.read_bytes()
        source.write_text(original.replace("## Work state", addition + "## Work state"))
        result = pm.alignment(self.root, True)
        self.assertEqual(result["covered_customizations"], [])
        self.assertIn("goal", custom.snapshot(self.root)["config"]["templates"])
        draft = records.draft_text(self.root, "goal", target)
        self.assertEqual(draft.count("## Stakeholder signoff"), 1)
        self.assertLess(draft.index("## Stakeholder signoff"), draft.index("## Alignment"))
        self.assertEqual(pm.check(self.root), [])
        self.assertEqual(target.read_bytes(), original_draft)
        source.write_text(original.replace("## Alignment", addition.replace("Record signoff.", "Core prompt.") + "## Alignment"))
        self.assertEqual(pm.alignment(self.root, True)["covered_customizations"], [])
        self.assertIn("{{Record signoff.}}", records.draft_text(self.root, "goal", target))
        source.write_text(original.replace("## Alignment", addition + "## Alignment"))
        self.assertIn("templates", pm.alignment(self.root, True)["covered_customizations"])
        self.assertNotIn("goal", custom.snapshot(self.root)["config"].get("templates", {}))

    def test_structured_replacement_and_append_survive_changed_core_markdown(self):
        self.change({"templates": {"goal": {
            "Alignment": {"mode": "replace", "content": "| Sponsor | Decision |\n| --- | --- |\n| {{Who?}} | {{What?}} |"},
            "Outcome": {"mode": "append", "prompt": "Who signs off?"}}}})
        source = self.root / "templates/goal.md"
        text = source.read_text()
        text = text.replace(records.section(text, "Alignment").strip(), "Core changed this to a list.\n\n- First\n- Second")
        text = text.replace("## Outcome\n", "## Outcome\n\n{{Who signs off?}}\n")
        source.write_text(text)
        target = self.work / "workspace/goals/signoff.md"
        draft = records.draft_text(self.root, "goal", target)
        self.assertNotIn("Core changed this", draft)
        self.assertIn("| Sponsor | Decision |", records.section(draft, "Alignment"))
        self.assertTrue(records.section(draft, "Outcome").strip().endswith("{{Who signs off?}}"))
        self.assertEqual(draft.count("{{Who signs off?}}"), 1)
        self.assertIn("| Guardrails |", draft)
        self.assertEqual(custom.reconcile(self.root, "example", True), [])
        with self.assertRaisesRegex(ValueError, "comparison table"):
            self.change({"templates": {"prioritization": {"Comparison": {"mode": "replace", "prompt": "Skip the table."}}}})

    def test_adopt_an_ordered_group_of_sections_without_retiring_another_local_section(self):
        self.change({"templates": {"goal": {
            "Sponsor": {"before": "Sources", "prompt": "Who owns it?"},
            "Budget": {"before": "Sources", "prompt": "Who funds it?"},
            "Timing": {"before": "Outcome", "prompt": "When does it start?"}}}})
        source = self.root / "templates/goal.md"
        original = source.read_text()
        sponsor = "## Sponsor\n\n{{Who owns it?}}\n\n"
        budget = "## Budget\n\n{{Who funds it?}}\n\n"
        source.write_text(original.replace("## Sources", budget + sponsor + "## Sources"))
        custom.reconcile(self.root, "different-order", False)
        draft = custom.draft_template(self.root, "goal", self.work / "workspace/goals/plan.md", source.read_text())
        self.assertLess(draft.index("## Sponsor"), draft.index("## Budget"))
        source.write_text(original.replace("## Sources", sponsor + budget + "## Sources"))
        self.assertEqual(custom.reconcile(self.root, "covered", True), ["templates"])
        self.assertEqual(list(custom.snapshot(self.root)["config"]["templates"]["goal"]), ["Timing"])

    def test_product_specific_core_defaults_cannot_shadow_studio(self):
        source = self.root / custom.DEFAULTS
        base = custom.core(self.root)
        core_product = {"default_view": "core-team", "templates": {"goal": {
            "Approval": {"content": "Core team approval.", "before": "Sources"}}},
            "checkpoints": {"enablement": {"title": "Core training", "criterion": "Ask the team."},
                            "upstream-dependencies": {"omit": True}}}
        views = {name: {"title": name} for name in ("core-team", "pm", "specialist")}
        base.update({"products": {"sales": core_product, "platform": core_product}, "views": views})
        source.write_text(json.dumps(base))
        # The broad PM overrides only the prompt, view choice and criteria. A
        # product-specific PM changes two of those choices for platform alone.
        common = {"templates": {"goal": {"Approval": {"prompt": "Ask the PM."}}},
                  "default_view": "pm", "checkpoints": {
                      "enablement": {"criterion": "Record readiness."}, "upstream-dependencies": {"omit": False}}}
        self.change({**common, "products": {"platform": {
            "templates": {"goal": {"Approval": {"content": "Ask the lead."}}},
            "default_view": "specialist", "checkpoints": {"enablement": {"title": "Lead training"}}}}})
        resolved = custom.snapshot(self.root)["effective"]
        for product in ("sales", "platform", "new-product"):
            with self.subTest(product=product):
                scoped = custom.for_product(resolved, product)
                self.assertEqual(custom.projection(self.root, [], product=product)["name"],
                                 "specialist" if product == "platform" else "pm")
                checkpoints = initiative_work.template(self.root, scoped["checkpoints"])
                self.assertIn("upstream-dependencies", checkpoints)
                self.assertEqual(checkpoints["enablement"]["criterion"], "Record readiness.")
                title = {"sales": "Core training", "platform": "Lead training"}.get(product, "Confirm customer and team enablement")
                self.assertEqual(checkpoints["enablement"]["title"], title)
                draft = records.draft_text(self.root, "goal", self.work / f"workspace/roadmaps/{product}/next.md")
                self.assertIn("Ask the lead." if product == "platform" else "{{Ask the PM.}}", draft)
                if product != "new-product":
                    self.assertLess(draft.index("## Approval"), draft.index("## Sources"))
        base.update(common)
        source.write_text(json.dumps(base))
        # The broad rule is still needed for named products with conflicting core defaults.
        custom.reconcile(self.root, "partial", True)
        pending = custom.snapshot(self.root)["config"]
        self.assertIn("default_view", pending)
        self.assertIn("Approval", pending["templates"]["goal"])
        self.assertIn("upstream-dependencies", pending["checkpoints"])
        base["products"] = {}
        source.write_text(json.dumps(base))
        custom.reconcile(self.root, "complete", True)
        pending = custom.snapshot(self.root)["config"]
        self.assertEqual(set(pending), {"products"})
        self.assertIn("platform", pending["products"])

    def test_superseded_structural_report_stays_local(self):
        parse = pm.build_parser().parse_args
        overrides.run(self.root, parse(["override", "reporting", "on"]))
        self.change({"fields": {"x-confidence": {"type": "boolean", "label": "Private label"}}})
        send = parse(["override", "report", "fields/x-confidence", "--title", "General request",
                      "--body", "Allow an optional field.", "--approved"])
        with patch.object(overrides, "gh", side_effect=ValueError("offline")):
            self.assertIn("report_pending", overrides.run(self.root, send))
        self.change({"fields": {"x-confidence": None}})
        with patch.object(overrides, "gh", side_effect=AssertionError("Superseded report reached GitHub")):
            self.assertEqual(overrides.run(self.root, parse(["override", "sync"]))["superseded"], ["fields/x-confidence"])

    def test_markdown_risk_matrix_and_forward_anchor(self):
        table = "| Risk | Owner | Mitigation |\n| --- | --- | --- |\n| {{risk}} | {{owner}} | {{next step}} |"
        sections = {"Intro": {"before": "Risks", "prompt": "Explain scope."},
                    "Risks": {"before": "Sources", "content": table}}
        self.change({"templates": {"initiative-brief": sections}})
        draft = records.draft_text(self.root, "initiative-brief", self.work / "workspace/initiatives/a/i/brief.md",
                                   initiative_id="a/i", owner="Fixture PM")
        self.assertIn("| {{risk}} | Fixture PM | {{next step}} |", draft)
        self.assertLess(draft.index("## Intro"), draft.index("## Risks"))
        self.assertLess(draft.index("## Risks"), draft.index("## Sources"))
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.change({"templates": {"initiative-brief": {"Risks": {"before": "Intro"}}}})

    def test_product_specific_drafts_and_older_records(self):
        old = records.draft_text(self.root, "initiative-brief", self.work / "workspace/initiatives/a/i/brief.md",
                                 initiative_id="a/i")
        self.change({"products": {"a": {"templates": {"initiative-brief": {
            "Local decisions": {"before": "Sources", "prompt": "Record the local decision."}}}}}})
        for product in ("a", "b"):
            draft = records.draft_text(self.root, "initiative-brief", self.work / f"workspace/initiatives/{product}/i/brief.md",
                                       initiative_id=f"{product}/i")
            self.assertEqual("## Local decisions" in draft, product == "a")
        self.assertNotIn("## Local decisions", old)

    def test_comparison_starter_binds_section_order(self):
        def starter(before):
            self.change({"products": {"sample": {"templates": {"prioritization": {
                "Review owner": {"prompt": "Name the reviewer.", "before": before}}}}}})
            return roadmap_edit.comparison_template(self.root, "sample")
        first = starter("Capacity constraints")
        moved = starter("Sources")
        self.assertEqual(first["sections"], moved["sections"])
        self.assertNotEqual(first["revision"], moved["revision"])

    def test_hand_edited_comparison_with_repeated_heading(self):
        with self.assertRaisesRegex(ValueError, "duplicate sections named Readout"):
            roadmap_edit.comparison_sections("## Readout\n\nFirst result.\n\n## Readout\n\nSecond result.")

    def test_one_product_uses_a_decision_table_another_keeps_the_prompt(self):
        table = "| Driver | Approver |\n| --- | --- |\n| {{lead}} | {{reviewer}} |"
        kind = "initiative-brief"
        self.change({"templates": {kind: {"Decision roles": {"prompt": "Who owns this?", "before": "Sources"}}}})
        self.change({"products": {"enterprise": {"templates": {kind: {"Decision roles": {"content": table}}}}}})
        def draft(product):
            return records.draft_text(self.root, kind, self.work / f"workspace/initiatives/{product}/pilot/{kind}.md",
                                      initiative_id=f"{product}/pilot")
        old = draft("enterprise")
        self.assertIn(table, old)
        self.assertLess(old.index("## Decision roles"), old.index("## Sources"))
        self.assertIn("{{Who owns this?}}", draft("growth"))
        self.change({"products": {"enterprise": {"templates": {kind: {"Decision roles": {"prompt": "Who decides now?"}}}}}})
        self.assertIn("Who decides now?", draft("enterprise"))
        self.assertNotIn(table, draft("enterprise"))
        self.assertIn(table, old)
        with self.assertRaisesRegex(ValueError, "either"):
            self.change({"templates": {kind: {"Decision roles": {"content": table, "prompt": "Choose both"}}}})

    def test_two_discovery_teams_use_the_same_brief_differently(self):
        kind = "discovery-brief"
        def target(product):
            return self.work / f"workspace/initiatives/{product}/renewals/{kind}.md"
        def draft(product):
            return records.draft_text(self.root, kind, target(product), initiative_id=product + "/renewals")
        old = draft("consumer")
        target("consumer").parent.mkdir(parents=True)
        target("consumer").write_text(old)
        tree = "- Reduce missed renewals\n  - Simplify timing\n    - Reminder email\n    - Calendar entry"
        self.change({"products": {
            "consumer": {"templates": {kind: {"Press release": {"content": "### Customer benefit\n{{Benefit}}", "before": "FAQ"},
                                               "FAQ": {"prompt": "What would a customer ask?"}}}},
            "platform": {"templates": {kind: {"Opportunity tree": {"content": tree},
                                              "How might we": {"prompt": "Which other framing fits?", "before": "Opportunity tree"}}}}}})
        consumer, platform = draft("consumer"), draft("platform")
        self.assertEqual(target("consumer").read_text(), old)
        self.assertLess(consumer.index("## Press release"), consumer.index("## FAQ"))
        self.assertNotIn("## Opportunity tree", consumer)
        self.assertIn(tree, platform)
        self.assertLess(platform.index("## How might we"), platform.index("## Opportunity tree"))
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.change({"products": {"platform": {"templates": {kind: {"Opportunity tree": {"before": "How might we"}}}}}})
        self.assertIn(tree, draft("platform"))

    def test_spreadsheet_and_markdown_exports_preserve_mixed_notes(self):
        view = {"columns": {"delta": "Delta", "note": "Evidence"}, "title": "Review"}
        note = '=Review, "pilot" | cohort\r\n二次確認\rAnother line'
        rows = [{"delta": -2.75, "note": note}, {"delta": 0, "note": None}]
        exported = initiative_views.render(view, rows, "csv")
        self.assertEqual(list(csv.reader(io.StringIO(exported, newline=""))),
                         [["delta", "note"], ["-2.75", "'" + note], ["0", ""]])
        markdown = initiative_views.render(view, rows, "markdown")
        self.assertEqual(len(markdown.splitlines()), 6)
        self.assertIn("&#124; cohort<br>二次確認<br>Another line", markdown)

    def test_audience_views_after_adding_a_private_field(self):
        self.change({"views": {"customer": {"columns": ["title"]}, "team": {"columns": ["*"]}}})
        self.change({"fields": {"x-margin": {"label": "Internal margin", "type": "number"}}})
        for name, contains_margin in [("customer", False), ("team", True)]:
            view = custom.projection(self.root, [], name)
            self.assertEqual("x-margin" in view["columns"], contains_margin)
        self.change({"views": {"team": {"group": "x-margin", "hidden": ["x-margin"]}}})
        view = custom.projection(self.root, [], "team")
        self.assertEqual(view["group"], "none")
        self.assertNotIn("x-margin", view["columns"])

    def test_moved_custom_page_does_not_block_other_workspace_edits(self):
        directory = self.work / "customizations/views"
        directory.mkdir()
        page = directory / "sales.html"
        page.write_text("<!-- pm:roadmap-data -->")
        self.change({"views": {"sales": {"page": "sales"}}})
        page.rename(directory / "quarterly.html")
        self.change({"fields": {"x-confidence": {"type": "number", "label": "Confidence"}}})
        self.assertTrue(any("sales.html" in problem for problem in pm.check(self.root)))
        with self.assertRaisesRegex(ValueError, "sales.html"):
            self.change({"views": {"another": {"page": "sales"}}})
        self.change({"views": {"sales": {"page": "quarterly"}}})
        self.assertEqual(pm.check(self.root), [])

    def test_adoption_of_literal_replacement_after_a_release(self):
        source = self.root / "templates/goal.md"
        body = "| Bet | Appetite |\n| --- | --- |\n| {{Pitch}} | {{Time budget}} |"
        self.change({"templates": {"goal": {"Alignment": {"mode": "replace", "content": body}}}})
        original = source.read_text()
        source.write_text(original.replace(records.section(original, "Alignment").strip(), body))
        self.assertIn("templates", pm.alignment(self.root, True)["covered_customizations"])
        self.assertEqual(pm.alignment(self.root, True)["covered_customizations"], [])

    def test_renamed_core_anchor_leaves_other_products_and_roadmap_edits_available(self):
        self.change({"products": {"enterprise": {"templates": {"initiative-brief":
            {"Rollout stages": {"before": "Delivery and launch", "prompt": "Name the pilot cohorts."}}}}}})
        source = self.root / "templates/initiative-brief.md"
        source.write_text(source.read_text().replace("## Delivery and launch", "## Delivery plan"))
        self.assertIn("customization_review", pm.alignment(self.root, True))
        self.change({"views": {"growth-review": {"columns": ["title"]}}})
        def draft(product):
            return records.draft_text(self.root, "initiative-brief", self.work / f"workspace/initiatives/{product}/i/initiative-brief.md",
                                      initiative_id=product + "/i")
        self.assertIn("## Delivery plan", draft("growth"))
        self.assertNotIn("Studio placed", draft("growth"))
        self.assertIn("Studio placed Rollout stages before Work state", draft("enterprise"))
        self.assertLess(draft("enterprise").index("## Rollout stages"), draft("enterprise").index("## Work state"))
        self.change({"products": {"enterprise": {"templates": {"initiative-brief":
            {"Decision notes": {"before": "Sources", "prompt": "Who confirms the pilot?"}}}}}})
        self.assertIn("{{Who confirms the pilot?}}", draft("enterprise"))
        with self.assertRaisesRegex(ValueError, "anchor"):
            self.change({"products": {"enterprise": {"templates": {"initiative-brief":
                {"Rollout stages": {"before": "Still missing"}}}}}})
        self.change({"products": {"enterprise": {"templates": {"initiative-brief":
            {"Rollout stages": {"before": "Delivery plan"}}}}}})
        self.assertLess(draft("enterprise").index("## Rollout stages"), draft("enterprise").index("## Delivery plan"))
        self.assertNotIn("Studio placed", draft("enterprise"))

    def test_missing_comparison_anchor_warns_in_product_preview(self):
        source = self.root / "templates/prioritization.md"
        source.write_text(source.read_text().replace("## Sources", "## Finance review\n\n{{Who reviews?}}\n\n## Sources"))
        self.change({"products": {"sales": {"templates": {"prioritization": {
            "Legal review": {"prompt": "Who confirms the obligations?", "before": "Finance review"}}}}}})
        self.assertEqual(roadmap_edit.comparison_template(self.root, "sales")["notices"], [])
        source.write_text(source.read_text().replace("## Finance review", "## Review assumptions"))
        preview = roadmap_edit.comparison_template(self.root, "sales")
        self.assertIn("Finance review is missing", preview["notices"][0])
        self.assertIn("Legal review", preview["sections"])
        self.assertEqual(roadmap_edit.comparison_template(self.root, "growth")["notices"], [])

    def test_removed_native_sections_keep_saved_append_and_replace(self):
        source = self.root / "templates/goal.md"
        text = source.read_text()
        self.change({"templates": {"goal": {
            "Alignment": {"mode": "replace", "prompt": "Who owns the decision?"},
            "Outcome": {"mode": "append", "prompt": "Document the appetite."}}}})
        source.write_text(text.replace("## Alignment", "## Strategy").replace("## Outcome", "## Success measures"))
        state_path = self.work / custom.FILE
        original_state = state_path.read_bytes()
        self.assertIn("customization_review", pm.alignment(self.root, False))
        self.assertEqual(state_path.read_bytes(), original_state)
        self.change({"templates": {"goal": {"Escalation": {"prompt": "Who can approve an exception?"}}}})
        draft = records.draft_text(self.root, "goal", self.work / "workspace/goals/plan.md")
        for section, prompt in (("Alignment", "Who owns the decision?"), ("Outcome", "Document the appetite.")):
            self.assertEqual(draft.count(f"## {section}\n"), 1)
            self.assertIn(f"Studio placed {section} before Work state because its original section is missing.", draft)
            self.assertIn(prompt, records.section(draft, section))
        with self.assertRaisesRegex(ValueError, "existing section"):
            self.change({"templates": {"goal": {"Missing": {"mode": "replace", "prompt": "What is new?"}}}})

    def test_two_agents_edit_from_the_same_read_and_retry(self):
        revision = custom.snapshot(self.root)["revision"]
        def update(key, token):
            return json.dumps({"revision": token, "config": {"fields": {key: {"label": key, "type": "text"}}}})
        command = [sys.executable, str(self.root / "tools/pm.py"), "customize", "apply"]
        keys = ["x-growth-owner", "x-platform-owner"]
        # Start two independent CLI processes with the same view of the private file.
        processes = [subprocess.Popen(command, cwd=self.root, text=True, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in keys]
        for key, process in zip(keys, processes):
            process.stdin.write(update(key, revision))
            process.stdin.close()
            process.stdin = None
        results = [process.communicate(timeout=20) for process in processes]
        codes = [process.returncode for process in processes]
        self.assertEqual(codes.count(0), 1, results)
        loser = next(i for i, code in enumerate(codes) if code)
        self.assertIn("Reload", results[loser][0])
        latest = custom.snapshot(self.root)
        self.assertIn(keys[1 - loser], latest["effective"]["fields"])
        subprocess.run(command, cwd=self.root, text=True, input=update(keys[loser], latest["revision"]),
                       capture_output=True, check=True)
        self.assertEqual(set(custom.snapshot(self.root)["effective"]["fields"]), set(keys))

    def test_cross_product_of_types_layouts_groups_exports_and_empty_cells(self):
        examples = {
            "text": ("A < B | C", {}), "number": (0, {}), "boolean": (False, {}),
            "date": ("2024-02-29", {}), "choice": ("High", {"choices": ["High", "Low"]}),
            "multiple": (["X", "Y"], {"choices": ["X", "Y"]})}
        fields = {"x-" + k: {"label": k, "type": k, **opts} for k, (_, opts) in examples.items()}
        views = {}
        for layout, group in itertools.product(("table", "board"), ("horizon", "areas", "none", "x-choice")):
            views[layout + "-" + group] = {"layout": layout, "group": group, "columns": ["title", *fields]}
        self.change({"fields": fields, "views": views, "products": {"sample": {"default_view": "table-areas"}}})
        _, state = custom.read(self.root)
        state["values"] = {"sample": {"sample/one": {"x-" + k: v for k, (v, _) in examples.items()}}}
        (self.work / custom.FILE).write_text(custom.encode(state))
        for name, style in itertools.product(views, ("json", "csv", "markdown", "html")):
            with self.subTest(name=name, style=style):
                rows = [{"product": "sample", "id": "sample/one", "title": "One"},
                        {"product": "other", "id": "sample/one", "title": "Two"}]
                view = custom.projection(self.root, rows, name)
                output = custom.page(self.root, view, rows) if style == "html" else initiative_views.render(view, rows, style)
                self.assertIn("One", output)
                for key in fields:
                    self.assertEqual(rows[0][key], examples[key[2:]][0])
                    self.assertIsNone(rows[1][key])
        self.assertEqual(custom.projection(self.root, [], product="sample")["name"], "table-areas")
        self.assertEqual(custom.projection(self.root, [], product="other")["name"], "standard")

    def test_adopt_then_remove_core_field_with_existing_values(self):
        field = {"type": "text", "label": "Team"}
        self.change({"fields": {"x-team": field}})
        path = self.work / custom.FILE
        _, state = custom.read(self.root)
        state["values"] = {"sample": {"sample/one": {"x-team": "Finance"}}}
        path.write_text(custom.encode(state))
        shared = self.root / custom.DEFAULTS
        base = custom.core(self.root)
        def release(definition):
            base["fields"] = definition
            shared.write_text(json.dumps(base))
        release({"x-team": {"type": "choice", "label": "Team", "choices": ["Engineering"]}})
        self.assertEqual(custom.validate(self.root, state)["fields"]["x-team"], field)
        release({"x-team": field})
        self.assertEqual(pm.alignment(self.root, True)["covered_customizations"], ["fields"])
        release({})
        snapshot = custom.snapshot(self.root)
        self.assertEqual(snapshot["effective"]["fields"]["x-team"], field)
        self.assertEqual(snapshot["values"]["sample"]["sample/one"]["x-team"], "Finance")
        self.change({"views": {"teams": {"group": "x-team"}}})
        self.assertEqual(pm.check(self.root), [])

    def test_bespoke_export_and_invalid_references(self):
        directory = self.work / "customizations/views"
        directory.mkdir()
        (directory / "demo.html").write_text("<title>Demo</title><!-- pm:roadmap-data -->")
        self.change({"views": {"demo": {"layout": "table", "page": "demo", "columns": ["title"]}}})
        view = custom.projection(self.root, [], "demo")
        hostile_title = "</script><not-markup>"
        page = custom.page(self.root, view, [{"title": hostile_title, "private": "unselected"}])
        self.assertNotIn(hostile_title, page)
        self.assertNotIn("unselected", page)
        self.assertIn("pm-roadmap", page)
        for invalid in ({"group": []}, {"hidden": ["unknown"]}, {"page": "../elsewhere"}, {"columns": []}):
            with self.assertRaises(ValueError):
                self.change({"views": {"bad": invalid}})

    def test_unreadable_customizations_leave_core_export_available(self):
        (self.work / custom.FILE).write_text("{")
        result = subprocess.run([sys.executable, str(self.root / "tools/pm.py"), "roadmap", "--view", "core"],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout), [])
        self.assertIn("customization_review", pm.alignment(self.root, True))
