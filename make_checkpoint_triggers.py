#!/usr/bin/env python3
"""Generate the 3 standard checkpoint triggers for a Life With Otto Short.

Publish handoff automation: instead of hand-writing post+pin / 24h / 48h triggers
per Short, this emits all three as ready-to-create trigger specs (name, run_once_at
in UTC, prompt) from one line of input. Feed each to create_trigger, or paste the
run_once_at + prompt into the app.

Usage (Windows: `python`; macOS/Linux: `python3`):
  python make_checkpoint_triggers.py \
    --title "Otto has a very specific rule about belly rubs" \
    --publish 2026-08-24 \
    --pin "Does your dog flop over and demand it, or do they make you work for it?"

Options:
  --publish-time  HH:MM local ET publish time (default 12:00 — the locked noon slot)
  --json          emit a JSON array (default: human-readable blocks)

Times are computed in America/New_York (handles EDT/EST automatically) and converted
to UTC RFC3339 for create_trigger's run_once_at. Pin fires publish+10min (no comment
box exists before publish); 24h and 48h fire on the locked 24/48 cadence.
"""
import argparse
import datetime as dt
import json
import sys

try:
    from zoneinfo import ZoneInfo
except ImportError:
    print("Needs Python 3.9+ (zoneinfo).", file=sys.stderr); sys.exit(2)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
CHANNEL_ID = "UCbCHHEKkZXwIABpc4yy29mg"
HANDLE = "@LifeWithOttoTV"
LOG = r"C:\Users\brown\Downloads\Otto Performance Log.csv"
PIN_QUEUE = r"C:\Users\brown\Downloads\Otto Pinned Comment Queue.csv"


def utc(d_et):
    return d_et.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(title, publish_date, publish_time, pin_text):
    hh, mm = (int(x) for x in publish_time.split(":"))
    pub = dt.datetime.combine(publish_date, dt.time(hh, mm), tzinfo=ET)
    row = publish_date.isoformat()
    # %-d/%#d differ across OSes; build the day without leading zero portably.
    long_date = f"{pub.strftime('%a %b')} {pub.day} {pub.year}"

    pin = {
        "name": f'Otto {row} — post & pin comment',
        "run_once_at": utc(pub + dt.timedelta(minutes=10)),
        "prompt": (
            f'The Life With Otto Short "{title}" published today, {long_date}, at '
            f'{publish_time} ET on {HANDLE} (channel {CHANNEL_ID}). Post and pin its comment '
            f'now — use the otto-pin-comment skill.\n\n'
            f'Pin text, from {PIN_QUEUE} row dated {row}: "{pin_text}"\n\n'
            f'Then set that row\'s status to posted and fill in the real video ID. Pins never '
            f'contain links. If the PC is not reachable, hand Kenneth the paste-ready text with '
            f'20-second mobile steps.'
        ),
    }
    h24 = {
        "name": f'Otto {row} — 24h row',
        "run_once_at": utc(pub + dt.timedelta(hours=24)),
        "prompt": (
            f'24h checkpoint for "{title}" (published {long_date}, {publish_time} ET).\n\n'
            f'Run vidiq-shorts-analytics Part 1 (Capture). Real numbers from the vidIQ MCP, '
            f'channel {CHANNEL_ID} — never from memory. Record: views (plus delta and % of typical '
            f'band), subscribers gained (N and % per view), stayed-to-watch %, engaged views, '
            f'Shorts-feed traffic %, sub vs non-sub watch-time split, hype. Append to the {row} row '
            f'in {LOG}.\n\nAlso confirm the pinned comment got posted; if not, run otto-pin-comment.'
        ),
    }
    h48 = {
        "name": f'Otto {row} — 48h close',
        "run_once_at": utc(pub + dt.timedelta(hours=48)),
        "prompt": (
            f'48h close for "{title}" (published {long_date}, {publish_time} ET).\n\n'
            f'Capture the 24h row PLUS average view duration (mm:ss and % of runtime), retention '
            f'shape (mid-clip cliff yes/no with timestamp), unique viewers and loops per person, '
            f'top geography. Real numbers from the vidIQ MCP, channel {CHANNEL_ID}. Update the {row} '
            f'row in {LOG}, mark CLOSED, run vidiq-shorts-analytics Part 2 (Diagnose).'
        ),
    }
    return [pin, h24, h48]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", required=True)
    ap.add_argument("--publish", required=True, help="publish date YYYY-MM-DD")
    ap.add_argument("--pin", required=True, help="pinned-comment text (a question, no links)")
    ap.add_argument("--publish-time", default="12:00", help="local ET HH:MM (default 12:00)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    pdate = dt.date.fromisoformat(a.publish)
    trigs = build(a.title, pdate, a.publish_time, a.pin)
    if a.json:
        print(json.dumps(trigs, indent=2)); return
    print(f"3 checkpoint triggers for: {a.title}\n" + "=" * 60)
    for t in trigs:
        print(f"\n### {t['name']}\nrun_once_at: {t['run_once_at']}\nprompt:\n{t['prompt']}")
    print("\n" + "=" * 60)
    print("Feed each {name, run_once_at, prompt} to create_trigger. Search existing "
          "triggers first so a re-confirmed publish doesn't duplicate them.")


if __name__ == "__main__":
    main()
