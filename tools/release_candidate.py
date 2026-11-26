"""Describe the tree tested by PR CI and enforce a fresh release version."""

from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import subprocess

import workspace

METADATA = "playbook/release.json"
VERSION = re.compile(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}")


def version_at(ref):
    data = workspace.validate_release(json.loads(workspace.git(Path.cwd(), "show", f"{ref}:{METADATA}")))
    value = data["system_version"]
    if not VERSION.fullmatch(value):
        raise ValueError("Use a canonical numeric major.minor.patch version")
    return value


def candidate_version(base, head):
    previous, current = version_at(base), version_at(head)
    if tuple(map(int, current.split("."))) <= tuple(map(int, previous.split("."))):
        raise ValueError(f"Increase system_version above {previous}")
    return current


def needs_native(paths):
    # Diff both sides of renames so moving a platform-sensitive file still runs macOS.
    patterns = (
        ".github/workflows/*", ".codex/*", ".claude/hooks/*", ".claude/settings.json",
        "playbook/workspace-format.json", "tools/workspace-seed/*", "tools/conversion.py",
        "tools/context_*.py", "tools/task_context.py", "tools/search_model/*", "tests/test_context_search.py",
        "tools/git_ops.py", "tools/hook.py", "tools/layout*.py", "tools/pm.py", "tools/snapshots.py",
        "tools/agent_session.py", "tools/studio_layout.py", "tests/test_studio_contract.py", "tests/test_studio_layout.py",
        "tools/overrides.py", "tools/company_source.py", "tools/customizations.py", "tests/test_overrides.py",
        "tools/storage.py", "tools/upgrades.py", "tools/workspace.py", "tools/release_*.py",
        "tools/publish_release.py", "tests/test_alignment.py", "tests/test_filing.py", "tests/test_pm.py",
        "tests/test_repositories.py", "tests/test_release.py", "tests/test_publication.py",
        "tests/test_client_core_parity.py", "tools/ingestion_signals.py", "tools/stakeholder*.py",
        "tools/source_evidence.py", "tools/evidence_spans.py", "tools/profile_retrieval.py",
        ".agents/skills/stakeholder-profiles/*", ".claude/skills/stakeholder-profiles/*",
        "tests/test_layout*.py", "tests/test_*_upgrade.py",
    )
    return any(fnmatchcase(path, pattern) for path in paths for pattern in patterns)


if __name__ == "__main__":
    base = os.environ["BASE_SHA"]
    version = candidate_version(base, "HEAD")
    if workspace.git(Path.cwd(), "tag", "--list", "v" + version):
        raise ValueError(f"Tag v{version} already exists")
    paths = subprocess.check_output(["git", "diff", "--name-only", "--no-renames", "-z", base, "HEAD"])
    print("native=" + str(needs_native(os.fsdecode(paths).split("\0"))).lower())
    print("tree=" + workspace.git(Path.cwd(), "rev-parse", "HEAD^{tree}"))
