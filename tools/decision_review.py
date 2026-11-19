"""Read a short weekly review from existing, scoped PM evidence."""

from datetime import date, timedelta
import json

import decision_forecasts
import evidence_reviews
import initiative_events
import initiative_store
import initiative_views
import layout
import records
import task_context
import workspace


def signed_findings(private, product, register, events, today):
    """Use register order so later sign-off closes a previous evidence reminder."""
    path = layout.initiative_register(product)
    decided = set()
    newest_evidence = {}
    for event in events:
        identifier = event.get("initiative")
        if event["type"] == "decision":
            decided.add(identifier)
            newest_evidence.pop(identifier, None)
        elif event["type"] == "result" and event["conclusion"] in {"contradicted", "inconclusive"}:
            newest_evidence[identifier] = event
        elif event["type"] == "signal" and identifier in decided:
            if event["source"] in register.items[identifier].get("_signal_reviews", {}):
                continue  # The active signed evidence review owns this signal's disposition.
            previous = newest_evidence.get(identifier)
            if previous is None or previous["type"] == "signal":
                newest_evidence[identifier] = event
    for item in register.items.values():
        subject = item["id"]
        decision = item["decisions"][-1] if item["decisions"] else {}
        rationale = initiative_events.decision_rationale(decision)

        def finding(rank, kind, message, source, check):
            return rank, {"kind": kind, "product": product, "subject": subject,
                          "finding": message, "sources": [path, source]}, check

        due = initiative_views.next_review(item, decision)
        dates = [day for value in (due, rationale.get("review_on"))
                 if (day := initiative_events.iso_date(value)) and day <= today]
        if dates:
            yield finding(0, "decision-due", f"{decision['action']} is due for review on {min(dates)}.",
                          decision["source"], "Check the signed review condition against current evidence.")
        if item["phase"] == "declined" or (item["phase"] == "shipped" and due is None):
            continue
        if decision and not initiative_events.iso_date(due) and not rationale.get("review_on"):
            if initiative_events.iso_date(decision["on"]) <= today - timedelta(weeks=6):
                yield finding(3, "decision-age", f"The latest signed decision dates to {decision['on']}.",
                              decision["source"], "Check whether the original reason still applies.")
        for review in initiative_views.signal_reviews(private, item):
            if evidence_reviews.review_due(review, today):
                message = f"{review['state']}: {review['evidence']['summary']} {review['reason']}"
                check = "Compare the cited evidence with the signed claim and choose a signal disposition."
                row = {"kind": "signal-review", "product": product, "subject": subject, "finding": message,
                       "risk_id": review["id"], "state": review["state"],
                       "sources": [path, *evidence_reviews.review_sources(review)]}
                yield 1, row, check
        evidence = newest_evidence.get(subject)
        if evidence and evidence["type"] == "result":
            yield finding(1, "experiment-evidence", f"{evidence['experiment']}: {evidence['conclusion']}.",
                          evidence["source"], "Compare the experiment result with the assumption it tested.")
        condition = rationale.get("reopen_when") or (due if not initiative_events.iso_date(due) else None)
        if evidence and condition:
            candidate = finding(1, "possible-trigger", f"Check whether new evidence meets this condition: {condition}",
                                evidence["source"], "Compare the observation with the signed reopen condition.")
            candidate[1]["sources"].append(decision["source"])
            yield candidate
        elif evidence and evidence["type"] == "signal":
            yield finding(3, "later-signal", f"Evidence added after the {decision['action']} decision: {evidence['summary']}",
                          evidence["source"], "Compare the new observation with the signed decision's reason.")
        if item["phase"] in initiative_events.IN_DEFINITION:
            for identifier, hypothesis in sorted(item["hypotheses"].items()):
                tests = {key for key, test in item["experiments"].items() if test["hypothesis"] == identifier}
                results = [row for row in item["results"].values() if row["experiment"] in tests]
                if results:
                    last = max(results, key=lambda row: row["observed_on"])
                    if initiative_events.iso_date(last["observed_on"]) <= today - timedelta(days=30):
                        yield finding(3, "quiet-hypothesis", f"The last dated test result for {identifier} was {last['observed_on']}.",
                                      last["source"], "Check the latest assessment for newer evidence.")
                if identifier not in item["assessments"]:
                    yield finding(4, "unassessed-hypothesis", f"{identifier} has no recorded assessment.",
                                  hypothesis["source"], "Check whether the cited evidence supports this hypothesis.")


