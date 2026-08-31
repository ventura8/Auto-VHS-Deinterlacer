@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" if not exist ".VENV\Scripts\python.exe" (
    echo [INFO] Virtual environment not found. Running automatic installation...
    powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
    if %errorlevel% neq 0 (
        echo [ERROR] Installation failed.
        pause
        exit /b 1
    )
)

echo Starting Auto-VHS-Deinterlacer...
REM Safely forward all drag-and-drop arguments with strict parameter quoting
set "CMD_ARGS="
:loop_args
if "%~1"=="" goto run_app
set CMD_ARGS=%CMD_ARGS% "%~1"
shift
goto loop_args

:run_app
set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=.VENV\Scripts\python.exe"
"%PYTHON_EXE%" auto_deinterlancer.py %CMD_ARGS%

if %errorlevel% neq 0 (
    echo.
    echo [APP ERROR] The application crashed or exited with an error.
    pause
) else (
    echo.
    echo Application finished.
    pause
)
