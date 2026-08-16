@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM Curious Classroom — score a topic, and only if it clears 40/50, build the video.
REM
REM Usage:
REM   scripts\curious_run.bat "Why Time Feels Faster As You Age"
REM   scripts\curious_run.bat "Why Time Feels Faster As You Age" score
REM
REM Nothing here uploads. niches\curious_classroom.yaml has shorts_allowed: false
REM for Phase 1 (videos 1-8), so the upload stage is blocked by policy anyway.

setlocal
cd /d C:\Users\brown\youtube-shorts-pipeline

if "%~1"=="" (
    echo Usage: curious_run.bat "topic" [score]
    exit /b 1
)

if not exist "scripts\secrets.bat" (
    echo [ERROR] scripts\secrets.bat not found. Copy scripts\secrets.example.bat and fill in your keys.
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

if /i "%~2"=="score" (
    %PYEXE% -m verticals score --topic "%~1" --niche curious_classroom
    exit /b %ERRORLEVEL%
)

REM Full build: gate -> script -> b-roll -> voiceover -> captions -> music -> assemble.
REM --dry-run stops after the draft so you can read the script before spending image credits.
%PYEXE% -m verticals run --topic "%~1" --niche curious_classroom --voice edge --verbose
exit /b %ERRORLEVEL%
