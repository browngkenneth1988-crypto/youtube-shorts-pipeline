@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM ============================================================
REM  Re-authorise YouTube uploads. Pass a niche to pick the channel:
REM    scripts\reauth.bat                    -> Life With Otto   (@LifeWithOttoTV)
REM    scripts\reauth.bat curious_classroom  -> Curious Classroom (@CuriousClassroomTV)
REM  Each channel keeps its own token file, so both stay authorised at once.
REM  Double-click this file. A browser window opens. Sign in.
REM  It prints which channel got authorised so you can catch a
REM  wrong-account sign-in immediately.
REM ============================================================

cd /d C:\Users\brown\youtube-shorts-pipeline

set PYEXE=
for %%P in ("py -3.13" "py -3.12" "py -3.11" "py -3" "python") do (
    if not defined PYEXE (
        %%~P -c "import sys" >nul 2>&1 && set "PYEXE=%%~P"
    )
)
if not defined PYEXE (
    echo [ERROR] No working Python found. Install Python 3.11+ from python.org and re-run.
    echo         Tick "Add python.exe to PATH" during install.
    pause
    exit /b 1
)
echo Using: %PYEXE%
echo.

%PYEXE% -c "import google_auth_oauthlib, googleapiclient" >nul 2>&1
if errorlevel 1 (
    echo Installing the Google auth libraries, one moment...
    %PYEXE% -m pip install --quiet google-auth-oauthlib google-api-python-client
)

%PYEXE% scripts\reauth_youtube.py %1
echo.
pause
