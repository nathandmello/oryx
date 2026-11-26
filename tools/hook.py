"""Guide and check oryx work through Codex and Claude hooks."""

import json
import errno
import os

import overrides
from os.path import abspath
from pathlib import Path
import re
import sys
from uuid import uuid4

import conversation
import ingestion_signals
import stakeholder_signals
import onboarding
import pm
import metric_checks
import preferences
import session_journal
import task_context
import turn_intent


CANDOR_GUIDANCE = (
    "Answer directly. Skip reflexive praise or agreement. Respect preferences and decisions. "
    "Agree plainly when warranted. If a claim exceeds the evidence, explain the gap. "
    "Revise your assessment when new facts or a better argument warrant it. "
    "Treat omissions as unknown. Preserve explicit exclusions within their stated scope when recording or reusing context."
)

PROFILE_GUIDANCE = (
    "Use playbook/ingestion.md for any inspected source, including ordinary PM input and summary-only requests. "
    "Keep the primary task moving. Evaluate stakeholder relevance privately in the source's permitted scope. "
    "Run pm.py ingestion assess with grounded observations at a natural pause before offering at most one change. "
    "For a named person's working history, communication, or a rehearsal, read the stakeholder-profiles skill. "
    "On a request to silence these suggestions, save the scoped customization first, even without a reason. "
    "Offer private feedback once if welcome and follow existing opt-in issue reporting. "
    "Only present an optional offer at a natural pause. Use pm.py offer presented TOKEN after observed delivery. "
    "If work would branch, offer a reviewed handoff for another terminal and preserve the parent task. "
    "Use pm.py handoff resume for the PM's open work. Session transcripts are private and independently controlled. "
    "Use pm.py journal only under the PM's direction. For optional client advice read playbook/context-advice.md."
)

CAPTURE_GUIDANCE = (
    PROFILE_GUIDANCE + " "
    "For requests to capture or update context, automatically read .agents/skills/ingest-context/SKILL.md. "
    "For meeting transcripts, read .agents/skills/summarize-meeting/SKILL.md before fetching sources. "
    "Retrieve remote transcripts through the available provider connector and reuse its response for local processing. "
    "If a transcript action is uncertain, ask for clarification and wait before proceeding with that action. "
    "Read the PM remit when available. Preview routes before writing to an authorised record. "
    "For intake, discovery, initiative briefs, or prioritization, read playbook/opportunities.md. "
    "Read the current records using pm.py initiative show. Use initiative propose for proposed changes. "
    "Find metric-linked experiment drafts with initiative show. Leave unknown fields empty. "
    "The PM reviews and approves the exact changes before they are applied. "
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
    "and identify the questions this activity needs answered. Use the PM's prior answers and scoped evidence first. "
    "Follow confirmed relationships to the relevant level of detail. Keep the reasoning brief in chat. "
    "If a material input is still unclear, explain what depends on it and offer to clarify it together. "
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
    "When drafting a schedule or commitment from a source, carry its timing phrase and any exception into the draft "
    "in the original words. Ask the PM to choose if scheduling needs a more exact time. "
    "When the PM brings new company learning, offer to review it. Check pm.py company-onboarding status. "
    "Use unresolved_company_questions to qualify the answer. Offer follow-up on the agreed cue or at the PM’s request. "
    "For role questions or requested coaching, use pm.py pm-profile --topic with the relevant topic. Ask before reading a broader mixed section. "
    "Use only applicable, confirmed context. Use playbook/pm-context.md and pm.py pm-onboarding for updates. "
    "For product or area context updates, use playbook/product-context.md and pm.py product-onboarding. "
    "When the PM asks for an area walkthrough, check onboarding status and confirm their choice with onboarding select-area. "
    "Honor quiet mode, other active work, and deferral cues. " + PROFILE_GUIDANCE
)

