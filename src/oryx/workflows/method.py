"""Select bounded instructions from the trusted method that owns a workflow step."""

from dataclasses import dataclass
from hashlib import sha256
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
    lines = path.read_text(encoding="utf-8").splitlines()
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
    matches = [i for i, (_, _, title) in enumerate(headings) if title == step.heading]
    if len(matches) != 1:
        raise ValueError(f"Cannot identify the workflow method section {step.file}#{step.heading}")
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


def measured(payload):
    """Measure the bytes Core actually delivers, before the host appends its own inputs."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    size = len(encoded.encode())
    if size > 65536:
        raise ValueError("Workflow input exceeds 64 KiB. Narrow the task and its applicable guidance")
    return {**payload, "context_size": {"bytes": size, "basis": "compact UTF-8 JSON before measurement",
                                       "limit_bytes": 65536}}


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
    result = prepare(root, command, step)
    result["owning_capture"] = capture
    return result
