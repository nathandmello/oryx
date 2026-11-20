"""Resolve private templates, roadmap projections and typed metadata at their consumers."""

from copy import deepcopy
from datetime import date
from html import escape
from graphlib import CycleError, TopologicalSorter
import hashlib
import json
import math
import sys
from urllib.parse import quote

import layout
import storage
import studio_layout

FILE = studio_layout.SETTINGS
DEFAULTS = "playbook/customization-defaults.json"


def merge(base, patch, path=()):
    """Merge settings, preserving inherited properties outside the edited choice."""
    if not isinstance(patch, dict):
        return deepcopy(patch)
    result = deepcopy(base) if isinstance(base, dict) else {}
    if len(path) == 3 and path[0] == "templates":
        # Prompts and literal Markdown are alternate bodies of the same section.
        if "prompt" in patch and patch["prompt"] is not None and "content" not in patch:
            result.pop("content", None)
        if "content" in patch and patch["content"] is not None and "prompt" not in patch:
            result.pop("prompt", None)
        if patch.get("mode") in ("append", "replace") and "before" not in patch:
            result.pop("before", None)
        if patch.get("before") is not None and "mode" not in patch:
            result["mode"] = "add"
    if len(path) == 2 and path[0] == "fields" and patch.get("type") in ("text", "number", "boolean", "date") and "choices" not in patch:
        result.pop("choices", None)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            child = () if path == ("products",) else (*path, key)
            result[key] = merge(result.get(key), value, child)
    return result


def keys(value, allowed, label):
    if not isinstance(value, dict) or value.keys() - set(allowed):
        raise ValueError(f"Review the supported properties of {label}")
    return value


def line(value):
    return isinstance(value, str) and value.strip() == value and bool(value) and len(value.splitlines()) == 1


def strings(values, label):
    if not isinstance(values, list) or not all(map(line, values)) or len(set(values)) != len(values):
        raise ValueError(f"Use a list of distinct names for {label}")
    return values


def read(root):
    path = studio_layout.location(storage.private_root(root), FILE)
    if path.resolve() != path or path.exists() and not path.is_file():
        raise ValueError(f"Use a regular private {FILE}")
    raw = path.read_text(encoding="utf-8") if path.exists() else None
    state = storage.json_input(raw) if raw is not None else {"version": 1, "config": {}, "values": {}, "retired": []}
    if (not isinstance(state, dict) or state.keys() - {"version", "config", "values", "retired", "field_contracts"}
            or not {"version", "config", "values", "retired"} <= state.keys()
            or type(state["version"]) is not int or state["version"] != 1
            or not isinstance(state["config"], dict) or not isinstance(state["values"], dict)
            or not isinstance(state["retired"], list) or not isinstance(state.get("field_contracts", {}), dict)):
        raise ValueError(f"Unsupported {FILE} format. Preserve it and inspect its version.")
    return raw, state


def revision(raw):
    return hashlib.sha256((raw or "").encode()).hexdigest()


def config_revision(root, raw):
    import records
    digest = hashlib.sha256((raw or "").encode())
    paths = ["playbook/release.json", DEFAULTS, "templates/views/roadmap.json", "templates/launch-checklist.json",
             *(f"templates/{kind}.md" for kind in records.KINDS)]
    for name in paths:
        path = root / name
        if path.resolve() != path or not path.is_file():
            raise ValueError(f"Missing or unsafe core input: {name}")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def core(root):
    path = root / DEFAULTS
    if path.resolve() != path:
        raise ValueError("Use regular core customization defaults")
    return storage.json_input(path.read_text(encoding="utf-8"))


def checkpoint_settings(base, local):
    if not isinstance(base, dict) or not isinstance(local, dict):
        raise ValueError("Use a map of launch starter checkpoints")
    settings = merge(base, local)
    for key, change in local.items():
        if isinstance(change, dict) and change and "omit" not in change:
            settings[key].pop("omit", None)
    return settings


SCOPED = ("templates", "default_view", "checkpoints")


