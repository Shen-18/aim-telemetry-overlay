@echo off
cd /d "%~dp0"

rem 1. Pick a real Python (skip the Microsoft Store alias stub in WindowsApps)
set "PY="
for /f "delims=" %%P in ('where python 2^>nul') do (
    echo %%P | find /i "WindowsApps" >nul
    if errorlevel 1 if not defined PY set "PY=%%P"
)
if not defined PY (
    echo ========================================================
    echo   [ERROR] No usable Python found in PATH.
    echo   Install Python 3.10+ and enable "Add Python to PATH".
    echo ========================================================
    pause
    exit /b 1
)

rem 2. Check dependencies, auto-install on first run
"%PY%" -c "import PySide6, numpy, pandas, PIL, imageio_ffmpeg" >nul 2>nul
if %errorlevel% neq 0 (
    echo First run: installing dependencies from requirements.txt ...
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Dependency install failed. Check network or run manually:
        echo         "%PY%" -m pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo Dependencies installed.
)

rem 3. Launch desktop workbench and close terminal console
set "PYW=%PY:python.exe=pythonw.exe%"
if exist "%PYW%" (
    start "" "%PYW%" scripts\app_gui.py %*
) else (
    start "" "%PY%" scripts\app_gui.py %*
)
exit
