"""Synthetic tests only. Real-page verification is recorded separately."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from icalendar import Calendar

from core import DataError, export_ics, human_diff, normalize, reconcile
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


def combined_fixture(split=False):
    """Synthetic source: one merged calendar is shared by distinct main slots."""
    value = fixture()
    value['event']['CourseCount'] = 2
    first = value['details'][0]
    first.update(ScheduleManagerID=200, HeBanID=400, ClassCode='DEMO-A DEMO-B',
                 CurriculumScheduleIDs='|51||52|', PKCIndex='|1||2|', KCIndex='|1|',
                 ClassHour=1, WeekNum=1, Teacher='第一节教师', Content='第一节内容')
    second = copy.deepcopy(first)
    second.update(DetailID=1002, KCIndex='|2|', Teacher='第二节教师', Content='第二节内容')
    value['details'].append(second)
    if not split:
        return [value]
    other = copy.deepcopy(value)
    value['event'].update(ID=11, MCSID='11', CourseCount=1, End='2026-09-07T08:40:00')
    other['event'].update(ID=12, MCSID='12', CourseCount=1, Start='2026-09-07T08:50:00')
    return [value, other]


class TimetableTests(unittest.TestCase):
    def baseline(self, items=None):
        return reconcile(normalized(items or [fixture()]), None, SCOPE, NOW)[0]

    def test_combined_class_uses_main_identity_and_preserves_shared_source_ids(self):
        event = normalized(combined_fixture())[0]
        self.assertEqual(event['source_ids']['MCSID'], ['11', '12'])
        self.assertEqual(event['source_ids']['detail_ids'], ['1001', '1002'])
        self.assertEqual(event['source_ids']['combined_class']['periods'], [1, 2])
        self.assertEqual(event['identity_basis'], 'slot')
        self.assertTrue(all(a.startswith(('slot:', 'main:')) for a in event['identity_aliases']))
        self.assertEqual(event['teacher'], '第一节教师；第二节教师')

    def test_combined_split_selects_relevant_details_and_repeats_without_changes(self):
        items = combined_fixture(split=True)
        old = self.baseline(items)
        self.assertEqual([e['teacher'] for e in old['events']], ['第一节教师', '第二节教师'])
        self.assertEqual([e['content'] for e in old['events']], ['第一节内容', '第二节内容'])
        self.assertEqual([e['source_ids']['combined_class']['periods'] for e in old['events']], [[1], [2]])
        self.assertEqual(len({e['uid'] for e in old['events']}), 2)
        current, diff = reconcile(normalized(items[::-1] + [copy.deepcopy(items[0])]), old, SCOPE, LATER)
        self.assertEqual(diff['changes'], [])
        self.assertEqual(export_ics(current), export_ics(old))
        for value in items:
            value['details'][1]['Teacher'] = '更新教师'
        updated, diff = reconcile(normalized(items), old, SCOPE, LATER)
        self.assertEqual([e['uid'] for e in updated['events']], [e['uid'] for e in old['events']])
        self.assertEqual(diff['summary'], {'ADDED': 0, 'REMOVED': 0, 'CHANGED': 1})

    def test_combined_class_rejects_unproven_or_conflicting_association(self):
        for field, value in [('HeBanID', None), ('ScheduleManagerID', 100),
                             ('ClassCode', 'DEMO-A'), ('CurriculumID', 999),
                             ('ClassTime', '2026-09-08T00:00:00'), ('PKCIndex', '|1||3|'),
                             ('KCIndex', '|3|'), ('IsDel', True)]:
            with self.subTest(field=field):
                items = combined_fixture()
                items[0]['details'][0][field] = value
                with self.assertRaises(DataError):
                    normalized(items)
        items = combined_fixture()
        items[0]['event']['CourseCount'] = 1
        with self.assertRaises(DataError):
            normalized(items)
        items = combined_fixture(split=True)
        with self.assertRaises(DataError):
            normalized(items[:1])
        items[1]['event']['Start'] = items[0]['event']['Start']
        with self.assertRaises(DataError):
            normalized(items)

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

    def test_course_code_change_updates_diff_ics_and_revision(self):
        item = fixture()
        old = self.baseline([item])
        item['event']['CourseCode'] = 'TEST002'
        current, diff = reconcile(normalized([item]), old, SCOPE, LATER)
        self.assertEqual(diff['summary'], {'ADDED': 0, 'REMOVED': 0, 'CHANGED': 1})
        self.assertEqual(diff['changes'][0]['fields'], {'course_code': {'before': 'TEST001', 'after': 'TEST002'}})
        self.assertIn('课程编号：TEST001 → TEST002', human_diff(diff))
        event = Calendar.from_ical(export_ics(current)).walk('VEVENT')[0]
        self.assertIn('课程编号：TEST002', str(event['DESCRIPTION']))
        self.assertEqual(str(event['UID']), old['events'][0]['uid'])
        self.assertEqual(int(event['SEQUENCE']), 1)
        self.assertEqual(current['events'][0]['modified_at'], LATER)
        repeated, changes = reconcile(normalized([item]), current, SCOPE, '2026-09-07T12:00:00Z')
        self.assertEqual(changes['changes'], [])
        self.assertEqual(export_ics(repeated), export_ics(current))
        with self.assertRaises(DataError):
            normalized([fixture(), item])

    def test_course_type_change_keeps_legacy_uid_and_repeat_is_stable(self):
        item = fixture()
        old = self.baseline([item])
        legacy_aliases = old['events'][0]['identity_aliases'][:]
        item['event']['CurriculumType'] = '选修课'
        current, diff = reconcile(normalized([item]), old, SCOPE, LATER)
        self.assertEqual(current['events'][0]['uid'], old['events'][0]['uid'])
        self.assertEqual(current['events'][0]['sequence'], 1)
        self.assertEqual(current['cancelled_events'], [])
        self.assertTrue(set(legacy_aliases).issubset(current['events'][0]['identity_aliases']))
        self.assertEqual(diff['summary'], {'ADDED': 0, 'REMOVED': 0, 'CHANGED': 1})
        self.assertEqual(diff['changes'][0]['fields'], {'course_type': {'before': '必修课', 'after': '选修课'}})
        repeated, changes = reconcile(normalized([item]), current, SCOPE, '2026-09-07T12:00:00Z')
        self.assertEqual(changes['changes'], [])
        self.assertEqual(export_ics(repeated), export_ics(current))

    def test_course_type_change_can_restore_cancelled_event(self):
        old = self.baseline()
        cancelled, _ = reconcile([], old, SCOPE, LATER)
        item = fixture()
        item['event']['CurriculumType'] = '选修课'
        restored, diff = reconcile(normalized([item]), cancelled, SCOPE, '2026-09-07T12:00:00Z')
        self.assertEqual(restored['events'][0]['uid'], old['events'][0]['uid'])
        self.assertEqual(restored['events'][0]['sequence'], 2)
        self.assertEqual(restored['cancelled_events'], [])
        self.assertTrue(diff['changes'][0]['restored'])

    def test_type_independent_matching_rejects_collisions_and_keeps_course_scope(self):
        first, second = fixture(), fixture()
        second['event']['CurriculumType'] = '选修课'
        with self.assertRaises(DataError):
            reconcile(normalized([first, second]), None, SCOPE, NOW)
        old = self.baseline([fixture(), fixture(2)])
        old['events'][1]['identity_aliases'] = [a.replace('必修课', '选修课') for a in old['events'][0]['identity_aliases']]
        with self.assertRaises(DataError):
            reconcile(normalized([first]), old, SCOPE, LATER)
        for field in ('CurriculumID', 'CSID'):
            with self.subTest(field=field):
                changed = copy.deepcopy(second)
                changed['event'][field] = 555
                if field == 'CurriculumID':
                    changed['details'][0][field] = 555
                current, diff = reconcile(normalized([changed]), self.baseline(), SCOPE, LATER)
                self.assertEqual(diff['summary'], {'ADDED': 1, 'REMOVED': 1, 'CHANGED': 0})
                self.assertNotEqual(current['events'][0]['uid'], self.baseline()['events'][0]['uid'])

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

    def test_month_becoming_empty_is_reported_even_when_event_moves(self):
        old = self.baseline()
        value = fixture()
        value['event'].update(Start='2026-10-05T08:00:00', End='2026-10-05T09:30:00')
        value['details'][0]['ClassTime'] = '2026-10-05T00:00:00'
        snapshot, diff = reconcile(normalized([value]), old, SCOPE, LATER)
        self.assertEqual(diff['summary'], {'ADDED': 0, 'REMOVED': 0, 'CHANGED': 1})
        self.assertTrue(any('2026-09 的课程由 1 次变为 0 次' in message for message in diff['warnings']))
        self.assertEqual(snapshot['warnings'], diff['warnings'])
        self.assertIn('异常提示', human_diff(diff))

    def test_large_deletion_warning_counts_removals_even_with_makeup_events(self):
        old = self.baseline([fixture(n) for n in range(1, 41)])
        for removed in (9, 10):
            with self.subTest(removed=removed):
                # Replacement lessons leave the total count unchanged.
                values = [fixture(n) for n in range(removed + 1, 41)] + [fixture(n) for n in range(101, 101 + removed)]
                snapshot, diff = reconcile(normalized(values), old, SCOPE, LATER)
                self.assertEqual(len(snapshot['events']), 40)
                self.assertEqual(diff['summary']['REMOVED'], removed)
                warnings = [message for message in diff['warnings'] if '异常提示：本次删除' in message]
                self.assertEqual(bool(warnings), removed == 10)
                if warnings:
                    self.assertIn('10/40', warnings[0])

    def test_ordinary_cancellation_and_previously_empty_months_have_no_anomaly(self):
        old = self.baseline([fixture(), fixture(2)])
        for previous, values in ((None, [fixture()]), (old, [fixture(2)])):
            snapshot, diff = reconcile(normalized(values), previous, SCOPE, LATER)
            self.assertFalse(any('异常提示' in message for message in diff['warnings']))

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