def resolve_layers(base, local):
    config = merge(base, local)
    config["checkpoints"] = checkpoint_settings(base.get("checkpoints", {}), local.get("checkpoints", {}))
    shared = {key: base[key] for key in SCOPED if key in base}
    private = {key: local[key] for key in SCOPED if key in local}
    owners = [layer.get("products", {}) for layer in (base, local)]
    if not all(isinstance(products, dict) for products in owners):
        raise ValueError("Supply product settings by product slug")
    config["products"] = {}
    for product in dict.fromkeys([*owners[0], *owners[1]]):
        scoped = shared
        inherited, personal = (keys(products.get(product, {}), SCOPED, "product settings") for products in owners)
        for layer in (inherited, private, personal):
            checkpoints = checkpoint_settings(scoped.get("checkpoints", {}), layer.get("checkpoints", {}))
            scoped = merge(scoped, layer)
            scoped["checkpoints"] = checkpoints
        config["products"][product] = scoped
    return config


def for_product(config, product):
    return config["products"].get(product, config)


def effective(root, state):
    config = resolve_layers(core(root), state["config"])
    fields = config.get("fields")
    local = state["config"].get("fields", {})
    if not isinstance(fields, dict) or not isinstance(local, dict):
        return config  # Schema validation will identify the malformed map.
    # A later release may remove or retype a core field which owns live private
    # values. Keep its last usable definition until the PM migrates those values.
    for key, previous in state.get("field_contracts", {}).items():
        if not isinstance(previous, dict):
            raise ValueError("Invalid saved field contract")
        override = local.get(key, {})
        if not isinstance(override, dict) or "type" in override or "choices" in override:
            continue
        current = fields.get(key)
        if (not current or current.get("type") != previous.get("type")
                or set(previous.get("choices", [])) - set(current.get("choices", []))):
            fields[key] = merge(previous, override)
    return config


