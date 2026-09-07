"""Synthetic capture -> CLI commit -> export checks. No school or public network."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sync
from core import DataError, normalize
from prepare import BROWSER_MODULES
from source import ORIGIN, request_key
from test_sync import NOW, LATER, SCOPE, combined_fixture, fixture
from wakeup import export_current


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {key: SCOPE[key] for key in ('semester', 'start', 'end_exclusive')}
        (self.root / 'config.local.json').write_text(json.dumps(self.config), encoding='utf-8')
        for name in BROWSER_MODULES:
            (self.root / name).write_bytes((sync.ROOT / name).read_bytes())
        root_patch = patch.object(sync, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        upload_patch = patch.object(sync, 'publish_current')
        self.upload = upload_patch.start()
        self.addCleanup(upload_patch.stop)

    def run_capture(self, items, fetched_at=NOW, flags=(), account_key='a' * 64, positional=False):
        responses = []
        years, term = self.config['semester'].split(':')
        for start, end in sync.month_ranges(self.config['start'], self.config['end_exclusive']):
            events = [value['event'] for value in items if start <= value['event']['Start'][:10] < end]
            responses.append({'path': '/Home/GetCurriculumTable', 'params': {'Start': start, 'End': end},
                              'response': {'Title': f'{years} 学年 第{term} 学期' if events else None, 'List': events}})
        seen = set()
        for value in items:
            params = {key: str(value['event'].get(key) or '') for key in
                      ('MCSID', 'CSID', 'CurriculumID', 'XXKMID', 'CurriculumType')}
            key = request_key('/Home/GetCalendarTable', params)
            if key not in seen:
                responses.append({'path': '/Home/GetCalendarTable', 'params': params, 'response': value['details']})
                seen.add(key)
        capture = {'format': 'shsmu-capture-v1', 'complete': True, 'origin': ORIGIN,
                   'config': self.config, 'account_key': account_key, 'fetched_at': fetched_at, 'responses': responses}
        path = self.root / 'synthetic-capture.json'
        path.write_text(json.dumps(capture), encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = sync.main([*([str(path)] if positional else ['--capture', str(path)]), *flags])
        self.last_output = output.getvalue()
        return result

    def committed_bytes(self):
        return {name: (self.root / name).read_bytes() for name in
                ('data/current.json', 'data/schedule.json', 'output/calendar.ics',
                 'output/changes.json', 'output/changes.txt')}

    def test_combined_split_cli_repeat_and_failed_capture_preserve_committed_files(self):
        values = combined_fixture(split=True)
        ordinary = fixture(8)
        ordinary['details'][0].update(PKCIndex='|1||2|', WeekNum=1)
        values.append(ordinary)
        self.assertEqual(self.run_capture(values), 0)
        export_current(self.root)
        csv = (self.root / 'output/wakeup.csv').read_bytes()
        ics = (self.root / 'output/calendar.ics').read_bytes()
        uids = [e['uid'] for e in sync.load_current(self.root)['events']]
        self.assertEqual(self.run_capture(values[::-1], LATER), 0)
        export_current(self.root)
        self.assertEqual((self.root / 'output/wakeup.csv').read_bytes(), csv)
        self.assertEqual((self.root / 'output/calendar.ics').read_bytes(), ics)
        self.assertEqual([e['uid'] for e in sync.load_current(self.root)['events']], uids)
        before = self.committed_bytes()
        self.upload.reset_mock()
        values[0]['details'][0]['HeBanID'] = None
        self.assertEqual(self.run_capture(values, '2026-09-07T12:00:00Z'), 2)
        self.assertEqual(self.committed_bytes(), before)
        self.assertEqual((self.root / 'output/wakeup.csv').read_bytes(), csv)
        self.upload.assert_not_called()

    def test_empty_details_keep_committed_version_and_never_upload(self):
        values = [fixture(), fixture(2)]
        self.assertEqual(self.run_capture(values), 0)
        before = self.committed_bytes()
        self.upload.reset_mock()
        values[0]['details'] = []
        values[0]['event']['Teacher'] = '不能用主响应教师替代缺失详情'
        self.assertEqual(self.run_capture(values, LATER), 2)
        self.assertIn('详情为空', self.last_output)
        self.assertEqual(self.committed_bytes(), before)
        self.upload.assert_not_called()
        with self.assertRaises(DataError):
            normalize(values, self.config['start'], self.config['end_exclusive'])

    def test_details_without_teacher_are_distinct_from_empty_response(self):
        value = fixture()
        value['details'][0]['Teacher'] = ''
        self.assertEqual(self.run_capture([value]), 0)
        self.assertEqual(sync.load_current(self.root)['events'][0]['teacher'], '')

    def test_cli_sync_then_wakeup_after_source_id_change(self):
        value = fixture()
        value['details'][0].update(PKCIndex='|1||2|', WeekNum=1)
        self.assertEqual(self.run_capture([value]), 0)
        uid = sync.load_current(self.root)['events'][0]['uid']
        export_current(self.root)
        expected_csv = (self.root / 'output/wakeup.csv').read_bytes()
        changed = copy.deepcopy(value)
        changed['event'].update(ID=502, MCSID='501,502')
        changed['details'][0]['CurriculumScheduleIDs'] = '|501||502|'
        for fetched_at in (LATER, '2026-09-07T12:00:00Z'):
            self.assertEqual(self.run_capture([changed], fetched_at), 0)
            before = self.committed_bytes()
            self.assertEqual(sync.load_current(self.root)['events'][0]['uid'], uid)
            self.assertEqual(export_current(self.root)['event_count'], 1)
            self.assertEqual((self.root / 'output/wakeup.csv').read_bytes(), expected_csv)
            self.assertEqual(self.committed_bytes(), before)

    def test_type_and_source_changes_preserve_uid_through_cli_and_export(self):
        value = fixture()
        value['details'][0].update(PKCIndex='|1||2|', WeekNum=1)
        self.assertEqual(self.run_capture([value]), 0)
        previous = sync.load_current(self.root)
        value['event'].update(CurriculumType='选修课', ID=502, MCSID='501,502', CourseCode='TEST002')
        value['details'][0]['CurriculumScheduleIDs'] = '|501||502|'
        self.assertEqual(self.run_capture([value], LATER), 0)
        current = sync.load_current(self.root)
        self.assertEqual(current['events'][0]['uid'], previous['events'][0]['uid'])
        self.assertEqual(current['events'][0]['sequence'], 1)
        diff = json.loads((self.root / 'output/changes.json').read_text(encoding='utf-8'))
        self.assertEqual(diff['summary'], {'ADDED': 0, 'REMOVED': 0, 'CHANGED': 1})
        self.assertEqual(set(diff['changes'][0]['fields']), {'course_code', 'course_type'})
        self.assertEqual(export_current(self.root)['event_count'], 1)

    def test_anomaly_notice_is_visible_and_saved_in_committed_diff(self):
        values = [fixture(n) for n in range(1, 13)]
        self.assertEqual(self.run_capture(values), 0)
        self.assertEqual(self.run_capture(values[:2], LATER), 0)
        self.assertIn('异常提示：本次删除 10/12', self.last_output)
        diff = json.loads((self.root / 'output/changes.json').read_text(encoding='utf-8'))
        self.assertEqual(diff['warnings'], sync.load_current(self.root)['warnings'])
        self.assertIn('异常提示：本次删除 10/12', (self.root / 'output/changes.txt').read_text(encoding='utf-8'))

    def test_dragged_file_import_and_stale_file_preserve_latest(self):
        value = fixture()
        self.assertEqual(self.run_capture([value], positional=True), 0)
        value['details'][0]['Teacher'] = '新教师'
        self.assertEqual(self.run_capture([value], LATER, positional=True), 0)
        before = self.committed_bytes()
        self.upload.reset_mock()
        self.assertEqual(self.run_capture([value], NOW, positional=True), 2)
        self.assertIn('更旧', self.last_output)
        self.assertEqual(self.committed_bytes(), before)
        self.upload.assert_not_called()

    def test_new_term_cannot_override_account_guard(self):
        self.assertEqual(self.run_capture([fixture()]), 0)
        before = self.committed_bytes()
        self.upload.reset_mock()
        self.assertEqual(self.run_capture([fixture()], LATER, flags=['--new-term'], account_key='b' * 64), 2)
        self.assertIn('不用于切换账号', self.last_output)
        self.assertEqual(self.committed_bytes(), before)
        self.upload.assert_not_called()

    def test_new_term_same_scope_keeps_uid_history_and_revision(self):
        value = fixture()
        self.assertEqual(self.run_capture([value]), 0)
        uid = sync.load_current(self.root)['events'][0]['uid']
        value['event'].update(ID=502, MCSID='501,502', CourseCode='CORRECTED')
        value['details'][0]['CurriculumScheduleIDs'] = '|501||502|'
        self.assertEqual(self.run_capture([value], LATER, flags=['--new-term']), 0)
        event = sync.load_current(self.root)['events'][0]
        self.assertEqual(event['uid'], uid)
        self.assertEqual(event['sequence'], 1)
        self.assertEqual(self.run_capture([value], '2026-09-07T12:00:00Z', flags=['--new-term']), 0)
        self.assertEqual(sync.load_current(self.root)['events'][0]['sequence'], 1)
        self.assertEqual(json.loads((self.root / 'output/changes.json').read_text(encoding='utf-8'))['changes'], [])

    def test_same_account_can_explicitly_start_a_new_semester(self):
        self.assertEqual(self.run_capture([fixture()]), 0)
        old_pointer = (self.root / 'data/current.json').read_bytes()
        self.config.update(semester='2026-2027:2', start='2027-02-01', end_exclusive='2027-06-01')
        (self.root / 'config.local.json').write_text(json.dumps(self.config), encoding='utf-8')
        value = fixture()
        value['event'].update(Start='2027-02-01T08:00:00', End='2027-02-01T09:30:00')
        value['details'][0]['ClassTime'] = '2027-02-01T00:00:00'
        self.assertEqual(self.run_capture([value], '2027-01-30T12:00:00Z'), 2)
        self.assertEqual((self.root / 'data/current.json').read_bytes(), old_pointer)
        self.assertEqual(self.run_capture([value], '2027-01-30T12:00:00Z', flags=['--new-term']), 0)
        self.assertEqual(sync.load_current(self.root)['scope']['semester'], '2026-2027:2')
        self.assertTrue((self.root / 'data/runs' / json.loads(old_pointer)['run_id'] / 'schedule.json').is_file())

    def test_file_picker_import_and_cancel_leave_committed_state(self):
        self.assertEqual(self.run_capture([fixture()]), 0)
        before = self.committed_bytes()
        output = io.StringIO()
        with patch.object(sync, 'select_capture', return_value=self.root / 'synthetic-capture.json'), contextlib.redirect_stdout(output):
            self.assertEqual(sync.main(['--select-capture']), 0)
        self.assertIn('已经处理', output.getvalue())
        self.upload.reset_mock()
        with patch.object(sync, 'select_capture', side_effect=KeyboardInterrupt), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sync.main(['--select-capture']), 130)
        self.assertEqual(self.committed_bytes(), before)
        self.upload.assert_not_called()

    def test_changed_schedule_warns_about_existing_wakeup_file(self):
        self.assertEqual(self.run_capture([fixture()]), 0)
        csv_path = self.root / 'output/wakeup.csv'
        csv_path.write_bytes(b'previous manual export')
        value = fixture()
        value['details'][0]['Teacher'] = '新教师'
        self.assertEqual(self.run_capture([value], LATER), 0)
        self.assertIn('WakeUp CSV 仍是旧文件', self.last_output)
        self.assertEqual(csv_path.read_bytes(), b'previous manual export')


if __name__ == '__main__':
    unittest.main()
