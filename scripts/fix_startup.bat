@echo off
rem Repair mode: move the broken .venv aside, then run start.bat (which rebuilds it).
rem ASCII-only on purpose. Chinese output comes from Python.
setlocal EnableExtensions
cd /d "%~dp0.."
title Qixi Guide - fix startup

echo Repair mode: moving old .venv out of the way (if any) ...
if exist ".venv" (
  if exist ".venv-old" rmdir /s /q ".venv-old"
  move /y ".venv" ".venv-old" >nul
)

call "%~dp0..\start.bat" %*
echo.
echo Done. Details in startup.log
pause