def template_text(kind, text, sections, *, notices=None, previous=None):
    import opportunities
    import records
    if not isinstance(sections, dict):
        raise ValueError("Use a map of template sections")
    dependencies = {}
    for name, change in sections.items():
        keys(change, ("mode", "prompt", "content", "before"), "template sections")
        anchor = change.get("before", "Work state")
        if not line(anchor):
            raise ValueError("Give each template anchor a section heading")
        dependencies[name] = [anchor] if anchor in sections and change.get("mode", "add") == "add" else []
    try:
        ordered = list(TopologicalSorter(dependencies).static_order())
    except CycleError:
        raise ValueError("Template section anchors form a cycle") from None
    # Detach positioned sections together. An upstream release can introduce
    # the same heading elsewhere, including several siblings at one anchor.
    positioned = {}
    for name, start, _, end in reversed(records.section_blocks(text)):
        if name in sections and sections[name].get("mode", "add") == "add":
            if name in positioned:
                raise ValueError(f"Use one template section named {name}")
            positioned[name] = text[start:end]
            text = text[:start] + text[end:]
    for name in ordered:
        change = sections[name]
        mode, prompt = change.get("mode", "add"), change.get("prompt")
        if not line(name) or mode not in ("add", "append", "replace"):
            raise ValueError("Give each template section a heading and valid mode")
        if ("prompt" in change) == ("content" in change):
            raise ValueError("Choose either a draft prompt or Markdown content")
        if "content" in change:
            body = change["content"]
            if (not isinstance(body, str) or not body.strip() or "<!-- pm:" in body
                    or records.section_blocks(body) or kind in records.CONTEXT_KINDS):
                raise ValueError("Use Markdown content inside one work section. Use a prompt for governed context.")
            body = body.strip()
            if kind == "discovery-brief" and any(row.startswith("## ") for row in body.splitlines()):
                raise ValueError("Indent example headings in a Discovery Brief, including inside code or comments")
            if kind in opportunities.BRIEFS and name in opportunities.REQUIRED_SECTIONS[kind]:
                generated = {"{{owner}}", "{{title}}", "{{id}}", "{{initiative_id}}", "{{date and result}}"}
                if not set(records.PLACEHOLDER.findall(body)) - generated:
                    body += "\n\n{{Review and complete this section for the initiative.}}"
        else:
            if not line(prompt) or any(x in prompt for x in ("{{", "}}", "<!--")):
                raise ValueError("Supply a single-line draft prompt")
            body = "{{" + prompt + "}}"
        if name in records.CONTEXT_RESERVED_SECTIONS | {"Parent initiative"}:
            raise ValueError(f"{name} belongs to the core record contract")
        if kind in records.CONTEXT_KINDS and name in records.CONTEXT_TABLES:
            raise ValueError(f"{name} uses a fixed evidence table")
        blocks = {heading: (start, body, end) for heading, start, body, end in records.section_blocks(text)}
        prior = (previous or {}).get(name, {})
        missing_target = mode != "add" and name not in blocks
        if missing_target and "before" not in change and (notices is not None or prior.get("mode") == mode):
            if notices is not None:
                notices.append(f"Studio placed {name} before Work state because its original section is missing.")
            mode = "add"
        if mode == "add":
            anchor = change.get("before", "Work state")
            if anchor not in blocks:
                same_position = (isinstance(prior, dict) and bool(prior) and prior.get("mode", "add") == "add"
                                 and prior.get("before", "Work state") == anchor)
                if "Work state" not in blocks or (not same_position and notices is None):
                    raise ValueError(f"Missing template anchor {anchor} for {name}")
                if notices is not None:
                    notices.append(f"Studio placed {name} before Work state because the saved heading {anchor} is missing.")
                anchor = "Work state"
            if kind in records.CONTEXT_KINDS:
                if missing_target:
                    lead = records.CONTEXT_LEADS.get(name, "Consult when reviewing evidence for this section.")
                    body = f"{records.CONTEXT_LEAD}\n{lead}\n\n{body}"
                elif not records.valid_context_lead(prompt):
                    raise ValueError("Supply a concrete section lead for a context template")
                else:
                    body = records.CONTEXT_LEAD + "\n" + prompt + "\n\n{{Record sourced findings.}}"
            where = blocks[anchor][0]
            block = positioned.get(name, "")
            if not block or records.section(block, name).strip() != body:
                block = f"## {name}\n\n{body}\n\n"
            text = text[:where] + block + text[where:]
        else:
            if name not in blocks or "before" in change:
                raise ValueError(f"Choose an existing section for {mode}: {name}")
            _, start, end = blocks[name]
            old = text[start:end].strip()
            if mode == "replace" and kind in records.CONTEXT_KINDS:
                lead, _ = records.split_context_lead(old)
                if lead is not None:
                    body = f"{records.CONTEXT_LEAD}\n{lead}\n\n{body}"
            if mode == "replace" and old == body:
                continue
            if mode == "append":
                if old == body or old.endswith("\n\n" + body):
                    continue
                # If core inserted the same paragraphs earlier, retain one
                # copy at the requested end, preserving the other paragraphs.
                remaining = ("\n\n" + old + "\n\n").replace("\n\n" + body + "\n\n", "\n\n").strip()
                body = "\n\n".join(part for part in (remaining, body) if part)
            text = text[:start] + "\n" + body + "\n\n" + text[end:]
    if kind == "prioritization" and "Comparison" in sections:
        _, errors = records.table(text, "Comparison", opportunities.COMPARISON_COLUMNS)
        if errors:
            raise ValueError("Keep the planning comparison table with its initiative ID and assessment columns")
    return text


def draft_template(root, kind, target, text, *, notices=None):
    import records
    config = effective(root, read(root)[1])
    parts = target.relative_to(storage.private_root(root)).parts
    if len(parts) >= 4 and (parts[:2] == ("context", "products")
                            or parts[0] == "workspace" and parts[1] in {"initiatives", "roadmaps", "experiments", "backlogs"}):
        config = for_product(config, parts[2])
    sections = config["templates"].get(kind, {})
    messages = []
    draft = template_text(kind, text, sections, notices=messages)
    if notices is not None:
        notices.extend(messages)
    native = {name for name, *_ in records.section_blocks(text)}
    positioned = [quote(name, safe="") for name, change in sections.items() if change.get("mode", "add") == "add" or name not in native]
    if positioned:
        preamble, separator, rest = draft.partition("\n## ")
        notes = "".join(f"> {message}\n\n" for message in messages)
        draft = preamble.rstrip("\n") + "\n\n" + notes + "<!-- studio:positioned " + ",".join(positioned) + " -->\n" + separator + rest
    return draft


