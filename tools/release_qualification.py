"""Bind a private stakeholder study to the reviewed release using a detached reviewer signature."""

import argparse
import base64
import binascii
from fnmatch import fnmatchcase
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SHA = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"[a-f0-9]{64}")
VERSION = re.compile(r"(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){2}", re.ASCII)
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
TITLE = "Stakeholder qualification"
SCORER = ("stakeholder_release.py", "stakeholder_statistics.py", "stakeholder_corpus.py")
PINS = ("manifest_sha256", "registration_sha256", "scorer_sha256", "evidence_sha256")
# This contract belongs to the independent reviewer. A scorer cannot rename its own obligations.
INTEGRATION = {
    "adapter": "meeting chat second-subscriber reverse-order grants-before-dispatch slow-failure-retry foreground span-at-preview-and-apply",
    "storage": "existing-new source-wording-destination-revision concurrent-accept identity-only hundred-unrelated model-input scoped-readiness follow-up",
    "handoffs": "concurrent-offers lost-ack defer-replay skip-return-mute feedback-consent authorized-issue-retry recording-transport",
    "continuity": "hard-kill-cross-client no-history-two-days similar-open-tasks parent-revision missing-partial-events four-settings silent-journal tip-mute-compaction",
    "privacy": "off-record profile-refusal expired other-studio model-input-and-reads backup-restore-feedback revoke backfill-opt-out purge-race retention quiet",
    "install": "protected-launch fresh-format2 format1 0.13-to-0.14 supported-upgrade optional-setup existing-grants native-capture recovery",
}


def required_gates():
    arms = ("oryx-codex", "oryx-claude")
    families = ("preferences", "decisions", "attribution", "identity", "boundaries", "reuse")
    gates = {f"{host}/{arm}/{group}/{test}" for host in ("linux", "macos", "wsl2") for arm in arms
             for group, tests in INTEGRATION.items() for test in tests.split()}
    gates.update(f"{arm}/known-answer" for arm in (*arms, "ref-claude"))
    gates.update(f"{arm}/{family}/{measure}" for arm in arms for family in ("overall", *families)
                 for measure in ("precision", "recall"))
    gates.update(f"{arm}/{workflow}/coaching" for arm in arms
                 for workflow in ("setup", "update", "conversation", "draft", "rehearsal"))
    gates.update(f"{family}/agreement" for family in families)
    for group in ("warm", "cold"):
        gates.add(group + "/turns")
        for metric in ("first", "complete"):
            gates.add(f"{group}/{metric}/p50/relative")
            gates.update(f"{group}/{metric}/p95/{rule}" for rule in ("relative", "absolute", "subscriber"))
    return gates
FEATURE = (
    "tools/stakeholder*.py", "tools/profile_retrieval.py", "tools/onboarding_profile_step.py",
    "tools/evidence_spans.py", "tools/source_evidence.py", "tools/ingestion*.py", "tools/offer_queue.py",
    "tools/*handoff*.py", "tools/session_journal.py", "tools/journal_*.py", "tools/context_advice.py",
    "tools/turn_intent.py", "tools/release_qualification.py", "tests/evals/stakeholder*",
    "tests/test_stakeholder*.py", "tests/test_profile_onboarding.py", "tests/test_profile_retrieval.py", "tests/test_profile_suggestions.py",
    "tests/test_profile_session_hooks.py", "tests/test_ingestion*.py", "tests/test_offer*.py",
    "tests/test_session_journal.py", "tests/test_context_advice.py", "tests/test_release_qualification.py",
    "playbook/stakeholder*.md", "playbook/ingestion.md", "playbook/handoffs.md", "playbook/context-advice.md",
    "playbook/session-continuity.md", "templates/stakeholder*.md", ".agents/skills/stakeholder-profiles/*",
    ".claude/skills/stakeholder-profiles/*",
)
SHARED = {
    "tools/agent_session.py", "tools/hook.py", "tools/pm.py", "tools/task_context.py", "tools/onboarding.py",
    "tools/onboarding_review.py", "tools/context_capture.py", "tools/overrides.py", "tools/release_review.py",
    "tools/publish_release.py", ".github/workflows/release.yml", ".github/workflows/review.yml",
    ".claude/settings.json", ".codex/hooks.json", "playbook/workflow-defaults.json", "playbook/commands.json",
    ".agents/skills/pm/SKILL.md", ".agents/skills/ingest-context/SKILL.md",
    ".claude/skills/pm/SKILL.md", ".claude/skills/ingest-context/SKILL.md", "tests/evals/release-review-catalog.json",
}
FEATURE_LINE = re.compile(r"stakeholder|profile[-_]suggest|journal|off[- ]the[- ]record|handoff|ingestion|"
                          r"context[-_]advice|release_qualification|oryx_study|postcompact|postmodelrequest|"
                          r"offer_queue|optional[-_]offer|turn_intent|off_record|native_event|prompt_cache", re.I)


