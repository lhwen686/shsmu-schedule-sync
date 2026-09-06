@echo off
chcp 65001 >nul
if "%~1"=="" (
  call "%~dp0同步课表.cmd" --select-capture
) else (
  call "%~dp0同步课表.cmd" %*
)
exit /b %errorlevel%
