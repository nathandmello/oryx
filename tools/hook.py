"""Guide and check PM Hub work through Codex and Claude hooks."""

import json
from os.path import abspath
from pathlib import Path
import re
import sys

import pm


CAPTURE_GUIDANCE = (
    "For requests to capture or update context, automatically read .agents/skills/ingest-context/SKILL.md. "
    "Read the PM remit when available. Preview routes before writing to an authorised record. "
    "For intake, discovery, initiative briefs, or prioritization, read playbook/opportunities.md. "
    "Read the current records using pm.py initiative show. Use initiative propose for proposed changes. "
    "Find metric-linked experiment drafts with initiative show. Leave unknown fields empty. "
    "Only the PM signs and applies changes with the protected signing key."
)


def edit_guard(root, cwd, payload):
    tool = payload.get("tool_name")
    inputs = payload.get("tool_input", {})
    edits = []
    if tool == "apply_patch":
        command = inputs if isinstance(inputs, str) else next(
            (inputs[key] for key in ("command", "input", "patch") if isinstance(inputs.get(key), str)), "")
        blocks = re.split(r"(?m)^\*\*\* ", command)
        for block in blocks:
            header, _, body = block.partition("\n")
            if header.startswith(("Add File: ", "Move to: ", "Update File: ", "Delete File: ")):
                added = "\n".join(row[1:] for row in body.splitlines() if row.startswith("+"))
                edits.append((header.split(": ", 1)[1], added + "\n"))
        if isinstance(inputs, dict) and inputs.get("workdir"):
            cwd = (cwd / inputs["workdir"]).resolve()
    elif tool in ("Write", "Edit", "MultiEdit") and inputs.get("file_path"):
        content = inputs.get("content", inputs.get("new_string", ""))
        if tool == "MultiEdit":
            content = "\n".join(item.get("new_string", "") for item in inputs.get("edits", []))
        edits.append((inputs["file_path"], content))

    private = pm.workspace.private_root(root)
    for value, content in edits:
        reason = edit_reason(root, private, Path(abspath(cwd / value)), content)
        if reason:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
    return {}


def edit_reason(root, private, requested, content):
    target = requested.resolve()
    if private.name == "private" and (target == root / "workspace" or root / "workspace" in target.parents):
        return "This is the retired private root. File PM work under private/workspace/ and reference material under private/context/."
    if any(private in path.parents and pm.opportunities.path_kind(path.relative_to(private)) == "register"
           for path in (requested, target)):
        return "Use pm.py initiative propose for register changes. The PM signs and applies the proposal."
    if private not in target.parents:
        return None
    relative = target.relative_to(private)
    parts = relative.parts
    managed = pm.opportunities.path_kind(relative)
    if managed:
        try:
            pm.storage.require_visible(private, relative)
        except ValueError as exc:
            return str(exc)
        if managed == "experiment-draft" and not target.exists():
            return "Start the linked draft with pm.py initiative draft-experiment."
    if target.suffix.lower() != ".md":
        return None
    if (not target.exists() and len(parts) == 3 and parts[:2] in {("workspace", "backlogs"), ("workspace", "roadmaps")}
            and pm.layout.SLUG.fullmatch(target.stem) and (private / pm.layout.initiative_register(target.stem)).is_file()):
        return "Use pm.py backlog or pm.py roadmap for this registered product."
    typed = any(line.startswith("<!-- pm:") for line in content.splitlines())
    plain_work = not managed and pm.layout.valid_work(relative) and parts[1] in {"initiatives", "backlogs"}
    if plain_work and typed:
        return "File the typed artifact at its canonical home. Backlogs and initiative plans are plain working documents."
    if target.exists() or plain_work or any(p in {"sources", "secrets"} or p.startswith(".") for p in parts):
        return None
    return "Use pm.py route-context for context. Use pm.py new to initialise typed records, including initiative and discovery briefs."


def response(event, errors, retry=False):
    if event not in ("SessionStart", "Stop"):
        raise ValueError("Expected SessionStart or Stop")
    detail = "\n".join(errors[:8])
    if len(errors) > 8:
        detail += f"\n{len(errors) - 8} more error(s). Run python3 tools/pm.py check."
    message = "PM Hub checks failed:\n" + detail
    if event == "SessionStart":
        result = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": CAPTURE_GUIDANCE}}
        if errors:
            result["systemMessage"] = message
        return result
    if not errors:
        return {}
    if event == "Stop" and not retry:
        return {"decision": "block", "reason": message + "\nFix these errors, then run the check again."}
    if event == "Stop":
        message += "\nReport the unresolved checks. Do not claim the work passed."
    return {"systemMessage": message}


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook input must be an object")
        event = payload["hook_event_name"]
        retry = payload.get("stop_hook_active", False)
        if not isinstance(retry, bool):
            raise ValueError("stop_hook_active must be a boolean")
        root = Path(__file__).resolve().parents[1]
        cwd = Path(payload.get("cwd", str(root))).resolve()
        if root != cwd and root not in cwd.parents:
            raise ValueError("Start the session inside this PM Hub checkout")
        if event == "PreToolUse":
            result = edit_guard(root, cwd, payload)
        else:
            errors = []
            private = pm.workspace.private_root(root)
            if private.is_dir() and event in {"SessionStart", "Stop"}:
                report = pm.alignment(root, prepare=event == "SessionStart")
                if event == "Stop" and any(item["status"] == "pending" for item in report["outstanding"]):
                    errors.append("Finish the pending filing review in playbook/updates.md. Record genuine evidence gaps as waiting.")
            result = response(event, errors + pm.check(root), retry)
            if event == "SessionStart":
                private = pm.workspace.private_root(root)
                if private.is_dir():
                    prompt = pm.context_capture.remit_prompt(private)
                    if prompt:
                        result["hookSpecificOutput"]["additionalContext"] += (
                            "\nAsk the PM once this session when questions are welcome: " + prompt
                            + " Accept deferral and continue the requested work. Save only PM-confirmed answers with set-remit."
                        )
                notice = pm.alignment_notice(root)
                if notice:
                    result["hookSpecificOutput"]["additionalContext"] += "\n" + notice
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(f"PM Hub hook failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
