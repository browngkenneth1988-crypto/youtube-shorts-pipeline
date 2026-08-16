@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM ============================================================
REM  6:00 AM Windows Task Scheduler job.
REM
REM  Aug 4 2026: repointed from the pets/Otto pipeline to the
REM  Curious Classroom queue builder.
REM
REM  Why: the pets pipeline produced AI-generated Otto imagery with
REM  synthetic narration for @LifeWithOttoTV, whose canon is real
REM  footage and music only. Curious Classroom's bottleneck is a
REM  scored topic queue, not production capacity, and its Phase 1
REM  cadence forbids daily Shorts. So this scores topics and banks
REM  scripts. It builds nothing and uploads nothing.
REM
REM  The old pets pipeline still exists: scripts\pets_run.bat
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

%PYEXE% scripts/curious_daily.py --limit 12 --verbose >> C:\Users\brown\.verticals\logs\curious_daily.log 2>&1
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo [%DATE% %TIME%] curious_daily exited with %RC% >> C:\Users\brown\.verticals\logs\curious_daily.log
exit /b %RC%
