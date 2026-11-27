"""Create or restore an offline local Workspace backup in a separate private directory."""

import argparse
import json
import subprocess
import sys
import zipfile
import zlib

from . import snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    inspect = actions.add_parser("inventory", help="Print a private, read-only filesystem inventory")
    inspect.add_argument("workspace")
    for name, source in (("backup", "workspace"), ("restore", "archive")):
        operation = actions.add_parser(name, help="Write a verified copy at a previously unused location")
        operation.add_argument(source)
        operation.add_argument("destination")
        operation.add_argument("--expect", required=True, help="SHA-256 of the independently retained inventory")
    args = parser.parse_args(argv)
    try:
        snapshot.require_pm_terminal()
        if args.action == "inventory":
            manifest = snapshot.inspect(args.workspace)
            result = {"digest": snapshot.digest(manifest), "inventory": manifest}
        elif args.action == "backup":
            result = snapshot.backup(args.workspace, args.destination, args.expect)
        else:
            result = snapshot.restore(args.archive, args.destination, args.expect)
    except (KeyError, TypeError, ValueError, OSError, RuntimeError, subprocess.SubprocessError,
            zipfile.BadZipFile, zlib.error) as error:
        print(f"Recovery held: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
