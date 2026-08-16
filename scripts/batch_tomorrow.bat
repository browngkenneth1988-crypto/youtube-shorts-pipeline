@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM ============================================================
REM  One-shot batch: finish the Curious Classroom topics that hit
REM  Gemini's daily quota on 2026-08-16.
REM
REM  Registered as a ONE-TIME Task Scheduler job for 2026-08-17 08:05,
REM  which is after the free-tier quota resets (midnight US/Pacific
REM  = 03:00 ET). Task name: VerticalsBatchCatchup
REM
REM  Cancel with:  schtasks /delete /tn VerticalsBatchCatchup /f
REM
REM  Reads its topics from %USERPROFILE%\.verticals\pending_topics.txt
REM  so the list can be edited without touching this file.
REM
REM  Uploads land PRIVATE (niche policy). Nothing publishes itself.
REM ============================================================
cd /d C:\Users\brown\youtube-shorts-pipeline

call "%~dp0secrets.bat" 2>nul

set LOG=%USERPROFILE%\.verticals\logs\batch_catchup.log
if not exist "%USERPROFILE%\.verticals\logs" mkdir "%USERPROFILE%\.verticals\logs"

echo. >> "%LOG%"
echo ==================== %DATE% %TIME% ==================== >> "%LOG%"

py -3 scripts\batch_shorts.py --niche curious_classroom ^
    --topics-file "%USERPROFILE%\.verticals\pending_topics.txt" >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%

REM Surface the outcome instead of exiting 0 into a log nobody reads --
REM that is exactly how the 6am job failed unnoticed for months.
py -3 -c "import sys; sys.path.insert(0, r'C:\Users\brown\youtube-shorts-pipeline'); from verticals.notify import record_status, alert; rc=%RC%; (record_status('batch_catchup', ok=True, detail='batch finished') if rc==0 else alert('batch_catchup', 'Batch exited %RC% - see batch_catchup.log'))" >> "%LOG%" 2>&1

echo exit=%RC% >> "%LOG%"
exit /b %RC%
