# What runs when

*Updated Aug 15 2026.*

## 6:00 AM daily — Windows Task Scheduler

Runs `scripts\daily_run.bat`. **Do not repoint Task Scheduler** — change what
`daily_run.bat` calls instead, so the schedule itself never has to be edited.

Currently calls `scripts/curious_daily.py`:

- pulls topics from the Curious Classroom discovery sources
- scores every new one against the 50-point rubric (40+ to approve)
- appends results to `~/.verticals/curious_queue.csv`
- writes a script for the single highest-scoring approved topic not yet drafted
- **builds nothing, uploads nothing** — no images, no voice, no Leonardo credits

Log: `~/.verticals/logs/curious_daily.log`

### How a bad morning looks now

Until Aug 15 2026 a failed run was invisible: every step swallowed its own
exception, the script exited 0, and Task Scheduler recorded success. The job had
been drafting nothing for days while reporting clean.

Three things changed:

- **The run exits non-zero** when it scores nothing it was given, or the draft
  fails. Task Scheduler's `LastTaskResult` is now a real signal.
- **It writes its own verdict** to `~/.verticals/logs/last_run_status.txt`, and a
  failure appends to `~/.verticals/logs/ALERTS.md` and raises a desktop toast.
- **`scripts\healthcheck.py` reports the last run** as a FAIL line, so the
  morning's outcome shows up without opening a log.

### The quota ceiling that caused it

Gemini's free tier allows **20 generate requests per day** for
`gemini-2.5-flash` — not per minute, per *day*. The queue builder asks for a
dozen scores plus a draft, and the old code retried each failure three times, so
a single run could spend 24+ requests against a budget of 20 and end with
nothing scored.

`verticals/llm.py` now treats quota and auth errors as *exhaustion* rather than
something to retry: the provider is dropped for the rest of the run after one
refusal, and `call_llm` fails over to the next configured provider.

### The fallback chain, as configured

`gemini` → `claude`. Verified live on 2026-08-16 by forcing Gemini's 429 and
watching a real Claude call answer.

Gemini stays first because it is free. Claude runs on a metered
`ANTHROPIC_API_KEY` in `scripts\secrets.bat` (key `verticals-fallback`, no
expiry — an expiring key would take the 6am job down on a morning nobody was
watching for it).

Cost, measured against the real prompts: a scoring call is ~796 input tokens
and a draft ~1777, so a full day at `--limit 12` is ~11.3k input and ~6k
output. On `claude-sonnet-5` that is roughly **$2.50/month worst case** — worst
case meaning Gemini is dry every single day. Days Gemini covers cost nothing.

If that ever needs to go to zero, install Ollama and it slots in ahead of
Claude as a $0 local option.

Why this and not video production: Curious Classroom Phase 1 canon is one
long-form per week and no Shorts until video 8 is live. A daily Shorts builder
would violate the cadence the playbook exists to protect. The channel's actual
bottleneck is a scored topic queue.

## Manual runners

| Script | What it does |
|---|---|
| `scripts\curious_run.bat "topic"` | Gate + full build for one Curious Classroom topic. Upload blocked by Phase 1 policy. |
| `scripts\curious_run.bat "topic" score` | Score only, no build. |
| `scripts\pets_run.bat` | The old pets/Otto pipeline. Parked — see the header. Uploads private. |
| `scripts\reauth.bat` | Re-authorise YouTube. Prints the channel it authorised. |

## Voice engine

**Edge TTS (free).** The ElevenLabs subscription ended Aug 1 2026 and its key was
removed from `scripts\secrets.bat`. The `music/` library is local MP3 files with
no API dependency and is unaffected.

`curious-classroom-playbook` v1.3 still names ElevenLabs as the engine. The
decision it locked (synthetic narration) holds; the engine named in it does not
exist any more. The playbook needs a v1.4 patch.
