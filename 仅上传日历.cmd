@echo off
chcp 65001 >nul
call "%~dp0同步课表.cmd" --upload-only
exit /b %errorlevel%