def context_findings(docs, product, today):
    for path, doc in docs.items():
        if product and not doc["company"] and doc["product"] != product:
            continue
        controls, _ = records.table(doc["text"], "Context controls", ("Field", "Value"))
        control = dict(controls)
        review = initiative_events.iso_date(control.get("Review by"))
        reviewed = initiative_events.iso_date(control.get("Last reviewed"))
        # Include only entries applicable to this document's scope. Repeated questions
        # in different product areas can have legitimately different answers.
        areas = set(task_context.AREA.findall(doc["text"]))
        for row in task_context.linked_entries(doc, areas, today):
            sources = [path] + [s["Source"] for s in row["sources"]]
            data = {"product": doc["product"], "subject": doc["title"], "sources": sources}
            dates = [day for source in row["sources"] if (day := initiative_events.iso_date(source["Checked on"]))]
            if reviewed:
                dates.append(reviewed)
            if row["text"].startswith("- Assumption:"):
                stale = review <= today if review else dates and max(dates) <= today - timedelta(weeks=3)
                if stale or (not dates and not review):
                    why = f"Review was due {review}." if review else (
                        f"Last documented check was {max(dates)}." if dates else "No dated check is recorded.")
                    yield 3, {**data, "kind": "stale-assumption", "finding": row["text"]}, (
                        f"{why} Confirm the assumption with its owner.")
            if row["section"] == "Decisions already closed" and row["binding"]:
                cells = row["text"].strip("|").split("|")
                when = initiative_events.iso_date(cells[2].strip().rpartition(", ")[2]) if len(cells) == 5 else None
                if when:
                    latest = max([when, *dates])
                    if (review <= today if review else latest <= today - timedelta(weeks=6)):
                        yield 3, {**data, "kind": "context-decision-review", "finding": cells[0].strip()}, (
                            "Review the sourced decision with its owner.")


def context_risk_findings(docs, product, today):
    selected = [doc for doc in docs.values() if not product or doc["company"] or doc["product"] == product]
    candidates = {risk["id"]: risk for risk in evidence_reviews.pair_candidates(
        evidence_reviews.observations(selected, today))}
    # The owning journal supersedes the same computed finding, including dismissals.
    candidates.update(evidence_reviews.stored(docs.values(), today.isoformat()))
    for risk in candidates.values():
        owned = risk["scope"]
        if product and not evidence_reviews.applies_to_task(
                risk, {"product": product, "initiative": owned["initiative"]}, {owned["area"]}, docs):
            continue
        if not evidence_reviews.review_due(risk, today):
            continue
        conflict = risk["classification"] == "potential conflict"
        question = next((claim["question"] for claim in risk["claims"] if claim.get("question")), risk["id"])
        row = {"kind": "possible-conflict" if conflict else "context-risk", "product": product or owned["product"],
               "subject": question, "finding": risk["reason"], "risk_id": risk["id"], "state": risk["state"],
               "sources": evidence_reviews.review_sources(risk)}
        yield 1, row, "Read the cited guidance and confirm which authority and evidence apply."


def review(root, product=None):
    private = workspace.repo(root, "workspace")
    workspace.settings(root)
    today = date.today()
    docs = task_context.context_documents(private, through=today)
    candidates = list(context_findings(docs, product, today))
    candidates.extend(context_risk_findings(docs, product, today))
    products = initiative_store.products(root)
    known = set(products) | {doc["product"] for doc in docs.values() if doc["product"]}
    if product and product not in known:
        raise ValueError(f"Unknown review product: {product}")
    seen = set()
    for slug in products:
        if product and product != slug:
            continue
        _, payload, register = initiative_store.read(root, slug)
        ctx = register.setup["references"]["product_id"]
        if ctx in seen:
            raise ValueError(f"Duplicate registered product context ID: {ctx}")
        seen.add(ctx)
        candidates.extend(signed_findings(private, slug, register, payload["events"], today))
    for forecast in decision_forecasts.list_records(private):
        slug = forecast["authority"]["product"]
        if (product and product != slug) or forecast["resolution"]:
            continue
        last = forecast["revisions"][-1]["on"] if forecast["revisions"] else forecast["made_on"]
        if forecast["resolve_on"] <= today.isoformat():
            rank, kind = 0, "forecast-due"
            message = f"{forecast['event']} is due for resolution on {forecast['resolve_on']}."
            check = f"Check the resolution evidence against the forecast criterion: {forecast['criterion']}"
        elif initiative_events.iso_date(last) <= today - timedelta(weeks=6):
            rank, kind = 3, "forecast-review"
            message = f"The last recorded probability for {forecast['event']} dates to {last}."
            check = "Check whether new evidence warrants a probability revision."
        else:
            continue
        candidates.append((rank, {"kind": kind, "product": slug, "subject": forecast["id"], "finding": message,
                                  "sources": [f"workspace/forecasts/{forecast['id']}.json", forecast["authority"]["record"]]},
                           check))
    candidates.sort(key=lambda item: (item[0], item[1]["product"] or "", item[1]["subject"],
                                      item[1]["kind"], item[1]["finding"], item[1]["sources"]))
    selected = []
    covered = set()
    for _, row, check in candidates:
        identity = (row["product"], row["subject"], row["kind"], row.get("risk_id"))
        if identity not in covered:
            selected.append((row, check))
            covered.add(identity)
        if len(selected) == 5:
            break
    return {"findings": [row for row, _ in selected],
            "next_check": f"{selected[0][0]['subject']}: {selected[0][1]}" if selected else None}


def add_commands(commands):
    parser = commands.add_parser("decision-review", help="Read up to five sourced findings for the weekly decision review")
    parser.add_argument("--product", type=layout.slug)
    parser.set_defaults(hub_action=run)


def run(root, args, prepare_write):
    print(json.dumps(review(root, args.product), ensure_ascii=False, indent=2))