def affected(files):
    for row in files.values():
        for name in (row["filename"], row.get("previous_filename", "")):
            if any(fnmatchcase(name, pattern) for pattern in FEATURE):
                return True
            if name in SHARED:
                patch = row.get("patch")
                # GitHub can omit or truncate a diff. A partial edit cannot rule out feature impact.
                if not isinstance(patch, str) or FEATURE_LINE.search(patch):
                    return True
                lines = patch.splitlines()
                if (sum(line.startswith("+") for line in lines) != row.get("additions")
                        or sum(line.startswith("-") for line in lines) != row.get("deletions")):
                    return True
    return False


def read_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate qualification field")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def expect(pattern, value, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"Invalid qualification {label}")
    return value


def canonical(receipt):
    return (json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def claims(repo, head, version, pins, artifact):
    if set(pins) != set(PINS):
        raise ValueError("Register the fixture, study, trusted scorer and captured evidence pins")
    return {"schema": "oryx-stakeholder-qualification/v2", "decision": "PASS",
            "repository": expect(REPO, repo, "repository"), "candidate": expect(SHA, head, "candidate"),
            "version": expect(VERSION, version, "release version"),
            **{key: expect(DIGEST, pins[key], key) for key in PINS},
            "artifact_sha256": expect(DIGEST, artifact, "artifact")}


def qualified_report(data, head, pins, gates):
    report = read_json(data)
    if (not isinstance(report, dict) or report.get("decision") != "PASS" or report.get("failed") != []
            or report.get("candidate") != head or report.get("manifest_sha256") != pins["manifest_sha256"]
            or report.get("registration_sha256") != pins["registration_sha256"]
            or not isinstance(report.get("checks"), dict) or not required_gates() <= gates <= report["checks"].keys()
            or any(value is not True for value in report["checks"].values())
            or not isinstance(report.get("results"), dict) or not report["results"]):
        raise ValueError("The pinned evaluator must report PASS on every required named gate for this candidate and study")
    return sha256(data).hexdigest()


def extract(body):
    sections = re.findall(r"^## " + TITLE + r"[ \t]*\n(.*?)(?=^## |\Z)", (body or "").replace("\r\n", "\n"),
                          re.M | re.S)
    if len(sections) != 1:
        raise ValueError("Supply one signed Stakeholder qualification section for this head")
    match = re.fullmatch(r"\s*```json\n([^\n]+)\n```\s*", sections[0])
    if not match or len(match[1]) > 8192:
        raise ValueError("Supply the complete signed stakeholder qualification receipt")
    envelope = read_json(match[1])
    if (not isinstance(envelope, dict) or set(envelope) != {"receipt", "signature"}
            or not isinstance(envelope["receipt"], dict) or not isinstance(envelope["signature"], str)):
        raise ValueError("Invalid signed qualification envelope")
    return envelope


def verify(body, public, repo, head, version, pins, *, artifact=None):
    envelope = extract(body)
    receipt = envelope["receipt"]
    expected = claims(repo, head, version, pins, artifact or receipt.get("artifact_sha256"))
    if receipt != expected:
        raise ValueError("Qualification differs from the reviewed repository, head, version, study, or artifact")
    if not public or len(public) > 8192 or not public.strip().startswith("-----BEGIN PUBLIC KEY-----"):
        raise ValueError("Configure the independent reviewer's public key outside the checkout")
    try:
        signature = base64.b64decode(envelope["signature"], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid qualification signature encoding") from exc
    with tempfile.TemporaryDirectory() as name:
        key, sig = Path(name) / "reviewer.pem", Path(name) / "pass.sig"
        key.write_text(public, encoding="ascii")
        sig.write_bytes(signature)
        result = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(key), "-signature", str(sig)],
                                input=canonical(expected), env={"PATH": os.defpath}, capture_output=True, timeout=10)
        if result.returncode:
            raise ValueError("Independent reviewer signature failed verification")
    return expected


