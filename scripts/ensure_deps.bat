@echo off
REM Called by the runners. Installs anything missing into the resolved %PYEXE%.
REM Python versions move (py -3 went 3.13 -> 3.14 in Aug 2026) and packages do
REM not follow. This makes that a non-event instead of a silent 6am failure.
if not defined PYEXE exit /b 1
%PYEXE% -c "import yaml, edge_tts, PIL, requests, feedparser" >nul 2>&1
if not errorlevel 1 exit /b 0
echo [deps] Installing missing packages into %PYEXE% ...
%PYEXE% -m pip install --quiet --disable-pip-version-check PyYAML edge-tts Pillow requests feedparser google-api-python-client google-auth-oauthlib
%PYEXE% -c "import yaml, edge_tts, PIL, requests, feedparser" >nul 2>&1
if errorlevel 1 (
    echo [deps] STILL MISSING after install. Run scripts\fix_deps.bat and read the output.
    exit /b 1
)
echo [deps] OK
exit /b 0
