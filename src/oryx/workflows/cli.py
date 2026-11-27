"""Manage guided work through a selected Workspace and reviewed, scoped handoff."""

import json
import sys
from . import checkpoints


def checked_paths(private):
    from . import capture_review
    return capture_review.checked_paths(private) | checkpoints.checked_paths(private)


def register(commands):
    parser = commands.add_parser("workflow", description=__doc__)
    actions = parser.add_subparsers(dest="wf_operation", required=True)
    start = actions.add_parser("start", help="Start a personal workflow for an exact reviewed handoff")
    start.add_argument("route", help="Quoted three-part guided catalog command")
    start.add_argument("--handoff", required=True)
    start.add_argument("--scope", required=True)
    start.add_argument("--revision", required=True, help="Current reviewed handoff revision")
    show = actions.add_parser("show", help="Revalidate scope, method version and evidence before resuming")
    show.add_argument("identifier")
    show.add_argument("--scope", required=True)
    show.add_argument("--with-inputs", action="store_true",
                      help="Read scoped JSON on stdin to include selected Core references and count supplied hook/tool text")
    advance = actions.add_parser("advance", help="Record the PM-selected transition at the expected revision")
    advance.add_argument("identifier")
    advance.add_argument("--scope", required=True)
    advance.add_argument("--expect", required=True, help="Expected workflow checkpoint revision")
    advance.add_argument("--to", required=True, help="One next step returned by the current method")
    advance.add_argument("--readback", help="Rechecked owning operation revision when it changed")
    advance.add_argument("--handoff-revision", required=True, help="Current reviewed handoff revision")


def run(root, args):
    if args.wf_operation == "start":
        result = checkpoints.start(root, args.route, args.handoff, args.scope, args.revision)
    elif args.wf_operation == "show":
        from oryx.workspace.storage import json_input
        inputs = None
        if args.with_inputs:
            raw = sys.stdin.buffer.read(131073)
            if len(raw) > 131072:
                raise ValueError("Workflow context envelope exceeds 128 KiB")
            inputs = json_input(raw)
            if not isinstance(inputs, dict):
                raise ValueError("Supply a workflow context envelope")
        result = checkpoints.show(root, args.identifier, args.scope, inputs=inputs)
    else:
        result = checkpoints.advance(root, args.identifier, args.scope, args.expect, args.to, args.handoff_revision, args.readback)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
