"""Synthetic tests only. Real-page verification is recorded separately."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from icalendar import Calendar

from core import DataError, export_ics, normalize, reconcile
from source import CaptureSource, LoginRequired, SourceError, scrub
from sync import fetch_complete, load_current, month_ranges, publish, repair_exports

NOW = '2026-09-05T12:00:00Z'
LATER = '2026-09-06T12:00:00Z'
SCOPE = {'semester':'2026-2027:1', 'start':'2026-09-07', 'end_exclusive':'2027-01-18', 'account_key':'synthetic-account'}


def fixture(number=1):
    row = {'ID': number * 10 + 2, 'Curriculum':'<<测试课程>> ', 'CurriculumID':99,
           'CSID':100, 'MCSID':f'{number*10+1},{number*10+2}', 'CourseCode':'TEST001',
           'CurriculumType':'必修课', 'Start':'2026-09-07T08:00:00', 'End':'2026-09-07T09:30:00',
           'ClassroomAcademy':'测试楼101', 'AllDay':False}
    detail = {'ID':number+2000, 'DetailID':number+1000, 'TeachingCalendarID':3000,
              'CurriculumID':99, 'CurriculumScheduleIDs':f'|{number*10+1}||{number*10+2}|',
              'ClassTime':'2026-09-07T00:00:00', 'Teacher':'测试教师', 'Content':'测试内容', 'IsDel':False}
    return {'event':row, 'details':[detail]}


def normalized(items):
    return normalize(items, SCOPE['start'], SCOPE['end_exclusive'])


class TimetableTests(unittest.TestCase):
    def baseline(self, items=None):
        return reconcile(normalized(items or [fixture()]), None, SCOPE, NOW)[0]

    def test_explicit_local_dates_and_chinese(self):
        event = normalized([fixture()])[0]
        self.assertEqual(event['course_name'], '测试课程')
        self.assertEqual(event['start'], '2026-09-07T08:00:00+08:00')
        self.assertEqual(event['teacher'], '测试教师')
        self.assertEqual(event['source_ids']['MCSID'], ['11','12'])

    def test_order_metadata_and_duplicate_records_have_no_effect(self):
        items = [fixture(1), fixture(2)]
        old = self.baseline(items)
        changed = copy.deepcopy(items[::-1])
        changed[0]['event']['BackgroundColor'] = 'red'
        changed[0]['details'][0].update(gid='new-random-guid', RowNumber=999)
        changed[0]['event']['MCSID'] = '22,21'
        current, diff = reconcile(normalized(changed + [changed[0]]), old, SCOPE, LATER)
        self.assertEqual(diff['changes'], [])
        self.assertEqual(len(current['events']), 2)
        self.assertEqual(export_ics(current), export_ics(old))

    def test_date_time_location_teacher_changes_keep_uid(self):
        original = fixture()
        old = self.baseline([original])
        changed = copy.deepcopy(original)
        changed['event'].update(Start='2026-09-08T10:00:00', End='2026-09-08T11:40:00', ClassroomAcademy='测试楼202')
        changed['details'][0].update(ClassTime='2026-09-08T00:00:00', Teacher='另一位测试教师')
        current, diff = reconcile(normalized([changed]), old, SCOPE, LATER)
        self.assertEqual(current['events'][0]['uid'], old['events'][0]['uid'])
        self.assertEqual(current['events'][0]['sequence'], 1)
        self.assertEqual(diff['summary'], {'ADDED':0,'REMOVED':0,'CHANGED':1})
        self.assertTrue({'date','start_time','end_time','location','teacher'} <= diff['changes'][0]['fields'].keys())

    def test_rebuilt_slot_ids_match_teaching_record(self):
        item = fixture()
        old = self.baseline([item])
        item['event'].update(ID=502, MCSID='501,502')
        item['details'][0]['CurriculumScheduleIDs'] = '|501||502|'
        current, diff = reconcile(normalized([item]), old, SCOPE, LATER)
        self.assertEqual(current['events'][0]['uid'], old['events'][0]['uid'])
        self.assertEqual(diff['changes'], [])

    def test_cancel_makeup_and_restore(self):
        old = self.baseline()
        current, diff = reconcile(normalized([fixture(2)]), old, SCOPE, LATER)
        self.assertEqual(diff['summary'], {'ADDED':1,'REMOVED':1,'CHANGED':0})
        self.assertEqual(current['cancelled_events'][0]['uid'], old['events'][0]['uid'])
        restored, changes = reconcile(normalized([fixture(), fixture(2)]), current, SCOPE, '2026-09-07T12:00:00Z')
        self.assertEqual(restored['events'][0]['uid'], old['events'][0]['uid'])
        self.assertEqual(restored['events'][0]['sequence'], 2)
        self.assertEqual(restored['cancelled_events'], [])

    def test_conflicts_and_split_merge_are_rejected(self):
        item = fixture()
        changed = copy.deepcopy(item)
        changed['event']['ClassroomAcademy'] = '冲突教室'
        with self.assertRaises(DataError):
            normalized([item, changed])
        one = fixture(2)
        one['details'][0]['DetailID'] = item['details'][0]['DetailID']
        with self.assertRaises(DataError):
            reconcile(normalized([item, one]), None, SCOPE, NOW)

    def test_invalid_dates_and_contradictory_details_rejected(self):
        for field, value in [('Start','2026-02-30T08:00:00'), ('End','2026-09-07T07:00:00')]:
            item = fixture()
            item['event'][field] = value
            with self.assertRaises(DataError):
                normalized([item])
        item = fixture()
        item['details'][0]['ClassTime'] = '2026-09-08T00:00:00'
        with self.assertRaises(DataError):
            normalized([item])

    def test_ics_roundtrip_escaping_folding_timezone_and_cancellations(self):
        item = fixture()
        item['event']['Curriculum'] = '中文课,分号;反斜线\\换行\n' + '长课程名称' * 30
        item['event']['ClassroomAcademy'] = '东楼,101;第二间'
        snapshot = self.baseline([item])
        wire = export_ics(snapshot)
        self.assertNotIn(b'\n', wire.replace(b'\r\n', b''))
        self.assertTrue(all(len(line) <= 75 for line in wire.split(b'\r\n')))
        parsed = Calendar.from_ical(wire)
        event = parsed.walk('VEVENT')[0]
        self.assertEqual(str(event['SUMMARY']), snapshot['events'][0]['course_name'])
        self.assertEqual(str(event['LOCATION']), item['event']['ClassroomAcademy'])
        self.assertEqual(event.decoded('DTSTART').utcoffset(), timedelta(hours=8))
        self.assertEqual(event['DTSTART'].params['TZID'], 'Asia/Shanghai')
        self.assertEqual(event.decoded('DTSTART').hour, 8)
        self.assertEqual(len(parsed.walk('VTIMEZONE')), 1)
        cancelled, _ = reconcile([], snapshot, SCOPE, LATER)
        self.assertEqual(str(Calendar.from_ical(export_ics(cancelled)).walk('VEVENT')[0]['STATUS']), 'CANCELLED')

    def test_scope_change_rejected(self):
        changed = dict(SCOPE, account_key='different-account')
        with self.assertRaises(DataError):
            reconcile(normalized([fixture()]), self.baseline(), changed, LATER)

    def test_chunk_coverage_and_exclusive_end(self):
        ranges = list(month_ranges(SCOPE['start'], SCOPE['end_exclusive']))
        self.assertEqual(len(ranges), 5)
        self.assertEqual(ranges[0][0], SCOPE['start'])
        self.assertEqual(ranges[-1][1], SCOPE['end_exclusive'])
        self.assertTrue(all(a[1] == b[0] for a,b in zip(ranges, ranges[1:])))
        self.assertEqual(normalize([fixture()], '2026-09-06', '2026-09-07'), [])

    def test_login_failure_keeps_current_and_exports_can_recover(self):
        class Expired:
            def timetable(self, *_):
                raise LoginRequired('test session expired')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = self.baseline()
            _, diff = reconcile(normalized([fixture()]), None, SCOPE, NOW)
            publish(root, root / 'data/runs/2026-09-05T120000Z_1234abcd', snapshot, diff, None)
            pointer = (root / 'data/current.json').read_bytes()
            with self.assertRaises(LoginRequired):
                fetch_complete(Expired(), SCOPE, root / 'data/runs/incomplete')
            self.assertEqual((root / 'data/current.json').read_bytes(), pointer)
            (root / 'output/calendar.ics').write_bytes(b'interrupted export')
            repair_exports(root)
            self.assertEqual((root / 'output/calendar.ics').read_bytes(), export_ics(snapshot))
            self.assertEqual(load_current(root), snapshot)

    def test_sensitive_fields_omitted(self):
        data = {'Teacher':'测试教师','Tel':'do-not-save','TeacherAccount':'private',
                'nested':[{'token':'private','Cookie':'private','DetailID':123}]}
        self.assertEqual(scrub(data), {'Teacher':'测试教师','nested':[{'DetailID':123}]})

    def test_capture_requires_all_months_and_exact_event_details(self):
        config = {k:SCOPE[k] for k in ('semester','start','end_exclusive')}
        capture = {'format':'shsmu-capture-v1','complete':True,'origin':'https://jwstu.shsmu.edu.cn',
                   'config':config,'account_key':'a'*64,'responses':[]}
        items = [fixture(1), fixture(2)]
        for start, end in month_ranges(config['start'], config['end_exclusive']):
            capture['responses'].append({'path':'/Home/GetCurriculumTable','params':{'Start':start,'End':end},
                'response':{'Title':'2026-2027 学年 第1 学期' if start==config['start'] else None,'List':[i['event'] for i in items] if start==config['start'] else []}})
        for item in items:
            params = {k:str(item['event'].get(k) or '') for k in ('MCSID','CSID','CurriculumID','XXKMID','CurriculumType')}
            capture['responses'].append({'path':'/Home/GetCalendarTable','params':params,'response':item['details']})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root/'capture.json'
            path.write_text(json.dumps(capture),encoding='utf-8')
            source = CaptureSource(path,config)
            bundle = fetch_complete(source,config,root/'complete')
            self.assertEqual(len(normalized(bundle['items'])),2)
            self.assertEqual(source.request_count,7)
            capture['responses'].pop()
            path.write_text(json.dumps(capture),encoding='utf-8')
            with self.assertRaises(SourceError):
                fetch_complete(CaptureSource(path,config),config,root/'incomplete')
            capture['responses'][0]['response']['Title'] = None
            path.write_text(json.dumps(capture),encoding='utf-8')
            with self.assertRaises(DataError):
                fetch_complete(CaptureSource(path,config),config,root/'missing-term')


if __name__ == '__main__':
    unittest.main(verbosity=2)
