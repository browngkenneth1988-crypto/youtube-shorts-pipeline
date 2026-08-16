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

# niche -> (token filename, expected channel handle)
CHANNELS = {
    "pets":              ("youtube_token.json",                   "@LifeWithOttoTV"),
    "curious_classroom": ("youtube_token_curious_classroom.json", "@CuriousClassroomTV"),
}


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
    token_name, expected_handle = CHANNELS[niche]
    token_path = SKILL_DIR / token_name
    print(f"Channel: {niche}  ->  {expected_handle}")
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
        if expected_handle.lower().lstrip("@") not in str(handle).lower().lstrip("@"):
            print(f"\n  WRONG CHANNEL. Expected {expected_handle}.")
            print("  Re-run and pick the right account, or switch channel at")
            print("  https://www.youtube.com/account before re-running.")
            sys.exit(3)
        print("\n  Correct channel. Uploads are live again.")
    except SystemExit:
        raise
    except Exception as e:
        print(f"\nToken saved, but the channel check failed: {e}")
        print("Not fatal — the token is written. Verify manually before trusting a run.")


if __name__ == "__main__":
    main()
