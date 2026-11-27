"""Keep editable experiment plans linked to approved initiative and metric identities."""

import json

from oryx.capabilities.initiative_events import FIELDS, VALIDATORS, linked
import layout
import storage

APPROVAL = {"initiative": "initiative ID", "metric": "slug"}
DETAILS = ("hypothesis", "method", "criterion", "planned_on", "source")


def folder(private, product, item):
    home = private / layout.experiment_draft_home(product, item["id"].split("/")[1])
    if home.resolve() != home:
        raise ValueError("Use a regular experiment draft directory")
    return home


def filename(metric):
    return f"experiment.{layout.slug(metric)}.draft.json"


def identity(item, metric):
    return {"initiative": item["id"], "metric": metric, "experiment": "experiment." + metric}


def lookup(register, identifier, metric):
    if not VALIDATORS["initiative ID"](identifier) or not VALIDATORS["slug"](metric):
        raise ValueError("Supply the registered initiative ID and product metric slug")
    return linked(register.items, identifier, "initiative in this product"), linked(register.metrics, metric, "product metric")


def read(path, item, metric):
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"Expected a regular draft file at {path.name}")
    draft = storage.json_input(path.read_text(encoding="utf-8"))
    keys = identity(item, metric)
    if (not isinstance(draft, dict) or draft.keys() - keys.keys() - set(DETAILS)
            or any(draft.get(key) != value for key, value in keys.items())):
        raise ValueError(f"{path.name}: keep the original initiative, metric, experiment ID, and supported fields")
    for key in DETAILS:
        if draft.get(key) is None:
            continue
        if not VALIDATORS[FIELDS["experiment"][key]](draft[key]):
            raise ValueError(f"{path.name}: invalid {key}")
        if key == "hypothesis":
            linked(item["hypotheses"], draft[key], "hypothesis in this initiative")
    return draft


def start(private, product, register, identifier, metric):
    item, _ = lookup(register, identifier, metric)
    path = folder(private, product, item) / filename(metric)
    storage.require_visible(private, path.relative_to(private).as_posix())
    if "experiment." + metric in item["experiments"]:
        raise ValueError("This experiment is already approved")
    if path.exists() or path.is_symlink():
        read(path, item, metric)
    else:
        if any(plan["metric"] == metric for plan in item["experiments"].values()):
            raise ValueError("This metric already has an approved experiment. Reuse its experiment ID.")
        draft = {**identity(item, metric), **dict.fromkeys(DETAILS)}
        mode = storage.initiative_mode(path, draft=True)
        storage.replace_text(path, None, json.dumps(draft, indent=2) + "\n", mode=mode)
    return path.relative_to(private).as_posix()


def proposed_plan(private, product, register, request):
    if set(request) != {"type", *APPROVAL}:
        raise ValueError("approve-experiment takes only initiative and metric")
    metric = request["metric"]
    item, _ = lookup(register, request["initiative"], metric)
    path = folder(private, product, item) / filename(metric)
    draft = read(path, item, metric)
    missing = [key for key in DETAILS if draft.get(key) is None]
    if missing:
        raise ValueError(f"{path.name}: complete {', '.join(missing)} before approval")
    return {"type": "experiment", **draft}


def states(private, product, register, item, metrics=None):
    home = folder(private, product, item)
    covered = {event["metric"] for event in item["experiments"].values()}
    if metrics is None:
        metrics = item["targets"].keys() - covered
        for path in home.glob("experiment.*.draft.json"):
            metric = path.name.removeprefix("experiment.").removesuffix(".draft.json")
            if not layout.SLUG.fullmatch(metric) or path.name != filename(metric):
                raise ValueError(f"{path.name}: use experiment.<metric-id>.draft.json in the initiative's experiment folder")
            linked(register.metrics, metric, "product metric")
            metrics.add(metric)
    for metric in sorted(metrics):
        path = home / filename(metric)
        storage.require_visible(private, path.relative_to(private).as_posix())
        draft = None
        status = "missing file"
        if path.exists() or path.is_symlink():
            draft = read(path, item, metric)
            approved = item["experiments"].get(draft["experiment"])
            if approved and any(draft.get(key) != approved[key] for key in DETAILS):
                raise ValueError(f"{path.name}: draft differs from the approved plan. Review the local edits.")
            if approved or (metric in covered and all(draft.get(key) is None for key in DETAILS)):
                status = "covered"
            else:
                status = "draft"
        elif metric in covered:
            continue
        elif status == "missing file":
            storage.initiative_mode(path, draft=True)
        yield metric, path, draft, status


def pending(private, product, register, transactions=None):
    if transactions is None:
        affected = dict.fromkeys(register.items)
    else:
        affected = {}
        for event in transactions:
            if event["type"] in {"target", "experiment"}:
                affected.setdefault(event["initiative"], set()).add(event["metric"])
    changes = []
    for identifier, metrics in affected.items():
        item = register.items[identifier]
        for metric, path, draft, status in states(private, product, register, item, metrics):
            if status != "draft":
                changes.append((item, metric, path, draft, status))
    return changes


def sync(private, product, register, changes=None):
    """Called with the workspace writer lock. Repeat safely after interruption."""
    if changes is None:
        changes = pending(private, product, register)
    for item, metric, path, draft, status in changes:
        if status == "missing file":
            start(private, product, register, item["id"], metric)
        else:
            if read(path, item, metric) != draft:
                raise ValueError(f"{path.name} changed during draft cleanup")
            path.unlink()


def view(private, product, register, item):
    drafts = {}
    for metric, path, draft, status in states(private, product, register, item):
        if status != "covered":
            drafts[metric] = {
                **(draft or identity(item, metric)), "status": status,
                "path": path.relative_to(private).as_posix(),
                "missing": [key for key in DETAILS if (draft or {}).get(key) is None],
            }
    return drafts


def check(private, product, register):
    for item in register.items.values():
        for _, path, _, status in states(private, product, register, item):
            if status != "draft":
                yield f"{path.relative_to(private)}: {status}. Run initiative sync-drafts {product}."


def misplaced(private, files, registers):
    homes = {folder(private, product, item)
             for product, register in registers.items() for item in register.items.values()}
    for path in files:
        if path.name.startswith("experiment.") and path.name.endswith(".draft.json") and path.parent not in homes:
            if not {"sources", "secrets"}.intersection(path.relative_to(private).parts):
                yield f"{path.relative_to(private)}: place the draft in its registered initiative's experiment folder"
