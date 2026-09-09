@echo off
chcp 65001 >nul
title Aemyos — build Windows exe + installer
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo  [ERROR] venv missing. Run install.bat first.
    pause
    exit /b 1
)

echo  [..] PyInstaller
venv\Scripts\python.exe -m pip install -q pyinstaller
if exist "dist\Aemyos" rmdir /s /q "dist\Aemyos"
venv\Scripts\python.exe -m PyInstaller aemyos.spec --noconfirm --clean
if errorlevel 1 (
    echo  [ERROR] PyInstaller failed.
    pause
    exit /b 1
)
echo  [OK] dist\Aemyos\Aemyos.exe
call sign.bat "dist\Aemyos\Aemyos.exe"
if errorlevel 1 (pause & exit /b 1)

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo  [WARN] Inno Setup not found - portable build only: dist\Aemyos\
    echo         winget install --id JRSoftware.InnoSetup -e
    pause
    exit /b 0
)

echo  [..] Inno Setup
"%ISCC%" /Q "/Saemyos=$q%CD%\sign.bat$q $f" installer.iss
if errorlevel 1 (
    echo  [ERROR] Inno Setup failed.
    pause
    exit /b 1
)
call sign.bat "dist\Aemyos-Setup-1.8.exe"
if errorlevel 1 (pause & exit /b 1)
echo  [OK] dist\Aemyos-Setup-1.8.exe
pause
