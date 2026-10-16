@echo off
rem ASCII-only on purpose.
chcp 65001 >nul
title Qixi Guide - Stop
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\stop_service.py
) else (
  where python >nul 2>&1 && (python scripts\stop_service.py) || (
    python3 scripts\stop_service.py 2>nul || echo [ERROR] Python not found.
  )
)
pause
