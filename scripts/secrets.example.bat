@echo off
REM Copy this file to scripts\secrets.bat and fill in real keys.
REM scripts\secrets.bat is gitignored. Never commit real keys.

set GEMINI_API_KEY=
set LEONARDO_API_KEY=

REM Failover provider. Gemini's free tier allows 20 generate requests PER DAY,
REM which one queue-builder run can exhaust. verticals/llm.py fails over to the
REM next configured provider when that happens, so setting at least one of these
REM is what makes the 6am job survive a dry vendor. Cost at this volume is cents
REM per month. ANTHROPIC_API_KEY is a pay-per-call key, not a Max subscription.
set ANTHROPIC_API_KEY=
REM set OPENAI_API_KEY=

REM Optional:
REM set ELEVENLABS_API_KEY=
REM set YT_PRIVACY=private
