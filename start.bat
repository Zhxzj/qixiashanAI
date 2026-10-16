@echo off
rem ASCII-only on purpose. Chinese output comes from scripts\sync_bootstrap.py.
setlocal EnableExtensions
cd /d "%~dp0"
title Qixi Guide

set "LOG=%~dp0startup.log"
echo [start.bat] %date% %time% launching > "%LOG%" 2>nul

if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    echo [start.bat] use .venv python >> "%LOG%"
    "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\sync_bootstrap.py" %*
    goto :done
  )
  echo [start.bat] .venv python broken; trying system python >> "%LOG%"
)

set "PY="
for /f "delims=" %%i in ('where python 2^>nul') do (
  if not defined PY (
    "%%i" -c "import sys;exit(0 if sys.version_info.major==3 and sys.version_info.minor>=10 or sys.version_info.major>3 else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=%%i"
  )
)
if defined PY (
  echo [start.bat] found python: %PY% >> "%LOG%"
  "%PY%" "%~dp0scripts\sync_bootstrap.py" %*
  goto :done
)

set "PY="
set "PY_ARGS="
for /f "delims=" %%i in ('where py 2^>nul') do (
  if not defined PY (
    "%%i" -3 -c "import sys;exit(0 if sys.version_info.major==3 and sys.version_info.minor>=10 or sys.version_info.major>3 else 1)" >nul 2>nul
    if not errorlevel 1 (
      set "PY=%%i"
      set "PY_ARGS=-3"
    )
  )
)
if defined PY (
  echo [start.bat] found py launcher: %PY% %PY_ARGS% >> "%LOG%"
  "%PY%" %PY_ARGS% "%~dp0scripts\sync_bootstrap.py" %*
  goto :done
)

echo [ERROR] Python 3.10 or newer is required.
echo   Install from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
echo [start.bat] python not found >> "%LOG%"
pause
exit /b 1

:done
if errorlevel 1 (
  echo.
  echo [start.bat] exited with error %errorlevel% >> "%LOG%"
  echo [ERROR] Startup failed. See startup.log in this folder.
  pause
)
exit /b 0
