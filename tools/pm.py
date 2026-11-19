"""Check PM Hub and generate its Claude skill adapters. Python 3.9+, standard library."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

import records
import workspace
import git_ops
import context_capture
import storage
import snapshots
from storage import inventory
import upgrades
import filing
import conversion

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "AGENTS.md", "CLAUDE.md", "README.md", ".gitignore",
    "tools/pm.py", "tools/hook.py", "tools/workspace.py", "tools/git_ops.py",
    "tools/filing.py", "tools/conversion.py", "tools/snapshots.py", "playbook/filing.md", "playbook/writing.md",
    "tools/context_capture.py", "tools/storage.py", "tools/upgrades.py",
    ".agents/skills/extend-hub/SKILL.md", ".claude/skills/extend-hub/SKILL.md",
    ".agents/skills/ingest-context/SKILL.md", ".claude/skills/ingest-context/SKILL.md",
    ".codex/hooks.json", ".codex/config.toml", ".claude/settings.json",
    ".github/workflows/check.yml", ".github/pull_request_template.md", "tools/release_review.py", "tests/test_pm.py",
    "playbook/framework.md", "playbook/working.md", "playbook/context.md", "templates/README.md", "tools/records.py",
    ".agents/skills/red-team/SKILL.md", ".claude/skills/red-team/SKILL.md",
    "playbook/git.md", "playbook/updates.md", "playbook/release.json", "tools/workspace-seed/README.md",
    "tools/workspace-seed/context/README.md", "tools/workspace-seed/products/README.md",
    "tools/workspace-seed/.gitignore",
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
            target = urlsplit(match[2].strip("<>"))
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
        listed = documented.get(scope, set()) | documented.get("shared", set())
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
            for event in ("SessionStart", "Stop", "PreToolUse"):
                group = {"hooks": [dict(handler, timeout=600 if event == "SessionStart" else 15)]}
                if event == "PreToolUse":
                    group["matcher"] = "Write|Edit|MultiEdit" if claude else "apply_patch"
                elif len(hooks[event]) != 1 or set(hooks[event][0]) != {"hooks"}:
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
    private = root / "workspace"
    try:
        workspace.repo(root, "workspace")
        workspace.settings(root)
    except (OSError, ValueError) as exc:
        return [f"workspace/: {exc}"]
    legacy = {}
    try:
        state = upgrades.read_state(private)[1]
        legacy = state.get(upgrades.RULE)
        if legacy is None:
            legacy = upgrades.candidates(private, inventory)
        for identifier, digest in state.get(upgrades.TRANSACTIONS, {}).items():
            if upgrades.fingerprint(conversion.archive_path(private, identifier)) != digest:
                errors.append(f"workspace/: missing or changed recovery archive for {identifier}")
        if conversion.pointer(private).exists():
            errors.append("workspace/: finish the pending recoverable filing plan before sharing changes")
    except (OSError, ValueError) as exc:
        errors.append(f"workspace/{upgrades.LEDGER}: {exc}")
    try:
        context_capture.read_remit(private)
    except (OSError, ValueError) as exc:
        errors.append(f"workspace/{context_capture.REMIT_PATH}: {exc}")
    for path in inventory(private):
        rel = path.relative_to(private).as_posix()
        label = f"workspace/{rel}"
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
            errors.append(f"{label}: use regular files inside PM Hub")
            continue
        if path.name == ".env" or path.name.startswith(".env.") or "secrets" in path.relative_to(private).parts:
            errors.append(f"{label}: private file must stay outside Git")
            continue
        if not path.is_file():
            continue
        parts = path.relative_to(private).parts
        if len(parts) == 2 and parts[0] == conversion.HISTORY and path.suffix == ".zip" and conversion.IDENTIFIER.fullmatch(path.stem):
            continue
        item = (legacy or {}).get(rel, {})
        is_source = item.get("role") == "source" or "sources" in parts
        old_record = item.get("status") in ("pending", "waiting") and item.get("digest") == upgrades.fingerprint(path)
        if not old_record and not is_source and ((len(parts) == 1 and rel not in {"README.md", ".gitignore", "settings.json", upgrades.LEDGER, conversion.PENDING})
                or (len(parts) > 1 and parts[0] not in {"context", "products"})):
            errors.append(f"{label}: use a home from the README placement map")
        if any(ARTIFACT.search(Path(part).stem) for part in parts):
            errors.append(f"{label}: engineering artifacts belong in the delivery system")
        if path.suffix == ".md":
            try:
                texts[rel] = path.read_text(encoding="utf-8")
                try:
                    if not old_record and not is_source:
                        filing.verify_note(private, rel, texts[rel])
                except ValueError as exc:
                    errors.append(f"{label}: {exc}")
                if not is_source:
                    errors.extend(f"{label}:{e}" for e in writing_errors(texts[rel]))
                errors.extend(f"{label}:{e}" for e in link_errors(root, path, texts[rel]))
            except (OSError, UnicodeError) as exc:
                errors.append(f"{label}: cannot read text: {exc}")
    for required in ("README.md", ".gitignore", "settings.json", "context/README.md", "products/README.md"):
        if not (private / required).is_file():
            errors.append(f"workspace/{required}: required file is missing")
    templates = {p: t for p, t in system_texts.items() if p.startswith("templates/")}
    errors.extend(f"workspace/{e}" for e in records.validate(dict(templates, **texts)))
    return errors


def check(root: Path = ROOT, include_workspace=True) -> list[str]:
    root = root.resolve()
    errors, texts, safe = [], {}, set()
    for path in inventory(root):
        rel = path.relative_to(root).as_posix()
        if rel == "workspace" or rel.startswith("workspace/"):
            errors.append("workspace/: PM data must never be tracked by the system repository")
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
                errors.append(f"{rel}: PM records belong inside workspace/")
    for rel in REQUIRED:
        if root / rel not in safe:
            errors.append(f"{rel}: required file is missing or unsafe")
    if texts.get("CLAUDE.md", "").strip() != "@AGENTS.md":
        errors.append("CLAUDE.md: import AGENTS.md without duplicate instructions")
    errors.extend(skill_errors(root, safe))
    errors.extend(guidance_errors(root, texts))
    errors.extend(hook_errors(texts))
    errors.extend(records.validate(texts))
    if "/workspace/" not in texts.get(".gitignore", "").splitlines():
        errors.append(".gitignore: exclude /workspace/ from the system repository")
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


def filing_validator(root):
    private = root / "workspace"
    def validate(edits, folds, archive, originals):
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
                filing.check_new(private, new_kind[1], name, None, retiring=folds)
            filing.verify_note(private, name, text)
            texts[name] = text
            problems.extend(writing_errors(text) + link_errors(root, private / name, text, planned={archive, *(private / target for target in edits)}))
        conversion.verify_fragments(private, texts, edits, LINK)
        for error in records.validate(texts):
            if error not in previous or error.partition(":")[0] in edits:
                problems.append(error)
        if problems:
            raise ValueError("Invalid filing result: " + " | ".join(problems[:8]))
    return validate


def alignment(root, prepare=False, record=None, outcome=None, digest=None, note=None, backup=None, for_conversion=False):
    private = workspace.repo(root, "workspace")
    def inspect():
        settings_file = private / "settings.json"
        original = settings_file.read_text(encoding="utf-8") if settings_file.resolve() == settings_file else None
        settings = workspace.settings(root, compatible=False)
        release = workspace.release(root)
        changing = settings["system_version"] != release["system_version"]
        if settings["workspace_format"] != release["workspace_format"] or (changing and not (
            settings["system_version"] in {"0.1.0", "0.2.0"} and release == {"system_version": "0.3.0", "workspace_format": 1}
        )):
            raise ValueError("Unsupported workspace version; inspect release compatibility before updating")
        recovery = None
        if prepare:
            state = upgrades.read_state(private)[1]
            if (changing or upgrades.RULE not in state or not upgrades.scan_marker(private).exists()
                    or conversion.pointer(private).exists() or record or for_conversion):
                recovery = snapshots.ensure(root, release["system_version"])
            conversion.resume(private, filing_validator(root), LINK)
        result = upgrades.run(private, inventory, prepare=prepare, record=record, outcome=outcome, digest=digest, note=note)
        if changing and prepare:
            settings["system_version"] = release["system_version"]
            storage.replace_text(settings_file, original, json.dumps(settings, indent=2) + "\n")
        result["needs_setup"] |= (changing or conversion.pointer(private).exists()) and not prepare
        if recovery:
            result["installation_backup"] = str(recovery)
        if backup:
            result["backups"] = upgrades.backup(private, backup)
        return result
    if prepare:
        with storage.writer_lock(private):
            return inspect()
    return inspect()


def prepare_private_write(root):
    private = workspace.repo(root, "workspace")
    settings = workspace.settings(root, compatible=False)
    if settings["system_version"] != workspace.release(root)["system_version"] or upgrades.RULE not in upgrades.read_state(private)[1] or conversion.pointer(private).exists():
        alignment(root, prepare=True)
    return workspace.settings(root)


def alignment_notice(root):
    if not (root / "workspace").exists():
        return ""
    try:
        result = alignment(root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return f"Workspace alignment unavailable: {exc}"
    items = result["outstanding"]
    if not result["needs_setup"] and not items:
        return ""
    return (f"Context upgrade: {len(items)} record(s) pending or waiting. "
            "Agent: run python3 tools/pm.py align and execute playbook/updates.md now. "
            "Read records and sources. Preview and apply verified conversions, and record specific unresolved evidence.")



def capture_errors(root, target, text):
    private = root / "workspace"
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
    return errors + writing_errors(text) + link_errors(root, target, text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    checks = commands.add_parser("check")
    checks.add_argument("--system-only", action="store_true")
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
    new.add_argument("kind", choices=records.KINDS)
    new.add_argument("path", help="Path under workspace/, starting with context/ or products/")
    new.add_argument("--title")
    new.add_argument("--parent")
    new.add_argument("--basis", choices=filing.BASES)
    new.add_argument("--reason")
    new.add_argument("--trigger")
    route = commands.add_parser("route-context", help="Route supplied context evidence from JSON on stdin")
    route.add_argument("--write", metavar="PATH", help="Apply entries to one authorised context record")
    commands.add_parser("set-remit", help="Save a PM-confirmed remit from JSON on stdin")
    initialise = commands.add_parser("init-workspace")
    initialise.add_argument("--owner", default="")
    initialise.add_argument("--delivery-system", default="Delivery workspace")
    git = commands.add_parser("git")
    git.add_argument("role", choices=("system", "workspace"))
    git.add_argument("operation", choices=("status", "fetch", "pull", "push"))
    args = parser.parse_args()
    try:
        if args.command == "align":
            if args.preview_plan or args.apply_plan:
                if any((args.status, args.record, args.outcome, args.note, args.digest, args.backup)):
                    raise ValueError("Use a filing plan option on its own")
                private = workspace.repo(ROOT, "workspace")
                plan = json.load(os.sys.stdin)
                validator = filing_validator(ROOT)
                if args.apply_plan:
                    alignment(ROOT, prepare=True, for_conversion=True)
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
                prompt = context_capture.remit_prompt(ROOT / "workspace")
                if prompt:
                    report["remit_prompt"] = prompt
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        if args.command == "init-workspace":
            workspace.initialise(ROOT, args.owner, args.delivery_system)
            print("Initialised workspace/ as a separate Git repository. No remote, commit, or push was created.")
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
        if args.command == "new":
            workspace.repo(ROOT, "workspace")
            settings = prepare_private_write(ROOT)
            if any(ARTIFACT.search(Path(part).stem) for part in Path(args.path).parts):
                raise ValueError("Engineering artifacts belong in the delivery system")
            private = ROOT / "workspace"
            with storage.writer_lock(private):
                filing.check_new(private, args.kind, args.path, args.title)
                contract = None
                if args.kind == "context-note":
                    contract = filing.note_contract(private, args.path, args.parent, args.basis, args.reason, args.trigger)
                elif any((args.parent, args.basis, args.reason, args.trigger)):
                    raise ValueError("Filing details apply to supporting context notes")
                created = records.create(ROOT, args.kind, args.path, args.title, owner=settings["owner"], filing_contract=contract)
            print(f"Created {created.relative_to(ROOT)} as a draft.")
            return 0
        if args.command == "set-remit":
            private = workspace.repo(ROOT, "workspace")
            prepare_private_write(ROOT)
            context_capture.write_remit(private, json.load(os.sys.stdin))
            print(f"Saved workspace/{context_capture.REMIT_PATH}.")
            return 0
        if args.command == "route-context":
            private = ROOT / "workspace"
            if private.exists() or private.is_symlink() or args.write is not None:
                workspace.repo(ROOT, "workspace")
            remit, error = context_capture.inspect_remit(private)
            plan = context_capture.route(json.load(os.sys.stdin), private, remit)
            if error:
                plan.update(remit_status="invalid", remit_error=error)
            plan["written"] = None
            if args.write is not None:
                settings = prepare_private_write(ROOT)
                if any(ARTIFACT.search(Path(part).stem) for part in Path(args.write).parts):
                    raise ValueError("Engineering artifacts belong in the delivery system")
                if context_capture.apply(ROOT, args.write, plan, settings["owner"], capture_errors):
                    plan["written"] = args.write
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            return 0
        if args.command == "sync-skills":
            print(f"Updated {sync_skills()} Claude skill file(s).")
            return 0
        errors = check(include_workspace=not args.system_only)
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
