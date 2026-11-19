"""Verify and publish signed initiative transactions in the private workspace."""

from datetime import date
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from tempfile import TemporaryDirectory

from initiative_events import DISCOVERY_PLAN_SCOPE, Register, needs_reference, validate_event
import brief_review
import evidence_reviews
import experiment_drafts
import initiative_areas
import initiative_intake
import initiative_work
import launch_readiness
import initiative_views
import layout
import layout_upgrade
import metric_registry
import opportunities
import outcome_evidence
import records
import storage
import upgrades
from storage import json_input

FILENAME = "initiatives.json"
NAMESPACE = "pm-hub-initiatives"
PRINCIPAL = "pm-hub-pm"
SIGNERS_ENV = "PM_HUB_ALLOWED_SIGNERS"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def external_file(root, value, label):
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path or path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"{label} must be a regular file outside the Hub checkout")
    return path


def verify(root, payload, signature):
    signers = os.environ.get(SIGNERS_ENV)
    if not signers:
        raise ValueError(f"Set {SIGNERS_ENV} to the trusted PM allowed-signers file")
    signers = external_file(root, signers, "Allowed signers")
    if not isinstance(signature, str) or not signature.startswith("-----BEGIN SSH SIGNATURE-----\n"):
        raise ValueError("Expected a PM SSH signature")
    with TemporaryDirectory() as folder:
        sig = Path(folder) / "register.sig"
        sig.write_text(signature, encoding="utf-8")
        result = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", PRINCIPAL,
             "-n", NAMESPACE, "-s", str(sig)],
            input=canonical(payload), capture_output=True, check=False,
        )
    if result.returncode:
        raise ValueError("Initiative register signature does not match the trusted PM signer")


def sign(root, payload, key):
    key = external_file(root, key, "PM signing key")
    result = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", NAMESPACE],
        input=canonical(payload), capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError("The PM signing key could not sign the reviewed transactions")
    signature = result.stdout.decode("ascii")
    verify(root, payload, signature)
    return signature


def register_path(root, product):
    if not isinstance(product, str) or not opportunities.SLUG.fullmatch(product):
        raise ValueError("Use the registered product slug")
    path = storage.private_root(root) / layout.initiative_register(product)
    if path.resolve() != path:
        raise ValueError("The initiative register must be a regular file under its product")
    return path


def local_markdown(root, name, kind):
    path = PurePosixPath(name)
    if (path.is_absolute() or path.as_posix() != name or "\\" in name or path.suffix != ".md"
            or any(part.startswith(".") or part in {"sources", "secrets"} for part in path.parts)):
        raise ValueError(f"Use a workspace-relative {kind} Markdown path")
    private = storage.private_root(root)
    target = private / path
    if target.resolve() != target or not target.is_file():
        raise ValueError(f"Required {kind} record is missing: {name}")
    storage.require_visible(private, path)
    if name in upgrades.source_paths(private):
        raise ValueError(f"{name} is preserved as an original source; use an active {kind} record")
    contents = target.read_bytes()
    text = contents.decode("utf-8").replace("\r\n", "\n")
    marker = records.MARKER.match(text)
    identifier, errors = records.state_errors(text)
    if not marker or marker[1] != kind or errors:
        details = f" ({'; '.join(errors)})" if errors else ""
        raise ValueError(f"{name} must be a valid {kind} record{details}")
    return text, identifier, contents


def context_references(root, product, setup):
    company, product_context = setup["company"], setup["product_context"]
    if company != layout.COMPANY or product_context != layout.product(product):
        raise ValueError("Choose the company context and the context record that owns this product")
    _, company_id, _ = local_markdown(root, company, "company-context")
    text, product_id, _ = local_markdown(root, product_context, "product-context")
    if records.parent_reference(product_context, text) != company:
        raise ValueError("The product context must link to the registered company context")
    return {"company_id": company_id, "product_id": product_id}


