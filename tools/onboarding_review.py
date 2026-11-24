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
    capture.fields(state, ("format", "revision", "reviewed", "completed"), ("product_selection", "product_history"))
    capture.fields(state["reviewed"], STAGES)
    if type(state["format"]) is not int or state["format"] != 1:
        raise ValueError("Unsupported walkthrough checkpoint format")
    count = 0
    for topics in state["reviewed"].values():
        check_topics(topics)
        count += len(topics)
    receipts = state["completed"]
    if not isinstance(receipts, dict) or not receipts.keys() <= set(STAGES):
        raise ValueError("Invalid completed walkthrough stages")
    for stage, receipt in receipts.items():
        if (not isinstance(receipt, list) or not receipt or not all(isinstance(key, str) for key in receipt)
                or len(set(receipt)) != len(receipt) or set(receipt) != state["reviewed"][stage].keys()):
            raise ValueError("The completed walkthrough needs a receipt for the topics reviewed")
    selected = state.get("product_selection")
    if selected is not None:
        capture.subject_key(selected, ("product",))
    history = state.get("product_history", {})
    if not isinstance(history, dict) or (selected or "unassigned") in history:
        raise ValueError("Invalid saved product walkthrough scopes")
    for subject, prior in history.items():
        if subject != "unassigned":
            capture.subject_key(subject, ("product",))
        capture.fields(prior, ("reviewed", "complete"))
        check_topics(prior["reviewed"])
        if type(prior["complete"]) is not bool or not prior["reviewed"]:
            raise ValueError("Invalid saved product walkthrough coverage")
        count += len(prior["reviewed"])
    if type(state["revision"]) is not int or state["revision"] < count:
        raise ValueError("Invalid walkthrough checkpoint revision")
    return raw, state


def check_topics(topics):
    if not isinstance(topics, dict) or any(
        not layout.SLUG.fullmatch(key) or outcome not in OUTCOMES for key, outcome in topics.items()
    ):
        raise ValueError("Invalid topic disposition in the walkthrough checkpoint")


def product_scope(private, state):
    """A qualified responsibility in the PM remit identifies a subject. Following or depending on it does not."""
    remit, error = capture.inspect_remit(private)
    confirmed = capture.remit_status(remit) == "confirmed"
    responsibilities = [item["subject"] for item in remit["responsibilities"]] if confirmed else []
    choices = [subject for subject in responsibilities if subject.startswith("product/")]
    subject = state.get("product_selection")
    if "product_selection" in state:
        required = subject is not None and subject not in choices
        if subject is None and choices and "product" not in state["completed"]:
            required = not any(item.startswith("area/") for item in responsibilities)
    elif "product" in state["completed"] or state["reviewed"]["product"]:
        # Old private catalogs could have a completed product pass without an attributed subject.
        required = False
    elif len(responsibilities) == len(choices) == 1:
        subject, required = choices[0], False
    else:
        required = True
    result = {"subject": subject, "choices": choices, "selection_required": required}
    if any(item.startswith("area/") for item in responsibilities):
        result["unresolved_parents"] = [item for item in responsibilities if item.startswith("area/")]
    if error:
        result["remit_problem"] = error
    return result


def product_subject(private):
    scope = product_scope(private, read(private)[1])
    return None if scope["selection_required"] else scope["subject"]


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


def view(private, frameworks, state):
    result = snapshot(frameworks, state)
    if result["stage"] == "product" and result["stage_available"]:
        scope = product_scope(private, state)
        result["product_scope"] = scope
        if scope["selection_required"]:
            result["prompt"] = ("Which part of your remit would you like to start with?" if scope["choices"]
                                else "What product or part of a product should we start with?")
            result["next_action"] = ("Reuse the confirmed remit. Clarify the parent if needed. After the PM chooses, "
                                     "use onboarding select-product. An unassigned or unknown scope can stay open.")
    elif result["ready"]:
        # Coverage belongs to the selected pass, even if the PM's responsibilities have since changed.
        result["reviewed_product_subject"] = state.get("product_selection")
    return result


def status(private):
    return view(private, manifest(private.parent), read(private)[1])


