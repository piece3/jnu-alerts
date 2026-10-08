@echo off
chcp 65001 >nul
cd /d "%~dp0"
title JNU Alerts - refresh
echo.
echo   Collecting JNU notices... (10-20 sec)
echo.
python scrape.py
start "" "%~dp0dashboard.html"
