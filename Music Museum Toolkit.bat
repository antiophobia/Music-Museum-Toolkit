@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo Python is required to run Music Museum Toolkit.
    echo Install Python 3, then double-click this launcher again.
    pause
    exit /b 1
)

python "Scripts\main.py"
set "toolkit_exit_code=%errorlevel%"

if not "%toolkit_exit_code%"=="0" (
    echo.
    echo Music Museum Toolkit stopped unexpectedly with exit code %toolkit_exit_code%.
    echo Review the message above for details.
    pause
)

exit /b %toolkit_exit_code%
