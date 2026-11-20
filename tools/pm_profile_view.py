"""Look up one portion of the PM's private profile, keeping the original source scope."""

import re

import context_capture
import pm_profile
import records
import upgrades


def sections(text):
    blocks = records.section_blocks(text)
    introduction = text[:blocks[0][1]] if blocks else text
    introduction = re.sub(r"\A\s*# [^\n]*(?:\n|$)", "", introduction).strip()
    if introduction:
        yield "Overview", introduction
    for name, _, start, end in blocks:
        body = text[start:end].strip()
        if body:
            yield name, body


def passage(origin, body, source_text):
    part = {"origin": origin, "text": body}
    references = {ref[1:-1] for ref in records.SOURCE_REFERENCE.findall(body)}
    if references:
        rows, errors = records.table(source_text, "Sources", records.SOURCE_COLUMNS)
        coverage = {ref: state for ref, state, _ in records.SOURCE_COVERAGE.findall(source_text)}
        part["sources"] = [{**dict(zip(records.SOURCE_COLUMNS, row)), "coverage": coverage.get(row[0], "unrecorded")}
                           for row in rows if row[0] in references]
        if errors or references.difference(row[0] for row in rows):
            part["source_notice"] = "Check the cited source in the original profile before relying on this entry."
    return part


def topic_view(path, topic, captured, remit):
    result = {"profile": path, "topic": topic, "passages": []}
    section = records.section(captured, pm_profile.WALKTHROUGH_TOPICS[topic]) or ""
    lines = section.splitlines()
    marker = f" <!-- pm-topic:{topic} -->"
    for index, line in pm_profile.visible_lines(lines).items():
        if line.startswith("- ") and line.endswith(marker):
            end = index + 1
            while end < len(lines) and lines[end].startswith("  "):
                end += 1
            body = "\n".join([line[:-len(marker)], *lines[index + 1:end]])
            result["passages"].append(passage("capture", body, captured))
    if remit is not None:
        status = remit.get("status", "unrecorded")
        result["remit"] = {"status": status, "responsibilities": remit["responsibilities"]}
        if status != "confirmed" and remit["responsibilities"]:
            result["remit"]["notice"] = "Confirm these rows with the PM before relying on current ownership."
    if not result["passages"] and not (remit and remit["responsibilities"]):
        result["lookup"] = "No scoped entries were found for this topic. Leave the underlying question open."
    return result


def view(private, heading=None, *, topic=None):
    """List section names by default. Return evidence only for an explicit selection."""
    path = pm_profile.safe_path(private, pm_profile.PATH)
    legacy = pm_profile.safe_path(private, pm_profile.LEGACY)
    retained = upgrades.source_paths(private)
    if (path.exists() and pm_profile.PATH in retained) or (legacy.exists() and pm_profile.LEGACY in retained):
        raise ValueError("Review the retained original at the PM profile location before using it")
    if path.exists() and legacy.exists():
        raise ValueError("Review the existing PM profile and legacy remit before choosing their contents")

    if topic is not None:
        if heading is not None or topic not in pm_profile.WALKTHROUGH_TOPICS:
            raise ValueError("Choose one supported PM topic or one section heading")
        remit = None
        if path.exists():
            text = path.read_text(encoding="utf-8")
            _, captured, _ = pm_profile.capture_block(text)
            if topic == "responsibilities":
                remit = pm_profile.parse(text)
                if remit is not None:
                    context_capture.validate_remit(private, remit)
            return topic_view(pm_profile.PATH, topic, captured or "", remit)
        if legacy.exists() and topic == "responsibilities":
            remit = context_capture.read_remit(private)
        return topic_view(pm_profile.LEGACY if legacy.exists() else None, topic, "", remit)
    result = {"profile": None, "sections": []}
    if legacy.exists():
        remit = context_capture.read_remit(private)
        result.update(profile=pm_profile.LEGACY, sections=["PM remit"], remit_status=pm_profile.effective_status(remit))
        if heading == "PM remit":
            result["remit"] = remit
    elif path.exists():
        result["profile"] = pm_profile.PATH
        text = path.read_text(encoding="utf-8")
        remit = pm_profile.parse(text)
        if remit is not None:
            result["remit_status"] = pm_profile.effective_status(context_capture.validate_remit(private, remit))
            if heading == "PM remit":
                result["remit"] = remit
        before, captured, after = pm_profile.capture_block(text)
        for origin, content in (("profile", before), ("capture", captured), ("profile", after)):
            if not content:
                continue
            for name, body in sections(content):
                if name not in result["sections"]:
                    result["sections"].append(name)
                if name != heading:
                    continue
                source_text = captured if origin == "capture" else before + "\n" + after
                result.setdefault("passages", []).append(passage(origin, body, source_text))
    if heading is not None:
        if heading not in result.pop("sections"):
            result["lookup"] = "No matching section is recorded. Leave the underlying question open."
        if heading != "PM remit":
            result.pop("remit_status", None)
        result["section"] = heading
    return result
