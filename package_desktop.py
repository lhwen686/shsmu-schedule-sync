"""Combine separately verified native builds without unpacking Mac symlinks on Windows."""
import argparse
import hashlib
import json
import os
import posixpath
import stat
import struct
import zipfile
from pathlib import Path, PurePosixPath
from platform_support import MAC_PACKAGE_LABEL


def mac_readme():
    return ('医学院课表助手 · ' + MAC_PACKAGE_LABEL + '\n\n'
        '本包供 Apple 芯片（M 系列）Mac 使用，内置运行环境，无需安装 Python。\n'
        '1. 用 Finder 完整解压 ZIP，将 Mac 文件夹中的“医学院课表助手.app”拖入“应用程序”，再双击打开。\n'
        '2. 查看“使用说明.html”，使用平时正常登录教务的 Chrome 或 Safari 安装书签；本包不要求重新采集已有完整 JSON。\n'
        '3. 更新时先安全退出旧助手，再替换 APP。课表默认保存在用户的 Library/Application Support/SHSMUScheduleAssistant，'
        '不在 APP 内。曾选择其他目录时继续使用原目录，不删除保存位置或 UID 历史。\n\n'
        '首次打开：本应用尚无 Developer ID 签名和 Apple 公证，可能显示“Apple 无法验证”。'
        '仅在确认来源可信且校验值一致后，由本人在尝试打开后前往“系统设置 → 隐私与安全性 → 仍要打开”，再次确认。'
        '如果提示文件损坏或将损坏电脑，停止打开，保留具体提示并联系维护者；不要移除隔离属性或关闭系统安全检查。\n'
        'Apple 官方说明：https://support.apple.com/zh-cn/102445\n\n'
        '下载权限：拒绝访问下载文件夹时，可在助手点“文件已经下载”手动选择完整 JSON，'
        '或选择另一可读的下载文件夹；无需完整磁盘访问权限。\n'
        '保存位置丢失：连接原磁盘或恢复文件夹权限，再选原课表目录；恢复前不导入、导出或保存设置。\n'
        '导出：两个按钮在 Finder 选中文件。若未能打开 Finder，使用窗口提供的文件路径或重试；无需重新采集。\n'
        '退出：Command+Q、菜单和 Dock 的退出均安全结束；保存开始后会等本次保存与导出完成。\n'
        '排错：进入“遇到问题 → 导出排错日志”。日志仅由本人手动发给维护者，含日期、节次等排错信息。\n\n'
        '版本：1.0.0-rc12 · Mac 修订 6；系统版本字段 1.0.0，构建号 12.0。'
        '原生二进制最低要求为 macOS 11.0；不表示每个后续系统均已实测。\n'
        '本包为候选版。两端生成的课表按钮均为 2026-09-08.12，升级后请手动替换旧书签。'
        'Intel Mac、其他系统实机、手机导入和正式签名公证仍待独立验收。\n')


