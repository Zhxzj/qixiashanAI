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
if errorlevel 1 pause
exit /b 0
