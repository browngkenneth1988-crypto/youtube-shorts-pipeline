@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM ============================================================
REM  The old pets / OttoMissClub daily pipeline. NOT scheduled.
REM
REM  Parked Aug 4 2026. It generates AI Otto imagery with synthetic
REM  narration for @LifeWithOttoTV, whose canon (otto-youtube-playbook
REM  v3.7, otto-shorts-factory) is real footage, music only, never AI
REM  voiceover. Uploads are private by default via niches\pets.yaml.
REM
REM  Run it by hand if you want it. To put it back on the 6am task,
REM  point Task Scheduler at this file instead of daily_run.bat.
REM ============================================================

cd /d C:\Users\brown\youtube-shorts-pipeline

if not exist "scripts\secrets.bat" (
    echo [ERROR] scripts\secrets.bat not found.
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
    echo [ERROR] No working Python interpreter found.
    exit /b 1
)

call scripts\ensure_deps.bat

%PYEXE% -c "import edge_tts" >nul 2>&1
if errorlevel 1 (
    echo Installing edge-tts ^(free voice engine^), one moment...
    %PYEXE% -m pip install --quiet edge-tts
)

%PYEXE% scripts/daily_shorts.py --niche pets --voice edge --verbose >> C:\Users\brown\.verticals\logs\daily.log 2>&1
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo [%DATE% %TIME%] pets_run.bat exited with %RC% >> C:\Users\brown\.verticals\logs\daily.log
exit /b %RC%
