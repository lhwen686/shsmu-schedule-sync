"""Package boundaries without building software or touching personal data."""
from pathlib import Path
import hashlib
import json
import stat
import struct
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from build_desktop import artifact_inventory, build_command
from desktop_smoke import dependency_bundle_root
from package_desktop import combine, mac_component


class PackagingTests(unittest.TestCase):
    def mac_fixture(self, folder):
        root = Path(folder)
        app = root / '医学院课表助手.app'
        app.mkdir()
        executable = app / '中文程序'
        executable.write_bytes(b'synthetic executable')
        executable.chmod(0o755)
        return root, app, executable

    def write_mac_manifest(self, root, app):
        files, links = artifact_inventory(app, root)
        manifest = {'platform': 'darwin', 'architecture': 'arm64',
                    'files': files, 'symlinks': links}
        (root / 'build-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (root / 'SHA256SUMS.txt').write_text('synthetic', encoding='utf-8')

    def test_mac_component_marks_chinese_names_utf8_and_preserves_executable_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app, executable = self.mac_fixture(folder)
            self.write_mac_manifest(root, app)
            output = root / 'mac.zip'
            mac_component(root, output)
            with zipfile.ZipFile(output) as archive:
                name = 'Mac/医学院课表助手.app/中文程序'
                info = archive.getinfo(name)
                self.assertTrue(info.flag_bits & 0x800)
                self.assertEqual(info.create_system, 3)
                self.assertEqual(info.external_attr >> 16, executable.stat().st_mode)
                self.assertEqual(archive.read(name), executable.read_bytes())
                self.assertIsNone(archive.testzip())

    def test_mac_component_preserves_symlink_without_copying_target_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app, _ = self.mac_fixture(folder)
            try:
                (app / '链接').symlink_to('中文程序')
            except OSError:
                self.skipTest('当前用户无符号链接权限')
            self.write_mac_manifest(root, app)
            output = root / 'mac.zip'
            mac_component(root, output)
            with zipfile.ZipFile(output) as archive:
                name = 'Mac/医学院课表助手.app/链接'
                self.assertTrue(stat.S_ISLNK(archive.getinfo(name).external_attr >> 16))
                self.assertEqual(archive.read(name).decode('utf-8'), '中文程序')

    def package_fixture(self, folder):
        root = Path(folder)
        windows = root / 'windows'
        windows.mkdir()
        binary = bytearray(134)
        binary[:2] = b'MZ'
        struct.pack_into('<I', binary, 0x3c, 128)
        binary[128:132] = b'PE\0\0'
        struct.pack_into('<H', binary, 132, 0x8664)
        guide = root / 'guide.html'
        guide.write_bytes(b'synthetic guide')
        common = {'format': 'shsmu-build-v1', 'source_fingerprint': 'synthetic-source',
                  'source_files': {'使用说明.html': hashlib.sha256(guide.read_bytes()).hexdigest()},
                  'app_version': 'synthetic'}
        win = {**common, 'platform': 'win32', 'files': {'医学院课表助手.exe': hashlib.sha256(binary).hexdigest()}, 'symlinks': {}}
        (windows / '医学院课表助手.exe').write_bytes(binary)
        (windows / 'build-manifest.json').write_text(json.dumps(win), encoding='utf-8')
        (windows / 'SHA256SUMS.txt').write_text('synthetic', encoding='utf-8')
        app = '医学院课表助手.app'
        resource = app + '/Contents/Resources/example'
        link = app + '/Contents/Frameworks/example'
        mac = {**common, 'platform': 'darwin', 'architecture': 'arm64', 'artifact': app,
               'files': {resource: hashlib.sha256(b'synthetic').hexdigest()},
               'symlinks': {link: '../Resources/example'}}
        component = root / 'mac.zip'
        with zipfile.ZipFile(component, 'w') as z:
            z.writestr('Mac/build-manifest.json', json.dumps(mac))
            z.writestr('Mac/SHA256SUMS.txt', 'synthetic')
            z.writestr('Mac/' + resource, b'synthetic')
            info = zipfile.ZipInfo('Mac/' + link)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, '../Resources/example')
        return component, windows, root / 'combined.zip', guide, link

    def test_combined_zip_preserves_mac_symlink_type_and_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            component, windows, output, guide, link = self.package_fixture(folder)
            combine(component, windows, output, guide)
            with zipfile.ZipFile(output) as z:
                self.assertTrue(stat.S_ISLNK(z.getinfo('Mac/' + link).external_attr >> 16))
                self.assertEqual(z.read('Mac/' + link), b'../Resources/example')
                self.assertIsNone(z.testzip())

    def test_combining_different_source_builds_preserves_existing_package(self):
        with tempfile.TemporaryDirectory() as folder:
            component, windows, output, guide, _ = self.package_fixture(folder)
            path = windows / 'build-manifest.json'
            value = json.loads(path.read_text())
            value['source_fingerprint'] = 'other-source'
            path.write_text(json.dumps(value))
            output.write_bytes(b'previous package')
            with self.assertRaisesRegex(ValueError, '源码或版本不一致'):
                combine(component, windows, output, guide)
            self.assertEqual(output.read_bytes(), b'previous package')

    def test_component_with_extra_private_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            component, windows, output, guide, _ = self.package_fixture(folder)
            with zipfile.ZipFile(component, 'a') as z:
                z.writestr('Mac/config.local.json', 'synthetic private data')
            with self.assertRaisesRegex(ValueError, '清单外'):
                combine(component, windows, output, guide)
            self.assertFalse(output.exists())

    def test_macos_resources_belong_to_same_app_and_external_files_do_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            contents = root / 'Demo.app/Contents'
            with patch('sys.platform', 'darwin'):
                bundle = dependency_bundle_root(contents / 'Frameworks')
            self.assertTrue((contents / 'Resources/tzdata').is_relative_to(bundle))
            self.assertFalse((root / 'external/tzdata').is_relative_to(bundle))
            with patch('sys.platform', 'win32'):
                self.assertEqual(dependency_bundle_root(root / '_MEI123'), root / '_MEI123')

    def test_inventory_covers_both_files_and_symlinks_without_external_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            artifact = root / 'Demo.app'
            artifact.mkdir()
            (artifact / 'resource').write_bytes(b'synthetic')
            files, links = artifact_inventory(artifact, root)
            self.assertEqual(set(files), {'Demo.app/resource'})
            self.assertEqual(links, {})
            # Windows may not permit creating symlinks for an ordinary user.
            try:
                (artifact / 'link').symlink_to('resource')
            except OSError:
                self.skipTest('当前用户无符号链接权限，文件清单检查已完成')
            self.assertEqual(artifact_inventory(artifact, root)[1], {'Demo.app/link': 'resource'})
            (artifact / 'link').unlink()
            (root / 'outside').write_bytes(b'private')
            (artifact / 'link').symlink_to('../outside')
            with self.assertRaisesRegex(RuntimeError, '外部或失效'):
                artifact_inventory(artifact, root)

    def test_build_rejects_unvalidated_architectures(self):
        with patch('sys.platform', 'darwin'), patch('platform.machine', return_value='x86_64'):
            with self.assertRaisesRegex(RuntimeError, 'Intel'):
                build_command(Path('dist'), Path('build'))
        with patch('sys.platform', 'win32'), patch('platform.machine', return_value='AMD64'), \
                patch('struct.calcsize', return_value=4):
            with self.assertRaisesRegex(RuntimeError, 'x64 Python'):
                build_command(Path('dist'), Path('build'))


    @staticmethod
    def native_fixture(minimum=(11, 0, 0), cpu=0x100000c):
        version = minimum[0] << 16 | minimum[1] << 8 | minimum[2]
        header = struct.pack('<8I', 0xfeedfacf, cpu, 0, 2, 1, 24, 0, 0)
        return header + struct.pack('<6I', 0x32, 24, 1, version, 0x1a0000, 0)

    def standalone_fixture(self, folder):
        import plistlib
        from build_desktop import MAC_INFO_PLIST
        from platform_support import MAC_PACKAGE_LABEL
        root, app, _ = self.mac_fixture(folder)
        binary = app / 'Contents/MacOS/医学院课表助手'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(self.native_fixture()); binary.chmod(0o755)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(MAC_INFO_PLIST))
        guide = root / '使用说明.html'; guide.write_bytes(b'synthetic guide')
        self.write_mac_manifest(root, app)
        manifest = json.loads((root / 'build-manifest.json').read_bytes())
        manifest.update(package_revision=MAC_PACKAGE_LABEL,
                        source_files={'使用说明.html': hashlib.sha256(guide.read_bytes()).hexdigest()})
        (root / 'build-manifest.json').write_text(json.dumps(manifest))
        return root, app, binary

    def test_macos_deployment_target_uses_arm64_minimum_not_build_sdk(self):
        from build_desktop import arm64_minimum
        binary = self.native_fixture()
        self.assertEqual(arm64_minimum(binary), (11, 0, 0))
        fat = struct.pack('>2I', 0xcafebabe, 1) + struct.pack('>5I', 0x100000c, 0, 28, len(binary), 0) + binary
        self.assertEqual(arm64_minimum(fat), (11, 0, 0))
        with self.assertRaises(ValueError):
            arm64_minimum(self.native_fixture(cpu=0x1000007))

    def test_macos_bundle_rejects_newer_dependencies_and_wrong_version(self):
        import plistlib
        from build_desktop import validate_macos_bundle
        with tempfile.TemporaryDirectory() as folder:
            root, app, binary = self.standalone_fixture(folder)
            self.assertEqual(set(validate_macos_bundle(app).values()), {'11.0.0'})
            binary.write_bytes(self.native_fixture((12, 0, 0)))
            with self.assertRaisesRegex(ValueError, '高于声明'):
                validate_macos_bundle(app)
            binary.write_bytes(self.native_fixture())
            info = app / 'Contents/Info.plist'
            metadata = plistlib.loads(info.read_bytes()); metadata['CFBundleVersion'] = '0.0.0'
            info.write_bytes(plistlib.dumps(metadata))
            with self.assertRaisesRegex(ValueError, '版本或系统声明'):
                validate_macos_bundle(app)

    def test_standalone_mac_archive_has_guidance_and_verifiable_checksums(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app, _ = self.standalone_fixture(folder)
            output = root / 'mac-only.zip'
            mac_component(root, output, standalone=True)
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('使用说明.html', archive.namelist())
                self.assertIn('仍要打开', archive.read('请先阅读.txt').decode())
                self.assertIn('修订 6', archive.read('请先阅读.txt').decode())
                for line in archive.read('SHA256SUMS.txt').decode().splitlines():
                    digest, name = line.split('  ', 1)
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
                self.assertFalse(any(name.startswith('Windows/') for name in archive.namelist()))
            (root / '使用说明.html').write_bytes(b'changed guide')
            previous = output.read_bytes()
            with self.assertRaisesRegex(ValueError, '使用说明'):
                mac_component(root, output, standalone=True)
            self.assertEqual(output.read_bytes(), previous)

    def test_mac_only_cli_rejects_component_zip_or_windows_input(self):
        import subprocess
        import sys
        for args in (['--mac-only', '--mac-zip', 'missing.zip'],
                     ['--mac-only', '--mac-dir', 'missing', '--windows-dir', 'missing']):
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('package_desktop.py')),
                                     *args, '--output', 'unused.zip'], capture_output=True)
            self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
