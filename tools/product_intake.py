"""Constrain a product capture round to the PM's confirmed remit and approved briefs."""

from datetime import date
import json
from pathlib import Path
import re

import context_capture as capture
import context_embeddings
import layout
import onboarding_review
import records
import storage


TOPIC_SEARCH = {
    "purpose": "Product purpose, business role, value proposition and existing direction",
    "customers": "Customers, users, buyers, needs, problems and jobs they want to accomplish",
    "experience": "User experience, customer journey, product capabilities, friction and workflows",
    "business-value": "Business model, distribution, pricing, costs, revenue and intended business contribution",
    "performance": "Results, adoption, retention, reliability, measures, baselines and customer outcomes",
    "environment": "Operating environment, dependencies, constraints, competitors, teams and decision roles",
}

# A similar heading, a citation title or an attached question cannot establish topic relevance.
# Look for the kind of claim the walkthrough asks for in the original statement itself.
TOPIC_CLAIM = {
    "purpose": r"(?:purpose|mission|vision) (?:is|was)|exists? to|built (?:for|to)|designed (?:for|to)|"
               r"enables?|serves?|used (?:for|to)|replaces?|provides?|unifies|centrali[sz]es|launched for",
    "customers": r"(?:customers?|users?|buyers?|subscribers?|purchasers?|clients?|patients?) "
                 r"(?:(?:primarily|mainly|typically) )?(?:are|is|include|comprise|need|want|use|work|buy|cannot)|"
                 r"(?:use|uses|need|needs|struggle|struggles|try|tries) .{1,50}? to|rely on|relies on|"
                 r"struggle to|need to|target audience|cannot|can’t|can't",
    "experience": r"(?:workflow|journey|interface|integration) (?:starts?|includes?|requires?|enables?|ends?)|"
                  r"clicks?|exports?|uploads?|logs? in|signs? in|signs? up|checks? out|drags? .{1,50} (?:into|onto)|"
                  r"submits?|hard to use|difficult to use|unable to",
    "business-value": r"pric(?:e|ed|ing)|revenues?|margin|costs?|retention|acquisition|distribution|subscriptions?|"
                      r"contracts?|moneti[sz]\w+|paid|pays?|sell|sells|sold|invoices?|channels?|funded|savings",
    "performance": r"baseline (?:is|was|of)|median|percentile|rose|fell|reached|decreased|increased|"
                   r"improved|declined|doubled|measured|stayed flat|remained stable",
    "environment": r"depend\w*|constrain\w*|compet\w*|alternatives?|positioning|regulat\w*|contract\w*|"
                   r"approv\w*|decides?|signs? off|own(?:s|er|ership)?|accountab\w*|responsib\w*|"
                   r"operat\w*|architect\w*|incidents?|handoffs?|stand-?up|deploy\w*",
}
PORTFOLIO_SCOPE = re.compile(r"\b(?:company[- ]wide|portfolio[- ]wide|(?:across|for) (?:all|every) "
                             r"(?:our |of our )?(?:products?|offerings?))\b", re.I)


def supports_topic(topic, row, claim, query):
    claim = " ".join(PORTFOLIO_SCOPE.sub("", claim).split())
    if topic == "performance":
        if row["text"].startswith(("- Assumption:", "- Interpretation:", "- Unknown:", "- Rule:")):
            return False
        if re.search(r"\b(?:goal|aim|target|intend|plan|expect)\w* to\b|\b(?:target|goal) (?:is|of)\b|"
                     r"\b(?:forecast|predict|project)(?:s|ed)?\b", claim, re.I):
            return False
        if row["text"].startswith("- Reported metric:"):
            return True
    pattern = TOPIC_CLAIM.get(topic)
    if not pattern or re.search(r"\b(?:" + pattern + r")\b", claim, re.I):
        return True
    # Keep strong paraphrases even when the PM uses different language. Check only the ranked finalists.
    try:
        model = context_embeddings.encoder()
        return context_embeddings.similarity(model.encode(query), model.encode(claim)) >= 0.40
    except (OSError, ValueError):
        return False


def scope(private):
    return onboarding_review.product_scope(private, onboarding_review.read(private)[1])


