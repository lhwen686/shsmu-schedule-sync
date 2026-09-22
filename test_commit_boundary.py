"""Inject actual filesystem failures through import/service, using temp data only."""
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import sync
from core import export_ics
from desktop_service import DesktopService
from prepare import BROWSER_MODULES
from test_desktop import CONFIG, write_capture
from test_sync import LATER
from test_wakeup import item

DERIVED = ('data/schedule.json', 'output/calendar.ics',
           'output/changes.json', 'output/changes.txt')


@contextlib.contextmanager
def scenario(existing=False):
    with tempfile.TemporaryDirectory(prefix='commit-boundary-') as temp:
        root = Path(temp)
        service = DesktopService(root)
        service.initialize()
        service.save_settings(CONFIG)
        with patch('sync.publish_current', side_effect=AssertionError('Desktop must not upload')):
            if existing:
                service.run(capture=write_capture(root, [item(), item(2)]))
            before = sync.load_current(root)
            pointer = (root / 'data/current.json').read_bytes() if before else None
            changed = item()
            changed['event'].update(ID=502, MCSID='501,502')
            changed['details'][0].update(Teacher='新合成教师', CurriculumScheduleIDs='|501||502|')
            capture = write_capture(root, [changed], fetched=LATER)
            yield root, service, capture, before, pointer


@contextlib.contextmanager
def fail_replace(root, target, *, after_commit=True, once=False, cancel=None):
    """Fail the real atomic replacement, not an export-function test double."""
    real_replace = os.replace
    state = {'committed': not after_commit, 'failures': 0, 'attempts': []}

    def replace(src, dst):
        relative = Path(dst).relative_to(root).as_posix()
        state['attempts'].append(relative)
        if relative == target and state['committed'] and (not once or not state['failures']):
            state['failures'] += 1
            if cancel is not None:
                cancel.set()
            raise PermissionError('synthetic replace denied: ' + relative)
        real_replace(src, dst)
        if relative == 'data/current.json':
            state['committed'] = True

    with patch('os.replace', side_effect=replace):
        yield state


