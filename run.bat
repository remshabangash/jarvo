@echo off
rem JARVO one-click launcher — always uses the project's own venv python.
rem Double-click this file to start the web server (http://127.0.0.1:5000)
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo [JARVO] venv nahi mila — pehle install_windows.bat chalao.
    pause
    exit /b 1
)
venv\Scripts\python Server.py
echo.
echo [JARVO] Server band ho gaya ya crash hua. Window khuli rakhi hai taake error parh saken.
pause
