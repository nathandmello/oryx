"""Review-bound effects on the customer peer's Git repositories and local pages."""
from datetime import datetime, timezone
import json
from .render import MIME, rendition

from oryx.governance.common import SHA, canonical, digest, identifier, record_id, shape
from oryx.governance.peer import storage_path


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_reference(ref):
    shape(ref, ("scope", "kind", "id", "revision"))
    identifier(ref["scope"])
    storage_path(ref["kind"], ref["id"])
    if not isinstance(ref["revision"], str) or not SHA.fullmatch(ref["revision"]):
        raise ValueError("Reference requires a pinned record revision")


def check_references(ctx, references, audience):
    if not isinstance(references, list) or len(references) > 64:
        raise ValueError("List the material source references")
    for ref in references:
        validate_reference(ref)
        row = ctx.record(ref["scope"], ref["kind"], ref["id"])
        if ref["revision"] != row["revision"]:
            raise ValueError("Referenced record changed; repeat disclosure review")
        if not set(audience) <= set(ctx.audience(ref["scope"])).intersection(row["record"]["reviewed_audience"]):
            raise PermissionError("The destination audience exceeds a referenced source audience")


def days(value):
    if type(value) is not int or not 1 <= value <= 366:
        raise ValueError("Use a positive reporting window of at most 366 days")


def document(ctx, scope, kind, name, value):
    if kind == "record":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Supply the reviewed document text")
    elif kind == "metric":
        shape(value, ("window_days", "unit"))
        days(value["window_days"])
        if value["unit"] != "events":
            raise ValueError("Use the supported structured event unit")
    elif kind == "policy":
        shape(value, ("exceptions",))
        ctx.record(scope, "metric", name)
        if not isinstance(value["exceptions"], dict):
            raise ValueError("List exceptions owned by this scope")
        for child, window in value["exceptions"].items():
            if child not in ctx.config["scopes"] or scope not in ctx.lineage(child)[:-1]:
                raise ValueError("Exceptions must name a registered narrower scope")
            days(window)
    elif kind == "report":
        shape(value, ("operation", "metric", "scope", "dataset", "window_days", "dependency_revision"))
        if value["operation"] != "count-events" or value["dataset"] not in ctx.config["datasets"]:
            raise ValueError("Unverifiable report definition or source")
        metric = ctx.metric(value["scope"], value["metric"])
        if value["window_days"] != metric["window_days"] or value["dependency_revision"] != metric["revision"]:
            raise ValueError("Stale report definition; submit a correction to the report owner")
        if not set(ctx.audience(scope)) <= set(ctx.audience(value["scope"])):
            raise PermissionError("Report logic refers to a narrower scope")
    else:
        raise ValueError("Unsupported governed record")


