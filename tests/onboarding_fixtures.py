"""Exercise established-workflow tests after a real, fictional onboarding conversation."""

import json
from pathlib import Path

import onboarding_review


def define_fixture_frameworks(root):
    """Supply a framework only when a test explicitly models an unavailable stage."""
    if root.resolve() == Path(__file__).resolve().parents[1]:
        raise ValueError("Use a disposable Core checkout for fictional onboarding frameworks")
    path = root / "playbook/onboarding-frameworks.json"
    frameworks = json.loads(path.read_text())
    for stage in ("pm", "product"):
        if frameworks[stage] is None:
            frameworks[stage] = [{"id": "fixture-topic", "question": f"What about the fictional {stage} topic?"}]
    path.write_text(json.dumps(frameworks, indent=2) + "\n")
    return frameworks


def review_current_topic(private, *, offer_profiles=True):
    state = onboarding_review.status(private)
    stage = state["stage"]
    identifier = {}
    if stage in {"product", "area"}:
        scope = state["product_scope"]
        if scope["selection_required"]:
            subject = scope["choices"][0] if scope["choices"] else None
            state = onboarding_review.select_product(private, {
                "revision": state["revision"], "subject": subject,
                "pm_reply": "Let's start with this responsibility." if subject else "My assignment is still open.",
            })
        identifier = {"subject": state["product_scope"]["subject"]}
    topic = state["walkthroughs"][stage]["next_topic"]
    onboarding_review.review(private, {
        "revision": state["revision"], "stage": stage, "topic": topic["id"],
        "outcome": "open", "pm_reply": "I don't know yet. Let's leave this open.", **identifier,
        **({"offer_profiles": False} if not offer_profiles and stage in {"product", "area"} else {}),
    })


def reviewed_studio(root, private):
    """Complete the actual walkthrough, leaving all facts open for the test's own data."""
    frameworks = define_fixture_frameworks(root)
    for _ in range(sum(len(topics) for topics in frameworks.values())):
        if onboarding_review.status(private)["ready"]:
            return
        review_current_topic(private, offer_profiles=False)
    if not onboarding_review.status(private)["ready"]:
        raise AssertionError("Reviewing every registered topic did not complete onboarding")


def reviewed_setup(test):
    """Create an isolated Studio for a test of an activity that requires onboarding."""
    import test_pm
    test_pm.HubTests.setUp(test)
    reviewed_studio(test.root, test.work)
