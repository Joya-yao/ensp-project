@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto run

echo [ERROR] .venv not found.
echo    python -m venv .venv
echo    .venv\Scripts\python.exe -m pip install pyyaml python-docx openpyxl
echo.
pause
exit /b 1

:run
echo Starting eNSP config generator (browser will open automatically)...
".venv\Scripts\python.exe" run.py --ui
set CODE=%errorlevel%
echo.
if not "%CODE%"=="0" echo Exit code: %CODE%
echo Window stays open. Press any key to close.
pause >nul
