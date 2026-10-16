@echo off
rem Dev server (foreground). ASCII-only; Chinese output from Python.
chcp 65001 >nul
cd /d "%~dp0.."
title Qixi Guide - dev server
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\sync_bootstrap.py --server
) else (
  echo [ERROR] No .venv yet. Run start.bat once first.
)
pause