def mac_component(mac_dir, output, *, standalone=False):
    from build_desktop import artifact_inventory
    manifest = json.loads((mac_dir / 'build-manifest.json').read_text(encoding='utf-8'))
    artifact = mac_dir / '医学院课表助手.app'
    if manifest['platform'] != 'darwin' or manifest['architecture'] != 'arm64':
        raise ValueError('需要 Apple 芯片 Mac 构建目录。')
    files, links = artifact_inventory(artifact, mac_dir)
    if files != manifest['files'] or links != manifest['symlinks']:
        raise ValueError('Mac 程序与构建清单不一致。')
    if standalone:
        from build_desktop import validate_macos_bundle
        validate_macos_bundle(artifact)
        if manifest.get('package_revision') != MAC_PACKAGE_LABEL:
            raise ValueError('Mac 构建修订号不一致。')
        guide = (mac_dir / '使用说明.html').read_bytes()
        if hashlib.sha256(guide).hexdigest() != manifest['source_files']['使用说明.html']:
            raise ValueError('使用说明与构建源码不一致。')
    paths = [artifact, *sorted(artifact.rglob('*')), mac_dir / 'build-manifest.json', mac_dir / 'SHA256SUMS.txt']
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                mode = path.lstat().st_mode
                name = 'Mac/' + path.relative_to(mac_dir).as_posix()
                if stat.S_ISDIR(mode):
                    name += '/'
                    data = b''
                elif stat.S_ISLNK(mode):
                    data = os.readlink(path).encode('utf-8')
                else:
                    data = path.read_bytes()
                # zipfile sets the UTF-8 flag for Chinese names. Native ditto ZIPs
                # can omit it, causing Windows/Python to read those names as CP437.
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
            if standalone:
                archive.writestr('使用说明.html', guide)
                archive.writestr('请先阅读.txt', mac_readme().encode('utf-8'))
                # Hash every ordinary file; symlink targets remain in the build manifest.
                sums = ''.join(hashlib.sha256(archive.read(info)).hexdigest() + '  ' + info.filename + '\n'
                    for info in archive.infolist()
                    if not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16))
                archive.writestr('SHA256SUMS.txt', sums.encode('utf-8'))
        with zipfile.ZipFile(temporary) as check:
            if check.testzip() is not None:
                raise ValueError('Mac ZIP 校验失败。')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def combine(mac_zip, windows_dir, output, guide):
    windows = json.loads((windows_dir / 'build-manifest.json').read_text(encoding='utf-8'))
    executable = windows_dir / '医学院课表助手.exe'
    binary = executable.read_bytes()
    if binary[:2] != b'MZ':
        raise ValueError('Windows 程序不是 PE 可执行文件。')
    pe = struct.unpack_from('<I', binary, 0x3c)[0]
    if binary[pe:pe + 4] != b'PE\0\0' or struct.unpack_from('<H', binary, pe + 4)[0] != 0x8664:
        raise ValueError('需要 Windows x64 程序。')
    digest = hashlib.sha256(binary).hexdigest()
    if windows['platform'] != 'win32' or windows['files'] != {executable.name: digest} or windows['symlinks']:
        raise ValueError('Windows 程序与构建清单不一致。')
    with zipfile.ZipFile(mac_zip) as source:
        mac = json.loads(source.read('Mac/build-manifest.json'))
        if (mac['format'] != 'shsmu-build-v1' or mac['platform'] != 'darwin'
                or mac['architecture'] != 'arm64' or mac['artifact'] != '医学院课表助手.app'):
            raise ValueError('需要 Apple 芯片 Mac 组件。')
        for name in (*mac['files'], *mac['symlinks']):
            if (not name.startswith(mac['artifact'] + '/') or '..' in PurePosixPath(name).parts
                    or '\\' in name):
                raise ValueError('Mac 清单含有应用目录之外的路径。')
        for field in ('format', 'source_fingerprint', 'source_files', 'app_version'):
            if mac[field] != windows[field]:
                raise ValueError('两个程序的源码或版本不一致，请用同一份构建材料重建。')
        allowed = {'Mac/build-manifest.json', 'Mac/SHA256SUMS.txt'}
        allowed.update('Mac/' + name for name in (*mac['files'], *mac['symlinks']))
        entries = source.infolist()
        if len({info.filename for info in entries}) != len(entries):
            raise ValueError('Mac 组件包含重复条目。')
        for info in entries:
            name = info.filename
            if info.is_dir():
                if not any(path.startswith(name) for path in allowed):
                    raise ValueError('Mac 组件包含多余目录。')
                continue
            if name not in allowed:
                raise ValueError('Mac 组件包含清单外文件。')
            data = source.read(info)
            relative = name.removeprefix('Mac/')
            if relative in mac['symlinks']:
                target = data.decode('utf-8')
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                if (not stat.S_ISLNK(info.external_attr >> 16) or target != mac['symlinks'][relative]
                        or not resolved.startswith('Mac/' + mac['artifact'] + '/')):
                    raise ValueError('Mac 组件链接类型或目标无效。')
            elif relative in mac['files']:
                if stat.S_ISLNK(info.external_attr >> 16) or hashlib.sha256(data).hexdigest() != mac['files'][relative]:
                    raise ValueError('Mac 组件文件与清单不一致。')
        if {info.filename for info in entries if not info.is_dir()} != allowed:
            raise ValueError('Mac 组件文件不完整。')
        if hashlib.sha256(guide.read_bytes()).hexdigest() != mac['source_files']['使用说明.html']:
            raise ValueError('使用说明与构建源码不一致。')
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.tmp')
        try:
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
                for info in entries:
                    # Keep Unix type/mode and symlink bytes, even when running on Windows.
                    target.writestr(info, source.read(info))
                for name in ('医学院课表助手.exe', 'build-manifest.json', 'SHA256SUMS.txt'):
                    target.write(windows_dir / name, 'Windows/' + name)
                target.write(guide, '使用说明.html')
                target.writestr('请先阅读.txt',
                    '先解压整个 ZIP。Windows x64 打开 Windows 文件夹中的 EXE；Apple 芯片 Mac 打开 Mac 文件夹中的 APP。\n'
                    '两个程序均内置运行环境，无需另装 Python。请阅读使用说明。\n\n'
                    'Mac 首次打开：当前应用没有 Developer ID 签名和 Apple 公证，系统可能显示“Apple 无法验证”。'
                    '在确认本包来自项目维护者并核对校验值后，可由使用者本人打开“系统设置 → 隐私与安全性”，'
                    '为“医学院课表助手”选择“仍要打开”，并再次确认“打开”。这会为该应用建立安全例外，'
                    '不会改变它尚未公证的状态；以后通常可以直接双击。Apple 官方说明：https://support.apple.com/zh-cn/102445\n\n'
                    '本包为 1.0.0-rc12 双平台候选版，两端生成的课表按钮均为 2026-09-08.12。'
                    '升级软件后仍须在实际使用的浏览器中手动替换一次旧书签。\n'
                    '更新前先退出旧助手，保留原课表保存目录、UID 和历史；不要把旧版 Windows 程序与新版 Mac 程序混合合包。\n'
                    '自动检查不等于个人电脑、学校或手机已验收；Mac 限 Apple 芯片，其他系统版本和 Intel Mac 仍需独立验收。\n')
            with zipfile.ZipFile(temporary) as check:
                if check.testzip() is not None:
                    raise ValueError('合并 ZIP 校验失败。')
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--mac-zip', type=Path)
    choice.add_argument('--mac-dir', type=Path)
    parser.add_argument('--windows-dir', type=Path)
    parser.add_argument('--mac-only', action='store_true', help='与 --mac-dir 配合，生成含使用说明的独立 Mac 验收包')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mac_only and not args.mac_dir:
        parser.error('--mac-only 必须与 --mac-dir 配合')
    if args.mac_dir:
        if args.windows_dir:
            parser.error('--mac-dir 只创建 Mac 组件')
        mac_component(args.mac_dir, args.output, standalone=args.mac_only)
        checksum = hashlib.sha256(args.output.read_bytes()).hexdigest()
    else:
        if not args.windows_dir:
            parser.error('合包需要 --windows-dir')
        checksum = combine(args.mac_zip, args.windows_dir, args.output, Path(__file__).with_name('使用说明.html'))
    print(f'已生成 {args.output.name}\nSHA-256: {checksum}')


if __name__ == '__main__':
    main()