def validate_intent(ctx, intent, check_base=True):
    shape(intent, ("operation", "scope", "base", "audience", "kind", "id", "content", "references", "last_updated"),
          ("source", "page", "expected_page", "live", "format", "recipients"))
    scope, operation = intent["scope"], intent["operation"]
    if operation not in {"propose", "transfer", "publish", "send"}:
        raise ValueError("Unknown disclosure operation")
    ctx.require(scope, "read", "publish" if operation in {"publish", "send"} else "propose")
    info = ctx.scope(scope)
    if check_base and info["revision"] != intent["base"]:
        raise ValueError("Destination revision changed; review again")
    if intent["audience"] != info["audience"]:
        raise ValueError("Destination audience changed; review again")
    try:
        when = datetime.fromisoformat(intent["last_updated"].replace("Z", "+00:00"))
        if when.utcoffset() is None:
            raise ValueError()
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Supply the source's last-updated time with timezone") from exc
    if not isinstance(intent["references"], list):
        raise ValueError("Declared references must be a list")
    recipients=info["audience"]
    if operation=="send":
        recipients=intent.get("recipients",recipients)
        if (not isinstance(recipients,list) or not recipients or recipients!=sorted(set(recipients))
                or not set(recipients)<=set(info["audience"]) or intent.get("format","md") not in MIME):
            raise ValueError("Select eligible individual recipients and an available rendition")
    elif "recipients" in intent or "format" in intent:
        raise ValueError("Recipient and rendition selection require a one-off send")
    check_references(ctx, intent["references"], recipients)
    kind, name = intent["kind"], record_id(intent["id"])
    document(ctx, scope, kind, name, intent["content"])
    private_source=isinstance(intent.get("source"),dict) and "workspace_id" in intent["source"]
    if operation in {"publish","send"} and private_source:
        if ctx.db.execute("SELECT 1 FROM owners WHERE id=?",(name,)).fetchone():
            raise ValueError("Use the current shared record owner")
        if intent.get("live"):
            raise ValueError("Unattended live refresh requires access to the shared authoritative source")
    if operation in {"publish", "send"} and not private_source:
        if kind != "record":
            raise ValueError("Publish an official document")
        src = intent.get("source")
        validate_reference(src)
        check_references(ctx, [src], recipients)
        owner = ctx.record(src["scope"], src["kind"], src["id"])["record"]
        if (src["id"] != name or src["kind"] != kind or owner["content"] != intent["content"]
                or owner["last_updated"] != intent["last_updated"] or owner["references"] != intent["references"]):
            raise ValueError("Rendition differs from authoritative record or its disclosure restrictions")
    if operation == "publish":
        identifier(intent.get("page"))
        if type(intent.get("expected_page")) is not int or intent["expected_page"] < 0 or type(intent.get("live")) is not bool:
            raise ValueError("Review exact page revision and live setting")
    elif any(k in intent for k in ("page", "expected_page", "live")):
        raise ValueError("Page controls apply only to a publication")
    if operation == "transfer" or private_source:
        src = shape(intent.get("source"), ("workspace_id", "id", "revision"))
        if kind != "record" or src["id"] != name or not SHA.fullmatch(src["revision"]) or digest(intent["content"].encode()) != src["revision"]:
            raise ValueError("Transfer must preserve exact identified private record bytes")
        import uuid
        if str(uuid.UUID(src["workspace_id"])) != src["workspace_id"]:
            raise ValueError("Invalid source Workspace identity")
    if operation == "propose" and "source" in intent:
        raise ValueError("Use transfer to declare a private source of ownership")


def approval(ctx, key, scope):
    ctx.human()
    ctx.require(scope, "read")
    if not isinstance(key, str) or not SHA.fullmatch(key):
        raise ValueError("Invalid reviewed digest")
    ctx.db.execute("INSERT OR IGNORE INTO approvals VALUES(?,?,?)", (key, ctx.actor, scope))
    return {"scope": scope, "commitment": key, "actor": ctx.actor}


def commit_id(ctx, commitment):
    return digest(canonical([ctx.config["organization"], ctx.actor, commitment]))


def approved_digest(ctx, key, scope):
    if not isinstance(key,str) or not SHA.fullmatch(key):
        raise ValueError("Invalid disclosure commitment")
    grant = ctx.db.execute("SELECT 1 FROM approvals WHERE digest=? AND actor=? AND scope=?", (key, ctx.actor, scope)).fetchone()
    if not grant:
        raise PermissionError("No exact disclosure authorization from the acting PM")
    return commit_id(ctx, key)


def checked_approval(ctx, intent):
    return approved_digest(ctx,digest(canonical(intent)),intent["scope"])


def official_body(intent):
    return {**{k: intent[k] for k in ("id", "kind", "content", "references", "last_updated")}, "reviewed_audience":intent["audience"]}


def row(ctx, proposal):
    if not isinstance(proposal, str) or not SHA.fullmatch(proposal):
        raise ValueError("Invalid proposal ID")
    result = ctx.db.execute("SELECT * FROM proposals WHERE id=?", (proposal,)).fetchone()
    if result is None:
        raise ValueError("Unknown customer proposal")
    ctx.require(result["scope"], "read")
    return result


