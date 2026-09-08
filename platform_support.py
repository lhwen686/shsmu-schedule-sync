"""Small OS boundaries, safe to import before optional GUI dependencies."""
import os
import sys
from pathlib import Path


def default_data_root():
    if sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
    return base / 'SHSMUScheduleAssistant'


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
