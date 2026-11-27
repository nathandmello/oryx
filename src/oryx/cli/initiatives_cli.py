"""Expose the governed initiative workflow through the existing pm.py command."""

import json
import sys

from initiative_events import (DECISION_FIELDS, EVALUATION_FIELDS, FIELDS, HORIZONS, OPTIONAL_FIELDS,
                               RATIONALE_FIELDS, OUTCOME_STATUSES, PHASES, RESULTS, RISKS, SIGNAL_ACTIONS, SIGNAL_IMPACTS, TRANSITIONS)
import customizations
import experiment_drafts
import initiative_areas
import storage
import initiative_store
import initiative_views
import metric_registry
import workspace


def add_commands(commands):
    initiative = commands.add_parser("initiative", help="Inspect or propose changes to a reviewed initiative register")
    operations = initiative.add_subparsers(dest="operation", required=True)
    operations.add_parser("schema", help="Show the accepted transaction fields")
    show = operations.add_parser("show", help="Follow an initiative, its evidence, and its metrics by ID")
    show.add_argument("product")
    show.add_argument("id", nargs="?")
    propose = operations.add_parser("propose", help="Validate JSON transactions from stdin without writing")
    propose.add_argument("product")
    draft = operations.add_parser("draft-experiment", help="Start or resume an editable draft for an initiative and metric")
    draft.add_argument("product")
    draft.add_argument("id")
    draft.add_argument("metric")
    sync = operations.add_parser("sync-drafts", help="Restore missing drafts and finish approved promotions")
    sync.add_argument("product")
    recover = operations.add_parser("recover", help="Finish a previously approved register update after interruption")
    recover.add_argument("product")
    apply = operations.add_parser("apply", help="Record the exact proposal reviewed by the PM")
    apply.add_argument("product")
    apply.add_argument("--approve", metavar="REVISION", help="Explicitly approve this exact reviewed revision from the PM shell")
    apply.add_argument("--confirm-distinct", action="append", default=[], metavar="NEW_ID",
                       help="PM confirmation that one reviewed capture describes a distinct problem")

    backlog = commands.add_parser("backlog", help="Generate the current initiative backlog")
    scope = backlog.add_mutually_exclusive_group()
    scope.add_argument("--phase", choices=PHASES)
    scope.add_argument("--all-phases", action="store_true", help="Include selected, deferred, and closed initiatives")
    backlog.add_argument("--due", action="store_true", help="Show reviews due today or earlier and report review issues")
    roadmap = commands.add_parser("roadmap", help="Generate the current selected roadmap")
    roadmap.add_argument("--view", help="Use a named workspace roadmap view")
    roadmap.add_argument("--cycle", help="Show one planning cycle")
    for view in (backlog, roadmap):
        view.add_argument("--product")
        view.add_argument("--area", help="Full product area subject, or area slug with --product")
        view.add_argument("--format", choices=("json", "csv", "markdown", "html") if view is roadmap else ("json", "csv", "markdown"), default="json")


def confirm_on_terminal(product, proposal):
    """Read the PM's choice from the controlling terminal while stdin carries the proposal."""
    if not isinstance(proposal, dict) or proposal.get("product") != product:
        raise ValueError("Choose the product named in the reviewed proposal")
    try:
        with open("/dev/tty", "w", encoding="utf-8") as prompt, open("/dev/tty", encoding="utf-8") as response:
            # ASCII escapes keep control characters in evidence from changing the prompt.
            prompt.write(json.dumps(proposal, ensure_ascii=True, indent=2) + "\n")
            prompt.write(f"Approve this exact proposal for {product}? Type approve to record it: ")
            prompt.flush()
            answer = response.readline().strip()
    except OSError as exc:
        raise ValueError("Open a PM terminal to review this proposal, or pass --approve with the exact reviewed revision") from exc
    if answer != "approve":
        raise ValueError("PM approval cancelled")
    return proposal.get("revision")


def run(root, args):
    from oryx.workspace import publication
    if args.command in {"backlog", "roadmap"} or getattr(args, "operation", "") in {"show", "propose"}:
        with publication.view(root):
            return run_command(root, args)
    return run_command(root, args)


