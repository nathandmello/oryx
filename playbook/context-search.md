# Search for task context

Codex and Claude use the same local search on each scoped task. Ask the question in your own words.
oryx ships an English embedding model with the system checkout. Existing private records need no conversion.

The resolver first identifies the company, product, area, or initiative. A follow-up can reuse the saved session scope.
An ambiguous request returns possible subjects. A named record or exact identifier keeps its existing routing priority.

When a search finds no match, describe what you checked. Leave the underlying question open.
Carry a documented exclusion forward with its original scope and timing.

Within that scope, the resolver compares eligible passages by wording and meaning.
It uses the title, heading, and valid section lead to interpret short passages.
It checks selected notes against the current source file and returns the complete entry with its source references.
Company boundaries, applicable rules, and closed decisions have first claim on the available space.
Check cited records when evidence conflicts or the response reports a gap.

Risk reviews use the evidence journal and signed initiative records. They can apply even when a passage ranks below the search cutoff.
Use `--history` to include recorded dispositions for the current scope.

The catalog lists records independently of search. Capture, metric definitions, and approval checks use their existing procedures.
If prompt hooks are unavailable, the agent runs the usual command:

```sh
python3 tools/pm.py task-context --product checkout "How often do we revisit what customers pay?"
```

For diagnostics, add `--explain`. The output identifies the retrieval method, candidate count, and additional records.
The standard hook response excludes these diagnostics.

## Local storage and recovery

The model runs offline using Python. oryx caches routing fields, eligible note passages, and embeddings in a disposable per-account database.
On POSIX, the database lives in a restricted directory under the system temporary directory.
On Windows, it lives under the account's local application data. Private workspace backups exclude this cache.

The resolver checks the current Git inventory and file identity each time. Changes, moves, and deletions take effect on the next lookup.
A restored workspace builds its own cache.

A busy or unavailable cache permits live retrieval. A missing or damaged model permits lexical retrieval.
A large cold search can reach the optional scoring time limit. The resolver returns available matches and retains completed work.
The PM does not need to rebuild an index or start a service.

See the [model provenance and license](../tools/search_model/README.md).
