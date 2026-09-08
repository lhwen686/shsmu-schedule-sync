"""Desktop workflow acceptance in disposable directories, never a live account."""
import json
import hashlib
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date
from icalendar import Calendar

import sync
from core import DataError
from desktop_service import DesktopJob, DesktopService, student_term_config, term_key
from prepare import BROWSER_MODULES
from source import ORIGIN, SourceError, request_key
from test_sync import NOW, LATER, SCOPE, combined_fixture, mixed_fixture
from test_wakeup import item
from wakeup import slot_times

CONFIG = {key: SCOPE[key] for key in ('semester', 'start', 'end_exclusive')}


def write_capture(root, values=None, *, fetched=NOW, account='a' * 64, config=CONFIG):
    values = values if values is not None else [item()]
    responses, seen = [], set()
    years, term = config['semester'].split(':')
    for start, end in sync.month_ranges(config['start'], config['end_exclusive']):
        events = [v['event'] for v in values if start <= v['event']['Start'][:10] < end]
        responses.append({'path': '/Home/GetCurriculumTable', 'params': {'Start': start, 'End': end},
                          'response': {'Title': f'{years} 学年 第{term} 学期' if events else None, 'List': events}})
    for value in values:
        params = {key: str(value['event'].get(key) or '') for key in
                  ('MCSID', 'CSID', 'CurriculumID', 'XXKMID', 'CurriculumType')}
        key = request_key('/Home/GetCalendarTable', params)
        if key not in seen:
            responses.append({'path': '/Home/GetCalendarTable', 'params': params, 'response': value['details']})
            seen.add(key)
    path = Path(root) / 'shsmu-capture-test.json'
    path.write_text(json.dumps({'format': 'shsmu-capture-v1', 'complete': True, 'origin': ORIGIN,
        'config': config, 'account_key': account, 'fetched_at': fetched,
        'collector_revision': '2026-09-06.8', 'responses': responses}), encoding='utf-8')
    return path


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='课表 desktop ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.service = DesktopService(self.root)
        self.service.initialize()
        self.service.save_settings(CONFIG)

    def state_bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for d in ('data', 'output')
                for p in (self.root / d).rglob('*') if p.is_file() and p.name != 'sync.lock'}

    def test_mixed_details_both_exports_reopen_and_repeat_without_upload(self):
        with patch('sync.publish_current', side_effect=AssertionError('Desktop must not upload')):
            path = write_capture(self.root, mixed_fixture())
            result = self.service.run(capture=path)
            self.assertIsNone(result['issue'])
            self.assertIsNone(result['apple_issue'])
            self.assertEqual(result['report']['event_count'], 2)
            self.assertEqual(result['apple_report']['event_count'], 2)
            saved = self.state_bytes()
            reopened = DesktopService(self.root)
            reopened.initialize()
            self.assertIsNotNone(reopened.ready_export())
            self.assertIsNotNone(reopened.ready_apple_export())
            self.assertTrue(reopened.run(capture=path)['imported'].duplicate)
            self.assertEqual(self.state_bytes(), saved)

    def test_combined_split_both_exports_reopen_and_repeat_without_upload(self):
        with patch('sync.publish_current', side_effect=AssertionError('Desktop must not upload')):
            path = write_capture(self.root, combined_fixture(split=True))
            result = self.service.run(capture=path)
            self.assertIsNone(result['issue'])
            self.assertIsNone(result['apple_issue'])
            self.assertEqual(result['report']['event_count'], 2)
            self.assertEqual(result['apple_report']['event_count'], 2)
            saved = self.state_bytes()
            reopened = DesktopService(self.root)
            reopened.initialize()
            self.assertIsNotNone(reopened.ready_export())
            self.assertIsNotNone(reopened.ready_apple_export())
            self.assertTrue(reopened.run(capture=path)['imported'].duplicate)
            self.assertEqual(self.state_bytes(), saved)

    def test_first_run_resources_are_separate_and_onboarding_is_explicit(self):
        fresh = DesktopService(self.root / 'new appdata')
        config = fresh.initialize()
        self.assertEqual(config['end_exclusive'], '2027-02-22')
        self.assertEqual(fresh.setup_step(), 1)
        self.assertTrue(fresh.bookmark_path.is_file())
        self.assertFalse((fresh.root / 'browser_ui.mjs').exists())
        self.assertFalse((fresh.root / 'data/current.json').exists())
        fresh.confirm_term()
        self.assertEqual(fresh.setup_step(), 2)
        fresh.acknowledge_bookmark()
        self.assertEqual(fresh.setup_step(), 0)
        fresh.save_settings({**config, 'end_exclusive': '2027-01-19'})
        self.assertEqual(fresh.setup_step(), 2)
        self.assertNotIn('collector_revision', fresh.state())

    def test_upgrade_offers_calendar_range_without_silently_changing_history(self):
        self.service.run(capture=write_capture(self.root))
        before = self.state_bytes()
        self.service.save_state(confirmed_term=term_key(CONFIG))
        self.service.acknowledge_bookmark()
        reopened = DesktopService(self.root)
        reopened.initialize()
        self.assertEqual(reopened.config()['end_exclusive'], '2027-01-18')
        self.assertEqual(reopened.setup_step(), 1)
        reopened.confirm_term()
        self.assertEqual(reopened.config()['end_exclusive'], '2027-02-22')
        self.assertEqual(reopened.setup_step(), 2)
        self.assertEqual(self.state_bytes(), before)

    def test_bookmark_confirmation_without_capture_resumes_guide_on_reopen(self):
        self.service.confirm_term()
        self.service.acknowledge_bookmark()
        self.assertEqual(self.service.setup_step(), 0)
        state_before = (self.root / 'local/desktop-state.json').read_bytes()
        config_before = self.service.config_path.read_bytes()
        reopened = DesktopService(self.root)
        reopened.initialize()
        self.assertEqual(reopened.setup_step(), 2)
        self.assertEqual((self.root / 'local/desktop-state.json').read_bytes(), state_before)
        self.assertEqual(reopened.config_path.read_bytes(), config_before)
        reopened.acknowledge_bookmark()
        self.assertEqual(reopened.setup_step(), 0)
        self.assertIsNone(sync.load_current(self.root))
        self.assertEqual(DesktopService(self.root).setup_step(), 2)

    def test_completed_capture_keeps_update_home_after_reopen(self):
        self.service.confirm_term()
        self.service.acknowledge_bookmark()
        self.service.run(capture=write_capture(self.root, config=self.service.config()))
        before = self.state_bytes()
        reopened = DesktopService(self.root)
        reopened.initialize()
        self.assertEqual(reopened.setup_step(), 0)
        self.assertEqual(self.state_bytes(), before)

    def test_collector_upgrade_updates_installer_preserving_schedule_and_config(self):
        config = student_term_config(CONFIG)
        self.service.save_settings(config)
        self.service.run(capture=write_capture(self.root, config=config))
        self.service.acknowledge_bookmark()
        self.assertEqual(self.service.setup_step(), 0)
        before = self.state_bytes()
        config_before = self.service.config_path.read_bytes()
        resources = self.root / '新版资源'
        resources.mkdir()
        for name in ('config.example.json', *BROWSER_MODULES):
            shutil.copy2(self.service.resources / name, resources / name)
        checker = resources / 'browser_compat.mjs'
        checker.write_text(checker.read_text(encoding='utf-8') + '\n// synthetic resource update\n', encoding='utf-8')
        upgraded = DesktopService(self.root, resources=resources)
        upgraded.initialize()
        self.assertEqual(upgraded.setup_step(), 2)
        self.assertIn('synthetic resource update', upgraded.bookmark_path.read_text(encoding='utf-8'))
        self.assertEqual(upgraded.config_path.read_bytes(), config_before)
        self.assertEqual(self.state_bytes(), before)
        upgraded.acknowledge_bookmark()
        self.assertEqual(upgraded.setup_step(), 0)

    def test_custom_or_unknown_term_is_never_silently_replaced(self):
        for config in ({**CONFIG, 'range_mode': 'custom'},
                       {**CONFIG, 'semester': '2026-2027:2'},
                       {**CONFIG, 'end_exclusive': '2027-03-01'}):
            self.assertEqual(student_term_config(config), config)

    def test_early_and_late_finishes_are_derived_without_end_date_input(self):
        config = student_term_config(CONFIG)
        self.service.save_settings(config)
        for day in ('2026-12-15', '2027-01-25', '2027-02-21'):
            value = item()
            week = (date.fromisoformat(day) - date(2026, 9, 7)).days // 7 + 1
            value['event'].update(Start=day + 'T08:00:00', End=day + 'T09:30:00')
            value['details'][0].update(ClassTime=day + 'T00:00:00', WeekNum=week)
            with self.subTest(day=day):
                result = self.service.run(capture=write_capture(self.root, [value], config=config))
                self.assertIsNone(result['issue'])
                self.assertEqual(result['report']['event_count'], 1)
                self.assertEqual(result['report']['course_end'], day)
                self.assertEqual(result['report']['semester_weeks'], week)
                self.assertEqual(len(sync.load_current(self.root)['coverage']), 6)

    def test_expanded_range_keeps_revisions_aliases_and_cancelled_history(self):
        one, two = item(), item(2)
        self.service.run(capture=write_capture(self.root, [one, two]))
        one['details'][0]['Teacher'] = '已更正教师'
        self.service.run(capture=write_capture(self.root, [one], fetched=LATER))
        before = sync.load_current(self.root)
        old_event = before['events'][0]
        self.assertEqual(old_event['sequence'], 1)
        self.assertEqual(len(before['cancelled_events']), 1)
        self.service.confirm_term()
        config = self.service.config()
        late = item(3)
        late['event'].update(Start='2027-01-25T08:00:00', End='2027-01-25T09:30:00')
        late['details'][0].update(ClassTime='2027-01-25T00:00:00', WeekNum=21)
        result = self.service.run(capture=write_capture(self.root, [one, late], config=config, fetched=LATER))
        self.assertIsNone(result['issue'])
        self.assertEqual(result['imported'].diff['summary'], {'ADDED': 1, 'REMOVED': 0, 'CHANGED': 0})
        after = sync.load_current(self.root)
        event = next(e for e in after['events'] if e['uid'] == old_event['uid'])
        for field in ('uid', 'sequence', 'created_at', 'modified_at', 'identity_aliases'):
            self.assertEqual(event[field], old_event[field])
        self.assertEqual(after['cancelled_events'], before['cancelled_events'])
        repeat = self.service.run(capture=write_capture(self.root, [one, late], config=config,
                                                       fetched='2026-09-06T13:00:00Z'))
        self.assertEqual(repeat['imported'].diff['summary'], {'ADDED': 0, 'REMOVED': 0, 'CHANGED': 0})

    def test_expansion_missing_or_wrong_semester_month_preserves_complete_version(self):
        self.service.run(capture=write_capture(self.root))
        before = self.state_bytes()
        self.service.confirm_term()
        config = self.service.config()
        for invalid in ('missing', 'wrong_semester'):
            path = write_capture(self.root, config=config, fetched=LATER)
            capture = json.loads(path.read_text(encoding='utf-8'))
            february = next(r for r in capture['responses'] if r['params'].get('Start') == '2027-02-01')
            if invalid == 'missing':
                capture['responses'].remove(february)
            else:
                february['response']['Title'] = '2026-2027 学年 第2 学期'
            path.write_text(json.dumps(capture), encoding='utf-8')
            with self.subTest(invalid=invalid), self.assertRaises((DataError, SourceError)):
                self.service.run(capture=path)
            # Failed runs may retain raw diagnostics, but committed history and outputs stay.
            for name, content in before.items():
                self.assertEqual((self.root / name).read_bytes(), content)

    def test_old_export_manifest_is_not_offered_with_new_week_settings(self):
        self.service.run(capture=write_capture(self.root))
        path = self.root / 'local/desktop-export.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest.pop('export_version')
        path.write_text(json.dumps(manifest), encoding='utf-8')
        self.assertIsNone(self.service.ready_export())
        self.service.run(export_only=True)
        self.assertIsNotNone(self.service.ready_export())

    def test_full_import_automatically_exports_with_no_upload(self):
        (self.root / 'local/webcal.json').write_text('{invalid configuration}', encoding='utf-8')
        with patch.object(sync, 'publish_current') as upload:
            result = self.service.run(capture=write_capture(self.root))
        upload.assert_not_called()
        self.assertIsNone(result['issue'])
        self.assertEqual(result['report']['event_count'], 1)
        self.assertEqual(result['report']['first_monday'], '2026-09-07')
        self.assertTrue(self.service.ready_export())
        self.assertEqual(result['apple_report']['event_count'], 1)
        self.assertIsNone(result['apple_issue'])
        self.assertEqual(self.service.ready_apple_export(), result['apple_report'])
        self.assertEqual((self.root / 'local/webcal.json').read_text(), '{invalid configuration}')

    def test_same_file_has_zero_changes_and_preserves_history(self):
        path = write_capture(self.root)
        self.service.run(capture=path)
        before = self.state_bytes()
        result = self.service.run(capture=path)
        self.assertTrue(result['imported'].duplicate)
        self.assertEqual(result['imported'].diff['summary'], {'ADDED': 0, 'REMOVED': 0, 'CHANGED': 0})
        self.assertEqual(before, self.state_bytes())

    def test_old_file_and_wrong_account_never_replace_current(self):
        self.service.run(capture=write_capture(self.root, fetched=LATER))
        before = self.state_bytes()
        for options, text in (({'fetched': NOW}, '更旧'), ({'fetched': LATER, 'account': 'b' * 64}, '账号')):
            with self.subTest(options=options), self.assertRaisesRegex(DataError, text):
                self.service.run(capture=write_capture(self.root, **options))
            self.assertEqual(before, self.state_bytes())

    def test_bad_file_cannot_become_a_ready_export(self):
        self.service.run(capture=write_capture(self.root))
        before = self.state_bytes()
        path = self.root / 'diagnostic.json'
        path.write_text('{"format":"shsmu-diagnostic-v1"}', encoding='utf-8')
        with self.assertRaises(SourceError):
            self.service.run(capture=path)
        self.assertIsNone(self.service.ready_export())
        self.assertEqual(before, self.state_bytes())

    def test_export_failure_commits_schedule_but_hides_old_csv_then_recovers(self):
        self.service.run(capture=write_capture(self.root))
        csv = (self.root / 'output/wakeup.csv').read_bytes()
        changed = item()
        changed['event'].update(Start='2026-09-07T08:10:00', End='2026-09-07T09:40:00')
        result = self.service.run(capture=write_capture(self.root, [changed], fetched=LATER))
        self.assertIn('课表已保存', result['issue'].title)
        self.assertIsNone(result['report'])
        self.assertIsNone(self.service.ready_export())
        self.assertEqual((self.root / 'output/wakeup.csv').read_bytes(), csv)
        self.assertIsNone(result['apple_issue'])
        self.assertEqual(result['apple_report'], self.service.ready_apple_export())
        event = Calendar.from_ical((self.root / 'output/calendar.ics').read_bytes()).walk('VEVENT')[0]
        self.assertEqual(event.decoded('DTSTART').strftime('%H:%M'), '08:10')
        current = sync.load_current(self.root)
        pointer = (self.root / 'data/current.json').read_bytes()
        self.assertEqual(current['events'][0]['start_time'], '08:10:00')
        times = [[a[:5], b[:5]] for a, b in slot_times().values()]
        times[0], times[1] = ['08:10', '08:50'], ['09:00', '09:40']
        self.service.save_settings(CONFIG, times)
        recovered = self.service.run(export_only=True)
        self.assertIsNone(recovered['issue'])
        self.assertTrue(self.service.ready_export())
        self.assertEqual(pointer, (self.root / 'data/current.json').read_bytes())

    def test_ready_file_checks_moved_file_and_changed_settings(self):
        self.service.run(capture=write_capture(self.root))
        file = self.root / 'output/wakeup.csv'
        data = file.read_bytes()
        file.write_bytes(b'not the verified file')
        self.assertIsNone(self.service.ready_export())
        file.write_bytes(data)
        self.assertIsNotNone(self.service.ready_export())
        values = [[a[:5], b[:5]] for a, b in slot_times().values()]
        self.service.save_settings(CONFIG, values)
        self.assertIsNone(self.service.ready_export())

    def test_apple_roundtrip_dates_unicode_and_cancellation_preserves_history(self):
        late = item(2)
        late['event'].update(Curriculum='中文,课程 "甲"\n第二行', ClassroomAcademy='测试楼;203',
                             Start='2026-09-27T17:40:00', End='2026-09-27T20:50:00')
        late['details'][0].update(ClassTime='2026-09-27T00:00:00', PKCIndex='|11||12||13||14|', WeekNum=3)
        self.service.run(capture=write_capture(self.root, [item(), late]))
        old_uids = {event['uid'] for event in sync.load_current(self.root)['events']}
        result = self.service.run(capture=write_capture(self.root, [late], fetched=LATER))
        data = (self.root / 'output/calendar.ics').read_bytes()
        events = Calendar.from_ical(data).walk('VEVENT')
        self.assertEqual(len(events), 2)
        self.assertEqual({str(event['UID']) for event in events}, old_uids)
        self.assertEqual(sorted(str(event['STATUS']) for event in events), ['CANCELLED', 'CONFIRMED'])
        active = next(event for event in events if str(event['STATUS']) == 'CONFIRMED')
        self.assertEqual(active.decoded('DTSTART').isoformat(), '2026-09-27T17:40:00+08:00')
        self.assertEqual(active.decoded('DTEND').isoformat(), '2026-09-27T20:50:00+08:00')
        self.assertEqual(str(active['DTSTART'].params['TZID']), 'Asia/Shanghai')
        self.assertEqual(str(active['SUMMARY']), '中文,课程 "甲"\n第二行')
        self.assertEqual(str(active['LOCATION']), '测试楼;203')
        self.assertIn('教师：测试教师', str(active['DESCRIPTION']))
        self.assertIn('授课内容：测试内容', str(active['DESCRIPTION']))
        self.assertEqual(result['apple_report'], {'event_count': 1, 'course_start': '2026-09-27',
            'course_end': '2026-09-27', 'capture_fetched_at': LATER,
            'ics_sha256': hashlib.sha256(data).hexdigest()})
        before = self.state_bytes()
        repeated = self.service.run(export_only=True)
        self.assertEqual(repeated['apple_report'], result['apple_report'])
        self.assertEqual(before, self.state_bytes())

    def test_apple_missing_modified_and_previous_version_recover_without_new_history(self):
        self.service.run(capture=write_capture(self.root))
        file = self.root / 'output/calendar.ics'
        original = file.read_bytes()
        changed = item()
        changed['details'][0]['Teacher'] = '变更教师'
        self.service.run(capture=write_capture(self.root, [changed], fetched=LATER))
        current_bytes = file.read_bytes()
        pointer = (self.root / 'data/current.json').read_bytes()
        moved = file.with_suffix('.moved')
        file.rename(moved)
        self.assertIsNone(self.service.ready_apple_export())
        self.service.run(export_only=True)
        self.assertEqual(file.read_bytes(), current_bytes)
        for invalid in (b'not a calendar', original):
            file.write_bytes(invalid)
            self.assertIsNone(self.service.ready_apple_export())
            self.assertIsNone(self.service.run(export_only=True)['apple_issue'])
            self.assertEqual(file.read_bytes(), current_bytes)
        self.assertEqual((self.root / 'data/current.json').read_bytes(), pointer)

    def test_apple_is_independent_of_wakeup_state_and_bad_slot_configuration(self):
        self.service.run(capture=write_capture(self.root))
        ready = self.service.ready_apple_export()
        self.service.save_state(export_ready=False)
        (self.root / 'local/wakeup-slots.json').write_text('{invalid', encoding='utf-8')
        self.assertIsNone(self.service.ready_export())
        self.assertEqual(self.service.ready_apple_export(), ready)
        result = self.service.run(export_only=True)
        self.assertIsNotNone(result['issue'])
        self.assertIsNone(result['apple_issue'])
        self.assertEqual(result['apple_report'], ready)

    def test_apple_write_failure_is_separate_and_keeps_previous_bytes(self):
        self.service.run(capture=write_capture(self.root))
        file = self.root / 'output/calendar.ics'
        file.write_bytes(b'old damaged file')
        pointer = (self.root / 'data/current.json').read_bytes()
        def fail_calendar(path, data):
            if Path(path) == file:
                raise PermissionError('synthetic write denial')
            sync.atomic_write(path, data)
        with patch('desktop_service.atomic_write', side_effect=fail_calendar):
            result = self.service.run(export_only=True)
        self.assertIsNone(result['issue'])
        self.assertIsNone(result['apple_report'])
        self.assertIsNotNone(result['apple_issue'])
        self.assertNotIn('作息', result['apple_issue'].next_step)
        self.assertEqual(file.read_bytes(), b'old damaged file')
        self.assertIsNone(self.service.ready_apple_export())
        self.assertIsNone(self.service.run(export_only=True)['apple_issue'])
        self.assertIsNotNone(self.service.ready_apple_export())
        self.assertEqual((self.root / 'data/current.json').read_bytes(), pointer)

    def test_apple_requires_complete_matching_snapshot_and_respects_lock(self):
        self.assertIsNone(self.service.ready_apple_export())
        with self.assertRaises(DataError):
            self.service.run(export_only=True)
        self.service.run(capture=write_capture(self.root))
        with sync.exclusive_sync(self.root):
            self.assertIsNone(self.service.ready_apple_export())
        self.service.save_settings({**CONFIG, 'end_exclusive': '2027-01-19'})
        self.assertIsNone(self.service.ready_apple_export())
        with self.assertRaises(DataError):
            self.service.run(export_only=True)
        self.service.save_settings(CONFIG)
        pointer = json.loads((self.root / 'data/current.json').read_text(encoding='utf-8'))
        snapshot = self.root / 'data/runs' / pointer['run_id'] / 'schedule.json'
        snapshot.write_text('{}', encoding='utf-8')
        self.assertIsNone(self.service.ready_apple_export())

    def test_empty_capture_cannot_replace_a_ready_apple_file(self):
        self.service.run(capture=write_capture(self.root))
        ready = self.service.ready_apple_export()
        before = (self.root / 'data/current.json').read_bytes()
        with self.assertRaisesRegex(DataError, '整个学期返回空课表'):
            self.service.run(capture=write_capture(self.root, [], fetched=LATER))
        self.assertEqual(self.service.ready_apple_export(), ready)
        self.assertEqual((self.root / 'data/current.json').read_bytes(), before)

    def test_invalid_settings_are_rejected_before_writes(self):
        config = self.service.config_path.read_bytes()
        with self.assertRaises(DataError):
            self.service.save_settings({**CONFIG, 'start': '2026-02-30'})
        with self.assertRaises(DataError):
            self.service.save_settings({**CONFIG, 'end_exclusive': '2027-01-19'}, [['25:00', '26:00']] * 14)
        self.assertEqual(config, self.service.config_path.read_bytes())
        self.assertFalse((self.root / 'local/wakeup-slots.json').exists())

    def test_selecting_downloads_does_not_confirm_a_new_term(self):
        fresh = DesktopService(self.root / 'fresh')
        config = fresh.initialize()
        fresh.save_settings({**config, 'downloads_dir': str(self.root)}, confirm_term=False)
        self.assertEqual(fresh.setup_step(), 1)

    def test_cancel_before_commit_preserves_pointer_and_existing_files(self):
        self.service.run(capture=write_capture(self.root))
        before = (self.root / 'data/current.json').read_bytes()
        token = threading.Event()
        def emit(stage, message):
            if stage == 'detail':
                token.set()
        with self.assertRaises(sync.SyncCancelled):
            self.service.run(capture=write_capture(self.root, fetched=LATER), cancel=token, emit=emit)
        self.assertEqual(before, (self.root / 'data/current.json').read_bytes())

    def test_cancel_after_commit_begins_finishes_export(self):
        token = threading.Event()
        result = self.service.run(capture=write_capture(self.root), cancel=token,
                                 emit=lambda stage, message: token.set() if stage == 'committing' else None)
        self.assertIsNone(result['issue'])
        self.assertIsNotNone(self.service.ready_export())
        self.assertIsNotNone(self.service.ready_apple_export())

    def test_second_window_cannot_write_during_wait(self):
        with sync.exclusive_sync(self.root):
            with self.assertRaisesRegex(DataError, '另一个同步程序'):
                self.service.run(capture=write_capture(self.root))

    def test_reopening_or_linking_existing_root_keeps_uids_and_output(self):
        self.service.run(capture=write_capture(self.root))
        before = self.state_bytes()
        reopened = DesktopService(self.root)
        reopened.initialize()
        self.assertEqual(before, self.state_bytes())
        self.assertIsNotNone(reopened.ready_export())
        self.assertTrue(reopened.run(capture=self.root / 'shsmu-capture-test.json')['imported'].duplicate)
        self.assertEqual(before, self.state_bytes())

    def test_worker_duplicate_start_and_manual_file_while_waiting(self):
        # File is intentionally older than the waiter's baseline. Only user selection imports it.
        path = write_capture(self.root)
        self.service.save_settings({**CONFIG, 'downloads_dir': str(self.root)})
        job = DesktopJob(self.service)
        self.assertTrue(job.start())
        self.addCleanup(lambda: (job.cancel(), job.thread.join(5)))
        deadline = time.monotonic() + 5
        while job.stage != 'waiting' and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(job.stage, 'waiting')
        self.assertFalse(job.start(capture=path))
        job.picker_open.set()
        self.assertFalse(job.submit_file(None))  # cancelling the dialog changes no baseline
        job.picker_open.clear()
        self.assertEqual(job.stage, 'waiting')
        self.assertFalse((self.root / 'data/current.json').exists())
        self.assertTrue(job.submit_file(path))
        job.thread.join(5)
        self.assertFalse(job.busy)
        self.assertIsNotNone(self.service.ready_export())

    def test_waiter_accepts_new_download_but_not_old_file_after_picker_cancel(self):
        downloads = self.root / 'downloads'
        downloads.mkdir()
        write_capture(downloads)
        self.service.save_settings({**CONFIG, 'downloads_dir': str(downloads)})
        job = DesktopJob(self.service)
        job.start()
        self.addCleanup(lambda: (job.cancel(), job.thread.join(5)))
        deadline = time.monotonic() + 5
        while job.stage != 'waiting' and time.monotonic() < deadline:
            time.sleep(0.02)
        job.picker_open.set()
        job.picker_open.clear()  # choosing nothing must not restart the watcher
        self.assertFalse((self.root / 'data/current.json').exists())
        path = downloads / 'shsmu-capture-new.json'
        path.write_bytes(write_capture(self.root, fetched=LATER).read_bytes())
        job.thread.join(5)
        self.assertFalse(job.busy)
        self.assertIsNotNone(self.service.ready_export())

    def test_worker_cancel_is_bounded_and_releases_the_lock(self):
        self.service.save_settings({**CONFIG, 'downloads_dir': str(self.root)})
        job = DesktopJob(self.service)
        job.start()
        job.cancel()
        job.thread.join(3)
        self.assertFalse(job.busy)
        self.assertFalse((self.root / 'data/current.json').exists())
        with sync.exclusive_sync(self.root):
            pass


    def test_wakeup_reminders_follow_export_instead_of_fixed_autumn_defaults(self):
        from datetime import timedelta
        from desktop import wakeup_setup_reminder
        report = self.service.run(capture=write_capture(self.root))['report']
        title, body = wakeup_setup_reminder(report)
        self.assertIn('40 分钟', title)
        self.assertIn('2026-09-07', body)
        self.assertIn('不要保留 9 月 4 日', body)

        # Another valid time table/term must not receive this autumn's instructions.
        report = json.loads(json.dumps(report))
        report['first_monday'] = '2027-03-01'
        for number, (start, end) in report['slot_times'].items():
            hour, minute, second = map(int, start.split(':'))
            later = timedelta(hours=hour, minutes=minute + 45)
            seconds = int(later.total_seconds())
            report['slot_times'][number] = [start, f'{seconds // 3600:02}:{seconds // 60 % 60:02}:00']
        title, body = wakeup_setup_reminder(report)
        self.assertIn('45 分钟', title)
        self.assertIn('2027-03-01', body)
        self.assertNotIn('40 分钟', title + body)
        self.assertNotIn('9 月', title + body)
        report['slot_times']['1'][1] = '08:30:00'
        title, body = wakeup_setup_reminder(report)
        self.assertIn('逐节', title)
        self.assertIn('本次各节时长不同', body)


class DesktopWidgetTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from desktop import AssistantWindow
        self.temp = tempfile.TemporaryDirectory(prefix='课表 widgets ')
        self.addCleanup(self.temp.cleanup)
        self.window = tk.Tk()
        self.window.withdraw()
        self.ui = AssistantWindow(self.window, Path(self.temp.name))
        self.ui.service.save_settings(CONFIG)
        self.addCleanup(self.ui.dispose)
        self.ui.preference_path = Path(self.temp.name) / 'preferences.json'

    def test_diagnostic_dialog_exports_selected_record_and_cancel_is_harmless(self):
        import tkinter as tk
        from tkinter import ttk
        import zipfile
        self.ui.service.run(capture=write_capture(Path(self.temp.name)))
        expected_id = self.ui.service.diagnostics.record['operation_id']
        self.ui.service.initialize()  # Opening the app again must still offer the last sync.
        self.ui.show_help()
        self.assertIn('导出排错日志', self.buttons())
        self.ui.show_diagnostics()
        dialog = next(w for w in self.window.winfo_children() if isinstance(w, tk.Toplevel))
        widgets = dialog.winfo_children()[0].winfo_children()
        save = next(w for w in widgets if isinstance(w, ttk.Button))
        target = Path(self.temp.name) / '用户选择的排错包.zip'
        with patch('desktop.filedialog.asksaveasfilename', return_value=''), patch('desktop.reveal_file') as reveal:
            save.invoke()
            reveal.assert_not_called()
            self.assertTrue(dialog.winfo_exists())
        with patch('desktop.filedialog.asksaveasfilename', return_value=str(target)), patch('desktop.reveal_file') as reveal:
            save.invoke()
            reveal.assert_called_once_with(target)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(json.loads(archive.read('manifest.json'))['operation_id'], expected_id)

    def test_callback_failure_has_persistent_exception_and_export_action(self):
        try:
            raise RuntimeError('PRIVATE_CALLBACK_DETAIL')
        except RuntimeError as error:
            self.window.report_callback_exception(type(error), error, error.__traceback__)
        self.assertIn('导出排错日志', self.buttons())
        record = self.ui.service.diagnostics.record
        self.assertEqual(record['status'], 'failed')
        self.assertNotIn('PRIVATE_CALLBACK_DETAIL', json.dumps(record))
        self.assertTrue(any(e.get('exception', {}).get('type') == 'RuntimeError' for e in record['events']))

    def test_uncaught_background_error_is_failed_and_only_queues_ui_update(self):
        def fail():
            raise RuntimeError('PRIVATE_THREAD_DETAIL')
        with patch('threading.excepthook', side_effect=lambda args: self.ui.handle_thread_error(args.exc_value)), \
                patch.object(self.ui, 'show_issue') as show:
            worker = threading.Thread(target=fail)
            worker.start()
            worker.join(5)
            self.assertFalse(worker.is_alive())
            show.assert_not_called()
        record = self.ui.service.diagnostics.record
        self.assertEqual(record['status'], 'failed')
        self.assertNotIn('PRIVATE_THREAD_DETAIL', json.dumps(record))
        self.assertTrue(any(e['event'] == 'unhandled_thread_failed' for e in record['events']))
        self.assertEqual(self.ui.job.events.get_nowait()[0], 'error')

    def test_picker_cancel_keeps_current_waiting_job(self):
        self.ui.service.save_settings({**CONFIG, 'downloads_dir': self.temp.name})
        self.ui.start()
        deadline = time.monotonic() + 5
        while self.ui.job.stage != 'waiting' and time.monotonic() < deadline:
            time.sleep(0.02)
        with patch('desktop.filedialog.askopenfilename', return_value=''):
            self.ui.pick_capture()
        self.assertTrue(self.ui.job.busy)
        self.assertFalse(self.ui.job.cancelled.is_set())
        self.ui.job.cancel()
        self.ui.job.thread.join(5)

    def test_user_setting_forms_and_phone_card_render_at_font_scales(self):
        from tkinter import ttk
        self.ui.service.run(capture=write_capture(Path(self.temp.name)))
        for factor in (1.0, 1.25, 1.5):
            self.window.tk.call('tk', 'scaling', 96 / 72 * factor)
            self.ui._style()
            self.ui.show_settings()
            self.window.update_idletasks()
            self.assertTrue(any(isinstance(w, ttk.Notebook) for w in self.ui.content.winfo_children()))
            self.ui.show_phone()
            self.window.update_idletasks()
            tree = next(w for w in self.ui.content.winfo_children() if isinstance(w, ttk.Treeview))
            self.assertEqual(len(tree.get_children()), 14)
            self.assertGreater(int(ttk.Style(self.window).lookup('Treeview', 'rowheight')),
                               self.ui.table_font.metrics('linespace'))

    def test_switching_to_long_phone_guide_starts_at_the_top(self):
        self.ui.service.run(capture=write_capture(Path(self.temp.name)))
        self.ui.show_help()
        self.window.update_idletasks()
        self.ui.canvas.configure(scrollregion=(0, 0, 800, 4000))
        self.ui.canvas.yview_moveto(0.4)
        self.ui.show_phone()
        self.window.update_idletasks()
        self.assertEqual(self.ui.canvas.yview()[0], 0.0)

    def widgets(self, ui=None):
        def walk(parent):
            for child in parent.winfo_children():
                yield child
                yield from walk(child)
        return list(walk((ui or self.ui).content))

    def buttons(self, ui=None):
        from tkinter import ttk
        return {str(widget.cget('text')): widget for widget in self.widgets(ui) if isinstance(widget, ttk.Button)}

    def test_startup_resumes_bookmark_guide_until_first_capture(self):
        import tkinter as tk
        from desktop import AssistantWindow
        self.assertIn('就用这个学期，下一步', self.buttons())
        self.buttons()['就用这个学期，下一步'].invoke()
        self.assertIn('复制安装页地址', self.buttons())
        self.assertNotIn('获取我的课表', self.buttons())
        self.buttons()['我已添加课表按钮，进入助手'].invoke()
        self.assertIn('获取我的课表', self.buttons())
        self.assertIn('重新查看书签安装引导', self.buttons())
        self.assertIn('首次导入 · 下一步获取课表',
                      [str(w.cget('text')) for w in self.widgets() if 'text' in w.keys()])
        for captured in (False, True):
            with self.subTest(captured=captured):
                if captured:
                    self.ui.service.run(capture=write_capture(
                        Path(self.temp.name), config=self.ui.service.config()))
                window = tk.Tk()
                window.withdraw()
                reopened = AssistantWindow(window, Path(self.temp.name))
                try:
                    window.update_idletasks()
                    self.assertEqual('复制安装页地址' in self.buttons(reopened), not captured)
                    self.assertEqual('获取我的课表' in self.buttons(reopened), captured)
                    self.assertEqual(reopened.canvas.yview()[0], 0.0)
                    reopened.nav_buttons[0].invoke()
                    self.assertEqual('复制安装页地址' in self.buttons(reopened), not captured)
                finally:
                    reopened.dispose()

    def test_both_exports_on_home_and_results_locate_exact_files(self):
        config = student_term_config(CONFIG)
        self.ui.service.save_settings(config)
        self.ui.service.acknowledge_bookmark()
        result = self.ui.service.run(capture=write_capture(Path(self.temp.name), config=config))
        for show in (self.ui.show_home, lambda: self.ui.show_result(result)):
            show()
            self.window.update_idletasks()
            buttons = self.buttons()
            with patch('desktop.reveal_file') as reveal:
                buttons['导出 WakeUp 文件'].invoke()
                buttons['导出苹果日历'].invoke()
                self.assertEqual([call.args[0] for call in reveal.call_args_list],
                    [self.ui.service.root / 'output/wakeup.csv', self.ui.service.root / 'output/calendar.ics'])
        (self.ui.service.root / 'output/calendar.ics').write_bytes(b'tampered')
        with patch('desktop.reveal_file') as reveal:
            self.ui.reveal_apple()
            reveal.assert_not_called()
        self.assertIn('重新生成导入文件', self.buttons())

    def test_reopened_setup_imports_existing_json_and_exposes_both_exports(self):
        import tkinter as tk
        from desktop import AssistantWindow
        self.ui.service.confirm_term()
        self.ui.service.acknowledge_bookmark()
        capture = write_capture(Path(self.temp.name), config=self.ui.service.config())
        before = capture.read_bytes()
        bookmark_ack = self.ui.service.state()['bookmark_ack']
        window = tk.Tk()
        window.withdraw()
        reopened = AssistantWindow(window, Path(self.temp.name))
        try:
            self.assertIn('复制安装页地址', self.buttons(reopened))
            self.assertIn('文件已经下载', self.buttons(reopened))
            with patch('desktop.filedialog.askopenfilename', return_value=str(capture)), \
                    patch('desktop_service.wait_capture', side_effect=AssertionError('must use selected JSON')):
                self.buttons(reopened)['文件已经下载'].invoke()
                deadline = time.monotonic() + 5
                while reopened.running and time.monotonic() < deadline:
                    window.update()
                    time.sleep(0.02)
            self.assertFalse(reopened.running)
            self.assertIsNotNone(reopened.service.ready_export())
            self.assertIsNotNone(reopened.service.ready_apple_export())
            with patch('desktop.reveal_file') as reveal:
                self.buttons(reopened)['导出 WakeUp 文件'].invoke()
                self.buttons(reopened)['导出苹果日历'].invoke()
                self.assertEqual([call.args[0] for call in reveal.call_args_list],
                    [reopened.service.root / 'output/wakeup.csv', reopened.service.root / 'output/calendar.ics'])
            self.assertEqual(capture.read_bytes(), before)
            self.assertEqual(reopened.service.state()['bookmark_ack'], bookmark_ack)
            reopened.show_home()
            self.assertIn('获取我的课表', self.buttons(reopened))
        finally:
            reopened.dispose()

    def test_setup_file_picker_cancel_keeps_setup_and_does_not_import(self):
        self.ui.confirm_term()
        before = self.ui.service.state()
        self.assertIn('文件已经下载', self.buttons())
        with patch('desktop.filedialog.askopenfilename', return_value=''):
            self.buttons()['文件已经下载'].invoke()
        self.assertFalse(self.ui.running)
        self.assertFalse(self.ui.job.busy)
        self.assertFalse(self.ui.job.picker_open.is_set())
        self.assertEqual(self.ui.service.state(), before)
        self.assertFalse((self.ui.service.root / 'data/current.json').exists())
        self.assertIn('复制安装页地址', self.buttons())

    def test_partial_and_total_export_failure_show_per_format_actions(self):
        self.ui.service.run(capture=write_capture(Path(self.temp.name)))
        for fail_wakeup, fail_apple in ((True, False), (False, True), (True, True)):
            with self.subTest(wakeup=fail_wakeup, apple=fail_apple):
                wakeup = self.ui.service._export_unlocked
                apple = self.ui.service._apple_export_unlocked
                with patch.object(self.ui.service, '_export_unlocked',
                                  side_effect=DataError('synthetic WakeUp failure') if fail_wakeup else wakeup), \
                     patch.object(self.ui.service, '_apple_export_unlocked',
                                  side_effect=DataError('synthetic ICS failure') if fail_apple else apple):
                    result = self.ui.service.run(export_only=True)
                self.ui.show_result(result)
                buttons = self.buttons()
                self.assertEqual(buttons['导出 WakeUp 文件'].instate(['disabled']), fail_wakeup)
                self.assertEqual(buttons['导出苹果日历'].instate(['disabled']), fail_apple)
                self.assertIn('重新生成导入文件', buttons)

    def test_phone_confirmations_are_separate_and_reject_a_changed_guide(self):
        self.ui.service.run(capture=write_capture(Path(self.temp.name)))
        self.ui.show_phone()
        self.ui.confirm_phone()
        state = self.ui.service.state()
        self.assertIn('phone_confirmed_csv', state)
        self.assertNotIn('phone_confirmed_ics', state)
        self.ui.show_apple_phone()
        apple_hash = self.ui.service.ready_apple_export()['ics_sha256']
        self.ui.confirm_apple_phone()
        self.assertEqual(self.ui.service.state()['phone_confirmed_csv'], state['phone_confirmed_csv'])
        self.assertEqual(self.ui.service.state()['phone_confirmed_ics'], apple_hash)
        self.ui.show_apple_phone()
        changed = item()
        changed['details'][0]['Teacher'] = '变更教师'
        self.ui.service.run(capture=write_capture(Path(self.temp.name), [changed], fetched=LATER))
        self.ui.confirm_apple_phone()
        self.assertEqual(self.ui.service.state()['phone_confirmed_ics'], apple_hash)
        self.assertNotEqual(self.ui.service.ready_apple_export()['ics_sha256'], apple_hash)
        self.ui.show_apple_phone()
        self.ui.confirm_apple_phone()
        self.assertEqual(self.ui.service.state()['phone_confirmed_ics'], self.ui.service.ready_apple_export()['ics_sha256'])
        self.assertEqual(self.ui.service.state()['phone_confirmed_csv'], state['phone_confirmed_csv'])

    def test_apple_guide_at_font_scales_starts_at_top_and_has_no_slot_table(self):
        from tkinter import ttk
        self.ui.service.run(capture=write_capture(Path(self.temp.name)))
        for factor in (1.0, 1.25, 1.5):
            self.window.tk.call('tk', 'scaling', 96 / 72 * factor)
            self.ui._style()
            self.ui.show_help()
            self.window.update_idletasks()
            self.ui.canvas.configure(scrollregion=(0, 0, 800, 4000))
            self.ui.canvas.yview_moveto(0.4)
            self.ui.show_apple_phone()
            self.window.update_idletasks()
            self.assertEqual(self.ui.canvas.yview()[0], 0.0)
            self.assertFalse(any(isinstance(widget, ttk.Treeview) for widget in self.widgets()))
            self.assertIn('我已在苹果日历导入并核对', self.buttons())


if __name__ == '__main__':
    unittest.main()
