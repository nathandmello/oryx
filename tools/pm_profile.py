"""Keep the PM's Markdown prose and machine-readable ownership in one private profile."""

from html import escape, unescape
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import layout
import storage

PATH = layout.PROFILE
LEGACY = "context/pm-remit.json"
CAPTURE_START = "<!-- start PM context capture -->"
CAPTURE_END = "<!-- end PM context capture -->"
TOPICS = {"background": "PM background", "preferences": "Working preferences",
          "stakeholders": "PM stakeholders", "context": "Other PM context"}
HEADING = "## PM remit"
RESPONSIBILITIES = ("Responsibility", "Role", "Goals", "Depends on")
FOLLOW = ("Follow",)
BREAK = re.compile(r"\s*<br\s*/?>\s*", re.I)
MARKDOWN_LINK = re.compile(r"\[([^]\r\n]+)\]\((<[^>\r\n]+>|[^\s)]+)\)")


def safe_path(private, name):
    path = private / name
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError(f"Choose a regular private file for {name}")
    return path


def create(private, title=None):
    title = "PM context" if title is None else title
    if not title.strip() or title.splitlines() != [title]:
        raise ValueError("Use a single nonempty line for the PM profile title")
    with storage.writer_lock(private):
        storage.require_visible(private, PATH)
        target = safe_path(private, PATH)
        if target.exists() or safe_path(private, LEGACY).exists():
            raise ValueError("A PM profile or legacy remit already exists")
        storage.replace_text(target, None, f"# {title}\n")
    return target


def effective_status(remit):
    return remit.get("status", "confirmed" if remit["responsibilities"] else "draft")


def _split_row(line):
    return tuple(cell.strip() for cell in line.strip()[1:-1].split("|"))


def visible_lines(lines):
    """Ignore headings or tables quoted inside fenced source examples."""
    result = {}
    fence = None
    for index, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        fence_line = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_line:
            token, rest = fence_line.groups()
            if fence is None:
                fence = token
                continue
            if token[0] == fence[0] and len(token) >= len(fence) and not rest.strip():
                fence = None
                continue
        if fence is None:
            result[index] = line
    return result


def capture_block(text):
    """Separate the sourced capture block from the PM's own prose, without reformatting either."""
    lines = text.splitlines(keepends=True)
    visible = visible_lines(lines)
    starts = [i for i, line in visible.items() if line == CAPTURE_START]
    ends = [i for i, line in visible.items() if line == CAPTURE_END]
    if not starts and not ends:
        return text, None, ""
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError("Repair the PM capture block boundaries before filing new evidence")
    left, right = starts[0], ends[0]
    return "".join(lines[:left]), "".join(lines[left + 1:right]), "".join(lines[right + 1:])


def _structure(lines):
    visible = visible_lines(lines)
    heads = [i for i, line in visible.items() if line.rstrip() == HEADING]
    if not heads:
        return None
    if len(heads) != 1:
        raise ValueError("Keep one PM remit section in the PM profile")
    start = heads[0]
    stop = next((i for i, ln in visible.items() if i > start and re.match(r"^#{1,2}(?:\s|$)", ln)), len(lines))
    spans = {}
    for i, raw in visible.items():
        if not start < i < stop:
            continue
        if raw.startswith("Status:"):
            key = "status"
            if raw.partition(":")[2].strip() not in ("draft", "confirmed"):
                raise ValueError("PM remit status must be draft or confirmed")
            end = i + 1
        elif raw.strip().startswith("|") and raw.strip().endswith("|") and _split_row(raw) in (RESPONSIBILITIES, FOLLOW):
            columns = _split_row(raw)
            key = "responsibilities" if columns == RESPONSIBILITIES else "follow"
            end = i + 1
            while end < stop and visible.get(end, "").lstrip().startswith("|"):
                row = visible[end].strip()
                if not row.endswith("|") or len(_split_row(row)) != len(columns):
                    raise ValueError(f"Check the columns in the PM remit {key} table")
                end += 1
            if end < i + 2 or not all(re.fullmatch(r":?-{3,}:?", x) for x in _split_row(lines[i + 1])):
                raise ValueError(f"Add the heading separator to the PM remit {key} table")
        else:
            continue
        if key in spans:
            raise ValueError(f"Keep one {key} field or table in the PM remit")
        spans[key] = (i, end)
    if not spans:
        return {"section": (start, stop)}  # A PM may already have a narrative description of their remit.
    if set(spans) != {"status", "responsibilities", "follow"}:
        raise ValueError("The PM remit needs Status, Responsibility and Follow")
    return spans


def _items(cell):
    return BREAK.split(cell) if cell else []


def _goal_from_cell(cell):
    link = MARKDOWN_LINK.fullmatch(cell)
    if not link:
        raise ValueError("Use a Markdown link for each PM goal")
    value = unescape(link[2].removeprefix("<").removesuffix(">"))
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return value
    path = parsed.path
    if not path or path.startswith("/"):
        raise ValueError("Use a goal link relative to the PM profile")
    # A Markdown link is relative to the profile. The command contract uses private-root paths.
    path = posixpath.normpath(posixpath.join("context/pm", path))
    return urlunsplit(("", "", path, parsed.query, parsed.fragment))


