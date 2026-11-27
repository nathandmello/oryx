"""Track a PM's first walkthrough separately from facts, source approvals and decisions."""

import json

import context_capture as capture
import layout
import onboarding_profile_step
import storage


FILE = "workspace/onboarding/review.json"
MANIFEST = "playbook/onboarding-frameworks.json"
STAGES = ("company", "pm", "product")
OUTCOMES = ("reviewed", "open", "not_applicable")
NAMES = {"company": "company", "pm": "PM", "product": "product", "area": "area"}


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


def read(private, *, for_status=False):
    path = private / FILE
    if path.resolve() != path:
        raise ValueError("Use a regular walkthrough checkpoint inside Studio")
    if not path.exists():
        return None, {"format": 1, "revision": 0, "reviewed": {stage: {} for stage in STAGES}, "completed": {}}
    if not path.is_file():
        raise ValueError("Use a regular walkthrough checkpoint inside Studio")
    raw = path.read_bytes()
    state = storage.json_input(raw)
    capture.fields(state, ("format", "revision", "reviewed", "completed"),
                   ("product_selection", "product_history", "area_selection", "area_history", "area_deferred"))
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
        count += check_pass(prior)
    if type(state["revision"]) is not int or state["revision"] < count:
        raise ValueError("Invalid walkthrough checkpoint revision")
    try:
        validate_area_progress(state, count)
    except ValueError as exc:
        message = "Repair the optional area walkthrough before continuing its review."
        if not for_status:
            raise ValueError(message) from exc
        state["area_problem"] = message
    if selected and "/area/" in selected and "product" not in receipts:
        # v0.13 did not distinguish parent topics from child topics. Keep the original
        # progress under its mixed subject; resume with the parent's own coverage.
        switch_product(state, parent_product(selected))
    return raw, state


def validate_area_progress(state, count):
    area_history = state.get("area_history", {})
    if not isinstance(area_history, dict):
        raise ValueError("Invalid saved area walkthroughs")
    for subject, prior in area_history.items():
        check_area(subject)
        count += check_pass(prior)
    active = state.get("area_selection")
    if active is not None:
        check_area(active)
        if area_history.get(active, {}).get("complete") or state.get("product_selection") != parent_product(active) or "product" not in state["completed"]:
            raise ValueError("The active area walkthrough needs its completed parent product walkthrough")
    deferred = state.get("area_deferred", [])
    if not isinstance(deferred, list) or any(not isinstance(s, str) for s in deferred) or len(set(deferred)) != len(deferred):
        raise ValueError("Invalid deferred area walkthroughs")
    for subject in deferred:
        check_area(subject)
    if state["revision"] < count:
        raise ValueError("Invalid optional area checkpoint revision")


def check_pass(prior):
    capture.fields(prior, ("reviewed", "complete"))
    check_topics(prior["reviewed"])
    if type(prior["complete"]) is not bool or not prior["reviewed"]:
        raise ValueError("Invalid saved walkthrough coverage")
    return len(prior["reviewed"])


def parent_product(subject):
    return subject.partition("/area/")[0]


def check_area(subject):
    capture.subject_key(subject, ("product",))
    if "/area/" not in subject:
        raise ValueError("Choose an area with a confirmed parent product")


def product_reviewed(state, subject):
    """Only a dedicated pass for this parent can qualify its areas for review."""
    if not subject:
        return False
    parent = parent_product(subject)
    if parent == state.get("product_selection"):
        return "product" in state["completed"]
    return state.get("product_history", {}).get(parent, {}).get("complete", False)


def check_topics(topics):
    if not isinstance(topics, dict) or any(
        not layout.SLUG.fullmatch(key) or outcome not in OUTCOMES for key, outcome in topics.items()
    ):
        raise ValueError("Invalid topic disposition in the walkthrough checkpoint")


def confirmed_subjects(private):
    remit, error = capture.inspect_remit(private)
    if capture.remit_status(remit) == "confirmed":
        return [item["subject"] for item in remit["responsibilities"]], error
    return [], error


def product_scope(private, state):
    """Owning an area establishes which product to review, without assigning product ownership."""
    responsibilities, error = confirmed_subjects(private)
    choices = list(dict.fromkeys(parent_product(s) for s in responsibilities if s.startswith("product/")))
    unresolved = [s for s in responsibilities if s.startswith("area/")]
    subject = state.get("product_selection")
    if "product_selection" in state:
        required = subject is not None and subject not in choices
        if subject is None and choices and "product" not in state["completed"]:
            required = not unresolved
    elif "product" in state["completed"] or state["reviewed"]["product"]:
        required = False  # Older custom frameworks could finish without an attributed subject.
    elif len(choices) == 1 and not unresolved:
        subject, required = choices[0], False
    else:
        required = True
    result = {"subject": subject, "choices": choices, "selection_required": required}
    if unresolved:
        result["unresolved_parents"] = unresolved
    if error:
        result["remit_problem"] = error
    return result


