"""Desktop workflow acceptance in disposable directories, never a live account."""
import json
from contextlib import ExitStack
import traceback
import hashlib
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
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


# Real import/export includes durable writes and diagnostic I/O. This is a
# bounded integration watchdog, not the worker cancellation-response contract.
WORKER_INTEGRATION_TIMEOUT = 30


def wait_for_worker(job, timeout=WORKER_INTEGRATION_TIMEOUT):
    if job.thread is not None:
        job.thread.join(timeout)
    if job.busy:
        raise AssertionError(f'Worker did not exit within {timeout}s (stage={job.stage})')


def cleanup_worker_directory(temp, jobs, timeout=WORKER_INTEGRATION_TIMEOUT):
    deadline = time.monotonic() + timeout
    try:
        for job in jobs:
            if job.busy and job.stage not in ('committing', 'exporting', 'result'):
                # Test teardown must not block in synchronous diagnostic I/O.
                # The existing cancellation token still respects the commit boundary.
                job.cancelled.set()
            wait_for_worker(job, max(0, deadline - time.monotonic()))
    finally:
        if any(job.busy for job in jobs):
            # Retain evidence and the worker's files if bounded cleanup failed.
            temp._finalizer.detach()
        else:
            temp.cleanup()


class WorkerObservation:
    """Observe this job without consuming its queue or replacing real file I/O."""
    def __init__(self, job):
        self.condition = threading.Condition()
        self.events = []
        self.polls = self.paused_polls = 0
        put, pause_check, cancel_wait = job.events.put, job.picker_open.is_set, job.cancelled.wait

        def record(item, *args, **kwargs):
            result = put(item, *args, **kwargs)
            with self.condition:
                self.events.append(item)
                self.condition.notify_all()
            return result

        def check_pause():
            value = pause_check()
            if value:
                with self.condition:
                    self.paused_polls += 1
                    self.condition.notify_all()
            return value

        def wait(timeout=None):
            # wait_capture waits one second only after a full scan. A paused
            # picker uses 0.1s instead and cannot count as an old-file scan.
            if timeout == 1:
                with self.condition:
                    self.polls += 1
                    self.condition.notify_all()
            return cancel_wait(timeout)

        job.events.put = record
        job.picker_open.is_set = check_pause
        job.cancelled.wait = wait

    def wait_for(self, predicate, description, timeout=WORKER_INTEGRATION_TIMEOUT):
        with self.condition:
            self.condition.wait_for(lambda: predicate() or any(
                stage in ('error', 'finished') for stage, _ in self.events), timeout)
            if not predicate():
                raise AssertionError(f'Timed out or worker ended before {description}; '
                                     f'events={[stage for stage, _ in self.events]}')

    def stage(self, name):
        self.wait_for(lambda: any(stage == name for stage, _ in self.events), name)


