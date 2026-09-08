"""Local platform boundaries; synthetic data, no browser or personal files."""
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import desktop
import diagnostics
from desktop_service import default_data_root, explain_error
from prepare import build_bookmark
from platform_support import ui_font_family
from source import SourceError
from sync import wait_capture


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mac trial ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_mac_data_and_startup_log_use_application_support(self):
        expected = self.root / 'Library/Application Support/SHSMUScheduleAssistant'
        with patch('sys.platform', 'darwin'), patch('pathlib.Path.home', return_value=self.root), \
                patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'windows-only')}):
            self.assertEqual(default_data_root(), expected)
            with patch.object(sys, 'argv', ['desktop.py']), patch.object(sys, 'excepthook'), \
                    patch.object(threading, 'excepthook'), patch('diagnostics.DiagnosticRecorder') as recorder:
                diagnostics.install_startup_hook()
                recorder.assert_called_once_with(expected)

    def test_windows_data_directory_is_preserved(self):
        with patch('sys.platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': str(self.root)}):
            self.assertEqual(default_data_root(), self.root / 'SHSMUScheduleAssistant')

    def test_platform_helpers_import_without_optional_dependencies(self):
        code = ('import sys; sys.path.insert(0, sys.argv[1]); import platform_support; '
                'assert not any(name in sys.modules for name in ("tkinter", "PIL", "icalendar"))')
        subprocess.run([sys.executable, '-I', '-S', '-c', code, str(Path(__file__).resolve().parent)],
                       check=True, capture_output=True)

    def test_startup_hook_respects_explicit_data_root(self):
        with patch.object(sys, 'argv', ['desktop.py', '--data-root', str(self.root)]), \
                patch.object(sys, 'excepthook'), patch.object(threading, 'excepthook'), \
                patch('diagnostics.DiagnosticRecorder') as recorder:
            diagnostics.install_startup_hook()
            recorder.assert_called_once_with(self.root)

    def test_system_font_selection_has_a_real_fallback(self):
        with patch('sys.platform', 'darwin'):
            self.assertEqual(ui_font_family(['PingFang SC', 'Arial'], 'Arial'), 'PingFang SC')
            self.assertEqual(ui_font_family(['Arial'], 'Arial'), 'Arial')
        with patch('sys.platform', 'win32'):
            self.assertEqual(ui_font_family(['Microsoft YaHei UI'], 'Arial'), 'Microsoft YaHei UI')

    def test_mac_reveal_uses_finder_and_preserves_path_argument(self):
        path = self.root / '测试 文件.csv'
        path.write_text('synthetic', encoding='utf-8')
        with patch('sys.platform', 'darwin'), patch('desktop.subprocess.Popen') as launch:
            desktop.reveal_file(path)
            launch.assert_called_once_with(['/usr/bin/open', '-R', str(path.resolve())])
        with patch('sys.platform', 'win32'), patch('desktop.subprocess.Popen') as launch:
            desktop.reveal_file(path)
            launch.assert_called_once_with(['explorer.exe', '/select,', str(path.resolve())])

    def test_mac_small_scroll_is_not_discarded(self):
        window = object()
        widget = Mock()
        widget.winfo_toplevel.return_value = window
        widget.winfo_class.return_value = 'Canvas'
        ui = SimpleNamespace(window=window, canvas=Mock())
        with patch('sys.platform', 'darwin'):
            desktop.AssistantWindow._wheel(ui, SimpleNamespace(widget=widget, delta=-1))
            ui.canvas.yview_scroll.assert_called_once_with(1, 'units')
        ui.canvas.reset_mock()
        with patch('sys.platform', 'win32'):
            desktop.AssistantWindow._wheel(ui, SimpleNamespace(widget=widget, delta=-120))
            ui.canvas.yview_scroll.assert_called_once_with(1, 'units')
        ui.canvas.reset_mock()
        widget.winfo_class.return_value = 'Text'
        desktop.AssistantWindow._wheel(ui, SimpleNamespace(widget=widget, delta=-1))
        ui.canvas.yview_scroll.assert_not_called()

    def test_mac_installer_changes_guidance_without_changing_bookmark(self):
        config = {'semester': '2026-2027:1', 'start': '2026-09-07', 'end_exclusive': '2027-01-18'}
        resources = Path(__file__).resolve().parent
        with patch('sys.platform', 'win32'):
            windows = build_bookmark(self.root, config, resources=resources, desktop=True)
        with patch('sys.platform', 'darwin'):
            mac = build_bookmark(self.root, config, resources=resources, desktop=True)
        page = (self.root / 'chrome-bookmark.html').read_text(encoding='utf-8')
        self.assertEqual(mac, windows)
        self.assertTrue('Command + Shift + B' in page, 'Mac bookmark shortcut missing')
        self.assertTrue('Command+C' in page, 'Mac copy shortcut missing')
        self.assertFalse('Ctrl + Shift + B' in page, 'Windows shortcut leaked into Mac page')

    def test_unreadable_download_folder_has_actionable_error(self):
        with patch('os.scandir', side_effect=PermissionError('synthetic denied')), \
                patch('os.listdir', side_effect=PermissionError('synthetic denied')):
            with self.assertRaisesRegex(SourceError, '无法读取下载文件夹') as error:
                wait_capture(self.root, timeout=0, progress=lambda text: None)
        issue = explain_error(error.exception)
        self.assertIn('文件已经下载', issue.next_step)

    def test_manual_picker_opens_even_when_download_directory_stat_is_denied(self):
        folder = Mock()
        folder.is_dir.side_effect = PermissionError('synthetic denied')
        ui = SimpleNamespace(running=False, job=SimpleNamespace(picker_open=threading.Event()),
                             service=Mock(), window=object(), start=Mock())
        capture = self.root / 'shsmu-capture-manual.json'
        with patch('desktop.capture_folder', return_value=folder), \
                patch('desktop.filedialog.askopenfilename', return_value=str(capture)) as picker:
            desktop.AssistantWindow.pick_capture(ui)
        picker.assert_called_once()
        self.assertIsNone(picker.call_args.kwargs['initialdir'])
        ui.start.assert_called_once_with(capture=capture)
        self.assertFalse(ui.job.picker_open.is_set())


class MacRecoveryRegressionTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temp = tempfile.TemporaryDirectory(prefix='Mac recovery ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.base = self.root / 'Application Support'
        self.base.mkdir()
        self.window = tk.Tk()
        self.window.withdraw()
        self.ui = None
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        if self.ui is not None:
            self.ui.dispose()
        else:
            self.window.destroy()

    def open_ui(self, preferences):
        import json
        (self.base / 'preferences.json').write_text(json.dumps(preferences), encoding='utf-8')
        with patch('desktop.default_data_root', return_value=self.base):
            self.ui = desktop.AssistantWindow(self.window)
        return self.ui

    def test_malformed_preferences_do_not_crash_startup_hook(self):
        (self.base / 'preferences.json').write_text('[]', encoding='utf-8')
        with patch('diagnostics.default_data_root', return_value=self.base), \
                patch.object(sys, 'argv', ['desktop.py']), patch.object(sys, 'excepthook'), \
                patch.object(threading, 'excepthook'):
            diagnostics.install_startup_hook()

    def test_malformed_preferences_require_recovery_without_new_timetable(self):
        ui = self.open_ui([])
        self.assertTrue(ui.recovery_issue)
        self.assertFalse((self.base / 'config.local.json').exists())
        with patch.object(ui.job, 'start') as start:
            ui.start(export_only=True)
            start.assert_not_called()
        self.assertEqual((self.base / 'preferences.json').read_text(), '[]')

    def test_missing_saved_root_cannot_be_created_by_settings_or_import(self):
        from core import DataError
        missing = self.root / '外置盘 未连接' / '原课表'
        ui = self.open_ui({'data_root': str(missing)})
        config = {'semester': '2026-2027:1', 'start': '2026-09-07', 'end_exclusive': '2027-02-22'}
        for operation in (lambda: ui.service.save_settings(config),
                          lambda: ui.service.run(export_only=True),
                          lambda: ui.service.save_state(export_ready=False),
                          ui.service.initialize):
            with self.assertRaises(DataError):
                operation()
            self.assertFalse(missing.exists())
        self.assertIsNone(ui.service.ready_export())
        self.assertIsNone(ui.service.ready_apple_export())
        self.assertFalse(missing.exists())
        with patch('desktop.filedialog.askopenfilename') as picker:
            ui.pick_capture()
            picker.assert_not_called()

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac system callbacks')
    def test_mac_quit_routes_through_safe_close_and_is_idempotent(self):
        ui = self.open_ui({'data_root': str(self.root)})
        self.assertTrue(self.window.tk.call('info', 'commands', '::tk::mac::Quit'))
        ui.running = True
        with patch.object(ui.job, 'cancel') as cancel, patch.object(ui, 'dispose') as dispose:
            self.window.tk.call('::tk::mac::Quit')
            self.window.tk.call('::tk::mac::Quit')
            cancel.assert_called_once()
            dispose.assert_not_called()
        ui.running = False

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac system callbacks')
    def test_dock_reopen_keeps_the_same_service(self):
        ui = self.open_ui({'data_root': str(self.root)})
        service = ui.service
        self.window.tk.call('::tk::mac::ReopenApplication')
        self.assertEqual(self.window.state(), 'normal')
        self.assertIs(ui.service, service)

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac Finder status')
    def test_finder_failure_has_retry_and_keeps_export_state(self):
        ui = self.open_ui({'data_root': str(self.root)})
        path = self.root / '排错.zip'
        path.write_bytes(b'synthetic')
        process = Mock()
        process.poll.return_value = 1
        with patch('desktop.reveal_file', return_value=process), \
                patch.object(ui, 'show_location_issue') as feedback:
            ui.locate_file(path)
            feedback.assert_called_once()
            self.assertEqual(feedback.call_args.args[0], path)
        self.assertFalse((self.root / 'data/current.json').exists())


    def test_denied_saved_folder_is_blocked_and_uses_fallback_logs(self):
        from platform_support import select_data_root
        import json
        (self.base / 'preferences.json').write_text(json.dumps({'data_root': str(self.root)}))
        with patch('platform_support.os.scandir', side_effect=PermissionError('synthetic denied')):
            selected, issue = select_data_root(self.base)
        self.assertEqual(selected, self.root)
        self.assertTrue(issue)
        with patch('desktop.select_data_root', return_value=(selected, issue)), \
                patch('desktop.default_data_root', return_value=self.base):
            self.ui = desktop.AssistantWindow(self.window)
        self.assertEqual(self.ui.service.diagnostics.directory, self.base / 'local/diagnostics')
        self.assertFalse((self.root / 'config.local.json').exists())

    def test_reselect_original_preserves_history_and_backs_up_preferences(self):
        from desktop_service import DesktopService
        from test_desktop import CONFIG, write_capture
        import hashlib
        original = self.root / '原来的课表'
        service = DesktopService(original)
        service.initialize(); service.save_settings(CONFIG)
        service.run(capture=write_capture(original))
        before = {str(p.relative_to(original)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for folder in ('data', 'output') for p in (original / folder).rglob('*') if p.is_file()}
        ui = self.open_ui([])
        with patch('desktop.filedialog.askdirectory', return_value=str(original)):
            ui.pick_root()
        self.assertIsNone(ui.recovery_issue)
        self.assertEqual(ui.service.root, original)
        after = {str(p.relative_to(original)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for folder in ('data', 'output') for p in (original / folder).rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual([p.read_text() for p in self.base.glob('preferences.recovery-*.json')], ['[]'])
        self.assertIsNotNone(ui.service.ready_export())
        self.assertIsNotNone(ui.service.ready_apple_export())

    def test_recovery_empty_directory_needs_confirmation(self):
        ui = self.open_ui([])
        empty = self.root / '新的目录'; empty.mkdir()
        with patch('desktop.filedialog.askdirectory', return_value=str(empty)), \
                patch('desktop.messagebox.askyesno', return_value=False):
            ui.pick_root()
        self.assertTrue(ui.recovery_issue)
        self.assertEqual(list(empty.iterdir()), [])
        with patch('desktop.filedialog.askdirectory', return_value=str(empty)), \
                patch('desktop.messagebox.askyesno', return_value=True):
            ui.pick_root()
        self.assertIsNone(ui.recovery_issue)
        self.assertTrue((empty / 'config.local.json').is_file())
        self.assertFalse((empty / 'data/current.json').exists())

    def test_recovery_logs_stay_exportable_if_default_directory_cannot_write(self):
        with patch('diagnostics.DiagnosticRecorder._write', side_effect=PermissionError('synthetic denied')):
            ui = self.open_ui([])
        self.assertTrue(ui.service.diagnostics.storage_warning)
        target = self.root / 'support.zip'
        ui.service.diagnostics.export(target)
        self.assertTrue(target.is_file())
        self.assertFalse((self.base / 'config.local.json').exists())

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac Finder status')
    def test_finder_timeout_is_nonblocking_and_does_not_invalidate_files(self):
        ui = self.open_ui({'data_root': str(self.root)})
        file = self.root / 'synthetic.csv'; file.write_bytes(b'unchanged')
        ui.service.save_state(export_ready=True)
        state = (self.root / 'local/desktop-state.json').read_bytes()
        process = Mock(); process.poll.return_value = None
        with patch('desktop.reveal_file', return_value=process), patch('desktop.time.monotonic', return_value=100), \
                patch.object(ui, 'show_location_issue') as feedback:
            ui.locate_file(file)
            process.wait.assert_not_called()
            feedback.assert_not_called()
            callback = ui.reveal_checks[process]
            self.window.after_cancel(callback)
            ui.check_location(process, file, Mock(), 99)
            feedback.assert_called_once()
            process.kill.assert_called_once()
        self.assertEqual((self.root / 'local/desktop-state.json').read_bytes(), state)
        self.assertEqual(file.read_bytes(), b'unchanged')

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac system callbacks')
    def test_command_w_closes_only_the_dialog(self):
        import tkinter as tk
        ui = self.open_ui({'data_root': str(self.root)})
        dialog = tk.Toplevel(self.window)
        ui.bind_dialog_close(dialog)
        self.assertTrue(dialog.bind('<Command-w>'))
        ui.close_window(dialog)
        self.assertEqual(self.window.winfo_exists(), 1)
        self.assertFalse(ui.disposed)

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac quit lifecycle')
    def test_safe_quit_cancels_before_commit_and_finishes_after_commit(self):
        from test_desktop import CONFIG, write_capture
        from test_sync import LATER
        from test_wakeup import item
        from desktop_service import DesktopService
        import tkinter as tk
        for stage in ('waiting', 'processing', 'committing', 'exporting'):
            with self.subTest(stage=stage):
                if self.ui is not None:
                    self.ui.dispose()
                    self.window = tk.Tk(); self.window.withdraw()
                root = self.root / stage
                self.ui = desktop.AssistantWindow(self.window, root)
                ui = self.ui
                ui.service.save_settings({**CONFIG, 'downloads_dir': str(root)})
                ui.service.run(capture=write_capture(root))
                before = (root / 'data/current.json').read_bytes()
                changed = item(); changed['Title'] = 'synthetic changed'
                # A later capture produces a new run even when normalized events match.
                capture = write_capture(root, [changed], fetched=LATER)
                reached, release = threading.Event(), threading.Event()
                original_emit = ui.job.emit
                def gate(name, value):
                    original_emit(name, value)
                    if name == stage:
                        reached.set()
                        if not release.wait(5):
                            raise RuntimeError('test stage timed out')
                with patch.object(ui.job, 'emit', side_effect=gate):
                    ui.start(capture=None if stage == 'waiting' else capture)
                    try:
                        self.assertTrue(reached.wait(5))
                        self.window.tk.call('::tk::mac::Quit')
                        self.window.tk.call('::tk::mac::Quit')
                        self.assertFalse(ui.disposed)
                        self.assertEqual(ui.job.cancelled.is_set(), stage in ('waiting', 'processing'))
                    finally:
                        release.set()
                        ui.job.thread.join(5)
                    self.assertFalse(ui.job.busy)
                    ui.poll()
                self.assertTrue(ui.disposed)
                after = (root / 'data/current.json').read_bytes()
                if stage in ('waiting', 'processing'):
                    self.assertEqual(before, after)
                else:
                    self.assertNotEqual(before, after)
                    reopened = DesktopService(root)
                    self.assertIsNotNone(reopened.ready_export())
                    self.assertIsNotNone(reopened.ready_apple_export())


    def test_disconnected_running_directory_is_not_recreated_by_logs(self):
        from core import DataError
        from desktop_service import DesktopService
        root = self.root / 'mounted'
        service = DesktopService(root, diagnostics_root=self.base)
        service.initialize()
        moved = self.root / 'unmounted'; root.rename(moved)
        with self.assertRaises(DataError):
            service.run(export_only=True)
        self.assertFalse(root.exists())
        self.assertTrue((moved / 'config.local.json').is_file())
        self.assertEqual(service.diagnostics.directory, self.base / 'local/diagnostics')

    def test_disconnected_default_directory_keeps_logs_in_memory(self):
        from core import DataError
        from desktop_service import DesktopService
        import zipfile
        for suffix in ('', 'fallback'):
            with self.subTest(fallback=suffix):
                root = self.root / ('default-' + (suffix or 'same'))
                service = DesktopService(root, diagnostics_root=root / suffix)
                service.initialize()
                moved = root.with_name(root.name + '-unmounted')
                root.rename(moved)
                with self.assertRaises(DataError):
                    service.run(export_only=True)
                service.diagnostics.event('window_closed')
                self.assertFalse(root.exists())
                self.assertTrue(service.diagnostics.records())
                destination = self.root / (root.name + '-support.zip')
                service.diagnostics.export(destination)
                with zipfile.ZipFile(destination) as archive:
                    self.assertIsNone(archive.testzip())
                self.assertFalse(root.exists())


if __name__ == '__main__':
    unittest.main()
