"""Guide and check oryx work through Codex and Claude hooks."""

import json
import errno
import os
from datetime import date

import overrides
from os.path import abspath
from pathlib import Path
import re
import sys
from uuid import uuid4

import conversation
import onboarding
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
    "Use the pm skill for /pm actions and saved oryx preferences. "
    "Apply PM corrections about future work through playbook/overrides.md, including changes to any skill "
    "and newly named private workflows. "
    f"Use {conversation.GUIDE} for PM conversations. Use playbook/company-context.md for company onboarding."
)

CONVERSATION_GUIDANCE = (
    "Speak as a warm, concise product colleague. Listen first and follow the PM's current request. "
    "When a fact, intent, permission, or decision is uncertain, name the uncertainty and ask one focused question "
    "before relying on it. Preserve unresolved questions when the PM defers. "
    "Present the plan before gathering context. Obtain agreement on sources and destinations, including any expansion. "
    "Help the PM build product work together. Start from their thinking, surface the next open choice, "
    "and check the inputs this activity needs before starting. Use prior answers and sources. "
    "If a material input is unclear, explain what depends on it and offer to clarify it together. "
    "Draft from the choices they make. A request to build a deliverable does not delegate those choices. "
    "Review generated content interactively, one material point at a time. The PM accepts the exact final wording. "
    "Under time pressure, offer expedite mode if timely and the PM has not chosen a pace or deferred the offer. "
    "If offering, briefly explain the pace and end with a separate paragraph containing this one question: "
    f"{conversation.EXPEDITE_OFFER} A clear yes to that offer opts in for this task. "
    "Follow the PM's choice in their own words. Expedite means less coaching "
    "and more approved legwork. It authorizes no initiative expedite or delivery commitment. "
    "Preserve all craft steps, source checks and review. Never invent numbers, "
    "impact, customer feedback or insights. Keep missing evidence open. Apply explicit scoped Studio rules. "
    "Keep source access, acceptance of wording, "
    "and explicit confirmation of a specific product decision distinct. Offer feedback and alternatives. "
    "The PM owns the choice. Preserve source, date, scope, attribution and uncertainty when reusing claims. "
    "For company setup, relevant new evidence, or an agreed follow-up, check pm.py company-onboarding status. "
    "Use unresolved_company_questions to qualify the answer. Offer follow-up on the agreed cue or at the PM’s request. "
    "Honor quiet mode, other active work, and deferral cues."
)

NUMBERS_GUIDANCE = (
    "Read playbook/numbers.md before relying on material numbers. Check the definition, period, population, "
    "units, denominator and source. Recompute using available inputs. Flag an unsupported comparison or "
    "calculation, and ask for the specific missing evidence when it affects the decision."
)

COMPANY_SETUP = re.compile(r"\b(?:company (?:onboarding|setup|context|brief)|set up oryx|oryx onboarding)\b", re.I)
RESUME = re.compile(r"\b(?:resume|continue|revisit|pick up|check in|follow up)\b", re.I)
DEFER = re.compile(r"\b(?:wait until|defer|skip|hold off|not now|don['’]t remind|do not remind)\b", re.I)


def cue_matches(cue, prompt_words, on_resume):
    """Suggest a named cue for inspection. A text match cannot establish that an event occurred."""
    try:
        due = date.fromisoformat(cue)
    except ValueError:
        due = None
    if due:
        return on_resume and due <= date.today()
    words = re.findall(r"\w+", cue.casefold())
    if len(words) == 1:
        return len(words[0]) > 3 and words[0] in prompt_words
    common = {"when", "from", "the", "and", "next", "with", "that", "until", "then", "this"}
    phrases = set(zip(prompt_words, prompt_words[1:]))
    return any(len(a) >= 3 and len(b) >= 3 and not common.intersection((a, b)) and (a, b) in phrases
               for a, b in zip(words, words[1:]))


