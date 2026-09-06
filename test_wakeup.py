"""Synthetic WakeUp conversion tests; iOS acceptance is tracked separately."""
import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import DataError, normalize, reconcile
from sync import publish
from test_sync import NOW, SCOPE, fixture
from wakeup import HEADER, build_export, export_current


def item(number=1):
    value = fixture(number)
    value['details'][0].update(PKCIndex='|1||2|', WeekNum=1)
    return value


def prepared(items):
    snapshot = reconcile(normalize(items, SCOPE['start'], SCOPE['end_exclusive']), None, SCOPE, NOW)[0]
    snapshot['coverage'] = []
    snapshot['capture_fetched_at'] = NOW
    bundle = {'complete': True, 'account_key': SCOPE['account_key'], 'coverage': [], 'items': items}
    return snapshot, bundle


def rows(content):
    return list(csv.reader(io.StringIO(content.decode('utf-8-sig'), newline='')))


class WakeUpTests(unittest.TestCase):
    def test_csv_roundtrip_special_characters_and_empty_fields(self):
        value = item()
        value['event']['Curriculum'] = '中文,课程 "A"\n第二行'
        value['event']['ClassroomAcademy'] = ''
        value['details'][0]['Teacher'] = ''
        content, guide, report = build_export(*prepared([value]))
        parsed = rows(content)
        self.assertTrue(content.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(parsed[0], list(HEADER))
        self.assertEqual(parsed[1], ['中文,课程 "A"\n第二行', '1', '1', '2', '无', '无', '1'])
        self.assertEqual(report['first_monday'], '2026-09-07')
        self.assertIn('推算', guide.decode('utf-8-sig'))

    def test_actual_dates_gapped_weeks_and_sunday(self):
        first, second = item(), item(2)
        second['event'].update(Start='2026-09-27T08:00:00', End='2026-09-27T09:30:00')
        second['details'][0].update(ClassTime='2026-09-27T00:00:00', WeekNum=3)
        parsed = rows(build_export(*prepared([second, first]))[0])
        self.assertEqual([row[-1] for row in parsed[1:]], ['1', '3'])
        self.assertEqual(parsed[2][1], '7')

    def test_split_details_union_and_evening(self):
        value = item()
        value['event'].update(Start='2026-09-07T17:40:00', End='2026-09-07T20:50:00')
        value['details'][0]['PKCIndex'] = '|11||12|'
        extra = copy.deepcopy(value['details'][0])
        extra.update(PKCIndex='|13||14|', ID=9999, DetailID=9999)
        value['details'].append(extra)
        parsed = rows(build_export(*prepared([value]))[0])
        self.assertEqual(parsed[1][2:4], ['11', '14'])

    def test_cancelled_excluded_and_overlaps_preserved(self):
        snapshot, bundle = prepared([item(), item(2)])
        snapshot['cancelled_events'] = [copy.deepcopy(snapshot['events'][0])]
        self.assertEqual(len(rows(build_export(snapshot, bundle)[0])), 3)

    def test_invalid_or_missing_slots(self):
        for slots in (None, '', '|1||3|', '|0|', '|15|', '1,2'):
            with self.subTest(slots=slots):
                value = item()
                value['details'][0]['PKCIndex'] = slots
                with self.assertRaises(DataError):
                    build_export(*prepared([value]))

    def test_time_mismatch_and_cross_day(self):
        for end in ('2026-09-07T09:31:00', '2026-09-08T09:30:00'):
            with self.subTest(end=end):
                value = item()
                value['event']['End'] = end
                with self.assertRaises(DataError):
                    build_export(*prepared([value]))

    def test_missing_and_inconsistent_week(self):
        for week in (None, 0, True, '1', 2):
            with self.subTest(week=week):
                one, two = item(), item(2)
                two['details'][0]['WeekNum'] = week
                with self.assertRaises(DataError):
                    build_export(*prepared([one, two]))

    def test_incomplete_mismatched_or_altered_source(self):
        for change in ('complete', 'account', 'content', 'count'):
            with self.subTest(change=change):
                snapshot, bundle = prepared([item()])
                if change == 'complete':
                    bundle['complete'] = False
                elif change == 'account':
                    bundle['account_key'] = 'different'
                elif change == 'content':
                    bundle['items'][0]['event']['ClassroomAcademy'] = 'changed'
                else:
                    bundle['items'] = []
                with self.assertRaises(DataError):
                    build_export(snapshot, bundle)

    def test_repeated_and_reordered_exports_identical(self):
        snapshot, bundle = prepared([item(), item(2)])
        expected = build_export(snapshot, bundle)
        bundle['items'].reverse()
        bundle['items'].append(copy.deepcopy(bundle['items'][0]))
        self.assertEqual(build_export(snapshot, bundle), expected)

    def test_export_preserves_source_and_failed_export_preserves_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, bundle = prepared([item()])
            run = root / 'data/runs/2026-09-05T120000Z_12345678'
            publish(root, run, snapshot, {'synced_at': NOW, 'summary': {'ADDED': 1, 'REMOVED': 0, 'CHANGED': 0}, 'changes': []}, None)
            capture = run / 'capture.json'
            capture.write_text(json.dumps(bundle), encoding='utf-8')
            protected = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch('webcal.publish_current', side_effect=AssertionError('No upload')):
                self.assertEqual(export_current(root)['event_count'], 1)
            for path, original in protected.items():
                self.assertEqual(path.read_bytes(), original)
            csv_path = root / 'output/wakeup.csv'
            original = csv_path.read_bytes()
            export_current(root)
            self.assertEqual(csv_path.read_bytes(), original)
            bundle['items'][0]['details'][0]['PKCIndex'] = '|1||3|'
            capture.write_text(json.dumps(bundle), encoding='utf-8')
            with self.assertRaises(DataError):
                export_current(root)
            self.assertEqual(csv_path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
