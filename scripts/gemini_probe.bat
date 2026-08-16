@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM Double-click. Finds which Gemini auth path works for your key.
cd /d C:\Users\brown\youtube-shorts-pipeline
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

%PYEXE% -c "import google.genai" >nul 2>&1
if errorlevel 1 (
    echo Installing google-genai SDK to test the official path...
    %PYEXE% -m pip install --quiet --disable-pip-version-check google-genai
)

%PYEXE% scripts\gemini_probe.py
echo.
pause
