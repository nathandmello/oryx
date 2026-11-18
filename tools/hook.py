"""Run the same read-only check through Codex and Claude lifecycle hooks."""

import json
from pathlib import Path
import sys

import pm


def response(event, errors, retry=False):
    if event not in ("SessionStart", "Stop"):
        raise ValueError("Expected SessionStart or Stop")
    if not errors:
        return {}
    detail = "\n".join(errors[:8])
    if len(errors) > 8:
        detail += f"\n{len(errors) - 8} more error(s). Run python3 tools/pm.py check."
    message = "PM Hub checks failed:\n" + detail
    if event == "Stop" and not retry:
        return {"decision": "block", "reason": message + "\nFix these errors, then run the check again."}
    if event == "Stop":
        message += "\nReport the unresolved checks. Do not claim the work passed."
    return {"systemMessage": message}


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook input must be an object")
        event = payload["hook_event_name"]
        retry = payload.get("stop_hook_active", False)
        if not isinstance(retry, bool):
            raise ValueError("stop_hook_active must be a boolean")
        root = Path(__file__).resolve().parents[1]
        cwd = Path(payload.get("cwd", str(root))).resolve()
        if root != cwd and root not in cwd.parents:
            raise ValueError("Start the session inside this PM Hub checkout")
        print(json.dumps(response(event, pm.check(root), retry)))
        return 0
    except Exception as exc:
        print(f"PM Hub hook failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
