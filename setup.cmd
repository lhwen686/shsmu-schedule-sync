@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -X utf8 sync.py --prepare
echo 安装完成。双击“同步课表.cmd”即可开始。
pause
