"""Remember customer-selected scope identities without persisting access, membership or shared records."""
from contextlib import contextmanager
import fcntl
import os
import re
import time
from uuid import UUID

from oryx.governance.common import canonical, digest, identifier, shape
from oryx.governance.files import directory, read, save, DirLock
from .location import workspace_id


HOME = ".oryx/state/valet-connections"
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def key(provider, scope):
    if provider not in {"peer", "github"}:
        raise ValueError("Choose an enrolled customer peer or GitHub scope")
    return digest(canonical([provider, identifier(scope)]))


def validate(private, value, name):
    shape(value, ("workspace", "provider", "scope", "authority", "revision"), ("actor","sync","branch","replica"))
    if (value["workspace"] != workspace_id(private) or name != key(value["provider"], value["scope"]) + ".json"
            or not isinstance(value["revision"], str) or not COMMIT.fullmatch(value["revision"])):
        raise ValueError("Scope connection identity or revision differs from its Workspace")
    if value["provider"] == "github":
        authority = shape(value["authority"], ("repository","organization"))
        if any(type(v) is not int or v <= 0 for v in authority.values()):
            raise ValueError("Invalid enrolled GitHub repository or organization identity")
    else:
        identifier(value["authority"])
    if "replica" in value and (value["provider"] != "github" or not isinstance(value["replica"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", value["replica"])):
        raise ValueError("Invalid shared replica generation")
    if "branch" in value:
        if value["provider"] != "github":
            raise ValueError("Only GitHub connections specify an official branch")
        identifier(value["branch"])
    if "actor" in value:
        if value["provider"] == "github":
            if type(value["actor"]) is not int or value["actor"] <= 0:
                raise ValueError("Invalid connected GitHub account")
        else:
            identifier(value["actor"])
    if "sync" in value:
        job = shape(value["sync"], ("state", "attempt_ns", "success_ns"))
        if job["state"] not in {"due","pending","current"} or any(
                n is not None and (type(n) is not int or n <= 0) for n in (job["attempt_ns"], job["success_ns"])):
            raise ValueError("Unrecognized connection synchronization receipt")
    return value


def recorded(private, provider, scope):
    path = directory(private, HOME) / (key(provider, scope) + ".json")
    if path.is_symlink():
        raise ValueError("Scope connection redirects outside its record")
    return validate(private, read(path), path.name) if path.exists() else None


def store(private, value, previous):
    name = key(value["provider"], value["scope"]) + ".json"
    validate(private, value, name)
    folder = directory(private, HOME, True)
    # A stale partial receipt after power loss belongs in the Git-private lease
    # directory. Only the final atomic replacement enters the visible inventory.
    staging = directory(private, ".git/oryx-scope-sync/" + key(value["provider"], value["scope"]), True)
    if staging.stat().st_dev != folder.stat().st_dev:
        staging = folder
    save(folder / name, value, expected=previous, staging=staging)
    return value


@contextmanager
def lease(private, provider, scope):
    # The stable lease survives atomic replacement of the receipt and releases on process death.
    folder = directory(private, ".git/oryx-scope-sync/" + key(provider, scope), True)
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("The connection already has an active synchronization")
        yield
    finally:
        os.close(fd)


def observe(scope, provider, previous):
    from oryx.governance import client, github
    if provider == "github":
        info = github.run("github-status", {"scope":scope})
        authority = {"repository":info["repository_id"], "organization":info["organization_id"]}
        revision, actor = info["official_revision"], info["actor_id"]
    else:
        info = client.request("scope", {"scope":scope}, expected_organization=previous and previous["authority"])
        authority, revision, actor = info["organization"], info["revision"], info["actor"]
    if (info["scope"] != scope or previous and (authority != previous["authority"]
            or previous.get("actor", actor) != actor
            or provider == "github" and previous.get("branch", info["official_branch"]) != info["official_branch"])):
        raise ValueError("The verified authority or current actor differs from the saved scope connection")
    return info, authority, revision, actor


def manage(private, action, provider, scope):
    previous = recorded(private, provider, scope)
    if action == "show":
        try:
            current, _, _, _ = observe(scope, provider, previous)
        except (OSError, KeyError, ValueError, RuntimeError):
            if provider == "github" and previous and "replica" in previous:
                with lease(private, provider, scope):
                    if recorded(private, provider, scope) == previous:
                        invalidate(private, previous)
            raise
        return {"current": current, "connection": previous}
    if action == "disconnect" and previous is None:
        return {"disconnected":scope, "provider":provider}
    if action == "sync" and previous is None:
        raise ValueError("No verified connection to this scope in the selected Workspace")
    with lease(private, provider, scope):
        previous = recorded(private, provider, scope)
        if action == "disconnect":
            if previous is None:
                return {"disconnected":scope, "provider":provider}
            if provider == "github":
                from . import replicas
                replicas.forget(private, previous)
            path = directory(private, HOME) / (key(provider, scope)+".json")
            with DirLock(path.parent):
                if read(path) != previous:
                    raise ValueError("Scope connection changed during disconnection")
                path.unlink()
                fd = os.open(path.parent,os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            return {"disconnected":scope, "provider":provider}
        # Explicit reconnect retries an interrupted sync. Newly connected scopes
        # start at their verified head and run on the next eligible session.
        if (action == "connect" and previous and "actor" in previous
                and (provider != "github" or "branch" in previous)):
            action = "sync"
        sync = (previous or {}).get("sync", {"state":"due","attempt_ns":None,"success_ns":None})
        if action == "sync":
            if not previous or "actor" not in previous or provider == "github" and "branch" not in previous:
                raise ValueError("Connect the enrolled scope under the PM’s current identity first")
            sync = {**sync, "state":"pending", "attempt_ns":time.time_ns()}
            previous = store(private, {**previous,"sync":sync}, previous)
        replica = None
        if action == "sync" and provider == "github":
            from oryx.governance.github import fetch_replica
            from . import replicas
            try:
                current, documents = fetch_replica(previous)
                revision = current["official_revision"]
                actor, authority = previous["actor"], previous["authority"]
                replica = replicas.publish(private, previous, revision, documents)
            except (OSError, KeyError, ValueError, RuntimeError):
                invalidate(private, previous)
                raise
        else:
            current, authority, revision, actor = observe(scope, provider, previous)
        if action == "sync":
            if provider != "github":
                from oryx.governance.client import request
                current = request("sync", {"scope":scope, "expected_actor":actor}, expected_organization=authority)
                revision = current["revision"]
            if current["scope"] != scope:
                raise ValueError("The authority returned a different scope")
            sync = {**sync, "state":"current", "success_ns":time.time_ns()}
        value = {"workspace":workspace_id(private), "provider":provider, "scope":scope, "authority":authority,
                 "revision":revision, "actor":actor, "sync":sync}
        if provider == "github":
            value["branch"] = previous["branch"] if action == "sync" else current["official_branch"]
        if replica:
            value["replica"] = replica
        result = {"current":current, "connection":store(private,value,previous)}
        if replica:
            replicas.prune(private, value, keep=replica)
        return result


def invalidate(private, previous):
    from . import replicas
    if previous and "replica" in previous:
        value = {k:v for k,v in previous.items() if k != "replica"}
        value["sync"] = {**previous["sync"], "state":"pending"}
        store(private, value, previous)
    replicas.prune(private, previous)


def github_record(private, body, binding):
    from oryx.governance import github
    from . import replicas
    shape(body, ("scope","id"), ("revision",))
    with lease(private, "github", body["scope"]):
        current = recorded(private, "github", body["scope"])
        if current is None or current["workspace"] != binding["workspace"] or "branch" not in current:
            raise ValueError("Reconnect the current GitHub scope before reading the shared replica")
        try:
            client = github.connect()
            reg, _ = github.verify_binding(client, current)
            result = client.perform("github-record", body)
            # The current registered path, authority and exact remote bytes still govern a cache hit.
            latest = github.connect()
            confirmed, path = github.verify_binding(latest, current)
            if confirmed != reg:
                raise ValueError("GitHub registration changed while reading the record")
            tip = latest.tip(path, confirmed)
            if "revision" in body:
                latest.descendant(path, result["commit"], tip)
            elif tip != result["commit"]:
                raise ValueError("The official GitHub revision changed while reading the record")
            if current["sync"]["state"] == "current" and result["commit"] == current["revision"] == tip:
                result["record"] = replicas.record(private, current, body["id"],
                                                   confirmed["records"][body["id"]], result["record"])
            return result
        except (OSError, KeyError, ValueError, RuntimeError):
            invalidate(private, current)
            raise


def connection_entries(private):
    folder = directory(private, HOME)
    if folder.exists():
        for path in sorted(folder.iterdir()):
            yield path.relative_to(private).as_posix(), validate(private, read(path), path.name)


def checked_paths(private):
    return {name for name, _ in connection_entries(private)}


def local_scopes(private):
    root = directory(private, ".oryx/state/scopes")
    values = {}
    for path in sorted(root.iterdir()) if root.exists() else ():
        value = read(path)
        shape(value, ("id", "type", "parent", "membership"))
        if (path.name != str(UUID(value["id"])) + ".json" or value["membership"] != "local-only"
                or value["type"] not in {"company", "function", "team", "user"}):
            raise ValueError("Invalid local scope registration")
        values[value["id"]] = value
    parents = {"company":{None}, "function":{"company"}, "team":{"company","function"},
               "user":{"company","function","team"}}
    for value in values.values():
        parent = value["parent"]
        if (parent is not None and parent not in values
                or (values[parent]["type"] if parent else None) not in parents[value["type"]]):
            raise ValueError("The local scope hierarchy has an unverified parent")
    return list(values.values())


def inventory(private):
    return {"local": local_scopes(private), "connections": [
        value for _, value in connection_entries(private)]}