def parse(text):
    if text.lstrip("\ufeff \r\n\t").startswith(("<!-- pm:", "{")):
        raise ValueError("The PM profile contains a different record format")
    lines = text.splitlines(keepends=True)
    spans = _structure(lines)
    if not spans or "section" in spans:
        return None
    start, stop = spans["responsibilities"]
    roles = []
    for row in lines[start + 2:stop]:
        subject, role, goals, deps = _split_row(row)
        roles.append({"subject": subject, "role": role,
                      "goals": [_goal_from_cell(link) for link in _items(goals)], "depends_on": _items(deps)})
    start, stop = spans["follow"]
    return {"status": lines[spans["status"][0]].partition(":")[2].strip(),
            "responsibilities": roles, "follow": [_split_row(row)[0] for row in lines[start + 2:stop]]}


def _goal_link(value):
    parsed = urlsplit(value)
    link = value if parsed.scheme or parsed.netloc else "../../" + value
    # Keep external query strings and literal punctuation intact in Markdown tables.
    href = escape(link, quote=False).replace("|", "&#124;")
    label = PurePosixPath(unquote(parsed.path)).name or parsed.hostname or "Goal"
    label = escape(label, quote=False).replace("|", "&#124;").replace("[", "&#91;").replace("]", "&#93;")
    return f"[{label}](<{href}>)"


def _row(cells):
    return "| " + " | ".join(cells) + " |"


def render(remit, original=None):
    """Replace only remit fields, preserving user prose, unchanged rows, and line endings."""
    original = "# PM context\n" if original is None else original
    old = parse(original)
    status = effective_status(remit)
    expected = dict(remit, status=status)
    lines = original.splitlines(keepends=True)
    spans = _structure(lines)
    newline = "\r\n" if "\r\n" in original else "\n"
    old_rows = {}
    if old is not None:
        start, stop = spans["responsibilities"]
        old_rows = {row["subject"]: (row, ln.rstrip("\r\n")) for row, ln in
                    zip(old["responsibilities"], lines[start + 2:stop])}
    rows = []
    for item in remit["responsibilities"]:
        prior, prior_line = old_rows.get(item["subject"], (None, None))
        if prior == item:
            rows.append(prior_line)
            continue
        goals = _split_row(prior_line)[2] if prior and prior["goals"] == item["goals"] else "<br>".join(map(_goal_link, item["goals"]))
        rows.append(_row((item["subject"], item["role"], goals, "<br>".join(item["depends_on"]))))
    updates = {"status": [f"Status: {status}"], "responsibilities": rows,
               "follow": [_row((subject,)) for subject in remit["follow"]]}
    if old is None:
        blocks = [updates["status"][0]]
        if spans is None:
            blocks.insert(0, HEADING)
        end = len(lines) if spans is None else spans["section"][1]
        before, after = "".join(lines[:end]), "".join(lines[end:])
        for key, columns in (("responsibilities", RESPONSIBILITIES), ("follow", FOLLOW)):
            blocks.append(newline.join([_row(columns), _row(["---"] * len(columns)), *updates[key]]))
        gap = "" if not before or before.endswith(newline * 2) else newline if before.endswith(newline) else newline * 2
        candidate = before + gap + (newline * 2).join(blocks) + newline + (newline if after else "") + after
    else:
        for key, (start, stop) in sorted(spans.items(), key=lambda item: item[1], reverse=True):
            if expected[key] != old[key]:
                if key != "status":
                    start += 2  # Keep the hand-edited table header and separator.
                    if start == stop and start and not lines[start - 1].endswith(("\n", "\r")):
                        lines[start - 1] += newline
                lines[start:stop] = [row + newline for row in updates[key]]
        candidate = "".join(lines)
    if parse(candidate) != expected:
        raise ValueError("Cannot recover the complete remit from Markdown. Check open fences and goal links")
    return candidate


def checked_goal(private, goal, *, legacy):
    if not isinstance(goal, str) or not goal.strip() or goal.splitlines() != [goal]:
        raise ValueError("Goal link needs one nonempty line")
    parsed = urlsplit(goal)
    if parsed.scheme in ("https", "http") and parsed.hostname and not (parsed.username or parsed.password):
        return
    if parsed.scheme or parsed.netloc or parsed.query:
        raise ValueError("Use a private path or an HTTP(S) goal link without credentials")
    value = unquote(parsed.path)
    path = Path(value)
    # Migrated profiles may still cite an existing goal whose purpose needs PM review.
    homes = {"context", "products"} if legacy else {"context", "workspace", "products"}
    if (path.as_posix() != value or len(path.parts) < 2 or path.parts[0] not in homes or
            any(part.startswith(".") or part == "secrets" for part in path.parts)):
        raise ValueError("Choose an existing goal under the private repository")
    if not safe_path(private, value).is_file():
        raise ValueError(f"Goal link has no private record: {goal}")


def legacy_data(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate legacy remit field: {key}")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)


def from_legacy(private, raw_bytes, moves):
    """Prepare the Markdown profile before a layout transaction moves referenced goal files."""
    import context_capture
    data = context_capture.validate_remit(private, legacy_data(raw_bytes), legacy=True)
    for role in data["responsibilities"]:
        for i, goal in enumerate(role["goals"]):
            url = urlsplit(goal)
            previous = unquote(url.path)
            if not url.scheme and previous in moves:
                role["goals"][i] = urlunsplit(("", "", quote(str(moves[previous]), safe="/"), "", url.fragment))
    return render(data).encode("utf-8")