def proposal_info(ctx, result):
    if result["status"]=="prepared":
        actual=ctx.git(result["scope"]).ref("refs/heads/proposals/"+result["id"])
        if actual==result["candidate"]:
            ctx.receipt(result["id"]+"/push","push",result["scope"],actual)
            ctx.db.execute("UPDATE proposals SET status='open' WHERE id=?",(result["id"],))
            result=row(ctx,result["id"])
        elif actual is not None:
            raise ValueError("Destination proposal ref differs from its prepared candidate")
    if result["status"] == "merging":
        reconcile_merge(ctx, result)
        result = row(ctx, result["id"])
    return {key: result[key] for key in ("id", "scope", "actor", "base", "candidate", "status", "reviewer")}


def owner_check(ctx, intent):
    if intent["kind"] != "record":
        return
    existing = ctx.db.execute("SELECT scope FROM owners WHERE id=?", (intent["id"],)).fetchone()
    if existing and (existing[0] != intent["scope"] or intent["operation"] == "transfer"):
        raise ValueError("This document already has an authoritative shared home")


def propose(ctx, intent):
    if intent["operation"] not in {"propose", "transfer"}:
        raise ValueError("Expected a Git proposal or transfer")
    key = checked_approval(ctx, intent)
    if ctx.db.execute("SELECT 1 FROM receipts WHERE id=?", (key+"/cancel",)).fetchone():
        raise ValueError("This transfer was closed before publication; review a new proposal")
    old = ctx.db.execute("SELECT * FROM proposals WHERE id=?", (key,)).fetchone()
    if old and old["status"] != "prepared":
        ctx.require(old["scope"], "read")
        return proposal_info(ctx, old)
    validate_intent(ctx, intent)
    owner_check(ctx, intent)
    scope = intent["scope"]
    git = ctx.git(scope)
    if old:
        candidate = old["candidate"]
    else:
        candidate = git.stage(intent["base"], storage_path(intent["kind"], intent["id"]), official_body(intent), key)
        ctx.db.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?,?,NULL,NULL)",
                       (key, scope, ctx.actor, intent["base"], candidate, canonical(intent).decode(), "prepared"))
    # Persist the candidate's Git identity before publishing its first reader-visible branch.
    refname = "refs/heads/proposals/" + key
    previous = git.ref(refname)
    if not previous:
        git.git("update-ref", refname, candidate, "0" * len(candidate))
    elif previous != candidate:
        raise ValueError("Uncertain proposal ref; reconcile with the destination owner")
    ctx.db.execute("UPDATE proposals SET status='open' WHERE id=?", (key,))
    ctx.receipt(key + "/push", "push", scope, candidate)
    return proposal_info(ctx, row(ctx, key))


def review(ctx, key, candidate, approve):
    ctx.human()
    rec = row(ctx, key)
    ctx.require(rec["scope"], "review")
    if type(approve) is not bool or rec["actor"] == ctx.actor or rec["status"] != "open" or rec["candidate"] != candidate:
        raise PermissionError("An independent reviewer must decide the exact open proposal")
    intent = json.loads(rec["body"])
    if intent["kind"] == "policy":
        ctx.require(rec["scope"], "policy")
    ctx.require(rec["scope"], "propose", actor=rec["actor"])
    # Validate as the author, then restore the authenticated review principal.
    original = ctx.actor
    try:
        ctx.actor = rec["actor"]
        validate_intent(ctx, intent)
    finally:
        ctx.actor = original
    if ctx.git(rec["scope"]).ref("refs/heads/proposals/" + key) != candidate:
        raise ValueError("Candidate changed at the destination")
    status = "approved" if approve else "closed"
    ctx.db.execute("UPDATE proposals SET status=?,reviewer=?,reviewed_revision=? WHERE id=?", (status, ctx.actor, candidate, key))
    ctx.receipt(key + "/review", "review", rec["scope"], candidate)
    return proposal_info(ctx, row(ctx, key))


def reconcile_merge(ctx, rec):
    git = ctx.git(rec["scope"])
    if not git.contains(rec["candidate"], git.ref()):
        return
    intent = json.loads(rec["body"])
    if intent["kind"] == "record":
        ctx.db.execute("INSERT INTO owners VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision WHERE scope=excluded.scope",
                       (intent["id"], rec["scope"], rec["candidate"]))
    ctx.receipt(rec["id"] + "/merge", "merge", rec["scope"], rec["candidate"])
    ctx.db.execute("UPDATE proposals SET status='merged' WHERE id=?", (rec["id"],))