def field_value(field, value):
    kind = field["type"]
    if kind == "number":
        valid = type(value) in (int, float) and (type(value) is int or math.isfinite(value))
    elif kind == "boolean":
        valid = type(value) is bool
    elif kind == "multiple":
        valid = isinstance(value, list) and all(isinstance(v, str) and v in field["choices"] for v in value)
        valid = valid and len(set(value)) == len(value)
    elif kind == "choice":
        valid = value in field["choices"]
    elif kind == "text":
        valid = isinstance(value, str) and bool(value.strip()) and "\x00" not in value
    else:
        valid = line(value)
        if valid and kind == "date":
            try:
                valid = date.fromisoformat(value).isoformat() == value
            except ValueError:
                valid = False
    if not valid:
        raise ValueError(f"Invalid {kind} value for {field['label']}")


def columns(core_columns, fields, view):
    available = {**core_columns, **{key: field["label"] for key, field in fields.items()}}
    order = strings(view.get("columns", ["*"]), "columns")
    hidden = strings(view.get("hidden", []), "hidden fields")
    labels = view.get("labels", {})
    if not isinstance(labels, dict) or not all(map(line, labels.values())):
        raise ValueError("Give column labels single-line names")
    if (set(order) - {"*"} | set(hidden) | set(labels)) - available.keys():
        raise ValueError("View refers to an unknown field")
    available.update(labels)
    result = {}
    for key in order:
        for field in ([k for k in available if k not in order] if key == "*" else [key]):
            if field not in hidden:
                result[field] = available[field]
    if not result:
        raise ValueError("Keep at least one visible roadmap column")
    return result


def validate(root, state, *, system_only=False, previous=None):
    import initiative_views
    import records
    config = resolve_layers(core(root), {}) if system_only else effective(root, state)
    keys(config, ("templates", "fields", "views", "default_view", "products", "checkpoints"), "customizations")
    for key in ("templates", "fields", "views"):
        if not isinstance(config.get(key), dict):
            raise ValueError(f"Use an object for {key}")
    products = config.get("products", {})
    if not isinstance(products, dict):
        raise ValueError("Supply product settings by product slug")
    import initiative_work
    if "checkpoints" in config:
        initiative_work.template(root, config["checkpoints"])
    templates = [(None, config["templates"])]
    for slug, settings in products.items():
        layout.slug(slug)
        keys(settings, ("templates", "default_view", "checkpoints"), "product settings")
        if "default_view" in settings and (not isinstance(settings["default_view"], str)
                or settings["default_view"] not in {"standard", *config["views"]}):
            raise ValueError(f"Choose an available default view for {slug}")
        if "checkpoints" in settings:
            initiative_work.template(root, settings["checkpoints"])
        specific = settings.get("templates", {})
        if not isinstance(specific, dict):
            raise ValueError("Use a template map for product-specific drafts")
        templates.append((slug, specific))
    for product, kinds in templates:
        for kind, sections in kinds.items():
            if kind not in records.KINDS:
                raise ValueError(f"Unknown template: {kind}")
            source = root / "templates" / f"{kind}.md"
            old = for_product(previous, product)["templates"] if previous is not None else {}
            try:
                template_text(kind, source.read_text(encoding="utf-8"), sections, previous=old.get(kind))
            except ValueError:
                # A renamed core heading can strand an old override. Only a change
                # to its effective instructions has to resolve it in this transaction.
                if previous is None:
                    raise
                if not isinstance(old, dict) or old.get(kind) != sections:
                    raise
    fields = config["fields"]
    for key, field in fields.items():
        if not key.startswith("x-"):
            raise ValueError("Use x- followed by a stable slug for a workspace field")
        layout.slug(key)
        keys(field, ("label", "type", "choices"), "roadmap fields")
        if not line(field.get("label")) or field.get("type") not in ("text", "number", "date", "boolean", "choice", "multiple"):
            raise ValueError(f"Choose a label and supported field type for {key}")
        if field["type"] in ("choice", "multiple"):
            if not strings(field.get("choices"), key):
                raise ValueError("Supply at least one choice")
        elif "choices" in field:
            raise ValueError("Choices apply only to choice fields")
    core_columns = initiative_views.view_template(root, "roadmap")["columns"]
    for name, view in config["views"].items():
        layout.slug(name)
        if name == "core":
            raise ValueError("The core view is reserved for the original roadmap")
        keys(view, ("title", "layout", "group", "columns", "hidden", "labels", "density", "page"), "roadmap views")
        if (not line(view.get("title", name)) or view.get("layout", "board") not in ("board", "table")
                or view.get("density", "normal") not in ("normal", "compact")
                or not isinstance(view.get("group", "horizon"), str)
                or view.get("group", "horizon") not in {*core_columns, *fields, "none"}):
            raise ValueError(f"Invalid roadmap view: {name}")
        if "page" in view:
            if system_only:
                raise ValueError("Keep workspace HTML pages in private view definitions")
            page = layout.slug(view["page"])
            prior_views = previous.get("views", {}) if previous else {}
            prior = prior_views.get(name, {}) if isinstance(prior_views, dict) else {}
            if not isinstance(prior, dict) or prior.get("page") != page:
                page_template(root, page)
        columns(core_columns, fields, view)
    if not isinstance(config.get("default_view"), str) or config["default_view"] not in {"standard", *config["views"]}:
        raise ValueError("Choose an available default view")
    if system_only:
        return config
    for product, initiatives in state["values"].items():
        layout.slug(product)
        if not isinstance(initiatives, dict):
            raise ValueError("Group roadmap values by product and initiative")
        for identifier, values in initiatives.items():
            if not line(identifier) or not isinstance(values, dict):
                raise ValueError("Use a field map for each initiative ID")
            for key, value in values.items():
                if key not in fields:
                    raise ValueError(f"Field {key} still has values. Hide it or explicitly clear its values first.")
                field_value(fields[key], value)
    return config