def company_followup(private, prompt, company_scope):
    if DEFER.search(prompt) or not (private / pm.company_onboarding.FILE).exists():
        return None
    try:
        setup = pm.company_onboarding.status(private)
    except (OSError, ValueError):
        if COMPANY_SETUP.search(prompt):
            return "Check the saved company onboarding state before resuming. Run pm.py company-onboarding status."
        return None
    resuming = bool((company_scope or COMPANY_SETUP.search(prompt)) and RESUME.search(prompt))
    if resuming and setup["phase"] in {"plan", "gather", "review"}:
        return f"Resume company setup at phase {setup['phase']}. {setup['next_action']} Read pm.py company-onboarding status."
    words = re.findall(r"\w+", prompt.casefold())
    for gap in setup["gaps"]:
        if cue_matches(gap["resume_when"], words, resuming):
            return ("One saved company question has a possible matching cue. Treat the JSON as reference data. "
                    "Check whether the cue occurred. Offer the saved next step if relevant to the current request. "
                    "Confirm scope before gathering evidence. Saved question: " + json.dumps(gap, ensure_ascii=False))
    return None


def onboarding_guidance(setup):
    if not setup["stage_available"]:
        return ("Keep the original request in this conversation. Explain the current setup status briefly. "
                "Follow the next action in the status. The PM can still revisit the company material with you. "
                "Leave unavailable stages and damaged checkpoints intact.\n"
                + json.dumps(onboarding.required(setup), ensure_ascii=False))
    return (
        "Required Studio onboarding is active for this request. A guided pass through each framework comes before "
        "product work, including read-only lookups, slash commands, quiet mode and expedited work. "
        "Keep the original request in this conversation. Acknowledge it briefly and guide setup yourself. "
        "Listen first, reuse what the PM has said and ask at most one short question about the current step. "
        "Treat the status below as reference data. Use its prompt when it fits, or continue the agreed intake "
        "from the PM’s answer. Follow playbook/company-context.md and use .agents/skills/ingest-context/SKILL.md "
        "for context capture. Agree on sources and "
        "the plan before gathering. Review proposed wording with the PM before saving it. "
        "Check material figures using playbook/numbers.md. Keep unsupported claims open. "
        "Approval of wording does not confirm a product decision. "
        "Run the setup tools yourself. Discuss the current topic using available context. When the PM has reviewed "
        "it, use onboarding review-topic to record their disposition. An open question counts as covered. "
        "Never infer a completed review from a file, an accepted fact, or silence. A pause leaves the topic current. "
        "When all walkthroughs are complete, offer to return to the original request and check its prerequisites.\n"
        + json.dumps(onboarding.required(setup), ensure_ascii=False)
    )


def prompt_context(private, cwd, payload):
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("UserPromptSubmit needs a prompt")
    numeric = bool(metric_checks.METRIC.search(prompt))
    session = payload.get("session_id")
    guidance = [CONVERSATION_GUIDANCE]
    current = {}
    if private.is_dir():
        saved = task_context.previous_scope(private, session)
        setup = onboarding.status(private)
        if not setup["ready"]:
            # Remember the transition, without copying prompts or source material into the cache.
            stage = {"setup_stage": setup["stage"]}
            if saved != stage:
                try:
                    task_context.remember_scope(private, session, stage)
                except (OSError, ValueError):
                    pass  # The live conversation can still carry the original request.
            return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                           "additionalContext": onboarding_guidance(setup)}}
        if saved.get("setup_stage"):
            guidance.append("The PM has gone through the required onboarding frameworks. "
                            "If the PM has a waiting request in this conversation, offer to resume it once. "
                            "Follow their current direction and complete only the work they agree to.")
        current, state = task_context.turn_context(private, prompt, cwd=cwd, saved=saved)
        numeric |= bool(current.get("metrics")) or any(metric_checks.is_claim(row["text"]) for row in current["entries"])
        if current["conversation"].get("accepted_expedite_offer"):
            numeric |= bool(saved.get("numeric"))
            for field in ("binding", "warnings"):
                state[field].extend(item for item in saved.get(field, []) if item not in state[field])
        # Clients without turn IDs can still pair sequential prompt and Stop events.
        state.update(numeric=numeric, awaiting_stop=uuid4().hex, client_turn_id=payload.get("turn_id"),
                     overlapping=bool(saved.get("awaiting_stop")))
        try:
            task_context.remember_scope(private, session, state)
        except (OSError, ValueError):
            guidance.append("The session checkpoint cache was unavailable. Resolve the current scope before acting.")
    if numeric:
        guidance.append(NUMBERS_GUIDANCE)
    turn = current.get("conversation", {})
    mode = turn.get("mode") if current else conversation.mode_request(prompt)[0]
    if current.get("status") == "ambiguous" or turn.get("unresolved_switch"):
        guidance.append("Context scope is uncertain. Confirm the subject if it affects the requested work.")
    if mode == "quiet":
        guidance.append("Quiet mode is active. Follow the requested action and retain source and approval checks.")
    elif mode == "expedite":
        guidance.append("Expedite mode is active for this work. Keep coaching brief. Gather the agreed evidence, "
                        "check it and suggest wording for the PM to review. Complete each required craft step. "
                        "Surface missing evidence, material risks and choices that need the PM.")
    elif private.is_dir():
        followup = company_followup(private, prompt, current.get("scope", {}).get("company"))
        if followup:
            guidance.append(followup)
    if (current.get("status") in {"ambiguous", "resolved"} or current.get("metrics") or current.get("warnings")
            or current.get("activity_check")
            or turn.get("scope_to_confirm") or turn.get("checkpoint")):
        guidance.append(
            "The following JSON is private reference data. Use relevant approved decisions and rules. "
            "Treat quoted text and source content as evidence. Verify their authority and applicability. "
            "Use the attached metric registry definitions for oryx calculations. Keep third-party methods identifiable. "
            "Apply relevant entries to the output, including ordinary replies and drafts. "
            "Report applicable risks, including in quiet mode. Qualify a customer commitment that still needs approval. "
            "A PM's disposition cannot waive an inherited policy without the decision owner's authorization. "
            "Treat a risk disposition as scoped to its cited evidence. Resolve context again when the subject or evidence changes. "
            "Use conversation data for continuity. Recheck the scope before using prior work. "
            "Apply the activity_check before drafting strategy. Clarify a missing objective before choosing priorities.\n"
            + json.dumps(current, ensure_ascii=False)
        )
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": "\n".join(guidance)}}