def run_command(root, args):
    if args.command == "initiative" and args.operation == "schema":
        print(json.dumps({
            "input": "array of objects with type and all required fields",
            "fields_by_type": {**FIELDS, "approve-experiment": experiment_drafts.APPROVAL},
            "optional_fields_by_type": OPTIONAL_FIELDS,
            "registry_metric": "Use type metric and its registry ID. For a revised snapshot, use a new metric ID plus registry_metric.",
            "intake_review": "Proposals compare new IDs against this product's history. The PM confirms distinct captures at apply.",
            "signal_review": "Review new evidence against the active approved plan. Use the source locator as signal and quote the affected claim.",
            "extra_fields_by_decision": DECISION_FIELDS,
            "ship_exceptions": "Optional object keyed by outstanding readiness ID. Each entry needs reason and authority. Review the generated readiness snapshot before approval.",
            "outcome_evidence": {
                "guardrail": "Safe bound by metric, unit, population, window basis and effective_on. Use lt, lte, gt or gte.",
                "adopted_from": "For a historical threshold provide the original target metric ID, on date and source.",
                "observation": "Supply definition reference, unit, population, basis, timezone, start, exclusive end, complete and source. Supply ratio inputs when applicable.",
                "value": "Use a numeric value in the declared unit with an observation. Use decimal strings for exact figures.",
                "correct-measurement": "Give the active measurement ID, reason, source and optional comparable replacement ID. Cite comparison_source for a legacy reading.",
                "guardrail_dispositions": "On review-outcomes, give each breached or unavailable guardrail ID and the PM's disposition.",
                "recorded_on": "oryx supplies the date of approval for new evidence transactions.",
            },
            "evaluation_fields": EVALUATION_FIELDS,
            "optional_decision_rationale": {"required": RATIONALE_FIELDS, "optional": ["review_on"],
                "alternatives": "nonempty list distinct from choice; decision source also covers rationale",
                "storage": "reviewed as part of the approved reason"},
            "target_review_fields": {
                "status": "PM judgment using an allowed outcome status",
                "measurements": "distinct release measurement IDs for this initiative and target; met, missed and inconclusive require evidence",
                "assessment": "PM interpretation of the outcome, guardrails or missing evidence",
            },
            "transitions": {action: {"from": sorted(start), "to": end} for action, (start, end) in TRANSITIONS.items()},
            "horizons": HORIZONS,
            "allowed_values": {"risk": RISKS, "conclusion": RESULTS, "horizon": HORIZONS,
                               "window": metric_registry.REPORTING_WINDOWS, "transition": sorted(TRANSITIONS), "outcome status": OUTCOME_STATUSES,
                               "signal impact": SIGNAL_IMPACTS, "signal action": SIGNAL_ACTIONS},
            "formats": {
                "object": "JSON object with the fields specified for its transaction",
                "number": "finite numeric value in the approved unit; use a decimal string to preserve precision",
                "bound": "lt or lte for a safe upper limit; gt or gte for a safe lower limit",
                "target reviews": "object keyed by every initiative target metric ID, using target_review_fields; empty for a release without targets",
                "review follow-up": "null to close, or an object with on (date) and action (text); required for pending outcomes",
                "initiative ID": "registered product context ID, a slash, and an initiative slug",
                "initiative IDs": "nonempty array of distinct initiative IDs",
                "product areas": "array of distinct product/<product>/area/<area> subjects in this product; [] clears the links",
                "slug": "lowercase ASCII letters and digits separated by single hyphens",
                "experiment ID": "an experiment slug or the experiment.<metric-id> returned by initiative show",
                "date": "YYYY-MM-DD",
                "past date": "YYYY-MM-DD on or before today",
                "positive": "integer greater than zero", "count": "nonnegative integer",
                "confidence": "integer from 0 to 10", "URL": "absolute HTTPS URL without credentials",
                "path": "workspace-relative path", "text": "concrete single-line text without placeholders",
                "optional text": "concrete single-line text or null",
            },
        }, indent=2))
        return
    workspace.repo(root, "workspace")
    workspace.settings(root)
    private = workspace.private_root(root)
    if args.command in {"backlog", "roadmap"}:
        product, area = initiative_areas.filter_subject(args.product, args.area)
        due_view = args.command == "backlog" and args.due
        registers = initiative_store.registrations(root, product, require_current=not due_view)
        if due_view or area is not None:
            registers = list(registers)
        if area is not None:
            if not any(area in item["areas"] for _, register in registers for item in register.items.values()):
                info = initiative_areas.resolve(private, product, area)
                if "issue" in info:
                    raise ValueError(info["issue"])
        if args.command == "backlog":
            rows = initiative_views.backlog(registers, args.phase, args.due, args.all_phases, area=area, private=private)
        else:
            rows = initiative_views.roadmap(registers, args.cycle, area=area, private=private)
    elif args.operation == "show":
        _, register = next(initiative_store.registrations(root, args.product))
        result = initiative_views.trace(args.product, register, args.id, private=private)
        result["review_issues"] = initiative_store.live_errors(root, register)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    elif args.operation == "recover":
        revision = initiative_store.recover(root, args.product)
        print(f"Restored PM-approved revision {revision}.")
        return
    elif args.operation == "propose":
        result, _, _, _ = initiative_store.prepare(root, args.product, initiative_store.json_input(sys.stdin.read()))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    elif args.operation in {"sync-drafts", "draft-experiment"}:
        with storage.writer_lock(private):
            _, register = next(initiative_store.registrations(root, args.product))
            if args.operation == "draft-experiment":
                print(experiment_drafts.start(private, args.product, register, args.id, args.metric))
            else:
                experiment_drafts.sync(private, args.product, register)
                print("Experiment drafts are current.")
        return
    else:
        initiative_store.require_pm_session()
        proposal = initiative_store.json_input(sys.stdin.read())
        approval = args.approve if args.approve is not None else confirm_on_terminal(args.product, proposal)
        revision = initiative_store.apply(root, args.product, proposal, approved_revision=approval,
                                          confirmations=args.confirm_distinct)
        print(f"Recorded PM-approved revision {revision}.")
        return
    if args.command == "roadmap":
        template = customizations.projection(root, rows, args.view, product=product)
    else:
        template = initiative_views.view_template(root, args.command)
    if args.format == "html":
        output = customizations.page(root, template, rows)
    else:
        output = initiative_views.render(template, rows, args.format)
    if due_view:
        for _, register in registers:
            for issue in initiative_store.live_errors(root, register, area=area):
                print(f"Review issue: {issue}", file=sys.stderr)
    print(output)
