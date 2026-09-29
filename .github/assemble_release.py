"""Assemble allowlisted, matching native builds; do not publish anything."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from diagnostics import APP_VERSION
from package_desktop import combine
from updater import SIGNED_MANIFEST, WINDOWS_EXE, build_manifest, bundled_collector_revision, sign_manifest


def update_notes(limit=600):
    """The first paragraph of RELEASE_NOTES.md as plain text for the update prompt."""
    text = (ROOT / 'RELEASE_NOTES.md').read_text(encoding='utf-8')
    paragraph = text.strip().split('\n\n')[0].replace('**', '').replace('`', '')
    return paragraph if len(paragraph) <= limit else paragraph[:limit - 1] + '…'


def signing_key():
    value = os.environ.get('UPDATE_SIGNING_KEY', '').strip()
    try:
        seed = bytes.fromhex(value)
    except ValueError:
        seed = b''
    if len(seed) != 32:
        raise SystemExit('UPDATE_SIGNING_KEY (64 hex characters) is required to sign the update manifest.')
    return seed


def main():
    seed = signing_key()
    artifacts = ROOT / 'artifacts'
    reports = [json.loads((artifacts / platform / 'self-test.json').read_text(encoding='utf-8'))
               for platform in ('windows', 'macos')]
    for report in reports:
        assert report['status'] == 'PASS' and report['frozen']
        assert report['app_version'] == APP_VERSION and report['collector_revision'] == '2026-09-29.19'
        assert report['bundled_bookmark_verified'] and report['dependency_paths_in_bundle']
    assert reports[0]['generated_bookmark_sha256'] == reports[1]['generated_bookmark_sha256']
    output = ROOT / 'dist/release'
    output.mkdir(parents=True, exist_ok=True)
    prefix = f'SHSMU-Schedule-Assistant-{APP_VERSION}'
    windows = artifacts / 'windows/Windows'
    combine(artifacts / 'macos/mac-component.zip', windows,
            output / f'{prefix}-Windows-x64-Mac-arm64.zip', ROOT / '使用说明.html')
    mac_name = f'{prefix}-Mac-arm64.zip'
    shutil.copy2(artifacts / 'macos' / mac_name, output / mac_name)
    with zipfile.ZipFile(output / f'{prefix}-Windows-x64.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('医学院课表助手.exe', 'build-manifest.json', 'SHA256SUMS.txt'):
            archive.write(windows / name, 'Windows/' + name)
        archive.write(ROOT / '使用说明.html', '使用说明.html')
        archive.writestr('请先阅读.txt',
            '完整解压 ZIP，再打开 Windows 文件夹中的医学院课表助手.exe。无需另装 Python。\n'
            '更新前退出旧助手并保留原课表目录。更新后请在实际采集的浏览器中手动替换旧书签，版本应为 2026-09-29.19。\n')
    shutil.copy2(ROOT / '使用说明.html', output / 'User-Guide.html')
    manifest = json.loads((windows / 'build-manifest.json').read_text(encoding='utf-8'))
    evidence = {'app_version': APP_VERSION, 'collector_revision': '2026-09-29.19',
                'source_fingerprint': manifest['source_fingerprint'],
                'generated_bookmark_sha256': reports[0]['generated_bookmark_sha256'],
                'native_self_tests': {'windows': reports[0], 'macos': reports[1]}}
    (output / 'build-verification.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    # The in-app updater reads this; it names files, never hosts (see updater.py).
    update = build_manifest(APP_VERSION, update_notes(), bundled_collector_revision(ROOT), {
        'windows-x64': {'name': f'{prefix}-Windows-x64.zip', 'path': output / f'{prefix}-Windows-x64.zip',
                        'member': WINDOWS_EXE},
        'macos-arm64': {'name': mac_name, 'path': output / mac_name}})
    update_bytes = json.dumps(update, ensure_ascii=False, indent=2).encode('utf-8')
    (output / 'latest.json').write_bytes(update_bytes)  # Unsigned, read by rc16, which predates signing.
    (output / SIGNED_MANIFEST).write_bytes(sign_manifest(update_bytes, seed))
    for path in output.glob('*.zip'):
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(set(archive.namelist()))
    sums = ''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
                   for path in sorted(output.iterdir()) if path.name != 'SHA256SUMS.txt')
    (output / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8')
    print(sums)


if __name__ == '__main__':
    main()
