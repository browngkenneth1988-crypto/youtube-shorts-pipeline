@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM Double-click to run the Curious Classroom queue builder right now,
REM instead of waiting for the 6am scheduled run. Same job, visible output.
REM Scores topics and banks scripts. Builds nothing, uploads nothing.

cd /d C:\Users\brown\youtube-shorts-pipeline

if not exist "scripts\secrets.bat" (
    echo [ERROR] scripts\secrets.bat not found.
    pause
    exit /b 1
)
call scripts\secrets.bat

set PYEXE=
for %%P in ("py -3.13" "py -3.12" "py -3.11" "py -3" "python") do (
    if not defined PYEXE (
        %%~P -c "import sys" >nul 2>&1 && set "PYEXE=%%~P"
    )
)
if not defined PYEXE (
    echo [ERROR] No working Python found.
    pause
    exit /b 1
)

call scripts\ensure_deps.bat

%PYEXE% scripts\curious_daily.py --limit 12 --verbose
echo.
echo Queue file: C:\Users\brown\.verticals\curious_queue.csv
echo.
pause
