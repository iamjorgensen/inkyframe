@echo off
setlocal

REM Path to your virtual environment's Python
set "PY=C:\temp\inkyframe\venv\Scripts\python.exe"

REM Script must be in the same folder as this .bat
set "SCRIPT=%~dp0main.py"

REM Log file
set "LOG=%~dp0render.log"

echo [%date% %time%] === Starting render loop === >> "%LOG%"
echo Using PY=%PY% >> "%LOG%"
echo Using SCRIPT=%SCRIPT% >> "%LOG%"

:LOOP
echo [%date% %time%] Running renderer... >> "%LOG%"

"%PY%" "%SCRIPT%" >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%

if not "%RC%"=="0" (
    echo [%date% %time%] Renderer exited with error %RC% >> "%LOG%"
) else (
    echo [%date% %time%] Renderer finished OK >> "%LOG%"
)

REM Wait 300 seconds (5 minutes)
timeout /t 60*60 /nobreak >nul

goto LOOP
