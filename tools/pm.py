"""Check PM Hub and generate its Claude skill adapters. Python 3.9+, standard library."""

from __future__ import annotations

import argparse
import json
import os
import sys
from html import unescape
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

import records
import red_team_eval
import workspace
import git_ops
import context_capture
import task_context
import metric_checks
import metric_registry
import storage
import snapshots
from storage import inventory
import upgrades
import filing
import conversion
import layout
import layout_upgrade
import opportunities
import pm_profile
import preferences
import hub_commands
import initiatives_cli
import initiative_store
import initiative_views
import initiative_work
import experiment_drafts

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "AGENTS.md", "CLAUDE.md", "README.md", ".gitignore",
    "tools/pm.py", "tools/hook.py", "tools/workspace.py", "tools/git_ops.py",
    "tools/layout.py", "tools/layout_upgrade.py", "tools/pm_profile.py", "playbook/workspace-format.json", "tools/filing.py", "tools/conversion.py", "tools/snapshots.py", "playbook/filing.md", "playbook/writing.md",
    "tools/context_capture.py", "tools/evidence_reviews.py", "playbook/evidence-reviews.md", "tools/task_context.py", "tools/metric_checks.py", "tools/storage.py", "tools/upgrades.py",
    "playbook/numbers.md", "playbook/metrics.md", "playbook/saas-metrics.json", "tools/metric_registry.py",
    "tools/preferences.py", ".agents/skills/pm/SKILL.md", ".claude/skills/pm/SKILL.md",
    "tools/hub_commands.py", "playbook/commands.md", hub_commands.CATALOG,
    ".agents/skills/extend-hub/SKILL.md", ".claude/skills/extend-hub/SKILL.md",
    ".agents/skills/ingest-context/SKILL.md", ".claude/skills/ingest-context/SKILL.md",
    ".codex/hooks.json", ".codex/config.toml", ".claude/settings.json",
    ".github/workflows/release.yml", ".github/workflows/review.yml", "tools/publish_release.py", "tools/release_candidate.py",
    ".github/workflows/check.yml", ".github/pull_request_template.md", "tools/release_review.py", "tests/test_pm.py",
    "playbook/framework.md", "playbook/working.md", "playbook/context.md", "templates/README.md", "tools/records.py",
    ".agents/skills/red-team/SKILL.md", ".claude/skills/red-team/SKILL.md",
    "playbook/git.md", "playbook/updates.md", "playbook/release.json", "tools/workspace-seed/README.md",
    "tools/workspace-seed/context/README.md", "tools/workspace-seed/workspace/README.md",
    "tools/workspace-seed/.gitignore", "tools/opportunities.py", "tools/brief_review.py", "playbook/opportunities.md",
    "tools/initiative_events.py", "tools/outcome_evidence.py", "tools/initiative_store.py", "tools/initiatives_cli.py", "tools/initiative_views.py",
    "tools/initiative_areas.py", "tools/initiative_intake.py", "tools/experiment_drafts.py",
    "tools/initiative_work.py", "tools/launch_readiness.py", "templates/launch-checklist.json", "playbook/initiative-work.md",
    ".agents/skills/manage-initiative-work/SKILL.md",
    "templates/views/backlog.json", "templates/views/roadmap.json",
    "playbook/initiative-approvals.md", "playbook/initiative-views.md", "playbook/outcome-evidence.md",
    ".agents/skills/manage-backlog/SKILL.md", ".agents/skills/run-discovery/SKILL.md",
    ".agents/skills/run-discovery/plan.md", ".agents/skills/run-discovery/investigate.md",
    ".agents/skills/define-initiative/SKILL.md", ".agents/skills/prioritize-roadmap/SKILL.md",
    "tools/red_team_eval.py", "tests/red-team-evals/cases.json", "tests/red-team-evals/context-guardrails.json",
    "tests/red-team-evals/context-sections.json",
)
ROOT_FILES = {"README.md", "AGENTS.md", "CLAUDE.md", ".gitignore"}
ROOT_DIRS = {"playbook", "templates", "tools", "tests",
             ".agents", ".claude", ".codex", ".github"}
SKILL_SOURCE = Path(".agents/skills")
SKILL_COPY = Path(".claude/skills")
HOOK_SCRIPT = ('from pathlib import Path; import runpy, sys; p=Path.cwd().resolve(); '
               'root=next(p for p in (p, *p.parents) if (p/"playbook/release.json").is_file() '
               'and (p/"tools/hook.py").is_file()); '
               'sys.path.insert(0, str(root/"tools")); '
               'runpy.run_path(str(root/"tools/hook.py"), run_name="__main__")')
CODEX_COMMAND = "python3 -c '" + HOOK_SCRIPT + "'"

ARTIFACT = re.compile(
    r"(?:^|[-_ ])(?:prds?|specs?|specifications?|requirements|user[-_ ]stories|"
    r"user[-_ ]flows|acceptance[-_ ]criteria)(?:$|[-_ ])", re.I)
WORDS = re.compile(r"\b[\w]+(?:['’-][\w]+)*\b")
LINK = re.compile(r"\[([^\]\n]+)\]\((<[^>\n]+>|[^\s)]+)\)")
PROCEDURE_START = re.compile(
    r"^(?:(?:if|when|before|after|unless)\b[^,]*,\s*)?"
    r"(?:add|apply|check|choose|close|compare|confirm|copy|create|enter|file|find|include|inspect|keep|"
    r"link|list|open|preserve|read|record|remove|repeat|replace|restore|review|run|save|select|set|"
    r"specify|start|store|supply|test|update|use|verify|write)\b", re.I)
BANNED = re.compile(r"\b(?:thus|delve|leverage)\b", re.I)


