"""Remember a PM's optional profile walkthrough independently of required onboarding."""

import json

import context_capture as capture
import offer_queue
import storage


FILE = "workspace/onboarding/stakeholder-profiles.json"
CHOICES = {"start": "active", "later": "deferred", "skip": "skipped", "finish": "complete"}


def read(private):
    path = private / FILE
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError("Use a regular stakeholder walkthrough checkpoint in Studio")
    if not path.exists():
        return None, {"revision": 0, "status": "available"}
    original = path.read_bytes()
    state = storage.json_input(original)
    capture.fields(state, ("revision", "status"))
    if (type(state["revision"]) is not int or state["revision"] < 1
            or state["status"] not in ("offered", *CHOICES.values())):
        raise ValueError("Invalid optional stakeholder walkthrough checkpoint")
    return original, state


def status(private):
    try:
        return read(private)[1]
    except (OSError, ValueError):
        return {"status": "repair", "next_action": "Review the optional profile checkpoint with the PM before changing it."}


def save(private, original, state, disposition):
    updated = {"revision": state["revision"] + 1, "status": disposition}
    storage.require_visible(private, FILE)
    storage.replace_text(private / FILE, original, json.dumps(updated, indent=2) + "\n")
    return updated


PROMPT = ("Offer optional stakeholder profiles once at this handoff. Ask whether to start with one person, "
          "return later, or skip. If the PM has asked to stop or resume their work, follow that request.")


def invitation(private, handle, *, delivered=False):
    """Recheck the exact walkthrough checkpoint before resurfacing a held invitation."""
    import onboarding_review
    setup = onboarding_review.status(private)
    if setup["stage"] != "ready" or setup["revision"] != handle["revision"]:
        return None
    optional = setup["stakeholder_profiles"]
    valid = (optional["status"] == "available" and optional["revision"] == handle["optional"])
    if delivered:
        valid |= optional["status"] == "offered" and optional["revision"] == handle["optional"] + 1
        valid |= optional["status"] == "deferred" and optional["revision"] == handle["optional"] + 2
    if valid:
        token = offer_queue.digest(f"optional-stakeholder-walkthrough:{handle['revision']}:{handle['optional']}")
        return {"status": "offer", "token": token, "next_action": PROMPT}
    return None


def mark_offered(private, handle):
    original, state = read(private)
    if state["status"] != "available" or state["revision"] != handle["optional"]:
        raise ValueError("Review the current optional walkthrough checkpoint")
    return save(private, original, state, "offered")


def offer(private, result, allowed):
    """Called under the walkthrough writer lock at a handoff, never on ordinary reads."""
    if not allowed or result["stakeholder_profiles"]["status"] != "available":
        return result
    try:
        handle = {"revision": result["revision"], "optional": result["stakeholder_profiles"]["revision"]}
        candidate = invitation(private, handle)
        if not candidate:
            return result
        selected = offer_queue.select(private, [{
            "workflow": "profile-onboarding", "token": candidate["token"], "priority": 75,
            "source_kind": "onboarding", "grant_ref": handle, "offer": candidate,
        }], moment="pause", mode="thought-partner")
        if selected.get("token") == candidate["token"]:
            result["stakeholder_profiles"] = read(private)[1]
            result["optional_offer"] = selected
            result["next_action"] = PROMPT
        elif "token" in selected:
            result["optional_offer"] = selected
            result["next_action"] = "Finish the current task. At this pause, use only the selected optional offer."
    except (OSError, ValueError):
        # The required walkthrough is already saved. Optional state or preferences can fail independently.
        result["next_action"] = "Return to the PM's request."
    return result


def choose(private, payload):
    capture.fields(payload, ("revision", "choice", "pm_reply"))
    original, state = read(private)
    if type(payload["revision"]) is not int or payload["revision"] != state["revision"]:
        raise ValueError("Read the current stakeholder_profiles revision before choosing the optional step")
    if not isinstance(payload["pm_reply"], str) or not payload["pm_reply"].strip():
        raise ValueError("Wait for the PM's choice about the stakeholder walkthrough")
    choice = capture.line(payload["choice"], "Stakeholder walkthrough choice")
    if choice not in CHOICES:
        raise ValueError("Choose start, later, skip, or finish for the stakeholder walkthrough")
    if choice == "finish" and state["status"] not in ("active", "complete"):
        raise ValueError("Start the optional stakeholder walkthrough before finishing it")
    if state["status"] != CHOICES[choice]:
        state = save(private, original, state, CHOICES[choice])
    return state
