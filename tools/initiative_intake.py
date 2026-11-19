"""Prepare a bounded human comparison before assigning a second initiative ID."""

import re

MAX_CANDIDATES = 5


def terms(value):
    return set(re.findall(r"[^\W_]+", value.casefold())) - {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "of", "on", "the", "to", "with",
    }


def candidates(items, capture):
    """Rank the whole product history for display. Only the PM can decide distinctness."""
    proposed_terms = terms(capture["title"] + " " + capture["summary"])
    proposed_areas = set(capture.get("areas", []))
    ranked = []
    for order, item in enumerate(items.values()):
        description = item["description"]
        first = item["signals"][0]
        problem = description["problem"] if description else first["summary"]
        evidence = [item["title"], *(signal["summary"] for signal in item["signals"])]
        if description:
            evidence.extend((description["problem"], description["audience"], description["outcome"]))
        shared = proposed_terms & terms(" ".join(evidence))
        priority = (len(shared), len(proposed_areas.intersection(item["areas"])), order)
        row = {"id": item["id"], "title": item["title"], "phase": item["phase"], "problem": problem,
               "source": description["source"] if description else first["source"]}
        ranked.append((priority, row))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in ranked[:MAX_CANDIDATES]]


def validate_review(items, review):
    if not isinstance(review, dict) or set(review) != {"considered", "candidates"}:
        raise ValueError("Expected a signed intake comparison")
    ids = review["candidates"]
    if (type(review["considered"]) is not int or review["considered"] != len(items)
            or not isinstance(ids, list) or not items or len(ids) != min(len(items), MAX_CANDIDATES)
            or not all(isinstance(key, str) and key in items for key in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("The intake comparison must reference existing initiatives at the time of capture")


def confirm_distinct(reviewed, confirmations):
    required = {event["initiative"] for event in reviewed if event["type"] == "capture" and "intake_review" in event}
    if set(confirmations) != required or len(confirmations) != len(required):
        expected = ", ".join(sorted(required)) or "(none)"
        raise ValueError("Review intake_reviews. Use signal for the same problem. "
                         f"The PM must supply --confirm-distinct once for each distinct capture. Expected: {expected}")