NUMBERS_GUIDANCE = (
    "Read playbook/numbers.md before relying on material numbers. Check the definition, period, population, "
    "units, denominator and source. Recompute using available inputs. Flag an unsupported comparison or "
    "calculation, and ask for the specific missing evidence when it affects the decision."
)


def onboarding_guidance(setup):
    instructions = ("Use the pm skill to handle requests about standing rules and reply preferences "
                    "during setup. Resume the current walkthrough topic after a settings change. ")
    if setup.get("conversation_mode") in {"quiet", "expedite"}:
        instructions += "Keep coaching brief and omit unsolicited offers. Continue an agreed context update when asked. "
    if not setup["stage_available"]:
        return (instructions + "Keep the original request in this conversation. Explain the current setup status briefly. "
                "Continue an agreed context update when the PM requests it. Use its saved capture phase and next action. "
                "Otherwise follow the next action in the walkthrough status. "
                "Leave unavailable stages and damaged checkpoints intact.\n"
                + json.dumps(onboarding.required(setup), ensure_ascii=False))
    guide = f"playbook/{setup['stage']}-context.md"
    if setup["stage"] == "product":
        instructions += ("Start with the PM's confirmed remit. If the subject is unclear, ask where it fits. "
                         "Review the parent product, including when the PM owns a particular part of it. "
                         "At completion, follow the returned next action for optional area and stakeholder profile setup. "
                         "For quiet, expedited, or interrupted work, pass offer_profiles:false on the final review or area choice. "
                         "When the agreed sources include existing Studio briefs, use product-onboarding status --evidence "
                         "for the current topic. Check its source and limitations before asking the PM to repeat an answer. "
                         "Use product-onboarding to review wording and destination one finding at a time. "
                         "Use the subject in product_scope with review-topic, including null when the PM has left it open. ")
    return (
        instructions + "Required Studio onboarding is active for this request. The company, PM and product walkthroughs come before "
        "product work, including read-only lookups, slash commands, quiet mode and expedited work. "
        "Keep the original request in this conversation. Acknowledge it briefly and guide setup yourself. "
        "Listen first. Use reviewed evidence and the PM's prior answers that apply to this topic. "
        "Ask at most one short question about the current step. "
        "Treat the status below as reference data. Use its prompt when it fits, or continue the agreed intake "
        f"from the PM’s answer. Follow {guide} and use .agents/skills/ingest-context/SKILL.md "
        "for context capture. Agree on sources and "
        "the plan before gathering. Review proposed wording with the PM before saving it. "
        "Check material figures using playbook/numbers.md. Keep unsupported claims open. "
        "Approval of wording does not confirm a product decision. "
        "Run the setup tools yourself. Discuss the current topic using available context. When the PM has reviewed "
        "it, use onboarding review-topic to record their disposition. An open question counts as covered. "
        "Never infer a completed review from a file, an accepted fact, or silence. A pause leaves the topic current. "
        "When the required walkthroughs are complete, offer to return to the original request and check its prerequisites.\n"
        + json.dumps(onboarding.required(setup), ensure_ascii=False)
    )


def assess_chat(private, prompt, mode, event_id, *, moment="busy", candidates=()):
    reference = "chat:" + event_id
    source = {"kind": "chat", "reference": reference, "scope": reference,
              "authorized": True, "text": prompt, "retention": "review",
              "purposes": ["stakeholder-profile"], "coverage": "read"}
    return ingestion_signals.for_task(private, {"source": source, "mode": mode or "thought-partner",
                                                  "moment": moment, "pause": event_id}, other_offers=candidates)