def product_subject(private):
    scope = product_scope(private, read(private)[1])
    return None if scope["selection_required"] else scope["subject"]


def walkthrough(topics, reviewed, complete):
    complete = topics is not None and complete
    next_topic = None
    if topics and not complete:
        # If an update removed the last outstanding topic, let the PM confirm closure.
        next_topic = next((topic for topic in topics if topic["id"] not in reviewed), topics[-1])
    return {"complete": complete, "next_topic": next_topic, "reviewed": reviewed}


def snapshot(frameworks, state):
    walks = {stage: walkthrough(topics, state["reviewed"][stage], stage in state["completed"])
             for stage, topics in frameworks.items()}
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
                                else "Which product should we start with?")
            result["next_action"] = ("Reuse the confirmed remit. Clarify the parent if needed. After the PM chooses, "
                                     "use onboarding select-product. An unassigned or unknown scope can stay open.")
    elif result["ready"]:
        result["stakeholder_profiles"] = onboarding_profile_step.status(private)
        parent = state.get("product_selection")
        if parent and "/area/" in parent:
            # A finished v0.13 mixed pass keeps Studio unlocked. It attests to neither
            # a dedicated parent review nor a separate review of the child.
            result["legacy_product_subject"], parent = parent, None
        result["reviewed_product_subject"] = parent
        if "area_problem" in state:
            return dict(result, area_problem=state["area_problem"], area_options=[], area_offers=[], reviewed_areas=[])
        subjects, _ = confirmed_subjects(private)
        areas = [s for s in subjects if "/area/" in s and parent_product(s) == parent]
        history = state.get("area_history", {})
        options = [s for s in areas if not history.get(s, {}).get("complete")]
        result["area_options"] = options
        result["area_offers"] = [s for s in options if s not in state.get("area_deferred", [])]
        result["reviewed_areas"] = [s for s in areas if history.get(s, {}).get("complete")]
        active = state.get("area_selection")
        if active in options:
            area_walk = walkthrough(frameworks["product"], history.get(active, {}).get("reviewed", {}), False)
            result["walkthroughs"]["area"] = area_walk
            result.update(stage="area", product_scope={"subject": active, "choices": options, "selection_required": False},
                          prompt=area_walk["next_topic"]["question"],
                          next_action="Review this topic for the chosen area. The PM can pause this optional step.")
    return result


def status(private):
    return view(private, manifest(storage.core_for(private)), read(private, for_status=True)[1])


def write(private, original, state):
    state["revision"] += 1
    storage.require_visible(private, FILE)
    storage.replace_text(private / FILE, original, json.dumps(state, indent=2) + "\n")


def check_response(payload, state):
    if type(payload["revision"]) is not int or payload["revision"] != state["revision"]:
        raise ValueError("The walkthrough revision is stale. Read onboarding status before continuing")
    if not isinstance(payload["pm_reply"], str) or not payload["pm_reply"].strip():
        raise ValueError("Wait for the PM's response to the current walkthrough step")


def switch_product(state, subject):
    previous = state.get("product_selection")
    if subject != previous:
        history = state.setdefault("product_history", {})
        reviewed = state["reviewed"]["product"]
        if reviewed:
            history[previous or "unassigned"] = {"reviewed": reviewed, "complete": "product" in state["completed"]}
        prior = history.pop(subject or "unassigned", {"reviewed": {}, "complete": False})
        state["reviewed"]["product"] = prior["reviewed"]
        state["completed"].pop("product", None)
        if prior["complete"]:
            state["completed"]["product"] = list(prior["reviewed"])
        state.pop("area_selection", None)
    state["product_selection"] = subject


def select_product(private, payload):
    """Choose the identity of a coverage pass without assigning ownership or creating a brief."""
    capture.fields(payload, ("revision", "subject", "pm_reply"))
    with storage.writer_lock(private):
        original, state = read(private)
        check_response(payload, state)
        frameworks = manifest(storage.core_for(private))
        current = snapshot(frameworks, state)
        if current["stage"] not in {"product", "ready"} or frameworks["product"] is None:
            raise ValueError("Complete company and PM setup before choosing a product walkthrough")
        subject = payload["subject"]
        scope = product_scope(private, state)
        if subject is None:
            if scope["choices"] and not scope.get("unresolved_parents"):
                raise ValueError("Choose a confirmed product responsibility or review the PM's remit")
        elif capture.subject_key(subject, ("product",)) not in scope["choices"]:
            raise ValueError("Confirm the product or parent product in the PM remit before selecting it")
        if "product_selection" in state and subject == state["product_selection"]:
            return view(private, frameworks, state)
        import company_onboarding
        if company_onboarding.active(private, kind="product"):
            raise ValueError("Finish the current product source plan before changing the walkthrough scope")
        switch_product(state, subject)
        write(private, original, state)
        return view(private, frameworks, state)


