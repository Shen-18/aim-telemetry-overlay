@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 1. 检查是否存在 Python 环境
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ========================================================
    echo   [错误] 系统未检测到 Python 命令！
    echo   请先安装 Python 3.10 或更高版本，并在安装时勾选
    echo   "Add Python to PATH"（添加到系统环境变量）。
    echo ========================================================
    pause
    exit /b 1
)

REM 2. 检查关键依赖库是否已安装，若缺失则自动从 requirements.txt 安装
python -c "import PySide6, numpy, pandas, PIL, imageio_ffmpeg" >nul 2>nul
if %errorlevel% neq 0 (
    echo ========================================================
    echo   首次运行提示：检测到尚未安装运行所需依赖
    echo   正在自动执行: pip install -r requirements.txt
    echo   请稍候...
    echo ========================================================
    python -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo [错误] 依赖安装失败，请检查网络连接或手动运行:
        echo        pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo.
    echo [完成] 依赖安装成功，正在启动工作台...
    echo.
)

REM 3. 启动 GUI 桌面工作台
python scripts\app_gui.py %*

