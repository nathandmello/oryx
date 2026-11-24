"""Route Studio work through the first unfinished guided walkthrough."""

from pathlib import Path

import company_onboarding
import conversation
import layout
import onboarding_review
import records


class SetupRequired(ValueError):
    def __init__(self, state):
        super().__init__(state["prompt"])
        self.state = state


def required(state):
    return {"status": "onboarding_required", "onboarding": state}


def setup_destination(relative):
    """Only foundation records can receive setup writes. Raw sources stay at their source."""
    path = Path(relative)
    if path.is_absolute() or any(p.startswith(".") or p in {"secrets", "sources"} for p in path.parts):
        return False
    if path.as_posix() in {layout.PROFILE, layout.COMPANY, layout.STAKEHOLDERS}:
        return True
    if layout.brief_kind(path) == "product-context":
        return True
    return path.parts[:2] == ("context", "company") and not records.context_location("context-note", path)


def status(private):
    """Progress comes from the reviewed topics. Saved facts help the PM discuss each topic."""
    try:
        state = onboarding_review.status(private)
        if state["ready"]:
            return state
        attach_capture(private, state, "company")
        if state["stage"] != "company":
            attach_capture(private, state, "pm")
        if state["stage"] == "product" and state["stage_available"]:
            attach_capture(private, state, "product")
    except (OSError, ValueError) as exc:
        return {"ready": False, "stage": "repair", "stage_available": False,
                "prompt": "Your saved walkthrough needs attention before we can continue.",
                "next_action": "Inspect the saved progress with the PM and agree on a repair.", "problem": str(exc)}
    state["company_updates"] = (
        "When the PM brings new company learning, offer to review it using pm.py company-onboarding status. "
        "Confirm the current business facts, choices and wording with the PM. Distinguish a hypothesis from an observation. "
        "Leave choosing a direction for strategy work. "
        "Keep usage and product-market fit evidence with the specific product and segment. "
        "Updating company context can leave the current walkthrough topic open. Product work still waits for onboarding."
    )
    if state["stage"] != "company":
        state["pm_updates"] = (
            "Use playbook/pm-context.md and pm.py pm-onboarding status for PM and stakeholder context. "
            "Reuse confirmed context with the PM. Review one point at a time. Keep examples tied to their stated period. "
            "Ask before describing one release as typical. Treat aspirations as context. "
            "Keep role facts with the PM and named relationships in the stakeholder map. "
            "Offer a private check-in on an agreed cue. Inspect personal details only after the PM chooses to revisit that point."
        )
    if state["stage"] == "product" and state["stage_available"]:
        state["product_updates"] = (
            "Use playbook/product-context.md and pm.py product-onboarding status. Reuse the PM's confirmed remit. "
            "For an area, cover its parent product and the owned scope in one pass. Keep their findings separate. "
            "Leave unverified outcomes open. Ask before looking in a new source or saving a finding."
        )
    return state


def attach_capture(private, state, kind):
    """Expose only the action needed to resume. Keep sources and proposed wording in the capture command."""
    action_key = "capture_next_action" if kind == "company" else f"{kind}_capture_next_action"
    try:
        phase = company_onboarding.active_phase(company_onboarding.read(private, kind=kind)[1])
    except (OSError, ValueError):
        if state["stage"] == kind:
            raise
        state[f"{kind}_phase"] = "unavailable"
        state[action_key] = f"Inspect the saved {kind} capture with the PM before updating it."
        return
    if phase:
        state[f"{kind}_phase"] = phase
        actions = {"company": company_onboarding.NEXT, "pm": company_onboarding.PM_NEXT,
                   "product": company_onboarding.PRODUCT_NEXT}[kind]
        state[action_key] = actions[phase]


def for_request(private, state, prompt, previous_mode=None):
    """Offer applicable agreed cues without advancing the walkthrough."""
    mode = conversation.mode_request(prompt)[0] or previous_mode
    if mode in ("quiet", "expedite"):
        return {**state, "conversation_mode": mode}
    if state["stage"] not in onboarding_review.STAGES:
        return state
    result = dict(state)
    kinds = onboarding_review.STAGES[:onboarding_review.STAGES.index(state["stage"]) + 1]
    for kind in kinds:
        scope = state.get("product_scope", {})
        if kind == "product" and (scope.get("selection_required") or not scope.get("subject")):
            continue
        cue = company_onboarding.followup(private, prompt, company_scope=state["stage"] == kind, kind=kind,
                                          subject=scope.get("subject") if kind == "product" else None)
        if cue:
            result[f"{kind}_followup"] = cue
    return result