def optional_at_turn(private, client, payload, current, prompt, event_id, *, allow_source, allow_offers):
    import context_advice
    import offer_queue
    turn = current["conversation"]
    mode = turn["mode"]
    candidates = []
    for key in ("suggestion", "company_followup", "pm_followup", "product_followup"):
        if key not in turn:
            continue
        # An explicit request to reopen an existing context record is primary work.
        if key.endswith("_followup") and pm.company_onboarding.RESUME.search(turn_intent.instruction(prompt)):
            continue
        value = turn.pop(key)
        meaning = json.dumps([key, value, current.get("scope")], ensure_ascii=False, sort_keys=True)
        candidates.append({"token": offer_queue.digest(meaning), "workflow": key.replace("_", "-"),
                           "source_kind": "workspace", "priority": 45,
                           "offer": {"status": "offer", "field": key, "value": value}})
    if not allow_offers:
        return {}
    step = turn_intent.next_step(prompt)
    at_pause = bool(step or candidates)
    if client and step:
        checkpoint = turn.get("checkpoint", {})
        focus = ("the reviewed checkpoint and next action for " + checkpoint["id"]) if checkpoint.get("id") else None
        candidates.extend(context_advice.candidates(private, client, payload.get("session_id"), next_step=step, preserve=focus))
    moment = "pause" if at_pause else "busy"
    result = assess_chat(private, prompt, mode, event_id, moment=moment, candidates=candidates) if allow_source else {}
    selected = result.get("selection")
    if selected is None and (at_pause or candidates):
        try:
            selected = offer_queue.select(private, candidates, moment=moment, mode=mode, pause=event_id)
        except (OSError, ValueError, RuntimeError):
            selected = {}
    if selected and selected.get("status") in {"offer", "clarify"}:
        field = selected.get("field")
        if field in ("suggestion", "company_followup", "pm_followup", "product_followup"):
            turn[field] = selected["value"]
        turn["optional_offer"] = {k: v for k, v in selected.items() if k not in ("field", "value")}
    return result.get("consumers", {})