def check(pr, files, api):
    if not affected(files):
        return
    head = expect(SHA, pr["head"]["sha"], "candidate")
    pins = read_json(os.environ.get("ORYX_STUDY_PINS") or "{}")
    pin = pins.get(head) if isinstance(pins, dict) else None
    if not isinstance(pin, dict) or set(pin) != set(PINS):
        raise ValueError("Register the independent fixture, study, scorer and evidence pins for this head")
    meta = api("contents/playbook/release.json?ref=" + head)
    if meta.get("encoding") != "base64":
        raise ValueError("Missing release metadata at the reviewed head")
    data = read_json(base64.b64decode("".join(meta["content"].split()), validate=True))
    verify(pr.get("body"), os.environ.get("ORYX_STUDY_REVIEWER_PUBLIC_KEY"), os.environ["GITHUB_REPOSITORY"],
           head, data["system_version"], pin)


def private_path(path):
    real = path.absolute()
    if real.resolve() != real or any((parent / ".git").is_file() or (parent / ".git/HEAD").is_file()
                                    for parent in (real, *real.parents)):
        raise ValueError("Use a private reviewer installation and study paths outside candidate checkouts")
    return real


def scorer_bundle(folder):
    folder = private_path(folder)
    parts = {}
    for name in (*SCORER, "required-gates.json"):
        path = private_path(folder / name)
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Incomplete protected scorer installation")
        parts[name] = path.read_bytes()
    names = read_json(parts["required-gates.json"])
    if (not isinstance(names, list) or not all(isinstance(name, str) and name for name in names)
            or len(set(names)) != len(names) or not required_gates() <= set(names)):
        raise ValueError("Register every required named gate in the independent scorer bundle")
    index = {name: sha256(data).hexdigest() for name, data in parts.items()}
    return sha256(canonical(index)).hexdigest(), parts, set(names)


def evidence_digest(folder):
    folder = private_path(folder)
    if not folder.is_dir():
        raise ValueError("Supply the captured evidence directory")
    files = {}
    for directory, children, names in os.walk(folder, onerror=raise_io):
        for name in children + names:
            path = Path(directory, name)
            if path.is_symlink():
                raise ValueError("Snapshot regular files in the protected evidence bundle")
        for name in names:
            path = Path(directory, name)
            if not path.is_file():
                raise ValueError("Snapshot regular files in the protected evidence bundle")
            hasher = sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(block)
            files[path.relative_to(folder).as_posix()] = hasher.hexdigest()
    if not files:
        raise ValueError("The captured evidence bundle is empty")
    return sha256(canonical(files)).hexdigest()


def raise_io(exc):
    raise exc


def score(bundle, frozen, evidence, pins):
    # Copy only authenticated module bytes. Never put the input directory or candidate on sys.path.
    bootstrap = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
                 "sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')")
    with tempfile.TemporaryDirectory() as temp:
        cases = Path(temp) / "tests/evals"
        cases.mkdir(parents=True)
        for name in SCORER:
            (cases / name).write_bytes(bundle[name])
        return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", bootstrap, str(cases), str(cases / SCORER[0]),
                               str(frozen), pins["manifest_sha256"], str(evidence), pins["registration_sha256"]],
                              cwd=temp, env={"PATH": os.defpath}, stdout=subprocess.PIPE)


