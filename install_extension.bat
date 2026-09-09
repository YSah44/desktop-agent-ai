@echo off
title DAVI - Chrome Extension Installer
color 0B
chcp 65001 >nul
setlocal EnableExtensions

set "ROOT=%~dp0"
set "EXT_DIR=%ROOT%chrome-extension"
if "%EXT_DIR:~-1%"=="\" set "EXT_DIR=%EXT_DIR:~0,-1%"

echo.
echo  ========================================================
echo   DAVI Chrome Extension Installer  v1.3
echo  ========================================================
echo.
echo  Folder:
echo    %EXT_DIR%
echo.

if not exist "%EXT_DIR%\icons\icon128.png" (
    echo  [..] Generating extension icons...
    if exist "%ROOT%venv\Scripts\python.exe" (
        "%ROOT%venv\Scripts\python.exe" "%EXT_DIR%\generate_icons.py"
    ) else (
        python "%EXT_DIR%\generate_icons.py"
    )
    echo  [OK] Icons generated
)

echo  [..] Copying folder path to clipboard...
powershell -NoProfile -Command "Set-Clipboard -LiteralPath '%EXT_DIR%'" 2>nul
if errorlevel 1 (
    echo %EXT_DIR%| clip
)
echo  [OK] Path is on the clipboard — paste it in Load unpacked
echo.

set "CHROME="
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

echo  Opening setup guide, chrome://extensions, and the folder...
if defined CHROME (
    start "" "%CHROME%" "%EXT_DIR%\install.html"
    timeout /t 1 /nobreak >nul
    start "" "%CHROME%" "chrome://extensions/"
) else (
    start "" "%EXT_DIR%\install.html"
    timeout /t 1 /nobreak >nul
    start "" "chrome://extensions/"
)
timeout /t 1 /nobreak >nul
explorer "%EXT_DIR%"

echo.
echo  EN
echo    1. Turn on Developer mode (top-right)
echo    2. Click Load unpacked
echo    3. Paste the folder path (Ctrl+V) and press Enter
echo    4. Start DAVI — toolbar badge should show ON
echo.
echo  TR
echo    1. Gelistirici modunu acin (sag ust)
echo    2. Paketlenmemis oge yukle
echo    3. Klasor yolunu yapistirin (Ctrl+V)
echo    4. DAVI'yi baslatin — ON rozeti gorunmeli
echo.
echo  After updates: chrome://extensions -^> DAVI -^> Reload
echo.
pause
