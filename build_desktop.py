"""Build only explicit public resources; never package a user's data directory."""
from pathlib import Path
import hashlib
import subprocess
import sys
import shutil
from prepare import BROWSER_MODULES

ROOT = Path(__file__).resolve().parent


def main():
    output = ROOT / 'dist'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
               '--name', '医学院课表助手', '--distpath', str(output), '--workpath', str(ROOT / 'build/desktop'),
               '--specpath', str(ROOT / 'build'), '--collect-all', 'tzdata']
    for name in ('config.example.json', *BROWSER_MODULES):
        command += ['--add-data', str(ROOT / name) + ';.']
    command += ['--add-data', str(ROOT / 'assets/bookmark-install.png') + ';assets']
    command.append(str(ROOT / 'desktop.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    binary = output / '医学院课表助手.exe'
    checksum = hashlib.sha256(binary.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{checksum}  {binary.name}\n', encoding='utf-8')
    shutil.copy2(ROOT / '使用说明.html', output / '使用说明.html')
    print(f'已生成 {binary.name}；SHA-256: {checksum}')


if __name__ == '__main__':
    main()
