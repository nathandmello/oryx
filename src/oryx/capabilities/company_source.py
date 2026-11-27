"""Import one versioned company workflow source into the PM's Studio."""

import json
from pathlib import Path
import stat

import layout
import storage
import workspace


FILE = "customizations/company.json"


class NewerFormat(ValueError):
    """A later version of oryx must read this file before an import can compare revisions."""


def parse(text):
    # Overrides use workflow_rules() below when assembling the three layers.
    from overrides import validate_rules

    try:
        bundle = storage.json_input(text)
    except RecursionError as exc:
        raise ValueError("Company workflow JSON exceeds supported nesting") from exc
    if isinstance(bundle, dict) and type(bundle.get("format")) is int and bundle["format"] > 1:
        raise NewerFormat("A newer version of oryx must read this company source format")
    if not isinstance(bundle, dict) or set(bundle) != {"format", "id", "revision", "rules"}:
        raise ValueError("A company source needs format, id, revision, and rules")
    if type(bundle["format"]) is not int or bundle["format"] != 1:
        raise ValueError("Expected company source format 1")
    layout.slug(bundle["id"])
    if type(bundle["revision"]) is not int or bundle["revision"] < 1:
        raise ValueError("Use a positive integer company revision")
    validate_rules(bundle["rules"])
    return bundle


def installed_path(studio):
    path = studio / FILE
    try:
        resolved = path.resolve()
    except RuntimeError as exc:  # pathlib reports symlink loops this way before Python 3.13.
        raise ValueError("Use a regular company source file inside Studio") from exc
    if resolved != path or path.parent.exists() and not path.parent.is_dir():
        raise ValueError("Use a regular company source file inside Studio")
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return path
    if not stat.S_ISREG(mode):
        raise ValueError("Use a regular company source file inside Studio")
    return path


def read(studio, *, repair=False):
    path = installed_path(studio)
    try:
        original = path.read_bytes()
    except FileNotFoundError:
        return None, None
    try:
        return original, parse(original.decode("utf-8"))
    except NewerFormat:
        raise
    except ValueError:
        if not repair:
            raise
        return original, None


def workflow_rules(root):
    _, bundle = read(storage.private_root(root))
    return bundle["rules"] if bundle is not None else {}


def inspection(root):
    """Keep an absent optional source distinct from a damaged installed copy."""
    try:
        return read(storage.private_root(root))[1], None
    except NewerFormat:
        return None, ("Company workflows unavailable. Update oryx to read the newer company source format, "
                      "or detach the source with pm.py company remove.")
    except (OSError, ValueError):
        return None, (f"Company workflows unavailable. The installed file at {FILE} could not be read or validated. "
                      "Run pm.py company show for the error. "
                      "Restore a known company file with pm.py company import PATH, "
                      "or detach the source with pm.py company remove.")


def install(studio, text):
    bundle = parse(text)
    with storage.writer_lock(studio):
        original, current = read(studio, repair=True)
        if current is not None:
            if bundle["id"] != current["id"]:
                raise ValueError("Remove the installed company source before switching its id")
            if bundle["revision"] < current["revision"]:
                raise ValueError("The installed company revision is newer")
            if bundle["revision"] == current["revision"]:
                if bundle != current:
                    raise ValueError("A company revision must have identical content on every import")
                return {"changed": False, "id": current["id"], "revision": current["revision"]}
        storage.require_visible(studio, FILE)
        candidate = json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"
        storage.replace_text(installed_path(studio), original, candidate)
        result = {"changed": True, "id": bundle["id"], "revision": bundle["revision"]}
        if original is not None and current is None:
            result["repaired"] = True
        return result


def add_commands(commands):
    company = commands.add_parser("company", help="Manage an optional company workflow source")
    company.set_defaults(hub_action=run)
    operations = company.add_subparsers(dest="operation", required=True)
    operations.add_parser("show", help="Read the installed company source")
    load = operations.add_parser("import", help="Install a company workflow bundle from a local JSON file")
    load.add_argument("path", type=Path)
    operations.add_parser("remove", help="Detach the installed company source")


def run(root, args, prepare_write):
    if args.operation == "show":
        result = read(workspace.repo(root, "workspace"))[1]
    elif args.operation == "import":
        if not args.path.is_file():
            raise ValueError("Choose a local company source JSON file")
        # The supplied path can be inside a checkout that preparation will move.
        text = args.path.read_text(encoding="utf-8")
        parse(text)
        prepare_write(root)
        result = install(workspace.repo(root, "workspace"), text)
    else:
        prepare_write(root)
        studio = workspace.repo(root, "workspace")
        with storage.writer_lock(studio):
            path = installed_path(studio)
            result = {"removed": path.exists()}
            path.unlink(missing_ok=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
