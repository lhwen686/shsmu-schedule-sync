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


if __name__ == '__main__':
    unittest.main()