def places(plan):
    """Validate the saved plan's shape without depending on a remit that may have changed."""
    subject = capture.subject_key(plan["subject"], ("product",)).split("/")
    product = subject[1]
    area = subject[3] if len(subject) == 4 else None
    parent = layout.product(product)
    destinations = plan["destinations"]
    if (not isinstance(destinations, list) or not destinations or not all(isinstance(p, str) for p in destinations)
            or len(set(destinations)) != len(destinations)):
        raise ValueError("Name each approved product or area brief once")
    child = None
    for path in destinations:
        if path == parent:
            continue
        parts = Path(path).parts
        if not area or len(parts) != 6 or path != layout.area(product, area, group=parts[3]) or child:
            raise ValueError("Choose the confirmed product overview or its one approved area overview")
        child = path
    titles = plan.get("titles", {})
    if not isinstance(titles, dict) or not titles.keys() <= set(destinations):
        raise ValueError("Only name briefs included in the proposed destinations")
    for title in titles.values():
        capture.line(title, "Brief title")
    return product, area, parent, child


def check_plan(private, plan):
    product, area, parent, child = places(plan)
    current = scope(private)
    if plan["subject"] not in current["choices"]:
        raise ValueError("Confirm this product or qualified area in the PM remit before planning its capture")
    stage = onboarding_review.status(private)["stage"]
    if stage != "ready" and (stage != "product" or current["selection_required"] or plan["subject"] != current["subject"]):
        raise ValueError("Use the subject confirmed for the current product walkthrough")
    for path in plan["destinations"]:
        capture.record_path(private, path)
    if child:
        group = Path(child).parts[3]
        if child != records.area_brief_path(product, area, private=private, group=group):
            raise ValueError("Review the existing home for this product area with the PM")
        parent_file = capture.record_path(private, parent)
        if parent_file.is_file():
            with parent_file.open("rb") as stream:
                if stream.readline(128).rstrip() != b"<!-- pm: product-context -->":
                    raise ValueError("Review the existing parent file before using it as a product brief")
        elif parent not in plan["destinations"]:
            raise ValueError("Include the missing parent product brief in the plan before creating the area brief")
    return product, area, parent, child


def finding(private, plan, entry):
    """Bind an excerpt to its approved scope and the homes the record router may select."""
    product, area, parent, child = check_plan(private, plan)
    if entry.get("product") != product or ("product_area" in entry and (not area or entry["product_area"] != area)):
        raise ValueError("Review a finding about the product or area in the approved plan")
    destination = child if "product_area" in entry else parent
    if not destination or destination not in plan["destinations"]:
        raise ValueError("Get agreement on this finding's destination before gathering or filing it")
    homes = [destination]
    if destination == child:
        if "shared_area" in entry:
            raise ValueError("Review the shared-area relationship in its product-level brief")
        group = Path(child).parts[3]
        if "area_group" in entry and entry["area_group"] != group:
            raise ValueError("The area grouping must match the approved directory")
        entry = dict(entry, area_group=group)
        # The record router can locate an exact scoped question (or a replay
        # of its saved answer) in the parent of a legacy inline area.
        if "answers" in entry and parent in plan["destinations"]:
            homes.append(parent)
    elif "area_group" in entry:
        raise ValueError("An area grouping belongs only to a finding about the area")
    if "record" in entry and (not isinstance(entry["record"], dict) or entry["record"].get("path") not in homes):
        raise ValueError("Use the finding's approved product or area overview")
    return entry, homes


def scaffold(root, private, parent, lint, title=None):
    """Only the accepted plan can create this empty structural parent. Leave personal work untouched."""
    path = capture.record_path(private, parent)
    if path.is_file():
        return None
    storage.require_visible(private, parent)
    product = Path(parent).parts[2]
    text = records.draft_text(root, "product-context", path, title=title or product.replace("-", " "))
    errors = lint(root, path, text, destination_only=True)
    if errors:
        raise ValueError("Review the proposed parent product brief: " + ". ".join(errors))
    storage.replace_text(path, None, text)
    return text


