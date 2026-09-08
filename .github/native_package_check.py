"""Check and package a native build using only temporary synthetic data."""
import json
import os
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from diagnostics import APP_VERSION
from package_desktop import mac_component


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-dir', type=Path, default=ROOT / 'dist/native')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist/upload')
    args = parser.parse_args()
    native = args.native_dir.resolve()
    upload = args.output_dir.resolve()
    upload.mkdir(parents=True, exist_ok=True)
    is_mac = sys.platform == 'darwin'
    executable = native / ('医学院课表助手.app/Contents/MacOS/医学院课表助手'
                           if is_mac else '医学院课表助手.exe')
    env = {key: value for key, value in os.environ.items()
           if key not in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV')}
    env['PATH'] = ('/usr/bin:/bin:/usr/sbin:/sbin' if is_mac else
                   os.path.join(os.environ['SystemRoot'], 'System32'))
    with tempfile.TemporaryDirectory(prefix='课表 中文 空格 ') as temporary:
        root = Path(temporary).resolve()
        report_path = root / 'self-test.json'
        result = subprocess.run([str(executable), '--data-root', str(root / 'data'),
                                 '--self-test', str(report_path)], env=env, timeout=180)
        report = json.loads(report_path.read_text(encoding='utf-8'))
        (upload / 'self-test.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        assert result.returncode == 0 and report['status'] == 'PASS', report
        assert report['frozen'] and not report['python_on_path'], report
        assert report['dependency_paths_in_bundle'] and report['bundled_bookmark_verified'], report
        assert report['app_version'] == APP_VERSION and report['collector_revision'] == '2026-09-08.12'
        if is_mac:
            mac_component(native, upload / 'mac-component.zip')
            standalone = upload / f'SHSMU-Schedule-Assistant-{APP_VERSION}-Mac-arm64.zip'
            mac_component(native, standalone, standalone=True)
            relocated = root / '重新解压 中文 空格'
            subprocess.run(['/usr/bin/ditto', '-x', '-k', str(standalone), str(relocated)], check=True)
            app = relocated / 'Mac/医学院课表助手.app'
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
            moved_report = root / 'relocated-self-test.json'
            moved = subprocess.run([str(app / 'Contents/MacOS/医学院课表助手'),
                                    '--data-root', str(root / 'relocated-data'),
                                    '--self-test', str(moved_report)], env=env, timeout=180)
            checked = json.loads(moved_report.read_text(encoding='utf-8'))
            assert moved.returncode == 0 and checked['status'] == 'PASS', checked
            assert checked['generated_bookmark_sha256'] == report['generated_bookmark_sha256']
            (upload / 'relocated-self-test.json').write_text(
                json.dumps(checked, ensure_ascii=False, indent=2), encoding='utf-8')
        else:
            destination = upload / 'Windows'
            destination.mkdir(exist_ok=True)
            for name in ('医学院课表助手.exe', 'build-manifest.json', 'SHA256SUMS.txt'):
                shutil.copy2(native / name, destination / name)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
