# Initiative tasks and launch checklists

Use the product and initiative slugs from the signed register or the product-owned initiative overview. Each initiative has two JSON lists beside its briefs.
Carry existing tasks into the list when the PM confirms the records and their status.

| Record | Purpose | Completion |
| --- | --- | --- |
| `tasks.json` | Work the PM owns or coordinates | Record what was delivered and who owned it. |
| `launch-checklist.json` | Readiness checks and downstream follow-through | Record verification evidence or an approved waiver. |

Link engineering tickets in `source`. Engineering keeps status and technical details in its tracker. Record the PM's coordination work here.

## Manage tasks

Use a stable slug for each task. Name the outcome and its completion criteria. Record the owner and due date when confirmed. Keep unknown fields empty.

Use `depends_on` for other tasks in this initiative. Review unfinished dependencies, high-priority work, and due dates before recommending a next action. Record external blockers in `blocked_reason` and cite their source. [GitHub issue dependencies](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-issue-dependencies)

Use `todo`, `in-progress`, `blocked`, `done`, or `cancelled`. A blocked task needs a reason. Done and cancelled tasks need a resolution. A done task also needs an owner.

## Review launch readiness

Start from the shared checklist. Tailor the criteria to the launch scope. Add checks for the teams, approvals, dependencies, or risks that apply.

| Phase | Typical evidence |
| --- | --- |
| `upstream` | Confirmed dependencies, launch scope, approvals, and team enablement |
| `launch` | Rollout plan, rollback or containment, dashboard and test alerts |
| `downstream` | Support handoff, follow-up owners, measurements and outcome review |

Use `pending`, `blocked`, `verified`, or `waived`. A verified check needs an owner and `verification` with `evidence`, `by`, and `on`. A waived check needs `waiver` with `reason`, `by`, and `on`. Use dates through today. Clear obsolete evidence fields when reopening.

Link supporting tasks with `tasks`. Completing an alert setup task records delivery. A test alert and its receipt can verify the monitoring checkpoint.

Include upstream and launch phases. The view shows readiness after both phases clear. The PM makes the decision. Review downstream checks after rollout.

### Evidence changes

Saved material edits retain previous evidence and blockers in each list. Previewing an edit leaves the records untouched.
A task's second completion retains its withdrawal. Recheck the affected checkpoint before signing.

By default, verification relies on every linked task. To cite independent evidence, set `verification.basis_tasks` to matching task IDs or `[]`.
Name the independent source in `verification.evidence`. A linked task with changed evidence needs a fresh verification statement.
The task owner and named verifier retain their own roles. History records the date of the saved change.

### Ship decision

Use `/pm delivery launch review PRODUCT INITIATIVE` or ask “Are we ready to ship?”

The ship proposal includes a scoped revision, upstream and launch checks, evidence history, waivers, and outstanding risks.
Its `advisories` preserve active signal and context risks, their cited claims, authorities and current dispositions.
Review missing phases, unresolved checks removed from scope, and attestations dated after the effective ship date.
Use the PM’s stated reason and approving authority for each outstanding ID in `ship.exceptions`.

```json
{"exceptions":{"missing:checklist":{"reason":"The incident commander verified rollback in drill R4.","authority":"Incident PM"}}}
```

Changes to a scoped advisory or its cited context evidence require a fresh proposal.
Advisories inform the PM’s judgment. Only outstanding readiness IDs require a signed exception.
The PM signs the [reviewed decision](initiative-approvals.md#propose-and-approve).
Use `/pm initiative record show` to read the signed evidence after launch. Downstream changes continue separately.

### Existing records

Existing version-1 lists remain readable. Preview the first edit, then save it to start a version-2 history.
The new list preserves the exact prior text in `legacy_original`. To recover it, extract that UTF-8 string into a separate file.
Verify the recovered copy against your private backup before restoring it. Update each client before sharing new lists or signed ship decisions.

Recheck linked verifications without a recorded task basis. Earlier signed releases retain their original evidence gaps.
History starts with known records. External withdrawals need a saved update and source.

## Use the commands

```sh
python3 tools/pm.py task list PRODUCT INITIATIVE --format markdown
python3 tools/pm.py launch-checklist init PRODUCT INITIATIVE --preview
python3 tools/pm.py launch-checklist init PRODUCT INITIATIVE
python3 tools/pm.py launch-checklist list PRODUCT INITIATIVE --format markdown
```

Read the current JSON view and revision. Supply `absent` for a new list. Preview the edits before saving.

```sh
python3 tools/pm.py task apply PRODUCT INITIATIVE --revision REVISION --preview < edits.json
python3 tools/pm.py task apply PRODUCT INITIATIVE --revision REVISION < edits.json
```

Use the same operations for `launch-checklist apply`. Submit an array with one `add` or `update` per ID. Updates supply only changed fields.

```json
[
  {
    "id": "set-up-test-alert",
    "action": "add",
    "fields": {
      "title": "Coordinate a test billing alert",
      "completion_criteria": "The on-call team receives and acknowledges the test alert.",
      "owner": "Billing PM"
    }
  }
]
```

A new checkpoint needs `title`, `phase`, and `criterion`. Both lists accept `owner`, `due_on`, and `source`. Task `priority` accepts `high`, `normal`, and `low`.

If the revision changed, read the latest list and reconcile the edits. After a Git conflict, rerun `pm.py check` before sharing.
