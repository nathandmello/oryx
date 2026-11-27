"""Workspace setup and housekeeping through the same operations used by the PM CLI."""
import json
import os

import onboarding
import storage
import workspace

from oryx.governance import cli as governance
from oryx.workspace import connections


def register(commands):
    parser = commands.add_parser("valet", help="Inspect or prepare the selected Workspace")
    actions = parser.add_subparsers(dest="operation")
    actions.add_parser("status", help="Inspect installation, selected Workspace and next setup step")
    setup = actions.add_parser("setup", help="Initialize the selected Workspace and inspect the next step")
    setup.add_argument("--owner", help="Create a local Workspace directly for this owner")
    setup.add_argument("--delivery-system", help="Delivery system for the local --owner setup")
    reviews = actions.add_parser("reviews", help="Discover personal reviews or reviews in an enrolled scope")
    reviews.add_argument("--scope")
    reviews.add_argument("--github", action="store_true", help="Read open pull requests from the enrolled GitHub scope")
    scope = actions.add_parser("scope", help="Create local scopes or use an enrolled customer authority")
    scopes = scope.add_subparsers(dest="scope_operation", required=True)
    scopes.add_parser("list", help="List local scopes and remembered connections in this Workspace")
    create = scopes.add_parser("create", help="Create a local scope independent of remote membership")
    create.add_argument("kind", choices=("company", "function", "team", "user"))
    create.add_argument("--parent", help="ID of the local parent scope")
    for name in ("show", "connect", "sync", "disconnect"):
        action = scopes.add_parser(name, help={"show":"Read current authority and revision",
                                  "connect":"Bind this Workspace to an already enrolled scope",
                                  "sync":"Recheck a connected scope and its current official revision",
                                  "disconnect":"Stop synchronizing this Workspace connection"}[name])
        action.add_argument("scope")
        provider = action.add_mutually_exclusive_group()
        provider.add_argument("--github", action="store_true", help="Use the enrolled GitHub repository")
        if name == "show":
            provider.add_argument("--local", action="store_true", help="Read one local scope by ID")

    github = actions.add_parser("github", help="Run a registered GitHub operation with its ordinary JSON input")
    github.add_argument("github_operation", choices=("status","reviews","policy","verify","record","propose",
                                                     "merge","transfer","reconcile"))
    git = actions.add_parser("git", help="Inspect or synchronize the personal Workspace")
    git.add_argument("operation_name", choices=("status", "fetch", "pull", "push"))


def status(root):
    release = workspace.release(root)
    base = {"core_version": release["system_version"], "workspace_format": release["workspace_format"]}
    if (root / "oryx-release-manifest.json").is_file() and "ORYX_WORKSPACE" not in os.environ:
        return {**base, "workspace": None, "next": "Select an absolute ORYX_WORKSPACE path"}
    selected = workspace.optional_repo(root)
    if selected is None:
        return {**base, "workspace": None, "next": "valet setup --owner NAME"}
    settings = workspace.settings(root, compatible=False)
    state = onboarding.status(selected)
    identifier = None
    if storage.selected_workspace(root) is not None:
        from oryx.workspace.location import workspace_id
        identifier = workspace_id(selected)
    return {**base, "workspace": str(selected), "workspace_id": identifier, "owner": settings["owner"],
            "stage": state["stage"], "ready": state["ready"], "next": state.get("next_action") or "onboarding status"}


def scope_action(args, private):
    action = args.scope_operation
    if action == "list":
        return connections.inventory(private)
    if action == "create":
        payload = {"type":args.kind, **({"parent":args.parent} if args.parent else {})}
        return governance.local_scope(private, payload)

    if action == "show" and args.local:
        for local in connections.local_scopes(private):
            if local["id"] == args.scope:
                return local
        raise ValueError("Unknown local scope in the selected Workspace")

    return connections.manage(private, action, "github" if args.github else "peer", args.scope)


def run(root, args):
    if args.operation == "scope":
        private = governance.private_root(None)
        try:
            result = scope_action(args, private)
        except (KeyError, TypeError, RuntimeError) as exc:
            raise ValueError("The customer authority could not verify the requested scope") from exc
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return None
    if args.operation == "github":
        return ["governance", "github-" + args.github_operation]
    if args.operation == "git":
        # The primary CLI performs the same pre-push validation and post-pull alignment.
        return ["git", "workspace", args.operation_name]
    if args.operation == "setup":
        from oryx.review.store import pm_only
        pm_only()
        if args.owner is None:
            if args.delivery_system is not None:
                raise ValueError("Use --owner with --delivery-system, or enter both in the setup walkthrough")
            from oryx.workflows.first_run import foreground_setup
            foreground_setup(root)
        else:
            workspace.initialise(root, args.owner, args.delivery_system or "Delivery workspace")
    if args.operation == "reviews":
        if not args.scope:
            if args.github:
                raise ValueError("Choose an enrolled scope with --scope")
            return ["review", "status"]
        if args.github:
            from oryx.governance.github import run as github
            reviews = github("github-reviews", {"scope": args.scope})
        else:
            from oryx.governance.client import request
            reviews = request("reviews", {"scope": args.scope})
        print(json.dumps(reviews, indent=2, ensure_ascii=False))
        return None
    print(json.dumps(status(root), indent=2, ensure_ascii=False))
    return None
