@echo off
chcp 65001 >nul
title Aemyos — Windows setup
color 0B
cd /d "%~dp0"

echo.
echo  ============================================
echo       Aemyos  ·  Windows desktop agent
echo  ============================================
echo.

where py >nul 2>&1
if errorlevel 1 (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Python 3.10+ is required.
        echo          Install from https://www.python.org/downloads/
        echo          Tick "Add python.exe to PATH" during setup.
        pause
        exit /b 1
    )
    set "PY=python"
) else (
    py -3.10 --version >nul 2>&1
    if errorlevel 1 (
        py -3 --version >nul 2>&1
        if errorlevel 1 (
            echo  [ERROR] Python 3.10+ is required.
            pause
            exit /b 1
        )
        set "PY=py -3"
    ) else (
        set "PY=py -3.10"
    )
)

echo  [OK] Python found
%PY% --version

if not exist "venv" (
    echo  [..] Creating virtual environment...
    %PY% -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Could not create venv.
        pause
        exit /b 1
    )
    echo  [OK] Virtual environment created
) else (
    echo  [OK] Virtual environment exists
)

echo  [..] Installing dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip -q
venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 (
    echo  [ERROR] pip install failed.
    pause
    exit /b 1
)
echo  [OK] Dependencies installed

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo.
    echo  ============================================
    echo   Add your own API keys in .env
    echo  ============================================
    echo.
    echo   Anthropic   https://console.anthropic.com/
    echo   Groq        https://console.groq.com/
    echo.
    echo   Optional: DAVI_PROVIDER=openrouter and OPENROUTER_API_KEY
    echo.
    echo  [OK] Created .env from .env.example
    echo       Paste keys there. Never commit that file.
    notepad ".env"
) else (
    echo  [OK] .env already exists ^(not overwritten^)
)

if not exist "memory.json" (
    copy /Y memory.template.json memory.json >nul
    echo  [OK] memory.json created
)

if not exist "screenshots" mkdir screenshots

if not exist "assets\face_idle.png" (
    if exist "generate_face.py" (
        echo  [..] Generating face avatar...
        venv\Scripts\python.exe generate_face.py
    )
)

if not exist "chrome-extension\icons\icon128.png" (
    if exist "chrome-extension\generate_icons.py" (
        echo  [..] Generating extension icons...
        venv\Scripts\python.exe chrome-extension\generate_icons.py
    )
)

echo.
echo  ============================================
echo   Setup complete
echo  ============================================
echo.
echo   Start:     start.bat
echo   Chrome:    setup_extension.bat
echo   Site:      https://aemyos.ai
echo.
echo   Speak a command. Say "stop" to quit.
echo   Ctrl+Shift+Q also quits.
echo.
pause