def report_ids(root):
    _, state = read(root)
    return [category + "/" + key for category in ("templates", "fields", "views", "products", "checkpoints")
            for key in state["config"].get(category, {})] + (["default_view"] if "default_view" in state["config"] else [])


def report_source(root, identifier):
    _, state = read(root)
    category, _, key = identifier.partition("/")
    if key and category in ("templates", "fields", "views", "products", "checkpoints"):
        value = state["config"].get(category, {}).get(key)
    elif identifier == "default_view":
        value = state["config"].get(category)
    else:
        return None
    if value is None:
        return None
    return revision(json.dumps(value, sort_keys=True, ensure_ascii=True))


def snapshot(root):
    raw, state = read(root)
    return {"revision": config_revision(root, raw), "config": state["config"], "effective": effective(root, state),
            "values": state["values"], "retired": state["retired"]}


def apply(root, request):
    import initiative_store
    import workspace
    keys(request, ("revision", "config", "values"), "customization changes")
    private = workspace.repo(root, "workspace")
    workspace.settings(root)
    with storage.writer_lock(private):
        raw, state = read(root)
        if request.get("revision") != config_revision(root, raw):
            raise ValueError("Customizations changed. Reload and reapply the intended changes.")
        patch = request.get("config", {})
        keys(patch, ("templates", "fields", "views", "default_view", "products", "checkpoints"), "customization changes")
        previous = effective(root, state)
        state["config"] = merge(state["config"], patch)
        edits = request.get("values", [])
        if not isinstance(edits, list):
            raise ValueError("Supply a list of field value edits")
        registers = {}
        for edit in edits:
            keys(edit, ("product", "id", "field", "value"), "field updates")
            if set(edit) != {"product", "id", "field", "value"}:
                raise ValueError("Supply product, id, field and value")
            product, identifier, key = layout.slug(edit["product"]), edit["id"], layout.slug(edit["field"])
            if not line(identifier):
                raise ValueError("Supply a stable initiative ID")
            if edit["value"] is not None:
                if product not in registers:
                    registers[product] = initiative_store.read(root, product)[2]
                if identifier not in registers[product].items:
                    raise ValueError("Unknown initiative in this product")
            values = state["values"].setdefault(product, {}).setdefault(identifier, {})
            if edit["value"] is None:
                values.pop(key, None)
            else:
                values[key] = edit["value"]
            if not values:
                del state["values"][product][identifier]
            if not state["values"][product]:
                del state["values"][product]
        used = {key for initiatives in state["values"].values() for values in initiatives.values() for key in values}
        state["field_contracts"] = {key: field for key, field in state.get("field_contracts", {}).items() if key in used}
        requested_fields = patch.get("fields", {})
        if isinstance(requested_fields, dict):
            for key, requested in requested_fields.items():
                if requested is None:
                    state["field_contracts"].pop(key, None)
        config = validate(root, state, previous=previous)
        inherited = core(root)["fields"]
        for key in used & inherited.keys():
            state["field_contracts"][key] = config["fields"][key]
        if config_revision(root, raw) != request["revision"]:
            raise ValueError("Core changed during this edit. Reload and review your changes.")
        next_revision = config_revision(root, encode(state))
        save(private, raw, state)
        result = {"revision": next_revision}
        if patch:
            import overrides
            try:
                reporting = overrides.read(private)[1]["reporting"]
            except (OSError, ValueError):
                result["feedback"] = "Customization saved. Review private override reporting settings."
                reporting = False
            if reporting:
                result["feedback"] = "Use the workspace reporting workflow for the public requirement."
                result["report_ids"] = report_ids(root)
        return result


