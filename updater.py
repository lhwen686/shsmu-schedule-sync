"""Check for, download and apply a newer desktop release. Never runs without the user's click.

The manifest (`latest.json`) names no hosts. Where it and the packages are
downloaded from is a list of HTTPS URL templates, tried in order: GitHub by
default, or `SOURCES` from an optional build-time `update_sources.py`.

The client reads `latest-signed.json`: the exact `latest.json` bytes plus an
Ed25519 signature by one of `TRUSTED_KEYS`. Because the manifest carries every
package's SHA-256, a valid signature makes any mirror, proxy or file host
usable without trusting it. Unsigned `latest.json` is still published for rc16.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import update_signing
from diagnostics import APP_VERSION

GITHUB_REPOSITORY = 'lhwen686/shsmu-schedule-sync'
CHANNEL_TAG = 'update-channel'
SIGNED_MANIFEST = 'latest-signed.json'
SIGNED_FORMAT = 'shsmu-update-signed-1'
# Signed bytes are prefixed so this key's signatures mean nothing elsewhere.
SIGNING_CONTEXT = b'SHSMU-Schedule-Assistant update manifest v1\n'
# Release key (GitHub secret UPDATE_SIGNING_KEY) first, then the offline backup
# key. Rotating a key needs a release signed by a key the old version trusts.
TRUSTED_KEYS = (
    'f6d1eea10feb049b1eaa8fc36ddd8bb6dc8fe9957bc4566be5ec7e64e5b5599f',
    '78918de02fcdcd2f6524d4dde86d136ebb5ea9f965aa53388ca19787387b02f3',
)
MANIFEST_LIMIT = 64 * 1024
DOWNLOAD_LIMIT = 300 * 1024 * 1024
TIMEOUT = 20
VERSION = re.compile(r'^(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-rc(\d{1,4}))?$')
FILE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
WINDOWS_EXE = 'Windows/医学院课表助手.exe'

# `{version}` and `{name}` are filled in for package downloads.
DEFAULT_SOURCES = {
    'manifest': (f'https://github.com/{GITHUB_REPOSITORY}/releases/download/{CHANNEL_TAG}/{SIGNED_MANIFEST}',),
    'files': (f'https://github.com/{GITHUB_REPOSITORY}/releases/download/v{{version}}/{{name}}',),
}

try:  # Build-time override, generated from repository variables; absent in source checkouts.
    from update_sources import SOURCES
except ImportError:
    SOURCES = DEFAULT_SOURCES


class UpdateError(Exception):
    """A user-facing reason, in Chinese, why checking or updating stopped."""


class UpdateCancelled(UpdateError):
    pass


def version_key(value):
    match = VERSION.match(str(value))
    if not match:
        raise UpdateError(f'无法识别版本号 {value!r}。')
    major, minor, patch, rc = match.groups()
    # A final release sorts after every release candidate of the same number.
    return int(major), int(minor), int(patch), int(rc) if rc else float('inf')


def is_newer(candidate, current=APP_VERSION):
    return version_key(candidate) > version_key(current)


def platform_key():
    if sys.platform == 'win32':
        return 'windows-x64'
    if sys.platform == 'darwin':
        return 'macos-arm64'
    return None


def validate_sources(sources):
    """Keep only HTTPS templates; a package template must name the file."""
    def clean(values, required=()):
        if isinstance(values, str):
            values = (values,)
        return tuple(value.strip() for value in values or ()
                     if isinstance(value, str) and value.strip().startswith('https://')
                     and all(field in value for field in required))
    sources = sources if isinstance(sources, dict) else {}
    manifest, files = clean(sources.get('manifest')), clean(sources.get('files'), ('{name}',))
    # A broken override must not strand every installed copy: fall back per list.
    return {'manifest': manifest or DEFAULT_SOURCES['manifest'], 'files': files or DEFAULT_SOURCES['files']}


def manifest_urls(sources=None):
    return list(validate_sources(SOURCES if sources is None else sources)['manifest'])


def file_urls(version, name, sources=None):
    templates = validate_sources(SOURCES if sources is None else sources)['files']
    return [template.format(version=version, name=name) for template in templates]


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    collector_revision: str
    name: str
    sha256: str
    size: int
    member: str | None = None
    member_sha256: str | None = None

    @property
    def size_label(self):
        return f'{self.size / 1024 / 1024:.1f} MB'


def parse_manifest(data, platform=None):
    """Validate every field the client relies on; reject rather than guess."""
    try:
        manifest = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise UpdateError('更新信息格式错误。') from error
    if not isinstance(manifest, dict) or manifest.get('schema') != 1:
        raise UpdateError('更新信息版本不受支持，请从发布页手动下载新版。')
    version = manifest.get('version')
    version_key(version)
    notes = manifest.get('notes', '')
    revision = manifest.get('collector_revision', '')
    if not isinstance(notes, str) or not isinstance(revision, str):
        raise UpdateError('更新信息格式错误。')
    entry = (manifest.get('files') or {}).get(platform or platform_key())
    if not isinstance(entry, dict):
        raise UpdateError('新版本暂未提供本系统的安装包。')
    name, digest, size = entry.get('name'), entry.get('sha256'), entry.get('size')
    member, member_digest = entry.get('member'), entry.get('member_sha256')
    if (not isinstance(name, str) or not FILE_NAME.match(name) or not isinstance(digest, str)
            or not SHA256.match(digest) or not isinstance(size, int) or not 0 < size <= DOWNLOAD_LIMIT
            or (member is not None and not isinstance(member, str))
            or (member_digest is not None and (not isinstance(member_digest, str) or not SHA256.match(member_digest)))):
        raise UpdateError('更新信息中的安装包描述无效。')
    return Release(version, notes[:4000], revision[:40], name, digest, size, member, member_digest)


def sign_manifest(manifest_bytes, seed, trusted=TRUSTED_KEYS):
    """Release-side: wrap the exact manifest bytes with a signature the app will accept."""
    signature = update_signing.sign(seed, SIGNING_CONTEXT + manifest_bytes)
    envelope = json.dumps({'format': SIGNED_FORMAT,
                           'manifest': base64.b64encode(manifest_bytes).decode('ascii'),
                           'signature': base64.b64encode(signature).decode('ascii')}, indent=2).encode('utf-8')
    verified_manifest(envelope, trusted)  # A key the app does not trust must fail the release, not the students.
    return envelope


def verified_manifest(data, trusted=TRUSTED_KEYS):
    """Return the inner manifest bytes only if a trusted key signed them."""
    try:
        envelope = json.loads(data.decode('utf-8'))
        if not isinstance(envelope, dict) or envelope.get('format') != SIGNED_FORMAT:
            raise ValueError
        manifest = base64.b64decode(envelope['manifest'], validate=True)
        signature = base64.b64decode(envelope['signature'], validate=True)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as error:
        raise UpdateError('更新信息格式错误或未签名。') from error
    message = SIGNING_CONTEXT + manifest
    if not any(update_signing.verify(bytes.fromhex(key), message, signature) for key in trusted):
        raise UpdateError('更新信息签名无效，可能被篡改。')
    return manifest


MACOS_CA_FILE = '/etc/ssl/cert.pem'
CERTIFICATE_ERROR = ('无法验证更新服务器的安全证书，已停止。请确认电脑的日期和时间正确后再试；'
                     '仍不行时请从发布页手动下载新版。')
_https = None


def https_context():
    """Verified TLS context with the operating system's root certificates.

    The packaged Mac runtime's OpenSSL looks for them only under python.org's
    install prefix, which student Macs do not have, so every HTTPS request
    failed (BUG-010). macOS ships its roots in /etc/ssl/cert.pem; add them.
    Certificate and host-name verification stay on.
    """
    global _https
    if _https is None:
        context = ssl.create_default_context()
        if sys.platform == 'darwin' and os.path.isfile(MACOS_CA_FILE):
            context.load_verify_locations(cafile=MACOS_CA_FILE)
        _https = context
    return _https


def certificate_failure(error):
    reason = getattr(error, 'reason', error)
    return isinstance(reason, ssl.SSLCertVerificationError)


def _open(url, timeout=TIMEOUT):
    request = urllib.request.Request(url, headers={'User-Agent': 'SHSMUScheduleAssistant/' + APP_VERSION})
    response = urllib.request.urlopen(request, timeout=timeout, context=https_context())
    # GitHub redirects to its download CDN; never follow a downgrade to plain HTTP.
    if not response.geturl().startswith('https://'):
        response.close()
        raise UpdateError('下载地址不是 HTTPS，已停止。')
    return response


def fetch_release(sources=None, platform=None, opener=_open, current=APP_VERSION, trusted=TRUSTED_KEYS):
    """Return the newest signed release, trying each manifest source in order.

    Stops at the first release newer than `current`; otherwise asks every source,
    so a stale mirror listed first cannot hide an update published elsewhere.
    """
    rejected, network, best = None, None, None
    for url in manifest_urls(sources):
        try:
            with opener(url) as response:
                data = response.read(MANIFEST_LIMIT + 1)
            if len(data) > MANIFEST_LIMIT:
                raise UpdateError('更新信息过大。')
            release = parse_manifest(verified_manifest(data, trusted), platform)
        except UpdateError as error:
            rejected = str(error)
            # A signed manifest that lacks this platform will not differ on the next host.
            if '本系统' in str(error):
                raise
            continue
        except (OSError, ValueError) as error:
            network = CERTIFICATE_ERROR if certificate_failure(error) else network or type(error).__name__
            continue
        if is_newer(release.version, current):
            return release
        if best is None or is_newer(release.version, best.version):
            best = release
    if best is not None:
        return best
    if rejected:  # A host answered with something unusable; say so rather than blame the network.
        raise UpdateError(rejected + '请稍后再试，或从发布页手动下载新版。')
    if network == CERTIFICATE_ERROR:
        raise UpdateError(CERTIFICATE_ERROR)
    raise UpdateError('暂时无法连接更新服务器，请检查网络后再试。' + (f'（{network}）' if network else ''))


def download(release, folder, *, sources=None, progress=None, cancelled=None, opener=_open):
    """Download to `folder` and verify size and SHA-256 before returning the path."""
    folder = Path(folder)
    target = folder / release.name
    partial = folder / (release.name + '.part')
    last_error = None
    for url in file_urls(release.version, release.name, sources):
        digest, received = hashlib.sha256(), 0
        try:
            with opener(url) as response, open(partial, 'wb') as output:
                while True:
                    if cancelled and cancelled():
                        raise UpdateCancelled('已取消更新。')
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > release.size:
                        raise UpdateError('下载的文件比预期大，已停止。')
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        progress(received, release.size)
            if received != release.size or digest.hexdigest() != release.sha256:
                raise UpdateError('下载的文件校验失败，可能已损坏或被篡改。')
            os.replace(partial, target)
            return target
        except UpdateCancelled:
            partial.unlink(missing_ok=True)
            raise
        except (UpdateError, OSError, ValueError) as error:
            last_error = error
            partial.unlink(missing_ok=True)
    if isinstance(last_error, UpdateError):
        raise last_error
    if certificate_failure(last_error):
        raise UpdateError(CERTIFICATE_ERROR)
    raise UpdateError('下载失败，请检查网络后再试。')


def extract_member(archive_path, release, destination):
    with zipfile.ZipFile(archive_path) as archive:
        try:
            data = archive.read(release.member)
        except KeyError as error:
            raise UpdateError('安装包内容不完整。') from error
    if release.member_sha256 and hashlib.sha256(data).hexdigest() != release.member_sha256:
        raise UpdateError('安装包内的程序校验失败。')
    Path(destination).write_bytes(data)
    return Path(destination)


def current_executable():
    """The installed program file, or None when running from source."""
    return Path(sys.executable).resolve() if getattr(sys, 'frozen', False) else None


def old_copy(executable):
    return executable.with_name(executable.name + '.old')


def replace_running_exe(executable, new_file):
    """Swap the program file in place. Windows lets a running EXE be renamed, not overwritten."""
    executable, new_file = Path(executable), Path(new_file)
    old = old_copy(executable)
    try:
        old.unlink(missing_ok=True)
    except OSError:
        old = executable.with_name(f'{executable.name}.{int(time.time())}.old')
    os.replace(executable, old)
    try:
        os.replace(new_file, executable)
    except OSError:
        os.replace(old, executable)
        raise
    return old


def restore_exe(executable, old):
    Path(executable).unlink(missing_ok=True)
    os.replace(old, executable)


def clean_environment(environ=None):
    """A onefile child would otherwise reuse this process's (soon deleted) unpack directory."""
    environ = dict(os.environ if environ is None else environ)
    for key in list(environ):
        if key.startswith('_PYI_') or key in ('_MEIPASS2', 'TCL_LIBRARY', 'TK_LIBRARY'):
            del environ[key]
    environ['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return environ


def launch(executable, arguments=()):
    flags = 0
    if os.name == 'nt':
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen([str(executable), *map(str, arguments)], cwd=str(Path(executable).parent), close_fds=True,
                            creationflags=flags, env=clean_environment())


def install_windows(release, *, progress=None, cancelled=None, sources=None, opener=_open):
    """Download, verify and swap the EXE. Returns the new EXE path for the caller to start."""
    executable = current_executable()
    if executable is None:
        raise UpdateError('只有打包后的助手可以自动更新；源码运行请用 git 拉取新版本。')
    if not release.member:
        raise UpdateError('更新信息缺少程序文件位置。')
    folder = executable.parent
    try:
        probe = tempfile.NamedTemporaryFile(dir=folder, prefix='.update-', delete=True)
        probe.close()
    except OSError as error:
        raise UpdateError(f'助手所在文件夹不可写入：{folder}\n请把助手移到“文档”等普通文件夹后再更新。') from error
    with tempfile.TemporaryDirectory(prefix='shsmu-update-') as work:
        archive = download(release, work, sources=sources, progress=progress, cancelled=cancelled, opener=opener)
        # Extract beside the EXE so the final rename stays on one volume.
        staged = extract_member(archive, release, folder / (executable.name + '.new'))
    try:
        old = replace_running_exe(executable, staged)
    except OSError as error:
        staged.unlink(missing_ok=True)
        raise UpdateError('无法替换程序文件，请关闭占用它的程序后重试。') from error
    return executable, old


def download_for_manual_install(release, folder, *, progress=None, cancelled=None, sources=None, opener=_open):
    """macOS: an unsigned app cannot safely replace itself; save the verified ZIP for the user."""
    return download(release, folder, sources=sources, progress=progress, cancelled=cancelled, opener=opener)


def cleanup_old_copies(executable=None, attempts=10, delay=0.5):
    """Remove the previous EXE once its process has exited. Safe to call on every start."""
    executable = executable or current_executable()
    if executable is None:
        return
    for _ in range(attempts):
        leftovers = [path for path in executable.parent.glob(executable.name + '*.old')] + \
                    [path for path in executable.parent.glob(executable.name + '.new')]
        for path in list(leftovers):
            try:
                path.unlink()
                leftovers.remove(path)
            except OSError:
                pass
        if not leftovers:
            return
        time.sleep(delay)


def bundled_collector_revision(resources=None):
    resources = Path(resources or Path(__file__).resolve().parent)
    try:
        match = re.search(r"const revision = '([^']+)';", (resources / 'browser_ui.mjs').read_text(encoding='utf-8'))
    except OSError:
        return ''
    return match.group(1) if match else ''


def build_manifest(version, notes, collector_revision, packages):
    """Release-side: `packages` maps platform key to {name, path, member?}."""
    files = {}
    for key, package in packages.items():
        path = Path(package['path'])
        entry = {'name': package['name'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                 'size': path.stat().st_size}
        if package.get('member'):
            with zipfile.ZipFile(path) as archive:
                entry['member'] = package['member']
                entry['member_sha256'] = hashlib.sha256(archive.read(package['member'])).hexdigest()
        files[key] = entry
    manifest = {'schema': 1, 'version': version, 'notes': notes,
                'collector_revision': collector_revision, 'files': files}
    for key in files:  # The client must accept exactly what we publish.
        parse_manifest(json.dumps(manifest).encode('utf-8'), key)
    return manifest