def prose(text: str):
    """Yield prose units; exclude metadata, fences, headings, tables, and quotations."""
    block, start, instruction = [], 0, False
    fence = None
    metadata = text.startswith("---\n")
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if metadata:
            if number > 1 and stripped == "---":
                metadata = False
            continue
        if stripped.startswith(("```", "~~~")):
            if block:
                yield start, " ".join(block), instruction
                block = []
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence:
            continue
        item = re.match(r"^\s*(?:(\d+)[.)]|[-*+])\s+(.+)$", line)
        boundary = not stripped or stripped.startswith(("#", ">", "|", "<!--", "@"))
        if boundary or item:
            if block:
                yield start, " ".join(block), instruction
                block = []
        if boundary:
            continue
        if not block:
            start = number
            instruction = bool(item and item[1])
        block.append(item[2] if item else stripped)
    if block:
        yield start, " ".join(block), instruction


def plain(text: str) -> str:
    text = re.sub(r"`[^`]+`", "code", text)
    text = LINK.sub(lambda match: match[1], text)
    return re.sub(r"https?://\S+", "source", text)


def writing_errors(text: str) -> list[str]:
    errors, total = [], 0
    for line, unit, instruction in prose(text):
        unit = plain(unit)
        total += len(WORDS.findall(unit))
        sentences = re.split(r"(?<=[.!?])\s+", unit)
        if len(sentences) > 6:
            errors.append(f"{line}: paragraph exceeds six sentences")
        for sentence in sentences:
            limit = 20 if instruction or PROCEDURE_START.match(sentence) else 25
            count = len(WORDS.findall(sentence))
            if count > limit:
                errors.append(f"{line}: sentence has {count} words (limit {limit})")
        for word in sorted(set(BANNED.findall(unit))):
            errors.append(f"{line}: replace '{word}' with direct, concrete wording")
    if total > 800:
        errors.append(f"authored prose has {total} words (limit 800); edit repeated detail and apply the filing rules")
    return errors


def link_errors(root: Path, path: Path, text: str, planned=()) -> list[str]:
    errors = []
    fence = None
    metadata = text.startswith("---\n")
    for line, unit in enumerate(text.splitlines(), 1):
        stripped = unit.strip()
        if metadata:
            if line > 1 and stripped == "---":
                metadata = False
            continue
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence:
            continue
        unit = re.sub(r"`[^`]+`", "", unit)
        for match in LINK.finditer(unit):
            target = urlsplit(unescape(match[2].strip("<>")))
            if target.scheme or target.netloc:
                continue
            destination = (path.parent / unquote(target.path)).resolve() if target.path else path.resolve()
            if root != destination and root not in destination.parents:
                errors.append(f"{line}: link leaves PM Hub: {match[2]}")
            elif not destination.exists() and destination not in planned:
                errors.append(f"{line}: broken link: {match[2]}")
    return errors


def skill_errors(root: Path, files: set[Path]) -> list[str]:
    source = root / SKILL_SOURCE
    copies = root / SKILL_COPY
    originals = {p.relative_to(source) for p in files if source in p.parents}
    generated = {p.relative_to(copies) for p in files if copies in p.parents}
    errors = []
    for rel in sorted(originals | generated):
        if rel not in originals:
            errors.append(f"{SKILL_COPY / rel}: no canonical skill source")
        elif rel not in generated or (source / rel).read_bytes() != (copies / rel).read_bytes():
            errors.append(f"{SKILL_COPY / rel}: run python3 tools/pm.py sync-skills")
        if rel.name == "SKILL.md" and rel in originals:
            text = (source / rel).read_text(encoding="utf-8")
            header = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
            name = re.search(r"^name: ([a-z0-9]+(?:-[a-z0-9]+)*)$", header[1], re.M) if header else None
            if not name or name[1] != rel.parent.name or not re.search(r"^description: \S.+$", header[1], re.M):
                errors.append(f"{SKILL_SOURCE / rel}: skill needs a matching name and a description")
    return errors


def guidance_errors(root: Path, texts: dict[str, str]) -> list[str]:
    """Compare the published template and routing tables with the commands they describe."""
    index = "templates/README.md"
    rows, problems = records.table(texts.get(index, ""), "Available templates", ("Template", "Purpose", "Home"))
    errors = [f"{index}: {problem}" for problem in problems]
    indexed = set()
    for name, _, _ in rows:
        for _, target in LINK.findall(name):
            url = urlsplit(target.strip("<>"))
            if not url.scheme and not url.netloc:
                indexed.add((root / "templates" / unquote(url.path)).resolve())
    for kind in records.KINDS:
        if (root / "templates" / f"{kind}.md") not in indexed:
            errors.append(f"{index}: missing index entry for {kind}.md")

    guide = "playbook/context.md"
    rows, problems = records.table(texts.get(guide, ""), "Brief routing topics", ("Scope", "Topics"))
    errors.extend(f"{guide}: {problem}" for problem in problems)
    documented = {}
    for label, topics in rows:
        scope = label.casefold()
        if scope != "shared" and scope not in context_capture.TOPICS:
            errors.append(f"{guide}: unsupported brief scope: {label}")
        documented.setdefault(scope, set()).update(re.findall(r"`([^`]+)`", topics))
    for scope, topics in context_capture.TOPICS.items():
        listed = documented.get(scope, set()) | (set() if scope == "pm" else documented.get("shared", set()))
        for topic in sorted(topics.keys() - listed):
            errors.append(f"{guide}: missing {scope} routing topic: {topic}")
        for topic in sorted(listed - topics.keys()):
            errors.append(f"{guide}: unsupported {scope} routing topic: {topic}")
    return errors


