@echo off
REM Daily OttoMissClub YouTube Shorts automation
REM This script is run by Windows Task Scheduler

cd /d C:\Users\brown\youtube-shorts-pipeline

REM Set API keys
set GEMINI_API_KEY=AIzaSyAwRAsyRh8e6tCGVAgJEy8jMjcX2Uzgu7A
set LEONARDO_API_KEY=a70c59de-56a1-444e-b9dc-e48e2941d571
set ELEVENLABS_API_KEY=sk_407e277891f0574aaf77b191e05c82caaa7ff992446bf3c6

REM Run the pipeline
py -3.13 scripts/daily_shorts.py --niche pets --voice elevenlabs --verbose >> C:\Users\brown\.verticals\logs\daily.log 2>&1
