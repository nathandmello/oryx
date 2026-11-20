"""Route Studio work through the first unfinished guided walkthrough."""

from pathlib import Path

import company_onboarding
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
    try:
        state = onboarding_review.status(private)
        if state["stage"] != "company":
            return state
        _, capture = company_onboarding.read(private)
    except (OSError, ValueError) as exc:
        return {"ready": False, "stage": "repair", "stage_available": False,
                "prompt": "Your saved walkthrough needs attention before we can continue.",
                "next_action": "Inspect the saved progress with the PM and agree on a repair.", "problem": str(exc)}
    if capture["pending"] is not None:
        phase = "review"
    elif capture["plan"] is not None:
        phase = "gather" if capture["approved"] else "plan"
    else:
        return state
    return {**state, "company_phase": phase, "capture_next_action": company_onboarding.NEXT[phase]}