def hook_errors(texts: dict[str, str]) -> list[str]:
    errors = []
    for name in (".codex/hooks.json", ".claude/settings.json"):
        try:
            config = json.loads(texts.get(name, ""))
            if set(config) != {"hooks"}:
                errors.append(f"{name}: keep client configuration limited to the declared hooks")
            hooks = config["hooks"]
            claude = name.startswith(".claude")
            handler = {"type": "command", "command": CODEX_COMMAND, "timeout": 15}
            if claude:
                handler.update(command="python3", args=["-c", HOOK_SCRIPT])
            for event in ("SessionStart", "UserPromptSubmit", "Stop", "PreToolUse"):
                group = {"hooks": [dict(handler, timeout=600 if event == "SessionStart" else 15)]}
                if event == "PreToolUse":
                    group["matcher"] = "Write|Edit|MultiEdit" if claude else "apply_patch"
                elif len(hooks.get(event, [])) != 1 or set(hooks[event][0]) != {"hooks"}:
                    errors.append(f"{name}: {event} must run without a matcher")
                if hooks.get(event) != [group]:
                    errors.append(f"{name}: {event} must call the shared checker once")
        except (ValueError, KeyError, TypeError):
            errors.append(f"{name}: invalid hook configuration")
    if texts.get(".codex/config.toml", "").strip() != 'sandbox_mode = "workspace-write"':
        errors.append(".codex/config.toml: preserve the workspace write boundary")
    return errors


def check_workspace(root: Path, system_texts: dict[str, str]) -> list[str]:
    errors, texts = [], {}
    try:
        private = workspace.repo(root, "workspace")
        workspace.settings(root)
    except (OSError, ValueError) as exc:
        return [f"private/: {exc}"]
    legacy, legacy_structure, structure_review = {}, set(), set()
    retained, original_paths = {}, set()
    try:
        state = upgrades.read_state(private)[1]
        layout_state = layout_upgrade.receipt(private, state)
        retained = layout_state.get("retained", {})
        original_paths = set(layout_state.get("sources", []))
        legacy = state.get(upgrades.RULE)
        if legacy is None:
            legacy = upgrades.candidates(private, inventory)
        originals = original_paths | {name for name, item in legacy.items() if item.get("role") == "source"}
        structure_review = set(upgrades.structure_review(root, private, state, originals))
        for identifier, digest in state.get(upgrades.TRANSACTIONS, {}).items():
            if upgrades.fingerprint(conversion.archive_path(private, identifier)) != digest:
                errors.append(f"private/: missing or changed recovery archive for {identifier}")
        if layout_upgrade.pending(private):
            errors.append("private/: finish the interrupted layout upgrade before sharing changes")
        if conversion.pointer(private).exists():
            errors.append("private/: finish the pending recoverable filing plan before sharing changes")
    except (OSError, ValueError) as exc:
        errors.append(f"private/{upgrades.LEDGER}: {exc}")
    try:
        context_capture.read_remit(private)
    except (OSError, ValueError) as exc:
        errors.append(f"private/{context_capture.REMIT_PATH}: {exc}")
    try:
        metric_registry.history(private)
    except (OSError, ValueError) as exc:
        errors.append(f"private/{metric_registry.PRIVATE}: {exc}")
    try:
        preferences.load(private)
    except (OSError, ValueError) as exc:
        errors.append(f"{preferences.CHECK_PREFIX}{exc}")
    files = inventory(private)
    initiative_work_homes = set()
    for path in files:
        rel = path.relative_to(private).as_posix()
        label = f"private/{rel}"
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
            errors.append(f"{label}: use regular files inside PM Hub")
            continue
        if path.name == ".env" or path.name.startswith(".env.") or "secrets" in path.relative_to(private).parts:
            errors.append(f"{label}: private file must stay outside Git")
            continue
        if not path.is_file():
            continue
        parts = path.relative_to(private).parts
        if rel == metric_registry.PRIVATE:
            continue
        if parts[0] in {"context", "products", "workspace"} and any(part.startswith(".") for part in parts[1:]):
            continue  # Editor metadata and private local files are outside the artifact inventory.
        if len(parts) == 2 and parts[0] == conversion.HISTORY and path.suffix == ".zip" and conversion.IDENTIFIER.fullmatch(path.stem):
            continue
        item = (legacy or {}).get(rel, {})
        is_source = item.get("role") == "source" or "sources" in parts or rel in original_paths
        old_record = item.get("status") in ("pending", "waiting") and item.get("digest") == upgrades.fingerprint(path)
        if rel in retained and retained[rel]["digest"] == upgrades.fingerprint(path):
            old_record = True
        if old_record or rel in structure_review:
            legacy_structure.add(rel)
        if not old_record and not is_source and ((len(parts) == 1 and rel not in {"README.md", ".gitignore", "settings.json", upgrades.LEDGER, conversion.PENDING})
                or (len(parts) > 1 and parts[0] not in {"context", "workspace"})):
            errors.append(f"{label}: use a home from the README placement map")
        managed = opportunities.path_kind(rel)
        execution = layout.initiative_work_identity(rel)
        if execution and not is_source and not old_record:
            initiative_work_homes.add(execution[:2])
        if (not is_source and not old_record and len(parts) > 1 and parts[0] in {"context", "workspace"}
                and path.suffix.lower() != ".md" and not execution and managed not in {"register", "experiment-draft"}):
            errors.append(f"{label}: file original evidence under sources/ and use a supported format for active artifacts")
        if not is_source and not old_record and any(ARTIFACT.search(Path(part).stem) for part in parts):
            errors.append(f"{label}: engineering artifacts belong in the delivery system")
        if path.suffix == ".md":
            try:
                if is_source:
                    continue  # Original evidence can use its own schema, IDs and links.
                content = path.read_text(encoding="utf-8")
                marker = records.MARKER.match(content)
                if not old_record or (marker and marker[1] in records.KINDS and not records.context_location(marker[1], rel)):
                    texts[rel] = content
                try:
                    if not old_record:
                        if rel not in {"README.md", "context/README.md", "workspace/README.md", pm_profile.PATH}:
                            marker = records.MARKER.match(texts[rel])
                            if parts[0] == "context" and not marker:
                                raise ValueError("Use a typed reference in its context entity or retain an original source")
                            if parts[0] == "workspace":
                                if managed in records.OPPORTUNITY_KINDS:
                                    if not marker or marker[1] != managed:
                                        raise ValueError(f"Use the matching {managed} template for this file")
                                elif not layout.valid_work(rel):
                                    raise ValueError("Use a work type and subject from the workspace filing rules")
                                elif parts[1] in layout.WORK_FOLDERS.values() and (not marker or layout.WORK_FOLDERS.get(marker[1]) != parts[1]):
                                    raise ValueError("Use the matching typed artifact for this working folder")
                                elif not marker and rel not in structure_review:
                                    errors.extend(f"{label}: {error}" for error in records.working_errors(content))
                        filing.verify_note(private, rel, texts[rel])
                except ValueError as exc:
                    errors.append(f"{label}: {exc}")
                if not old_record:
                    errors.extend(f"{label}:{e}" for e in writing_errors(content))
                    errors.extend(f"{label}:{e}" for e in link_errors(root, path, content))
            except (OSError, UnicodeError) as exc:
                errors.append(f"{label}: cannot read text: {exc}")
    errors.extend(f"private/{error}" for error in filing.topic_structure_errors(private))
    for required in ("README.md", ".gitignore", "settings.json", "context/README.md", "workspace/README.md"):
        if not (private / required).is_file():
            errors.append(f"private/{required}: required file is missing")
    try:
        registrations = dict(initiative_store.registrations(root))
        errors.extend(f"private/{error}" for error in initiative_work.check(root, initiative_work_homes, registrations))
        errors.extend(f"private/{e}" for e in experiment_drafts.misplaced(private, files, registrations))
        for product, register in registrations.items():
            errors.extend(f"private/{e}" for e in experiment_drafts.check(private, product, register))
            errors.extend(f"private/: {error}" for error in initiative_store.live_errors(root, register))
        errors.extend(f"private/{error}" for error in initiative_store.draft_errors(texts, registrations))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        errors.append(f"private/: {exc}")
    templates = {p: t for p, t in system_texts.items() if p.startswith("templates/")}
    errors.extend(f"private/{e}" for e in records.validate(dict(templates, **texts), legacy_structure=legacy_structure))
    return errors


