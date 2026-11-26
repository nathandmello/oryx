"""Check the signed stakeholder gate across the offline and hosted release entry points."""

import argparse
import base64
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_pm
import release_qualification as qual
import release_review


class ReleaseQualificationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.signing = self.folder / "private.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256",
                        "-out", str(self.signing)], capture_output=True, check=True)
        self.public = subprocess.check_output(["openssl", "pkey", "-in", str(self.signing), "-pubout"], text=True)
        self.head, self.manifest, self.study = "a"*40, "1"*64, "2"*64
        self.repo, self.version = "fixture/oryx", "0.14.0"
        self.expected_pins = dict(zip(qual.PINS, (self.manifest, self.study, "3"*64, "4"*64)))
        proof = {host: {"host": host, "candidate": self.head, "matched": True, "runner_sha256": "5"*64,
                        "capture_sha256": sha256(host.encode()).hexdigest()} for host in ("linux", "macos", "wsl2")}
        candidate = "oryx-codex-harness"
        performance = {"codex_budgets_ms":{"first":10, "complete":20}}
        for group in ("warm", "cold"):
            performance[f"{group}/turns"] = {"n":100,"median":0,"upper":0}
            for metric in ("first", "complete"):
                for percentile in ("p50","p95"):
                    performance[f"{group}/{metric}/{percentile}"] = {
                        "n":100, "matched_upper_ratio":1, "native_absolute_upper_ms":2, "subscriber_upper_ratio":1}
        results = {
            "shared_core":proof, "performance":performance,
            "extraction":{f"{candidate}/{f}":{"precision_lower95":.99,"recall_lower95":.99}
                          for f in ("overall",*qual.FAMILIES)},
            "comparison":{f:{"lower95":.99,"deficit_lower95":-.04} for f in qual.FAMILIES},
            "coaching":{f"{candidate}/{w}":{"lower95":.99} for w in qual.WORKFLOWS}}
        self.report = {"protocol": qual.PROTOCOL, "comparison_mode": qual.COMPARISON_MODE, "decision": "PASS",
                       "checks": dict.fromkeys(qual.required_gates(), True), "results": results, "failed": [],
                       "candidate": self.head, "manifest_sha256": self.manifest, "registration_sha256": self.study}
        self.data = (json.dumps(self.report) + "\n").encode()
        self.artifact = sha256(self.data).hexdigest()
        self.receipt = qual.claims(self.repo, self.head, self.version, self.expected_pins, self.artifact)
        self.signature = base64.b64encode(subprocess.check_output(
            ["openssl", "dgst", "-sha256", "-sign", str(self.signing)], input=qual.canonical(self.receipt))).decode()
        self.pr = {"number": 24, "changed_files": 1, "head": {"sha": self.head}, "base": {"sha": "d"*40, "ref":"main"},
                   "merged": True, "merge_commit_sha": "b"*40, "body": self.section(self.receipt)}
        self.feature = {"filename": "renamed-file.py", "previous_filename": "tools/session_journal.py"}
        self.expected = (self.public, self.repo, self.head, self.version, self.expected_pins)
        self.pins = {self.head: self.expected_pins}
        self.env = {"GITHUB_REPOSITORY": self.repo, "ORYX_STUDY_PINS": json.dumps(self.pins),
                    "ORYX_STUDY_REVIEWER_PUBLIC_KEY": self.public}

    def section(self, receipt):
        return "## Stakeholder qualification\n\n```json\n" + json.dumps(
            {"receipt": receipt, "signature": self.signature}) + "\n```\n"

    def api(self, path):
        if path.startswith("pulls/24/files?"):
            return [self.feature]
        if path == "contents/playbook/release.json?ref=" + self.head:
            return {"encoding": "base64", "content": base64.b64encode(json.dumps({"system_version": self.version}).encode()).decode()}
        if path == "pulls/24":
            return self.pr
        self.fail("Unexpected API request " + path)

    def test_signature_binds_each_field_and_private_raw_artifact(self):
        self.assertEqual(qual.verify(self.pr["body"], *self.expected, artifact=self.artifact), self.receipt)
        for key, val in (("decision", "HOLD"), ("repository","other/oryx"), ("candidate","c"*40),
                         ("version","1.0.0"), ("manifest_sha256","1"*63+"a"), ("registration_sha256","3"*64),
                         ("scorer_sha256","6"*64), ("evidence_sha256","7"*64), ("schema","unverified"), ("artifact_sha256","4"*64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                qual.verify(self.section(dict(self.receipt, **{key:val})), *self.expected)
        with self.assertRaises(ValueError):
            qual.verify(self.pr["body"], *self.expected, artifact=sha256(self.data.rstrip()).hexdigest())
        old = dict(self.receipt, schema="oryx-stakeholder-qualification/v2")
        del old["protocol"], old["comparison_mode"]
        old_signature = subprocess.check_output(["openssl", "dgst", "-sha256", "-sign", str(self.signing)],
                                                input=qual.canonical(old))
        with patch.object(self, "signature", base64.b64encode(old_signature).decode()), self.assertRaises(ValueError):
            qual.verify(self.section(old), *self.expected)
        for value in ("PASS", json.dumps(self.report), self.pr["body"]*2):
            with self.assertRaises(ValueError):
                qual.verify(value, *self.expected)

    def test_approved_public_key_and_external_registrations_are_required(self):
        files = {self.feature["filename"]: self.feature}
        with patch.dict(os.environ, self.env):
            qual.check(self.pr, files, self.api)
            for env in ({"ORYX_STUDY_PINS": "{}"}, {"ORYX_STUDY_REVIEWER_PUBLIC_KEY": ""},
                        {"ORYX_STUDY_PINS": json.dumps({self.head: dict(self.pins[self.head], registration_sha256="c"*64)})}):
                with patch.dict(os.environ, env), self.assertRaises(ValueError):
                    qual.check(self.pr, files, self.api)
        other = self.folder / "other.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256",
                        "-out", str(other)], capture_output=True, check=True)
        wrong = subprocess.check_output(["openssl", "pkey", "-in", str(other), "-pubout"], text=True)
        with self.assertRaisesRegex(ValueError, "signature"):
            qual.verify(self.pr["body"], wrong, *self.expected[1:])

    def test_real_review_and_publication_recheck_the_live_pr_body(self):
        event = self.folder / "event.json"
        event.write_text(json.dumps({"pull_request": self.pr}))
        env = dict(self.env, GITHUB_EVENT_PATH=str(event))
        with patch.dict(os.environ, env), patch.object(release_review, "github", self.api), patch.object(release_review, "review"):
            with redirect_stdout(io.StringIO()):
                release_review.main()
            self.pr["body"] = "PASS"
            with self.assertRaisesRegex(ValueError, "signed Stakeholder"):
                release_review.main()
            with self.assertRaisesRegex(ValueError, "signed Stakeholder"):
                release_review.publication(self.pr, "main", "b"*40, self.api)

    def test_scoped_changes_and_fail_closed_shared_diffs(self):
        for path in ("tools/session_journal.py", "tools/offer_queue.py", "tests/test_client_core_parity.py",
                     "tests/evals/stakeholder_release.py",
                     "tests/evals/stakeholder_statistics.py", ".agents/skills/stakeholder-profiles/SKILL.md"):
            self.assertTrue(qual.affected({"file":{"filename": "moved", "previous_filename":path}}))
        for path in ("README.md","playbook/release.json","tools/metric_registry.py"):
            qual.check({}, {"file": {"filename": path}}, self.api)
        shared = {"filename": "tools/pm.py", "patch": "@@ -1\n+add_metric_command(cmd)", "additions": 1, "deletions": 0}
        self.assertFalse(qual.affected({"file": shared}))
        self.assertTrue(qual.affected({"file": dict(shared, additions=45)}))
        self.assertTrue(qual.affected({"file": dict(shared, patch="@@\n-release_qualification.check(pr, files, api)")}))
        self.assertTrue(qual.affected({"file": {"filename":"tools/pm.py"}}))

    def test_only_independently_pinned_scorer_can_run_on_evidence(self):
        protected = self.folder / "review"
        protected.mkdir()
        corpus, evidence, scorer = (protected / name for name in ("corpus", "evidence", "scorer"))
        for folder in (corpus, evidence, scorer):
            folder.mkdir()
        (corpus / "manifest.json").write_text("{}")
        registration = dict(protocol=qual.PROTOCOL, comparison_mode=qual.COMPARISON_MODE, candidate=self.head)
        (evidence / "registration.json").write_bytes(qual.canonical(registration))
        (evidence / "observer.json").write_text("captured independently")
        self.manifest = sha256(b"{}").hexdigest()
        self.study = sha256(qual.canonical(registration)).hexdigest()
        self.report.update(manifest_sha256=self.manifest, registration_sha256=self.study)
        for name in qual.SCORER:
            (scorer / name).write_text("")
        gates = qual.required_gates() | {"registered-fixture/original/required-access"}
        self.report["checks"].update(dict.fromkeys(gates, True))
        (scorer / "required-gates.json").write_text(json.dumps(sorted(gates)))
        # This trusted fixture only has to exercise the controller boundary and signed report contract.
        trusted = "print(" + repr(json.dumps(self.report)) + ")\n"
        (scorer / qual.SCORER[0]).write_text(trusted)
        checkout = self.folder / "candidate"
        checkout.mkdir()
        (checkout / ".git").mkdir()
        (checkout / ".git/HEAD").write_text("ref: refs/heads/candidate")
        marker = self.folder / "candidate-code-ran"
        malicious = f"open({str(marker)!r}, 'w').write('ran')"
        (checkout / qual.SCORER[0]).write_text(malicious)
        fake_openssl = checkout / "openssl"
        fake_openssl.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        fake_openssl.chmod(0o700)
        (scorer / "sitecustomize.py").write_text(malicious)
        (scorer / "json.py").write_text(malicious)
        args = argparse.Namespace(repository=self.repo, head=self.head, version=self.version,
                                  frozen=corpus, evidence=evidence, scorer_dir=scorer,
                                  manifest=self.manifest, registration=self.study, signing_key=self.signing,
                                  report=self.folder / "report.json", scorer_digest=qual.scorer_bundle(scorer)[0],
                                  evidence_digest=qual.evidence_digest(evidence))
        # Invoke the installed reviewer tool on an isolated interpreter even from a hostile working directory.
        cli = protected / "qualification.py"
        cli.write_bytes(Path(qual.__file__).read_bytes())
        import sys
        cmd = [sys.executable, "-I", str(cli), "attest", "--repository", self.repo,
               "--version", self.version, "--head", self.head, "--manifest", self.manifest,
               "--registration", self.study, "--frozen", str(corpus), "--evidence", str(evidence),
               "--scorer-dir", str(scorer), "--scorer-digest", args.scorer_digest,
               "--evidence-digest", args.evidence_digest, "--report", str(args.report),
               "--signing-key", str(self.signing)]
        result = subprocess.run(cmd, cwd=checkout, env=dict(os.environ, PYTHONPATH=str(checkout),
                             PATH=str(checkout) + os.pathsep + os.defpath),
                                check=True, capture_output=True, text=True)
        self.assertFalse(marker.exists())
        verified = qual.verify(result.stdout, self.public, self.repo, self.head, self.version, qual.args_pins(args),
                               artifact=sha256(args.report.read_bytes()).hexdigest())
        self.assertEqual(verified["scorer_sha256"], args.scorer_digest)
        args.report.unlink()
        with patch.object(qual, "__file__", str(cli)):
            (scorer / qual.SCORER[0]).write_text(malicious)
            with self.assertRaisesRegex(ValueError, "protected pin"):
                qual.attest(args)
            self.assertFalse(marker.exists())
            args.scorer_dir = checkout
            with self.assertRaisesRegex(ValueError, "outside candidate"):
                qual.attest(args)
            args.scorer_dir = scorer
            (scorer / qual.SCORER[0]).write_text(trusted)
            (evidence / "observer.json").write_text("substituted observation")
            with self.assertRaisesRegex(ValueError, "protected pin"):
                qual.attest(args)
            self.assertFalse(args.report.exists())

    def test_missing_renamed_arbitrary_and_false_gates_hold(self):
        gates = qual.required_gates() | {"registered-case/current-intent"}
        expected = dict.fromkeys(gates, True)
        self.report["checks"] = expected
        args = (self.head, self.expected_pins, gates)
        self.assertTrue(qual.qualified_report(json.dumps(self.report).encode(), *args))
        for checks in ({"test": True}, dict(expected, **{f"{qual.COMPARISON_MODE}/warm/first/p95/relative": False}),
                       {k:v for k,v in expected.items() if k != "registered-case/current-intent"},
                       {("replaced" if k == "linux/oryx-codex/privacy/revoke" else k):v for k,v in expected.items()}):
            with self.assertRaisesRegex(ValueError, "required named gate"):
                qual.qualified_report(json.dumps(dict(self.report, checks=checks)).encode(), *args)

    def test_report_cannot_relabel_an_old_study_or_assert_parity_without_captures(self):
        args = (self.head, self.expected_pins, qual.required_gates())
        for changes in ({"protocol":"v1"}, {"comparison_mode":"native"}, {"results":{"shared_core":True}},
                        {"results":{"shared_core":{}}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                qual.qualified_report(json.dumps(dict(self.report, **changes)).encode(), *args)
        proof = self.report["results"]["shared_core"]
        proof["macos"]["capture_sha256"] = proof["linux"]["capture_sha256"]
        with self.assertRaisesRegex(ValueError, "own capture"):
            qual.qualified_report(json.dumps(self.report).encode(), *args)

    def test_signed_scorer_needs_measured_codex_results_even_with_all_boolean_gates(self):
        args = (self.head, self.expected_pins, qual.required_gates())
        with self.assertRaisesRegex(ValueError,"Codex measurements"):
            qual.qualified_report(json.dumps(dict(self.report, results={"shared_core":self.report["results"]["shared_core"]})).encode(), *args)
        self.report["results"]["performance"]["warm/complete/p95"]["native_absolute_upper_ms"] = 200
        with self.assertRaisesRegex(ValueError,"Codex measurements"):
            qual.qualified_report(json.dumps(self.report).encode(), *args)
