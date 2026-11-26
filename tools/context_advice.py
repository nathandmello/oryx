"""Suggest a client action at a PM milestone using a recent, session-local observation."""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from time import time

import overrides
import pm_profile
import storage
import workspace

MAX_AGE = 5 * 60
HIGH_WINDOW = 80
LONG_WINDOW = 50
LONG_INPUT = 64000
CLIENTS = ("claude", "codex")
NEXT_STEPS = ("continue", "break", "unrelated", "inspect")
# Only the PM's attribution at the beginning of the request can supply a terminal reading.
STATUS_REPORT = re.compile(r"^\s*(?:my|our) (?:codex )?/status (?:shows|says|reports) "
                           r"(\d{1,3}(?:\.\d+)?)\s*% (?:of (?:the )?context )?(?:left|remaining)\b", re.I)


def digest(value):
    return sha256(value.encode()).hexdigest()


def state_path(private, client, session):
    if client not in CLIENTS or not isinstance(session, str) or not session or len(session) > 256:
        raise ValueError("Supply the current client and session")
    return pm_profile.safe_path(private, ".state/context-advice/" + digest(client + "\0" + session) + ".json")


def read(path):
    if not path.is_file():
        return None, {}
    raw = path.read_bytes()
    state = storage.json_input(raw)
    if not isinstance(state, dict):
        raise ValueError("Invalid session signal")
    return raw, state


def count(value):
    return type(value) is int and 0 <= value < 2**63


def percentage(value):
    return type(value) in (int, float) and 0 <= value <= 100


def update(private, client, session, turn, action, fields=None):
    """Apply ordered observations. Compaction invalidates earlier inputs, including late callbacks."""
    path = state_path(private, client, session)
    key = digest(turn) if isinstance(turn, str) and turn else None
    with storage.writer_lock(private):
        raw, state = read(path)
        if action in {"start", "reset"}:
            if action == "start" and not state:
                return
            state = {"generation": state.get("generation", 0) + 1, "barrier": True,
                     "blocked_turn": key or state.get("blocked_turn"),
                     "previous_turn": state.get("turn") or state.get("previous_turn")}
        elif action == "turn":
            if raw is None or not key or key in (state.get("blocked_turn"), state.get("previous_turn")):
                return
            state.update(barrier=False, turn=key)
        else:
            # After compaction require a new identified prompt before accepting measurements.
            if state.get("barrier") or state.get("generation") and not key:
                return
            if state.get("turn") and key and state["turn"] != key:
                return
            if key:
                state["turn"] = key
            now = int(time())
            for name, value in fields.items():
                if value is None:
                    state.pop(name, None)
                else:
                    state[name] = [value, now]
        encoded = json.dumps(state, sort_keys=True) + "\n"
        if raw != encoded.encode():
            storage.replace_text(path, raw, encoded, mode=0o600)


def observe_hook(private, client, payload):
    """Use documented main-session hook fields only. Optional telemetry cannot block the PM."""
    if private is None or client not in CLIENTS or payload.get("agent_type") or payload.get("agent_id"):
        return
    session = payload.get("session_id")
    if not session:
        return
    event = payload.get("hook_event_name")
    turn = payload.get("turn_id") if client == "codex" else payload.get("prompt_id")
    try:
        if event in {"PreCompact", "PostCompact"} or event == "SessionStart" and payload.get("source") in {"compact", "clear"}:
            update(private, client, session, turn, "reset")
        elif event == "SessionStart" and payload.get("source") in {"resume", "startup"}:
            update(private, client, session, turn, "start")
        elif event == "UserPromptSubmit":
            update(private, client, session, turn, "turn")
            if client == "codex":
                prompt = payload.get("prompt")
                report = STATUS_REPORT.match(prompt) if isinstance(prompt, str) else None
                if report and percentage(left := float(report[1])):
                    update(private, client, session, turn, "report", {"pm_used": 100 - left})
        elif client == "codex" and event == "PostModelRequest" and payload.get("status") == "completed":
            usage = payload.get("token_usage")
            last = usage.get("input_tokens") if isinstance(usage, dict) else None
            update(private, client, session, turn, "request", {"last_input": last if count(last) else None})
    except (ValueError, OSError, RuntimeError):
        return