class WorkerSynchronizationTests(unittest.TestCase):
    def test_phase_wait_has_a_finite_failure_before_waiting(self):
        observer = WorkerObservation(DesktopJob(Mock()))
        with self.assertRaisesRegex(AssertionError, 'before waiting'):
            observer.wait_for(lambda: bool(observer.events), 'waiting', timeout=0.02)
        self.assertEqual(observer.events, [])

    def test_finished_is_not_thread_exit_and_cleanup_retains_live_directory(self):
        temp = tempfile.TemporaryDirectory(prefix='worker cleanup ')
        root = Path(temp.name)
        release, finished = threading.Event(), threading.Event()
        job = DesktopJob(Mock(run=Mock(return_value={})))
        put = job.events.put

        def held_finish(item):
            put(item)
            if item[0] == 'finished':
                finished.set()
                if not release.wait(5):
                    raise AssertionError('Controlled worker gate was not released')
                (root / 'worker-exited.txt').write_text('synthetic', encoding='utf-8')

        job.events.put = held_finish
        try:
            self.assertTrue(job.start())
            self.assertTrue(finished.wait(3))
            with self.assertRaisesRegex(AssertionError, 'Worker did not exit'):
                wait_for_worker(job, timeout=0.02)
            with self.assertRaisesRegex(AssertionError, 'Worker did not exit'):
                cleanup_worker_directory(temp, [job], timeout=0.02)
            self.assertTrue(job.busy)
            self.assertTrue(root.is_dir())
        finally:
            release.set()
            try:
                wait_for_worker(job, timeout=3)
                self.assertTrue((root / 'worker-exited.txt').is_file())
            finally:
                cleanup_worker_directory(temp, [job], timeout=3)


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='课表 desktop ')
        self.worker_jobs = []
        self.addCleanup(cleanup_worker_directory, self.temp, self.worker_jobs)
        self.root = Path(self.temp.name).resolve()
        self.service = DesktopService(self.root)
        self.service.initialize()
        self.service.save_settings(CONFIG)

    def state_bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for d in ('data', 'output')
                for p in (self.root / d).rglob('*') if p.is_file() and p.name != 'sync.lock'}

    def observed_worker(self):
        job = DesktopJob(self.service)
        self.worker_jobs.append(job)
        return job, WorkerObservation(job)

    def assert_worker_import(self, job, observer, fetched):
        observer.stage('processing')
        self.assertFalse(job.submit_file(self.root / 'shsmu-capture-test.json'))
        wait_for_worker(job)
        self.assertFalse(job.thread.is_alive())
        stages = [stage for stage, _ in observer.events]
        self.assertNotIn('error', stages)
        self.assertEqual(stages.count('result'), 1)
        self.assertEqual(stages.count('committing'), 1)
        self.assertEqual(stages.count('finished'), 1)
        self.assertEqual(stages[-1], 'finished')
        result = next(value for stage, value in observer.events if stage == 'result')
        self.assertTrue(result['committed'])
        self.assertFalse(result['imported'].duplicate)
        self.assertIsNone(result['issue'])
        self.assertIsNone(result['apple_issue'])
        self.assertEqual(result['output_issues'], {})
        self.assertEqual(sync.load_current(self.root)['capture_fetched_at'], fetched)
        self.assertEqual(len(list((self.root / 'data/runs').iterdir())), 1)
        # Readiness reloads JSON: integer slot keys/tuples become strings/lists.
        self.assertEqual(self.service.ready_export(), json.loads(json.dumps(result['report'])))
        self.assertEqual(self.service.ready_apple_export(), result['apple_report'])
        for report, key, path in [(result['report'], 'csv_sha256', 'output/wakeup.csv'),
                                  (result['apple_report'], 'ics_sha256', 'output/calendar.ics')]:
            data = (self.root / path).read_bytes()
            self.assertTrue(data)
            self.assertEqual(hashlib.sha256(data).hexdigest(), report[key])
        with sync.exclusive_sync(self.root):
            pass

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

    def test_manual_json_without_bookmark_ack_reopens_saved_timetable(self):
        self.service.confirm_term()
        self.service.run(capture=write_capture(self.root, config=self.service.config()))
        self.assertNotIn('bookmark_ack', self.service.state())
        before = self.state_bytes()
        reopened = DesktopService(self.root)
        reopened.initialize()
        self.assertEqual(reopened.setup_step(), 0)
        self.assertNotIn('bookmark_ack', reopened.state())
        self.assertEqual(self.state_bytes(), before)
        self.assertIsNotNone(reopened.ready_export())
        self.assertIsNotNone(reopened.ready_apple_export())
        # A saved timetable from a different term cannot complete new setup.
        reopened.save_settings({**reopened.config(), 'semester': '2026-2027:2',
                                'range_mode': 'custom'})
        self.assertEqual(reopened.setup_step(), 2)

    def test_incomplete_manual_json_does_not_complete_onboarding(self):
        self.service.confirm_term()
        capture = write_capture(self.root, config=self.service.config())
        value = json.loads(capture.read_text())
        value['complete'] = False
        capture.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises((DataError, SourceError)):
            self.service.run(capture=capture)
        reopened = DesktopService(self.root)
        reopened.initialize()
        self.assertEqual(reopened.setup_step(), 2)
        self.assertIsNone(sync.load_current(self.root))
        self.assertNotIn('bookmark_ack', reopened.state())

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
        self.assertEqual('课程时间与作息设置不一致', result['issue'].title)
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
        real_replace = sync.os.replace
        def fail_calendar(source, destination):
            # Both shared repair and the independent Apple exporter must see
            # the same persistent filesystem failure.
            if Path(destination) == file:
                raise PermissionError('synthetic write denial')
            return real_replace(source, destination)
        with patch('os.replace', side_effect=fail_calendar):
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
        job, observer = self.observed_worker()
        self.assertTrue(job.start())
        observer.stage('waiting')
        observer.wait_for(lambda: observer.polls >= 2, 'old file scans', timeout=5)
        self.assertEqual(job.stage, 'waiting')
        self.assertFalse(job.start(capture=path))
        job.picker_open.set()
        observer.wait_for(lambda: observer.paused_polls > 0, 'picker pause', timeout=3)
        self.assertFalse(job.submit_file(None))  # cancelling the dialog changes no baseline
        polls = observer.polls
        job.picker_open.clear()
        observer.wait_for(lambda: observer.polls >= polls + 2, 'old file scans after cancel', timeout=5)
        self.assertEqual(job.stage, 'waiting')
        self.assertFalse((self.root / 'data/current.json').exists())
        self.assertTrue(job.submit_file(path))
        self.assert_worker_import(job, observer, NOW)

    def test_waiter_accepts_new_download_but_not_old_file_after_picker_cancel(self):
        downloads = self.root / 'downloads'
        downloads.mkdir()
        write_capture(downloads)
        self.service.save_settings({**CONFIG, 'downloads_dir': str(downloads)})
        job, observer = self.observed_worker()
        self.assertTrue(job.start())
        observer.stage('waiting')
        observer.wait_for(lambda: observer.polls >= 2, 'old file scans', timeout=5)
        self.assertFalse(job.start(capture=downloads / 'shsmu-capture-test.json'))
        job.picker_open.set()
        observer.wait_for(lambda: observer.paused_polls > 0, 'picker pause', timeout=3)
        self.assertFalse((self.root / 'data/current.json').exists())
        path = downloads / 'shsmu-capture-new.json'
        path.write_bytes(write_capture(self.root, fetched=LATER).read_bytes())
        paused_polls = observer.paused_polls
        observer.wait_for(lambda: observer.paused_polls >= paused_polls + 2, 'held picker', timeout=3)
        self.assertEqual(job.stage, 'waiting')
        self.assertFalse((self.root / 'data/current.json').exists())
        self.assertFalse(job.submit_file(None))
        # A download made while the picker was open must not become an old
        # baseline file when the picker is cancelled. Real two-scan stability
        # detection and the complete import/export path remain in use.
        job.picker_open.clear()
        self.assert_worker_import(job, observer, LATER)

    def test_worker_cancel_is_bounded_and_releases_the_lock(self):
        self.service.save_settings({**CONFIG, 'downloads_dir': str(self.root)})
        job, _ = self.observed_worker()
        job.start()
        job.cancel()
        job.thread.join(3)
        self.assertFalse(job.busy)
        self.assertFalse((self.root / 'data/current.json').exists())
        with sync.exclusive_sync(self.root):
            pass


    def test_error_copy_preserves_original_classification_inputs(self):
        from desktop_service import explain_error
        cases = [
            (DataError('账号与当前记录不符'), '登录账号与当前课表不一致'),
            (DataError('匿名校验标识不一致'), '登录账号与当前课表不一致'),
            (DataError('学期范围不一致'), '课表与学期设置不一致'),
            (DataError('JSON 文件错误'), '课表文件暂不可用'),
            (DataError('数据目录断开'), '无法访问原课表文件夹'),
            (DataError('原数据目录缺少完整版本索引，请保留目录并恢复索引，不要新建历史。'), '原课表记录不完整'),
            (DataError('配置文件不是有效的 UTF-8 JSON；请对照 config.example.json 检查双引号、逗号和日期。'), '学期设置无法使用'),
            (DataError('自定义作息第 3 节无效；请使用 HH:MM，保证下课晚于上课，且与上一节不重叠。'), '第 3 节时间有误'),
            (DataError('没有已提交的完整课表，请先获取课表。'), '尚未保存课表'),
            (sync.SyncCancelled('已取消'), '操作已取消'),
        ]
        for error, expected in cases:
            with self.subTest(original=str(error)):
                issue = explain_error(error)
                self.assertEqual(issue.title, expected)
                self.assertEqual(issue.detail, str(error))
        unknown = explain_error(RuntimeError('synthetic private reason'))
        self.assertEqual(unknown.title, '本次操作未完成')
        self.assertEqual(unknown.detail, 'RuntimeError')
        self.assertNotIn('已保存', unknown.next_step)
        for apple in (False, True):
            issue = explain_error(PermissionError('synthetic'), exporting=True, apple=apple)
            self.assertEqual(issue.title, '文件操作未完成')
            self.assertNotIn('已保存', issue.next_step)

    def test_reveal_only_selects_a_file_and_missing_log_uses_generic_issue(self):
        from desktop import reveal_file
        from desktop_service import explain_error
        target = self.root / 'synthetic-log.zip'
        target.write_bytes(b'synthetic')
        selected = str(target.resolve())
        for platform, expected in (
                ('win32', ['explorer.exe', '/select,', selected]),
                ('darwin', ['/usr/bin/open', '-R', selected])):
            with self.subTest(platform=platform), patch('platform_support.sys.platform', platform), \
                    patch('desktop.subprocess.Popen') as process:
                reveal_file(target)
                process.assert_called_once_with(expected)
        with self.assertRaises(DataError) as caught:
            reveal_file(self.root / 'missing-log.zip')
        issue = explain_error(caught.exception)
        self.assertEqual(issue.title, '本次操作未完成')
        self.assertNotIn('重新生成', issue.next_step)

    def test_wakeup_reminders_follow_export_instead_of_fixed_autumn_defaults(self):
        from datetime import timedelta
        from desktop import wakeup_setup_reminder
        report = self.service.run(capture=write_capture(self.root))['report']
        title, body = wakeup_setup_reminder(report)
        self.assertEqual('导入后请核对日期和作息', title)
        self.assertIn('40 分钟', body)
        self.assertIn('2026-09-07', body)
        self.assertNotIn('不要保留 9 月 4 日', body)
        self.assertNotIn('50 分钟', body)

        # Another valid time table/term must not receive this autumn's instructions.
        report = json.loads(json.dumps(report))
        report['first_monday'] = '2027-03-01'
        for number, (start, end) in report['slot_times'].items():
            hour, minute, second = map(int, start.split(':'))
            later = timedelta(hours=hour, minutes=minute + 50)
            seconds = int(later.total_seconds())
            report['slot_times'][number] = [start, f'{seconds // 3600:02}:{seconds // 60 % 60:02}:00']
        title, body = wakeup_setup_reminder(report)
        self.assertIn('50 分钟', body)
        self.assertIn('2027-03-01', body)
        self.assertNotIn('40 分钟', title + body)
        self.assertNotIn('9 月', title + body)
        report['slot_times']['1'][1] = '08:30:00'
        title, body = wakeup_setup_reminder(report)
        self.assertEqual('导入后请核对日期和作息', title)
        self.assertIn('逐节', body)
        self.assertIn('各节课时长不同', body)
        self.assertNotIn('每节课时长：', body)