def attest(args):
    # This entry point runs from the reviewer's independently installed copy, outside every checkout.
    private_path(Path(__file__))
    scorer, frozen, evidence, report, key = map(private_path, (
        args.scorer_dir, args.frozen, args.evidence, args.report, args.signing_key))
    if any(report.is_relative_to(folder) or key.is_relative_to(folder) for folder in (scorer, frozen, evidence)):
        raise ValueError("Keep private reports and the signing identity outside scorer and study inputs")
    pins = args_pins(args)
    claims(args.repository, args.head, args.version, pins, "0" * 64)
    actual, bundle, gates = scorer_bundle(scorer)
    if actual != pins["scorer_sha256"] or evidence_digest(evidence) != pins["evidence_sha256"]:
        raise ValueError("The independent scorer or captured evidence differs from its protected pin")
    if (sha256(private_path(frozen / "manifest.json").read_bytes()).hexdigest() != pins["manifest_sha256"] or
            sha256((evidence / "registration.json").read_bytes()).hexdigest() != pins["registration_sha256"]):
        raise ValueError("The frozen fixture or study registration differs from its protected pin")
    process = score(bundle, frozen, evidence, pins)
    with os.fdopen(os.open(report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as target:
        target.write(process.stdout)
    if process.returncode:
        raise ValueError("Study held. Inspect the private evaluator report")
    artifact = qualified_report(process.stdout, args.head, pins, gates)
    if evidence_digest(evidence) != pins["evidence_sha256"]:
        raise ValueError("Captured evidence changed during scoring")
    receipt = claims(args.repository, args.head, args.version, pins, artifact)
    signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key)],
                               input=canonical(receipt), env={"PATH": os.defpath}, stdout=subprocess.PIPE, check=True).stdout
    envelope = {"receipt": receipt, "signature": base64.b64encode(signature).decode()}
    print("## " + TITLE + "\n\n```json\n" + json.dumps(envelope, sort_keys=True) + "\n```")


def args_pins(args):
    return dict(zip(PINS, (args.manifest, args.registration, args.scorer_digest, args.evidence_digest)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    ops = parser.add_subparsers(dest="operation", required=True)
    sign = ops.add_parser("attest", help="Run the independently installed scorer and sign a verified pass")
    check = ops.add_parser("verify", help="Compare a signed receipt with private evidence and independent pins")
    ops.add_parser("required-gates", help="List the minimum registered gate names")
    fingerprint = ops.add_parser("fingerprint", help="Hash a private scorer installation or captured evidence directory")
    fingerprint.add_argument("kind", choices=("scorer", "evidence"))
    fingerprint.add_argument("path", type=Path)
    for cmd in (sign, check):
        for field in ("repository", "head", "version", "manifest", "registration", "scorer-digest", "evidence-digest"):
            cmd.add_argument("--" + field, required=True)
        for field in ("report", "scorer-dir", "evidence"):
            cmd.add_argument("--" + field, type=Path, required=True)
    for flag in ("frozen", "signing-key"):
        sign.add_argument("--" + flag, type=Path, required=True)
    for flag in ("receipt", "public-key"):
        check.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "required-gates":
        print(json.dumps(sorted(required_gates()), indent=2))
    elif args.operation == "fingerprint":
        print(scorer_bundle(args.path)[0] if args.kind == "scorer" else evidence_digest(args.path))
    elif args.operation == "attest":
        attest(args)
    else:
        pins = args_pins(args)
        digest, _, gates = scorer_bundle(args.scorer_dir)
        if digest != pins["scorer_sha256"] or evidence_digest(args.evidence) != pins["evidence_sha256"]:
            raise ValueError("Independent scorer or captured evidence differs from its pin")
        artifact = qualified_report(args.report.read_bytes(), args.head, pins, gates)
        verify(args.receipt.read_text(), args.public_key.read_text(), args.repository, args.head, args.version,
               pins, artifact=artifact)
        print("Verified signed stakeholder release evidence.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as exc:
        sys.exit("Stakeholder qualification failed: " + str(exc))