def brief_path(product, initiative, kind):
    return layout.initiative_brief(product, initiative.split("/")[1], kind)


def doc_reference(root, name, kind, *, plan_scope=None, options=None, initiative=None, review=False):
    text, identifier, contents = local_markdown(root, name, kind)
    if kind in opportunities.BRIEFS:
        parent_error = opportunities.brief_parent_error(name, text, initiative)
        if parent_error:
            raise ValueError(parent_error)
    if plan_scope == DISCOVERY_PLAN_SCOPE:
        # The section reader treats column-zero "## " lines as boundaries, including inside examples.
        headings_pattern = r"(?m)^## ([^\n]*)"
        raw = [heading.rstrip() for heading in re.findall(headings_pattern, text)]
        visible = [heading.rstrip() for heading in re.findall(headings_pattern, brief_review.visible(text))]
        allowed = {"Parent initiative", "Work state", *opportunities.REQUIRED_SECTIONS[kind]}
        names = set(raw)
        if raw != visible or len(raw) != len(names) or not names <= allowed:
            raise ValueError(f"{name}: ambiguous discovery section boundary. Use ### for subsections "
                             "and indent example headings inside code or comments.")
    headings = (*opportunities.DISCOVERY_PLAN, "Sources") if plan_scope else opportunities.REQUIRED_SECTIONS[kind]
    missing = opportunities.missing(text, headings)
    if missing:
        raise ValueError(f"{name} needs content in {', '.join(missing)}")
    if review and kind in opportunities.BRIEFS:
        brief_review.check_review_content(text, kind, headings, root=root)
    reference = {"path": name, "id": identifier}
    if plan_scope:
        if plan_scope == DISCOVERY_PLAN_SCOPE:
            reference["scope"] = DISCOVERY_PLAN_SCOPE
        elif plan_scope == "legacy-plan":
            # An older signed timebox covered the plan sections alone.
            headings = opportunities.DISCOVERY_PLAN
        else:
            raise ValueError("Unknown signed discovery plan scope")
        revision = digest(canonical([records.section(text, heading).strip() for heading in headings]))
    else:
        if records.work_state(text)[0].get("State") != "complete":
            raise ValueError(f"Complete {name} before this decision")
        if options is not None:
            opportunities.check_comparison(text, options)
        revision = digest(contents)
    return {**reference, "sha256": revision}


def capture_references(root, product, event, register):
    kind = event["type"]
    if kind == "setup":
        reference = context_references(root, product, event)
        for existing_product, existing in registrations(root):
            if existing_product != product and existing.setup["references"]["product_id"] == reference["product_id"]:
                raise ValueError("This product context ID already owns an initiative register")
        return reference
    if kind == "cycle":
        for identifier in event["options"]:
            item = register.items.get(identifier)
            if item is None or item["phase"] != "candidate":
                raise ValueError(f"Cycle option {identifier} must be an approved candidate in this product")
        return doc_reference(root, layout.prioritization(product, event["cycle"]), "prioritization", options=event["options"])
    if kind == "review-signal":
        item = register.items.get(event["initiative"])
        review = item["_signal_reviews"].get(event["signal"]) if item else None
        if not review:
            raise ValueError("Choose a signal recorded on this initiative after approval")
        claim = None
        if event["claim"] is not None:
            claims = initiative_views.signal_claims(storage.private_root(root), review["basis"])
            claim = next((claim for claim in claims if claim["text"] == event["claim"]), None)
            if claim is None:
                raise ValueError("Quote a specific claim from the signed brief, approval, or plan")
        return {"basis": review["basis"], "claim": claim}
    action = event["action"]
    initiative = event["initiative"]
    if initiative not in register.items:
        raise ValueError(f"Unknown initiative in this product: {initiative}")
    if action == "approve-initiative":
        return doc_reference(root, brief_path(product, initiative, "initiative-brief"), "initiative-brief",
                             initiative=initiative, review=True)

    discovery = brief_path(product, initiative, "discovery-brief")
    if action == "start-discovery":
        return doc_reference(root, discovery, "discovery-brief", plan_scope=DISCOVERY_PLAN_SCOPE,
                             initiative=initiative, review=True)
    item = register.items[initiative]
    if item["phase"] == "in discovery":
        signed_plan = item["discovery"][1]
        if "scope" not in signed_plan:
            raise ValueError("The prior timebox did not bind Sources. Review the citations and sign start-discovery before prepare-brief.")
        if doc_reference(root, discovery, "discovery-brief", plan_scope=DISCOVERY_PLAN_SCOPE, initiative=initiative) != signed_plan:
            raise ValueError("The discovery plan changed. Authorize the revised timebox before concluding.")
        return doc_reference(root, discovery, "discovery-brief", initiative=initiative, review=True)
    return {}


