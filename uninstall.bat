@echo off
rem ASCII-only on purpose.
chcp 65001 >nul
cd /d "%~dp0"
title Qixi Guide - Uninstall
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\uninstall.py
) else (
  where python >nul 2>&1 && (python scripts\uninstall.py) || (
    echo Python not found; please run this from the project folder with Python installed.
    echo You can also simply delete this folder (green app, no registry changes).
  )
)
pause