def profile_offer_allowed(payload):
    allowed = payload.get("offer_profiles", True)
    if type(allowed) is not bool:
        raise ValueError("Set offer_profiles to true or false")
    return allowed


def profiles(private, payload):
    """An explicitly requested optional pass can start even with an area still open."""
    with storage.writer_lock(private):
        result = status(private)
        if not result["ready"]:
            raise ValueError("Review the parent product before starting optional stakeholder profiles")
        choice = onboarding_profile_step.choose(private, payload)
        result["stakeholder_profiles"] = choice
        if choice["status"] == "active":
            result["next_action"] = (
                "Use the stakeholder profile guide. Ask which person the PM wants to start with. "
                "Review one sourced observation at a time; the PM can pause or finish whenever they like.")
        else:
            result["next_action"] = "Return to the PM's request."
        return result


def select_area(private, payload):
    """Opt into one owned area after parent review, or leave the optional pass for later."""
    capture.fields(payload, ("revision", "subject", "pm_reply"), ("offer_profiles",))
    allowed = profile_offer_allowed(payload)
    with storage.writer_lock(private):
        original, state = read(private)
        check_response(payload, state)
        frameworks = manifest(storage.core_for(private))
        current = view(private, frameworks, state)
        if not current["ready"]:
            raise ValueError("Complete the parent product walkthrough before reviewing an area")
        active = state.get("area_selection")
        subject = payload["subject"]
        if subject is not None:
            check_area(subject)
            if subject not in current["area_options"]:
                raise ValueError("Choose an unfinished confirmed area of the reviewed parent product")
            if subject == active:
                return current
        if subject:
            import company_onboarding
            plan = company_onboarding.read(private, "product")[1]["plan"]
            if plan and plan["subject"] != subject:
                raise ValueError("Finish the current product source plan before changing the area walkthrough")
        deferred = state.get("area_deferred", [])
        if subject is None:
            paused = [active] if active else current["area_options"]
            if not active and all(s in deferred for s in paused):
                return current
            state["area_deferred"] = list(dict.fromkeys(deferred + paused))
            state.pop("area_selection", None)
        else:
            state["area_selection"] = subject
            if subject in deferred:
                deferred.remove(subject)
        write(private, original, state)
        result = view(private, frameworks, state)
        return onboarding_profile_step.offer(private, result, allowed) if subject is None else result


def review(private, payload):
    fields = ("revision", "stage", "topic", "outcome", "pm_reply")
    if isinstance(payload, dict) and payload.get("stage") in ("product", "area"):
        fields += ("subject",)
    capture.fields(payload, fields, ("offer_profiles",))
    allowed = profile_offer_allowed(payload)
    if payload["outcome"] not in OUTCOMES:
        raise ValueError("Choose reviewed, open, or not_applicable for the current topic")
    with storage.writer_lock(private):
        original, state = read(private)
        check_response(payload, state)
        frameworks = manifest(storage.core_for(private))
        current = view(private, frameworks, state)
        stage = current["stage"]
        if stage == "ready" or not current["stage_available"] or payload["stage"] != stage:
            raise ValueError("Review the currently available walkthrough stage")
        if payload["topic"] != current["walkthroughs"][stage]["next_topic"]["id"]:
            raise ValueError("Review the current walkthrough topic with the PM before moving on")
        if stage in ("product", "area"):
            scope = current["product_scope"]
            if scope["selection_required"]:
                raise ValueError("Choose the product walkthrough scope with the PM before reviewing topics")
            if payload["subject"] != scope["subject"]:
                raise ValueError("The product walkthrough scope changed. Review the current topic with the PM")
            if stage == "product":
                state["product_selection"] = scope["subject"]
        import company_onboarding
        if company_onboarding.read(private, kind="product" if stage == "area" else stage)[1]["pending"]:
            raise ValueError(f"Accept or defer the pending {NAMES[stage]} finding before advancing the walkthrough")
        # The receipt records coverage only. Capturing a fact has its own source and wording review.
        if stage == "area":
            subject = state["area_selection"]
            history = state.setdefault("area_history", {})
            coverage = history.setdefault(subject, {"reviewed": {}, "complete": False})
            coverage["reviewed"][payload["topic"]] = payload["outcome"]
            if all(topic["id"] in coverage["reviewed"] for topic in frameworks["product"]):
                coverage["complete"] = True
                state.pop("area_selection")
        else:
            topics = state["reviewed"][stage]
            topics[payload["topic"]] = payload["outcome"]
            if all(topic["id"] in topics for topic in frameworks[stage]):
                state["completed"][stage] = list(topics)
        write(private, original, state)
        result = view(private, frameworks, state)
        if stage == "product" and result["ready"] and result["area_offers"]:
            result["next_action"] = "Offer the PM a separate, optional review of their area. They can return to their request now."
        elif stage in ("product", "area") and result["stage"] == "ready":
            onboarding_profile_step.offer(private, result, allowed)
        return result