def live_errors(root, register, initiative=None, *, investment=False):
    """Check exact revisions for live gates while preserving historical signed decisions."""
    errors = []
    for item in register.items.values():
        if initiative is not None and item["id"] != initiative:
            continue
        phase = item["phase"]
        references = []
        if phase == "in discovery":
            signed_plan = item["discovery"][1]
            references.append((signed_plan, "discovery-brief", signed_plan.get("scope", "legacy-plan")))
        elif phase in {"defining", "candidate", "planned", "delivery"} and item["discovery_findings"]:
            references.append((item["discovery_findings"], "discovery-brief", None))
        if phase in {"candidate", "planned", "delivery"} and item["initiative_brief"]:
            references.append((item["initiative_brief"], "initiative-brief", None))
        if phase in {"planned", "delivery"} and item["planning"]:
            cycle = register.cycles[item["planning"]["cycle"]]
            references.append((cycle["references"], "prioritization", None))
        for reference, kind, plan_scope in references:
            review_brief = investment and kind == "initiative-brief"
            try:
                current = doc_reference(root, reference["path"], kind, plan_scope=plan_scope, initiative=item["id"],
                                        review=review_brief)
                if current != reference:
                    raise ValueError(f"{reference['path']} differs from the reviewed revision")
            except (OSError, ValueError) as exc:
                recovery = " Reopen the initiative, revise its brief, and obtain a new approval." if review_brief else ""
                errors.append(f"{item['id']}: {exc}{recovery}")
    return errors


def read(root, product):
    target = register_path(root, product)
    private = storage.private_root(root)
    for old_path in layout_upgrade.legacy_initiative_registers(private):
        if old_path.parent.name == product:
            raise ValueError(f"Existing prototype register at {old_path.relative_to(private)}. Preserve it and use its original Hub checkout.")
    register = Register(product)
    if not target.exists():
        return None, {"version": 1, "product": product, "events": []}, register
    storage.require_visible(private, target.relative_to(private))
    original = target.read_text(encoding="utf-8")
    value = json_input(original)
    if not isinstance(value, dict) or set(value) != {"record", "signature"}:
        raise ValueError(f"{product}: expected a signed initiative register")
    payload = value["record"]
    verify(root, payload, value["signature"])
    if (not isinstance(payload, dict) or set(payload) != {"version", "product", "events"}
            or type(payload["version"]) is not int or payload["version"] != 1 or payload["product"] != product
            or not isinstance(payload["events"], list) or not payload["events"]):
        raise ValueError(f"{product}: unexpected initiative register schema or product")
    for index, event in enumerate(payload["events"]):
        register.accept(event, index)
        if event.get("action") == "ship" and "readiness" in event:
            launch_readiness.require_exceptions(event)
    if context_references(root, product, register.setup) != register.setup["references"]:
        raise ValueError(f"{product}: registered company or product context identity changed")
    return original, payload, register


