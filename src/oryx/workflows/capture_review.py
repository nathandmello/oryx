"""Review native pending onboarding findings in the foreground of the selected Workspace."""

import json
import os
import stat

from oryx.review import cli, store


class Prepared(Exception):
    """Stop the native renderer at its first proposed file mutation, before any write."""

    def __init__(self, record):
        self.record = record


def candidate(private, target, original, text):
    if target.resolve() != target or not target.is_relative_to(private):
        raise ValueError("Use an unredirected onboarding record in the selected Workspace")
    before = None
    if os.path.lexists(target):
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                or info.st_mode & 0o7022 or os.listxattr(target) or info.st_size > store.MAX_METADATA):
            raise ValueError("Review requires a bounded, individually owned regular onboarding document")
        before = target.read_bytes().decode("utf-8")
    normalized = None if before is None else before.replace("\r\n", "\n").replace("\r", "\n")
    if original not in (before, normalized) or (text is not None and len(text.encode()) > store.MAX_METADATA):
        raise ValueError("The original document changed or exceeds the review limit")
    return {"path": target.relative_to(private).as_posix(), "before": before, "text": text,
            "base": None if before is None else store.sha(before.encode()),
            "after": None if text is None else store.sha(text.encode())}


DECISIONS = ".oryx/state/capture-decisions"


def checked_paths(private):
    from oryx.workspace.location import workspace_id

    folder = private / DECISIONS
    if not os.path.lexists(folder):
        return set()
    if folder.resolve() != folder:
        raise ValueError("Use an unredirected onboarding decision directory")
    store.checked_directory(folder, private=True)
    paths = set()
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in os.listdir(fd):
            key = name.removesuffix(".json")
            if not store.HEX.fullmatch(key) or name != key + ".json":
                raise ValueError("Unexpected onboarding decision file")
            raw = store.read_fd(fd, name, 1024)
            record = json.loads(raw, object_pairs_hook=store.unique)
            if (not isinstance(record, dict) or set(record) != {"workspace", "kind", "revision", "review", "path", "base", "after"}
                    or store.sha(raw) != key or record["workspace"] != workspace_id(private)
                    or record["kind"] not in {"company", "product", "pm"}
                    or type(record["revision"]) is not int or record["revision"] < 1
                    or not isinstance(record["path"], str) or not record["path"].endswith(".md")
                    or not all(isinstance(digest, str) and store.HEX.fullmatch(digest)
                               for digest in [record["review"], record["after"]] + ([record["base"]] if record["base"] is not None else []))):
                raise ValueError("Invalid onboarding review decision")
            paths.add((folder / name).relative_to(private).as_posix())
    finally:
        os.close(fd)
    return paths


def record_approval(private, shown):
    import storage

    change = shown["change"]
    folder = private / DECISIONS
    if folder.resolve() != folder:
        raise ValueError("Use the selected Workspace decision directory")
    for path in (folder.parent, folder):
        path.mkdir(mode=0o700, exist_ok=True)
        store.checked_directory(path, private=True)
    data = store.encoded({"workspace": shown["workspace"], "kind": shown["kind"], "revision": shown["revision"],
                          "review": store.sha(store.encoded(shown)), **{key: change[key] for key in ("path", "base", "after")}})
    target = folder / (store.sha(data) + ".json")
    storage.require_visible(private, target.relative_to(private))
    try:
        store.publish_file(target, data, mode=0o400)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != data:
            raise ValueError("An existing onboarding decision differs. Preserve it before continuing")


def review_accept(root, private, state, owner, lint, kind, *, original, operation, question):
    import company_onboarding
    import storage
    from oryx.workspace.location import workspace_id

    store.pm_only()
    if not state["pending"]:
        raise ValueError("Preview a finding before reviewing it")
    if os.environ.get("PM_HUB_SHARED_GROUP"):
        raise ValueError("Exact onboarding review requires an individually owned Workspace")
    identity = workspace_id(private)
    try:
        terminal = cli.tty_session()
    except OSError as error:
        raise ValueError(f"The finding remains pending. Open {kind}-onboarding {operation} in the PM terminal "
                         f"with --revision {state['revision']}" +
                         (" and --question with the exact open question" if question else "")) from error
    # One original checkpoint identifies one finding. The generated record kind distinguishes
    # a new product from its area. Dates, custom templates and source-dependent text are rerendered.
    draft_token = store.sha(store.encoded([identity, kind, store.sha(original)]))[:12]
    pending = state["pending"]
    with terminal:
        # A new area may first need its own product brief. The native owner renders that
        # independent record first and validates the area against the saved parent next.
        for _ in range(2):
            def render():
                if company_onboarding.read(private, kind)[0] != original or workspace_id(private) != identity:
                    raise ValueError("The pending onboarding review or selected Workspace changed")
                def stage(target, prior, text):
                    raise Prepared(candidate(private, target, prior, text))
                try:
                    changed = company_onboarding.accept(root, private, state, owner, lint, kind, publish=stage, draft_token=draft_token)
                except Prepared as result:
                    return result.record
                if changed is not False:
                    raise ValueError("The native onboarding capture did not yield a reviewable document")
                target = private / pending["destination"]
                current = target.read_bytes().decode() if target.is_file() else None
                if current is None:
                    raise ValueError("An unchanged finding must exist at its reviewed destination")
                return candidate(private, target, current, current)

            planned = render()
            parent = planned["path"] == pending.get("creates_parent")
            shown = {"workspace": identity, "kind": kind, "operation": operation, "revision": state["revision"],
                     "source_scope": pending["source_scope"], "source": pending["source"],
                     "verification": pending["verification"], "finding": pending["entry"], "question": question,
                     "risk_review": pending.get("risk_preview"), "change": planned,
                     "effect": ("Save the new product brief. Its first area finding follows in a separate review."
                                if parent else "Save this exact finding and advance the pending onboarding review.")}
            terminal.write(b"Review this exact local change. JSON escapes represent exact characters.\n")
            terminal.write(json.dumps(shown, ensure_ascii=True, indent=2).encode() + b"\n")
            terminal.write(b"Type save or later and press Return: ")
            if terminal.readline(32).strip() != b"save":
                raise ValueError("The finding remains pending. Open the current onboarding revision to resume")
            if render() != planned:
                raise ValueError("The current source or document changed. Reopen the pending review")
            record_approval(private, shown)
            if planned["before"] != planned["text"]:
                expected = planned["before"].encode() if planned["before"] is not None else None
                storage.replace_text(private / planned["path"], expected, planned["text"], durable=True)
            if not parent:
                return
    raise ValueError("Reopen the pending review to confirm the next proposed record")
