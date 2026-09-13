@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SAATHI Setup

echo ================================================
echo              SAATHI - First-time setup
echo ================================================
echo.

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python 3 is required. Install it from https://www.python.org/downloads/windows/
        echo Enable ^"Add Python to PATH^" during installation, then run this file again.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist "venv\Scripts\python.exe" (
    echo Creating an isolated Python environment...
    %PYTHON% -m venv venv
    if errorlevel 1 goto :failed
)

echo Installing SAATHI dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed

if not exist ".env" (
    echo.
    echo Enter your Groq API key. It will be saved only in this folder.
    set /p "GROQ_API_KEY=GROQ_API_KEY: "
    if not defined GROQ_API_KEY (
        echo A Groq API key is required to use SAATHI.
        pause
        exit /b 1
    )
    >.env echo GROQ_API_KEY=%GROQ_API_KEY%
)

echo.
echo Setup complete. Starting SAATHI...
start "SAATHI" http://127.0.0.1:5000
venv\Scripts\python.exe server.py
exit /b %ERRORLEVEL%

:failed
echo.
echo Setup failed. Read the error above and try again.
pause
exit /b 1
