"""Select bounded instructions from the trusted method that owns a workflow step."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
import posixpath
import json
import re


@dataclass(frozen=True)
class Step:
    name: str
    file: str
    heading: str
    stop: str
    transitions: tuple


def fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return sha256(payload).hexdigest()


def section(root, step):
    path = root / step.file
    if path.resolve() != path or not path.is_file() or path.stat().st_size > 128 * 1024:
        raise ValueError("The verified workflow method is unavailable")
    return extract(path.read_text(encoding="utf-8"), step.heading, step.file)


def extract(source, wanted, name, *, anchor=False):
    lines = source.splitlines()
    headings = []
    fence = None
    for number, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token.startswith(fence) and not line.strip().strip(token[0]):
                fence = None
            continue
        match = re.fullmatch(r"(#{1,6}) (.+)", line)
        if fence is None and match:
            headings.append((number, len(match[1]), match[2].strip()))
    def label(title):
        return re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-") if anchor else title
    matches = [i for i, (_, _, title) in enumerate(headings) if label(title) == wanted]
    if len(matches) != 1:
        raise ValueError(f"Cannot identify the workflow method section {name}#{wanted}")
    index = matches[0]
    start, level, _ = headings[index]
    # Only the requested step enters model context. Linked methods are not expanded.
    end = next((number for number, depth, _ in headings[index + 1:] if depth <= level), len(lines))
    text = "\n".join(lines[start:end]).strip()
    if len(text.encode()) > 16 * 1024:
        raise ValueError("Workflow method exceeds its step budget; split the method before continuing")
    return text


def prepare(root, command, current=None):
    from .registry import WORKFLOWS
    steps = WORKFLOWS.get(command)
    if steps is None:
        raise ValueError("The guide has no registered Python workflow")
    sections = {step.name: section(root, step) for step in steps}
    version = fingerprint({"engine": 1, "steps": [
        [s.name, s.file, s.heading, s.stop, s.transitions, sections[s.name]] for s in steps
    ]})
    if current == "finish":
        return {"command": command, "version": version, "step": "finish", "status": "complete", "allowed_next": []}
    step = next((s for s in steps if s.name == current), None) if current else steps[0]
    if step is None:
        raise ValueError("The workflow step is unavailable in this release")
    text = sections[step.name]
    return {"command": command, "version": version, "step": step.name, "status": "open",
            "method": {"source": step.file, "heading": step.heading, "text": text,
                       "bytes": len(text.encode()), "words": len(text.split())},
            "stop_when": step.stop, "allowed_next": list(step.transitions)}


INPUT_LIMIT = 65536
BINDING = ("workspace_id", "scope", "id", "revision", "readback_revision")


def measured(payload, observed_bytes=0):
    """Count the actual Core JSON line and already delivered host material in UTF-8."""
    meter = {"bytes": 0, "core_bytes": 0, "supplied_observation_bytes": observed_bytes,
             "limit_bytes": INPUT_LIMIT, "basis": "Core JSON plus supplied hook/tool UTF-8 text"}
    result = {**payload, "context_size": meter}
    # The report is part of the delivered bytes. Decimal widths converge monotonically.
    while True:
        size = len((json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode())
        if size + observed_bytes > INPUT_LIMIT:
            raise ValueError("Workflow input exceeds 64 KiB. Narrow the task and its applicable guidance")
        if meter["core_bytes"] == size:
            return result
        meter.update(core_bytes=size, bytes=size + observed_bytes)


def linked_methods(name, content):
    """Only release-owned Markdown reachable from the selected trusted branch is eligible."""
    targets = set()
    for link in re.findall(r"\]\(([a-zA-Z0-9_./#-]+)\)", content):
        path, marker, anchor = link.partition("#")
        if path.startswith("/") or marker and not re.fullmatch(r"[\w-]+", anchor):
            continue
        relative = posixpath.normpath(posixpath.join(posixpath.dirname(name), path)) if path else name
        if (relative.endswith(".md") and relative.startswith(("playbook/", "templates/", ".agents/skills/"))):
            targets.add(relative + ("#" + anchor if anchor else ""))
    return targets


def with_inputs(root, view, inputs):
    """Assemble selected linked Core references. Transient host text carries no authority."""
    if (not isinstance(inputs, dict) or set(inputs) != {"binding", "references", "observations"}
            or inputs["binding"] != {key: view[key] for key in BINDING}):
        raise ValueError("Bind context inputs to the current Workspace, scope, workflow and readback revision")
    references, observations = inputs["references"], inputs["observations"]
    if (not isinstance(references, list) or len(references) > 8
            or not all(type(ref) is str and len(ref) <= 512 for ref in references)
            or len(set(references)) != len(references)
            or not isinstance(observations, list) or len(observations) > 32):
        raise ValueError("Select up to eight distinct method references and up to 32 host observations")
    initial = view["workflow"].get("method")
    allowed = linked_methods(initial["source"], initial["text"]) if initial else set()
    material = []
    for reference in references:
        if reference not in allowed:
            raise ValueError("Select a linked Core method from this step or an earlier selected reference")
        name, _, heading = reference.partition("#")
        path = root / PurePosixPath(name)
        if path.resolve() != path or not path.is_file() or path.stat().st_size > 128 * 1024:
            raise ValueError("Selected Core method reference is unavailable")
        body = path.read_text(encoding="utf-8")
        if heading:
            body = extract(body, heading, name, anchor=True)
        material.append({"source": reference, "text": body})
        allowed.update(linked_methods(name, body))
    seen = []
    for item in observations:
        if (not isinstance(item, dict) or set(item) != {"kind", "text"}
                or item["kind"] not in ("hook", "tool") or type(item["text"]) is not str):
            raise ValueError("Supply only already delivered hook or tool text for this checkpoint")
        seen.append({"kind": item["kind"], "bytes": len(item["text"].encode())})
    return measured({**view, "selected_method_references": material, "observations": seen},
                    sum(item["bytes"] for item in seen))


def entry(root, command, private=None):
    """Follow the actual onboarding owner when an existing capture round is already underway."""
    from .readback import ONBOARDING, onboarding_capture
    if private is None or command not in ONBOARDING:
        return prepare(root, command)
    kind = ONBOARDING[command]
    capture = onboarding_capture(private, kind)
    step = {"company": {"plan": "assess", "gather": "assess", "review": "review"},
            "pm": {"plan": "scope", "gather": "scope", "review": "review", "paused": "pause"},
            "product": {"review": "review"}}[kind].get(capture["phase"])
    if kind == "product" and step is None:
        import onboarding_review
        if onboarding_review.status(private)["stage"] == "area":
            step = "area"
    result = prepare(root, command, step)
    result["owning_capture"] = capture
    return result
