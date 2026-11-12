@echo off
rem Double-click to start Eve. Opens her page in your browser; close this window to stop her.
cd /d "%~dp0"
title Eve
start "" cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:8899"
".venv\Scripts\python.exe" eve_ui.py %*
pause
