"""Read a private release channel and reconcile Core updates and diagnostic delivery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from . import archive, workspace_update


VERSION = re.compile(r"(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})")
COMMIT = re.compile(r"[0-9a-f]{40}")
STAGES = {"discover", "download", "verify", "compatibility", "activate", "health", "interrupted"}
RECOVERIES = {"previous-verified", "no-prior-core", "manual-reconciliation", "superseded"}
TOKENS = ("ORYX_DOWNLOAD_TOKEN", "ORYX_REPORT_TOKEN")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Release endpoint redirected. Verify its configured public URL")


def endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1"}):
        raise ValueError("Use the configured HTTPS endpoint without embedded credentials")
    if any(part in {".", ".."} for part in parsed.path.split("/")):
        raise ValueError("Use the canonical release endpoint")
    return value.rstrip("/")


def request(base, path, token, *, method="GET", data=None, limit=65536):
    if not token or any(c in token for c in "\r\n"):
        raise ValueError("A valid release-channel credential is required")
    url = endpoint(base) + "/" + path
    headers = {"Authorization": "Bearer " + token, "Cache-Control": "no-cache"}
    req = Request(url, data=data, method=method, headers=headers)
    with build_opener(NoRedirect()).open(req, timeout=45) as response:
        if response.status not in {200, 201}:
            raise ValueError("Release endpoint did not positively acknowledge the request")
        result = response.read(limit + 1)
        if len(result) > limit:
            raise ValueError("Release response exceeded the permitted size")
        return result


def encode(data):
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def decode(raw):
    return json.loads(raw, object_pairs_hook=archive.unique_object)


def release_record(data):
    if (not isinstance(data, dict) or set(data) != {"version", "commit", "archive", "signature", "release_id"}
            or not isinstance(data["version"], str) or not VERSION.fullmatch(data["version"])
            or not isinstance(data["commit"], str) or not COMMIT.fullmatch(data["commit"])
            or any(not isinstance(data[name], str) or not archive.HEX.fullmatch(data[name]) for name in ("archive", "signature"))
            or type(data["release_id"]) is not int or data["release_id"] < 1):
        raise ValueError("Malformed release identity")
    return data


def downloaded(base, record, name, token, folder):
    limit = archive.MAX_ARCHIVE if name == "archive" else 64 * 1024
    data = request(base, "objects/" + record[name], token, limit=limit)
    if hashlib.sha256(data).hexdigest() != record[name]:
        raise ValueError("Served content differs from the advertised release digest")
    target = folder / name
    target.write_bytes(data)
    return target


def save(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(encode(data))
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            archive.sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)


def operations(store):
    folder = store / "operations"
    folder.mkdir(mode=0o700, exist_ok=True)
    archive.check_private_dir(folder)
    return folder


def binding(base):
    return hashlib.sha256(endpoint(base).encode()).hexdigest()


def validated_report(job):
    report = {name: job[name] for name in ("incident", "version", "step", "recovery")}
    if (not isinstance(report["incident"], str) or not re.fullmatch(r"[0-9a-f]{32}", report["incident"])
            or not isinstance(report["version"], str) or not (report["version"] == "unknown" or VERSION.fullmatch(report["version"]))
            or report["step"] not in STAGES or report["recovery"] not in RECOVERIES):
        raise ValueError("Invalid diagnostic report")
    return report


def deliver(path, job, base, token):
    if job["delivery"] == "confirmed" or job["status"] != "failed" or job["channel"] != binding(base):
        return
    report = validated_report(job)
    try:
        response = decode(request(base, "reports/" + report["incident"], token, method="PUT", data=encode(report)))
        issue = response.get("issue") if isinstance(response, dict) else None
        if type(issue) is int and issue > 0 and response.get("incident") == report["incident"]:
            job.update(delivery="confirmed", issue=issue)
        else:
            job["delivery"] = "pending"
    except (ValueError, HTTPError, URLError, OSError):
        job["delivery"] = "pending"
    save(path, job)


def current_receipt(job):
    return {name: job.get(name) for name in ("incident", "status", "version", "step", "recovery", "workspace_recovery", "delivery", "issue")}


def verify_health(core):
    archive.check_runtime(core)
    environment = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    result = subprocess.run([sys.executable, "-I", "-B", str(core / "bin/oryx"), "check", "--system-only"],
                            cwd=core, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=120, check=False)
    if result.returncode:
        raise ValueError("Verified Core failed installed startup checks")


def apply_job(job, *, undo=False):
    return workspace_update.apply(job.get("workspace"), reverse=bool(job.get("reverse")) != undo)


def complete(store, generations, job):
    active = archive.read_state(store)["active"]
    if not active or active["digest"] != job["candidate"]:
        raise ValueError("Active generation differs from this operation")
    verify_health(generations / active["generation"] / "core")
    if not job["prior"] or active["generation"] != job["prior"]["generation"]:
        job["activated_generation"] = active["generation"]
    try:
        job["workspace_recovery"] = apply_job(job)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        if job.get("kind") != "rollback":
            raise
        job["workspace_recovery"] = "manual-reconciliation"
    job.update(status="succeeded", recovery="unused", delivery="unused")


def recover(store, generations, key, job):
    current = archive.read_state(store)["active"]
    prior = job["prior"]
    if current is not None and (prior is None or current["generation"] != prior["generation"]):
        if current["digest"] != job.get("candidate"):
            return "superseded"
    if prior is None:
        if current is None:
            return "no-prior-core"
        # No last working generation exists on a failed first installation.
        (store / archive.STATE).unlink()
        archive.sync_directory(store)
        return "no-prior-core"
    source = archive.local_path(generations / prior["generation"])
    restored = archive.install_locked(store, generations, source / "archive.zip", source / "archive.sig", key,
                                      current, expected=prior)
    verify_health(restored)
    restored_state = archive.read_state(store)
    if restored_state["previous"] != job.get("prior_previous"):
        archive.activate(store, restored_state["active"], job.get("prior_previous"))
    try:
        job["workspace_recovery"] = apply_job(job, undo=True)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        job["workspace_recovery"] = "manual-reconciliation"
        return "manual-reconciliation"
    return "previous-verified"


def inspect_jobs(store):
    folder = store / "operations"
    if not folder.exists():
        return []
    archive.check_private_dir(folder)
    records = []
    for path in sorted(folder.glob("*.json")):
        if not re.fullmatch(r"[0-9a-f]{32}", path.stem):
            raise ValueError("Unrecognized release operation")
        data = decode(archive.regular(path).read_bytes())
        if data["incident"] != path.stem:
            raise ValueError("Invalid release operation identity")
        records.append((path, data))
    return records


def reconcile(store, generations, key, base, token):
    results = []
    for path, job in inspect_jobs(store):
        if job["status"] == "running":
            # A process can die after activating but before the final health receipt.
            current = archive.read_state(store)["active"]
            try:
                if current and job.get("candidate") == current["digest"]:
                    complete(store, generations, job)
                else:
                    job.update(status="failed", step="interrupted", recovery=recover(store, generations, key, job))
            except (OSError, ValueError, subprocess.SubprocessError, archive.zipfile.BadZipFile):
                try:
                    outcome = recover(store, generations, key, job)
                except (ValueError, OSError, subprocess.SubprocessError, archive.zipfile.BadZipFile):
                    outcome = "manual-reconciliation"
                job.update(status="failed", step="interrupted", recovery=outcome)
            save(path, job)
        if job["status"] == "failed" and job["channel"] == binding(base):
            deliver(path, job, base, token)
            results.append(current_receipt(job))
    return results


def update(store, base, key_path, download_token, report_token, workspace=None):
    base = endpoint(base)
    store = archive.store_root(store)
    if workspace is not None:
        workspace, _ = workspace_update.validate(workspace, os.environ.get("ORYX_WORKSPACE_ID"))
        if workspace == store or store in workspace.parents or workspace in store.parents:
            raise ValueError("Core store and selected Workspace overlap")
    key = archive.trusted_key(key_path, store)
    with archive.locked(store) as generations:
        reconcile(store, generations, key, base, report_token)
        state = archive.read_state(store)
        prior = state["active"]
        job = {"incident": uuid4().hex, "status": "running", "step": "discover", "version": "unknown",
               "kind": "update", "prior": prior, "prior_previous": state["previous"], "channel": binding(base), "candidate": None, "recovery": "unused", "delivery": "pending"}
        path = operations(store) / (job["incident"] + ".json")
        save(path, job)
        try:
            record = release_record(decode(request(base, "latest", download_token)))
            job.update(version=record["version"], candidate=record["archive"], step="download")
            save(path, job)
            if prior:
                prior_version = tuple(map(int, prior["version"].split(".")))
                version = tuple(map(int, record["version"].split(".")))
                if version < prior_version or version == prior_version and record["archive"] != prior["digest"]:
                    raise ValueError("Advertised version conflicts with installed release history")
            with tempfile.TemporaryDirectory(dir=generations) as name:
                folder = Path(name)
                bundle = downloaded(base, record, "archive", download_token, folder)
                signature = downloaded(base, record, "signature", download_token, folder)
                job["step"] = "verify"
                save(path, job)
                archive.verify_signature(bundle, signature, key)
                with archive.zipfile.ZipFile(bundle) as signed:
                    if archive.manifest_for(signed)["version"] != record["version"]:
                        raise ValueError("Channel version differs from authenticated manifest")
                if workspace is not None:
                    job["step"] = "compatibility"
                    save(path, job)
                    job["workspace"] = workspace_update.prepare(workspace, job["incident"],
                                                               prior["version"] if prior else None, record["version"])
                job["step"] = "activate"
                save(path, job)
                core = archive.install_locked(store, generations, bundle, signature, key, prior,
                                              expected={"digest": record["archive"]}, preactivate=verify_health)
                job["step"] = "health"
                save(path, job)
                complete(store, generations, job)
        except (ValueError, KeyError, OSError, URLError, subprocess.SubprocessError, archive.zipfile.BadZipFile):
            try:
                outcome = recover(store, generations, key, job)
            except (ValueError, OSError, subprocess.SubprocessError, archive.zipfile.BadZipFile):
                outcome = "manual-reconciliation"
            job.update(status="failed", recovery=outcome)
        save(path, job)
        deliver(path, job, base, report_token)
        return current_receipt(job)


def rollback(store, key_path):
    store = archive.store_root(store)
    key = archive.trusted_key(key_path, store)
    with archive.locked(store) as generations:
        jobs = inspect_jobs(store)
        # Resume a killed rollback from its durable intent on the same invocation.
        running = [(p, j) for p, j in jobs if j["status"] == "running"]
        if running:
            if len(running) != 1 or running[0][1].get("kind") != "rollback":
                raise ValueError("Resume the interrupted update with retry-reports first")
            path, job = running[0]
        else:
            state = archive.read_state(store)
            previous = state["previous"]
            if previous is None:
                raise ValueError("No previous verified Core release")
            active = state["active"]
            parent = next((j for _, j in jobs if j.get("activated_generation") == active["generation"]
                           and j["status"] == "succeeded" and j.get("prior")
                           and j["prior"]["digest"] == previous["digest"]), {})
            job = {"incident": uuid4().hex, "kind": "rollback", "status": "running", "step": "activate",
                   "version": previous["version"], "prior": active, "prior_previous": previous,
                   "target": previous, "channel": parent.get("channel"), "candidate": previous["digest"],
                   "workspace": parent.get("workspace"), "reverse": not parent.get("reverse", False),
                   "delivery": "unused", "recovery": "unused"}
            path = operations(store) / (job["incident"] + ".json")
            save(path, job)
        state = archive.read_state(store)
        if state["active"]["digest"] != job["candidate"]:
            if state["active"] != job["prior"]:
                raise ValueError("Core changed outside the interrupted rollback")
            target = job["target"]
            source = archive.local_path(generations / target["generation"])
            archive.check_private_dir(source)
            archive.install_locked(store, generations, source / "archive.zip", source / "archive.sig", key,
                                   state["active"], expected=target, preactivate=verify_health)
        complete(store, generations, job)
        save(path, job)
        return {"core": str(archive.current(store)), "workspace_recovery": job["workspace_recovery"],
                "workspace_git_ref": job["workspace"]["ref"] if job.get("workspace") else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    for action in ("update", "rollback", "status", "retry-reports"):
        command = subs.add_parser(action)
        command.add_argument("--store", type=Path, required=True)
        if action != "status":
            command.add_argument("--public-key", type=Path, required=True)
        if action == "update":
            command.add_argument("--workspace", type=Path)
        if action in {"update", "retry-reports"}:
            command.add_argument("--endpoint", required=True)
    args = parser.parse_args(argv)
    if args.action == "update":
        result = update(args.store, args.endpoint, args.public_key, os.environ.get(TOKENS[0]), os.environ.get(TOKENS[1]),
                        workspace=args.workspace or os.environ.get("ORYX_WORKSPACE"))
    elif args.action == "rollback":
        result = rollback(args.store, args.public_key)
    elif args.action == "status":
        store = archive.store_root(args.store)
        result = {"core": archive.read_state(store), "updates": [current_receipt(j) for _, j in inspect_jobs(store)]}
    else:
        store = archive.store_root(args.store)
        key = archive.trusted_key(args.public_key, store)
        with archive.locked(store) as generations:
            result = reconcile(store, generations, key, args.endpoint, os.environ.get(TOKENS[1]))
    print(json.dumps(result, sort_keys=True))
    if isinstance(result, dict) and (result.get("status") == "failed" or result.get("workspace_recovery") == "manual-reconciliation"):
        return 1
    return 0
