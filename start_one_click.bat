@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_one_click.ps1" %*
if errorlevel 1 (
  echo.
  pause
)
