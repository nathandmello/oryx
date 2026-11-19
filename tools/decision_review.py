"""Read a short weekly review from existing, scoped PM evidence."""

from datetime import date, timedelta
import json

import decision_forecasts
import initiative_events
import initiative_store
import initiative_views
import layout
import records
import task_context
import workspace


def signed_findings(product, register, events, today):
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
    decisions = []
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
                decisions.append(row)
                cells = row["text"].strip("|").split("|")
                when = initiative_events.iso_date(cells[2].strip().rpartition(", ")[2]) if len(cells) == 5 else None
                if when:
                    latest = max([when, *dates])
                    if (review <= today if review else latest <= today - timedelta(weeks=6)):
                        yield 3, {**data, "kind": "context-decision-review", "finding": cells[0].strip()}, (
                            "Review the sourced decision with its owner.")

    for conflict in task_context.decision_conflicts(decisions, docs):
        left, right = conflict["entries"]
        sources = []
        for row in (left, right):
            sources.extend([row["record"], *(s["Source"] for s in row["sources"])])
        title = conflict["question"]
        product_scope = docs[left["record"]]["product"] or docs[right["record"]]["product"]
        yield 1, {"kind": "possible-conflict", "product": product_scope, "subject": title,
                  "finding": f"Two active decisions give different next steps for {conflict['scope']}.",
                  "sources": list(dict.fromkeys(sources))}, (
                      "Read both active decisions and confirm which applies before reopening either.")


def review(root, product=None):
    private = workspace.repo(root, "workspace")
    workspace.settings(root)
    today = date.today()
    docs = task_context.context_documents(private)
    candidates = list(context_findings(docs, product, today))
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
        candidates.extend(signed_findings(slug, register, payload["events"], today))
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
        identity = (row["product"], row["subject"], row["kind"])
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
