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

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "AGENTS.md", "CLAUDE.md", "README.md", ".gitignore",
    "tools/pm.py", "tools/hook.py", "tools/workspace.py", "tools/git_ops.py",
    ".agents/skills/extend-hub/SKILL.md", ".claude/skills/extend-hub/SKILL.md",
    ".codex/hooks.json", ".codex/config.toml", ".claude/settings.json",
    ".github/workflows/check.yml", "tests/test_pm.py",
    "playbook/framework.md", "playbook/working.md", "playbook/context.md", "templates/README.md", "tools/records.py",
    ".agents/skills/red-team/SKILL.md", ".claude/skills/red-team/SKILL.md",
    "playbook/git.md", "playbook/release.json", "tools/workspace-seed/README.md",
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
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".state", ".generated", "worktrees"}
ARTIFACT = re.compile(
    r"(?:^|[-_ ])(?:prds?|specs?|specifications?|requirements|user[-_ ]stories|"
    r"user[-_ ]flows|acceptance[-_ ]criteria)(?:$|[-_ ])", re.I)
WORDS = re.compile(r"\b[\w]+(?:['’-][\w]+)*\b")
LINK = re.compile(r"\[([^\]\n]+)\]\((<[^>\n]+>|[^\s)]+)\)")
BANNED = re.compile(r"\b(?:may|might|could|would|should|thus|delve|leverage)\b", re.I)


def inventory(root: Path) -> list[Path]:
    """Respect Git ignore rules. The fallback supports disposable test fixtures."""
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=True,
        )
        return sorted({root / p for p in result.stdout.split("\0") if p})
    paths = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                paths.append(path)
                dirs.remove(name)
            elif name in SKIP_DIRS or name == "secrets" or (path == root / "workspace"):
                dirs.remove(name)
        paths.extend(Path(directory) / name for name in names)
    return sorted(paths)


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
        limit = 20 if instruction else 25
        for sentence in sentences:
            count = len(WORDS.findall(sentence))
            if count > limit:
                errors.append(f"{line}: sentence has {count} words (limit {limit})")
        for word in sorted(set(BANNED.findall(unit))):
            errors.append(f"{line}: replace '{word}' with direct, concrete wording")
    if total > 800:
        errors.append(f"authored prose has {total} words (limit 800); split by purpose")
    return errors


def link_errors(root: Path, path: Path, text: str) -> list[str]:
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
            elif not destination.exists():
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


def hook_errors(texts: dict[str, str]) -> list[str]:
    errors = []
    for name in (".codex/hooks.json", ".claude/settings.json"):
        try:
            config = json.loads(texts.get(name, ""))
            if set(config) != {"hooks"}:
                errors.append(f"{name}: keep client configuration limited to the declared hooks")
            hooks = config["hooks"]
            for event in ("SessionStart", "Stop"):
                if len(hooks[event]) != 1 or set(hooks[event][0]) != {"hooks"}:
                    errors.append(f"{name}: {event} must run without a matcher")
                handlers = [handler for group in hooks[event] for handler in group["hooks"]]
                expected = [{"type": "command", "command": CODEX_COMMAND, "timeout": 15}]
                if name.startswith(".claude"):
                    expected = [{"type": "command", "command": "python3",
                                 "args": ["-c", HOOK_SCRIPT], "timeout": 15}]
                if handlers != expected:
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
        if ((len(parts) == 1 and rel not in {"README.md", ".gitignore", "settings.json"})
                or (len(parts) > 1 and parts[0] not in {"context", "products"})):
            errors.append(f"{label}: use a home from the README placement map")
        if any(ARTIFACT.search(Path(part).stem) for part in parts):
            errors.append(f"{label}: engineering artifacts belong in the delivery system")
        if path.suffix == ".md":
            try:
                texts[rel] = path.read_text(encoding="utf-8")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    checks = commands.add_parser("check")
    checks.add_argument("--system-only", action="store_true")
    commands.add_parser("sync-skills")
    new = commands.add_parser("new")
    new.add_argument("kind", choices=records.KINDS)
    new.add_argument("path", help="Path under workspace/, starting with context/ or products/")
    new.add_argument("--title")
    initialise = commands.add_parser("init-workspace")
    initialise.add_argument("--owner", default="")
    initialise.add_argument("--delivery-system", default="Delivery workspace")
    git = commands.add_parser("git")
    git.add_argument("role", choices=("system", "workspace"))
    git.add_argument("operation", choices=("status", "fetch", "pull", "push"))
    args = parser.parse_args()
    try:
        if args.command == "init-workspace":
            workspace.initialise(ROOT, args.owner, args.delivery_system)
            print("Initialised workspace/ as a separate Git repository. No remote, commit, or push was created.")
            return 0
        if args.command == "git":
            if args.operation == "push":
                failures = check(ROOT, include_workspace=args.role == "workspace")
                if failures:
                    raise ValueError("Checks failed before push:\n" + "\n".join(failures))
            print(git_ops.run(ROOT, args.role, args.operation))
            if args.operation == "pull":
                result = subprocess.run([os.sys.executable, str(ROOT / "tools/pm.py"), "check"])
                return result.returncode
            return 0
        if args.command == "new":
            workspace.repo(ROOT, "workspace")
            settings = workspace.settings(ROOT)
            if any(ARTIFACT.search(Path(part).stem) for part in Path(args.path).parts):
                raise ValueError("Engineering artifacts belong in the delivery system")
            created = records.create(ROOT, args.kind, args.path, args.title, owner=settings["owner"])
            print(f"Created {created.relative_to(ROOT)} as a draft.")
            return 0
        if args.command == "sync-skills":
            print(f"Updated {sync_skills()} Claude skill file(s).")
            return 0
        errors = check(include_workspace=not args.system_only)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}")
        return 1
    for error in errors:
        print(f"FAIL: {error}")
    print(f"PM Hub: {'FAIL' if errors else 'PASS'} ({len(errors)} error(s)).")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
