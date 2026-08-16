#!/usr/bin/env python3
"""Re-authorise YouTube upload access and verify WHICH channel got authorised.

No prompts. Uses ~/.verticals/client_secret.json unless a path is passed.

    py -3 scripts/reauth_youtube.py [path\\to\\client_secret.json]

After sign-in it calls the API and prints the channel title, handle, and ID,
so you find out immediately if you signed into the wrong Google account.
"""

import os
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

SKILL_DIR = Path.home() / ".verticals"
DEFAULT_SECRET = SKILL_DIR / "client_secret.json"

# niche -> token filename. The channel this must land on is NOT hardcoded here:
# it is read from niches/<niche>.yaml, so the profile stays the single source of
# truth and this file cannot drift out of step with it.
CHANNELS = {
    "pets":              "youtube_token.json",
    "curious_classroom": "youtube_token_curious_classroom.json",
}


def expected_channel(niche: str):
    """(channel_id, handle) the niche profile says this token must authorise.

    Returns (None, None) when the profile has no channel block, in which case
    the check is skipped rather than guessed at.
    """
    try:
        import yaml
        root = Path(__file__).resolve().parent.parent
        prof = yaml.safe_load((root / "niches" / f"{niche}.yaml").read_text(encoding="utf-8"))
        ch = (prof or {}).get("channel", {}) or {}
        return ch.get("channel_id"), ch.get("handle")
    except Exception:
        return None, None


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("Missing dependency. Run:")
        print("   py -3 -m pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    args = [a for a in sys.argv[1:] if a]
    niche = args[0] if args and args[0] in CHANNELS else "pets"
    rest = [a for a in args if a != niche]
    token_name = CHANNELS[niche]
    token_path = SKILL_DIR / token_name
    want_id, expected_handle = expected_channel(niche)
    print(f"Channel: {niche}  ->  {expected_handle or '(not pinned in profile)'}")
    secret = Path(rest[0]).expanduser() if rest else DEFAULT_SECRET
    if not secret.exists():
        print(f"client_secret.json not found at: {secret}")
        print("Download it from Google Cloud Console -> APIs & Services -> Credentials")
        print(f"and save it to {DEFAULT_SECRET}")
        sys.exit(1)

    SKILL_DIR.mkdir(parents=True, exist_ok=True)

    if token_path.exists():
        backup = token_path.with_suffix(".json.old")
        backup.write_text(token_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Previous token backed up to {backup}")

    print(f"Using client secret: {secret}")
    print("Opening your browser for Google sign-in...")
    print(f"Sign in with the Google account that owns {expected_handle},")
    print("and pick that channel if Google shows a channel chooser.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        print()
        print("WARNING: Google did not return a refresh token.")
        print("Uploads will work now but break again within the hour.")
        print("Revoke the app at https://myaccount.google.com/permissions and re-run.")

    fd = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())
    print(f"\nToken saved: {token_path}")

    # Verify which channel this token can actually post to.
    try:
        yt = build("youtube", "v3", credentials=creds)
        resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
        items = resp.get("items", [])
        if not items:
            print("\nNo channel found on this account. You signed into the wrong Google account.")
            sys.exit(2)
        ch = items[0]
        title = ch["snippet"]["title"]
        handle = ch["snippet"].get("customUrl", "(no handle)")
        subs = ch.get("statistics", {}).get("subscriberCount", "?")
        print("\n" + "=" * 52)
        print(f"  Authorised channel : {title}")
        print(f"  Handle             : {handle}")
        print(f"  Channel ID         : {ch['id']}")
        print(f"  Subscribers        : {subs}")
        print("=" * 52)
        # Compare channel IDs, not handles. A substring handle match cannot
        # tell @curiousclassroomtv from @curiousclassroomtv-z6b — two real
        # channels on this account, one verified and one not — so the old
        # check passed for either and could bless a token that uploads to the
        # empty channel.
        if want_id and ch["id"] != want_id:
            print(f"\n  WRONG CHANNEL. Expected {expected_handle} ({want_id}).")
            print(f"  You authorised {handle} ({ch['id']}).")
            print("  Re-run and pick the right channel in Google's chooser, or")
            print("  switch at https://www.youtube.com/account first.")
            print(f"  The bad token is already written to {token_path};")
            print("  re-run before uploading.")
            sys.exit(3)
        if want_id:
            print("\n  Correct channel. Uploads are live again.")
        else:
            print(f"\n  Profile pins no channel_id — authorised {handle} unchecked.")
    except SystemExit:
        raise
    except Exception as e:
        print(f"\nToken saved, but the channel check failed: {e}")
        print("Not fatal — the token is written. Verify manually before trusting a run.")


if __name__ == "__main__":
    main()
