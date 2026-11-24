# Search for task context

Codex and Claude use the same local search on each scoped task. Ask the question in your own words.
oryx ships an English embedding model with the system checkout. Existing private records need no conversion.

The resolver first identifies the company, product, area, or initiative. A follow-up can reuse the saved session scope.
An ambiguous request returns possible subjects. A named record or exact identifier keeps its existing routing priority.

## Choose evidence for the activity

Start with the PM’s purpose and the decisions they already made. A direct lookup can take one search.
For a broader request, identify the questions that could change the answer. Search the authorised records for each.
Follow confirmed relationships when a question needs wider context. Preserve the scope of every claim you use.

For product strategy, check the company objective, the product’s contribution, and the customer problem in the PM’s scope.

For “Did Refunds get better?”, first look for what the PM agreed would count as better.
If the agreed outcome was fewer support contacts, look for the measure, cohort, baseline, and comparable result.
A pilot result speaks for its participants and period. A product-wide trend alone cannot establish the pilot’s effect.

When two outcomes fit and the PM has not chosen one, ask which outcome they want to assess.
If an essential figure is missing, offer to check an agreed source. Continue work supported by the available evidence.

When a search finds no match, describe what you checked. Leave the underlying question open.
Carry a documented exclusion forward with its original scope and timing.

For a question about the PM, use `pm.py pm-profile --topic responsibilities` or the relevant profile topic.
Use `pm.py pm-profile` to list older or handwritten sections. Ask before opening a section that mixes personal subjects.
Consult the [stakeholder map](stakeholders.md) when a reporting line or decision role affects the task.

## How search selects passages

Within that scope, the resolver compares eligible passages by wording and meaning.
It uses the title, heading, and valid section lead to interpret short passages.
It checks selected notes against the current source file and returns the complete entry with its source references.
Company boundaries, applicable rules, and closed decisions have first claim on the available space.

Use each entry’s `evidence_status`, exact wording, source date, and scope when explaining it.
Company lookups also surface relevant, unresolved onboarding questions. Preserve their follow-up cues.
Carry an attached open question alongside its claim into later conversations. Ask before relying on conflicting or incomplete evidence.

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
