@echo off
rem ASCII-only on purpose.
chcp 65001 >nul
title Qixi Guide - Build portable pack
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] No .venv yet. Run start.bat once first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\build_portable.py %*
set "BUILD_RC=%errorlevel%"
if not "%BUILD_RC%"=="0" pause
exit /b %BUILD_RC%
