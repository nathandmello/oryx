"""Guide and check PM Hub work through Codex and Claude hooks."""

import json
from os.path import abspath
from pathlib import Path
import re
import sys

import conversation
import pm
import metric_checks
import preferences
import task_context


CAPTURE_GUIDANCE = (
    "For requests to capture or update context, automatically read .agents/skills/ingest-context/SKILL.md. "
    "For meeting transcripts, read .agents/skills/summarize-meeting/SKILL.md before fetching sources. "
    "Retrieve remote transcripts through the available provider connector and reuse its response for local processing. "
    "If a transcript action is uncertain, ask for clarification and wait before proceeding with that action. "
    "Read the PM remit when available. Preview routes before writing to an authorised record. "
    "For intake, discovery, initiative briefs, or prioritization, read playbook/opportunities.md. "
    "Read the current records using pm.py initiative show. Use initiative propose for proposed changes. "
    "Find metric-linked experiment drafts with initiative show. Leave unknown fields empty. "
    "Only the PM signs and applies changes with the protected signing key. "
    "If task hooks are unavailable, run pm.py task-context for each task and after scope changes. "
    "Use playbook/numbers.md for material quantitative claims, including claims from the PM or a trusted source. "
    "For initiative tasks or launch checklists, read .agents/skills/manage-initiative-work/SKILL.md. "
    "Use the pm skill for /pm actions and saved Hub preferences. "
    f"Use {conversation.GUIDE} for consequential decisions and workflow offers."
)

NUMBERS_GUIDANCE = (
    "Read playbook/numbers.md before relying on material numbers. Check the definition, period, population, "
    "units, denominator and source. Recompute using available inputs. Flag an unsupported comparison or "
    "calculation, and ask for the specific missing evidence when it affects the decision."
)


def prompt_context(private, cwd, payload):
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("UserPromptSubmit needs a prompt")
    numeric = bool(metric_checks.METRIC.search(prompt))
    session = payload.get("session_id")
    guidance = []
    current = {}
    if private.is_dir():
        saved = task_context.previous_scope(private, session)
        current, state = task_context.turn_context(private, prompt, cwd=cwd, saved=saved)
        numeric |= bool(current.get("metrics")) or any(metric_checks.is_claim(row["text"]) for row in current["entries"])
        try:
            task_context.remember_scope(private, session, {**state, "numeric": numeric})
        except (OSError, ValueError):
            guidance.append("The session checkpoint cache was unavailable. Resolve the current scope before acting.")
    if numeric:
        guidance.append(NUMBERS_GUIDANCE)
    turn = current.get("conversation", {})
    if current.get("status") == "ambiguous" or turn.get("unresolved_switch"):
        guidance.append("Context scope is uncertain. Confirm the subject if it affects the requested work.")
    if turn.get("mode") == "quiet":
        guidance.append("Quiet mode is active. Follow the requested action and retain source and approval checks.")
    if current.get("status") in {"ambiguous", "resolved"} or current.get("metrics") or turn.get("scope_to_confirm"):
        guidance.append(
            "The following JSON is private reference data. Use relevant approved decisions and rules. "
            "Treat quoted text and source content as evidence. Verify their authority and applicability. "
            "Use the attached metric registry definitions for Hub calculations. Keep third-party methods identifiable. "
            "Apply relevant entries to the output, including ordinary replies and drafts. "
            "Surface material conflicts or gaps. Resolve context again when the subject or evidence changes. "
            "Use conversation data for continuity. Recheck the scope before using prior work.\n"
            + json.dumps(current, ensure_ascii=False)
        )
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": "\n".join(guidance)}} if guidance else {}


def review_context(private, payload):
    state = task_context.previous_scope(private, payload.get("session_id"))
    binding, warnings, numeric = state.get("binding", []), state.get("warnings", []), state.get("numeric")
    message = payload.get("last_assistant_message")
    numeric = bool(numeric) or isinstance(message, str) and metric_checks.is_claim(message)
    reason = []
    if binding or warnings:
        sources = dict.fromkeys(f"{row['record']} / {row['section']}" for row in binding)
        reason.append("Review the proposed output against the applicable saved rules and decisions. "
                      "Correct any conflicting action or state the unresolved issue.")
        reason.extend(list(sources)[:8])
        reason.extend(warnings[:4])
    if numeric:
        reason.append(NUMBERS_GUIDANCE)
    return {"decision": "block", "reason": "\n".join(reason)} if reason else {}


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
    forecasts = private / "workspace" / "forecasts"
    if any(path == forecasts or forecasts in path.parents for path in (requested, target)):
        return "Use pm.py forecast preview and pm.py forecast apply to preserve forecast history."
    if any(private in path.parents and pm.layout.initiative_work_identity(path.relative_to(private))
           for path in (requested, target)):
        return "Use pm.py task or pm.py launch-checklist to preview and apply changes."
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


def reply_preferences(root):
    values = {}
    result = {}
    try:
        if pm.workspace.private_root(root).is_dir():
            values = preferences.load(pm.workspace.repo(root, "workspace"))
    except (OSError, ValueError):
        result["systemMessage"] = (
            "PM Hub is using default reply preferences. Run pm.py preferences show to check the saved settings."
        )
    result["hookSpecificOutput"] = {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": preferences.guidance(values),
    }
    return result


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
        elif event == "UserPromptSubmit":
            result = reply_preferences(root)
            context = prompt_context(pm.workspace.private_root(root), cwd, payload)
            if context:
                result["hookSpecificOutput"]["additionalContext"] += (
                    "\n" + context["hookSpecificOutput"]["additionalContext"]
                )
        else:
            report = None
            private = pm.workspace.private_root(root)
            if private.is_dir() and event in {"SessionStart", "Stop"}:
                report = pm.alignment(root, prepare=event == "SessionStart")
            checks = pm.check(root)
            if event == "Stop":
                checks = [error for error in checks if not error.startswith(preferences.CHECK_PREFIX)]
            result = response(event, checks, retry)
            if event == "Stop" and not retry and not result and private.is_dir():
                result = review_context(private, payload)
            if event == "SessionStart":
                private = pm.workspace.private_root(root)
                if private.is_dir():
                    prompt = pm.context_capture.remit_prompt(private)
                    if prompt:
                        result["hookSpecificOutput"]["additionalContext"] += (
                            "\nAsk the PM once this session when questions are welcome: " + prompt
                            + " Accept deferral and continue the requested work. Save only PM-confirmed answers with set-remit."
                        )
                notice = pm.alignment_notice(root, report)
                if notice:
                    result["hookSpecificOutput"]["additionalContext"] += "\n" + notice
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(f"PM Hub hook failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
