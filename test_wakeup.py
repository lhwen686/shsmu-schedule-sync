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
from test_sync import NOW, LATER, SCOPE, combined_fixture, fixture, mixed_fixture
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
    def test_mixed_details_use_only_selected_periods_and_teachers(self):
        content, _, report = build_export(*prepared(mixed_fixture()))
        self.assertEqual(report['event_count'], 2)
        self.assertEqual([r[2:5] for r in rows(content)[1:]],
                         [['1', '2', '本班教师1'], ['1', '3', '本班教师2']])

    def test_combined_split_exports_only_each_main_event_period(self):
        content, _, report = build_export(*prepared(combined_fixture(split=True)))
        parsed = rows(content)
        self.assertEqual(report['event_count'], 2)
        self.assertEqual([r[2:5] for r in parsed[1:]],
                         [['1', '1', '第一节教师'], ['2', '2', '第二节教师']])

    def test_combined_split_still_validates_actual_endpoint_and_custom_times(self):
        values = combined_fixture(split=True)
        values[0]['event']['Start'] = '2026-09-07T07:55:00'
        snapshot, bundle = prepared(values)
        self.assertEqual(len(snapshot['events']), 2)  # ICS does not depend on a WakeUp template.
        with self.assertRaises(DataError):
            build_export(snapshot, bundle)
        from wakeup import slot_times
        times = slot_times()
        times[1] = ('07:55:00', '08:40:00')
        self.assertEqual(build_export(snapshot, bundle, times=times)[2]['event_count'], 2)

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
        content, _, report = build_export(*prepared([second, first]))
        parsed = rows(content)
        self.assertEqual([row[-1] for row in parsed[1:]], ['1', '3'])
        self.assertEqual(parsed[2][1], '7')
        self.assertEqual(report['semester_weeks'], 3)
        self.assertEqual(report['course_start'], '2026-09-07')
        self.assertEqual(report['course_end'], '2026-09-27')

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

    def test_sync_then_export_after_identifier_change_and_repeat(self):
        value = item()
        previous, bundle = prepared([value])
        expected_csv = build_export(previous, bundle)[0]
        value = copy.deepcopy(value)
        value['event'].update(ID=502, MCSID='501,502')
        value['details'][0]['CurriculumScheduleIDs'] = '|501||502|'
        bundle['items'] = [value]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for number in (1, 2):
                snapshot, diff = reconcile(normalize([value], SCOPE['start'], SCOPE['end_exclusive']),
                                           previous, SCOPE, LATER)
                snapshot.update(coverage=[], capture_fetched_at=LATER)
                self.assertEqual(snapshot['events'][0]['uid'], previous['events'][0]['uid'])
                self.assertEqual(diff['changes'], [])
                self.assertGreater(len(snapshot['events'][0]['identity_aliases']),
                                   len(normalize([value], SCOPE['start'], SCOPE['end_exclusive'])[0]['identity_aliases']))
                run = root / f'data/runs/2026-09-06T120000Z_1234567{number}'
                publish(root, run, snapshot, diff, previous)
                (run / 'capture.json').write_text(json.dumps(bundle), encoding='utf-8')
                source_bytes = (run / 'schedule.json').read_bytes()
                self.assertEqual(export_current(root)['event_count'], 1)
                self.assertEqual((root / 'output/wakeup.csv').read_bytes(), expected_csv)
                self.assertEqual((run / 'schedule.json').read_bytes(), source_bytes)
                previous = snapshot

    def test_history_does_not_allow_wrong_current_source_or_duplicate_identity(self):
        for change in ('current_id', 'alias', 'duplicate'):
            with self.subTest(change=change):
                snapshot, bundle = prepared([item(), item(2)])
                if change == 'current_id':
                    snapshot['events'][0]['source_ids']['ID'] = 9999
                elif change == 'alias':
                    snapshot['events'][0]['identity_aliases'].pop()
                else:
                    snapshot['events'][1] = copy.deepcopy(snapshot['events'][0])
                with self.assertRaises(DataError):
                    build_export(snapshot, bundle)

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