def pinned_definition(root, product, metric):
    """Find an older signed registry snapshot without substituting a newer definition."""
    if "contract" in metric:
        return metric["contract"]
    name = metric_registry.reference_metric(metric)
    if not name:
        return None
    reference = metric["source"].removeprefix(metric_registry.REFERENCE)
    private = storage.private_root(root)
    bundled = metric_registry.defaults(root).get(name)
    if bundled:
        row = metric_registry.describe(name, bundled)
        if row["reference"] == reference:
            return row
    for entry in metric_registry.history(private)[1]["revisions"]:
        if entry["metric"] == name and entry["product"] in (None, product):
            row = metric_registry.describe(name, entry["definition"], product=entry["product"],
                                           approved_by=entry["approved_by"], effective_on=entry["effective_on"])
            if row["reference"] == reference:
                return row
    raise ValueError(f"Recover the approved metric revision {reference} before recording new evidence")


def prepare(root, product, changes, *, review_dates=None):
    if not isinstance(changes, list) or not changes:
        raise ValueError("Provide a nonempty JSON array of transactions")
    original, payload, register = read(root, product)
    previous_events = payload["events"]
    accepted = []
    intake_reviews = {}
    signal_sources = {}
    proposed_experiments = set()
    definitions = None
    for event in changes:
        if isinstance(event, dict) and event.get("type") == "approve-experiment":
            event = experiment_drafts.proposed_plan(storage.private_root(root), product, register, event)
        elif (isinstance(event, dict) and event.get("type") == "experiment"
              and str(event.get("experiment", "")).startswith("experiment.")):
            raise ValueError("Use approve-experiment to review the named draft")
        if isinstance(event, dict) and event.get("type") == "metric":
            event = metric_registry.snapshot(root, storage.private_root(root), product, event)
        validate_event(event)
        kind = event["type"]
        if kind == "metric" and metric_registry.reference_metric(event):
            event = {**event, "contract": pinned_definition(root, product, event)}
        if kind in outcome_evidence.READINGS | {"guardrail", "correct-measurement"}:
            event = {**event, "recorded_on": date.today().isoformat()}
            if kind != "correct-measurement":
                definition = register.metrics.get(event["metric"])
                if definition and metric_registry.reference_metric(definition) and (
                        kind == "guardrail" or "observation" in event and "contract" not in definition):
                    event["contract"] = pinned_definition(root, product, definition)
                if definition and metric_registry.reference_metric(definition) and "observation" in event:
                    cutoff = outcome_evidence.measurement_cutoff(event)
                    current = metric_registry.effective(root, storage.private_root(root), product, cutoff)
                    effective = current.get(metric_registry.reference_metric(definition))
                    if effective and definition["source"] != metric_registry.REFERENCE + effective["reference"]:
                        if not brief_review.has_answer(event.get("restatement", "")):
                            raise ValueError("The registry changed at this cutoff. Cite the source of a restatement on the signed basis.")
        if kind == "decision" and event["action"] == "review-outcomes":
            item = register.items.get(event["initiative"])
            if item:
                event = {**event, "evidence_review": outcome_evidence.review_snapshot(item, event, register.metrics)}
        if event["type"] == "target" and (existing := register.metrics.get(event["metric"])):
            if definitions is None:
                definitions = metric_registry.effective(root, storage.private_root(root), product)
            current = metric_registry.current_for_snapshot(definitions, existing)
            if current and existing["source"] != metric_registry.REFERENCE + current["reference"]:
                raise ValueError("Use the effective registry definition under a new metric ID for this target.")
            if not current and metric_registry.reference_metric(existing):
                raise ValueError("The signed definition is no longer in the registry. Review a current definition under a new metric ID.")
            if not current and metric_registry.named_definitions(definitions, existing["name"]):
                raise ValueError("Several registry definitions match the signed metric. Choose one and propose it under a new metric ID.")
        if event["type"] == "capture" and register.items:
            shortlist = initiative_intake.candidates(register.items, event)
            intake_reviews[event["initiative"]] = shortlist
            event = {**event, "intake_review": {"considered": len(register.items),
                                                "candidates": [row["id"] for row in shortlist]}}
        initiative_areas.check_change(storage.private_root(root), product, register, event)
        if event["type"] == "experiment":
            if event["planned_on"] < date.today().isoformat():
                raise ValueError("Set the planned test date to the approval date or later")
            proposed_experiments.add((event["initiative"], event["experiment"]))
        elif event["type"] == "result" and (event["initiative"], event["experiment"]) in proposed_experiments:
            raise ValueError("Apply the experiment approval before proposing its results")
        if event["type"] == "decision" and event["action"] in {"approve-initiative", "plan", "start-delivery", "ship"}:
            problems = live_errors(root, register, event["initiative"], investment=event["action"] in {"plan", "start-delivery"})
            if problems:
                raise ValueError("Resolve the existing review gates:\n" + "\n".join(problems))
        if event.get("action") == "ship":
            reviewed_on = review_dates.get(len(accepted)) if review_dates else None
            item = register.items.get(event["initiative"])
            if item is None:
                raise ValueError(f"Unknown initiative in this product: {event['initiative']}")
            private = storage.private_root(root)
            advisories = {
                "signals": {r["id"]: r for r in initiative_views.signal_reviews(private, item)
                            if r["active"] and r["state"] != "routine"},
                "context": evidence_reviews.launch_context(private, product, item),
            }
            snapshot = initiative_work.ship_snapshot(root, product, event["initiative"], event["on"], reviewed_on, advisories)
            if set(event.get("exceptions", {})) - snapshot["outstanding"].keys():
                raise ValueError("Preview the current evidence. Ship exceptions must refer to current outstanding launch risks: "
                                 + ", ".join(sorted(snapshot["outstanding"])))
            event = {**event, "readiness": snapshot}
        if needs_reference(event):
            event = {**event, "references": capture_references(root, product, event, register)}
        register.accept(event, len(previous_events) + len(accepted))
        if event["type"] in {"signal", "review-signal"}:
            source = event["signal"] if event["type"] == "review-signal" else event["source"]
            signal_sources.setdefault(event["initiative"], set()).add(source)
        if event["type"] == "decision" and event["action"] == "plan":
            cycle = register.cycles[event["cycle"]]
            if register.approved_at[event["initiative"]] > cycle["compared_at"]:
                raise ValueError("Review a new comparison for the current Initiative Brief approval before selection")
        accepted.append(event)
    errors = live_errors(root, register)
    if errors:
        raise ValueError("Resolve the existing review gates:\n" + "\n".join(errors))
    candidate = {**payload, "events": previous_events + accepted}
    proposal = {
        "product": product, "base": digest(canonical(payload)) if original is not None else None,
        "changes": changes, "reviewed_transactions": accepted, "revision": digest(canonical(candidate)),
    }
    if intake_reviews:
        proposal["intake_reviews"] = intake_reviews
    signal_reviews = {}
    for initiative, sources in signal_sources.items():
        reviews = [review for review in initiative_views.signal_reviews(storage.private_root(root), register.items[initiative])
                   if review["id"] in sources]
        if reviews:
            signal_reviews[initiative] = reviews
    if signal_reviews:
        proposal["signal_reviews"] = signal_reviews
    return proposal, original, candidate, register


