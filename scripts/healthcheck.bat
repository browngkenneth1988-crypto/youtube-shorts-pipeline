@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM Double-click to prove the whole stack works before 6am does.
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

%PYEXE% scripts\healthcheck.py
echo.
pause
