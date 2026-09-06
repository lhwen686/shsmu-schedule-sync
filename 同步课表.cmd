@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行 setup.cmd 安装依赖。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 sync.py %*
set "sync_exit=%errorlevel%"
pause
exit /b %sync_exit%