def write(private, original, state):
    state["revision"] += 1
    storage.require_visible(private, FILE)
    storage.replace_text(private / FILE, original, json.dumps(state, indent=2) + "\n")


def check_response(payload, state):
    if type(payload["revision"]) is not int or payload["revision"] != state["revision"]:
        raise ValueError("The walkthrough revision is stale. Read onboarding status before continuing")
    if not isinstance(payload["pm_reply"], str) or not payload["pm_reply"].strip():
        raise ValueError("Wait for the PM's response to the current walkthrough step")


def select_product(private, payload):
    """Choose the identity of a coverage pass without assigning ownership or creating a brief."""
    capture.fields(payload, ("revision", "subject", "pm_reply"))
    with storage.writer_lock(private):
        original, state = read(private)
        check_response(payload, state)
        frameworks = manifest(private.parent)
        current = snapshot(frameworks, state)
        if current["stage"] not in {"product", "ready"} or frameworks["product"] is None:
            raise ValueError("Complete company and PM setup before choosing a product walkthrough")
        subject = payload["subject"]
        scope = product_scope(private, state)
        if subject is None:
            if scope["choices"] and not scope.get("unresolved_parents"):
                raise ValueError("Choose a confirmed product responsibility or review the PM's remit")
        elif capture.subject_key(subject, ("product",)) not in scope["choices"]:
            raise ValueError("Confirm the product or qualified product area in the PM remit before selecting it")
        if "product_selection" in state and subject == state["product_selection"]:
            return view(private, frameworks, state)
        import company_onboarding
        if company_onboarding.active(private, kind="product"):
            raise ValueError("Finish the current product source plan before changing the walkthrough scope")
        previous = state.get("product_selection")
        reviewed = state["reviewed"]["product"]
        if subject != previous:
            history = state.setdefault("product_history", {})
            if reviewed:
                history[previous or "unassigned"] = {"reviewed": reviewed, "complete": "product" in state["completed"]}
            prior = history.pop(subject or "unassigned", {"reviewed": {}, "complete": False})
            state["reviewed"]["product"] = prior["reviewed"]
            state["completed"].pop("product", None)
            if prior["complete"]:
                state["completed"]["product"] = list(prior["reviewed"])
        state["product_selection"] = subject
        write(private, original, state)
        return view(private, frameworks, state)


def review(private, payload):
    fields = ("revision", "stage", "topic", "outcome", "pm_reply")
    if isinstance(payload, dict) and payload.get("stage") == "product":
        fields += ("subject",)
    capture.fields(payload, fields)
    if payload["outcome"] not in OUTCOMES:
        raise ValueError("Choose reviewed, open, or not_applicable for the current topic")
    with storage.writer_lock(private):
        original, state = read(private)
        check_response(payload, state)
        frameworks = manifest(private.parent)
        current = view(private, frameworks, state)
        stage = current["stage"]
        if current["ready"] or not current["stage_available"] or payload["stage"] != stage:
            raise ValueError("Review the currently available walkthrough stage")
        if payload["topic"] != current["walkthroughs"][stage]["next_topic"]["id"]:
            raise ValueError("Review the current walkthrough topic with the PM before moving on")
        if stage == "product":
            scope = current["product_scope"]
            if scope["selection_required"]:
                raise ValueError("Choose the product walkthrough scope with the PM before reviewing topics")
            if payload["subject"] != scope["subject"]:
                raise ValueError("The product walkthrough scope changed. Review the current topic with the PM")
            state["product_selection"] = scope["subject"]
        import company_onboarding
        if company_onboarding.read(private, kind=stage)[1]["pending"]:
            raise ValueError(f"Accept or defer the pending {NAMES[stage]} finding before advancing the walkthrough")
        # The receipt records coverage only. Capturing a fact has its own source and wording review.
        topics = state["reviewed"][stage]
        topics[payload["topic"]] = payload["outcome"]
        if all(topic["id"] in topics for topic in frameworks[stage]):
            state["completed"][stage] = list(topics)
        write(private, original, state)
        return view(private, frameworks, state)
