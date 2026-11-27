"""Workspace setup and housekeeping through the same operations used by the PM CLI."""
import json
import os

import onboarding
import storage
import workspace


def register(commands):
    parser = commands.add_parser("valet", help="Inspect or prepare the selected Workspace")
    actions = parser.add_subparsers(dest="operation")
    actions.add_parser("status", help="Inspect installation, selected Workspace and next setup step")
    setup = actions.add_parser("setup", help="Initialize the selected Workspace and inspect the next step")
    setup.add_argument("--owner", required=True)
    setup.add_argument("--delivery-system", default="Delivery workspace")
    reviews = actions.add_parser("reviews", help="Discover personal reviews or reviews in an enrolled scope")
    reviews.add_argument("--scope")
    reviews.add_argument("--github", action="store_true", help="Read open pull requests from the enrolled GitHub scope")
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


def run(root, args):
    if args.operation == "git":
        # The primary CLI performs the same pre-push validation and post-pull alignment.
        return ["git", "workspace", args.operation_name]
    if args.operation == "setup":
        workspace.initialise(root, args.owner, args.delivery_system)
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
