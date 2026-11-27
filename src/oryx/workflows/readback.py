"""Read the owning capability at each checkpoint without authoring a product decision."""

import re
from hashlib import sha256

from .method import fingerprint


ONBOARDING = {"context company capture": "company", "context pm capture": "pm",
              "context product capture": "product"}
INITIATIVE = {
    "discovery brief draft", "discovery findings review", "initiative brief draft",
    "delivery launch review", "delivery outcome review",
}
PRODUCT = re.compile(r"product/([a-z0-9]+(?:-[a-z0-9]+)*)(?:/initiative/([a-z0-9]+(?:-[a-z0-9]+)*))?")


def onboarding_capture(private, kind):
    import company_onboarding
    state = company_onboarding.status(private, kind=kind)
    # The method receives the decision and permitted next read. Pending wording stays behind its own review.
    return {"phase": state["phase"], "revision": state["revision"], "next_action": state["next_action"],
            "status_command": [kind + "-onboarding", "status"]}


def observe(root, private, command, scope):
    if command in ONBOARDING:
        import onboarding_review
        name = ONBOARDING[command]
        journey = onboarding_review.status(private)
        stage = "area" if name == "product" and journey["stage"] == "area" else name
        walk = journey["walkthroughs"][stage]
        complete = walk["complete"]
        subject = (journey.get("product_scope") or {}).get("subject")
        if name == "product" and scope.startswith("product/"):
            subject = subject or journey.get("reviewed_product_subject")
            if stage == "area" and scope != subject:
                raise ValueError("Resume this area walkthrough with a handoff scoped to its selected area")
            if stage != "area" and "/area/" in scope:
                complete = scope in journey.get("reviewed_areas", [])
        return {"owner": "onboarding", "stage": stage, "revision": journey["revision"],
                "complete": complete, "next_topic": (walk["next_topic"] or {}).get("id"),
                "capture": onboarding_capture(private, name)}
    if command not in INITIATIVE | {"portfolio roadmap plan", "initiative intake capture"}:
        return {"owner": "reviewed-handoff"}
    match = PRODUCT.fullmatch(scope)
    if not match or command in INITIATIVE and match.group(2) is None:
        return {"owner": "initiative", "status": "scope-required",
                "required_scope": "product/<product>/initiative/<initiative>" if command in INITIATIVE else "product/<product>"}
    import initiative_store
    product, slug = match.groups()
    raw, _, register = initiative_store.read(root, product)
    if raw is None:
        return {"owner": "initiative", "status": "unregistered", "product": product}
    result = {"owner": "initiative", "status": "registered", "product": product,
              "register_revision": sha256(raw.encode()).hexdigest()}
    if slug is None:
        if command == "portfolio roadmap plan":
            import initiative_views
            rows = initiative_views.roadmap([(product, register)], private=private)
            result.update(cycles=sorted(register.cycles), roadmap_revision=fingerprint(rows))
        return result
    matches = [key for key in register.items if key.rsplit("/", 1)[-1] == slug]
    if len(matches) != 1:
        return {**result, "status": "unregistered", "initiative": slug}
    item = register.items[matches[0]]
    result.update(initiative=item["id"], phase=item["phase"])
    if command == "delivery launch review":
        import initiative_work
        task_data, check_data = initiative_work.load_work(root, product, slug)
        _, raw_tasks, tasks, task_history = task_data
        target, raw_checks, checks, check_history = check_data
        readiness = initiative_work.view(initiative_work.CHECKLIST, target, raw_checks, checks, check_history, tasks, task_history)
        outstanding = readiness["outstanding"]
        result.update(tasks_revision=initiative_work.revision(raw_tasks), checklist_revision=readiness["revision"],
                      readiness_revision=readiness["readiness_revision"], readiness=readiness["launch_readiness"],
                      outstanding_count=len(outstanding), outstanding=dict(sorted(outstanding.items())[:8]),
                      full_review_command=["launch-checklist", "list", product, slug])
    return result


def permit_completion(command, to, observed):
    if to != "finish":
        return
    if observed.get("owner") == "onboarding" and not observed["complete"]:
        raise ValueError("Complete the owning onboarding walkthrough before closing this workflow")
    if command in INITIATIVE and observed.get("status") != "registered":
        raise ValueError("Choose the registered product and initiative before closing this workflow")
    if command == "portfolio roadmap plan" and observed.get("status") != "registered":
        raise ValueError("Review the registered product roadmap before closing this workflow")
