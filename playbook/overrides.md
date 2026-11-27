# Workspace overrides

Use the same private rules in Codex and Claude Code. Each rule has a stable identifier, a scope, and the requested behavior.
The PM can change how any skill works or teach oryx a new workflow in ordinary conversation.

## Start a PM session

Archive candidates use the [local CLI](installed-core.md). For source checkouts:

```sh
python3 tools/pm.py agent codex
python3 tools/pm.py agent claude
```

Linux and WSL2 require bubblewrap with working user namespaces. macOS uses sandbox-exec.
The launcher aligns Studio before startup. Core and [initiative approval receipts](initiative-approvals.md) are read-only during the session.

Run system updates from the PM's terminal. Use a separate development checkout for shared contributions.
Review and trust the project hooks. Use local filesystem tools for edits to oryx files.
Use the [available tools](ingestion.md#choose-an-external-tool) within the PM’s permissions.

For templates, fields, columns, and browser layouts, use [workspace customization](customization.md).

## Save and use a rule

“Going forward, open leadership meeting summaries with decisions” authorises a standing rule. Save it privately and revise the current summary.
“For this meeting” applies once. Keep quotations from transcripts and examples as evidence.

Name the activity and any limits the PM gave. Reuse the identifier for a revision within the same scope.
Use `--target weekly-review-order` on a second ID for a narrower exception to that behavior.

Use the most specific matching Studio rule, then company guidance, then core. Keep unrelated steps from each source.
The PM can customize the coaching, delegated work, and review steps for a named workflow.
A deadline alone changes none of them. Keep unrelated steps, evidence requirements, source permissions, and PM decision ownership.
The current request can make an exception for one task.

```sh
python3 tools/pm.py override set weekly-review-order --scope "Weekly reviews" --behavior "Put pending decisions first."
python3 tools/pm.py override list
```

Apply the rule immediately and on subsequent relevant turns. Both clients receive the same rules at prompt submission.
Use the effective rules from the list command when prompt hooks are unavailable.
The private repository stores rules, reporting receipts, and retired rules in `studio/customizations/rules.json`.

Silence profile prompts immediately with `pm.py override profile-suggestions off`. Use `--source transcript` for a narrower request. Offer optional feedback afterwards.

## Add a workflow

For “When I say Friday handoff, draft my update,” save the name, trigger, and requested steps.

```sh
python3 tools/pm.py override set friday-handoff --scope "When the PM asks for a Friday handoff" --behavior "Draft the Friday handoff." --steps "List pending decisions first. Then list blockers with owners. Leave the update as a draft."
```

Use `pm.py override show friday-handoff` to read its full procedure. Follow it for ordinary requests and `/pm workspace workflow open friday-handoff`.
If the PM withdraws the habit, use `pm.py override remove friday-handoff`. Core defaults resume where applicable.

A rule can change agent judgment or call existing tools. For a changed app or generated artifact, exercise its actual entry point.
If it needs new core support, explain the gap and follow the feedback process. Keep the PM's requirement active.

Keep longer procedures in `studio/customizations/skills/<name>/SKILL.md`. Register the trigger with `override set` and reference that file in its steps.
Both clients can then find the procedure from the same rule.

## Company working practices

A solo Studio needs no company setup. Import a local, versioned workflow file when colleagues share their working practices.

```json
{"format":1,"id":"product-ops","revision":1,"rules":{"weekly-review-order":{"scope":"Weekly reviews","behavior":"Start with decisions."}}}
```

Run `pm.py company import PATH`. Inspect the installed copy with `pm.py company show`.
Import a newer revision to update it. Use `pm.py company remove` to detach it.
A matching personal rule takes priority. Use the [Finance definition import](metrics.md#share-a-company-definition) for an official company metric.

If the installed company file is damaged, reimport a trusted copy or detach it. Your personal instructions remain available.

## Report a requirement

Enable reporting at the PM's request. Sign in to GitHub CLI for delivery. Saving works offline.

Feedback follows the same repository through its rename from `nathandmello/pm-hub` to `nathandmello/oryx`.
Open the link returned by the command to see the issue or comment on GitHub.
Reporting checks the owner, current name, and [repository ID](https://api.github.com/repositories/1463535158) before delivery. A mismatch keeps the report in Studio.

```sh
python3 tools/pm.py override reporting on
```

Saving a recognized request sends its built-in public description when reporting is enabled. Other requests need a preview. Review possible issue matches before sending.

For a new rule, describe the general requirement using fictional examples. Never copy private instructions or records into GitHub.
Exclude names, paths, customer evidence, and organisation details.
Show the exact proposed public title and body. Obtain approval for novel wording.
Search open issues in the shared oryx repository using the approved public description.

Choose an existing issue when its requirement matches. Use its number with `--issue` and supply the new detail in the body.
An explicit issue number checks for duplicate feedback on that issue. Saved receipts from either name work offline.
Use the same approved wording when retrying. Omit the issue number for a distinct requirement.

```sh
python3 tools/pm.py override report weekly-review-order --title "Configurable weekly review order" --body "Support placing pending decisions first." --approved
```

Review locally saved receipts with `override list`. A failed report leaves the rule active.
Retry queued reports with `python3 tools/pm.py override sync`. Use `override reporting off` to pause sends.

## Check after an update

The managed pull runs alignment. A direct pull receives the same check on the next session start.
Preview with `python3 tools/pm.py align --status`. See covered rules under `covered_overrides`.

Active rules override the corresponding core defaults. Releases publish [workflow defaults](workflow-defaults.json) for both clients.
Alignment retires an override only when core matches the target, scope, and complete behavior and removing it preserves the effective result.

Partial matches, optional features, conflicting conditions, and uncertain prose keep their overrides.
Review retired entries with `override list`. Restore one with `override set`.
