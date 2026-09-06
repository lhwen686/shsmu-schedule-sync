@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto check_env
py -3 -c "import sys; sys.exit(sys.version_info < (3,12))" >nul 2>&1
if errorlevel 1 goto try_python
py -3 -m venv .venv
goto created_env
:try_python
python -c "import sys; sys.exit(sys.version_info < (3,12))" >nul 2>&1
if errorlevel 1 (
  echo 未找到可用的 Python 3.12 或更新版本。
  echo 请从 https://www.python.org/downloads/windows/ 安装 Python，勾选启动器或加入 PATH，然后重新运行本文件。
  goto failed
)
python -m venv .venv
:created_env
if errorlevel 1 (
  echo 无法创建项目环境。请先解压 ZIP 到可写的固定目录，再重新运行。
  goto failed
)
:check_env
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3,12))" >nul 2>&1
if errorlevel 1 (
  echo 现有 .venv 不可用或 Python 版本过旧。
  echo 安装 Python 3.12 或更新版本后，将本目录 .venv 手动改名备份，再运行 setup.cmd。
  echo 请保留 data、output、local 和 config.local.json。
  goto failed
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --timeout 30 --retries 2 -r requirements.txt
if errorlevel 1 (
  echo 依赖未安装完成，请检查上面的下载或权限错误后重试 setup.cmd。现有文件已保留。
  goto failed
)
".venv\Scripts\python.exe" -X utf8 sync.py --prepare
if errorlevel 1 (
  echo 书签安装页未生成，请按上面的配置提示修正后重试 setup.cmd。
  goto failed
)
echo 安装完成。请在已有 Chrome 中打开 chrome-bookmark.html 并安装或更新书签。
echo 日常先双击“同步课表.cmd”。若 JSON 已下载，可双击“导入已下载课表.cmd”选择文件。
pause
exit /b 0
:failed
echo 安装尚未完成，请保留上面的错误信息。
pause
exit /b 1