def encode(state):
    return json.dumps(state, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def save(private, raw, state):
    path = studio_layout.location(private, FILE)
    storage.require_visible(private, path.relative_to(private))
    storage.replace_text(path, raw, encode(state))


def reconcile(root, release, apply_changes):
    raw, state = read(root)
    if not state["config"]:
        return []
    validate(root, state)
    # One instruction is one template section, checklist checkpoint, field,
    # named view or default selection. Keep product scopes independent.
    config = state["config"]
    batches = []
    def collect(settings, prefix=()):
        for kind, sections in settings.get("templates", {}).items():
            siblings = {}
            for name, change in sections.items():
                if change.get("mode", "add") == "add":
                    anchor = change.get("before", "Work state")
                    seen = {name}
                    while anchor not in seen and anchor in sections and sections[anchor].get("mode", "add") == "add":
                        seen.add(anchor)
                        anchor = sections[anchor].get("before", "Work state")
                    siblings.setdefault(anchor, []).append(name)
            # Adjacent sections anchored together can be redundant as a group
            # even when removing either one alone would change their order.
            template = prefix + ("templates", kind)
            batches.extend((template, names) for names in siblings.values() if len(names) > 1)
            batches.extend((template, [name]) for name in sections)
        for category in ("fields", "views", "checkpoints"):
            batches.extend((prefix + (category,), [key]) for key in settings.get(category, {}))
        if "default_view" in settings:
            batches.append((prefix, ["default_view"]))
    collect(config)
    for product, settings in config.get("products", {}).items():
        collect(settings, ("products", product))

    def outcome(candidate, path, *, core_only=False):
        import initiative_work
        basis = {**state, "config": candidate}
        if core_only:
            basis["field_contracts"] = {}
        resolved = effective(root, basis)
        if path[0] == "products":
            selected = [for_product(resolved, path[1])]
            path = path[2:]
        else:
            selected = [resolved, *resolved["products"].values()]
        category = path[0]
        if category in ("fields", "views"):
            return resolved[category].get(path[1])
        if category == "default_view":
            return [scope[category] for scope in selected]
        results = []
        for scope in selected:
            if category == "templates":
                kind = path[1]
                sections = scope["templates"].get(kind, {})
                source = (root / "templates" / (kind + ".md")).read_text(encoding="utf-8")
                results.append(template_text(kind, source, sections))
            else:
                results.append(initiative_work.template(root, scope["checkpoints"]))
        return results

    retired = {}
    for prefix, names in batches:
        trial = deepcopy(config)
        isolated = {}
        node, cursor = trial, isolated
        parents = []
        for key in prefix:
            parents.append((node, key))
            node = node.get(key, {})
            cursor = cursor.setdefault(key, {})
        if not all(name in node for name in names):
            continue  # Already retired with a group at this scope.
        for name in names:
            cursor[name] = node.pop(name)
        for parent, key in reversed(parents):
            if not parent[key]:
                del parent[key]
        path = prefix + (names[0],)
        before = outcome(config, path)
        try:
            # A different private rule (or a recovery contract) must never be
            # mistaken for the new release supplying this behavior itself.
            if outcome(isolated, path, core_only=True) != outcome({}, path, core_only=True):
                continue
            if before != outcome(trial, path):
                continue
        except ValueError:
            continue  # Another private rule still depends on this declaration.
        archived = retired
        for key in prefix:
            archived = archived.setdefault(key, {})
        archived.update(cursor)
        config = trial
    if retired and apply_changes:
        state["config"] = config
        final = validate(root, state)
        for key in retired.get("fields", {}):
            if any(key in values for initiatives in state["values"].values() for values in initiatives.values()):
                state.setdefault("field_contracts", {})[key] = final["fields"][key]
        state["retired"].append({"release": release, "config": retired})
        save(storage.private_root(root), raw, state)
    return list(retired)


def projection(root, rows, name=None, *, product=None):
    import initiative_views
    base = initiative_views.view_template(root, "roadmap")
    if name == "core":
        names = {"core": "Core roadmap", "standard": "Workspace roadmap"}
        try:
            current = effective(root, read(root)[1])
            names.update({key: item.get("title", key) for key, item in current.get("views", {}).items()
                          if isinstance(item, dict)})
        except (ValueError, OSError, AttributeError):
            pass  # Keep the original view available while a PM repairs configuration.
        return {**base, "name": "core", "layout": "board", "group": "horizon", "density": "normal",
                "custom": False, "views": names,
                "fields": {}, "revision": None, "page": None}
    raw, state = read(root)
    config = effective(root, state)
    if name is None:
        name = for_product(config, product)["default_view"]
    if not isinstance(name, str) or name not in {"standard", *config["views"]}:
        raise ValueError(f"Unknown roadmap view: {name}")
    view = config["views"].get(name, {})
    labels = columns(base["columns"], config["fields"], view)
    for row in rows:
        stored = state["values"].get(row["product"], {}).get(row["id"], {})
        row.update({key: stored.get(key) for key in config["fields"]})
    group = view.get("group", "horizon")
    return {"name": name, "title": view.get("title", base["title"]), "columns": labels,
            "layout": view.get("layout", "board"), "group": "none" if group in view.get("hidden", []) else group,
            "density": view.get("density", "normal"), "custom": bool(view or config["fields"]),
            "views": {**({"core": "Core roadmap"} if config["views"] or config["fields"] else {}),
                      **{key: config["views"].get(key, {}).get("title", key) for key in dict.fromkeys(["standard", *config["views"]])}},
            "page": view.get("page"), "fields": config["fields"], "revision": config_revision(root, raw)}


def page_template(root, name):
    name = layout.slug(name)
    path = studio_layout.location(storage.private_root(root), studio_layout.VIEWS) / (name + ".html")
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"Supply a regular customizations/views/{name}.html file")
    storage.require_visible(storage.private_root(root), path.relative_to(storage.private_root(root)))
    source = path.read_text(encoding="utf-8")
    if source.count("<!-- pm:roadmap-data -->") != 1:
        raise ValueError("Include one <!-- pm:roadmap-data --> placeholder in the standalone page")
    return source


