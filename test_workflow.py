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
from source import ORIGIN, request_key
from test_sync import NOW, LATER, SCOPE, fixture
from wakeup import export_current


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {key: SCOPE[key] for key in ('semester', 'start', 'end_exclusive')}
        (self.root / 'config.local.json').write_text(json.dumps(self.config), encoding='utf-8')
        for name in ('browser_transport.mjs', 'browser_capture.mjs', 'browser_ui.mjs'):
            (self.root / name).write_bytes((sync.ROOT / name).read_bytes())
        root_patch = patch.object(sync, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        upload_patch = patch.object(sync, 'publish_current')
        self.upload = upload_patch.start()
        self.addCleanup(upload_patch.stop)

    def run_capture(self, items, fetched_at=NOW, flags=()):
        responses = []
        for start, end in sync.month_ranges(self.config['start'], self.config['end_exclusive']):
            events = [value['event'] for value in items if start <= value['event']['Start'][:10] < end]
            responses.append({'path': '/Home/GetCurriculumTable', 'params': {'Start': start, 'End': end},
                              'response': {'Title': '2026-2027 学年 第1 学期' if events else None, 'List': events}})
        seen = set()
        for value in items:
            params = {key: str(value['event'].get(key) or '') for key in
                      ('MCSID', 'CSID', 'CurriculumID', 'XXKMID', 'CurriculumType')}
            key = request_key('/Home/GetCalendarTable', params)
            if key not in seen:
                responses.append({'path': '/Home/GetCalendarTable', 'params': params, 'response': value['details']})
                seen.add(key)
        capture = {'format': 'shsmu-capture-v1', 'complete': True, 'origin': ORIGIN,
                   'config': self.config, 'account_key': 'a' * 64, 'fetched_at': fetched_at, 'responses': responses}
        path = self.root / 'synthetic-capture.json'
        path.write_text(json.dumps(capture), encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = sync.main(['--capture', str(path), *flags])
        self.last_output = output.getvalue()
        return result

    def committed_bytes(self):
        return {name: (self.root / name).read_bytes() for name in
                ('data/current.json', 'data/schedule.json', 'output/calendar.ics',
                 'output/changes.json', 'output/changes.txt')}

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


if __name__ == '__main__':
    unittest.main()
