"""Run every local synthetic test suite without changing personal outputs."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    node = shutil.which('node')
    if not node:
        print('检查需要 Node.js；请安装后重新打开终端再运行。日常同步不依赖 Node.js。', file=sys.stderr)
        return 1
    commands = [[sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', str(ROOT), '-p', 'test_*.py', '-v']]
    commands.extend([node, str(path)] for path in sorted(ROOT.glob('test_*.mjs')))
    failed = 0
    for command in commands:
        if subprocess.run(command, cwd=ROOT).returncode:
            failed += 1
    if failed:
        print(f'检查失败：{failed} 组未通过，请查看上面的错误。', file=sys.stderr)
        return 1
    print('全部本地模拟测试通过；没有重新采集学校、上传线上日历或验证手机刷新。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