def page(root, view, rows, *, expected_page=None):
    labels = view["columns"]
    data = [{key: row[key] for key in labels} for row in rows]
    if view["page"]:
        source = page_template(root, view["page"])
        if expected_page is not None and revision(source) != expected_page:
            raise ValueError("The custom page changed. Refresh the roadmap before exporting.")
        payload = json.dumps({"columns": labels, "rows": data}, ensure_ascii=True).replace("<", "\\u003c")
        return source.replace("<!-- pm:roadmap-data -->", '<script type="application/json" id="pm-roadmap">' + payload + '</script>')
    from initiative_views import cell
    headers = "".join("<th>" + escape(label) + "</th>" for label in labels.values())
    body = "".join("<tr>" + "".join("<td>" + escape(cell(row[key])) + "</td>" for key in labels) + "</tr>" for row in data)
    return ('<!doctype html><meta charset="utf-8"><title>' + escape(view["title"])
            + "</title><h1>" + escape(view["title"]) + "</h1><table><thead><tr>" + headers
            + "</tr></thead><tbody>" + body + "</tbody></table>")


def add_commands(commands):
    parser = commands.add_parser("customize", help="Manage workspace templates, roadmap views and custom fields")
    parser.add_argument("operation", choices=("show", "apply"))


def run(root, args):
    if args.operation == "show":
        return snapshot(root)
    return apply(root, storage.json_input(sys.stdin.read()))