def merge(ctx, key, candidate):
    ctx.human()
    rec = row(ctx, key)
    scope = rec["scope"]
    ctx.require(scope, "merge")
    if rec["status"] == "merging":
        reconcile_merge(ctx, rec)
        rec = row(ctx, key)
    if rec["status"] == "merged" and candidate == rec["candidate"]:
        return proposal_info(ctx, rec)
    if (rec["status"] not in {"approved", "merging"} or rec["candidate"] != candidate
            or rec["reviewed_revision"] != candidate or rec["reviewer"] == rec["actor"]):
        raise ValueError("Missing current independent review on this candidate")
    ctx.require(scope, "read", "review", actor=rec["reviewer"])
    ctx.require(scope, "read", "propose", actor=rec["actor"])
    intent = json.loads(rec["body"])
    if intent["kind"] == "policy":
        ctx.require(scope, "policy")
        ctx.require(scope, "policy", actor=rec["reviewer"])
    original = ctx.actor
    try:
        ctx.actor = rec["actor"]
        validate_intent(ctx, intent)
        owner_check(ctx, intent)
    finally:
        ctx.actor = original
    git = ctx.git(scope)
    if git.ref("refs/heads/proposals/" + key) != candidate:
        raise ValueError("Candidate differs from verified destination review")
    ctx.db.execute("UPDATE proposals SET status='merging' WHERE id=?", (key,))
    git.git("update-ref", "refs/heads/main", candidate, rec["base"])
    reconcile_merge(ctx, row(ctx, key))
    return proposal_info(ctx, row(ctx, key))


def bind_distribution(ctx, identity, source, references):
    ctx.db.execute("CREATE TABLE IF NOT EXISTS distribution_sources(id TEXT PRIMARY KEY, binding TEXT)")
    ctx.db.execute("INSERT OR REPLACE INTO distribution_sources VALUES(?,?)",
                   (identity,canonical({"source":source,"references":references}).decode()))


def check_distribution(ctx, identity):
    if not ctx.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='distribution_sources'").fetchone():
        raise PermissionError("Distribution has no verified source binding")
    row=ctx.db.execute("SELECT binding FROM distribution_sources WHERE id=?",(identity,)).fetchone()
    if not row:
        raise PermissionError("Distribution source binding unavailable")
    binding=json.loads(row["binding"])
    check_references(ctx,binding["references"],[ctx.actor])
    src=binding["source"]
    if "scope" in src:
        ctx.record(src["scope"],src["kind"],src["id"])


def dispatch_direct(ctx, intent):
    if intent["operation"] not in {"publish", "send"}:
        raise ValueError("Expected an explicit publication or delivery")
    key = checked_approval(ctx, intent)
    scope = intent["scope"]
    ctx.require(scope, "read", "publish")
    receipt = ctx.db.execute("SELECT * FROM receipts WHERE id=?", (key,)).fetchone()
    if receipt:
        return dict(receipt)
    validate_intent(ctx, intent)
    # Page edit/delivery and its durable receipt belong to one local provider transaction.
    ctx.db.execute("BEGIN IMMEDIATE")
    try:
        if intent["operation"] == "send":
            fmt=intent.get("format","md")
            artifact=rendition(fmt,intent["content"],intent["last_updated"])
            if len(artifact)>640_000:
                raise ValueError("Rendition exceeds the local delivery limit")
            ctx.db.execute("CREATE TABLE IF NOT EXISTS renditions(id TEXT PRIMARY KEY,format TEXT,data BLOB)")
            ctx.db.execute("INSERT INTO renditions VALUES(?,?,?)",(key,fmt,artifact))
            ctx.db.execute("INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?)", (key, scope, ctx.actor, intent["source"]["revision"], intent["content"], now(), canonical(intent.get("recipients",intent["audience"])).decode(), intent["last_updated"]))
            bind_distribution(ctx,key,intent["source"],intent["references"])
            revision = intent["source"]["revision"]
        else:
            page_id = scope + "/" + intent["page"]
            old = ctx.db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
            prior = old["page_rev"] if old else 0
            if prior != intent["expected_page"]:
                raise ValueError("Destination page changed; inspect both versions")
            if old and (old["actor"] != ctx.actor or old["record"] != intent["id"]):
                raise PermissionError("Existing page has another publication binding")
            bind_distribution(ctx,page_id,intent["source"],intent["references"])
            revision = str(prior + 1)
            ctx.db.execute("INSERT OR REPLACE INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (page_id, scope, intent["id"], intent["source"]["revision"], prior + 1, intent["content"],
                            now(), int(intent["live"]), ctx.actor, canonical(intent["audience"]).decode(), prior + 1, intent["last_updated"]))
        ctx.receipt(key, intent["operation"], scope, revision)
        ctx.db.execute("COMMIT")
    except BaseException:
        ctx.db.execute("ROLLBACK")
        raise
    return dict(ctx.db.execute("SELECT * FROM receipts WHERE id=?", (key,)).fetchone())