class DesktopWidgetTests(unittest.TestCase):
    def setUp(self):
        self.windows, self.uis, self.extra_threads = [], [], []
        self.callback_errors, self.lifecycle = [], []
        self.widget_patches = ExitStack()
        self.cleaned = False
        self.temp = tempfile.TemporaryDirectory(prefix='课表 widgets ')
        # This single owner decides when deletion is safe, including setUp failure.
        # Never let TemporaryDirectory's independent finalizer race a live worker.
        self.temp._finalizer.detach()
        self.addCleanup(self.cleanup_widgets)
        self.ui = self.new_ui()
        self.window = self.ui.window
        self.ui.service.save_settings(CONFIG)
        self.ui.preference_path = Path(self.temp.name) / 'preferences.json'

    def new_ui(self):
        import tkinter as tk
        from desktop import AssistantWindow
        window = tk.Tk()
        self.windows.append(window)  # Own even a partially constructed window.
        window.withdraw()
        ui = AssistantWindow(window, Path(self.temp.name))
        self.uis.append(ui)
        original = window.report_callback_exception
        def callback_error(kind, error, tb):
            self.callback_errors.append(error)
            self.lifecycle.append((time.monotonic(), 'callback_error', repr(error)))
            original(kind, error, tb)
        window.report_callback_exception = callback_error
        return ui

    def widget_patch(self, *args, **kwargs):
        # Patches used by workers stay installed through failure cleanup.
        return self.widget_patches.enter_context(patch(*args, **kwargs))

    def widget_state(self):
        return [dict(running=ui.running, busy=ui.job.busy, stage=ui.job.stage,
                     alive=bool(ui.job.thread and ui.job.thread.is_alive()),
                     disposed=ui.disposed) for ui in self.uis]

    def wait_tk(self, predicate, *, window=None, timeout=WORKER_INTEGRATION_TIMEOUT,
                check_errors=True):
        window = window if window is not None else self.window
        started = time.monotonic()
        deadline = started + timeout
        pending, errors, completed = [None], [], [False]
        self.lifecycle.append((time.monotonic(), 'wait_start', self.widget_state()))
        def check():
            pending[0] = None
            try:
                if check_errors and self.callback_errors:
                    raise AssertionError(f'Tk callback failed: {self.callback_errors!r}')
                if predicate():
                    completed[0] = True
                    window.quit()
                elif time.monotonic() >= deadline:
                    self.lifecycle.append((time.monotonic(), 'deadline_expired',
                                           dict(started=started, deadline=deadline,
                                                timeout=timeout)))
                    raise AssertionError(f'Tk completion timeout after {timeout}s: '
                                         f'{self.widget_state()}')
                else:
                    pending[0] = window.after(20, check)
            except Exception as error:
                errors.append(error)
                self.lifecycle.append((time.monotonic(), 'wait_error', repr(error)))
                window.quit()
        pending[0] = window.after(0, check)
        try:
            window.mainloop()
        finally:
            if pending[0] is not None:
                window.after_cancel(pending[0])
        if errors:
            raise errors[0]
        self.assertTrue(completed[0], 'Tk mainloop exited before completion')
        self.lifecycle.append((time.monotonic(), 'wait_complete', self.widget_state()))

    def wait_ui(self, ui, *, timeout=WORKER_INTEGRATION_TIMEOUT):
        self.wait_tk(lambda: not ui.running and not ui.job.busy and ui.job.events.empty(),
                     window=ui.window, timeout=timeout)
        self.assertFalse(ui.job.thread is not None and ui.job.thread.is_alive())

    def cleanup_widgets(self, timeout=WORKER_INTEGRATION_TIMEOUT):
        if self.cleaned:
            return
        self.lifecycle.append((time.monotonic(), 'cleanup_start', self.widget_state()))
        for ui in self.uis:
            if ui.job.busy and ui.job.stage not in ('committing', 'exporting', 'result'):
                ui.job.cancelled.set()  # Existing token; no synchronous diagnostic I/O.
        def settled():
            return (all(not ui.job.busy and (ui.disposed or
                        (not ui.running and ui.job.events.empty())) for ui in self.uis)
                    and all(not thread.is_alive() for thread in self.extra_threads))
        try:
            if not settled():
                active = next(ui.window for ui in self.uis if not ui.disposed)
                self.wait_tk(settled, window=active, timeout=timeout, check_errors=False)
            self.assertTrue(settled(), 'Active widget worker must retain its directory')
            self.lifecycle.append((time.monotonic(), 'workers_exited', self.widget_state()))
            for ui in reversed(self.uis):
                ui.dispose()
            for window in reversed(self.windows):
                if not any(ui.window is window for ui in self.uis):
                    window.destroy()  # Constructor failed before registration.
            self.widget_patches.close()
            self.temp.cleanup()
            self.cleaned = True
            self.lifecycle.append((time.monotonic(), 'cleanup_complete', self.widget_state()))
        except Exception:
            frames = sys._current_frames()
            self.lifecycle.append((time.monotonic(), 'cleanup_retained', dict(
                directory=self.temp.name, state=self.widget_state(),
                stacks={t.name: traceback.format_stack(frames[t.ident])
                        for t in threading.enumerate() if t.ident in frames})))
            raise
        self.assertFalse(self.callback_errors, f'Tk callback errors: {self.callback_errors!r}')

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
        with patch('desktop.filedialog.asksaveasfilename', return_value=''), patch('desktop.reveal_file', return_value=Mock(poll=Mock(return_value=0))) as reveal:
            save.invoke()
            reveal.assert_not_called()
            self.assertTrue(dialog.winfo_exists())
        with patch('desktop.filedialog.asksaveasfilename', return_value=str(target)), patch('desktop.reveal_file', return_value=Mock(poll=Mock(return_value=0))) as reveal:
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
        self.assertEqual(len(self.callback_errors), 1)
        self.callback_errors.clear()  # This test explicitly invokes the error handler.

    def test_uncaught_background_error_is_failed_and_only_queues_ui_update(self):
        calls, queued, hook_errors = [], [], []
        original_show = self.ui.show_issue
        original_put = self.ui.job.events.put
        def show(issue):
            calls.append(threading.current_thread())
            return original_show(issue)
        def put(value, *args, **kwargs):
            queued.append((value[0], threading.current_thread()))
            return original_put(value, *args, **kwargs)
        def hook(args):
            try:
                self.ui.handle_thread_error(args.exc_value)
                self.assertNotIn(threading.current_thread(), calls)
            except Exception as error:
                hook_errors.append(error)
        def fail():
            raise RuntimeError('PRIVATE_THREAD_DETAIL')
        self.widget_patch('threading.excepthook', side_effect=hook)
        self.widget_patch('desktop.AssistantWindow.show_issue',
                          autospec=True, side_effect=lambda ui, issue: show(issue))
        self.widget_patches.enter_context(patch.object(self.ui.job.events, 'put', side_effect=put))
        worker = threading.Thread(target=fail, name='widget-error-worker')
        self.extra_threads.append(worker)
        worker.start()
        self.wait_tk(lambda: not worker.is_alive() and self.ui.job.events.empty())
        self.assertFalse(worker.is_alive())
        self.assertEqual(hook_errors, [])
        self.assertEqual(queued, [('error', worker)])
        self.assertEqual(calls, [threading.current_thread()])
        record = self.ui.service.diagnostics.record
        self.assertEqual(record['status'], 'failed')
        self.assertNotIn('PRIVATE_THREAD_DETAIL', json.dumps(record))
        self.assertTrue(any(e['event'] == 'unhandled_thread_failed' for e in record['events']))

    def test_picker_cancel_keeps_current_waiting_job(self):
        self.ui.service.save_settings({**CONFIG, 'downloads_dir': self.temp.name})
        self.ui.start()
        self.wait_tk(lambda: self.ui.job.stage == 'waiting', timeout=5)
        self.widget_patch('desktop.filedialog.askopenfilename', return_value='')
        self.ui.pick_capture()
        self.assertTrue(self.ui.job.busy)
        self.assertFalse(self.ui.job.cancelled.is_set())
        self.ui.job.cancel()
        self.wait_ui(self.ui, timeout=5)  # Preserve this test's cancellation budget.
        with sync.exclusive_sync(self.ui.service.root):
            pass

    def test_user_setting_forms_and_phone_card_render_at_font_scales(self):
        from tkinter import ttk
        self.ui.service.run(capture=write_capture(Path(self.temp.name)))
        for factor in (1.0, 1.25, 1.5):
            self.window.tk.call('tk', 'scaling', 96 / 72 * factor)
            self.ui._style()
            self.ui.show_settings()
            self.buttons()['学期、作息与文件夹详细设置'].invoke()
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

    def file_buttons(self, ui=None):
        from tkinter import ttk
        label = '在 Finder 中显示' if sys.platform == 'darwin' else '打开文件位置'
        return [w for w in self.widgets(ui) if isinstance(w, ttk.Button)
                and str(w.cget('text')) == label]

    def test_startup_resumes_bookmark_guide_until_first_capture(self):
        import tkinter as tk
        from desktop import AssistantWindow
        self.assertIn('确认学期并继续', self.buttons())
        self.buttons()['确认学期并继续'].invoke()
        self.assertIn('复制安装页地址', self.buttons())
        self.assertNotIn('获取课表', self.buttons())
        self.buttons()['已添加书签，继续'].invoke()
        self.assertIn('获取课表', self.buttons())
        self.assertIn('查看书签安装说明', self.buttons())
        self.assertIn('首次使用',
                      [str(w.cget('text')) for w in self.widgets() if 'text' in w.keys()])
        for captured in (False, True):
            with self.subTest(captured=captured):
                if captured:
                    self.ui.service.run(capture=write_capture(
                        Path(self.temp.name), config=self.ui.service.config()))
                reopened = self.new_ui()
                window = reopened.window
                try:
                    window.update_idletasks()
                    self.assertEqual('复制安装页地址' in self.buttons(reopened), not captured)
                    self.assertEqual('重新获取课表' in self.buttons(reopened), captured)
                    self.assertEqual(reopened.canvas.yview()[0], 0.0)
                    reopened.nav_buttons[0].invoke()
                    self.assertEqual('复制安装页地址' in self.buttons(reopened), not captured)
                finally:
                    self.wait_ui(reopened)
                    reopened.dispose()

    def test_both_exports_on_home_and_results_locate_exact_files(self):
        config = student_term_config(CONFIG)
        self.ui.service.save_settings(config)
        self.ui.service.acknowledge_bookmark()
        result = self.ui.service.run(capture=write_capture(Path(self.temp.name), config=config))
        for show in (self.ui.show_home, lambda: self.ui.show_result(result)):
            show()
            self.window.update_idletasks()
            if self.ui.page == 'home':
                entry = self.buttons()['查看文件与导入步骤']
                self.assertFalse(entry.instate(['disabled']))
                entry.invoke()
                self.window.update_idletasks()
                self.assertEqual(self.ui.page, 'results')
            buttons = self.buttons()
            with patch('desktop.reveal_file', return_value=Mock(poll=Mock(return_value=0))) as reveal:
                files = self.file_buttons()
                self.assertEqual(len(files), 2)
                files[0].invoke()
                files[1].invoke()
                self.assertEqual([call.args[0] for call in reveal.call_args_list],
                    [self.ui.service.root / 'output/wakeup.csv', self.ui.service.root / 'output/calendar.ics'])
        (self.ui.service.root / 'output/calendar.ics').write_bytes(b'tampered')
        with patch('desktop.reveal_file', return_value=Mock(poll=Mock(return_value=0))) as reveal:
            self.ui.reveal_apple()
            reveal.assert_not_called()
        self.assertIn('重新生成导入文件', self.buttons())

    def test_reopened_setup_imports_existing_json_and_exposes_both_exports(self):
        self.ui.service.confirm_term()
        self.ui.service.acknowledge_bookmark()
        capture = write_capture(Path(self.temp.name), config=self.ui.service.config())
        before = capture.read_bytes()
        bookmark_ack = self.ui.service.state()['bookmark_ack']
        self.ui.dispose()
        reopened = self.new_ui()
        self.assertIn('复制安装页地址', self.buttons(reopened))
        self.assertIn('选择已下载的课表', self.buttons(reopened))
        self.widget_patch('desktop.filedialog.askopenfilename', return_value=str(capture))
        self.widget_patch('desktop_service.wait_capture',
                          side_effect=AssertionError('must use selected JSON'))
        observation = WorkerObservation(reopened.job)
        # Fixed integration budget starts immediately before the actual button.
        started = time.monotonic()
        self.buttons(reopened)['选择已下载的课表'].invoke()
        self.wait_ui(reopened, timeout=max(0, WORKER_INTEGRATION_TIMEOUT -
                                          (time.monotonic() - started)))
        self.assertFalse(reopened.job.thread.is_alive())
        self.assertEqual(reopened.page, 'results')
        stages = [stage for stage, _ in observation.events]
        self.assertEqual(stages.count('finished'), 1)
        self.assertNotIn('error', stages)
        with sync.exclusive_sync(reopened.service.root):
            pass
        self.assertFalse(reopened.running)
        self.assertIsNotNone(reopened.service.ready_export())
        self.assertIsNotNone(reopened.service.ready_apple_export())
        with patch('desktop.reveal_file', return_value=Mock(poll=Mock(return_value=0))) as reveal:
            files = self.file_buttons(reopened)
            self.assertEqual(len(files), 2)
            files[0].invoke()
            files[1].invoke()
            self.assertEqual([call.args[0] for call in reveal.call_args_list],
                [reopened.service.root / 'output/wakeup.csv', reopened.service.root / 'output/calendar.ics'])
        self.assertEqual(capture.read_bytes(), before)
        self.assertEqual(reopened.service.state()['bookmark_ack'], bookmark_ack)
        reopened.show_home()
        self.assertIn('重新获取课表', self.buttons(reopened))

    def test_tk_finished_live_worker_retains_directory_and_patches_until_release(self):
        release, finished = threading.Event(), threading.Event()
        root = Path(self.temp.name)
        marker = self.widget_patch('desktop_service.wait_capture',
                                  side_effect=AssertionError('selected capture only'))
        put = self.ui.job.events.put
        gate_errors, heartbeat = [], []
        def held_finish(value, *args, **kwargs):
            result = put(value, *args, **kwargs)
            if value[0] == 'finished':
                finished.set()
                if not release.wait(WORKER_INTEGRATION_TIMEOUT):  # Worker-only latch.
                    gate_errors.append('Controlled gate was not released')
                (root / 'worker-exited.txt').write_text('synthetic', encoding='utf-8')
            return result
        self.widget_patches.enter_context(patch.object(self.ui.job.events, 'put',
                                                      side_effect=held_finish))
        self.ui.start(capture=write_capture(root))
        try:
            self.wait_tk(lambda: finished.is_set() and not self.ui.running)
            self.assertTrue(self.ui.job.thread.is_alive())
            self.assertEqual(self.ui.page, 'results')
            beat = self.window.after(10, lambda: heartbeat.append(time.monotonic()))
            try:
                with self.assertRaisesRegex(AssertionError, 'Tk completion timeout'):
                    self.wait_ui(self.ui, timeout=0.08)
                with self.assertRaisesRegex(AssertionError, 'Tk completion timeout'):
                    self.cleanup_widgets(timeout=0.08)
            finally:
                self.window.after_cancel(beat)
            # after() cannot preempt native event handling. Assert the fixed
            # deadline, not an invented Tk scheduling/performance guarantee;
            # the isolated process watchdog bounds an unresponsive mainloop.
            expiries = [entry for entry in self.lifecycle if entry[1] == 'deadline_expired']
            self.assertEqual(len(expiries), 2)
            for observed, _, budget in expiries:
                self.assertAlmostEqual(budget['deadline'] - budget['started'], 0.08)
                self.assertGreaterEqual(observed, budget['deadline'])
            self.assertTrue(heartbeat, 'Tk heartbeat must run while the worker is held')
            self.assertTrue(root.is_dir())
            self.assertFalse(self.ui.disposed)
            self.assertFalse(self.temp._finalizer.alive)
            import desktop_service
            self.assertIs(desktop_service.wait_capture, marker)
        finally:
            release.set()
            self.wait_ui(self.ui)
        self.assertEqual(gate_errors, [])
        self.assertTrue((root / 'worker-exited.txt').is_file())
        self.cleanup_widgets()
        self.cleanup_widgets()  # Idempotent explicit + unittest cleanup.
        self.assertFalse(root.exists())

    def test_tk_predicate_error_is_returned_to_the_test(self):
        def fail():
            raise RuntimeError('controlled predicate error')
        with self.assertRaisesRegex(RuntimeError, 'controlled predicate error'):
            self.wait_tk(fail)

    def test_tk_callback_error_cannot_pass_completion(self):
        def fail():
            raise RuntimeError('controlled Tk callback error')
        callback = self.window.after(0, fail)
        try:
            with self.assertRaisesRegex(AssertionError, 'Tk callback failed'):
                self.wait_tk(lambda: True)
            self.assertEqual(len(self.callback_errors), 1)
            self.callback_errors.clear()  # Explicit negative test only.
        finally:
            self.window.after_cancel(callback)

    def test_setup_file_picker_cancel_keeps_setup_and_does_not_import(self):
        self.ui.confirm_term()
        before = self.ui.service.state()
        self.assertIn('选择已下载的课表', self.buttons())
        with patch('desktop.filedialog.askopenfilename', return_value=''):
            self.buttons()['选择已下载的课表'].invoke()
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
                files = self.file_buttons()
                self.assertEqual(len(files), 2)
                self.assertEqual(files[0].instate(['disabled']), fail_wakeup)
                self.assertEqual(files[1].instate(['disabled']), fail_apple)
                shown = [str(w.cget('text')) for w in self.widgets() if 'text' in w.keys()]
                expected = ('导入文件未生成，请查看下方原因后重试。' if fail_wakeup and fail_apple else
                            '部分导入文件未生成，请查看下方状态。已生成的文件仍可使用。')
                self.assertIn(expected, shown)
                self.assertEqual('使用已生成的文件时，请在手机手动导入并核对。' in shown,
                                 fail_wakeup != fail_apple)
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
            self.assertIn('我已导入并核对', self.buttons())

    def test_work_copy_uses_existing_browser_state_and_preserves_diagnostic_input(self):
        self.ui.browser_collection = True
        self.ui.show_work()
        shown = lambda: [str(w.cget('text')) for w in self.widgets() if 'text' in w.keys()]
        self.assertIn('在浏览器获取课表', shown())
        self.assertIn('读取进度请看教务网页；助手收到文件后会继续处理。', shown())
        raw = '收到失败诊断 synthetic；仍在等待'
        self.ui.job.events.put(('waiting', raw))
        self.window.after_cancel(self.ui.poll_id)
        self.ui.poll()
        self.assertEqual(self.ui.details[-1], raw)
        self.assertEqual(self.ui.status.get(), '浏览器读取未完成，请按网页提示处理。助手仍在等待课表文件。')
        self.ui.job.events.put(('processing', '正在检查课表文件…'))
        self.window.after_cancel(self.ui.poll_id)
        self.ui.poll()
        self.assertIn('处理课表', shown())
        self.assertNotIn('读取进度请看教务网页；助手收到文件后会继续处理。', shown())
        self.assertEqual(self.ui.status.get(), '正在检查课表文件…')

    def test_both_success_and_wakeup_confirmation_stale_hash_copy(self):
        result = self.ui.service.run(capture=write_capture(Path(self.temp.name)))
        self.ui.show_result(result)
        shown = [str(w.cget('text')) for w in self.widgets() if 'text' in w.keys()]
        self.assertIn('导入文件已生成', shown)
        self.assertIn('与上次相比：新增 1 次 · 移除 0 次 · 修改 0 次', shown)
        self.assertNotIn('使用已生成的文件时，请在手机手动导入并核对。', shown)
        self.ui.show_phone()
        self.ui.confirm_phone()
        saved_hash = self.ui.service.state()['phone_confirmed_csv']
        self.ui.show_phone()
        changed = item()
        changed['details'][0]['Teacher'] = '合成变更教师'
        self.ui.service.run(capture=write_capture(Path(self.temp.name), [changed], fetched=LATER))
        self.ui.confirm_phone()
        self.assertEqual(self.ui.service.state()['phone_confirmed_csv'], saved_hash)
        shown = [str(w.cget('text')) for w in self.widgets() if 'text' in w.keys()]
        self.assertIn('WakeUp 文件已变化或不可用', shown)
        self.ui.show_phone()
        self.ui.confirm_phone()
        self.assertEqual(self.ui.service.state()['phone_confirmed_csv'], self.ui.service.ready_export()['csv_sha256'])
        self.assertNotIn('phone_confirmed_ics', self.ui.service.state())


if __name__ == '__main__':
    unittest.main()
