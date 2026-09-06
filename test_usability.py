"""First-use and recovery scenarios in disposable directories, with no live network."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sync
import webcal
from core import DataError
from source import CaptureSource, SourceError
from test_sync import SCOPE
from test_wakeup import item, prepared
from wakeup import build_export, export_current, load_slot_times, slot_times
from test_sync import NOW

ROOT = Path(__file__).resolve().parent
CONFIG = {k: SCOPE[k] for k in ('semester', 'start', 'end_exclusive')}


class UsabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_settings_accept_bom_and_relative_download_directory(self):
        path = self.root / 'config.local.json'
        path.write_text(json.dumps({**CONFIG, 'downloads_dir': '收到的课表'}), encoding='utf-8-sig')
        config = sync.load_settings(path)
        self.assertEqual(config['semester'], CONFIG['semester'])
        self.assertEqual(sync.capture_folder(config, path), self.root / '收到的课表')
        with patch.dict(os.environ, SHSMU_TEST_DOWNLOADS=str(self.root)):
            self.assertEqual(sync.capture_folder({}, path, Path('$SHSMU_TEST_DOWNLOADS')), self.root)

    def test_invalid_settings_report_actionable_errors(self):
        path = self.root / 'config.local.json'
        cases = ['{', '[]', '{}', json.dumps({**CONFIG, 'semester': '2026-2028:1'}),
                 json.dumps({**CONFIG, 'start': '2026-02-30'}), json.dumps({**CONFIG, 'start': 20260907}),
                 json.dumps({**CONFIG, 'downloads_dir': []})]
        for content in cases:
            with self.subTest(content=content):
                path.write_text(content, encoding='utf-8')
                with self.assertRaises(DataError):
                    sync.load_settings(path)

    def test_prepare_bad_config_and_missing_repair_never_report_success(self):
        config_path = self.root / 'config.local.json'
        config_path.write_text('{', encoding='utf-8')
        for flags, message in ((['--prepare'], 'JSON'), (['--repair'], '尚无完整课表'),
                               (['--config', str(self.root / 'missing.json')], '配置文件不存在')):
            output = io.StringIO()
            with patch.object(sync, 'ROOT', self.root), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertEqual(sync.main(flags), 2)
            self.assertIn(message, output.getvalue())
            self.assertNotIn('已从完整快照恢复', output.getvalue())
        self.assertFalse((self.root / 'missing.json').exists())

    def wait_with_steps(self, steps, timeout=8):
        ticks = [0]
        def sleep(_):
            ticks[0] += 1
            if ticks[0] in steps:
                steps[ticks[0]]()
        output = io.StringIO()
        with patch.object(sync.time, 'monotonic', side_effect=lambda: ticks[0]), patch.object(sync.time, 'sleep', side_effect=sleep), contextlib.redirect_stdout(output):
            result = sync.wait_capture(self.root, timeout)
        return result, ticks[0], output.getvalue()

    def test_wait_detects_overwritten_same_filename(self):
        path = self.root / 'shsmu-capture-test.json'
        path.write_text('old', encoding='utf-8')
        result, ticks, _ = self.wait_with_steps({1: lambda: path.write_text('{"new":true}', encoding='utf-8')})
        self.assertEqual(result, path)
        self.assertEqual(ticks, 2)

    def test_wait_stabilizes_growing_file_before_reading(self):
        path = self.root / 'shsmu-capture-test.json'
        result, ticks, _ = self.wait_with_steps({1: lambda: path.write_text('{', encoding='utf-8'),
                                               2: lambda: path.write_text('{"complete":true}', encoding='utf-8')})
        self.assertEqual(json.loads(result.read_text())['complete'], True)
        self.assertEqual(ticks, 3)

    def test_wait_ignores_temporary_download_and_reports_diagnostic(self):
        pending = self.root / 'shsmu-capture-test.json.crdownload'
        path = self.root / 'shsmu-capture-test.json'
        diagnostic = self.root / 'shsmu-diagnostic-test.json'
        pending.write_text('{}', encoding='utf-8')
        result, _, output = self.wait_with_steps({1: lambda: diagnostic.write_text('{}', encoding='utf-8'),
                                                 2: lambda: pending.rename(path)})
        self.assertEqual(result, path)
        self.assertEqual(output.count('收到失败诊断文件'), 1)

    def test_wait_does_not_silently_import_existing_file(self):
        (self.root / 'shsmu-capture-old.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(SourceError, '导入已下载课表'):
            self.wait_with_steps({}, timeout=3)

    def test_capture_errors_do_not_echo_file_contents(self):
        path = self.root / 'capture.json'
        for value in ('{private-value', '[]', '{"format":"shsmu-diagnostic-v1"}'):
            path.write_text(value, encoding='utf-8')
            with self.assertRaises(SourceError) as caught:
                CaptureSource(path, CONFIG)
            self.assertNotIn('private-value', str(caught.exception))
        with self.assertRaisesRegex(SourceError, '无法读取'):
            CaptureSource(self.root / 'missing.json', CONFIG)

    def test_malformed_upload_config_is_exit_four_without_network(self):
        path = self.root / 'local/webcal.json'
        path.parent.mkdir()
        for value in ('{private-value', '[]', '{"enabled":"false"}', '{"enabled":true,"origin":null}',
                      '{"enabled":true,"origin":"https://example.invalid:bad"}'):
            path.write_text(value, encoding='utf-8')
            output = io.StringIO()
            with patch.object(sync, 'ROOT', self.root), patch.object(webcal, 'request') as request, contextlib.redirect_stderr(output):
                self.assertEqual(sync.main(['--upload-only']), 4)
            request.assert_not_called()
            self.assertNotIn('private-value', output.getvalue())
            self.assertIn('仅上传日历', output.getvalue())

    def test_optional_upload_accepts_bom_and_explains_local_only(self):
        path = self.root / 'local/webcal.json'
        path.parent.mkdir()
        path.write_text('{"enabled": false}', encoding='utf-8-sig')
        output = io.StringIO()
        with patch.object(webcal, 'request') as request, contextlib.redirect_stdout(output):
            self.assertIsNone(webcal.publish_current(self.root))
        request.assert_not_called()
        self.assertIn('未启用 WebCal', output.getvalue())

    def test_custom_wakeup_times_match_actual_source_and_label_unobserved(self):
        path = self.root / 'local/wakeup-slots.json'
        path.parent.mkdir()
        values = [[start[:5], end[:5]] for start, end in slot_times().values()]
        values[0] = ['08:10', '08:50']
        values[1] = ['09:00', '09:40']
        path.write_text(json.dumps(values), encoding='utf-8-sig')
        source = item()
        source['event'].update(Start='2026-09-07T08:10:00', End='2026-09-07T09:40:00')
        snapshot, bundle = prepared([source])
        with self.assertRaisesRegex(DataError, 'local/wakeup-slots.json'):
            build_export(snapshot, bundle)
        csv_data, guide, report = build_export(snapshot, bundle, load_slot_times(self.root))
        self.assertEqual(report['event_count'], 1)
        self.assertIn('自定义', guide.decode('utf-8-sig'))
        self.assertIn('08:10', guide.decode('utf-8-sig'))
        self.assertTrue(csv_data.startswith(b'\xef\xbb\xbf'))

    def test_invalid_custom_times_preserve_existing_exports(self):
        snapshot, bundle = prepared([item()])
        run = self.root / 'data/runs/2026-09-06T120000Z_12345678'
        sync.publish(self.root, run, snapshot, {'synced_at': NOW, 'summary': {'ADDED': 1, 'REMOVED': 0, 'CHANGED': 0}, 'changes': []}, None)
        (run / 'capture.json').write_text(json.dumps(bundle), encoding='utf-8')
        export_current(self.root)
        expected = {p: p.read_bytes() for p in (self.root / 'output').iterdir()}
        path = self.root / 'local/wakeup-slots.json'
        for values in ([['08:00', '08:40']], [['08:00', '08:40']] * 14, [['25:00', '26:00']] * 14):
            path.write_text(json.dumps(values), encoding='utf-8')
            with self.assertRaises(DataError):
                export_current(self.root)
            self.assertEqual({p: p.read_bytes() for p in expected}, expected)
        self.assertIsNone(load_slot_times(self.root / 'other'))

    @unittest.skipUnless(os.name == 'nt', 'Windows CMD entrypoint')
    def test_setup_cmd_real_exit_status_and_success_message(self):
        # A real temporary interpreter, with a local dummy pip; no packages or network.
        self.root = self.root / '中文与 spaces'
        self.root.mkdir()
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(self.root / '.venv')], check=True, capture_output=True)
        (self.root / 'setup.cmd').write_bytes((ROOT / 'setup.cmd').read_bytes())
        pip = self.root / 'pip'
        pip.mkdir()
        (pip / '__init__.py').write_text('', encoding='utf-8')
        (pip / '__main__.py').write_text("import os; raise SystemExit(int(os.environ['SHSMU_TEST_PIP_EXIT']))", encoding='utf-8')
        (self.root / 'sync.py').write_text("import os; raise SystemExit(int(os.environ['SHSMU_TEST_PREPARE_EXIT']))", encoding='utf-8')
        for pip_exit, prepare_exit, expected in ((1, 0, 1), (0, 2, 1), (0, 0, 0)):
            with self.subTest(pip=pip_exit, prepare=prepare_exit):
                env = {**os.environ, 'SHSMU_TEST_PIP_EXIT': str(pip_exit), 'SHSMU_TEST_PREPARE_EXIT': str(prepare_exit)}
                result = subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'setup.cmd'], cwd=self.root,
                                        env=env, input='\n', capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertEqual('安装完成。' in result.stdout, expected == 0, result.stdout)
        (self.root / 'sync.py').write_text("import json, sys; from pathlib import Path; Path('cli-args.json').write_text(json.dumps(sys.argv[1:])); raise SystemExit(2)", encoding='utf-8')
        for name in ('同步课表.cmd', '导入已下载课表.cmd'):
            (self.root / name).write_bytes((ROOT / name).read_bytes())
        for name, arguments, expected in (('同步课表.cmd', ['课表 文件.json'], ['课表 文件.json']),
                                           ('导入已下载课表.cmd', [], ['--select-capture']),
                                           ('导入已下载课表.cmd', ['课表 文件.json'], ['课表 文件.json'])):
            result = subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', name, *arguments], cwd=self.root,
                                    input='\n', capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(json.loads((self.root / 'cli-args.json').read_text()), expected)


if __name__ == '__main__':
    unittest.main()
