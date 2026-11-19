"""Expose the governed initiative workflow through the existing pm.py command."""

import json
import sys

from initiative_events import (DECISION_FIELDS, EVALUATION_FIELDS, FIELDS, HORIZONS, OPTIONAL_FIELDS,
                               OUTCOME_STATUSES, PHASES, RESULTS, RISKS, TRANSITIONS)
import experiment_drafts
import initiative_areas
import storage
import initiative_store
import initiative_views
import workspace


def add_commands(commands):
    initiative = commands.add_parser("initiative", help="Inspect or propose changes to a signed initiative register")
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
    sync = operations.add_parser("sync-drafts", help="Restore missing drafts and finish previously signed promotions")
    sync.add_argument("product")
    apply = operations.add_parser("apply", help="PM approval using a signing key outside this checkout")
    apply.add_argument("product")
    apply.add_argument("--key", required=True)
    apply.add_argument("--confirm-distinct", action="append", default=[], metavar="NEW_ID",
                       help="PM confirmation that one reviewed capture describes a distinct problem")

    backlog = commands.add_parser("backlog", help="Generate the current initiative backlog")
    scope = backlog.add_mutually_exclusive_group()
    scope.add_argument("--phase", choices=PHASES)
    scope.add_argument("--all-phases", action="store_true", help="Include selected, deferred, and closed initiatives")
    backlog.add_argument("--due", action="store_true", help="Show reviews due today or earlier and report review issues")
    roadmap = commands.add_parser("roadmap", help="Generate the current selected roadmap")
    roadmap.add_argument("--cycle", help="Show one planning cycle")
    for view in (backlog, roadmap):
        view.add_argument("--product")
        view.add_argument("--area", help="Full product area subject, or area slug with --product")
        view.add_argument("--format", choices=("json", "csv", "markdown"), default="json")


def run(root, args):
    if args.command == "initiative" and args.operation == "schema":
        print(json.dumps({
            "input": "array of objects with type and all required fields",
            "fields_by_type": {**FIELDS, "approve-experiment": experiment_drafts.APPROVAL},
            "optional_fields_by_type": OPTIONAL_FIELDS,
            "registry_metric": "Use type metric and its registry ID. For a revised snapshot, use a new metric ID plus registry_metric.",
            "intake_review": "Proposals compare new IDs against this product's history. The PM confirms distinct captures at apply.",
            "extra_fields_by_decision": DECISION_FIELDS,
            "evaluation_fields": EVALUATION_FIELDS,
            "target_review_fields": {
                "status": "PM judgment using an allowed outcome status",
                "measurements": "distinct release measurement IDs for this initiative and target; met, missed and inconclusive require evidence",
                "assessment": "PM interpretation of the outcome, guardrails or missing evidence",
            },
            "transitions": {action: {"from": sorted(start), "to": end} for action, (start, end) in TRANSITIONS.items()},
            "horizons": HORIZONS,
            "allowed_values": {"risk": RISKS, "conclusion": RESULTS, "horizon": HORIZONS,
                               "transition": sorted(TRANSITIONS), "outcome status": OUTCOME_STATUSES},
            "formats": {
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
            rows = initiative_views.backlog(registers, args.phase, args.due, args.all_phases, area=area)
        else:
            rows = initiative_views.roadmap(registers, args.cycle, area=area)
    elif args.operation == "show":
        _, register = next(initiative_store.registrations(root, args.product))
        result = initiative_views.trace(args.product, register, args.id, private=private)
        result["review_issues"] = initiative_store.live_errors(root, register)
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
        revision = initiative_store.apply(root, args.product, initiative_store.json_input(sys.stdin.read()),
                                          args.key, args.confirm_distinct)
        print(f"Recorded PM-signed revision {revision}.")
        return
    output = initiative_views.render(initiative_views.view_template(root, args.command), rows, args.format)
    if due_view:
        for _, register in registers:
            for issue in initiative_store.live_errors(root, register, area=area):
                print(f"Review issue: {issue}", file=sys.stderr)
    print(output)
