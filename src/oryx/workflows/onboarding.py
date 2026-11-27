"""Route Studio work through the first unfinished guided walkthrough."""

from pathlib import Path
import re

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
            "Review the whole product first. A PM who owns part of it can choose a separate area walkthrough afterwards. "
            "Leave unverified outcomes open. Ask before looking in a new source or saving a finding."
        )
    return state


WALKTHROUGH_REQUEST = re.compile(
    r"^(?:(?:please|let['’]s|(?:can|could) (?:we|you)|i(?: want| would like) to) )?"
    r"(?:start|begin|resume|continue|pick up|revisit|pause|skip|defer|do) "
    r"(?:(?:the|my|our|optional) )*(?P<target>[\w’' -]+?)"
    r"(?: (?:now|later|for now))?[.!?]*$", re.I
)


def area_request(state, prompt):
    """An explicit walkthrough request can resume an optional pass without intercepting ordinary product work."""
    if not state["ready"]:
        return None
    active = state["stage"] == "area"
    options = state.get("area_options", [])
    if not (active or options or state.get("area_problem")):
        return None
    _, request = conversation.mode_request(prompt)
    match = WALKTHROUGH_REQUEST.fullmatch(request.strip())
    if not match:
        return None
    target = " ".join(match["target"].casefold().split())
    if (active and state.get("stakeholder_profiles", {}).get("status") == "active"
            and target in {"walkthrough", "setup", "onboarding"}):
        return None  # profile_request exposes the ambiguous continuation without choosing for the PM.
    generic = target in {"area walkthrough", "area setup", "area onboarding", "area context", "step 4", "step four"}
    named = []
    if not generic and not (active and target in {"setup", "onboarding", "walkthrough"}):
        # A named request must start with a confirmed area identifier and end with a setup activity.
        # This uses the PM's existing remit without reading private briefs for additional titles.
        name, _, activity = target.replace("-", " ").rpartition(" ")
        if activity not in {"walkthrough", "setup", "onboarding", "context"}:
            return None
        for subject in options:
            slug = subject.rsplit("/", 1)[-1].replace("-", " ")
            if name != slug and not name.startswith(slug + " "):
                continue
            label = name[len(slug):].split()
            if len(label) <= 2 and not {"using", "with", "for", "and", "from"}.intersection(label):
                named.append(subject)
        if not named:
            return None
    if state.get("area_problem"):
        return {"status": "optional_area_walkthrough", "onboarding": {
            "stage": "repair", "next_action": "Review the saved area walkthrough with the PM before resuming it."}}
    selection = {"stage": state["stage"], "revision": state["revision"],
                 "parent": state.get("reviewed_product_subject"), "area_options": options}
    if active and (not named or state["product_scope"]["subject"] in named):
        selection.update(subject=state["product_scope"]["subject"], next_topic=state["walkthroughs"]["area"]["next_topic"])
    if named:
        selection["matching_areas"] = named
    return {"status": "optional_area_walkthrough", "onboarding": selection}


PROFILE_WALKTHROUGH = re.compile(
    r"^(?:(?:please|let['’]s|(?:can|could) (?:we|you)|i(?: want| would like) to) )?"
    r"(?P<activity>set up|start|begin|resume|continue|pick up|revisit|pause|skip|defer|finish|end|do) "
    r"(?:(?:the|my|our|optional) )*(?P<target>stakeholder profiles?(?: (?:walkthrough|onboarding|setup))?"
    r"|(?:walkthrough|onboarding|setup) for stakeholder profiles|walkthrough|onboarding|setup)"
    r"(?: (?:now|later|for now))?[.!?]*$", re.I
)


def profile_request(state, prompt):
    """Only route a direct setup request. Reading a person or bringing new work never resumes setup."""
    if not state["ready"]:
        return None
    _, request = conversation.mode_request(prompt)
    match = PROFILE_WALKTHROUGH.fullmatch(request.strip())
    if not match:
        return None
    progress = state.get("stakeholder_profiles", {})
    if "stakeholder" not in match["target"].casefold():
        if progress.get("status") != "active":
            return None
        if state["stage"] == "area":
            return {"status": "optional_stakeholder_profiles", "onboarding": {
                "stage": "choose", "next_action": "Ask whether the PM means the area walkthrough or stakeholder profile setup."}}
    return {"status": "optional_stakeholder_profiles", "onboarding": {
        "stage": "stakeholder_profiles", "walkthrough": progress,
        "next_action": "Follow the PM's request about profile setup. Use onboarding profiles for their choice; "
                       "look up the person before suggesting one sourced entry."}}


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
