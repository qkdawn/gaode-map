@echo off
setlocal

set "IP=%~1"
if "%IP%"=="" (
  set /p IP=Enter new public DB IP: 
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_analysis.ps1" -PublicDbHost "%IP%"
if errorlevel 1 (
  echo.
  pause
)
