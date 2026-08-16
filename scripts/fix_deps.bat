@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM Double-click to repair the Python environment after a version change.
cd /d C:\Users\brown\youtube-shorts-pipeline

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
echo Interpreter: %PYEXE%
%PYEXE% -c "import sys; print('Version:', sys.version)"
echo.
echo Installing everything the pipeline needs...
%PYEXE% -m pip install --disable-pip-version-check PyYAML edge-tts Pillow requests feedparser google-api-python-client google-auth-oauthlib anthropic
echo.
echo Verifying...
%PYEXE% -c "import yaml, edge_tts, PIL, requests, feedparser; print('  all core imports OK')"
%PYEXE% -c "import whisper; print('  whisper OK')" 2>nul || echo   whisper MISSING - run: %PYEXE% -m pip install openai-whisper
echo.
echo Now double-click healthcheck.bat again.
pause
