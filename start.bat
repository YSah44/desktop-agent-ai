@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".env" (
    echo  No .env file found! Run install.bat first.
    pause
    exit /b 1
)

:: pythonw = no extra console on the taskbar (that one always shows the Python icon).
if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" -u main.py %*
) else if exist "venv\Scripts\python.exe" (
    start "" "venv\Scripts\python.exe" -u main.py %*
) else (
    start "" pythonw -u main.py %*
)