def observe_claude(private, payload):
    if not isinstance(payload, dict) or payload.get("agent"):
        return None
    window = payload.get("context_window")
    if not isinstance(window, dict):
        return None
    used = window.get("used_percentage")
    cache = payload.get("prompt_cache")
    cache = cache if isinstance(cache, dict) else {}
    expiry = cache.get("expires_at")
    # A historical cache read never establishes a live warm prefix.
    warm_until = expiry if cache.get("warm") is True and count(expiry) else None
    size = cache.get("recache_tokens_if_cold")
    fields = {"used": used if percentage(used) else None, "warm_until": warm_until,
              "recache": size if count(size) else None}
    update(private, "claude", payload.get("session_id"), payload.get("prompt_id"), "statusline", fields)
    return fields["used"]


def observe_codex_event(private, session, payload):
    """Accept an event from the App Server connection that owns this thread."""
    if not isinstance(payload, dict) or not isinstance(payload.get("params"), dict):
        return
    method, params = payload.get("method"), payload["params"]
    if not session or params.get("threadId") != session:
        return
    if method == "turn/started" and isinstance(params.get("turn"), dict):
        update(private, "codex", session, params["turn"].get("id"), "turn")
        return
    turn = params.get("turnId")
    if not turn:
        return
    if method == "thread/compacted" or (method == "item/completed" and isinstance(params.get("item"), dict)
                                        and params["item"].get("type") == "contextCompaction"):
        update(private, "codex", session, turn, "reset")
    elif method == "thread/tokenUsage/updated":
        usage = params.get("tokenUsage") or {}
        if not isinstance(usage, dict) or not isinstance(usage.get("last"), dict):
            return
        size, last = usage.get("modelContextWindow"), usage["last"].get("totalTokens")
        used = min(100, 100 * last / size) if count(size) and size > 0 and count(last) else None
        update(private, "codex", session, turn, "app-server", {"used": used, "pm_used": None})


def recent(state, field, now):
    sample = state.get(field)
    if (isinstance(sample, list) and len(sample) == 2 and type(sample[1]) is int
            and 0 <= now - sample[1] <= MAX_AGE):
        return sample[0]
    return None


def suggestion(client, state, next_step, preserve, now):
    reported = recent(state, "pm_used", now)
    used = reported if reported is not None else recent(state, "used", now)
    used = used if percentage(used) else 0
    last = recent(state, "last_input", now)
    recache = recent(state, "recache", now)
    expiry = recent(state, "warm_until", now)
    long_thread = used >= LONG_WINDOW or count(last) and last >= LONG_INPUT or count(recache) and recache >= LONG_INPUT
    remaining = f"{100 - used:.0f}% of the context window remains"
    focus = preserve or "the agreed decisions, their sources, and the next open question"
    if next_step == "unrelated" and long_thread:
        return "fresh", "Your next task is unrelated. Start it in a fresh session to give it its own context."
    if next_step == "break" and client == "claude" and long_thread and count(expiry) and expiry > now:
        return "warm-break", ("Claude reports a warm prompt cache. Before your break, you could use "
                              f"`/compact` to preserve {focus}. This can reduce uncached rereading on return.")
    if next_step == "continue" and used >= HIGH_WINDOW:
        if client == "claude":
            return "compact", f"Only {remaining}. Before the next phase, you could use `/compact` and ask it to retain {focus}."
        source = "Your /status reading" if reported is not None else "The latest Codex usage report"
        return "compact", f"{source} indicates {remaining}. You could run `/compact` before starting the next phase."
    if next_step == "inspect" and client == "codex":
        return "inspect", "Run `/status` to see how much context remains in this Codex session."
    return None


