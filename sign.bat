@echo off
:: Sign one file with Azure Trusted Signing.   Usage: sign.bat <file>
:: Needs signing.json (copy signing.example.json, fill in your account) and a
:: one-time "az login". Without signing.json the build stays unsigned.
setlocal
cd /d "%~dp0"
:: The signing dlib finds the token through "az"; make sure the real CLI wins in PATH.
set "PATH=%ProgramFiles%\Microsoft SDKs\Azure\CLI2\wbin;%PATH%"
if "%~1"=="" (echo [SIGN] usage: sign.bat ^<file^> & exit /b 1)
if not exist "signing.json" (echo [SIGN] signing.json missing - leaving "%~nx1" unsigned & exit /b 0)

set "SIGNTOOL="
for /d %%d in ("build-tools\sdk\bin\10.*") do if exist "%%~d\x64\signtool.exe" set "SIGNTOOL=%%~d\x64\signtool.exe"
set "DLIB=build-tools\tsc\bin\x64\Azure.CodeSigning.Dlib.dll"
if not defined SIGNTOOL (echo [SIGN] signtool missing under build-tools\sdk & exit /b 1)
if not exist "%DLIB%" (echo [SIGN] Azure.CodeSigning.Dlib.dll missing under build-tools\tsc & exit /b 1)

"%SIGNTOOL%" sign /fd SHA256 /tr http://timestamp.acs.microsoft.com /td SHA256 /dlib "%DLIB%" /dmdf "signing.json" "%~1"
if errorlevel 1 (echo [SIGN] FAILED: %~nx1 & exit /b 1)
"%SIGNTOOL%" verify /pa /q "%~1" >nul 2>&1 && echo [SIGN] OK: %~nx1
exit /b 0
