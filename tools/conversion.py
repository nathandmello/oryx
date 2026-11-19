"""Apply a reviewed filing plan with recoverable preimages in the private repository."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import NamedTemporaryFile
from urllib.parse import unquote, urlsplit
import zipfile

import filing
import records
import storage
import upgrades

HISTORY = ".hub-history"
TRANSACTIONS = upgrades.TRANSACTIONS
PENDING = ".hub-filing-pending.json"
IDENTIFIER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pointer(private):
    path = private / PENDING
    if path.resolve() != path:
        raise ValueError("Unsafe recovery journal")
    return path


def archive_path(private, identifier):
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise ValueError("Use a stable lowercase filing plan ID")
    path = private / HISTORY / (identifier + ".zip")
    if path.resolve() != path:
        raise ValueError("Unsafe recovery archive path")
    return path


def check_plan(private, plan, *, legacy_replay=False):
    if (not isinstance(plan, dict) or set(plan) != {"id", "reason", "changes"}
            or not isinstance(plan["changes"], list) or not plan["changes"]
            or not isinstance(plan["reason"], str) or not records.specific(plan["reason"].strip())):
        raise ValueError("A filing plan needs an ID, a specific reason, and changes")
    archive_path(private, plan["id"])
    edits, folds = {}, {}
    for row in plan["changes"]:
        if not isinstance(row, dict) or set(row) - {"replacements"} not in ({"path", "before", "text"}, {"path", "before", "into"}):
            raise ValueError("Each change needs a path, its current digest, and text or a fold destination")
        name = row["path"]
        upgrades.review_path(private, name)
        if "sources" in Path(name).parts:
            raise ValueError("Keep original source files in place")
        if not isinstance(row.get("replacements", []), list):
            raise ValueError("List source-backed replacements for changed lines")
        new_target = "text" in row and row["before"] == "absent"
        if name in edits or name in folds or not (new_target or re.fullmatch(r"[0-9a-f]{64}", str(row["before"]))):
            raise ValueError("Use each existing path once, with its SHA-256 digest")
        if "text" in row:
            if not isinstance(row["text"], str) or not row["text"].strip():
                raise ValueError("Supply the complete retained document")
            edits[name] = row
        else:
            if Path(name).name == "README.md":
                raise ValueError("Keep workspace navigation in place")
            if not isinstance(row["into"], str):
                raise ValueError("Select a retained destination for the fold")
            folds[name] = row
    for row in folds.values():
        if legacy_replay:
            # Only for a hash-verified, previously accepted transaction from format 1.
            if Path(row["into"]).parts[:1] not in {("context",), ("products",)}:
                raise ValueError("Invalid legacy filing destination")
        else:
            filing.home(row["into"])
    if any(row["into"] not in edits for row in folds.values()):
        raise ValueError("Include the verified destination text for every fold")
    for name, row in edits.items():
        if row["before"] == "absent" and not any(f["into"] == name for f in folds.values()):
            raise ValueError("A new filing destination must receive an existing record")
    return edits, folds


def content_lines(text):
    # Keep literal clauses. Ignore only Markdown structure without a claim.
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or re.fullmatch(r"[| :\-]+|<!-- pm: [a-z-]+ -->", line):
            continue
        yield number, line


def markdown_anchors(text):
    ids = set(re.findall(r"""<(?:a|[hH][1-6])\b[^>]*(?:id|name)=["']([^"']+)["']""", text, re.I))
    fenced = None
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            marker = line.lstrip()[:3]
            if not fenced or fenced == marker:
                fenced = None if fenced else marker
            continue
        heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if fenced or not heading:
            continue
        slug = re.sub(r"[^\w\- ]", "", heading[1].lower()).replace(" ", "-")
        result, index = slug, 0
        while result in ids:
            index += 1
            result = f"{slug}-{index}"
        ids.add(result)
    return ids


def verify_fragments(private, texts, edits, link_pattern):
    cache = {}
    for name, text in texts.items():
        if name.startswith("templates/"):
            continue
        for match in link_pattern.finditer(text):
            url = urlsplit(match[2].strip("<>"))
            if url.scheme or url.netloc or not url.fragment:
                continue
            target = (private / name).parent / unquote(url.path) if url.path else private / name
            target = target.resolve()
            if not target.is_relative_to(private) or target.suffix.lower() != ".md":
                continue
            dest = target.relative_to(private).as_posix()
            if (name not in edits and dest not in edits) or dest not in texts:
                continue
            if dest not in cache:
                cache[dest] = markdown_anchors(texts[dest])
            if unquote(url.fragment) not in cache[dest]:
                raise ValueError(f"Resolve the link from {name} to the missing anchor in {dest}: {url.fragment}")


def source_lines(path, page):
    if path.suffix.lower() != ".pdf":
        if page is not None:
            raise ValueError("Use a page number only for PDF evidence")
        return path.read_text(encoding="utf-8").splitlines()
    binary = shutil.which("pdftotext")
    if not binary or type(page) is not int or page < 1:
        raise ValueError("PDF proof needs a positive page and pdftotext, or an approved local text extract")
    result = subprocess.run([binary, "-f", str(page), "-l", str(page), "-layout", str(path), "-"],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError("Could not inspect the specified PDF page")
    return [line.strip() for line in result.stdout.decode("utf-8").splitlines()]


NAVIGATION_WORDS = set("""
a an the and as at below above by for from in into of on or this that these those to its their
see read link links linked refer refers reference references section sections index appendix contents
home parent company product initiative brief profile context direction source sources register ids evidence
limits notes research capture checks audit corrections record records recorded holds hold store stores
preserve preserves maintained contains see also targets announced clarifications
""".split())


def navigation_line(private, name, line, link_pattern):
    """Archive only explicitly selected navigation that contains no unrecognised substantive words."""
    links = list(link_pattern.finditer(line))
    if not links:
        label = re.sub(r"^(?:company|product|initiative|artifact)(?: context)?\s*[:–—]\s*", "", line.strip("# ").casefold())
        return line.startswith("#") and label in {"contents", "index", "notes", "research notes", "source register",
                                                  "context notes", "sources", "references", "capture notes"}
    for link in links:
        url = urlsplit(link[2].strip("<>"))
        target = ((private / name).parent / unquote(url.path)).resolve() if url.path else private / name
        if url.scheme or url.netloc or not target.is_relative_to(private):
            return False
    visible = link_pattern.sub(lambda m: m[1], line)
    return bool(visible.strip("# ")) and set(re.findall(r"[\w’']+", visible.casefold())) <= NAVIGATION_WORDS


def check_coverage(private, originals, edits, folds, link_pattern):
    """Every removed content line survives in a named destination or has a verified replacement."""
    visible = set(storage.inventory(private))
    def canonical_links(line, name):
        def normalise(match):
            uri = urlsplit(match[2].strip("<>"))
            if uri.scheme or uri.netloc:
                return match[0]
            target = ((private / name).parent / unquote(uri.path)).resolve() if uri.path else private / name
            if target.is_relative_to(private) and target.relative_to(private).as_posix() in folds:
                target = private / folds[target.relative_to(private).as_posix()]["into"]
            return f"[{match[1]}]({target}{'?' + uri.query if uri.query else ''}{'#' + uri.fragment if uri.fragment else ''})"
        return link_pattern.sub(normalise, line)
    for name, row in {**edits, **folds}.items():
        destination = row.get("into", name)
        text = canonical_links(edits[destination]["text"], destination)
        previous = dict(content_lines(originals[name].decode("utf-8")))
        accounted = set()
        for proof in row.get("replacements", []):
            if isinstance(proof, dict) and set(proof) == {"line", "disposition"}:
                number = proof["line"]
                if (proof["disposition"] != "navigation" or type(number) is not int or number not in previous
                        or number in accounted or not navigation_line(private, name, previous[number], link_pattern)):
                    raise ValueError("Archive only verified non-substantive navigation")
                accounted.add(number)
                continue
            if isinstance(proof, dict) and set(proof) == {"line", "destination"}:
                number, target = proof["line"], proof["destination"]
                if (type(number) is not int or number not in previous or not isinstance(target, str) or target not in edits
                        or number in accounted or canonical_links(previous[number], name) not in canonical_links(edits[target]["text"], target)):
                    raise ValueError("Retain the original line at its declared destination")
                accounted.add(number)
                continue
            if not isinstance(proof, dict) or set(proof) - {"page"} != {"line", "source", "digest", "quote", "destination"}:
                raise ValueError("Identify the old line, primary source path and digest, exact source line and retained destination")
            number, source, quote, target = (proof[k] for k in ("line", "source", "quote", "destination"))
            if type(number) is not int or number not in previous or number in accounted or not isinstance(target, str) or target not in edits:
                raise ValueError("Identify one existing content line and a retained destination")
            if not isinstance(source, str) or not isinstance(quote, str) or not quote.strip() or not records.specific(quote.strip()):
                raise ValueError("Give the full authoritative source line")
            path = private / source
            if (path.resolve() != path or path not in visible or source in edits or source in folds
                    or any(p.startswith(".") or p == "secrets" for p in Path(source).parts)
                    or Path(source).is_absolute() or path.suffix.lower() not in (".md", ".txt", ".pdf")):
                raise ValueError("Use an unchanged local primary source for a replacement")
            if (upgrades.fingerprint(path) != proof["digest"] or quote not in source_lines(path, proof.get("page"))
                    or quote not in edits[target]["text"]):
                raise ValueError("Replacement must retain the complete verified source line")
            accounted.add(number)
        for number, line in previous.items():
            if number not in accounted and canonical_links(line, name) not in text:
                raise ValueError(f"Account for the original content at {name}:{number} before applying the plan")


def recoverable_swap(private, identifier, name, before, candidate):
    """Keep the displaced inode so external editor writes stay recoverable even across a rename."""
    path = private / name
    if before == "absent":
        if not path.exists():
            storage.replace_text(path, None, candidate.decode("utf-8"))
        elif path.read_bytes() != candidate:
            raise ValueError(f"Concurrent edit at the new destination {name}")
        return
    saved = private / ".git" / "pm-hub-recovery" / "filing" / identifier / name
    if saved.resolve() != saved:
        raise ValueError("Unsafe displaced-file path")
    saved.parent.mkdir(parents=True, exist_ok=True)
    if saved.exists() and upgrades.fingerprint(saved) != before:
        raise ValueError(f"Concurrent edit preserved at {saved}; review it before resuming")
    if path.exists():
        if candidate is not None and path.read_bytes() == candidate:
            return
        if upgrades.fingerprint(path) != before:
            raise ValueError(f"Concurrent change to {name}; retained the file")
        if saved.exists():
            raise ValueError(f"Original path {name} reappeared during conversion; inspect both copies")
        os.rename(path, saved)
        if upgrades.fingerprint(saved) != before:
            if not path.exists():
                os.link(saved, path)
            raise ValueError(f"Concurrent change in {name}; preserved at {saved}")
    if candidate is not None:
        try:
            storage.replace_text(path, None, candidate.decode("utf-8"))
            if saved.exists():
                os.chmod(path, saved.stat().st_mode & 0o777)
        except OSError as exc:
            raise OSError(f"Could not publish {name}; the verified original is recoverable: {exc}") from exc


def check_references(private, edits, folds, link_pattern):
    """Require the plan to resolve all visible references to retired files."""
    retired = {private / name for name in folds}
    filenames = {p.name for p in retired}
    for path in storage.inventory(private):
        rel = path.relative_to(private)
        name = rel.as_posix()
        if (name == upgrades.LEDGER or not path.is_file() or path.resolve() != path
                or any(part.startswith(".") or part == "secrets" for part in rel.parts)):
            continue
        if path.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html"}:
            continue
        before = path.read_text(encoding="utf-8")
        registered = records.section(before, "Sources") or ""
        for reference in link_pattern.finditer(registered):
            url = urlsplit(reference[2].strip("<>"))
            if not url.scheme and not url.netloc and url.path:
                source = (path.parent / unquote(url.path)).resolve()
                if source in retired or (source.is_relative_to(private) and source.relative_to(private).as_posix() in edits
                                           and edits[source.relative_to(private).as_posix()]["before"] != digest(edits[source.relative_to(private).as_posix()]["text"].encode())):
                    raise ValueError(f"Preserve registered primary source {source.name}")
        if name in folds:
            continue
        content = edits[name]["text"] if name in edits else before
        for match in link_pattern.finditer(content):
            url = urlsplit(match[2].strip("<>"))
            if not url.scheme and not url.netloc and (path.parent / unquote(url.path)).resolve() in retired:
                raise ValueError(f"Update the incoming link in {name} before folding")
        # Unknown link syntaxes and path-valued configuration remain in place until resolved.
        remainder = link_pattern.sub("", content) if path.suffix.lower() == ".md" else content
        if any(filename in unquote(remainder) for filename in filenames):
            raise ValueError(f"Resolve or retain the filename reference in {name} before folding")


def save_archive(private, archive, plan):
    archive.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=archive.parent, delete=False) as temp:
        staged = Path(temp.name)
    try:
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as out:
            out.writestr("plan.json", json.dumps(plan, ensure_ascii=False))
            for row in plan["changes"]:
                if row["before"] == "absent":
                    continue
                data = (private / row["path"]).read_bytes()
                if digest(data) != row["before"]:
                    raise ValueError(f"Local edits changed {row['path']}; rebuild the plan")
                out.writestr("original/" + row["path"], data)
        with zipfile.ZipFile(staged) as check:
            if check.testzip() is not None:
                raise ValueError("Could not verify the recovery archive")
        os.link(staged, archive)
    finally:
        staged.unlink(missing_ok=True)


def apply(private, plan, validate, link_pattern, *, preview=False, legacy_replay=False):
    """Caller holds the writer lock. A durable journal makes each step retryable."""
    edits, folds = check_plan(private, plan, legacy_replay=legacy_replay)
    archive = archive_path(private, plan["id"])
    new_paths = [name for name, row in edits.items() if row["before"] == "absent"]
    ignored = subprocess.run(["git", "-C", str(private), "check-ignore", "--no-index", "--",
                              archive.relative_to(private).as_posix(), PENDING, upgrades.LEDGER, *new_paths], capture_output=True)
    if ignored.returncode != 1:
        raise ValueError("Private Git must include the recovery archive, journal, and ledger before filing")
    journal = pointer(private)
    original_state, state = upgrades.read_state(private)
    if any(state.get(upgrades.RULE, {}).get(name, {}).get("role") == "source" for name in (*edits, *folds)):
        raise ValueError("Preserve identified original sources")
    done = state.setdefault(TRANSACTIONS, {})
    exists = archive.exists()
    if exists:
        with zipfile.ZipFile(archive) as saved:
            if json.loads(saved.read("plan.json")) != plan:
                raise ValueError("The archive ID belongs to another filing plan")
            for row in plan["changes"]:
                if row["before"] != "absent" and digest(saved.read("original/" + row["path"])) != row["before"]:
                    raise ValueError("Recovery preimage failed verification")
    token = json.dumps({"id": plan["id"], "sha256": digest(archive.read_bytes())}) if exists else None
    pending = json.loads(journal.read_text()) if journal.is_file() else None
    if pending is not None and (not isinstance(pending, dict) or not exists or pending.get("id") != plan["id"]
                                or pending.get("sha256") != digest(archive.read_bytes())):
        raise ValueError("Resume the pending filing plan before starting another")
    if plan["id"] in done:
        if not exists or done[plan["id"]] != digest(archive.read_bytes()):
            raise ValueError("The completed filing plan's recovery archive is missing or changed")
        if pending and not preview:
            journal.unlink()
        return {"id": plan["id"], "status": "already applied"}
    resuming = pending is not None
    allowed = {str(name) for name in storage.inventory(private)}
    originals = {}
    for name, row in {**edits, **folds}.items():
        path = private / name
        current = upgrades.fingerprint(path)
        after = digest(row["text"].encode()) if name in edits else "absent"
        if current != row["before"] and not (resuming and (current == after or
                (current == "absent" and name in edits and
                 pending.get("moving") == name))):
            raise ValueError(f"Local edits changed {name}; original data preserved")
        if current != "absent" and str(path) not in allowed:
            raise ValueError(f"Filing excludes ignored records: {name}")
        if not exists:
            originals[name] = path.read_bytes() if path.exists() else b""
    if exists:
        with zipfile.ZipFile(archive) as saved:
            originals = {row["path"]: (saved.read("original/" + row["path"]) if row["before"] != "absent" else b"") for row in plan["changes"]}
    check_coverage(private, originals, edits, folds, link_pattern)
    check_references(private, edits, folds, link_pattern)
    validate(edits, folds, archive, originals)
    summary = {"id": plan["id"], "edited": list(edits), "folded": list(folds),
               "recovery": archive.relative_to(private).as_posix()}
    if preview:
        return dict(summary, status="preview")
    if not exists:
        save_archive(private, archive, plan)
        token = json.dumps({"id": plan["id"], "sha256": digest(archive.read_bytes())})
    if not pending:
        storage.replace_text(journal, None, token)
    for name, row in edits.items():
        candidate = row["text"].encode()
        if upgrades.fingerprint(private / name) != digest(candidate):
            intent = dict(json.loads(token), moving=name)
            storage.replace_text(journal, journal.read_text(), json.dumps(intent))
        recoverable_swap(private, plan["id"], name, row["before"], candidate)
    check_references(private, edits, folds, link_pattern)
    for name, row in folds.items():
        if (private / row["into"]).read_bytes() != edits[row["into"]]["text"].encode():
            raise ValueError("Fold destination changed; retained the original")
        if (private / name).exists():
            recoverable_swap(private, plan["id"], name, row["before"], None)
    for name, row in {**edits, **folds}.items():
        displaced = private / ".git" / "pm-hub-recovery" / "filing" / plan["id"] / name
        if displaced.exists() and upgrades.fingerprint(displaced) != row["before"]:
            raise ValueError(f"Concurrent edit retained at {displaced}; reconcile before continuing")
    for name, row in edits.items():
        if (private / name).read_bytes() != row["text"].encode():
            raise ValueError(f"Concurrent edit in {name}; inspect the recovery archive")
    done[plan["id"]] = digest(archive.read_bytes())
    items = state.setdefault(upgrades.RULE, {})
    for name, row in {**edits, **folds}.items():
        if name in items:
            items[name] = {"status": "reviewed", "note": plan["reason"], "digest": upgrades.fingerprint(private / name)}
    storage.replace_text(private / upgrades.LEDGER, original_state, upgrades.encode(state))
    journal.unlink()
    return dict(summary, status="applied")


def resume(private, validate, link_pattern, *, legacy=False):
    journal = pointer(private)
    if not journal.exists():
        return None
    pending = json.loads(journal.read_text())
    if not isinstance(pending, dict) or not isinstance(pending.get("sha256"), str) or "id" not in pending:
        raise ValueError("Invalid pending filing journal")
    archive = archive_path(private, pending["id"])
    if digest(archive.read_bytes()) != pending["sha256"]:
        raise ValueError("Pending recovery archive changed; retained workspace files")
    with zipfile.ZipFile(archive) as saved:
        return apply(private, json.loads(saved.read("plan.json")), validate, link_pattern, legacy_replay=legacy)
