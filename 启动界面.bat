@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title eNSP config generator

set "VENV=.venv"
set "VENV_PY=.venv\Scripts\python.exe"

echo ==========================================
echo  eNSP config generator - local web UI
echo ==========================================
echo.

if exist "%VENV_PY%" goto check_deps

call :probe py
if not defined SYS_PY call :probe python
if not defined SYS_PY call :probe python3
if not defined SYS_PY goto no_python

echo [INFO] Creating virtual environment .venv with %SYS_PY% ...
%SYS_PY% -m venv .venv
if errorlevel 1 goto venv_failed
if not exist "%VENV_PY%" goto venv_failed

:check_deps
"%VENV_PY%" -c "import yaml, docx" >nul 2>nul
if not errorlevel 1 goto run

echo [INFO] Installing dependencies into .venv (first run only, may take a minute) ...
"%VENV_PY%" -m pip install --disable-pip-version-check --quiet pyyaml python-docx openpyxl
if errorlevel 1 goto pip_failed

:run
echo.
echo Starting the local web UI. Your browser opens automatically.
echo Keep this window open while you use it; close it to stop the server.
echo.
"%VENV_PY%" run.py --ui
set "CODE=%errorlevel%"
echo.
if not "%CODE%"=="0" echo Exit code: %CODE%
echo Window stays open. Press any key to close.
pause >nul
exit /b %CODE%

:probe
where %1 >nul 2>nul
if errorlevel 1 exit /b 0
%1 -c "import sys;raise SystemExit(0 if sys.version_info[0]==3 and sys.version_info[1]>=10 else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "SYS_PY=%1"
exit /b 0

:no_python
echo [ERROR] Python 3.10 or newer was not found on this computer.
echo.
echo   1. Download it from https://www.python.org/downloads/
echo   2. On the first installer page, tick "Add python.exe to PATH"
echo   3. Run this file again
echo.
pause
exit /b 1

:venv_failed
echo [ERROR] Could not create the virtual environment .venv
echo   Delete the .venv folder if it exists and run this file again.
echo   If it still fails, create the environment manually:
echo     python -m venv .venv
echo     .venv\Scripts\python.exe -m pip install pyyaml python-docx openpyxl
echo.
pause
exit /b 1

:pip_failed
echo [ERROR] Installing dependencies failed. Check your network or proxy, then retry.
echo   Manual command:
echo     .venv\Scripts\python.exe -m pip install pyyaml python-docx openpyxl
echo.
pause
exit /b 1
