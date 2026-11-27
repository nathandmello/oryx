"""Retrieve current private work passages by record identity and product scope."""
from pathlib import PurePosixPath
import re

import context_index
import context_search
import layout
import records
import source_evidence
import storage
import upgrades
from oryx.workspace import citations, identity


# Handoffs are scoped continuations with their own reader. Instructions, notes and
# source originals do not become supporting evidence through the work registry.
WORK = layout.WORK_DOMAINS & identity.DOMAINS
MAX_PASSAGE = 2400
MAX_OUTPUT = 7400


def location(name):
    parts = layout.work_parts(name)
    if parts[:1] != ("workspace",):
        return None
    parts = parts[1:]
    if len(parts) < 2 or parts[0] not in WORK or name.endswith("/README.md"):
        return None
    return (parts[0], parts[1] if len(parts) >= 3 else None,
            parts[2] if len(parts) >= 4 and parts[0] in {"experiments", "initiatives"} else None)


def permitted_references(private):
    state = source_evidence.state(private)[1]
    denied = set(source_evidence.denied_references(private, state))
    # Grants for a review permit their named subscriber to see the passage.
    # They cannot authorize general task retrieval of that source document.
    for grant in state["grants"].values():
        name = source_evidence.local_name(grant["reference"])
        if name:
            denied.add(source_evidence.fingerprint(name))
    return denied


def names(query, name):
    return re.search(r"(?<![\w./-])" + re.escape(name) + r"(?![\w/-])", query, re.I) is not None


def sections(text):
    """A section is indivisible. Keep its qualifications with any matching statement."""
    state = records.work_state(text)[0]
    for heading, _, start, end in records.section_blocks(text):
        content = records.visible_section_markup(text[start:end]).strip()
        if heading not in {"Work state", "Sources"} and content and "{{" not in content and len(content) <= MAX_PASSAGE:
            yield heading, content, state.get("State")
    if not state and not re.search(r"(?m)^## ", text):
        body = re.sub(r"\A(?:<!--[^\n]+-->\s*)?#[^\n]*\n", "", text).strip()
        if body and len(body) <= MAX_PASSAGE:
            yield "Record", body, None


def search(private, prompt, scope, tokenize, identifiers, *, record=None):
    index_file = private / identity.INDEX
    if not index_file.exists():
        return None
    manifest = identity.load(private)
    registry = manifest["records"]
    blocked = permitted_references(private)
    originals = upgrades.source_paths(private)
    inventory = set(storage.inventory(private))
    candidates, exact, labels = [], set(), {}
    inaccessible = False
    for rid, item in registry.items():
        path = item["path"]
        place = location(path)
        if not place or not identity.eligible(path) or private / path not in inventory:
            continue
        domain, product, initiative = place
        direct = record in {rid, *item["aliases"]} or any(names(prompt, n) for n in [rid, *item["aliases"]])
        if scope.get("product") and product != scope["product"]:
            continue
        if scope.get("initiative") and initiative and scope["initiative"] != initiative:
            continue
        if scope.get("company") or scope.get("stakeholders") or scope.get("area"):
            # The purpose folder alone does not establish rights to act for these narrower scopes.
            continue
        if not direct and (not scope.get("product") or product != scope["product"] or path.endswith(".json")):
            continue
        if (any(n in originals or source_evidence.withheld(blocked, n) for n in item["aliases"])
                or (identity.transfer_status(private, rid) or {}).get("status") in {"transferred", "pending"}):
            continue
        try:
            raw = identity.read_regular(identity.local_file(private, path))
            if identity.checksum(raw) != item["revision"]:
                inaccessible |= direct
                continue
            text = raw.decode()
        except (OSError, ValueError):
            inaccessible |= direct
            continue
        info = {"id": rid, "revision": item["revision"], "record": path, "domain": domain}
        if path.endswith(".json"):
            # Event logs, drafts and checklists require different native projections.
            # Exact reference resolution supplies the citation without presenting an
            # old event or unapproved field as current PM evidence.
            passages = [("Record", "", None)]
        else:
            marker = records.MARKER.match(text)
            if not direct and (not marker or marker[1] not in records.KINDS or marker[1] in records.CONTEXT_KINDS):
                continue
            links = [m[0] for _, m in citations.visible_links(text)]
            sources, _ = records.table(records.visible_section_markup(text), "Sources", records.SOURCE_COLUMNS)
            references = [*links, *(row[1] for row in sources)]
            if any(records.uses_customization_source(path, ref) or source_evidence.withheld(blocked, ref, path)
                   for ref in references):
                continue
            passages = list(sections(text))
            if not passages and direct:
                passages = [("Record", "", None)]
        for heading, body, state in passages:
            if direct:
                exact.add(len(candidates))
            candidates.append({**info, "section": heading, "text": body, "state": state})
            labels[path, heading] = domain + " " + PurePosixPath(path).stem.replace("-", " ") + " " + heading
    if not candidates and not inaccessible:
        return None
    hits, scores, mode = context_search.rank(prompt, scope, candidates, labels, context_index.Index(), tokenize, identifiers)
    chosen = sorted(exact | hits, key=lambda i: (i not in exact, not scores[i][0], -scores[i][1], -scores[i][2], i))
    result = []
    length = 0
    verified = {}
    for i in chosen:
        row = candidates[i]
        if len(result) >= 6 or length + len(row["text"]) > MAX_OUTPUT:
            continue
        rid = row["id"]
        if rid not in verified:
            try:
                current = identity.resolve(private, rid)
                verified[rid] = (current.get("transfer_status") not in {"pending", "transferred"}
                                 and (current["path"], current["revision"]) == (row["record"], row["revision"]))
            except (OSError, ValueError):
                verified[rid] = False
        if verified[rid]:
            result.append({**row, "match": "record-identity" if i in exact else "passage"})
            length += len(row["text"])
        else:
            inaccessible = True
    if blocked != permitted_references(private):
        raise ValueError("Source permissions changed during retrieval. Review the task again.")
    if not result and not inaccessible:
        return None
    response = {"workspace_id": manifest["workspace_id"], "records": result,
                "method": "keyword-only" if mode == "lexical" else mode}
    if inaccessible:
        response["gap"] = "A requested work record changed or is unavailable. Recheck its authoritative revision."
    return response
