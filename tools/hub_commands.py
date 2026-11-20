"""Discover and route published oryx slash commands."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import re
from shlex import join

import storage
import workspace
import overrides


CATALOG = "playbook/commands.json"
NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
HELP = {"-h", "--help"}
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
NATIVE_COMMAND_DIRS = {(".claude", "commands"), (".codex", "prompts")}


def name(value):
    return isinstance(value, str) and NAME.fullmatch(value) is not None


def description(value):
    return isinstance(value, str) and len(value.splitlines()) == 1 and bool(value.strip())


def load(root, cli_parser=None):
    path = root / CATALOG
    if path.resolve() != path or not path.is_file():
        raise ValueError("Use the regular shared command catalog inside oryx.")
    catalog = storage.json_input(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or catalog.keys() != {"domains", "verbs", "aliases", "commands"}:
        raise ValueError("Define domains, verbs, aliases, and commands.")
    domains, verbs, aliases, commands = (catalog[key] for key in ("domains", "verbs", "aliases", "commands"))
    for labels in (domains, verbs):
        if not isinstance(labels, dict) or not labels or not all(
                name(key) and description(value) for key, value in labels.items()):
            raise ValueError("Use named domains and verbs with short descriptions.")
    if not isinstance(commands, dict) or not commands:
        raise ValueError("Register commands by domain, subject, and verb.")
    subjects, cli_targets = set(), {}
    for key, entry in commands.items():
        parts = key.split(" ")
        if (len(parts) != 3 or parts[0] not in domains or not name(parts[1]) or parts[2] not in verbs
                or not isinstance(entry, dict) or not description(entry.get("summary"))):
            raise ValueError(f"Invalid command path or summary: {key}")
        subjects.add(" ".join(parts[:2]))
        if entry.keys() == {"summary", "guide"}:
            validate_guide(root, key, entry["guide"])
        elif entry.keys() == {"summary", "effect", "cli", "example"}:
            validate_cli(key, entry, cli_parser)
            target = tuple(entry["cli"])
            if target in cli_targets:
                raise ValueError(f"{key} repeats the CLI target for {cli_targets[target]}. Use a compatibility alias.")
            cli_targets[target] = key
        else:
            raise ValueError(f"Choose one CLI target or workflow guide for {key}.")
    if not isinstance(aliases, dict):
        raise ValueError("Define compatibility aliases by their former path.")
    for alias, target in aliases.items():
        parts = alias.split(" ")
        targets = commands if len(parts) == 3 else subjects
        if (len(parts) > 3 or not all(name(part) for part in parts) or alias in domains
                or alias in subjects or alias in commands or not isinstance(target, str) or target not in targets):
            raise ValueError(f"Map {alias} to a canonical path without shadowing a published name.")
    return catalog


def validate_guide(root, key, guide):
    if not isinstance(guide, str):
        raise ValueError(f"Choose a shared workflow guide for {key}.")
    relative = Path(guide)
    parts = relative.parts
    playbook = len(parts) == 2 and parts[0] == "playbook" and relative.suffix == ".md"
    skill = len(parts) == 4 and parts[:2] == (".agents", "skills") and name(parts[2]) and parts[3] == "SKILL.md"
    target = root / relative
    if not (playbook or skill) or target.resolve() != target or not target.is_file():
        raise ValueError(f"Choose a regular shared playbook or canonical skill for {key}.")


def validate_cli(key, entry, parser):
    target, example = entry["cli"], entry["example"]
    if (entry["effect"] not in ("read", "local-write") or not isinstance(target, list)
            or not target or not all(name(part) for part in target) or target[0] == "action"
            or not isinstance(example, list)
            or not all(isinstance(arg, str) and arg not in HELP for arg in example)):
        raise ValueError(f"Use a fixed CLI target, effect, and example arguments for {key}.")
    if parser is not None:
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                parser.parse_args([*target, *example])
        except SystemExit:
            raise ValueError(f"CLI target or example does not match the terminal parser for {key}.") from None


def expand_alias(catalog, args):
    for length in range(min(3, len(args)), 0, -1):
        replacement = catalog["aliases"].get(" ".join(args[:length]))
        if replacement:
            return [*replacement.split(), *args[length:]]
    return args


def compatibility_errors(root, base, current, parser):
    if not COMMIT.fullmatch(base):
        raise ValueError("Use the full SHA of a local base commit for the command comparison.")
    root = workspace.repo(root, "system")
    if workspace.git(root, "cat-file", "-t", base) != "commit":
        raise ValueError("Use the full SHA of a local base commit for the command comparison.")
    if not workspace.git(root, "ls-tree", "--name-only", base, "--", CATALOG):
        return []
    previous = storage.json_input(workspace.git(root, "show", f"{base}:{CATALOG}"))
    commands, aliases = previous["commands"], previous["aliases"]
    published = set(commands)
    for alias, target in aliases.items():
        if target in commands:
            published.add(alias)
        else:
            prefix = target + " "
            published.update(f"{alias} {path[len(prefix):]}" for path in commands if path.startswith(prefix))

    errors = []
    for path in sorted(published):
        before = commands[" ".join(expand_alias(previous, path.split()))]
        after = current["commands"].get(" ".join(expand_alias(current, path.split())))
        if after is None:
            errors.append(f"Keep /pm {path} available or add a compatibility alias.")
        elif before.get("effect", "guided") != after.get("effect", "guided"):
            errors.append(f"Keep the published effect of /pm {path}. Use a new path for a different effect.")
        elif "cli" in before and before["example"] != after["example"]:
            try:
                validate_cli(path, {**after, "example": before["example"]}, parser)
            except ValueError:
                errors.append(f"Keep the previous CLI example working for /pm {path}.")
    return errors


def show(catalog, parts):
    if not parts:
        print("Usage: /pm DOMAIN SUBJECT VERB [arguments] or pm.py action DOMAIN SUBJECT VERB [arguments]")
        print("\nDomains")
        for domain, summary in catalog["domains"].items():
            print(f"  {domain:<12} {summary}")
        print("\nChoose a domain to see its available actions.")
        return
    prefix = " ".join(parts) + " "
    matches = {path: entry for path, entry in catalog["commands"].items() if path.startswith(prefix)}
    if len(parts) == 1:
        subjects = sorted({path.rsplit(" ", 1)[0] for path in matches})
        for subject in subjects:
            print(f"  /pm {subject}")
        return
    for path, entry in matches.items():
        effect = entry.get("effect", "guided")
        print(f"  /pm {path} [{effect}]  {entry['summary']}")


def route(root, args):
    """Return the CLI arguments, or print the catalog or a workflow handoff."""
    catalog = load(root)
    if args == ["--catalog"]:
        print(json.dumps(catalog, indent=2))
        return None
    describe = args[:1] == ["--describe"]
    if describe:
        args = args[1:]
    args = expand_alias(catalog, args)
    if describe and (len(args) != 3 or any(part in HELP for part in args)):
        raise ValueError("Provide one complete action path to describe.")
    parts, help_requested = [], False
    for part in args[:3]:
        if part in HELP:
            help_requested = True
            break
        parts.append(part)
    if len(parts) < 3:
        if parts and not any(path.startswith(" ".join(parts) + " ") for path in catalog["commands"]):
            raise ValueError("Unknown oryx action. Run pm.py action to list domains.")
        if help_requested and len(args) != len(parts) + 1:
            raise ValueError("Use help on its own after a domain or subject.")
        show(catalog, parts)
        return None
    path = " ".join(parts)
    if path not in catalog["commands"]:
        if parts[0] not in catalog["domains"]:
            raise ValueError("Unknown oryx domain. Run pm.py action to list domains.")
        subject = " ".join(parts[:2])
        menu = subject if any(key.startswith(subject + " ") for key in catalog["commands"]) else parts[0]
        raise ValueError(f"Unknown oryx action. Run pm.py action {menu} to see the available paths.")
    entry = catalog["commands"][path]
    arguments = args[3:]
    if describe:
        print(json.dumps({"command": path, "effect": "guided", **entry}, indent=2))
        return None
    if "cli" in entry:
        if arguments in (["-h"], ["--help"]):
            print(f"/pm {path} [{entry['effect']}]\n{entry['summary']}")
            print("Example: " + join(["/pm", *parts, *entry["example"]]), end="\n\n")
        return [*entry["cli"], *arguments]
    if arguments in (["-h"], ["--help"]):
        print(f"/pm {path} [guided]\n{entry['summary']}\nWorkflow: {entry['guide']}")
    else:
        result = {"command": path, "effect": "guided", "task": entry["summary"],
                  "guide": entry["guide"], "arguments": arguments}
        private = workspace.optional_repo(root)
        if private is not None:
            result["workflow_guidance"] = overrides.guidance(private)
        print(json.dumps(result, indent=2))
    return None