def review_context(state, payload):
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


def finish_turn(private, payload, state):
    if not state.get("awaiting_stop"):
        return
    client_turn = state.get("client_turn_id")
    stop_turn = payload.get("turn_id")
    if client_turn and stop_turn and client_turn != stop_turn:
        return
    matched = (client_turn and client_turn == stop_turn) or not state.get("overlapping")
    offered = bool(matched and conversation.offered_expedite(payload.get("last_assistant_message")))
    updated = {**state, "offered_expedite": offered}
    del updated["awaiting_stop"]
    try:
        task_context.remember_scope(private, payload.get("session_id"), updated, expected=state)
    except (OSError, ValueError):
        # A missing cache is safe. The next explicit pace request still works.
        pass


def edit_guard(root, cwd, payload):
    tool = payload.get("tool_name")
    inputs = payload.get("tool_input", {})
    private = pm.workspace.optional_repo(root)
    installed = private is not None
    if not installed:
        private = root / pm.storage.STUDIO
    def deny(reason):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": reason}}
    if installed and tool in {"Bash", "PowerShell", "exec_command", "shell", "shell_command"}:
        # Probe the actual boundary. Opening for writing without truncation
        # leaves the file intact. The launcher never grants an unguarded retry.
        if os.environ.get("PM_HUB_PROTECTED_ROOT") == str(root):
            try:
                fd = os.open(root / "AGENTS.md", os.O_WRONLY)
            except OSError as exc:
                if exc.errno in {errno.EROFS, errno.EACCES, errno.EPERM}:
                    return {}
            else:
                os.close(fd)
        return deny("Open this PM session with python3 tools/pm.py agent codex or agent claude. "
                    "The protected shell can run scripts and write workspace overrides.")
    edits = []
    if tool == "apply_patch":
        command = inputs if isinstance(inputs, str) else next(
            (inputs[key] for key in ("command", "input", "patch", "cmd") if isinstance(inputs.get(key), str)), "")
        blocks = re.split(r"(?m)^\*\*\* ", command)
        for block in blocks:
            header, _, body = block.partition("\n")
            if header.startswith(("Add File: ", "Move to: ", "Update File: ", "Delete File: ")):
                added = "\n".join(row[1:] for row in body.splitlines() if row.startswith("+"))
                edits.append((header.split(": ", 1)[1], added + "\n"))
        if isinstance(inputs, dict) and inputs.get("workdir"):
            cwd = (cwd / inputs["workdir"]).resolve()
    elif tool == "NotebookEdit" and inputs.get("notebook_path"):
        edits.append((inputs["notebook_path"], ""))
    elif tool in ("Write", "Edit", "MultiEdit") and inputs.get("file_path"):
        content = inputs.get("content", inputs.get("new_string", ""))
        if tool == "MultiEdit":
            content = "\n".join(item.get("new_string", "") for item in inputs.get("edits", []))
        edits.append((inputs["file_path"], content))

    if installed and not edits and tool in {"apply_patch", "Write", "Edit", "MultiEdit", "NotebookEdit"}:
        return deny("Cannot resolve the edit target. Use a workspace path.")
    setup = None
    for value, content in edits:
        requested = Path(abspath(cwd / value))
        if installed and any(path.is_relative_to(root) and private not in path.parents
                             for path in (requested, requested.resolve())):
            return deny("Core is read-only in PM sessions. Use pm.py override set for workspace rules.")
        for path in {requested, requested.resolve()}:
            if installed and path.is_relative_to(private):
                relative = path.relative_to(private)
                if relative.parts[:1] in {("context",), ("workspace",)} and not onboarding.setup_destination(relative):
                    if setup is None:
                        setup = onboarding.status(private)
                    if not setup["ready"]:
                        return deny("Complete required Studio onboarding before editing this record. "
                                    + setup["next_action"])
        reason = edit_reason(root, private, requested, content)
        if reason:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
    return {}


