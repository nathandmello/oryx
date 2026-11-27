"""Store and apply the PM's presentation preferences."""

import json
import re

import pm_profile
import storage
import upgrades
import workspace


START = "<!-- pm-hub-preferences -->"
END = "<!-- /pm-hub-preferences -->"
# Earlier releases also parse this heading when reading a shared PM profile.
HEADING = "## Hub reply preferences"
BLOCK = re.compile(HEADING + r"\n\n```json\n(?P<values>.+)\n```\n", re.S)
CHECK_PREFIX = f"{pm_profile.PATH}: oryx reply preferences: "
CHOICES = {
    "detail": {
        "concise": "Keep optional explanation brief.",
        "detailed": "Give more explanation where useful.",
    },
    "layout": {
        "bullets": "Prefer bullets where the content fits a list.",
        "prose": "Prefer short paragraphs where prose fits.",
    },
}


def block_span(text):
    """Locate the managed block outside fenced examples and captured evidence."""
    prefix, _, suffix = pm_profile.capture_block(text)
    marks = []
    for section, offset in ((prefix, 0), (suffix, len(text) - len(suffix))):
        lines = section.splitlines(keepends=True)
        visible = pm_profile.visible_lines(lines)
        for index, line in enumerate(lines):
            if visible.get(index) in (START, END):
                marks.append((visible[index], offset, offset + len(line)))
            offset += len(line)
    if not marks:
        return None
    if [mark[0] for mark in marks] != [START, END] or marks[0][1] < len(prefix) < marks[1][1]:
        raise ValueError("Keep one complete preferences block outside captured evidence.")
    return marks[0][1], marks[0][2], marks[1][1], marks[1][2]


def validate(values):
    if not isinstance(values, dict) or values.keys() - CHOICES.keys():
        raise ValueError("Use only the detail and layout preference fields.")
    for name, value in values.items():
        if not isinstance(value, str) or value not in CHOICES[name]:
            raise ValueError(f"Choose {name} from {', '.join(CHOICES[name])}.")
    return values


def parse(text, span):
    if span is None:
        return {}
    _, start, end, _ = span
    block = BLOCK.fullmatch(text[start:end].replace("\r\n", "\n"))
    if block is None:
        raise ValueError("Use the managed heading and fenced JSON object for preferences.")
    try:
        values = storage.json_input(block["values"])
    except (ValueError, RecursionError):
        raise ValueError("Use valid JSON with unique preference fields.") from None
    return validate(values)


def load(private):
    target = pm_profile.safe_path(private, pm_profile.PATH)
    if not target.is_file() or pm_profile.PATH in upgrades.source_paths(private):
        return {}
    text = target.read_bytes().decode("utf-8")
    return parse(text, block_span(text))


def effective(values):
    return {name: values.get(name, "default") for name in CHOICES}


def guidance(values):
    lines = [
        "Current oryx presentation preferences for this turn supersede earlier preference snapshots.",
        "Apply them only to reply presentation and optional draft prose.",
        "Follow oryx rules, required artifact content, and the PM's current task instructions first.",
    ]
    for name, value in effective(values).items():
        lines.append(CHOICES[name].get(value, f"Use the oryx default for reply {name}."))
    return " ".join(lines)


def preview(values):
    lines = ["The pilot is ready for review.", "The PM will review the results on Friday."]
    if values.get("detail") != "concise":
        lines.append("The results cover completion rates and issues reported by pilot users.")
    if values.get("detail") == "detailed":
        lines.append("The review will compare the completion rate with the target and confirm which issues need follow-up.")
    if values.get("layout") == "bullets":
        return "\n".join(f"- {line}" for line in lines)
    return " ".join(lines)


def save(private, *, updates=None, reset=None):
    with storage.writer_lock(private):
        storage.require_visible(private, pm_profile.PATH)
        if (pm_profile.PATH in upgrades.source_paths(private) or
                pm_profile.safe_path(private, pm_profile.LEGACY).exists()):
            raise ValueError("Resolve the original or legacy PM profile before saving preferences.")
        target = pm_profile.safe_path(private, pm_profile.PATH)
        original = target.read_bytes().decode("utf-8") if target.is_file() else None
        text = "# PM context\n" if original is None else original
        span = block_span(text)
        values = {} if reset == "all" else parse(text, span)
        if updates is not None:
            values.update(validate(updates))
        elif reset != "all":
            values.pop(reset, None)
        if span is None and not values:
            return values
        newline = "\r\n" if "\r\n" in text else "\n"
        block = "\n".join((START, HEADING, "", "```json", json.dumps(values, indent=2), "```", END, ""))
        block = block.replace("\n", newline)
        if span is None:
            gap = "" if not text or text.endswith(newline * 2) else newline if text.endswith(newline) else newline * 2
            candidate = text + gap + block
        else:
            candidate = text[:span[0]] + block + text[span[3]:]
        if parse(candidate, block_span(candidate)) != values or pm_profile.parse(candidate) != pm_profile.parse(text):
            raise ValueError("Repair the Markdown structure before saving preferences.")
        if candidate != original:
            storage.replace_text(target, original, candidate)
    return values


def add_commands(commands):
    group = commands.add_parser("preferences", help="View or tune the PM's reply preferences", allow_abbrev=False)
    group.set_defaults(hub_action=run)
    actions = group.add_subparsers(dest="preference_action", required=True)
    actions.add_parser("show", help="Show the current values and oryx defaults")
    for verb, help_text in (("preview", "Try changes on a sample"), ("set", "Save changes")):
        action = actions.add_parser(verb, help=help_text, allow_abbrev=False)
        for name, choices in CHOICES.items():
            action.add_argument(f"--{name}", choices=choices, action="append")
    reset = actions.add_parser("reset", help="Restore oryx defaults for one or all preferences")
    reset.add_argument("field", nargs="?", choices=[*CHOICES, "all"], default="all")


def run(root, args, prepare_write):
    verb = args.preference_action
    updates = {}
    if verb in {"set", "preview"}:
        for name in CHOICES:
            values = getattr(args, name)
            if values:
                if len(values) != 1:
                    raise ValueError(f"Supply --{name} once.")
                updates[name] = values[0]
        if verb == "set" and not updates:
            raise ValueError("Supply a detail or layout choice to save.")
    if verb in {"set", "reset"}:
        prepare_write(root)
    private = workspace.repo(root, "workspace")
    if verb == "set":
        values = save(private, updates=updates)
    elif verb == "reset":
        values = save(private, reset=args.field)
    else:
        values = load(private)
        values.update(updates)
    print(json.dumps(effective(values), indent=2))
    if verb == "preview":
        print("\nSample reply\n" + preview(values))