def apply(root, product, proposal, key, confirmations=()):
    private = storage.private_root(root)
    if (not isinstance(proposal, dict)
            or set(proposal) - {"intake_reviews", "signal_reviews"}
            != {"product", "base", "changes", "reviewed_transactions", "revision"}):
        raise ValueError("Apply requires the complete JSON from initiative propose")
    reviewed = proposal["reviewed_transactions"]
    if not isinstance(reviewed, list):
        raise ValueError("Apply requires the reviewed transactions from initiative propose")
    review_dates = {}
    for index, event in enumerate(reviewed):
        if isinstance(event, dict) and event.get("action") == "ship" and "readiness" in event:
            launch_readiness.validate_snapshot(event["readiness"])
            review_dates[index] = event["readiness"]["reviewed_on"]
    with storage.writer_lock(private):
        expected, original, candidate, _ = prepare(root, product, proposal["changes"], review_dates=review_dates)
        if proposal != expected:
            raise ValueError("The proposal is stale or was modified. Preview it and review the new revision.")
        for event in expected["reviewed_transactions"]:
            if event.get("action") == "ship":
                launch_readiness.require_exceptions(event)
        initiative_intake.confirm_distinct(expected["reviewed_transactions"], confirmations)
        target = register_path(root, product)
        storage.require_visible(private, target.relative_to(private))
        signature = sign(root, candidate, key)
        # A hardware-backed signer can wait for human confirmation. Recheck before publication.
        try:
            current, _, _, register = prepare(root, product, proposal["changes"], review_dates=review_dates)
        except (ValueError, OSError) as exc:
            raise ValueError(f"Records changed while approval was pending. Review a new proposal. {exc}") from exc
        if current != expected:
            raise ValueError("Records changed while approval was pending. Review a new proposal.")
        envelope = json.dumps({"record": candidate, "signature": signature}, ensure_ascii=False, indent=2) + "\n"
        draft_changes = experiment_drafts.pending(private, product, register, current["reviewed_transactions"])
        storage.replace_text(target, original, envelope, mode=storage.initiative_mode(target, draft=False))
        try:
            experiment_drafts.sync(private, product, register, draft_changes)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Revision {expected['revision']} was signed and saved. "
                             f"Resolve the draft issue, then run initiative sync-drafts {product}: {exc}") from exc
    return expected["revision"]