class CommitBoundaryTests(unittest.TestCase):
    def assert_history(self, root, before):
        current = sync.load_current(root)
        self.assertEqual(current['events'][0]['teacher'], '新合成教师')
        if before is not None:
            event = current['events'][0]
            self.assertEqual(event['uid'], before['events'][0]['uid'])
            self.assertEqual(event['sequence'], before['events'][0]['sequence'] + 1)
            self.assertTrue(set(before['events'][0]['identity_aliases']).issubset(event['identity_aliases']))
            self.assertEqual(len(current['cancelled_events']), 1)
            self.assertEqual(json.loads((root / 'data/previous.json').read_text('utf-8')), before)
        return current

    def assert_repaired(self, root, service, pointer, snapshot):
        runs = sorted((root / 'data/runs').iterdir())
        result = service.run(export_only=True)
        self.assertTrue(result['committed'])
        self.assertFalse(result['output_issues'])
        self.assertIsNone(result['issue'])
        self.assertIsNone(result['apple_issue'])
        self.assertEqual((root / 'data/current.json').read_bytes(), pointer)
        self.assertEqual(sync.load_current(root), snapshot)
        self.assertEqual(sorted((root / 'data/runs').iterdir()), runs)
        run = root / 'data/runs' / json.loads(pointer)['run_id']
        for target in DERIVED:
            self.assertEqual((root / target).read_bytes(), (run / Path(target).name).read_bytes())
        self.assertIsNotNone(service.ready_export())
        self.assertIsNotNone(service.ready_apple_export())

    def test_before_pointer_failure_never_commits_or_starts_format_exports(self):
        for existing in (False, True):
            for target in ('data/current.json', 'run-calendar'):
                with self.subTest(existing=existing, target=target), scenario(existing) as (root, service, capture, before, pointer):
                    real_replace = os.replace
                    def replace(src, dst):
                        rel = Path(dst).relative_to(root).as_posix()
                        if rel == target or (target == 'run-calendar' and rel.startswith('data/runs/') and rel.endswith('/calendar.ics')):
                            raise PermissionError('synthetic precommit failure')
                        return real_replace(src, dst)
                    with patch('os.replace', side_effect=replace), \
                            patch.object(service, '_apple_export_unlocked', wraps=service._apple_export_unlocked) as apple, \
                            patch.object(service, '_export_unlocked', wraps=service._export_unlocked) as wakeup:
                        with self.assertRaises(PermissionError):
                            service.run(capture=capture)
                        apple.assert_not_called()
                        wakeup.assert_not_called()
                    self.assertEqual(sync.load_current(root), before)
                    self.assertEqual((root / 'data/current.json').read_bytes() if before else None, pointer)

    def test_import_reports_each_postcommit_write_failure(self):
        for target in DERIVED:
            with self.subTest(target=target), scenario() as (root, service, capture, before, _):
                with sync.exclusive_sync(root), fail_replace(root, target) as fault:
                    result = sync.import_capture_unlocked(root, CONFIG, capture, progress=lambda _: None)
                self.assertGreater(fault['failures'], 0)
                self.assertTrue(result.committed)
                self.assertEqual(set(result.output_errors), {target})
                self.assertIsInstance(result.output_errors[target], PermissionError)
                self.assertEqual(sync.load_current(root), result.snapshot)
                for other in set(DERIVED) - {target}:
                    self.assertIn(other, fault['attempts'])

    def test_service_postcommit_failures_both_formats_reopen_and_repair(self):
        for existing in (False, True):
            for target in DERIVED:
                with self.subTest(existing=existing, target=target), scenario(existing) as (root, service, capture, before, _):
                    old_bytes = (root / target).read_bytes() if (root / target).exists() else None
                    with fail_replace(root, target) as fault:
                        result = service.run(capture=capture)
                    self.assertGreater(fault['failures'], 0)
                    self.assertTrue(result['committed'])
                    self.assertEqual(service.diagnostics.record['status'], 'partial')
                    snapshot = self.assert_history(root, before)
                    self.assertEqual((root / target).read_bytes() if (root / target).exists() else None, old_bytes)
                    self.assertIsNotNone(result['report'])
                    self.assertIsNone(result['issue'])
                    if target == 'output/calendar.ics':
                        self.assertIsNone(result['apple_report'])
                        self.assertIsNotNone(result['apple_issue'])
                    else:
                        self.assertIsNotNone(result['apple_report'])
                        self.assertIn(target, result['output_issues'])
                    reopened = DesktopService(root)
                    reopened.initialize()
                    self.assertIsNotNone(reopened.ready_export())
                    self.assertEqual(reopened.ready_apple_export() is None, target == 'output/calendar.ics')
                    self.assert_repaired(root, reopened, (root / 'data/current.json').read_bytes(), snapshot)

    def test_wakeup_write_failures_leave_apple_usable_and_old_csv_unready(self):
        for existing in (False, True):
            for target in ('output/wakeup.csv', 'output/wakeup导入说明.txt', 'local/desktop-export.json'):
                with self.subTest(existing=existing, target=target), scenario(existing) as (root, service, capture, before, _):
                    with fail_replace(root, target):
                        result = service.run(capture=capture)
                    self.assertTrue(result['committed'])
                    self.assertIsNotNone(result['apple_report'])
                    self.assertIsNone(result['report'])
                    self.assertIsNotNone(result['issue'])
                    reopened = DesktopService(root)
                    reopened.initialize()
                    self.assertIsNone(reopened.ready_export())
                    self.assertIsNotNone(reopened.ready_apple_export())
                    self.assert_repaired(root, reopened, (root / 'data/current.json').read_bytes(), self.assert_history(root, before))

    def test_duplicate_with_broken_outputs_does_not_require_new_capture(self):
        with scenario() as (root, service, capture, _, _):
            service.run(capture=capture)
            pointer = (root / 'data/current.json').read_bytes()
            snapshot = sync.load_current(root)
            with fail_replace(root, 'output/changes.txt', after_commit=False):
                result = service.run(capture=capture)
            self.assertTrue(result['imported'].duplicate)
            self.assertTrue(result['committed'])
            self.assertIn('output/changes.txt', result['output_issues'])
            self.assertIsNotNone(result['report'])
            self.assertIsNotNone(result['apple_report'])
            self.assert_repaired(root, service, pointer, snapshot)

    def test_cancel_before_commit_and_during_failed_postcommit_export(self):
        for existing in (False, True):
            with self.subTest(existing=existing), scenario(existing) as (root, service, capture, before, pointer):
                cancel = threading.Event()
                def observe(stage, value):
                    if stage == 'detail':
                        cancel.set()
                with self.assertRaises(sync.SyncCancelled):
                    service.run(capture=capture, cancel=cancel, emit=observe)
                self.assertEqual(sync.load_current(root), before)
                cancel.clear()
                with fail_replace(root, 'output/changes.txt', cancel=cancel):
                    result = service.run(capture=capture, cancel=cancel)
                self.assertTrue(cancel.is_set())
                self.assertTrue(result['committed'])
                self.assertIsNotNone(result['report'])
                self.assertIsNotNone(result['apple_report'])
                self.assert_repaired(root, service, (root / 'data/current.json').read_bytes(), self.assert_history(root, before))

    def test_one_shot_apple_failure_is_retried_and_not_reported_as_current_failure(self):
        with scenario() as (root, service, capture, _, _):
            with fail_replace(root, 'output/calendar.ics', once=True) as fault:
                result = service.run(capture=capture)
            self.assertEqual(fault['failures'], 1)
            self.assertTrue(result['committed'])
            self.assertIsNotNone(result['apple_report'])
            self.assertIsNone(result['apple_issue'])
            self.assertFalse(result['output_issues'])
            self.assertIn('output/calendar.ics', result['imported'].output_errors)
            self.assertEqual((root / 'output/calendar.ics').read_bytes(), export_ics(sync.load_current(root)))

    def test_state_write_failure_after_commit_still_attempts_both_formats(self):
        with scenario() as (root, service, capture, _, _):
            with fail_replace(root, 'local/desktop-state.json'):
                result = service.run(capture=capture)
            self.assertTrue(result['committed'])
            self.assertIn('local/desktop-state.json', result['output_issues'])
            self.assertIsNotNone(result['apple_report'])
            self.assertIsNotNone(result['issue'])
            self.assert_repaired(root, service, (root / 'data/current.json').read_bytes(), sync.load_current(root))

    def test_cli_reports_committed_failure_skips_upload_and_repairs(self):
        with scenario() as (root, service, capture, _, _):
            for name in BROWSER_MODULES:
                (root / name).write_bytes((service.resources / name).read_bytes())
            output = io.StringIO()
            with patch.object(sync, 'ROOT', root), \
                    patch('sync.publish_current') as upload, \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                with fail_replace(root, 'output/changes.txt'):
                    self.assertEqual(sync.main(['--capture', str(capture)]), 1)
                upload.assert_not_called()
                pointer = (root / 'data/current.json').read_bytes()
                self.assertIn('课表已保存', output.getvalue())
                self.assertIn('--repair', output.getvalue())
                self.assertEqual(sync.main(['--repair']), 0)
                self.assertEqual((root / 'data/current.json').read_bytes(), pointer)
                with fail_replace(root, 'output/calendar.ics', after_commit=False):
                    self.assertEqual(sync.main(['--repair']), 1)

    def test_rejected_account_never_reaches_output_repair_or_commit(self):
        with scenario(True) as (root, service, _, before, pointer):
            capture = write_capture(root, account='b' * 64, fetched=LATER)
            with fail_replace(root, 'output/changes.txt', after_commit=False) as fault:
                with self.assertRaisesRegex(sync.DataError, '账号'):
                    service.run(capture=capture)
            self.assertEqual(fault['failures'], 0)
            self.assertEqual(sync.load_current(root), before)
            self.assertEqual((root / 'data/current.json').read_bytes(), pointer)


if __name__ == '__main__':
    unittest.main()