def candidates(private, client, session, *, next_step, preserve=None):
    """Build a transient offer. The shared selector controls timing, mute, and delivery."""
    if next_step not in NEXT_STEPS:
        return []
    try:
        if not overrides.context_advice_allowed(private, "native"):
            return []
        path = state_path(private, client, session)
        raw, state = read(path)
        if state.get("barrier") and next_step != "inspect":
            return []
        now = int(time())
        result = suggestion(client, state, next_step, preserve, now)
        if not result:
            return []
        action, message = result
        token = digest(f"{path.stem}/{state.get('generation', 0)}/{action}")
        until = min((sample[1] + MAX_AGE for key, sample in state.items()
                     if recent(state, key, now) is not None), default=now + MAX_AGE)
        if action == "warm-break":
            until = min(until, state["warm_until"][0] - 1)
        revision = sha256(raw or b"").hexdigest()
        return [{"workflow": "context-advice", "token": token, "source_kind": "native",
                 "observation": [path.stem, revision, until],
                 "priority": 65, "offer": {"status": "offer", "action": action, "message": message}}]
    except (ValueError, OSError, RuntimeError):
        return []


def still_current(private, candidate):
    """Recheck the signal under the selector lock before reserving a tip."""
    key, revision, until = candidate["observation"]
    if not re.fullmatch(r"[a-f0-9]{64}", key) or int(time()) > until:
        return False
    path = pm_profile.safe_path(private, ".state/context-advice/" + key + ".json")
    raw, _ = read(path)
    return sha256(raw or b"").hexdigest() == revision


def add_commands(commands):
    cmd = commands.add_parser("context-advice", help="Consider an optional client action at a task milestone")
    cmd.set_defaults(hub_action=run)
    opts = cmd.add_subparsers(dest="operation", required=True)
    consider = opts.add_parser("consider", help="Select at most one offer for this pause")
    consider.add_argument("--client", choices=CLIENTS)
    consider.add_argument("--session")
    consider.add_argument("--next-step", choices=NEXT_STEPS, required=True)
    consider.add_argument("--preserve", help="Reviewed handoff wording for this compact suggestion")
    consider.add_argument("--mode", choices=("thought-partner", "quiet", "expedite"))
    consider.add_argument("--moment", choices=("busy", "pause"), default="pause")
    consider.add_argument("--pause", help="The pause ID shared by optional workflows")


def run(root, args, prepare_write):
    import offer_queue
    import task_context
    private = workspace.repo(root, "workspace")
    client = args.client or os.environ.get("PM_HUB_CLIENT")
    session = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID" if client == "claude" else "CODEX_THREAD_ID")
    if client not in CLIENTS or not session:
        raise ValueError("Supply the current client and session ID")
    scope = task_context.previous_scope(private, session)
    saved_mode = scope.get("mode") or scope.get("work_mode")
    mode = saved_mode if saved_mode in {"quiet", "expedite"} else args.mode or "thought-partner"
    with storage.writer_lock(private):
        offers = candidates(private, client, session, next_step=args.next_step, preserve=args.preserve)
        result = offer_queue.select(private, offers, mode=mode, moment=args.moment, pause=args.pause)
    print(json.dumps(result, ensure_ascii=False))


def main():
    """Protected host entry point. Read one bounded notification, dropping unrelated fields."""
    if sys.argv[1:] not in (["claude-statusline"], ["codex-event"]):
        return 2
    root = Path(__file__).resolve().parents[1]
    client = "claude" if sys.argv[1] == "claude-statusline" else "codex"
    if os.environ.get("PM_HUB_PROTECTED_ROOT") != str(root) or os.environ.get("PM_HUB_CLIENT") != client:
        return 0
    try:
        private = workspace.repo(root, "workspace")
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            return 0
        data = storage.json_input(raw)
        if client == "claude":
            used = observe_claude(private, data)
            if used is not None:
                print(f"Context {used:.0f}% used")
        else:
            observe_codex_event(private, os.environ.get("CODEX_THREAD_ID"), data)
    except (ValueError, OSError, RuntimeError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
