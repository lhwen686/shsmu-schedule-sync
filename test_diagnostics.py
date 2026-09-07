"""Support packages are tested as evidence, including redacted offline replay."""
import copy
import json
import os
import tempfile
import threading
import unittest
import zipfile
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import diagnostics
from core import DataError, normalize, reconcile
from desktop_service import DesktopService, DesktopJob
from diagnostics import DiagnosticRecorder, Redactor
from source import CaptureSource, SourceError
from sync import load_current, wait_capture
from test_desktop import CONFIG, write_capture
from test_sync import combined_fixture, mixed_fixture
from test_wakeup import item
from wakeup import build_export


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='诊断测试 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = DesktopService(self.root)
        self.service.initialize()
        self.service.save_settings(CONFIG)

    def package(self, log=None, **kwargs):
        log = log or self.service.diagnostics
        target = self.root / 'support.zip'
        log.export(target, **kwargs)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(set(archive.namelist()), {'summary.txt', 'manifest.json', 'events.jsonl', 'repro.json'})
            raw = b'\n'.join(archive.read(name) for name in archive.namelist()).decode('utf-8-sig')
            return (json.loads(archive.read('manifest.json')), json.loads(archive.read('repro.json'))['material'],
                    [json.loads(line) for line in archive.read('events.jsonl').splitlines()], raw)

    def test_success_package_has_full_timeline_and_no_original_text(self):
        capture = write_capture(self.root)
        original = json.loads(capture.read_text())
        self.service.run(capture=capture)
        manifest, material, events, raw = self.package()
        names = [e['event'] for e in events]
        for expected in ('operation_started', 'input_validated', 'month_read', 'detail_read', 'normalizing',
                         'reconciled', 'commit_started', 'commit_finished', 'apple_export_finished',
                         'wakeup_export_finished', 'operation_finished'):
            self.assertIn(expected, names)
        self.assertEqual(manifest['status'], 'success')
        self.assertIn('BROWSER_TRACE_MISSING', manifest['limitations'])
        self.assertEqual(material['input']['format'], 'shsmu-support-capture-v1')
        for record in original['responses']:
            values = record['response']['List'] if isinstance(record['response'], dict) else record['response']
            for value in values:
                for field in ('Curriculum', 'Teacher', 'Content', 'ClassroomAcademy'):
                    if value.get(field):
                        self.assertNotIn(value[field], raw)
        self.assertNotIn(str(self.root), raw)
        self.assertNotIn('a' * 64, raw)

    def test_redacted_normal_combined_and_mixed_material_replays_exports(self):
        for index, values in enumerate(([item()], combined_fixture(True), mixed_fixture())):
            with self.subTest(index=index):
                root = self.root / str(index)
                root.mkdir()
                service = DesktopService(root)
                service.initialize()
                service.save_settings(CONFIG)
                path = write_capture(root, values)
                service.run(capture=path)
                _, material, _, raw = self.package(service.diagnostics)
                output, _, report = build_export(material['committed'], material['bundle'])
                self.assertEqual(report['event_count'], len(values))
                self.assertTrue(output.startswith(b'\xef\xbb\xbf'))
                self.assertNotIn('本班教师', raw)
                if index == 1:
                    self.assertEqual(len(material['bundle']['items'][0]['details'][0]['ClassCode'].split()), 2)
                service.run(capture=path)
                _, repeated, _, _ = self.package(service.diagnostics)
                events = normalize(repeated['bundle']['items'], CONFIG['start'], CONFIG['end_exclusive'])
                _, diff = reconcile(events, repeated['previous'], repeated['previous']['scope'], '2026-09-07T12:00:00Z')
                self.assertEqual(diff['summary'], {'ADDED': 0, 'REMOVED': 0, 'CHANGED': 0})

    def test_failure_material_preserves_error_and_failed_item(self):
        values = mixed_fixture()
        values[0]['details'][1]['CurriculumScheduleIDs'] = '|11|'
        with self.assertRaises(DataError) as before:
            self.service.run(capture=write_capture(self.root, values))
        manifest, material, events, _ = self.package()
        with self.assertRaises(DataError) as after:
            normalize(material['bundle']['items'], CONFIG['start'], CONFIG['end_exclusive'])
        self.assertEqual(str(before.exception), str(after.exception))
        self.assertEqual(manifest['status'], 'failed')
        failure = next(e for e in events if 'exception' in e)
        self.assertEqual(failure['context']['index'], 1)
        self.assertTrue(any(f['file'] == 'core.py' for f in failure['exception']['frames']))
        self.assertIn('checks', failure['context'])

    def test_trace_only_changes_never_change_duplicate_or_uid(self):
        capture = write_capture(self.root)
        self.service.run(capture=capture)
        baseline = load_current(self.root)
        raw = json.loads(capture.read_text())
        for metadata in ({'schema_version': 1, 'request_log': []}, 'broken metadata'):
            raw['diagnostics'] = metadata
            capture.write_text(json.dumps(raw), encoding='utf-8')
            result = self.service.run(capture=capture)
            self.assertTrue(result['imported'].duplicate)
            self.assertEqual(load_current(self.root), baseline)

    def test_redaction_drops_secrets_paths_unknown_values_and_exception_message(self):
        log = self.service.diagnostics
        log.begin('sync')
        secret = 'PRIVATE_MUST_NEVER_APPEAR'
        payload = {'config': {**CONFIG, 'upload_url': 'https://example.test/' + secret},
                   'responses': [{'path': '/Home/GetCalendarTable', 'params': {'CSID': 100},
                                  'response': [{'Teacher': secret, 'Content': 'C:\\Users\\' + secret + '\\data',
                                                'Tel': secret, 'password': secret, 'StudentName': secret,
                                                'unknown': {'private': secret}, 'Cookie': secret}]}]}
        payload['responses'][0]['response'][0]['ClassTime'] = '13912345678'
        log.attach('input', payload)
        try:
            raise RuntimeError(secret)
        except RuntimeError as error:
            log.exception(error)
        log.finish('failed')
        _, _, _, raw = self.package()
        self.assertNotIn(secret, raw)
        self.assertNotIn('13912345678', raw)
        for path in log.directory.iterdir():
            self.assertNotIn(secret, path.read_text(encoding='utf-8'))

    def test_support_material_cannot_be_imported(self):
        for format in ('shsmu-support-v1', 'shsmu-support-capture-v1', 'shsmu-browser-support-v1'):
            path = self.root / 'repro.json'
            path.write_text(json.dumps({'format': format}), encoding='utf-8')
            with self.assertRaisesRegex(SourceError, '诊断文件'):
                CaptureSource(path, CONFIG)

    def test_reopen_recovers_records_and_marks_unfinished_operation(self):
        log = self.service.diagnostics
        log.begin('sync')
        log.event('waiting_started')
        operation_id = log.record['operation_id']
        reopened = DiagnosticRecorder(self.root)
        record = next(r for r in reopened.records() if r['operation_id'] == operation_id)
        self.assertEqual(record['status'], 'interrupted')
        manifest, _, _, _ = self.package(reopened, operation_id=operation_id)
        self.assertIn('INCOMPLETE_RECORD', manifest['limitations'])
        self.assertEqual(log.record['status'], 'running')

    def test_corrupt_record_is_ignored_and_missing_material_is_reported(self):
        log = self.service.diagnostics
        log.begin('sync')
        log.attach('input', {'complete': True})
        operation = log.record['operation_id']
        log.finish('failed')
        (log.directory / ('b' * 32 + '.record.json')).write_text('null')
        (log.directory / (operation + '.material.json')).write_text('[]')
        reopened = DiagnosticRecorder(self.root)
        manifest, material, _, _ = self.package(reopened, operation_id=operation)
        self.assertIn('MATERIAL_UNAVAILABLE', manifest['limitations'])
        self.assertEqual(material, {})

    def test_write_failure_keeps_working_and_exports_memory(self):
        log = self.service.diagnostics
        with patch.object(log, '_write', side_effect=OSError('private path')):
            result = self.service.run(capture=write_capture(self.root))
        self.assertIsNotNone(result['report'])
        self.assertIsNotNone(result['apple_report'])
        self.assertTrue(log.storage_warning)
        manifest, material, _, _ = self.package()
        self.assertIn('WRITE_FAILED', manifest['limitations'])
        self.assertIn('bundle', material)

    def test_partial_export_failure_is_recorded_separately(self):
        with patch.object(self.service, '_export_unlocked', side_effect=OSError('private path')):
            result = self.service.run(capture=write_capture(self.root))
        self.assertIsNotNone(result['apple_report'])
        manifest, _, events, _ = self.package()
        self.assertEqual(manifest['status'], 'partial')
        self.assertIn('wakeup_export_failed', [e['event'] for e in events])
        self.assertIn('apple_export_finished', [e['event'] for e in events])

    def test_malformed_json_does_not_log_body(self):
        path = self.root / 'bad.json'
        path.write_text('PRIVATE_MALFORMED_BODY', encoding='utf-8')
        with self.assertRaises(SourceError):
            self.service.run(capture=path)
        manifest, _, events, raw = self.package()
        self.assertEqual(manifest['status'], 'failed')
        self.assertNotIn('PRIVATE_MALFORMED_BODY', raw)
        self.assertIn('JSON_INVALID', manifest['limitations'])
        self.assertIn('material_unavailable', [e['event'] for e in events])

    def test_cancelled_run_retains_previous_schedule(self):
        capture = write_capture(self.root)
        self.service.run(capture=capture)
        previous = load_current(self.root)
        job = DesktopJob(self.service)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Exception):
            self.service.run(capture=capture, cancel=cancel)
        manifest, _, _, _ = self.package()
        self.assertEqual(manifest['status'], 'cancelled')
        self.assertEqual(load_current(self.root), previous)

    def test_retention_removes_only_owned_records_and_directory_isolation(self):
        log = self.service.diagnostics
        log.begin('sync')
        log.finish('success')
        old = log.directory / (log.record['operation_id'] + '.record.json')
        os.utime(old, (0, 0))
        foreign = log.directory / 'my-private-file.json'
        foreign.write_text('do not touch', encoding='utf-8')
        log.begin('export')
        self.assertFalse(old.exists())
        self.assertTrue(foreign.exists())
        self.assertEqual(DiagnosticRecorder(self.root / 'another').records(), [])
        log.max_disk = 1500
        for _ in range(5):
            log.begin('settings')
            log.finish('success')
        self.assertLess(sum(p.stat().st_size for p in log._owned()), 3000)

    def test_bounds_and_browser_supplement(self):
        log = self.service.diagnostics
        log.begin('sync')
        with patch('diagnostics.MAX_MATERIAL', 20), patch('diagnostics.MAX_EVENTS', 2):
            log.attach('input', {'responses': [{'response': {'List': []}}]})
            for _ in range(5):
                log.event('waiting')
        log.finish('success')
        manifest, material, _, raw = self.package(browser_text=json.dumps({
            'format': 'shsmu-browser-support-v1', 'failure': {'code': 'ACCESS'},
            'config': {'token': 'PRIVATE_TOKEN', **CONFIG}}))
        self.assertIn('MATERIAL_LIMIT', manifest['limitations'])
        self.assertIn('EVENT_LIMIT', manifest['limitations'])
        self.assertIn('browser_supplement', material)
        self.assertNotIn('PRIVATE_TOKEN', raw)
        with self.assertRaises(ValueError):
            self.package(browser_text='not JSON')

    def test_export_failure_does_not_replace_previous_package(self):
        self.package()
        previous = (self.root / 'support.zip').read_bytes()
        with patch('diagnostics.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.package()
        self.assertEqual(previous, (self.root / 'support.zip').read_bytes())

    def test_running_log_rotates_history_and_oversized_supplement_is_reported(self):
        log = self.service.diagnostics
        log.begin('sync')
        old_id = log.record['operation_id']
        log.finish('success')
        log.begin('sync')
        current_bytes = (log.directory / (log.record['operation_id'] + '.record.json')).stat().st_size
        log.max_disk = current_bytes + 300
        log.event('waiting_started')
        self.assertFalse((log.directory / (old_id + '.record.json')).exists())
        self.assertLessEqual(sum(p.stat().st_size for p in log._owned()), log.max_disk)
        with patch('diagnostics.MAX_MATERIAL', 100):
            manifest, material, _, raw = self.package(browser_text=json.dumps({
                'format': 'shsmu-browser-support-v1', 'responses': [{'response': [{'Teacher': 'private ' * 30}]}]}))
        self.assertIn('MATERIAL_LIMIT', manifest['limitations'])
        self.assertNotIn('browser_supplement', material)
        self.assertNotIn('private', raw)

    def test_browser_diagnostic_is_observed_only_when_stable(self):
        folder = self.root / 'downloads'
        folder.mkdir()
        seen = []
        iteration = [0]
        def choose():
            iteration[0] += 1
            if iteration[0] == 1:
                (folder / 'shsmu-diagnostic-test.json').write_text('{"format":"shsmu-diagnostic-v1"}')
            return self.root / 'chosen.json' if iteration[0] == 4 else None
        result = wait_capture(folder, timeout=10, choose=choose, progress=lambda text: None,
                              observe=lambda name, **data: seen.append((name, data)))
        self.assertEqual(result.name, 'chosen.json')
        self.assertEqual(len([v for v in seen if v[0] == 'browser_diagnostic_file']), 1)

    def test_observer_failure_does_not_affect_capture_import(self):
        from sync import import_capture_unlocked, exclusive_sync
        with exclusive_sync(self.root):
            result = import_capture_unlocked(self.root, CONFIG, write_capture(self.root), progress=lambda t: None,
                observe=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('observer broken')))
        self.assertEqual(len(result.snapshot['events']), 1)

    def test_startup_hook_records_import_failure_before_gui_dependencies(self):
        root = self.root / 'startup-failure'
        code = '''import sys, types
from diagnostics import install_startup_hook
sys.argv = ['app', '--data-root', sys.argv[1]]
sys.modules['tkinter'] = types.SimpleNamespace(messagebox=types.SimpleNamespace(showerror=lambda *a, **k: None))
install_startup_hook()
raise ImportError('PRIVATE_IMPORT_FAILURE')
'''
        completed = subprocess.run([sys.executable, '-c', code, str(root)], capture_output=True,
                                   cwd=Path(__file__).resolve().parent, timeout=20)
        self.assertEqual(completed.returncode, 1)
        record = DiagnosticRecorder(root).records()[0]
        self.assertEqual(record['status'], 'failed')
        self.assertNotIn('PRIVATE_IMPORT_FAILURE', json.dumps(record))

    def test_invalid_account_and_leading_zero_ids_stay_invalid_or_distinct(self):
        redactor = Redactor()
        value = redactor.clean({'account_key': 'invalid-account', 'params': {'MCSID': '0011,11'}})
        self.assertNotRegex(value['account_key'], r'^[a-f0-9]{64}$')
        first, second = value['params']['MCSID'].split(',')
        self.assertNotEqual(first, second)
        self.assertEqual(int(first), int(second))
        self.assertNotEqual(redactor.identifier('ALPHA'), redactor.identifier('BETA'))
        self.assertEqual(redactor.identifier('ALPHA'), redactor.identifier('ALPHA'))


if __name__ == '__main__':
    unittest.main()
