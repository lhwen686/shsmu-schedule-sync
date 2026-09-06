"""Desktop workflow acceptance in disposable directories, never a live account."""
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date

import sync
from core import DataError
from desktop_service import DesktopJob, DesktopService, student_term_config, term_key
from prepare import BROWSER_MODULES
from source import ORIGIN, SourceError, request_key
from test_sync import NOW, LATER, SCOPE
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
        self.root = Path(self.temp.name)
        self.service = DesktopService(self.root)
        self.service.initialize()
        self.service.save_settings(CONFIG)

    def state_bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for d in ('data', 'output')
                for p in (self.root / d).rglob('*') if p.is_file() and p.name != 'sync.lock'}

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


if __name__ == '__main__':
    unittest.main()
