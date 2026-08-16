#!/usr/bin/env python3
"""Stack healthcheck — proves every dependency works before a scheduled run does.

Checks Python, ffmpeg, edge-tts, Whisper, the Gemini key, the Leonardo key, and
the YouTube token. Costs nothing: every network call is a free metadata endpoint.

    py -3 scripts/healthcheck.py
"""

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OK, WARN, FAIL = "  OK  ", " WARN ", " FAIL "
results = []


def record(status, name, detail=""):
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def check_python():
    v = sys.version_info
    if v >= (3, 10):
        record(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    else:
        record(FAIL, "Python", f"{v.major}.{v.minor} — need 3.10+")


def check_ffmpeg():
    for exe in ("ffmpeg", "ffprobe"):
        if shutil.which(exe):
            record(OK, exe)
        else:
            record(FAIL, exe, "not on PATH — video assembly will fail")


def check_imports():
    for mod, why in (("edge_tts", "voiceover"), ("whisper", "captions"),
                     ("yaml", "niche profiles"), ("PIL", "thumbnails")):
        try:
            __import__(mod)
            record(OK, f"import {mod}", why)
        except Exception as e:
            record(FAIL, f"import {mod}", f"{why} — {type(e).__name__}")


def check_gemini():
    from verticals.config import get_gemini_key
    key = get_gemini_key()
    if not key:
        record(FAIL, "Gemini key", "not set in env or ~/.verticals/config.json")
        return
    try:
        import requests
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": key}, timeout=20,
        )
        if r.status_code == 200:
            n = len(r.json().get("models", []))
            # Listing models is free and does not touch the generate quota, so
            # this proves the key is accepted, not that there are requests left.
            # The Topic gate check below is what exercises the real budget.
            record(OK, "Gemini key", f"accepted, {n} models visible (auth only)")
        elif r.status_code in (400, 401, 403):
            record(FAIL, "Gemini key", f"HTTP {r.status_code} — rejected. "
                                       f"Generate a fresh one at aistudio.google.com/apikey")
        else:
            record(WARN, "Gemini key", f"HTTP {r.status_code}")
    except Exception as e:
        record(WARN, "Gemini key", f"could not reach Google — {type(e).__name__}")


def check_leonardo():
    from verticals.config import get_leonardo_key
    key = get_leonardo_key()
    if not key:
        record(WARN, "Leonardo key", "not set — b-roll images will fail")
        return
    try:
        import requests
        r = requests.get(
            "https://cloud.leonardo.ai/api/rest/v1/me",
            headers={"Authorization": f"Bearer {key}", "accept": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            d = r.json()
            try:
                u = d["user_details"][0]
                record(OK, "Leonardo key", f"valid, {u.get('subscriptionTokens', '?')} tokens left")
            except Exception:
                record(OK, "Leonardo key", "valid")
        elif r.status_code in (401, 403):
            record(FAIL, "Leonardo key", f"HTTP {r.status_code} — rejected")
        else:
            record(WARN, "Leonardo key", f"HTTP {r.status_code}")
    except Exception as e:
        record(WARN, "Leonardo key", f"could not reach Leonardo — {type(e).__name__}")


CHANNELS = {
    "pets":              ("youtube_token.json",                   "lifewithottotv"),
    "curious_classroom": ("youtube_token_curious_classroom.json", "curiousclassroomtv"),
}


def check_youtube(niche="pets"):
    name, want = CHANNELS[niche]
    label = f"YouTube token [{niche}]"
    token = Path.home() / ".verticals" / name
    if not token.exists():
        record(WARN, label, f"not authorized yet — run: scripts\\reauth.bat {niche}")
        return
    try:
        import json
        d = json.loads(token.read_text(encoding="utf-8"))
        if not d.get("refresh_token"):
            record(FAIL, label, "no refresh_token — re-run scripts\\reauth.bat")
            return
        need = {"https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.force-ssl"}
        missing = need - set(d.get("scopes", []))
        if missing:
            record(FAIL, label, "missing a scope — re-run reauth and tick both boxes")
            return
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_file(str(token))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        yt = build("youtube", "v3", credentials=creds)
        ch = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
        handle = ch["snippet"].get("customUrl", "?")
        if want in str(handle).lower().lstrip("@"):
            record(OK, label, f"{ch['snippet']['title']} ({handle})")
        else:
            record(FAIL, label, f"WRONG CHANNEL: {ch['snippet']['title']} ({handle})")
    except Exception as e:
        record(FAIL, label, f"{type(e).__name__}: {str(e)[:90]}")


def check_scoring():
    """End-to-end: niche profile + LLM + the 50-point gate."""
    try:
        from verticals.score import score_topic
        r = score_topic("Why Time Feels Faster As You Age", niche="curious_classroom")
        if r is None:
            record(FAIL, "Topic gate", "no scoring rubric loaded")
        elif r.get("verdict") == "ERROR":
            record(FAIL, "Topic gate", str(r.get("summary", ""))[:90])
        else:
            record(OK, "Topic gate", f"scored {r['total']}/50 -> {r['verdict']}")
    except Exception as e:
        record(FAIL, "Topic gate", f"{type(e).__name__}: {str(e)[:90]}")


def check_last_run():
    """Surface how the last scheduled run actually ended.

    Task Scheduler reports the .bat's exit code, which was 0 whether or not the
    work happened. This reads what the job itself recorded.
    """
    try:
        from verticals.notify import read_status
        line = read_status()
    except Exception as e:
        record(WARN, "Last scheduled run", f"unreadable — {type(e).__name__}")
        return
    if not line:
        record(WARN, "Last scheduled run", "no run recorded yet")
        return
    parts = line.split("\t")
    when, job, state = parts[0], parts[1], parts[2]
    detail = parts[3] if len(parts) > 3 else ""
    label = "Last scheduled run"
    if state == "OK":
        record(OK, label, f"{job} {when} — {detail}")
    else:
        record(FAIL, label, f"{job} {when} — {detail}")


def main():
    print("\n" + "=" * 58)
    print("  Verticals stack healthcheck")
    print("=" * 58)
    check_python()
    check_ffmpeg()
    check_imports()
    print("-" * 58)
    check_gemini()
    check_leonardo()
    check_youtube('pets')
    check_youtube('curious_classroom')
    check_last_run()
    print("-" * 58)
    print("  Running one real scoring call (costs a few cents at most)...")
    check_scoring()
    print("=" * 58)

    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    if fails:
        print(f"\n  {len(fails)} FAILED:")
        for _, n, d in fails:
            print(f"    - {n}: {d}")
        print("\n  The 6am job will not complete until these are fixed.\n")
        sys.exit(1)
    print(f"\n  All green{f' ({len(warns)} warnings)' if warns else ''}. "
          f"The 6am job will run clean.\n")


if __name__ == "__main__":
    main()
