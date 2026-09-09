@echo off
title DAVI Extension Setup
color 0B
chcp 65001 >nul
setlocal EnableExtensions

set "ROOT=%~dp0"
set "EXT_DIR=%ROOT%chrome-extension"
if "%EXT_DIR:~-1%"=="\" set "EXT_DIR=%EXT_DIR:~0,-1%"

echo.
echo  ========================================================
echo   DAVI Browser Extension - Quick Setup
echo  ========================================================
echo.
echo  This folder will be copied to the clipboard:
echo    %EXT_DIR%
echo.

if not exist "%EXT_DIR%\icons\icon128.png" (
    if exist "%ROOT%venv\Scripts\python.exe" (
        "%ROOT%venv\Scripts\python.exe" "%EXT_DIR%\generate_icons.py"
    ) else (
        python "%EXT_DIR%\generate_icons.py"
    )
)

powershell -NoProfile -Command "Set-Clipboard -LiteralPath '%EXT_DIR%'" 2>nul
if errorlevel 1 echo %EXT_DIR%| clip
echo  [OK] Path copied. In Chrome: Developer mode -^> Load unpacked -^> Ctrl+V
echo.

set "CHROME="
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if defined CHROME (
    start "" "%CHROME%" "%EXT_DIR%\install.html"
    timeout /t 1 /nobreak >nul
    start "" "%CHROME%" "chrome://extensions/"
) else (
    start "" "%EXT_DIR%\install.html"
    start "" "chrome://extensions/"
)
explorer "%EXT_DIR%"

echo  Overlay Settings -^> Install Chrome Extension also opens this guide.
echo  Reload the extension after file updates.
echo.
pause
