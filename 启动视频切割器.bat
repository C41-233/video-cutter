@echo off
title 视频切割器
cd /d "%~dp0"
echo 正在启动视频切割器...
where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pythonw.exe "%~dp0video_cutter.py"
    exit
)
where pyw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pyw.exe -3 "%~dp0video_cutter.py"
    exit
)
echo 未找到 Python，请安装 Python 3 并将其加入 PATH
pause
