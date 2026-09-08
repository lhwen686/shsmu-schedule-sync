"""Build only explicit public resources; never package a user's data directory."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import struct
import subprocess
import sys
import shutil
from prepare import BROWSER_MODULES
from diagnostics import APP_VERSION
from platform_support import MAC_PACKAGE_LABEL

ROOT = Path(__file__).resolve().parent
APP_NAME = '医学院课表助手'
MAC_MINIMUM = (11, 0, 0)
MAC_INFO_PLIST = {'CFBundleShortVersionString': APP_VERSION.split('-')[0],
                  'CFBundleVersion': '12.0', 'LSMinimumSystemVersion': '11.0',
                  'NSAboutPanelOptionVersion': APP_VERSION + ' · ' + MAC_PACKAGE_LABEL}
BUILD_INPUTS = ('build_desktop.py', 'desktop.py', 'desktop_service.py', 'desktop_smoke.py',
                'desktop-macos.spec', 'package_desktop.py',
                'platform_support.py', 'diagnostics.py', 'prepare.py', 'sync.py', 'source.py',
                'core.py', 'wakeup.py', 'webcal.py', 'requirements.txt', 'requirements-build.txt',
                'config.example.json', *BROWSER_MODULES, 'assets/bookmark-install.png', '使用说明.html')


def source_fingerprint():
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in BUILD_INPUTS}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return hashes, fingerprint


def build_command(output, work):
    if sys.platform not in ('win32', 'darwin'):
        raise RuntimeError('请分别在 Windows x64 和 Apple 芯片 Mac 上构建。')
    if sys.platform == 'darwin' and platform.machine() != 'arm64':
        raise RuntimeError('本次 Mac 构建仅针对 Apple 芯片；Intel 需单独验收。')
    if sys.platform == 'win32' and (platform.machine().lower() not in ('amd64', 'x86_64')
                                   or struct.calcsize('P') != 8):
        raise RuntimeError('Windows 构建需要 x64 Python。')
    if sys.platform == 'darwin':
        return [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', str(output),
                '--workpath', str(work / 'desktop'), str(ROOT / 'desktop-macos.spec')]
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onefile',
               '--name', APP_NAME, '--distpath', str(output), '--workpath', str(work / 'desktop'),
               '--specpath', str(work), '--collect-all', 'tzdata']
    for name in ('config.example.json', *BROWSER_MODULES):
        command += ['--add-data', str(ROOT / name) + os.pathsep + '.']
    command += ['--add-data', str(ROOT / 'assets/bookmark-install.png') + os.pathsep + 'assets']
    command.append(str(ROOT / 'desktop.py'))
    return command


def arm64_minimum(data):
    """Read the deployment target, not the SDK version, of an arm64 Mach-O."""
    def thin(offset):
        if data[offset:offset + 4] != b'\xcf\xfa\xed\xfe':
            return []
        if struct.unpack_from('<I', data, offset + 4)[0] != 0x100000c:
            return []
        count = struct.unpack_from('<I', data, offset + 16)[0]
        end = offset + 32 + struct.unpack_from('<I', data, offset + 20)[0]
        pos, versions = offset + 32, []
        for _ in range(count):
            command, size = struct.unpack_from('<II', data, pos)
            if size < 8 or pos + size > min(len(data), end):
                raise ValueError('Mach-O 加载命令不完整。')
            if command in (0x32, 0x24):
                if size < 16:
                    raise ValueError('Mach-O 系统版本命令不完整。')
                if command == 0x32 and struct.unpack_from('<I', data, pos + 8)[0] != 1:
                    raise ValueError('程序包含非 macOS 的原生二进制。')
                number = struct.unpack_from('<I', data, pos + (12 if command == 0x32 else 8))[0]
                versions.append((number >> 16, (number >> 8) & 255, number & 255))
            pos += size
        return versions
    versions = thin(0)
    if data[:4] in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
        fat64 = data[:4] == b'\xca\xfe\xba\xbf'
        for i in range(struct.unpack_from('>I', data, 4)[0]):
            offset = struct.unpack_from('>Q' if fat64 else '>I', data, 8 + i * (32 if fat64 else 20) + 8)[0]
            versions.extend(thin(offset))
    if not versions:
        raise ValueError('原生二进制缺少 arm64 或 macOS 最低版本声明。')
    return max(versions)


def validate_macos_bundle(artifact):
    import plistlib
    info = plistlib.loads((artifact / 'Contents/Info.plist').read_bytes())
    if any(info.get(key) != value for key, value in MAC_INFO_PLIST.items()):
        raise ValueError('Mac 版本或系统声明与本次候选不一致。')
    versions = {}
    for path in artifact.rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as stream:
            magic = stream.read(4)
            native = path.suffix in ('.dylib', '.so') or path.parent == artifact / 'Contents/MacOS'
            if not native and magic not in (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
                continue
            stream.seek(0)
            minimum = arm64_minimum(stream.read())
        if minimum > MAC_MINIMUM:
            raise ValueError('原生二进制要求的系统高于声明：' + path.name)
        versions[path.relative_to(artifact).as_posix()] = '.'.join(map(str, minimum))
    if not versions:
        raise ValueError('Mac 应用缺少原生程序。')
    return versions


def artifact_inventory(artifact, output):
    paths = sorted(artifact.rglob('*')) if artifact.is_dir() else [artifact]
    files, links = {}, {}
    for path in paths:
        name = path.relative_to(output).as_posix()
        if path.is_symlink():
            target = os.readlink(path)
            if not path.resolve().is_relative_to(artifact.resolve()) or not path.exists():
                raise RuntimeError(f'应用包含外部或失效链接：{name}')
            links[name] = target
        elif path.is_file():
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files, links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--work-dir', type=Path, default=ROOT / 'build')
    args = parser.parse_args()
    output, work = args.output_dir.resolve(), args.work_dir.resolve()
    source_hashes, fingerprint = source_fingerprint()
    subprocess.run(build_command(output, work), cwd=ROOT, check=True)
    if source_fingerprint()[1] != fingerprint:
        raise RuntimeError('构建过程中源码发生变化，请重新构建。')
    artifact = output / (APP_NAME + ('.app' if sys.platform == 'darwin' else '.exe'))
    if not artifact.exists():
        raise RuntimeError('未找到本平台的完整构建产物。')
    if sys.platform == 'darwin':
        minimum_versions = validate_macos_bundle(artifact)
        # Finder may attach bundle metadata in the build directory. It is not
        # application content and causes Apple's strict signature check to fail.
        attrs = subprocess.run(['/usr/bin/xattr', str(artifact)], check=True,
                               capture_output=True, text=True).stdout.splitlines()
        for name in ('com.apple.FinderInfo', 'com.apple.ResourceFork'):
            if name in attrs:
                subprocess.run(['/usr/bin/xattr', '-d', name, str(artifact)], check=True)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(artifact)], check=True)
    files, links = artifact_inventory(artifact, output)
    (output / 'SHA256SUMS.txt').write_text(''.join(f'{value}  {name}\n' for name, value in files.items()), encoding='utf-8')
    manifest = {'format': 'shsmu-build-v1', 'app_version': APP_VERSION,
                'platform': sys.platform, 'architecture': platform.machine(),
                'python_version': platform.python_version(), 'source_fingerprint': fingerprint,
                'source_files': source_hashes, 'artifact': artifact.name, 'files': files, 'symlinks': links}
    if sys.platform == 'darwin':
        manifest.update(package_revision=MAC_PACKAGE_LABEL, minimum_macos='11.0',
                        binary_minimum_versions=minimum_versions, bundle_version=MAC_INFO_PLIST['CFBundleVersion'])
    (output / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copy2(ROOT / '使用说明.html', output / '使用说明.html')
    print(f'已生成 {artifact.name}；来源与文件校验见 build-manifest.json 和 SHA256SUMS.txt。')


if __name__ == '__main__':
    main()
