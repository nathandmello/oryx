"""A single readable PM profile preserves narrative and round-trips ownership."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import context_capture
import pm_profile


class PMProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.private = Path(temp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.private)], check=True)
        self.path = self.private / pm_profile.PATH
        self.legacy = self.private / pm_profile.LEGACY
        self.goal = self.private / "workspace/goals/refunds.md"
        self.goal.parent.mkdir(parents=True)
        self.goal.write_text("# Refund rate\n")
        self.role = {"subject": "product/checkout/area/refunds", "role": "owner",
                     "goals": ["workspace/goals/refunds.md#refund-rate", "https://example.com/goals?q=1&v=2"],
                     "depends_on": ["product/billing", "area/pricing"]}
        self.remit = {"status": "draft", "responsibilities": [self.role], "follow": ["topic/regulation"]}

    def test_prose_only_profile_prompts_and_owned_rows_are_editable_markdown(self):
        created = pm_profile.create(self.private, "My PM context")
        created.write_text(created.read_text() + "\n## Background\n\nI support the checkout group.\n")
        self.assertIsNone(context_capture.read_remit(self.private))
        self.assertEqual(context_capture.remit_prompt(self.private), context_capture.REMIT_PROMPT)
        context_capture.write_remit(self.private, self.remit)
        self.assertIn("I support the checkout group.", self.path.read_text())
        self.assertIn("| Responsibility | Role | Goals | Depends on |", self.path.read_text())
        self.assertIn("[refunds.md](<../../workspace/goals/refunds.md#refund-rate>)", self.path.read_text())
        self.assertFalse(self.legacy.exists())
        self.assertEqual(context_capture.read_remit(self.private), self.remit)
        before = self.path.read_bytes()
        context_capture.write_remit(self.private, self.remit)
        self.assertEqual(self.path.read_bytes(), before)
        self.path.write_text(self.path.read_text().replace("| owner |", "| shared |").replace("Status: draft", "Status: confirmed"))
        current = context_capture.read_remit(self.private)
        self.assertEqual(current["responsibilities"][0]["role"], "shared")
        self.assertIsNone(context_capture.remit_prompt(self.private))
        with self.assertRaises(ValueError):
            pm_profile.create(self.private)

    def test_update_preserves_crlf_unicode_custom_labels_and_prose_even_inside_remit(self):
        prose = "# PM context\r\n\r\nPublic-facing names use café.\r\n"
        doc = pm_profile.render(self.remit, prose).replace("Status: draft", "Status: draft\r\n\r\nAsk François about release authority.")
        doc = doc.replace("[refunds.md]", "[Our refund target]") + "\r\n## Colleagues\r\n\r\nCheck with Jo.\r\n"
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(doc.encode("utf-8"))
        changed = dict(self.remit, status="confirmed")
        context_capture.write_remit(self.private, changed)
        self.assertEqual(self.path.read_bytes(), doc.replace("Status: draft", "Status: confirmed").encode())
        changed["responsibilities"] = [dict(self.role, role="shared")]
        context_capture.write_remit(self.private, changed)
        self.assertIn("[Our refund target]", self.path.read_bytes().decode())
        self.assertEqual(context_capture.read_remit(self.private), changed)

    def test_fenced_example_is_prose_and_invalid_or_duplicate_structures_are_untouched(self):
        example = "# My notes\n\n````md\n## PM remit\nStatus: confirmed\n```\n````\n"
        self.path.parent.mkdir(parents=True)
        self.path.write_text(example)
        context_capture.write_remit(self.private, self.remit)
        self.assertTrue(self.path.read_text().startswith(example))
        valid = self.path.read_text()
        for invalid in (valid + "\n## PM remit\n", valid.replace("Status: draft", "Status: later"),
                        valid.replace("Responsibility |", "Subject |"), valid.replace(" | owner |", " | unknown |"),
                        valid.replace("topic/regulation", "topic/../regulation"), valid.replace("<../../workspace/", "</etc/"),
                        valid.replace("Status: draft", "Status: draft\nStatus: confirmed")):
            with self.subTest(invalid=invalid):
                self.path.write_text(invalid)
                self.assertTrue(context_capture.inspect_remit(self.private)[1])
                with self.assertRaises(ValueError):
                    context_capture.write_remit(self.private, self.remit)
                self.assertEqual(self.path.read_text(), invalid)

    def test_legacy_conversion_validates_input_and_retargets_local_goal_only(self):
        rel = "products/store/göal old.md"
        path = self.private / rel
        path.parent.mkdir(parents=True)
        path.write_text("# Goal\n\n## Refund rate\n")
        remote = "https://example.com/policies/a?q=left%7Cright&final=1"
        role = dict(self.role, goals=["products/store/g%C3%B6al%20old.md#refund-rate", remote])
        data = {"responsibilities": [role], "follow": []}
        raw = json.dumps(data).encode()
        profile = pm_profile.from_legacy(self.private, raw, {rel: "workspace/goals/göal old.md"})
        result = pm_profile.parse(profile.decode())
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["responsibilities"], [dict(role, goals=["workspace/goals/g%C3%B6al%20old.md#refund-rate", remote])])
        self.assertEqual(pm_profile.from_legacy(self.private, raw, {rel: "workspace/goals/göal old.md"}), profile)
        self.assertFalse(self.path.exists())
        for bad in (b'{"responsibilities": [], "follow": [], "follow": []}', b'{"unknown": 1}', b'['):
            with self.assertRaises(ValueError):
                pm_profile.from_legacy(self.private, bad, {})

    def test_partial_legacy_invalid_and_profile_collision_do_not_change_either_file(self):
        self.legacy.parent.mkdir(parents=True)
        self.legacy.write_text('{"responsibilities": [], "follow": ["topic/invoicing"]}')
        self.assertEqual(context_capture.remit_prompt(self.private), context_capture.DRAFT_REMIT_PROMPT)
        with self.assertRaises(ValueError):
            context_capture.write_remit(self.private, self.remit)
        self.assertFalse(self.path.exists())
        self.path.parent.mkdir()
        self.path.write_text("# My PM context\n\nEvidence within.\n")
        before = self.path.read_bytes(), self.legacy.read_bytes()
        self.assertTrue(context_capture.inspect_remit(self.private)[1])
        with self.assertRaises(ValueError):
            context_capture.write_remit(self.private, self.remit)
        self.assertEqual(before, (self.path.read_bytes(), self.legacy.read_bytes()))
        self.path.unlink()
        self.legacy.write_text('{"responsibilities":')
        self.assertTrue(context_capture.inspect_remit(self.private)[1])
        self.assertFalse(self.path.exists())

    def test_explicit_empty_and_unconfirmed_are_distinct(self):
        for status, expected in (("confirmed", None), ("draft", context_capture.REMIT_PROMPT)):
            data = {"status": status, "responsibilities": [], "follow": []}
            context_capture.write_remit(self.private, data)
            self.assertEqual(context_capture.read_remit(self.private), data)
            self.assertEqual(context_capture.remit_prompt(self.private), expected)

    def test_retained_legacy_goal_can_still_be_used_after_other_records_move(self):
        old = self.private / "products/checkout/existing draft.md"
        old.parent.mkdir(parents=True)
        old.write_text("# Existing draft\n")
        role = dict(self.role, goals=["products/checkout/existing%20draft.md"])
        data = dict(self.remit, responsibilities=[role])
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(pm_profile.from_legacy(self.private, json.dumps(data).encode(), {}))
        self.assertEqual(context_capture.read_remit(self.private), data)
        context_capture.write_remit(self.private, dict(data, status="confirmed"))
        self.assertEqual(context_capture.read_remit(self.private)["responsibilities"], [role])

    def test_route_supplied_pm_evidence_questions_and_mixed_company_sources(self):
        # Exercise the public CLI, including the normal validators and old mixed-source contract.
        from test_pm import HubTests
        fixture = HubTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        def capture(entries, *args):
            source = {"reference": "PM interview", "date": "undated", "coverage": "read", "checked_on": "2025-01-01",
                      "text": "I work with refund operations. Finance sets prices. Jo represents Finance."}
            return subprocess.run([sys.executable, str(fixture.root / "tools/pm.py"), "route-context", *args],
                                  input=json.dumps({"sources": [source], "entries": entries}), text=True,
                                  capture_output=True, cwd=fixture.work)
        fact = {"scope": "pm", "topic": "background", "quote": "I work with refund operations.", "source": 1, "location": "Opening"}
        company = dict(fact, scope="company", topic="constraints", quote="Finance sets prices.")
        question = {"scope": "pm", "topic": "stakeholders", "question": "Who represents Finance?"}
        path = pm_profile.PATH
        target = fixture.work / path
        mixed = [company, fact, question]
        preview = capture(mixed)
        self.assertEqual(preview.returncode, 0, preview.stdout)
        rows = json.loads(preview.stdout)["entries"]
        self.assertEqual([row["destination"] for row in rows], ["context/company/overview.md", path, path])
        self.assertEqual(rows[1]["relevance"], "pm")
        self.assertFalse(target.exists())
        self.assertNotEqual(capture([dict(fact, record={"path": "context/pm/audit.md", "reason": "Keep notes."})]).returncode, 0)
        pm_profile.create(fixture.work)
        target.write_bytes(b"# My PM context\r\n\r\n## Sources\r\n\r\nPrivate source note.\r\n")
        context_capture.write_remit(fixture.work, {"status": "confirmed", "responsibilities": [], "follow": []})
        human = target.read_bytes()
        wrote = capture(mixed, "--write", path)
        self.assertEqual(wrote.returncode, 0, wrote.stdout)
        self.assertEqual(json.loads(wrote.stdout)["written"], path)
        self.assertTrue(target.read_bytes().startswith(human))
        self.assertIn("- Unknown: Who represents Finance?", target.read_text())
        self.assertIn("> I work with refund operations.", target.read_text())
        self.assertNotIn("Finance sets prices.", target.read_text())
        self.assertEqual(context_capture.read_remit(fixture.work), {"status": "confirmed", "responsibilities": [], "follow": []})
        self.assertFalse((fixture.work / "context/company/overview.md").exists())
        before = target.read_bytes()
        self.assertIsNone(json.loads(capture(mixed, "--write", path).stdout)["written"])
        self.assertEqual(before, target.read_bytes())
        answered = capture([dict(fact, topic="stakeholders", quote="Jo represents Finance.", answers=question["question"])], "--write", path)
        self.assertEqual(answered.returncode, 0, answered.stdout)
        self.assertNotIn("- Unknown: Who represents Finance?", target.read_text())
        self.assertIn("Jo represents Finance.", target.read_text())
        self.assertTrue(target.read_bytes().startswith(human))
        damaged = target.read_bytes().replace(pm_profile.CAPTURE_END.encode(), b"")
        target.write_bytes(damaged)
        self.assertNotEqual(capture([fact], "--write", path).returncode, 0)
        self.assertEqual(target.read_bytes(), damaged)

    def test_unstructured_remit_heading_preserves_narrative_and_accepts_confirmation(self):
        self.path.parent.mkdir(parents=True)
        before = "# My PM notes\n\n## PM remit\n\nI joined the checkout group this week.\n"
        after = "## People\n\nCheck with Jo.\n"
        self.path.write_text(before + "\n" + after)
        self.assertIsNone(context_capture.read_remit(self.private))
        context_capture.write_remit(self.private, self.remit)
        text = self.path.read_text()
        self.assertTrue(text.startswith(before))
        self.assertTrue(text.endswith(after))
        self.assertEqual(text.count("## PM remit"), 1)
        self.assertEqual(context_capture.read_remit(self.private), self.remit)

    def test_unclosed_fences_preserve_original_on_remit_and_narrative_capture(self):
        self.path.parent.mkdir(parents=True)
        entry = {"scope": "pm", "section": "PM background", "question": "Who leads the reviews?"}
        for fence in ("```", "~~~", "````md\r\n```"):
            original = f"# Profile\r\n\r\n{fence}\r\nMy unfinished example.\r\n".encode()
            self.path.write_bytes(original)
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "open fences"):
                    context_capture.write_remit(self.private, self.remit)
                with self.assertRaisesRegex(ValueError, "open fences"):
                    context_capture.apply_profile(self.private.parent, self.private, self.path, [entry], [], lambda *_: [])
            self.assertEqual(self.path.read_bytes(), original)
            self.assertIsNone(context_capture.read_remit(self.private))

    def test_ignored_profile_writes_are_rejected_before_changing_private_files(self):
        (self.private / ".gitignore").write_text("/context/pm/\n")
        with self.assertRaisesRegex(ValueError, "ignores"):
            pm_profile.create(self.private)
        with self.assertRaisesRegex(ValueError, "ignores"):
            context_capture.write_remit(self.private, self.remit)
        entry = {"scope": "pm", "section": "PM background", "question": "Who leads the reviews?"}
        with self.assertRaisesRegex(ValueError, "ignores"):
            context_capture.apply_profile(self.private.parent, self.private, self.path, [entry], [], lambda *_: [])
        self.assertFalse(self.path.exists())