def read_page(ctx, scope, page):
    ctx.require(scope, "read")
    value = ctx.db.execute("SELECT * FROM pages WHERE id=?", (scope + "/" + identifier(page),)).fetchone()
    if not value or ctx.actor not in json.loads(value["audience"]):
        raise PermissionError("Page or publication visibility unavailable")
    check_distribution(ctx,value["id"])
    owner = ctx.db.execute("SELECT scope FROM owners WHERE id=?", (value["record"],)).fetchone()
    outstanding = None
    if owner and "read" in ctx.rights(owner["scope"]):
        latest = ctx.record(owner["scope"], "record", value["record"])
        outstanding = latest["revision"] != value["source_rev"]
    return {"id": page, "scope": scope, "content": value["body"], "page_revision": value["page_rev"],
            "source_revision": value["source_rev"], "last_publication": value["updated"], "live": bool(value["live"]),
            "outstanding": outstanding, "source_last_updated": value["source_updated"], "destination_edited": value["delivered_rev"] != value["page_rev"]}

def refresh_pages(ctx, scope):
    """Catch up opted-in publications only while the connected publisher retains permission."""
    result = []
    for page in ctx.db.execute("SELECT * FROM pages WHERE scope=? AND actor=? AND live=1 ORDER BY id", (scope, ctx.actor)).fetchall():
        try:
            ctx.require(scope, "publish")
            if page["page_rev"] != page["delivered_rev"] or ctx.audience(scope) != json.loads(page["audience"]):
                raise ValueError("Destination content or audience changed")
            owner = ctx.db.execute("SELECT scope FROM owners WHERE id=?", (page["record"],)).fetchone()
            if not owner:
                raise ValueError("The source owner is unverified")
            source = ctx.record(owner["scope"], "record", page["record"])
            if source["revision"] == page["source_rev"]:
                continue
            if not set(ctx.audience(scope)) <= set(ctx.audience(owner["scope"])).intersection(source["record"]["reviewed_audience"]):
                raise PermissionError("The publication audience exceeds its new source scope")
            check_references(ctx, source["record"]["references"], ctx.audience(scope))
            new_revision = page["page_rev"] + 1
            ctx.db.execute("BEGIN IMMEDIATE")
            try:
                ctx.db.execute("UPDATE pages SET body=?,source_rev=?,source_updated=?,page_rev=?,delivered_rev=?,updated=? WHERE id=?",
                               (source["record"]["content"], source["revision"], source["record"]["last_updated"], new_revision, new_revision, now(), page["id"]))
                bind_distribution(ctx,page["id"],{"scope":owner["scope"],"kind":"record","id":page["record"],"revision":source["revision"]},source["record"]["references"])
                ctx.receipt(digest(canonical(["live",page["id"],source["revision"]])), "live-publication", scope, str(new_revision))
                ctx.db.execute("COMMIT")
            except BaseException:
                ctx.db.execute("ROLLBACK")
                raise
            result.append({"page": page["id"], "status": "published", "revision": new_revision})
        except (ValueError, PermissionError):
            result.append({"page": page["id"], "status": "held"})
    return result