def recall(private):
    """Return one complete passage for the current topic from specifically authorised local briefs."""
    import company_onboarding
    import context_index
    import context_search
    import evidence_reviews
    import task_context
    import upgrades

    journey = onboarding_review.status(private)
    result = {"status": "no_active_topic", "subject": None, "topic": None, "evidence": None}
    if journey["stage"] != "product" or not journey["stage_available"]:
        return result
    current = journey["product_scope"]
    topic = journey["walkthroughs"]["product"]["next_topic"]
    result.update(subject=current["subject"], topic=topic["id"])
    if current["selection_required"]:
        return dict(result, status="select_scope")
    if not current["subject"]:
        return dict(result, status="open")
    original, state = company_onboarding.read(private, "product")
    plan = state["plan"]
    if not state["approved"] or not plan or plan["subject"] != current["subject"]:
        return dict(result, status="plan_required")
    if state["pending"]:
        return dict(result, status="pending_review")

    product, area, parent, child = places(plan)
    sources = set(plan["sources"])
    homes = {layout.COMPANY: "company", parent: f"product/{product}"}
    if topic["id"] == "environment":
        homes[layout.STAKEHOLDERS] = "stakeholders"
    if area:
        # Respect an authorised existing home even when the parent is the only write destination.
        named = [name for name in sources if (identity := layout.area_identity(name))
                 and identity[:2] == (product, area) and name == layout.area(*identity)]
        if len(named) > 1 or (child and named and named[0] != child):
            raise ValueError("Confirm one existing home for this area before retrieving evidence")
        if named:
            homes[named[0]] = plan["subject"]

    rows, labels, row_scopes, approved_docs = [], {}, [], []
    today = date.today()
    originals = upgrades.source_paths(private)
    for name, home in homes.items():
        if name not in sources or name in originals:
            continue
        path = capture.record_path(private, name)
        if not path.is_file():
            continue
        storage.require_visible(private, name)
        if area and home == plan["subject"] and records.area_brief_path(product, area, private=private) != name:
            raise ValueError("Confirm the current home for the approved area before retrieving evidence")
        doc = task_context.read_document(Path(name), path, through=today)
        if not doc or doc["kind"] != layout.brief_kind(name):
            continue
        if doc["area"] and doc["parent"] != parent:
            raise ValueError("Review the existing area brief’s parent with the PM before using it")
        approved_docs.append(doc)
        scoped_areas = {area} if area and doc["product"] else set()
        for row in task_context.linked_entries(doc, scoped_areas, today):
            if (not row["sources"] or any(source["coverage"] == "unavailable" or source["Checked on"] > today.isoformat()
                                          for source in row["sources"])
                    or len(json.dumps(row, ensure_ascii=False)) > 2400):
                continue  # Leave an oversized entry available in its source with its qualifications intact.
            claim = context_search.passage(row).splitlines()[0]
            if home == "stakeholders" and not all(task_context.mentions(claim, key) for key in (product, area) if key):
                continue
            if home == "company" and not (task_context.mentions(claim, product) or PORTFOLIO_SCOPE.search(claim)):
                continue
            rows.append(row)
            labels[name, row["section"]] = row["section"]
            row_scopes.append(plan["subject"] if row.get("product_area") else home)
    query = TOPIC_SEARCH.get(topic["id"], topic["question"])
    hits, scores, _ = context_search.rank(query, {"product": product, "area": area}, rows, labels,
                                          context_index.Index(), task_context.tokens, task_context.IDENTIFIER)
    hits = {i for i in hits if supports_topic(topic["id"], rows[i], context_search.passage(rows[i]).splitlines()[0], query)}
    if not hits:
        return dict(result, status="open")
    best = max(hits, key=lambda i: (*scores[i], row_scopes[i] == plan["subject"], -i))
    candidate = rows[best]
    reviews = evidence_reviews.stored(approved_docs, today.isoformat())
    if review_ids := list(task_context.shared_row_reviews(candidate, reviews)):
        candidate["risk_reviews"] = review_ids
    if original != company_onboarding.read(private, "product")[0] or journey != onboarding_review.status(private):
        raise ValueError("The product walkthrough or source plan changed. Check the current topic again")
    return dict(result, status="candidate", evidence=dict(candidate, scope=row_scopes[best],
                                                           evidence_status=task_context.evidence_status(candidate)))
