@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo 没找到 .venv，先建虚拟环境：
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install pyyaml python-docx openpyxl
    pause
    exit /b 1
)

echo 正在启动 eNSP 配置生成器（浏览器会自动打开）...
".venv\Scripts\python.exe" run.py --ui
if errorlevel 1 (
    echo.
    echo 启动失败，按任意键关闭。
    pause >nul
)
