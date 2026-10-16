@echo off
rem Portable pack launcher (ASCII only on purpose).
chcp 65001 >nul
title Qixi Guide
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0runtime\packages"
set "PYW=%~dp0runtime\python\pythonw.exe"
set "PY=%~dp0runtime\python\python.exe"

if not exist "%PY%" (
  echo [ERROR] runtime\python not found - please re-extract the whole folder.
  pause
  exit /b 1
)
if not exist "%~dp0runtime\packages" (
  echo [WARN] runtime\packages missing - dependencies may fail to load.
  pause
)

echo Starting Qixi Guide ... browser will open automatically.
echo Closing the app window stops the service.
if exist "%PYW%" (
  start "" "%PYW%" "%~dp0launcher.py"
) else (
  start "" "%PY%" "%~dp0launcher.py"
)
exit /b 0
