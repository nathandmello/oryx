"""Exercise old signed decisions, untracked version-1 lists, and launch scope changes."""

from datetime import date, timedelta
import json
import os
import unittest
from unittest.mock import patch

import test_opportunities


class LaunchCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.h = test_opportunities.InitiativeTests()
        self.addCleanup(self.h.doCleanups)
        self.h.setUp()
        h = self.h
        h.submit(h.setup_event(), h.capture(), h.decision(
            'expedite', owner='Service PM', obligation='Restore regional receipt delivery', deadline=h.today,
            scope='Renewal canary', review_on=h.today, delivery='https://example.com/drills/renewal'))
        self.ship = h.decision('ship', review_on=h.today)
        self.proof = {'evidence': 'Pager receipt for regional drill R1.', 'by': 'Duty engineer', 'on': h.today}

    def show(self, kind):
        return json.loads(self.h.cli(kind, 'list', 'example', 'renewal'))

    def edit(self, kind, change, *args, error=None):
        revision = self.show(kind)['revision']
        output = self.h.cli(kind, 'apply', 'example', 'renewal', '--revision', revision, *args, value=[change], error=error)
        return json.loads(output) if error is None else output

    def as_legacy(self, kind, field):
        path = self.h.work / self.show(kind)['path']
        body = json.loads(path.read_bytes())
        original = json.dumps({key: body[key] for key in ('product', 'initiative', field)} | {'version': 1},
                              ensure_ascii=False, indent=3) + '\r\n'
        path.write_bytes(original.encode())
        return path, original

    def test_legacy_ship_replays_without_a_backfilled_review_or_signed_rewrite(self):
        h = self.h
        envelope = json.loads(h.ledger.read_bytes())
        envelope['record']['events'].append(self.ship)
        with patch.dict(os.environ, h.env):
            envelope['signature'] = test_opportunities.pm.initiative_store.sign(h.root, envelope['record'], h.key)
        h.ledger.write_text(json.dumps(envelope))
        before = h.ledger.read_bytes()
        trace = json.loads(h.cli('action', 'initiative', 'record', 'show', 'example', h.i))['initiative']
        self.assertEqual(trace['decisions'][-1], self.ship)
        self.assertIn('not recorded', trace['launch_review'])
        self.assertEqual(h.ledger.read_bytes(), before)
        self.assertIn('PASS', h.cli('check'))

    def test_existing_lists_preview_recover_exact_bytes_and_review_missing_basis(self):
        task = {'id': 'receipt', 'action': 'add', 'fields': {'title': 'Check receipt', 'owner': 'Duty engineer',
                'completion_criteria': 'Verify alert in region one', 'status': 'done', 'resolution': 'Receipt R1 arrived'}}
        self.edit('task', task)
        check = {'id': 'monitor', 'action': 'add', 'fields': {'title': 'Check regional monitor', 'owner': 'Duty engineer',
                 'criterion': 'Verify regional alert delivery', 'tasks': ['receipt'], 'phase': 'launch',
                 'status': 'verified', 'verification': self.proof}}
        self.edit('launch-checklist', check)
        task_file, old_task = self.as_legacy('task', 'tasks')
        check_file, old_check = self.as_legacy('launch-checklist', 'checkpoints')
        proposed = self.h.preview(self.ship)['reviewed_transactions'][0]['readiness']
        self.assertEqual(set(proposed['outstanding']), {'missing:upstream', 'check:monitor'})
        update = {'id': 'receipt', 'action': 'update', 'fields': {'status': 'blocked', 'resolution': None,
                                                                  'blocked_reason': 'Region one receipt was withdrawn'}}
        self.assertIn('version 2', self.edit('task', update, '--preview')['format_note'])
        self.assertEqual(task_file.read_bytes(), old_task.encode())
        self.assertEqual(check_file.read_bytes(), old_check.encode())
        self.edit('task', update)
        self.assertEqual(json.loads(task_file.read_bytes())['legacy_original'].encode(), old_task.encode())
        self.edit('task', {'id': 'receipt', 'action': 'update', 'fields': {
            'status': 'done', 'blocked_reason': None, 'resolution': 'Receipt R2 arrived'}})
        self.assertEqual(json.loads(task_file.read_bytes())['legacy_original'].encode(), old_task.encode())
        refreshed = self.edit('launch-checklist', {'id': 'monitor', 'action': 'update', 'fields': {
            'verification': {**self.proof, 'evidence': 'Regional canary report R2 confirmed receipt.'}}})
        self.assertEqual(refreshed['checkpoints'][0]['review_issues'], [])
        self.assertEqual(json.loads(check_file.read_bytes())['legacy_original'].encode(), old_check.encode())
        self.assertIn('PASS', self.h.cli('check'))

    def test_unchanged_review_can_be_signed_the_following_day(self):
        h = self.h
        proposal = h.preview(h.ship_without_checklist())
        store = test_opportunities.pm.initiative_store

        class FollowingDay(date):
            @classmethod
            def today(cls):
                return date.today() + timedelta(days=1)

        with patch.dict(os.environ, h.env), patch.object(store.launch_readiness, 'date', FollowingDay):
            store.apply(h.root, 'example', proposal, h.key)
        self.assertEqual(h.trace()['initiative']['decisions'][-1]['readiness']['reviewed_on'], h.today)

    def test_change_during_signature_never_publishes_the_old_snapshot(self):
        h = self.h
        store = test_opportunities.pm.initiative_store
        from_original = store.sign
        proposal = h.preview(h.ship_without_checklist())
        before = h.ledger.read_bytes()
        target = h.work / 'workspace/initiatives/example/renewal/launch-checklist.json'

        def delayed_sign(root, payload, key):
            signature = from_original(root, payload, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({'version': 1, 'product': 'example', 'initiative': 'renewal', 'checkpoints': {}}))
            return signature

        with patch.dict(os.environ, h.env), patch.object(store, 'sign', delayed_sign):
            with self.assertRaisesRegex(ValueError, 'while approval was pending'):
                store.apply(h.root, 'example', proposal, h.key)
        self.assertEqual(h.ledger.read_bytes(), before)
        self.assertEqual(h.trace()['initiative']['phase'], 'delivery')

    def test_unresolved_gate_moved_downstream_keeps_its_risk_and_scope_history(self):
        for key, phase in [('briefing', 'upstream'), ('monitor', 'launch'), ('rollback', 'launch')]:
            fields = {'title': f'Check {key}', 'owner': 'Duty engineer', 'criterion': f'Confirm {key}',
                      'phase': phase, 'status': 'verified', 'verification': self.proof}
            if key == 'monitor':
                fields.update(status='blocked', blocked_reason='Regional alert route is unavailable', verification=None)
            self.edit('launch-checklist', {'id': key, 'action': 'add', 'fields': fields})
        moved = self.edit('launch-checklist', {'id': 'monitor', 'action': 'update', 'fields': {'phase': 'downstream'}})
        self.assertEqual(moved['launch_readiness'], 'pending')
        first = self.h.preview(self.ship)
        readiness = first['reviewed_transactions'][0]['readiness']
        self.assertIn('scope:monitor', readiness['outstanding'])
        self.assertIn('Regional alert route', str(readiness['removed_from_scope']))
        self.h.apply(first, error='scope:monitor')
        self.edit('launch-checklist', {'id': 'monitor', 'action': 'update', 'fields': {
            'status': 'verified', 'blocked_reason': None, 'verification': self.proof}})
        self.assertEqual(first, self.h.preview(self.ship))
        self.h.submit({**self.ship, 'exceptions': {'scope:monitor': {
            'reason': 'This region stays offline during the internal drill.', 'authority': 'Release PM'}}})
        self.assertIn('scope:monitor', self.h.trace()['initiative']['decisions'][-1]['exceptions'])
