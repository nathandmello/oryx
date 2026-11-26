# Context and prompt cache

A context window holds the input available to one model request. A prompt cache can reduce the time and cost of processing earlier input.

At a milestone, consider the PM's next task and the latest signal from the current session. Finish the current work first.
Pass the candidate through the [shared offer selector](../tools/offer_queue.py). Quiet mode, expedited work, and a busy moment suppress delivery.
The PM chooses whether to compact or start a new session.

## Claude Code

Start a protected session with the Oryx context indicator when you want to share status-line measurements.

```sh
python3 tools/pm.py agent claude --context-statusline
```

This launch option selects an indicator for that run. An ordinary launch keeps your configured status line.
To keep a custom status-line script, send a copy of its JSON input to the collector inside that script.

```sh
# Use the JSON your existing script already read from stdin.
printf '%s' "$input" | python3 "$PM_HUB_PROTECTED_ROOT/tools/context_advice.py" claude-statusline >/dev/null
```

Claude supplies the window percentage. Recent versions also report whether the prompt cache is warm and when that reading expires.

A long thread and an upcoming break can justify compacting while the cache is warm. A cache miss alone needs no action.
At a milestone in a full window, suggest a focused `/compact`. Name the decisions or open question the PM wants to retain.
For a long thread followed by unrelated work, suggest starting a fresh session. [Claude status-line fields](https://code.claude.com/docs/en/statusline#prompt-cache-fields)

## Codex CLI

The protected terminal can report tokens used by the latest model request. Its request hook supplies no window capacity.
Use `/status` to inspect the remaining context. The PM can share a reading such as “My /status shows 12% left.”
Use a recent reading at the next milestone to suggest `/compact`. Cached input tokens describe the previous request. [Codex hooks](https://developers.openai.com/codex/hooks/) · [CLI commands](https://developers.openai.com/codex/cli/slash-commands/)

An App Server integration can forward individual notifications from its own connection to `tools/context_advice.py codex-event`.
Run the collector in the protected Codex workspace environment. Set `CODEX_THREAD_ID` to the connected thread.
It checks `PM_HUB_PROTECTED_ROOT` and `PM_HUB_CLIENT` before storing the window measurement.

Forward turn starts and completed compaction events too. The ordinary terminal receives its metrics through its project hooks. [App Server events](https://developers.openai.com/codex/app-server/)

## Delivery and control

The adviser considers 80% window use high. It refreshes evidence after compaction and ignores signals older than five minutes.
Signal files in Studio's ignored `.state/context-advice/` contain numeric observations, hashed identifiers, and timing.
Oryx keeps handoff wording in the current suggestion.

At a milestone, use the current session and client. Supply a reviewed handoff detail when available.

```sh
python3 tools/pm.py context-advice consider --next-step continue --preserve "the launch decision and its open pricing question"
```

Use `--session` and `--client` if the host omits their environment variables.
Use `offer decline TOKEN` to dismiss the suggestion. Use `override context-advice off` to mute future tips.
Use `override context-advice on` to restore them. The PM controls [workspace rules](overrides.md) and transcript capture independently.
