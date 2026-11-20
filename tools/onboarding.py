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
    if path.as_posix() in {layout.PROFILE, layout.COMPANY}:
        return True
    if layout.brief_kind(path) == "product-context":
        return True
    return path.parts[:2] == ("context", "company") and not records.context_location("context-note", path)


def status(private):
    """Progress comes from the reviewed topics. Saved facts help the PM discuss each topic."""
    state = None
    try:
        state = onboarding_review.status(private)
        if state["ready"]:
            return state
        _, capture = company_onboarding.read(private)
    except (OSError, ValueError) as exc:
        if state and state["stage"] != "company":
            return {**state, "company_phase": "unavailable",
                    "capture_next_action": "Inspect the saved company capture with the PM before updating it."}
        return {"ready": False, "stage": "repair", "stage_available": False,
                "prompt": "Your saved walkthrough needs attention before we can continue.",
                "next_action": "Inspect the saved progress with the PM and agree on a repair.", "problem": str(exc)}
    state["company_updates"] = (
        "When the PM brings new company learning, offer to review it using pm.py company-onboarding status. "
        "Agree on the source and wording. Distinguish a hypothesis from an observation. "
        "Updating company context can leave the current walkthrough topic open. Product work still waits for onboarding."
    )
    phase = company_onboarding.active_phase(capture)
    if phase is None:
        return state
    return {**state, "company_phase": phase, "capture_next_action": company_onboarding.NEXT[phase]}


def for_request(private, state, prompt, previous_mode=None):
    """Add an agreed company cue when it fits this turn, without advancing either workflow."""
    mode = conversation.mode_request(prompt)[0] or previous_mode
    if mode in ("quiet", "expedite"):
        return {**state, "conversation_mode": mode}
    if state["stage"] == "repair":
        return state
    cue = company_onboarding.followup(private, prompt, company_scope=state["stage"] == "company")
    return {**state, "company_followup": cue} if cue else state
