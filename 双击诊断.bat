@echo off
setlocal
set "PS1=%~dp0scripts\fix-ensp40.ps1"
if not exist "%PS1%" (
  echo [ERROR] scripts\fix-ensp40.ps1 not found.
  echo Keep this .bat next to the scripts folder.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -WhatIf -Pause
exit /b %errorlevel%
