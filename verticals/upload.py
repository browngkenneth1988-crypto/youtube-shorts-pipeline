"""YouTube API upload + thumbnail + captions."""

from pathlib import Path

from .config import get_youtube_token_path, write_secret_file
from .log import log
from .publish import assert_publishable
from .retry import with_retry


@with_retry(max_retries=2, base_delay=5.0)
def upload_to_youtube(
    video_path: Path,
    draft: dict,
    srt_path: Path = None,
    lang: str = "en",
    thumbnail_path: Path = None,
) -> str:
    """Upload video to YouTube with metadata, captions, and optional thumbnail.

    Privacy, made-for-kids, and category come from the niche's publishing policy
    (see verticals/publish.py). Default is private — an unattended pipeline never
    makes something public on its own.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    niche = draft.get("niche", "general")
    platform = draft.get("platform", "shorts")
    policy = assert_publishable(niche, platform)

    token_path = get_youtube_token_path(niche)
    creds = Credentials.from_authorized_user_file(str(token_path))
    if creds.expired:
        if creds.refresh_token:
            creds.refresh(Request())
            write_secret_file(token_path, creds.to_json())
        else:
            raise RuntimeError(
                "YouTube OAuth token is expired and has no refresh token.\n"
                "Re-run: python3 scripts/setup_youtube_oauth.py"
            )

    youtube = build("youtube", "v3", credentials=creds)

    # Refuse to upload to the wrong channel. A niche whose profile names a
    # channel_id must be authorised for exactly that channel — otherwise a
    # missing token would silently fall back to another channel's credentials
    # and publish there.
    from .niche import load_niche
    want_id = (load_niche(niche).get("channel", {}) or {}).get("channel_id")
    if want_id:
        me = youtube.channels().list(part="snippet", mine=True).execute()
        items = me.get("items") or []
        got_id = items[0]["id"] if items else None
        if got_id != want_id:
            got_name = items[0]["snippet"]["title"] if items else "no channel"
            raise RuntimeError(
                f"WRONG CHANNEL. Niche '{niche}' expects {want_id} but this token "
                f"authorises {got_name} ({got_id}). Nothing uploaded.\n"
                f"Fix: scripts\\reauth.bat {niche}"
            )
        log(f"Channel verified: {items[0]['snippet']['title']} ({got_id})")

    log(
        f"Uploading {video_path.name} "
        f"[niche: {niche}, privacy: {policy['privacy']}, "
        f"madeForKids: {policy['made_for_kids']}, category: {policy['category_id']}]"
    )

    body = {
        "snippet": {
            "title": (draft.get("youtube_title", draft["news"])[:90] + " #Shorts"),
            "description": draft.get("youtube_description", ""),
            "tags": draft.get("youtube_tags", "").split(","),
            "categoryId": policy["category_id"],
            "defaultLanguage": lang,
            "defaultAudioLanguage": lang,
        },
        "status": {
            "privacyStatus": policy["privacy"],
            "selfDeclaredMadeForKids": policy["made_for_kids"],
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            log(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    log(f"Uploaded: {url}")

    # Upload SRT if available
    if srt_path and srt_path.exists():
        try:
            youtube.captions().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "language": lang,
                        "name": lang.upper(),
                        "isDraft": False,
                    }
                },
                media_body=MediaFileUpload(str(srt_path), mimetype="application/octet-stream"),
            ).execute()
            log("Captions uploaded.")
        except Exception as e:
            log(f"Caption upload failed: {e}")

    # Upload thumbnail if available
    if thumbnail_path and thumbnail_path.exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/png"),
            ).execute()
            log("Thumbnail uploaded.")
        except Exception as e:
            log(f"Thumbnail upload failed: {e}")

    return url
