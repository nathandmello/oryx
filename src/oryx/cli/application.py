"""Dispatch the installed executable and compatible checkout script to the same operations."""
from importlib import import_module
import json
import os
import sys

# Each owner parses the remainder and enforces its own access checks.
OWNERS = {
    "governance": "oryx.governance.cli",
    "sharing": "oryx.sharing.cli",
    "release": "oryx.release.__main__",
    "review": "oryx.review.cli",
    "workspace": "oryx.workspace.operations",
}


def register(commands):
    for name in [*OWNERS, "resource", "recovery"]:
        owner = commands.add_parser(name, add_help=False, help=f"Use the {name} commands")
        owner.add_argument("arguments", nargs="...")
    from oryx.cli import valet
    valet.register(commands)


def dispatch(root, args):
    if args[0] == "resource":
        if args[1:] in (["-h"], ["--help"]):
            print("Usage: oryx resource 'oryx://core/path[#anchor]'")
            return 0
        if len(args) != 2:
            raise ValueError("Supply one oryx://core/ resource reference")
        from oryx.workspace.resources import CoreResources
        from conversion import markdown_anchors
        print(json.dumps(CoreResources(root).resolve(args[1], markdown_anchors)))
        return 0
    if args[0] == "recovery":
        from oryx.recovery.__main__ import main
        return main(args[1:])
    module = import_module(OWNERS[args[0]])
    if args[0] == "workspace":
        return module.main(root, args[1:])
    return module.main(args[1:])


def inspect_action(root, argv):
    if argv[:2] not in (["action", "--describe"], ["action", "--catalog"]):
        return None
    from oryx.cli import catalog
    try:
        catalog.route(root, argv[1:])
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


def main(root):
    discovered = inspect_action(root, sys.argv[1:])
    if discovered is not None:
        return discovered
    # Resolve relative legacy imports from this installation regardless of the invoking directory.
    sys.path.insert(0, os.fspath(root / "tools"))
    from oryx.cli import command
    return command.main()
