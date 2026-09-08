"""Small OS boundaries, safe to import before optional GUI dependencies."""
import os
import sys
import json
import stat
from pathlib import Path

MAC_PACKAGE_LABEL = 'Mac 修订 6'


def default_data_root():
    if sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
    return base / 'SHSMUScheduleAssistant'


def select_data_root(base, explicit=None):
    """Resolve startup preferences without creating or replacing any directory.

    Explicit maintenance/test roots may be new. A saved root must still exist;
    damaged or inaccessible preferences require the user's directory selection.
    """
    base = Path(base)
    if explicit is not None:
        return Path(explicit).absolute(), None
    try:
        preferences = json.loads((base / 'preferences.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return base, None
    except (OSError, ValueError):
        return base, '无法读取上次的保存位置。请重新选择原课表目录；原偏好文件和课表已保留。'
    if not isinstance(preferences, dict):
        return base, '保存位置记录格式异常。请重新选择原课表目录；原偏好文件和课表已保留。'
    candidate = preferences.get('data_root')
    if not isinstance(candidate, str) or not candidate.strip() or not Path(candidate).is_absolute():
        return base, '保存位置记录无效。请重新选择原课表目录；没有新建另一份课表。'
    selected = Path(candidate)
    try:
        if not stat.S_ISDIR(selected.stat().st_mode):
            raise NotADirectoryError(candidate)
        # stat alone does not prove a folder can be read (including macOS TCC).
        with os.scandir(selected) as entries:
            next(entries, None)
        return selected.resolve(), None
    except (OSError, ValueError, RuntimeError):
        return selected, '上次使用的数据目录不可用。请连接原磁盘或恢复文件夹权限，再选择原目录；没有新建另一份课表。'


def reveal_command(path):
    if sys.platform == 'darwin':
        return ['/usr/bin/open', '-R', str(path)]
    return ['explorer.exe', '/select,', str(path)]


def ui_font_family(available, fallback):
    candidates = ('PingFang SC', 'Heiti SC') if sys.platform == 'darwin' else ('Microsoft YaHei UI',)
    return next((name for name in candidates if name in available), fallback)


def scroll_units(delta):
    if sys.platform == 'darwin':
        # Aqua supplies small deltas; Windows-style division would drop them.
        return (-1 if delta > 0 else 1) * max(1, int(abs(delta))) if delta else 0
    return -int(delta / 120)


def bookmark_shortcut():
    return 'Command + Shift + B' if sys.platform == 'darwin' else 'Ctrl + Shift + B'


def copy_shortcut():
    return 'Command+C' if sys.platform == 'darwin' else 'Ctrl+C'