def products(root):
    private = storage.private_root(root)
    layout_upgrade.require_supported_registers(private)
    home = private / "workspace" / "backlogs"
    if home.resolve() != home:
        raise ValueError("Use a regular workspace/backlogs directory")
    return sorted(path.parent.name for path in home.glob(f"*/{FILENAME}"))


def registrations(root, product=None, require_current=False):
    names = [product] if product is not None else products(root)
    seen = set()
    for slug in names:
        original, _, register = read(root, slug)
        if original is None:
            if product is not None:
                raise ValueError(f"{slug}: set up the product initiative register first")
            continue
        product_id = register.setup["references"]["product_id"]
        if product_id in seen:
            raise ValueError(f"Duplicate registered product context ID: {product_id}")
        seen.add(product_id)
        if require_current and (errors := live_errors(root, register)):
            raise ValueError("\n".join(errors))
        yield slug, register


def verify_draft_home(root, kind, name):
    parts = PurePosixPath(name).parts
    if (kind == "roadmap" and len(parts) == 3 and parts[:2] == ("workspace", "roadmaps")
            and register_path(root, PurePosixPath(name).stem).is_file()):
        raise ValueError("Use pm.py roadmap for a product with a signed initiative register")
    if kind not in opportunities.BRIEFS:
        return
    _, _, register = read(root, parts[2])
    product_id = register.setup["references"]["product_id"] if register.setup else ""
    identifier = f"{product_id}/{parts[3]}"
    if identifier not in register.items:
        raise ValueError("Register the initiative with the PM before creating its brief")
    return identifier


def draft_errors(texts, products):
    for name, text in texts.items():
        marker = records.MARKER.match(text)
        if not marker or marker[1] not in opportunities.BRIEFS:
            continue
        if opportunities.location_error(marker[1], name):
            continue
        _, _, slug, subject, _ = PurePosixPath(name).parts
        register = products.get(slug)
        product_id = register.setup["references"]["product_id"] if register else ""
        identifier = f"{product_id}/{subject}"
        if not register or identifier not in register.items:
            yield f"{name}: brief must belong to an initiative in the signed product register"
        elif error := opportunities.brief_parent_error(name, text, identifier):
            yield error