def check(root: Path = ROOT, include_workspace=True, *, command_base=None) -> list[str]:
    root = root.resolve()
    errors, texts, safe = [], {}, set()
    for path in inventory(root):
        rel = path.relative_to(root).as_posix()
        if Path(rel).parts[0] in {"workspace", "private"}:
            errors.append("private/: PM data must never be tracked by the system repository")
            continue  # do not read data exposed by an incorrect system index
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root):
            errors.append(f"{rel}: use regular files inside PM Hub")
            continue
        if path.name == ".env" or path.name.startswith(".env.") or "secrets" in path.relative_to(root).parts:
            errors.append(f"{rel}: private file must stay outside Git")
            continue  # never read secret contents
        if not path.is_file():
            continue
        safe.add(path)
        parts = path.relative_to(root).parts
        if parts[:2] in hub_commands.NATIVE_COMMAND_DIRS:
            errors.append(f"{rel}: register shared slash actions in {hub_commands.CATALOG}")
            continue
        if (len(parts) == 1 and rel not in ROOT_FILES) or (len(parts) > 1 and parts[0] not in ROOT_DIRS):
            errors.append(f"{rel}: use a home from the README placement map")
        if path.suffix not in (".md", ".json", ".toml") and path.name != ".gitignore":
            continue
        try:
            texts[rel] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{rel}: cannot read text: {exc}")
            continue
        if path.suffix == ".md":
            if any(ARTIFACT.search(Path(part).stem) for part in path.relative_to(root).parts):
                errors.append(f"{rel}: engineering artifacts belong in the delivery system")
            if not rel.startswith(".claude/skills/"):
                errors.extend(f"{rel}:{error}" for error in writing_errors(texts[rel]))
            errors.extend(f"{rel}:{error}" for error in link_errors(root, path, texts[rel]))
            if records.MARKER.match(texts[rel]) and not rel.startswith("templates/"):
                errors.append(f"{rel}: PM records belong inside private/")
    for rel in REQUIRED:
        if root / rel not in safe:
            errors.append(f"{rel}: required file is missing or unsafe")
    if texts.get("CLAUDE.md", "").strip() != "@AGENTS.md":
        errors.append("CLAUDE.md: import AGENTS.md without duplicate instructions")
    errors.extend(skill_errors(root, safe))
    for view in ("backlog", "roadmap"):
        try:
            initiative_views.view_template(root, view)
        except (OSError, ValueError) as exc:
            errors.append(f"templates/views/{view}.json: {exc}")
    try:
        metric_registry.defaults(root)
    except (OSError, ValueError) as exc:
        errors.append(f"{metric_registry.DEFAULTS}: {exc}")
    try:
        initiative_work.template(root)
    except (OSError, ValueError) as exc:
        errors.append(f"{initiative_work.TEMPLATE}: {exc}")
    errors.extend(guidance_errors(root, texts))
    try:
        parser = build_parser()
        catalog = hub_commands.load(root, parser)
        if command_base is not None:
            errors.extend(f"{hub_commands.CATALOG}: {error}" for error in
                          hub_commands.compatibility_errors(root, command_base, catalog, parser))
    except (OSError, ValueError) as exc:
        errors.append(f"{hub_commands.CATALOG}: {exc}")
    errors.extend(hook_errors(texts))
    errors.extend(records.validate(texts))
    if not {"/workspace/", "/private/"} <= set(texts.get(".gitignore", "").splitlines()):
        errors.append(".gitignore: exclude /workspace/ and /private/ from the system repository")
    try:
        workspace.release(root)
    except (OSError, ValueError) as exc:
        errors.append(f"playbook/release.json: {exc}")
    if include_workspace:
        errors.extend(check_workspace(root, texts))
    return errors


