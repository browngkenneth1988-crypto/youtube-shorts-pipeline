#!/usr/bin/env python3
"""Give every freshly uploaded, unscheduled video a publish slot.

    py -3 scripts/schedule_uploads.py --niche curious_classroom            # dry run
    py -3 scripts/schedule_uploads.py --niche curious_classroom --apply

Reads cadence_days and publish_window_et from the niche profile, finds the
latest slot already taken on the channel, and lays the unscheduled videos out
after it at that cadence. Running it twice is a no-op: anything already
carrying a publishAt is left alone.

SAFETY. This makes private videos go public on their own, so the selection is
deliberately narrow:

  * only videos with privacyStatus 'private' AND no publishAt
  * only videos uploaded within --max-age-days (default 7), so an old private
    video someone is sitting on never gets swept into a schedule
  * never touches a video that is already scheduled or already public
  * never touches an id listed in ~/.verticals/schedule_skip.txt
  * --apply is required; without it this only prints the plan

The skip list exists because "private with no publishAt" is also what a video
you deliberately want kept back looks like. Unscheduling something would
otherwise just hand it back to this script on the next run.

Timezone comes from zoneinfo, not a hardcoded offset, so the 9am slot stays
9am across the DST boundary rather than silently shifting an hour in November.
"""
import argparse
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = Path.home() / ".verticals"

try:
    # Windows ships no system tz database, so zoneinfo needs the tzdata
    # package. Failing loudly beats falling back to a fixed UTC offset: that
    # would put every slot an hour out from the first Sunday in November.
    ET = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    raise SystemExit(
        "No timezone database found. Install it with:\n"
        "    py -3 -m pip install tzdata"
    ) from None


SKIP_FILE = SKILL_DIR / "schedule_skip.txt"


def load_profile(niche: str) -> dict:
    return yaml.safe_load((REPO / "niches" / f"{niche}.yaml").read_text(encoding="utf-8"))


def load_skips() -> set:
    """Video ids that must never be auto-scheduled. One per line, # comments."""
    if not SKIP_FILE.exists():
        return set()
    return {
        ln.strip() for ln in SKIP_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    }


def token_for(niche: str) -> Path:
    for p in (SKILL_DIR / f"youtube_token_{niche}.json", SKILL_DIR / "youtube_token.json"):
        if p.exists():
            return p
    raise SystemExit(f"No YouTube token for niche '{niche}'. Run scripts\\reauth.bat {niche}")


def client(niche: str):
    creds = Credentials.from_authorized_user_file(str(token_for(niche)))
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def channel_videos(yt):
    """Every video on the authorised channel, newest first."""
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], None
    while True:
        try:
            r = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                        maxResults=50, pageToken=page).execute()
        except Exception:
            return []          # empty channel: the uploads playlist 404s
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    out = []
    for i in range(0, len(ids), 50):
        out += yt.videos().list(part="snippet,status", id=",".join(ids[i:i + 50])).execute()["items"]
    return out


def next_slot_after(dt_utc, cadence_days, slot_time):
    """First slot strictly after dt_utc, on the cadence, at the ET slot time."""
    day = dt_utc.astimezone(ET).date() + timedelta(days=cadence_days)
    return datetime.combine(day, slot_time, tzinfo=ET).astimezone(timezone.utc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-age-days", type=int, default=7)
    a = ap.parse_args()

    prof = load_profile(a.niche)
    pub = prof.get("publishing", {}) or {}
    cadence = int(pub.get("cadence_days", 2))
    window = str(pub.get("publish_window_et", "09:00-11:00")).split("-")[0]
    hh, mm = (int(x) for x in window.split(":"))
    slot_time = time(hh, mm)

    yt = client(a.niche)
    vids = channel_videos(yt)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=a.max_age_days)

    skips = load_skips()
    scheduled, pending, skipped = [], [], []
    for v in vids:
        st, sn = v["status"], v["snippet"]
        published = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        if st.get("publishAt"):
            scheduled.append(datetime.fromisoformat(st["publishAt"].replace("Z", "+00:00")))
        elif v["id"] in skips:
            skipped.append(v)
        elif st["privacyStatus"] == "private" and published >= cutoff:
            pending.append((published, v))

    pending.sort(key=lambda t: t[0])          # oldest upload gets the earliest slot

    print(f"niche {a.niche}: cadence {cadence}d, slot {slot_time:%H:%M} ET")
    print(f"  on channel : {len(vids)} video(s)")
    print(f"  scheduled  : {len(scheduled)}")
    if skipped:
        print(f"  skip-listed: {len(skipped)}  ({SKIP_FILE.name})")
        for v in skipped:
            print(f"               {v['id']}  {v['snippet']['title'][:44]}")
    print(f"  to schedule: {len(pending)}  (private, unscheduled, <{a.max_age_days}d old)")
    if not pending:
        print("\nNothing to do.")
        return 0

    # Start after the last taken slot, or from today if the channel is empty.
    cursor = max(scheduled) if scheduled else now
    print()
    for _, v in pending:
        when = next_slot_after(cursor, cadence, slot_time)
        while when <= now:                     # never schedule into the past
            when = next_slot_after(when, cadence, slot_time)
        cursor = when
        et = when.astimezone(ET)
        print(f"  {v['id']}  {et:%a %d %b %H:%M} ET   {v['snippet']['title'][:44]}")

        if not a.apply:
            continue
        status = v["status"]
        status["privacyStatus"] = "private"    # required alongside publishAt
        status["publishAt"] = when.isoformat().replace("+00:00", "Z")
        yt.videos().update(part="status", body={"id": v["id"], "status": status}).execute()

    if not a.apply:
        print("\nDry run. Re-run with --apply to schedule.")
        return 0

    # Read back fresh: the API serves a stale status immediately after a write.
    print("\nverifying...")
    ok = 0
    for _, v in pending:
        st = yt.videos().list(part="status", id=v["id"]).execute()["items"][0]["status"]
        got = st.get("publishAt")
        print(f"  {v['id']}  publishAt={got}  privacy={st['privacyStatus']}")
        ok += bool(got)
    print(f"\n  {ok}/{len(pending)} scheduled")
    return 0 if ok == len(pending) else 1


if __name__ == "__main__":
    sys.exit(main())
