"""Guide and check PM Hub work through Codex and Claude hooks."""

import json
from pathlib import Path
import re
import sys

import pm


CAPTURE_GUIDANCE = (
    "For requests to capture or update context, automatically read .agents/skills/ingest-context/SKILL.md. "
    "Read the PM remit when available. Preview routes before writing to an authorised record."
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
            if header.startswith(("Add File: ", "Move to: ")):
                added = "\n".join(row[1:] for row in body.splitlines() if row.startswith("+"))
                edits.append((header.split(": ", 1)[1], added + "\n"))
        if isinstance(inputs, dict) and inputs.get("workdir"):
            cwd = (cwd / inputs["workdir"]).resolve()
    elif tool in ("Write", "Edit", "MultiEdit") and inputs.get("file_path"):
        content = inputs.get("content", inputs.get("new_string", ""))
        if tool == "MultiEdit":
            content = "\n".join(item.get("new_string", "") for item in inputs.get("edits", []))
        edits.append((inputs["file_path"], content))

    private = root / "workspace"
    for value, content in edits:
        target = (cwd / value).resolve()
        if private not in target.parents or target.exists() or target.suffix.lower() != ".md":
            continue
        parts = target.relative_to(private).parts
        if not any(part == "sources" or part == "secrets" or part.startswith(".") for part in parts):
            reason = (
                "Use pm.py route-context to preview and write an authorised context record. "
                "Use pm.py new to initialise other typed records."
            )
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
    return {}


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
            private = root / "workspace"
            if private.is_dir() and event in {"SessionStart", "Stop"}:
                report = pm.alignment(root, prepare=event == "SessionStart")
                if event == "Stop" and any(item["status"] == "pending" for item in report["outstanding"]):
                    errors.append("Finish the pending filing review in playbook/updates.md. Record genuine evidence gaps as waiting.")
            result = response(event, errors + pm.check(root), retry)
            if event == "SessionStart":
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