def prompt_context(private, cwd, payload, *, client=None, off_record=False):
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("UserPromptSubmit needs a prompt")
    visible = session_journal.visible_turn(payload)
    session = payload.get("session_id") if visible else None
    control, profile_refusal, mute = turn_intent.controls(prompt)
    private_turn = off_record or control is not None
    allow_profiles = not (private_turn or profile_refusal or mute)
    numeric = bool(metric_checks.METRIC.search(prompt))
    guidance = [CONVERSATION_GUIDANCE if allow_profiles else CONVERSATION_GUIDANCE.removesuffix(" " + PROFILE_GUIDANCE)]
    if not allow_profiles:
        guidance.append("Apply this request only to the PM's present task. Exclude it from stakeholder evaluation and optional offers.")
    if private_turn:
        guidance.append("Keep this exchange off record. Do not backfill it, save its contents, or prepare optional evidence or handoffs from it.")
    if mute:
        guidance.append("Apply the PM's explicit mute immediately using pm.py override " + mute
                        + " off with the requested scope. A reason is optional.")
    request_text = turn_intent.instruction(prompt)
    current = {}
    if private.is_dir():
        event_id = None
        if allow_profiles:
            try:
                event_id = turn_intent.turn_key(private, client, session, payload, prompt)
            except (OSError, ValueError, RuntimeError):
                pass  # Optional offers require a usable submission identity.
        else:
            turn_intent.end_submission(private, client, session)
        settings_request = turn_intent.exact_mute(prompt) if mute and not private_turn else None
        if settings_request:
            try:
                args = pm.build_parser().parse_args(["override", *settings_request])
                persisted = overrides.run(private.parent, args, defer_reports=True)
                if persisted.get("saved"):
                    guidance.append("The requested suggestion mute is saved. Confirm it briefly. A reason is optional. "
                                    "Run pm.py override sync only under the PM’s existing reporting consent.")
            except (OSError, ValueError, RuntimeError):
                guidance.append("Apply the requested mute with pm.py override before offering anything else.")
        saved = task_context.previous_scope(private, session)
        def leave_audience():
            if "profile_audience" in saved:
                cleared = {key: value for key, value in saved.items() if key != "profile_audience"}
                try:
                    task_context.remember_scope(private, session, cleared, expected=saved)
                except (OSError, ValueError):
                    pass
                return cleared
            return saved
        if private_turn or profile_refusal or mute:
            pm.work_handoffs.bind_active(private, client, payload)
            saved = leave_audience()
        setup = onboarding.status(private)
        if not setup["ready"]:
            pm.work_handoffs.bind_active(private, client, payload)
            # Remember the transition, without copying prompts or source material into the cache.
            setup = onboarding.for_request(private, setup, prompt, saved.get("setup_mode"))
            stage = {"setup_stage": setup["stage"]}
            if "conversation_mode" in setup:
                stage["setup_mode"] = setup["conversation_mode"]
            if not private_turn and saved != stage:
                try:
                    task_context.remember_scope(private, session, stage)
                except (OSError, ValueError):
                    pass  # The live conversation can still carry the original request.
            return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                           "additionalContext": onboarding_guidance(setup) + (("\n" + guidance[-1]) if not allow_profiles else "")}}
        profile_walkthrough = onboarding.profile_request(setup, prompt)
        area = onboarding.area_request(setup, prompt)
        if profile_walkthrough and not area:
            pm.work_handoffs.bind_active(private, client, payload)
            leave_audience()
            guidance += ["Use .agents/skills/stakeholder-profiles/SKILL.md. Use the walkthrough revision and the PM's "
                         "actual choice with onboarding profiles. Keep optional setup separate from approved profile wording.",
                         json.dumps(profile_walkthrough, ensure_ascii=False)]
            return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(guidance)}}
        if area:
            pm.work_handoffs.bind_active(private, client, payload)
            leave_audience()
            if area["onboarding"]["stage"] == "repair":
                guidance.append("Explain the area walkthrough needs attention. Agree on any repair first.")
            else:
                guidance.append(
                    "Use playbook/product-context.md for the optional fourth step. Confirm the area if the request is ambiguous. "
                    "Use the PM’s actual reply to select or pause with onboarding select-area. For the same active area, "
                    "use product-onboarding status and continue at its current topic. Other work remains available.")
            guidance.append(json.dumps(area, ensure_ascii=False))
            return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(guidance)}}
        if saved.get("setup_stage"):
            guidance.append("The PM has gone through the required onboarding frameworks. "
                            "If the PM has a waiting request in this conversation, offer to resume it once. "
                            "Follow their current direction and complete only the work they agree to.")
        prior = saved
        if prior.get("handoff"):
            # Revalidate this work before reusing its record, pace, or audience.
            saved = {}
        active = task_context.previous_scope(private, pm.work_handoffs.active_key(client, session)) if allow_profiles else {}
        _, subject = conversation.mode_request(request_text)
        continuing = active and pm.work_handoffs.CURRENT_TASK.fullmatch(subject)
        resume = (pm.work_handoffs.for_prompt(private, subject, client=client, payload=payload)
                  if visible and allow_profiles and not continuing else None)
        work = None
        if resume:
            work = resume.get("work")
            if not work:
                if prior:
                    try:
                        task_context.remember_scope(private, session, {}, expected=prior)
                    except (OSError, ValueError):
                        pass
                guidance.append("The PM asked to resume work. Verify the current scope. If several match, ask which one.\n"
                                + json.dumps(resume, ensure_ascii=False))
                return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(guidance)}}
        elif active:
            work = pm.work_handoffs.bind_active(private, client, payload, continuing=True)
        if work:
            record = work.get("record") or work.get("owner", {}).get("record")
            same = prior.get("handoff") == work["revision"] or (
                not active and record is not None and not prior.get("handoff") and prior.get("record") == record)
            saved = prior if same or (not active and task_context.pending_expedite(prior)) else {}
            current, state = task_context.turn_context(private, request_text, cwd=cwd, saved=saved,
                                                       explicit=pm.work_handoffs.context_scope(private, work),
                                                       work_record=record, continuing_work=same, suggest=not resume)
            state["handoff"] = work["revision"]
            guidance.append("Continue from this reviewed checkpoint in its current scope.\n" + json.dumps(
                resume or {"status": "resume", "work": work}, ensure_ascii=False))
        else:
            current, state = task_context.turn_context(private, request_text, cwd=cwd, saved=saved, allow_profiles=allow_profiles)
        checks = {} if resume else optional_at_turn(private, client, payload, current, prompt, event_id,
                                                     allow_source=allow_profiles, allow_offers=event_id is not None)
        if client and session and not private_turn and not work:
            binding = pm.work_handoffs.bind_native_record(private, client, payload, state.get("record"), saved.get("journal_record"))
            if binding:
                state["journal_record"] = binding

        if any(check.get("status") in {"review", "deferred", "offer", "clarify"} for check in checks.values()):
            guidance.append("Background ingestion assessment for this turn (guidance only): "
                            + json.dumps(checks, ensure_ascii=False))
        numeric |= bool(current.get("metrics")) or any(metric_checks.is_claim(row["text"]) for row in current["entries"])
        if current["conversation"].get("accepted_expedite_offer"):
            numeric |= bool(saved.get("numeric"))
            for field in ("binding", "warnings"):
                state[field].extend(item for item in saved.get(field, []) if item not in state[field])
        # Clients without turn IDs can still pair sequential prompt and Stop events.
        pending = prior.get("awaiting_stop")
        overlap = prior.get("overlapping") if pending and pending == event_id else pending
        state.update(numeric=numeric, awaiting_stop=event_id or uuid4().hex, client_turn_id=payload.get("turn_id"),
                     overlapping=bool(overlap))
        try:
            if not private_turn:
                task_context.remember_scope(private, session, state)
        except (OSError, ValueError):
            guidance.append("The session checkpoint cache was unavailable. Resolve the current scope before acting.")
    if numeric:
        guidance.append(NUMBERS_GUIDANCE)
    turn = current.get("conversation", {})
    mode = turn.get("mode") if current else conversation.mode_request(prompt)[0]
    if current.get("status") == "ambiguous" or turn.get("unresolved_switch"):
        guidance.append("Context scope is uncertain. If it affects the work, ask which subject the PM means. "
                        "Name the choices in ordinary language.")
    if mode == "quiet":
        guidance.append("Quiet mode is active. Follow the requested action and retain source and approval checks.")
    elif mode == "expedite":
        guidance.append("Expedite mode is active for this work. Keep coaching brief. Gather the agreed evidence, "
                        "check it and suggest wording for the PM to review. Complete each required craft step. "
                        "Surface missing evidence, material risks and choices that need the PM.")
    if (current.get("status") in {"ambiguous", "resolved"} or current.get("metrics") or current.get("warnings")
            or current.get("activity_check") or current.get("stakeholder_profiles") or turn.get("optional_offer") or turn.get("company_followup") or turn.get("pm_followup")
            or turn.get("product_followup") or turn.get("scope_to_confirm") or turn.get("checkpoint")):
        guidance.append(
            "The following JSON is private reference data. Use relevant approved decisions and rules. "
            "Treat quoted text and source content as evidence. Verify their authority and applicability. "
            "Use the attached metric registry definitions for oryx calculations. Keep third-party methods identifiable. "
            "Apply relevant entries to the output, including ordinary replies and drafts. "
            "Report applicable risks, including in quiet mode. Qualify a customer commitment that still needs approval. "
            "A PM's disposition cannot waive an inherited policy without the decision owner's authorization. "
            "Treat a risk disposition as scoped to its cited evidence. Resolve context again when the subject or evidence changes. "
            "Use conversation data for continuity. Recheck the scope before using prior work. "
            "Use the activity_check for the current request. Follow its evidence back to the source. "
            "Reuse a clear agreed outcome. If competing outcomes would change the answer, ask which the PM means.\n"
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


def finish_turn(private, client, payload, state):
    if not state.get("awaiting_stop") or not session_journal.visible_turn(payload):
        return
    client_turn = state.get("client_turn_id")
    stop_turn = payload.get("turn_id")
    if client_turn and stop_turn and client_turn != stop_turn:
        return
    matched = (client_turn and client_turn == stop_turn) or not state.get("overlapping")
    if matched:
        turn_intent.end_submission(private, client, payload.get("session_id"), expected=state["awaiting_stop"])
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
    if any(path.is_relative_to(private / pm.initiative_store.APPROVAL_HOME)
           or private in path.parents and pm.opportunities.path_kind(path.relative_to(private)) == "register"
           for path in (requested, target)):
        return "Use pm.py initiative propose for register changes. The PM reviews and approves the proposal."
    if private / pm.company_onboarding.FILE in (requested, target):
        return "Use pm.py company-onboarding to preserve the approved source scope and reviewed items."
    if private / pm.company_onboarding.PM_FILE in (requested, target):
        return "Use pm.py pm-onboarding to preserve approved sources and the wording under review."
    if private / pm.company_onboarding.PRODUCT_FILE in (requested, target):
        return "Use pm.py product-onboarding to preserve approved sources, destinations and wording."
    if private / pm.ingestion_signals.source_evidence.GRANTS in (requested, target):
        return "Use pm.py ingestion to grant, inspect or revoke source access."
    if private / pm.stakeholder_profiles.STAMPS in (requested, target):
        return "Use pm.py stakeholder-profile index to verify the private identity index."
    if any(path.is_relative_to(private / pm.stakeholder_profiles.HOME) for path in (requested, target)):
        return "Use pm.py stakeholder-profile preview and accept after the PM approves the exact wording."
    if private / pm.work_handoffs.FILE in (requested, target):
        return "Use pm.py handoff to review, save and resume scoped work."
    if private / pm.offer_queue.FILE in (requested, target):
        return "Use pm.py offer to review a pending suggestion or record its delivery."
    if private / stakeholder_signals.FILE in (requested, target):
        return "Use pm.py ingestion presented or decline for stakeholder suggestion receipts."
    if private / pm.onboarding_profile_step.FILE in (requested, target):
        return "Use pm.py onboarding profiles for the optional stakeholder walkthrough."
    if private / pm.onboarding_review.FILE in (requested, target):
        return "Use pm.py onboarding review-topic after discussing the current topic with the PM."
    company = private / "context" / "company"
    if any(path == company or company in path.parents for path in (requested, target)):
        try:
            if pm.company_onboarding.active(private):
                return "Use pm.py company-onboarding to review and accept company context within the current source plan."
        except (OSError, ValueError):
            return "Check the saved company onboarding state with pm.py company-onboarding status before editing this record."
    pm_records = {private / pm.layout.PROFILE, private / pm.layout.STAKEHOLDERS}
    if pm_records.intersection((requested, target)):
        try:
            setup = onboarding.status(private)
            if setup["stage"] in {"company", "repair"}:
                return setup["next_action"]
            if setup["stage"] == "pm" or pm.company_onboarding.active(private, kind="pm"):
                return "Use pm.py pm-onboarding to review and accept PM or stakeholder wording in the agreed scope."
        except (OSError, ValueError):
            return "Check pm.py onboarding status and pm.py pm-onboarding status before editing this record."
    for path in {requested, target}:
        if not path.is_relative_to(private / "context" / "products"):
            continue
        relative = path.relative_to(private)
        try:
            setup = onboarding.status(private)
            if setup["stage"] == "repair":
                return setup["next_action"]
            if setup["stage"] == "product":
                return "Use pm.py product-onboarding to review the parent product before starting an area walkthrough."
            if pm.company_onboarding.product_capture_owns(private, relative):
                return "Use pm.py product-onboarding to review and accept changes in the agreed destination."
        except (OSError, ValueError):
            return "Check pm.py product-onboarding status with the PM before editing this record."
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


def journal_before_prompt(private, client, payload):
    if not private or not client or not payload.get("session_id"):
        return turn_intent.controls(payload.get("prompt", ""))[0] is not None
    choice = turn_intent.controls(payload.get("prompt", ""))[0]
    try:
        if choice is not None:
            session_journal.set_off_record(private, client, payload["session_id"], choice)
            return True  # Both control turns are excluded.
        private_turn = session_journal.off_record(private, client, payload["session_id"])
        if not private_turn:
            session_journal.capture(private, client, payload)
        return private_turn
    except (OSError, ValueError):
        # An unreadable privacy policy cannot authorize optional processing.
        return True


def record_native_event(private, client, payload, *, journal=False, metrics=False):
    if private is None or client is None:
        return
    if journal:
        try:
            session_journal.capture(private, client, payload)
        except (OSError, ValueError):
            pass  # The transcript writer never interrupts the PM's task.
    if metrics:
        import context_advice
        try:
            context_advice.observe_hook(private, client, payload)
        except (OSError, ValueError):
            pass  # Missing or invalid telemetry cannot authorize guidance.


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
        client = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("claude", "codex") else os.environ.get("PM_HUB_CLIENT")
        if client not in ("claude", "codex"):
            client = None
        private = pm.workspace.optional_repo(root)
        if event in {"SessionStart", "PreCompact", "PostCompact"} and session_journal.visible_turn(payload):
            turn_intent.end_submission(private, client, payload.get("session_id"))
        if event in {"PreCompact", "PostCompact", "PostModelRequest"}:
            record_native_event(private, client, payload, metrics=True)
            result = {}
        elif event == "PreToolUse":
            result = edit_guard(root, cwd, payload)
        elif event == "UserPromptSubmit" and not session_journal.visible_turn(payload):
            # Only a visible PM submission can supply controls, evidence or session state.
            result = {"hookSpecificOutput": {"hookEventName": event,
                                             "additionalContext": "Continue the assigned work under the PM's existing settings."}}
        elif event == "UserPromptSubmit":
            private_turn = journal_before_prompt(private, client, payload)
            if not private_turn:
                record_native_event(private, client, payload, metrics=True)
            result = reply_preferences(root)
            context = prompt_context(pm.workspace.private_root(root), cwd, payload, client=client, off_record=private_turn)
            if context:
                result["hookSpecificOutput"]["additionalContext"] += (
                    "\n" + context["hookSpecificOutput"]["additionalContext"]
                )
        else:
            report = None
            if event == "SessionStart":
                if private and payload.get("source") not in ("resume", "compact"):
                    pm.work_handoffs.bind_active(private, client, payload)
                record_native_event(private, client, payload, journal=True, metrics=True)
            state = task_context.previous_scope(private, payload.get("session_id")) if private and event == "Stop" else {}
            if private is not None and event in {"SessionStart", "Stop"}:
                report = pm.alignment(root, prepare=event == "SessionStart")
            checks = pm.check(root, validate_profiles=False)
            if event == "Stop":
                prefix = f"{private.name if private else pm.storage.STUDIO}/{preferences.CHECK_PREFIX}"
                checks = [error for error in checks if not error.startswith(prefix)]
            result = response(event, checks, retry)
            if event == "Stop" and private is not None:
                if not retry and not result:
                    result = review_context(state, payload)
                if result.get("decision") != "block":
                    record_native_event(private, client, payload, journal=True)
                    finish_turn(private, client, payload, state)
            if event == "SessionStart":
                if private is not None:
                    setup = onboarding.status(private)
                    if not setup["ready"]:
                        result["hookSpecificOutput"]["additionalContext"] = onboarding_guidance(setup)
                notice = pm.alignment_notice(root, report)
                if notice:
                    result["hookSpecificOutput"]["additionalContext"] += "\n" + notice
        if event in {"SessionStart", "UserPromptSubmit"}:
            output = result["hookSpecificOutput"]
            output["additionalContext"] = CANDOR_GUIDANCE + "\n" + output["additionalContext"]
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(f"oryx hook failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
