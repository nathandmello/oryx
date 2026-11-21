"""Track a PM's first walkthrough separately from facts, source approvals and decisions."""

import json

import context_capture as capture
import layout
import storage


FILE = "workspace/onboarding/review.json"
MANIFEST = "playbook/onboarding-frameworks.json"
STAGES = ("company", "pm", "product")
OUTCOMES = ("reviewed", "open", "not_applicable")
NAMES = {"company": "company", "pm": "PM", "product": "product"}


def manifest(root):
    path = root / MANIFEST
    if path.resolve() != path or not path.is_file():
        raise ValueError("Use the regular Core onboarding framework catalog")
    frameworks = storage.json_input(path.read_bytes())
    capture.fields(frameworks, STAGES)
    for stage, topics in frameworks.items():
        if topics is None:
            continue  # A planned framework has no eligible review operations.
        if not isinstance(topics, list) or not topics:
            raise ValueError(f"Define at least one {stage} topic or leave its framework unavailable")
        seen = set()
        for item in topics:
            capture.fields(item, ("id", "question"))
            key = capture.line(item["id"], "Walkthrough topic ID")
            capture.line(item["question"], "Walkthrough question")
            if not layout.SLUG.fullmatch(key) or key in seen:
                raise ValueError(f"Use a unique, stable topic ID within the {stage} framework")
            seen.add(key)
    return frameworks


def read(private):
    path = private / FILE
    if path.resolve() != path:
        raise ValueError("Use a regular walkthrough checkpoint inside Studio")
    if not path.exists():
        return None, {"format": 1, "revision": 0, "reviewed": {stage: {} for stage in STAGES}, "completed": {}}
    if not path.is_file():
        raise ValueError("Use a regular walkthrough checkpoint inside Studio")
    raw = path.read_bytes()
    state = storage.json_input(raw)
    capture.fields(state, ("format", "revision", "reviewed", "completed"))
    capture.fields(state["reviewed"], STAGES)
    if type(state["format"]) is not int or state["format"] != 1:
        raise ValueError("Unsupported walkthrough checkpoint format")
    count = 0
    for topics in state["reviewed"].values():
        if not isinstance(topics, dict) or any(
            not layout.SLUG.fullmatch(key) or outcome not in OUTCOMES for key, outcome in topics.items()
        ):
            raise ValueError("Invalid topic disposition in the walkthrough checkpoint")
        count += len(topics)
    receipts = state["completed"]
    if not isinstance(receipts, dict) or not receipts.keys() <= set(STAGES):
        raise ValueError("Invalid completed walkthrough stages")
    for stage, receipt in receipts.items():
        if (not isinstance(receipt, list) or not receipt or not all(isinstance(key, str) for key in receipt)
                or len(set(receipt)) != len(receipt) or set(receipt) != state["reviewed"][stage].keys()):
            raise ValueError("The completed walkthrough needs a receipt for the topics reviewed")
    if type(state["revision"]) is not int or state["revision"] < count:
        raise ValueError("Invalid walkthrough checkpoint revision")
    return raw, state


def snapshot(frameworks, state):
    walks = {}
    for stage, topics in frameworks.items():
        reviewed = state["reviewed"][stage]
        complete = topics is not None and stage in state["completed"]
        next_topic = None
        if topics and not complete:
            # If an update removed the only outstanding topic, let the PM close
            # their in-progress pass against the final topic still in the framework.
            next_topic = next((topic for topic in topics if topic["id"] not in reviewed), topics[-1])
        walks[stage] = {"complete": complete,
                        "next_topic": next_topic, "reviewed": reviewed}
    stage = next((name for name in STAGES if not walks[name]["complete"]), "ready")
    result = {"revision": state["revision"], "ready": stage == "ready", "stage": stage, "walkthroughs": walks}
    if stage == "ready":
        return dict(result, stage_available=True, prompt="", next_action="Return to the PM's request.")
    if frameworks[stage] is None:
        return dict(result, stage_available=False, prompt=f"The {NAMES[stage]} walkthrough is coming next.",
                    next_action="Keep the request on hold. Resume when the next framework is available.")
    return dict(result, stage_available=True, prompt=walks[stage]["next_topic"]["question"],
                next_action="Review this topic with the PM. Help them use existing evidence or leave a gap open.")


def status(private):
    return snapshot(manifest(private.parent), read(private)[1])


def review(private, payload):
    capture.fields(payload, ("revision", "stage", "topic", "outcome", "pm_reply"))
    if not isinstance(payload["pm_reply"], str) or not payload["pm_reply"].strip():
        raise ValueError("Wait for the PM's response to the current walkthrough topic")
    if payload["outcome"] not in OUTCOMES:
        raise ValueError("Choose reviewed, open, or not_applicable for the current topic")
    with storage.writer_lock(private):
        original, state = read(private)
        if type(payload["revision"]) is not int or payload["revision"] != state["revision"]:
            raise ValueError("The walkthrough revision is stale. Read onboarding status before continuing")
        frameworks = manifest(private.parent)
        view = snapshot(frameworks, state)
        stage = view["stage"]
        if view["ready"] or not view["stage_available"] or payload["stage"] != stage:
            raise ValueError("Review the currently available walkthrough stage")
        if payload["topic"] != view["walkthroughs"][stage]["next_topic"]["id"]:
            raise ValueError("Review the current walkthrough topic with the PM before moving on")
        if stage in {"company", "pm"}:
            import company_onboarding
            if company_onboarding.read(private, kind=stage)[1]["pending"]:
                raise ValueError(f"Accept or defer the pending {NAMES[stage]} finding before advancing the walkthrough")
        # The receipt records coverage only. Capturing a fact has its own source and wording review.
        topics = state["reviewed"][stage]
        topics[payload["topic"]] = payload["outcome"]
        if all(topic["id"] in topics for topic in frameworks[stage]):
            state["completed"][stage] = list(topics)
        state["revision"] += 1
        storage.require_visible(private, FILE)
        storage.replace_text(private / FILE, original, json.dumps(state, indent=2) + "\n")
        return snapshot(frameworks, state)
