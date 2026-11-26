# Private session journal

Use the journal when you want Oryx to remember your conversation on this machine. Recording starts after you enable it.

```sh
python3 tools/pm.py journal enable
python3 tools/pm.py journal status
python3 tools/pm.py journal retention 30
```

Trust the project hooks in your client. A submitted PM message enters the journal immediately. The completed assistant reply enters when the client delivers it. Recording runs silently during normal work. Context and cache suggestions have separate controls.

Say “off the record” to pause the current client session, including that request. Say “back on the record” to resume with your next request. The other client keeps its own session policy.

```sh
python3 tools/pm.py journal pause --client claude --session SESSION_ID
python3 tools/pm.py journal resume --client claude --session SESSION_ID
python3 tools/pm.py journal disable
```

## Recover a conversation

Name the work you want to continue. A reviewed handoff identifies its objective, open question, scope, and next action. A linked exchange supplies the most recent messages from the same work and permission interval.
The first returned message reports how many earlier events were omitted when the handoff reaches its limit.

For an explicit session inspection, choose the client and its session ID. The command shows the latest 20 turns. Use `--limit` to change this number.

```sh
python3 tools/pm.py journal show --client codex --session SESSION_ID
python3 tools/pm.py journal reference --client codex --session SESSION_ID --scope JOURNAL_SCOPE
```

Use the exact `journal_scope` returned for the selected handoff. The second command returns only a matching reference. To attach an unscoped exchange, first review the exact exchange and destination. Run `journal attach` with its client, session, `--event`, `--scope JOURNAL_SCOPE`, and `--approved`.

A missing reply appears as a gap. When available, Oryx checks the client’s own transcript from that submission’s saved file position. It accepts a completed reply only within that turn. A missing file, interrupted stream, ambiguous speaker, or changed file can leave a gap.

The journal records visible human and assistant text. It excludes tool events, delegated output, private reasoning, attachments, and client metadata from conversation text. Recognized credential patterns and oversized messages produce gaps. Use off-record mode for sensitive discussion.

## Storage and deletion

Your local state directory holds one owner-only journal per Studio checkout. On Unix, the base is `$XDG_STATE_HOME/oryx/journals` or `~/.local/state/oryx/journals`. Oryx backups, general context search, and Git exports omit it. Restoring Studio elsewhere restores reviewed handoffs. Local transcript references can be unavailable there.

Retention defaults to 90 days. Launching the journal hooks or running a journal command expires old turns. Expiry removes their text, checkpoints, and lookup entries together. Shortening retention takes effect immediately.

```sh
python3 tools/pm.py journal prune
python3 tools/pm.py journal delete --client codex --session SESSION_ID
python3 tools/pm.py journal delete-all
```

Deletion removes Oryx’s journal copies. Your client controls its own history. Disabling recording stops recovery and hides saved conversations until you enable recording again. Use deletion to erase them.


## Manage a moved or removed Studio

A moved or newly created Studio starts with recording disabled. The original journal stays in your local state directory.
Recording requires a filesystem that reports directory creation time. On other filesystems, status explains the limitation and session pauses still work.

Before moving Studio, run `journal status` to see its store ID. After a move, list owner-local store IDs and modification times from your terminal.

```sh
python3 tools/pm.py journal stores
python3 tools/pm.py journal prune --store STORE_ID
python3 tools/pm.py journal delete-store STORE_ID
```

These commands also work from a core checkout without Studio. Choose the exact store ID for maintenance.
Pruning applies that store’s retention period. Deleting the store erases its conversations, pauses, and recording consent.
