"""Keep source links bound to the original indexed revision and its recorded limitations."""
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from urllib.parse import unquote, urlsplit

from . import identity

FILE = identity.STATE / "citations.json"
LINK = re.compile(r"\[[^\]\n]*\]\((<[^>\n]+>|[^\s)]+)\)")


def load(root):
    file = identity.local_file(root, str(FILE))
    if not file.exists():
        return {}
    data = json.loads(identity.read_regular(file))
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("workspace_id") != identity.workspace_id(root) or not isinstance(data.get("records"),dict):
        raise ValueError("Invalid citation registry")
    return data["records"]


def validate(root, registry):
    rows = load(root)
    records = registry["records"]
    statuses = {"unverified", "historical-target-unverified", "historical-target-ambiguous", "external-permission-required"}
    from .resources import URI
    for rid, revisions in rows.items():
        if rid not in records or not isinstance(revisions,dict) or not revisions.keys() <= set(records[rid]["history"]):
            raise ValueError("A citation belongs to an unknown record revision")
        for rev, links in revisions.items():
            data = identity.read_regular(identity.local_file(root,str(identity.BLOBS/rev))).decode("utf-8")
            if not isinstance(links,dict) or set(links) != {href.strip("<>") for href in LINK.findall(data)}:
                raise ValueError("Saved citations differ from the actual source revision")
            for edge in links.values():
                if not isinstance(edge,dict):
                    raise ValueError("Invalid historical citation")
                status = edge.get("status")
                if status in statuses and set(edge) == {"status"}:
                    continue
                if status == "core" and set(edge) == {"status","uri"} and URI.fullmatch(edge["uri"]):
                    continue
                if (status == "record" and set(edge) == {"status","id","revision","anchor"} and edge["id"] in records
                        and edge["revision"] in records[edge["id"]]["history"] and
                        (edge["anchor"] is None or isinstance(edge["anchor"],str))):
                    continue
                raise ValueError("Dangling or malformed historical citation")
    return rows


def classify(href, source_path, aliases, registry, git_tree):
    try:
        link = urlsplit(href)
    except ValueError:
        return {"status": "unverified"}
    if link.scheme == "oryx" and link.netloc == "core":
        return {"status": "core", "uri": href}
    if link.scheme or link.netloc:
        return {"status": "external-permission-required"}
    raw = unquote(link.path)
    if raw.startswith("/") or "\\" in raw or link.query:
        return {"status": "unverified"}
    relative = posixpath.normpath(posixpath.join(str(PurePosixPath(source_path).parent), raw)) if raw else source_path
    if relative.startswith("../"):
        resource = relative[3:]
        if (resource.startswith(("playbook/","templates/",".agents/skills/")) or resource in {"AGENTS.md","README.md","CLAUDE.md"}) and ".." not in resource.split("/"):
            return {"status": "core", "uri": "oryx://core/" + resource + ("#" + link.fragment if link.fragment else "")}
        return {"status": "unverified"}
    rid = aliases.get(relative)
    if not rid:
        return {"status": "unverified"}
    if git_tree is not None and (rid, relative) not in git_tree:
        return {"status": "historical-target-unverified"}
    rev = registry["records"][rid]["revision"] if git_tree is None else git_tree[rid, relative]
    return {"status": "record", "id": rid, "revision": rev, "anchor": link.fragment or None}


def reconcile(root, registry, versions=None):
    edges = load(root)
    aliases = {name: rid for rid, row in registry["records"].items() for name in row["aliases"]}
    trees = {}
    for rid, entries in (versions or {}).items():
        for revision, occurrences in entries.items():
            for item in occurrences:
                trees.setdefault(item["git"], {})[rid,item["path"]] = revision
    for rid, row in registry["records"].items():
        if not row["path"].endswith(".md"):
            continue
        rows = edges.setdefault(rid,{})
        for rev in row["history"]:
            if rev in rows:
                continue
            doc = identity.read_regular(identity.local_file(root, str(identity.BLOBS / rev))).decode("utf-8")
            hrefs = sorted({item.strip("<>") for item in LINK.findall(doc)})
            history = (versions or {}).get(rid,{}).get(rev,[])
            options = [(r["path"],trees[r["git"]]) for r in history if r["git"] != "index"]
            if rev == row["revision"]:
                options.append((row["path"],None))
            resolved = {}
            for href in hrefs:
                candidates = [classify(href, name, aliases, registry, tree) for name, tree in options]
                if not candidates:
                    resolved[href] = {"status":"historical-target-unverified"}
                elif all(result == candidates[0] for result in candidates):
                    resolved[href] = candidates[0]
                else:
                    resolved[href] = {"status":"historical-target-ambiguous"}
            rows[rev] = resolved
    identity.write_json(root / FILE, {"schema":1,"workspace_id":registry["workspace_id"],"records":edges})


def lookup(root, record, href, revision=None):
    owner = identity.resolve(root, record, revision)
    if owner["transfer_status"] == "transferred":
        return owner
    row = load(root).get(owner["id"],{}).get(owner["revision"],{}).get(href)
    if row is None:
        raise ValueError("This link was not recorded for that source revision")
    if row.get("status") == "record":
        target = identity.resolve(root, row["id"], row["revision"])
        if row["anchor"] and target.get("source_path"):
            from conversion import markdown_anchors
            text = identity.read_regular(identity.local_file(root, target["source_path"])).decode("utf-8")
            if row["anchor"] not in markdown_anchors(text):
                raise ValueError("The historical citation anchor was unavailable")
        return {**row,"target":target}
    return row
