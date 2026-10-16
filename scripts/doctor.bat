@echo off
rem ASCII-only on purpose.
chcp 65001 >nul
title Qixi Guide - Doctor
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\doctor.py
) else (
  echo [ERROR] No .venv yet. Run start.bat once first.
)
pause
