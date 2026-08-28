@echo off
rem ==============================================================================
rem  Unattended Test Runner for dockurr/windows
rem ==============================================================================

echo [OEM Setup] Initializing Windows Test Environment...
powershell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy RemoteSigned -Force"

rem Map shared host workspace drive
if exist "Z:\install.ps1" (
    cd /d Z:\
    echo [OEM Setup] Found shared repository at Z:\
    echo [OEM Setup] Running install.ps1...
    rem Host options (-NonInteractive) must precede -File; -NoPause is the script switch.
    powershell -ExecutionPolicy Bypass -NonInteractive -File .\install.ps1 -NoPause
    if errorlevel 1 (
        call :fail installer
        exit /b 1
    )
    echo [OEM Setup] Installing dependencies (main, dev, ml-heavy)...
    .\.VENV\Scripts\python.exe -m poetry -v install --only main,dev,ml-heavy
    if errorlevel 1 (
        call :fail dependencies
        exit /b 1
    )
    echo [OEM Setup] Running Pytest suite...
    .\.VENV\Scripts\python.exe -m pytest -v tests/
    if errorlevel 1 (
        call :fail tests
        exit /b 1
    )
    echo [OEM Setup] All Windows container tests completed successfully.
    > Z:\windows_test_status.txt echo passed
    shutdown /s /t 0
) else (
    echo [OEM Setup] Shared repository not found at Z:\. Waiting for volume mount...
    call :fail missing-mount
    exit /b 1
)

exit /b 0

:fail
echo [OEM Setup] Failure during %~1.
> Z:\windows_test_status.txt echo failed: %~1
shutdown /s /t 0
exit /b 1
