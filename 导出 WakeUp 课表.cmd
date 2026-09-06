@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行 setup.cmd 安装依赖。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 wakeup.py
set "wakeup_exit=%errorlevel%"
pause
exit /b %wakeup_exit%