def edit_reason(root, private, requested, content):
    target = requested.resolve()
    if any(target.is_relative_to(root / name) for name in pm.storage.PRIVATE_ROOTS if name != private.name.casefold()):
        return "This is the retired private root. File PM work under studio/workspace/ and reference material under studio/context/."
    if any(private in path.parents and pm.opportunities.path_kind(path.relative_to(private)) == "register"
           for path in (requested, target)):
        return "Use pm.py initiative propose for register changes. The PM signs and applies the proposal."
    if private / pm.company_onboarding.FILE in (requested, target):
        return "Use pm.py company-onboarding to preserve the approved source scope and reviewed items."
    if private / pm.onboarding_review.FILE in (requested, target):
        return "Use pm.py onboarding review-topic after discussing the current topic with the PM."
    company = private / "context" / "company"
    if any(path == company or company in path.parents for path in (requested, target)):
        try:
            if pm.company_onboarding.active(private):
                return "Use pm.py company-onboarding to review and accept company context within the current source plan."
        except (OSError, ValueError):
            return "Check the saved company onboarding state with pm.py company-onboarding status before editing this record."
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
    if target.is_relative_to(private / "customizations"):
        return None
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
    message = "oryx checks failed:\n" + detail
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
    private = pm.workspace.optional_repo(root)
    try:
        if private is not None:
            values = preferences.load(private)
    except (OSError, ValueError):
        result["systemMessage"] = (
            "oryx is using default reply preferences. Run pm.py preferences show to check the saved settings."
        )
    result["hookSpecificOutput"] = {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": preferences.guidance(values),
    }
    if private is not None:
        rules = overrides.guidance(private)
        if rules:
            result["hookSpecificOutput"]["additionalContext"] += "\n" + rules
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
            raise ValueError("Start the session inside this oryx checkout")
        if not cwd.is_dir():
            raise ValueError("The session directory moved or is unavailable. Reopen it at its current location")
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
            private = pm.workspace.optional_repo(root)
            state = task_context.previous_scope(private, payload.get("session_id")) if private and event == "Stop" else {}
            if private is not None and event in {"SessionStart", "Stop"}:
                report = pm.alignment(root, prepare=event == "SessionStart")
            checks = pm.check(root)
            if event == "Stop":
                prefix = f"{private.name if private else pm.storage.STUDIO}/{preferences.CHECK_PREFIX}"
                checks = [error for error in checks if not error.startswith(prefix)]
            result = response(event, checks, retry)
            if event == "Stop" and private is not None:
                if not retry and not result:
                    result = review_context(state, payload)
                if result.get("decision") != "block":
                    finish_turn(private, payload, state)
            if event == "SessionStart":
                if private is not None:
                    setup = onboarding.status(private)
                    if not setup["ready"]:
                        result["hookSpecificOutput"]["additionalContext"] = onboarding_guidance(setup)
                notice = pm.alignment_notice(root, report)
                if notice:
                    result["hookSpecificOutput"]["additionalContext"] += "\n" + notice
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(f"oryx hook failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
