@echo off
chcp 65001 >nul
title 视频切割器

cd /d "%~dp0"
echo 正在启动视频切割器...
start "" "pythonw.exe" "%~dp0video_cutter.py"
exit
