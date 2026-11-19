"""Keep the evidence considered in launch reviews and in signed ship decisions."""

from datetime import date
import hashlib
import json


GATE_PHASES = ('upstream', 'launch')


def digest(value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def material(row):
    # Scheduling and display changes do not change evidence.
    return {key: value for key, value in row.items() if key not in {'priority', 'due_on'}}


def task_basis(row):
    if row['status'] != 'verified':
        return []
    return row['verification'].get('basis_tasks', row['tasks'])


def task_token(row, history):
    return {"entries": len(history), "revision": digest([material(row), history])}


def audit_rows(before, after, histories, changes, tasks, task_history, *, checklist):
    """Prepare audit entries alongside the rows for one atomic file replacement."""
    updated = dict(histories)
    for change in changes:
        key = change['id']
        old, row = before.get(key), after[key]
        history = list(histories.get(key, []))
        previous = history[-1] if history else None
        reaffirmed = checklist and 'verification' in change['fields'] and row['status'] == 'verified'
        basis = previous.get('basis') if previous else None
        if checklist and (reaffirmed or old is None or row['status'] != 'verified'):
            basis = {task: task_token(tasks[task], task_history.get(task, [])) for task in task_basis(row)}
        if (reaffirmed and old and old['status'] == 'verified' and previous and previous.get('basis') != basis
                and old['verification']['evidence'] == row['verification']['evidence']):
            raise ValueError('Cite fresh verification evidence or explain the independent basis after a task changed')
        state = material(row)
        if old is not None and material(old) == state and (not reaffirmed or (previous and previous.get('basis') == basis)):
            continue
        if old is not None and previous is None:
            history.append({'recorded_on': None, 'state': material(old)})
        entry = {'recorded_on': date.today().isoformat(), 'state': state}
        if checklist and row['status'] == 'verified' and basis is not None:
            entry['basis'] = basis
        if checklist and old and task_basis(old):
            # Preserve the former task evidence even when a verifier removes its link.
            entry['prior_tasks'] = {task: task_record(tasks[task], task_history.get(task, [])) for task in task_basis(old)}
        updated[key] = [*history, entry]
    return updated


def task_record(row, history):
    return {'current': material(row), 'history': history}


def validate_history(rows, histories, validate_state):
    if not isinstance(histories, dict) or not histories.keys() <= rows.keys():
        raise ValueError('Launch evidence history must refer to existing record IDs')
    for key, entries in histories.items():
        if not isinstance(entries, list) or not entries:
            raise ValueError(f'{key}: give the recorded evidence history in order')
        for entry in entries:
            if (not isinstance(entry, dict) or not {'state', 'recorded_on'} <= entry.keys()
                    or entry.keys() - {'state', 'recorded_on', 'basis', 'prior_tasks'}
                    or not isinstance(entry['state'], dict) or ('basis' in entry and not isinstance(entry['basis'], dict))):
                raise ValueError(f'{key}: invalid evidence history entry')
            if 'basis' in entry and any(
                not isinstance(token, dict) or token.keys() != {'entries', 'revision'}
                or type(token['entries']) is not int or token['entries'] < 0 or not isinstance(token['revision'], str)
                for token in entry['basis'].values()
            ):
                raise ValueError(f'{key}: invalid recorded task revision')
            state = entry['state']
            if state.keys() != material(rows[key]).keys():
                raise ValueError(f'{key}: evidence history has incomplete fields')
            validate_state(state)
            if 'prior_tasks' in entry:
                prior_tasks = entry['prior_tasks']
                if not isinstance(prior_tasks, dict) or any(
                    not isinstance(task, dict) or task.keys() != {'current', 'history'}
                    or not isinstance(task['current'], dict) or not isinstance(task['history'], list)
                    for task in prior_tasks.values()
                ):
                    raise ValueError(f'{key}: invalid former task evidence')
            if entry['recorded_on'] is not None:
                try:
                    date.fromisoformat(entry['recorded_on'])
                except (TypeError, ValueError):
                    raise ValueError(f'{key}: invalid evidence recording date') from None
        if entries[-1]['state'] != material(rows[key]):
            raise ValueError(f'{key}: current evidence differs from its saved history. Reconcile the original records.')


def concerns(row, history, tasks, task_history, effective_on):
    issues = []
    if row['status'] in {'blocked', 'pending'}:
        issues.append(row['blocked_reason'] or 'Checkpoint is pending verification.')
    if row['status'] in {'verified', 'waived'}:
        proof = row['verification'] or row['waiver']
        if proof['on'] > effective_on:
            issues.append('The attestation is dated after the effective ship date.')
    if row['status'] == 'verified':
        basis = history[-1].get('basis', {}) if history else {}
        for key in task_basis(row):
            task = tasks[key]
            recorded = task_history.get(key, [])
            previous = basis.get(key)
            if previous != task_token(task, recorded):
                issues.append(f'{key}: review the linked evidence and reaffirm this verification.')
                start = previous['entries'] if previous else 0
                for entry in recorded[start:]:
                    change = entry['state']
                    if change['blocked_reason']:
                        issues.append(f"{key}: recorded blocker on {entry['recorded_on'] or 'an unknown date'}: {change['blocked_reason']}")
            if task['status'] != 'done':
                issues.append(f"{key}: {task['status']}. {task['blocked_reason'] or 'Completion evidence is outstanding.'}")
    return issues


def snapshot(checks, check_history, tasks, task_history, *, present, effective_on, reviewed_on=None):
    checkpoints, linked_tasks, outstanding, removed = {}, {}, {}, {}
    phases = set()
    for key, row in sorted(checks.items()):
        history = check_history.get(key, [])
        if row['phase'] not in GATE_PHASES:
            # Preserve the removal itself without binding subsequent downstream edits.
            gated = [i for i, entry in enumerate(history) if entry['state'].get('phase') in GATE_PHASES]
            if gated:
                last = gated[-1]
                crossing = history[last + 1]
                removed[key] = history[:last + 2]
                prior_tasks = crossing.get('prior_tasks', {})
                old = history[last]['state']
                if set(task_basis(old)) - prior_tasks.keys():
                    raise ValueError(f'{key}: recover missing task evidence for the scope change')
                problems = concerns(old, history[:last + 1],
                                    {task: entry['current'] for task, entry in prior_tasks.items()},
                                    {task: entry['history'] for task, entry in prior_tasks.items()}, effective_on)
                if problems or crossing['state']['status'] in {'blocked', 'pending'}:
                    outstanding['scope:' + key] = ['Removed from launch scope with unresolved readiness.',
                                                    *problems]
            continue
        phases.add(row['phase'])
        checkpoints[key] = {'current': material(row), 'history': history}
        for task in task_basis(row):
            linked_tasks[task] = task_record(tasks[task], task_history.get(task, []))
        problems = concerns(row, history, tasks, task_history, effective_on)
        if problems:
            outstanding['check:' + key] = problems
    if not present:
        outstanding['missing:checklist'] = ['No launch checklist was recorded.']
    else:
        for phase in GATE_PHASES:
            if phase not in phases:
                outstanding['missing:' + phase] = [f'No {phase} checkpoints were recorded.']
    facts = {'checklist_present': present, 'checkpoints': checkpoints, 'linked_tasks': linked_tasks,
             'removed_from_scope': removed, 'outstanding': outstanding}
    return {**facts, 'revision': digest(facts), 'reviewed_on': reviewed_on or date.today().isoformat()}


def validate_snapshot(value):
    keys = {'checklist_present', 'checkpoints', 'linked_tasks', 'removed_from_scope', 'outstanding'}
    if (not isinstance(value, dict) or value.keys() != keys | {'revision', 'reviewed_on'}
            or type(value['checklist_present']) is not bool
            or any(not isinstance(value[key], dict) for key in keys - {'checklist_present'})
            or value['revision'] != digest({key: value[key] for key in keys})):
        raise ValueError('Invalid signed launch readiness snapshot')
    try:
        reviewed = date.fromisoformat(value['reviewed_on'])
        if reviewed > date.today() or reviewed.isoformat() != value['reviewed_on']:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Invalid launch readiness review date') from None


def require_exceptions(event):
    outstanding = event['readiness']['outstanding']
    exceptions = event.get('exceptions', {})
    if outstanding.keys() != exceptions.keys():
        raise ValueError('Review each outstanding launch risk. Give its exact ID, reason and authority in ship exceptions: '
                         + ', '.join(sorted(outstanding)))
