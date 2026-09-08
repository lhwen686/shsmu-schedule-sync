# Explicit macOS metadata must be included before PyInstaller signs the bundle.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all

sys.path.insert(0, SPECPATH)
from build_desktop import APP_NAME, MAC_INFO_PLIST
from prepare import BROWSER_MODULES

root = Path(SPECPATH)
datas, binaries, hiddenimports = collect_all('tzdata')
datas += [(str(root / name), '.') for name in ('config.example.json', *BROWSER_MODULES)]
datas += [(str(root / 'assets/bookmark-install.png'), 'assets')]
a = Analysis([str(root / 'desktop.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME,
          console=False, target_arch='arm64', argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)
app = BUNDLE(coll, name=APP_NAME + '.app', bundle_identifier='cn.shsmu.scheduleassistant',
             version=MAC_INFO_PLIST['CFBundleShortVersionString'], info_plist=MAC_INFO_PLIST)
