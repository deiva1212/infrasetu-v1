@echo off
title Infrasetu server
cd /d "%~dp0"
echo ============================================
echo   Infrasetu - starting local server
echo ============================================

set "PY=%USERPROFILE%\anaconda3\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "venv\Scripts\python.exe" (
  echo Creating virtual environment...
  "%PY%" -m venv venv || goto :fail
)

echo Installing / checking packages...
"venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

if not exist "infrasetu.db" (
  echo Loading sample data...
  "venv\Scripts\python.exe" -m flask --app app seed || goto :fail
)

echo.
echo  App running at  http://127.0.0.1:5000
echo  Admin login:    admin@infrasetu.in / Admin@123
echo  Close this window to stop the server.
echo.
start "" http://127.0.0.1:5000
"venv\Scripts\python.exe" -m flask --app app run --port 5000
goto :eof

:fail
echo.
echo Something went wrong - see the messages above.
pause