def sync_skills(root: Path = ROOT) -> int:
    root = root.resolve()
    changed = 0
    for path in inventory(root):
        source = root / SKILL_SOURCE
        if source not in path.parents:
            continue
        if path.name == ".env" or path.name.startswith(".env.") or "secrets" in path.relative_to(source).parts:
            raise ValueError("Private files cannot be skill payloads")
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
            raise ValueError("Skill sources must use regular files")
        target = root / SKILL_COPY / path.relative_to(source)
        if target.is_symlink() or any(p.is_symlink() for p in target.parents if p != root):
            raise ValueError("Skill copies must use regular files")
        if target.exists() and path.read_bytes() == target.read_bytes():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        changed += 1
    return changed


def filing_validator(root, *, legacy_replay=False, legacy_structure=False):
    private = workspace.private_root(root)
    def validate(edits, folds, archive, originals):
        changes = set(folds) | {name for name, row in edits.items() if row["text"].encode("utf-8") != originals[name]}
        governed = {name for name in changes if opportunities.path_kind(name) in records.OPPORTUNITY_KINDS}
        if governed and not (legacy_replay or legacy_structure):
            for product in initiative_store.products(root):
                _, payload, _ = initiative_store.read(root, product)
                for event in payload["events"]:
                    reference = event.get("references", {})
                    if reference.get("path") in governed and "sha256" in reference:
                        raise ValueError(f"{reference['path']} binds signed evidence. Use the initiative review workflow.")
        texts = {f"templates/{kind}.md": (root / f"templates/{kind}.md").read_text() for kind in records.KINDS}
        for path in inventory(private):
            if path.suffix.lower() == ".md" and path.is_file() and path.resolve() == path:
                name = path.relative_to(private)
                if not any(p.startswith(".") or p == "secrets" for p in name.parts):
                    texts[name.as_posix()] = path.read_text(encoding="utf-8")
        previous = set(records.validate(texts))
        for name, row in folds.items():
            texts.pop(name, None)
            target = edits[row["into"]]["text"]
            if not records.MARKER.match(target):
                raise ValueError("Fold into a typed owning brief or work artifact")
            marker = records.MARKER.match(originals[name].decode("utf-8").replace("\r\n", "\n"))
            if marker and edits[row["into"]]["before"] == "absent":
                if records.work_state(originals[name].decode())[0].get("ID") != records.work_state(target)[0].get("ID"):
                    raise ValueError("Preserve the stable ID when moving a typed record")
        problems = []
        for name, row in edits.items():
            text = row["text"]
            old = originals[name].decode("utf-8").replace("\r\n", "\n")
            marker = records.MARKER.match(old)
            if marker and (not text.startswith(marker[0]) or records.work_state(old)[0].get("ID") != records.work_state(text)[0].get("ID")):
                raise ValueError(f"Preserve the record kind and stable ID in {name}")
            if row["before"] == "absent":
                new_kind = records.MARKER.match(text)
                if not new_kind:
                    raise ValueError("New filing destinations must use an appropriate record template")
                if not legacy_replay:
                    filing.check_new(private, new_kind[1], name, None, retiring=folds)
            if not legacy_replay:
                filing.verify_note(private, name, text)
                if not legacy_structure and not records.MARKER.match(text) and layout.valid_work(name):
                    problems.extend(f"{name}: {error}" for error in records.working_errors(text))
            texts[name] = text
            problems.extend(writing_errors(text) + link_errors(root, private / name, text, planned={archive, *(private / target for target in edits)}))
        conversion.verify_fragments(private, texts, edits, LINK)
        if not legacy_replay:
            for error in records.validate(texts, legacy_structure=texts if legacy_structure else ()):
                if error not in previous or error.partition(":")[0] in edits:
                    problems.append(error)
        if problems:
            raise ValueError("Invalid filing result: " + " | ".join(problems[:8]))
    return validate


def alignment(root, prepare=False, record=None, outcome=None, digest=None, note=None, backup=None, for_conversion=False):
    def inspect(private):
        layout_upgrade.require_supported_registers(private)
        settings_file = private / "settings.json"
        original = settings_file.read_text(encoding="utf-8")
        settings = workspace.settings(root, compatible=False)
        release = workspace.release(root)
        old_layout = settings["workspace_format"] == 1
        changing = any(settings[key] != value for key, value in release.items())
        if not workspace.supports_update(settings, release):
            raise ValueError("Unsupported workspace version; inspect release compatibility before updating")
        moving = private.name == "workspace"
        if moving:
            workspace.check_relocation(root, private)
        review_pending = conversion.pointer(private).exists()
        state = upgrades.read_state(private)[1]
        layout_upgrade.receipt(private, state)
        recovery = None
        # Old filing transactions must finish with their accepted paths before layout planning.
        if prepare and (changing or old_layout or moving or review_pending or record or for_conversion
                        or upgrades.RULE not in state or not upgrades.scan_marker(private).exists()):
            recovery = snapshots.ensure(root, release["system_version"], layout_change=old_layout or moving)
        if prepare and review_pending:
            validator = filing_validator(root, legacy_replay=old_layout, legacy_structure=upgrades.STRUCTURE_RULE not in state)
            conversion.resume(private, validator, LINK, legacy=old_layout)
        result = upgrades.run(private, inventory, prepare=prepare, record=record, outcome=outcome, digest=digest, note=note)
        if review_pending and not prepare:
            layout_plan = {"moves": {}, "outstanding": [], "changed": False, "awaiting_filing_recovery": True}
        else:
            layout_plan = layout_upgrade.run(private, apply=False)
        if prepare:
            if layout_plan["changed"] or layout_upgrade.pending(private):
                if not recovery:
                    recovery = snapshots.ensure(root, release["system_version"], layout_change=True)
                layout_plan = layout_upgrade.run(private, apply=True)
            if layout_plan.get("moves"):
                # The earlier review ledger may contain paths rewritten by the layout migration.
                result["outstanding"] = upgrades.run(private, inventory)["outstanding"]
            if changing:
                settings.update(release)
                storage.replace_text(settings_file, original, json.dumps(settings, indent=2) + "\n")
        result["layout"] = layout_plan
        result["structure_review"] = upgrades.align_structure(root, private, prepare=prepare)
        pending = {item["path"]: item for item in result["outstanding"]}
        for item in layout_plan["outstanding"]:
            pending.setdefault(item["path"], item)
        result["outstanding"] = list(pending.values())
        result["needs_setup"] |= (
            changing or moving or layout_plan["changed"] or review_pending or result["structure_review"]["needs_scan"]
        ) and not prepare
        if recovery:
            result["installation_backup"] = str(recovery)
        if backup:
            result["backups"] = upgrades.backup(private, backup)
        if moving:
            result["private_root_move"] = {"from": "workspace", "to": "private"}
        return result

    if not prepare:
        return inspect(workspace.repo(root, "workspace"))
    # Resolve the private path after locking the outer checkout. A second client can
    # enter during the directory rename and must pick up the same private Git history.
    with storage.repository_lock(root):
        private = workspace.repo(root, "workspace")
        with storage.repository_lock(private):
            result = inspect(private)
        if private.name == "workspace":
            workspace.relocate_private(root, private)
        return result


