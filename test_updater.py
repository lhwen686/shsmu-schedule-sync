import dataclasses
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import updater


class FakeResponse(io.BytesIO):
    def __init__(self, data, url='https://example.test/file'):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


def opener_for(routes):
    calls = []

    def opener(url, timeout=None):
        calls.append(url)
        value = routes.get(url)
        if value is None or isinstance(value, Exception):
            raise value or OSError('unreachable')
        return FakeResponse(*value) if isinstance(value, tuple) else FakeResponse(value)
    opener.calls = calls
    return opener


def zip_with_exe(path, exe=b'MZ new program'):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(updater.WINDOWS_EXE, exe)
        archive.writestr('使用说明.html', '<p>guide</p>')
    return path


class VersionTest(unittest.TestCase):
    def test_release_candidates_sort_before_final(self):
        order = ['1.0.0-rc9', '1.0.0-rc15', '1.0.0-rc16', '1.0.0', '1.0.1-rc1', '1.1.0']
        self.assertEqual(sorted(order, key=updater.version_key), order)
        self.assertTrue(updater.is_newer('1.0.0-rc16', '1.0.0-rc15'))
        self.assertFalse(updater.is_newer('1.0.0-rc15', '1.0.0-rc15'))
        self.assertFalse(updater.is_newer('1.0.0-rc14', '1.0.0-rc15'))

    def test_rejects_unknown_version_text(self):
        for value in ('v1.0.0', '1.0', '1.0.0-beta1', None, '1.0.0-rc15; rm'):
            with self.assertRaises(updater.UpdateError):
                updater.version_key(value)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        zip_with_exe(self.folder / 'SHSMU-Schedule-Assistant-1.0.0-rc16-Windows-x64.zip')
        (self.folder / 'mac.zip').write_bytes(b'mac archive')
        self.manifest = updater.build_manifest('1.0.0-rc16', '修复问题', '2026-10-01.1', {
            'windows-x64': {'name': 'SHSMU-Schedule-Assistant-1.0.0-rc16-Windows-x64.zip',
                            'path': self.folder / 'SHSMU-Schedule-Assistant-1.0.0-rc16-Windows-x64.zip',
                            'member': updater.WINDOWS_EXE},
            'macos-arm64': {'name': 'SHSMU-Schedule-Assistant-1.0.0-rc16-Mac-arm64.zip',
                            'path': self.folder / 'mac.zip'}})
        self.data = json.dumps(self.manifest).encode()

    def test_manifest_names_no_hosts_and_round_trips(self):
        self.assertNotIn('http', self.data.decode())
        release = updater.parse_manifest(self.data, 'windows-x64')
        self.assertEqual(release.version, '1.0.0-rc16')
        self.assertEqual(release.member_sha256, hashlib.sha256(b'MZ new program').hexdigest())
        self.assertIsNone(updater.parse_manifest(self.data, 'macos-arm64').member)

    def test_rejects_unsafe_or_missing_entries(self):
        with self.assertRaisesRegex(updater.UpdateError, '本系统'):
            updater.parse_manifest(self.data, 'linux-x64')
        for field, value in (('name', '../evil.exe'), ('sha256', 'abc'), ('size', 0), ('size', 10**12)):
            manifest = json.loads(self.data)
            manifest['files']['windows-x64'][field] = value
            with self.assertRaises(updater.UpdateError, msg=field):
                updater.parse_manifest(json.dumps(manifest).encode(), 'windows-x64')
        for data in (b'not json', json.dumps({'schema': 2}).encode()):
            with self.assertRaises(updater.UpdateError):
                updater.parse_manifest(data, 'windows-x64')

    def test_defaults_point_at_github_releases(self):
        self.assertEqual(updater.manifest_urls(updater.DEFAULT_SOURCES), [
            'https://github.com/lhwen686/shsmu-schedule-sync/releases/download/update-channel/latest.json'])
        self.assertEqual(updater.file_urls('1.0.0-rc16', 'a.zip', updater.DEFAULT_SOURCES), [
            'https://github.com/lhwen686/shsmu-schedule-sync/releases/download/v1.0.0-rc16/a.zip'])

    def test_configured_sources_are_tried_in_order(self):
        sources = {'manifest': ['https://one.test/latest.json', 'http://insecure.test/latest.json',
                                'https://two.test/latest.json'],
                   'files': 'https://one.test/{version}/{name}'}
        urls = updater.manifest_urls(sources)
        self.assertEqual(urls, ['https://one.test/latest.json', 'https://two.test/latest.json'],
                         'plain HTTP is dropped')
        self.assertEqual(updater.file_urls('1.0.0-rc16', 'a.zip', sources), ['https://one.test/1.0.0-rc16/a.zip'])
        opener = opener_for({urls[-1]: self.data})
        release = updater.fetch_release(sources, 'windows-x64', opener)
        self.assertEqual(release.version, '1.0.0-rc16')
        self.assertEqual(opener.calls, urls)

    def test_unusable_configuration_falls_back_to_github(self):
        for sources in ({}, None, {'manifest': ['http://x.test/latest.json'],
                                           'files': ['https://x.test/no-file-name']}, 'garbage'):
            self.assertEqual(updater.validate_sources(sources), updater.DEFAULT_SOURCES)

    def test_unreachable_everywhere_is_a_readable_error(self):
        with self.assertRaisesRegex(updater.UpdateError, '无法连接'):
            updater.fetch_release([], 'windows-x64', opener_for({}))

    def test_https_downgrade_is_refused(self):
        response = FakeResponse(b'{}', url='http://downgraded.test/latest.json')
        original = updater.urllib.request.urlopen
        updater.urllib.request.urlopen = lambda request, timeout=None: response
        try:
            with self.assertRaisesRegex(updater.UpdateError, 'HTTPS'):
                updater._open('https://mirror.test/latest.json')
        finally:
            updater.urllib.request.urlopen = original


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.payload = b'x' * 700_000
        self.release = updater.Release('1.0.0-rc16', '', '', 'pkg.zip',
                                       hashlib.sha256(self.payload).hexdigest(), len(self.payload))
        self.sources = {'files': ['https://mirror.test/u/{version}/{name}', updater.DEFAULT_SOURCES['files'][0]]}
        self.urls = updater.file_urls('1.0.0-rc16', 'pkg.zip', self.sources)

    def test_falls_back_when_first_source_serves_wrong_bytes(self):
        opener = opener_for({self.urls[0]: b'tampered', self.urls[1]: self.payload})
        seen = []
        path = updater.download(self.release, self.folder, sources=self.sources,
                                progress=lambda done, total: seen.append(done), opener=opener)
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(seen[-1], len(self.payload))
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['pkg.zip'])

    def test_rejects_when_no_source_matches(self):
        opener = opener_for({self.urls[0]: b'bad', self.urls[1]: self.payload + b'extra'})
        with self.assertRaisesRegex(updater.UpdateError, '比预期大|校验'):
            updater.download(self.release, self.folder, sources=self.sources, opener=opener)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_cancel_leaves_nothing(self):
        opener = opener_for({self.urls[1]: self.payload})
        with self.assertRaises(updater.UpdateCancelled):
            updater.download(self.release, self.folder, sources=updater.DEFAULT_SOURCES, cancelled=lambda: True, opener=opener)
        self.assertEqual(list(self.folder.iterdir()), [])


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.exe = self.folder / '医学院课表助手.exe'
        self.exe.write_bytes(b'MZ old program')

    def test_swap_keeps_old_copy_until_cleanup_and_can_restore(self):
        new = self.folder / 'staged'
        new.write_bytes(b'MZ new')
        old = updater.replace_running_exe(self.exe, new)
        self.assertEqual(self.exe.read_bytes(), b'MZ new')
        self.assertEqual(old.read_bytes(), b'MZ old program')
        updater.restore_exe(self.exe, old)
        self.assertEqual(self.exe.read_bytes(), b'MZ old program')
        new.write_bytes(b'MZ new')
        updater.replace_running_exe(self.exe, new)
        updater.cleanup_old_copies(self.exe, attempts=1)
        self.assertEqual([p.name for p in self.folder.iterdir()], [self.exe.name])

    def test_install_windows_end_to_end_with_member_check(self):
        archive = zip_with_exe(Path(tempfile.mkdtemp()) / 'pkg.zip')
        data = archive.read_bytes()
        release = updater.Release('1.0.0-rc16', '', '', 'pkg.zip', hashlib.sha256(data).hexdigest(), len(data),
                                  updater.WINDOWS_EXE, hashlib.sha256(b'MZ new program').hexdigest())
        opener = opener_for({updater.file_urls('1.0.0-rc16', 'pkg.zip', updater.DEFAULT_SOURCES)[-1]: data})
        original = updater.current_executable
        updater.current_executable = lambda: self.exe
        try:
            executable, old = updater.install_windows(release, sources=updater.DEFAULT_SOURCES, opener=opener)
            self.assertEqual(executable.read_bytes(), b'MZ new program')
            self.assertEqual(old.read_bytes(), b'MZ old program')
            updater.restore_exe(executable, old)
            wrong = dataclasses.replace(release, member_sha256='0' * 64)
            with self.assertRaisesRegex(updater.UpdateError, '校验'):
                updater.install_windows(wrong, sources=updater.DEFAULT_SOURCES, opener=opener)
            self.assertEqual(self.exe.read_bytes(), b'MZ old program')
            self.assertEqual([p.name for p in self.folder.iterdir()], [self.exe.name])
        finally:
            updater.current_executable = original

    def test_source_checkout_cannot_self_update(self):
        release = updater.Release('1.0.0-rc16', '', '', 'pkg.zip', '0' * 64, 1, updater.WINDOWS_EXE)
        with self.assertRaisesRegex(updater.UpdateError, '打包后'):
            updater.install_windows(release, opener=opener_for({}))

    def test_child_environment_drops_pyinstaller_state(self):
        env = updater.clean_environment({'_PYI_APPLICATION_HOME_DIR': 'x', '_MEIPASS2': 'y',
                                          'TCL_LIBRARY': 'z', 'PATH': 'p'})
        self.assertEqual(env, {'PATH': 'p', 'PYINSTALLER_RESET_ENVIRONMENT': '1'})

    def test_bundled_revision_matches_bookmark_module(self):
        self.assertRegex(updater.bundled_collector_revision(), r'^\d{4}-\d{2}-\d{2}\.\d+$')


if __name__ == '__main__':
    unittest.main()
