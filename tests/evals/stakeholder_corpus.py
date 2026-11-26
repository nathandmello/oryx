"""Freeze original synthetic materials, deliver clean packets and capture observable file effects."""
import argparse
import hashlib
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

FAMILIES = ("preferences", "decisions", "attribution", "identity", "boundaries", "reuse")
EFFECTS = ("scope", "preview", "outcome", "retry", "fresh-use")
STAGES = ("baseline", "preview", "outcome", "retry", "fresh-use")
ROOT = Path(__file__).resolve().parents[2]
HEX = re.compile(r"[0-9a-f]{64}")
IDENT = re.compile(r"[A-Za-z0-9_-]{1,80}")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def data(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def read(path):
    return json.loads(path.read_bytes())


def external(path):
    require(not path.is_relative_to(ROOT), "Keep operator and judge materials outside the product")


def fresh(root):
    external(root.resolve())
    root.mkdir(mode=0o700, parents=True, exist_ok=False)


def freeze(corpus, directory):
    directory = directory.resolve()
    rows = [json.loads(line) for line in corpus.read_text().splitlines() if line.strip()]
    ids = [x["id"] for x in rows]
    require(len(set(ids)) == len(ids) and all(IDENT.fullmatch(i) for i in ids), "Duplicate or invalid ID")
    origins = {x["id"]: x for x in rows if x["origin"] == x["id"]}
    sources = set()
    for row in rows:
        require(row["origin"] in origins and row["family"] in FAMILIES, "Unknown family or original")
        original = origins[row["origin"]]
        require(row["split"] in {"dev","heldout"} and row["split"] == original["split"]
                and row["family"] == original["family"], "Variant changes stratum")
        require(row["origin"] == row["id"] or row.get("transform_expectation"), "Missing transformation rule")
        require(row["source"].strip() and row["prompt"].strip() and row["source"] not in sources,
                "Missing or repeated source")
        sources.add(row["source"])
        key = row["key"]
        require(isinstance(key["negative"], bool) and
                (all(item.get("durable") is False for item in key["required"]) if key["negative"] else key["required"]),
                "Wholly negative sources can require clarification or abstention, never a durable proposal")
        meanings = [f["id"] for group in ("required","permissible") for f in key[group]]
        require(len(set(meanings)) == len(meanings) and set(key["assertions"]) >= set(EFFECTS), "Invalid source key")
        require(row["script"] and row["permitted_sources"] and set(row["seed"]) >=
                {"people","profiles","decisions","grants"}, "Missing PM or seed context")
    breadth = Counter((x["split"],x["family"]) for x in origins.values())
    for family in FAMILIES:
        require(breadth["heldout",family] >= 8 and breadth["dev",family] >= 2, f"Missing breadth in {family}")
    require(sum(x["key"]["negative"] for x in origins.values() if x["split"] == "heldout") >= 8,
            "Need eight independent negative holdouts")
    fresh(directory)
    manifest = {"version":1, "cases":{}}
    for row in rows:
        case = directory / row["id"]
        case.mkdir(mode=0o700)
        files = {"source.txt":row["source"].encode(), "request.txt":row["prompt"].encode(),
                 "seed.json":data({"date":row["date"],"records":row["seed"],"sources":row["permitted_sources"]}),
                 "operator.json":data(row["script"]), "key.json":data(row["key"])}
        hashes = {}
        for name, value in files.items():
            (case/name).write_bytes(value)
            hashes[name] = digest(value)
        manifest["cases"][row["id"]] = {field:row[field] for field in ("split","family","origin","format","workflow")}
        manifest["cases"][row["id"]].update(files=hashes, transformation=row.get("transform_expectation"))
    raw = data(manifest)
    (directory/"manifest.json").write_bytes(raw)
    return digest(raw)


def load_manifest(directory, pin):
    path = directory / "manifest.json"
    require(HEX.fullmatch(pin) and digest(path.read_bytes()) == pin, "Manifest digest differs from external freeze")
    return read(path)["cases"]


def verified_file(directory, cases, case, name):
    path = directory / case / name
    require(path.is_file() and not path.is_symlink() and digest(path.read_bytes()) == cases[case]["files"][name],
            f"Frozen bytes changed for {case}/{name}")
    return path


def packet(directory, pin, case, out):
    cases = load_manifest(directory, pin)
    files = [verified_file(directory, cases, case, name) for name in ("source.txt","request.txt","seed.json")]
    fresh(out)
    for path in files:
        shutil.copyfile(path, out/path.name)
    # Operator provisions the seeds in native storage and submits the request. Only source.txt is mounted.


def snapshot(root):
    """Include ignored, hidden, and untracked files. Fingerprint symlinks without following them."""
    root = root.resolve(strict=True)
    records = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(folder)/name
            if name == ".git" and not path.is_symlink():
                if name in dirs:
                    dirs.remove(name)
                continue
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                payload = os.readlink(path).encode()
            elif stat.S_ISREG(mode):
                payload = path.read_bytes()
            elif stat.S_ISDIR(mode):
                payload = b""
            else:
                raise ValueError(f"Unsupported filesystem object: {path.name}")
            records[path.relative_to(root).as_posix()] = [mode, digest(payload)]
    return records


def changed(before, after):
    return {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action",required=True)
    f = sub.add_parser("freeze")
    f.add_argument("corpus",type=Path)
    f.add_argument("directory",type=Path)
    p = sub.add_parser("packet")
    p.add_argument("directory",type=Path)
    p.add_argument("pin")
    p.add_argument("case")
    p.add_argument("out",type=Path)
    s = sub.add_parser("snapshot")
    s.add_argument("root",type=Path)
    s.add_argument("output",type=Path)
    args = cli.parse_args()
    try:
        if args.action == "freeze":
            print(freeze(args.corpus,args.directory))
        elif args.action == "packet":
            packet(args.directory,args.pin,args.case,args.out)
        else:
            out = args.output.resolve()
            external(out)
            require(not out.is_relative_to(args.root.resolve()), "Keep evidence outside the measured tree")
            with out.open("xb") as f:
                f.write(data(snapshot(args.root)))
    except (ValueError, OSError, KeyError) as exc:
        sys.exit(str(exc))