def prepare_private_write(root):
    private = workspace.repo(root, "workspace")
    settings = workspace.settings(root, compatible=False)
    state = upgrades.read_state(private)[1]
    if (private.name == "workspace" or any(settings[key] != value for key, value in workspace.release(root).items())
            or not layout_upgrade.complete(private) or layout_upgrade.pending(private)
            or not {upgrades.RULE, upgrades.STRUCTURE_RULE} <= set(state) or conversion.pointer(private).exists()):
        alignment(root, prepare=True)
    return workspace.settings(root)


def alignment_notice(root, result=None):
    try:
        if not workspace.private_root(root).exists():
            return ""
        if result is None:
            result = alignment(root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return f"Workspace alignment unavailable: {exc}"
    items = result["outstanding"]
    review = result["structure_review"]
    notices = []
    if result["needs_setup"] or items:
        notices.append(f"Workspace update has {len(items)} earlier review item(s). Follow playbook/updates.md. "
                       "Inspect and explain the evidence. Seek the user's choice before transforming existing artifacts.")
    if review["offer_handoff"] or review["needs_scan"] or review["records"]:
        notices.append(f"Artifact audit found {len(review['records'])} existing record(s) with format differences. "
                       "Read .agents/skills/review-hub-upgrade/SKILL.md and run align --status for paths and findings. "
                       "Explain the benefits and expected improvements. Offer to leave artifacts in place or review a "
                       "conversion preview. Apply only the plan the user explicitly approves. "
                       "Respect any choice already recorded for this update.")
    return "\n".join(notices)



def capture_errors(root, target, text):
    private = workspace.private_root(root)
    rel = target.relative_to(private).as_posix()
    texts = {f"templates/{kind}.md": (root / "templates" / f"{kind}.md").read_text(encoding="utf-8")
             for kind in records.KINDS}
    for path in inventory(private):
        parts = path.relative_to(private).parts
        if (path != target and path.suffix == ".md" and path.resolve() == path and path.is_file()
                and not any(part == "secrets" or part.startswith(".") for part in parts)):
            with path.open("rb") as stream:
                if records.MARKER.match(stream.readline(128).decode("utf-8", errors="replace")):
                    stream.seek(0)
                    texts[path.relative_to(private).as_posix()] = stream.read().decode("utf-8")
    texts[rel] = text
    errors = [error for error in records.validate(texts) if error.startswith(rel + ":")]
    if text.startswith("<!-- pm: product-area-context -->\n"):
        filing.verify_note(private, rel, text)
    return errors + writing_errors(text) + link_errors(root, target, text)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("action", help="Discover and run published PM Hub actions")
    preferences.add_commands(commands)
    checks = commands.add_parser("check")
    checks.add_argument("--system-only", action="store_true")
    checks.add_argument("--command-base", metavar="COMMIT", help="Check published slash actions against a base commit")
    align = commands.add_parser("align", help="Prepare or resume the private context upgrade")
    align.add_argument("--status", action="store_true", help="Read-only preview")
    plans = align.add_mutually_exclusive_group()
    plans.add_argument("--preview-plan", action="store_true", help="Check a filing plan from stdin")
    plans.add_argument("--apply-plan", action="store_true", help="Apply a recoverable filing plan from stdin")
    align.add_argument("--record")
    align.add_argument("--outcome", choices=("reviewed", "waiting", "source"))
    align.add_argument("--digest")
    align.add_argument("--note")
    align.add_argument("--backup", nargs="+", metavar="PATH")
    commands.add_parser("sync-skills")
    new = commands.add_parser("new")
    new.add_argument("kind", choices=(*records.KINDS, "pm-context"))
    new.add_argument("path", help="Path inside private/, starting with context/ or workspace/")
    new.add_argument("--title")
    new.add_argument("--parent")
    new.add_argument("--basis", choices=filing.BASES)
    new.add_argument("--topic-question")
    new.add_argument("--topic-peer")
    new.add_argument("--reason")
    new.add_argument("--trigger")
    initiatives_cli.add_commands(commands)
    initiative_work.add_commands(commands)
    route = commands.add_parser("route-context", help="Route supplied context evidence from JSON on stdin")
    route.add_argument("--write", metavar="PATH", help="Apply entries to one authorised context record")
    area = commands.add_parser("area-context", help="Locate a product area's context and its source records")
    area.add_argument("product")
    area.add_argument("area")
    task = commands.add_parser("task-context", help="Read scoped guidance for a workspace task")
    task.add_argument("prompt", nargs="?", default="")
    task.add_argument("--product", type=layout.slug)
    task.add_argument("--area", type=layout.slug)
    task.add_argument("--initiative", type=layout.slug)
    task.add_argument("--company", action="store_true")
    task.add_argument("--history", action="store_true", help="Include recorded risk dispositions in this scope")
    commands.add_parser("catalog", help="List private records by title, type, state, and scope")
    commands.add_parser("check-metric", help="Check a numerical claim from JSON on stdin")
    metrics = commands.add_parser("metric", help="Read and maintain the business metric registry")
    metric_commands = metrics.add_subparsers(dest="operation", required=True)
    for operation in ("list", "show", "set"):
        metric = metric_commands.add_parser(operation)
        if operation != "list":
            metric.add_argument("id", type=layout.slug)
        metric.add_argument("--product", type=layout.slug)
        if operation == "set":
            metric.add_argument("--write", action="store_true", help="Save the PM-confirmed definition")
        else:
            metric.add_argument("--as-of")
    commands.add_parser("set-remit", help="Save a PM-confirmed remit from JSON on stdin")
    initialise = commands.add_parser("init-workspace")
    initialise.add_argument("--owner", default="")
    initialise.add_argument("--delivery-system", default="Delivery workspace")
    git = commands.add_parser("git")
    git.add_argument("role", choices=("system", "workspace"))
    git.add_argument("operation", choices=("status", "fetch", "pull", "push"))
    red_team_eval.register(commands)
    return parser


def main() -> int:
    try:
        argv = sys.argv[1:]
        if argv[:1] == ["action"]:
            argv = hub_commands.route(ROOT, argv[1:])
            if argv is None:
                return 0
        args = build_parser().parse_args(argv)
        if hasattr(args, "hub_action"):
            args.hub_action(ROOT, args, prepare_private_write)
            return 0
        if args.command == "align":
            if args.preview_plan or args.apply_plan:
                if any((args.status, args.record, args.outcome, args.note, args.digest, args.backup)):
                    raise ValueError("Use a filing plan option on its own")
                private = workspace.repo(ROOT, "workspace")
                plan = json.load(os.sys.stdin)
                validator = filing_validator(ROOT)
                if args.apply_plan:
                    alignment(ROOT, prepare=True, for_conversion=True)
                    private = workspace.repo(ROOT, "workspace")
                    validator = filing_validator(ROOT)
                    with storage.writer_lock(private):
                        report = conversion.apply(private, plan, validator, LINK)
                else:
                    alignment(ROOT)
                    report = conversion.apply(private, plan, validator, LINK, preview=True)
                print(json.dumps(report, indent=2))
                return 0
            if args.status and any((args.record, args.outcome, args.note, args.digest, args.backup)):
                raise ValueError("Use --status alone for a read-only preview")
            report = alignment(ROOT, not args.status, args.record, args.outcome, args.digest, args.note, args.backup)
            if args.record is None and not args.backup:
                prompt = context_capture.remit_prompt(workspace.private_root(ROOT))
                if prompt:
                    report["remit_prompt"] = prompt
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        if args.command == "init-workspace":
            workspace.initialise(ROOT, args.owner, args.delivery_system)
            print("Initialised private/ as a separate Git repository. No remote, commit, or push was created.")
            print(context_capture.REMIT_PROMPT)
            return 0
        if args.command == "git":
            if args.operation == "push":
                failures = check(ROOT, include_workspace=args.role == "workspace")
                if failures:
                    raise ValueError("Checks failed before push:\n" + "\n".join(failures))
            print(git_ops.run(ROOT, args.role, args.operation))
            if args.operation == "pull":
                update = subprocess.run([os.sys.executable, str(ROOT / "tools/pm.py"), "align"])
                if update.returncode:
                    return update.returncode
                result = subprocess.run([os.sys.executable, str(ROOT / "tools/pm.py"), "check"])
                return result.returncode
            return 0
        if args.command in {"backlog", "roadmap", "initiative"}:
            if args.command == "initiative" and args.operation in {"apply", "sync-drafts", "draft-experiment"}:
                prepare_private_write(ROOT)
            initiatives_cli.run(ROOT, args)
            return 0
        if args.command in {"task", "launch-checklist"}:
            writing = args.operation != "list" and not args.preview
            if writing:
                prepare_private_write(ROOT)
                private = workspace.repo(ROOT, "workspace")
                with storage.writer_lock(private):
                    initiative_work.run(ROOT, args, write=True)
            else:
                workspace.repo(ROOT, "workspace")
                workspace.settings(ROOT)
                initiative_work.run(ROOT, args)
            return 0
        if args.command == "new":
            workspace.repo(ROOT, "workspace")
            settings = prepare_private_write(ROOT)
            if any(ARTIFACT.search(Path(part).stem) for part in Path(args.path).parts):
                raise ValueError("Engineering artifacts belong in the delivery system")
            private = workspace.private_root(ROOT)
            if args.kind == "pm-context":
                if args.path != context_capture.REMIT_PATH or any((args.parent, args.basis, args.reason, args.trigger, args.topic_question, args.topic_peer)):
                    raise ValueError("Create the PM profile at context/pm/context.md")
                created = pm_profile.create(private, args.title)
                print(f"Created {created.relative_to(ROOT)}.")
                return 0
            with storage.writer_lock(private):
                filing.check_new(private, args.kind, args.path, args.title)
                initiative_id = initiative_store.verify_draft_home(ROOT, args.kind, args.path)
                contract = None
                parent = None
                if args.kind != "context-note" and (args.topic_question or args.topic_peer):
                    raise ValueError("Topic fields apply to supporting context notes")
                if args.kind == "product-area-context":
                    contract = filing.area_contract(private, args.path, args.parent, args.basis, args.reason, args.trigger)
                elif args.kind == "context-note":
                    contract = filing.note_contract(private, args.path, args.parent, args.basis, args.reason, args.trigger,
                                                    topic_question=args.topic_question, topic_peer=args.topic_peer)
                elif args.kind == "initiative-context" and args.parent and not any((args.basis, args.reason, args.trigger)):
                    parent = args.parent
                elif any((args.parent, args.basis, args.reason, args.trigger)):
                    raise ValueError("Filing details apply to supporting context notes")
                created = records.create(ROOT, args.kind, args.path, args.title, owner=settings["owner"], filing_contract=contract,
                                         product_parent=parent, initiative_id=initiative_id)
            print(f"Created {created.relative_to(ROOT)} as a draft.")
            return 0
        if args.command == "area-context":
            private = workspace.repo(ROOT, "workspace")
            print(json.dumps(context_capture.area_context(private, args.product, args.area), indent=2))
            return 0
        if args.command in {"task-context", "catalog"}:
            private = workspace.repo(ROOT, "workspace")
            if args.command == "catalog":
                result = task_context.catalog(private)
            else:
                if ((args.area or args.initiative) and not args.product) or (args.company and args.product):
                    raise ValueError("Use a product for area or initiative scope, or choose company scope")
                explicit = {"company": True} if args.company else (
                    {"product": args.product, "area": args.area, "initiative": args.initiative} if args.product else None
                )
                result = task_context.resolve(private, args.prompt, cwd=Path.cwd().resolve(), explicit=explicit,
                                              include_history=args.history)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if args.command == "check-metric":
            payload = storage.json_input(os.sys.stdin.read())
            definitions = None
            if isinstance(payload, dict) and "metric" in payload:
                key = layout.slug(payload["metric"])
                fallback = payload.get("as_of")
                if fallback is not None:
                    metric_registry.day(fallback)
                labels = ("current", "baseline") if payload.get("kind") in ("growth", "percentage_points") else ("current",)
                private = workspace.private_root(ROOT)
                definitions = {
                    label: metric_registry.effective(ROOT, private, payload.get("product"),
                                                     metric_checks.observation_day(payload.get(label), fallback)).get(key)
                    for label in labels
                }
                if not any(definitions.values()) and key not in metric_registry.effective(ROOT, private, payload.get("product")):
                    raise ValueError("Choose a metric ID from pm.py metric list")
            result = metric_checks.check(payload, definitions)
            print(json.dumps(result, indent=2))
            return int(result["status"] != "consistent")
        if args.command == "metric":
            private = workspace.private_root(ROOT)
            if private.exists() or args.operation == "set":
                private = workspace.repo(ROOT, "workspace")
            if args.operation == "set":
                request = storage.json_input(os.sys.stdin.read())
                if args.write:
                    prepare_private_write(ROOT)
                    private = workspace.repo(ROOT, "workspace")
                result = metric_registry.set_definition(ROOT, private, args.id, args.product, request, args.write)
            else:
                result = metric_registry.effective(ROOT, private, args.product, args.as_of)
                if args.operation == "show":
                    if args.id not in result:
                        raise ValueError("Choose a metric ID from pm.py metric list")
                    result = result[args.id]
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if args.command == "set-remit":
            prepare_private_write(ROOT)
            private = workspace.repo(ROOT, "workspace")
            context_capture.write_remit(private, json.load(os.sys.stdin))
            print(f"Saved private/{context_capture.REMIT_PATH}.")
            return 0
        if args.command == "route-context":
            if args.write is not None:
                settings = prepare_private_write(ROOT)
            private = workspace.private_root(ROOT)
            if private.exists() or private.is_symlink() or args.write is not None:
                workspace.repo(ROOT, "workspace")
            remit, error = context_capture.inspect_remit(private)
            plan = context_capture.route(json.load(os.sys.stdin), private, remit)
            definitions = {}
            for entry in plan["entries"]:
                text = entry.get("quote", "")
                if metric_checks.is_claim(text):
                    product = entry.get("product")
                    if product not in definitions:
                        definitions[product] = metric_registry.effective(ROOT, private, product)
                    matched = metric_registry.matching(definitions[product], text)
                    if matched:
                        entry["metric_registry"] = [row["reference"] for row in matched]
            if error:
                plan.update(remit_status="invalid", remit_error=error)
            plan["written"] = None
            if args.write is not None:
                if any(ARTIFACT.search(Path(part).stem) for part in Path(args.write).parts):
                    raise ValueError("Engineering artifacts belong in the delivery system")
                if context_capture.apply(ROOT, args.write, plan, settings["owner"], capture_errors):
                    plan["written"] = args.write
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            return 0
        if args.command == "sync-skills":
            print(f"Updated {sync_skills()} Claude skill file(s).")
            return 0
        if args.command == "eval-red-team":
            return red_team_eval.run(args)
        if not args.system_only and workspace.private_root(ROOT).is_dir() and workspace.settings(ROOT, compatible=False)["workspace_format"] == 1:
            report = alignment(ROOT)
            system_errors = check(include_workspace=False, command_base=args.command_base)
            if not system_errors and report["needs_setup"]:
                print("Shared Hub checks passed. Private format 1 checks await session alignment.")
                return 0
        errors = check(include_workspace=not args.system_only, command_base=args.command_base)
        if not args.system_only:
            notice = alignment_notice(ROOT)
            if notice:
                print(notice)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}")
        return 1
    for error in errors:
        print(f"FAIL: {error}")
    print(f"PM Hub: {'FAIL' if errors else 'PASS'} ({len(errors)} error(s)).")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
