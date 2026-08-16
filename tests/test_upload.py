"""Tests for verticals/upload.py — YouTube upload with mocked Google API.

upload.py imports the google client libraries lazily inside the function, so
we inject mock modules into sys.modules rather than requiring the real
(heavyweight, network-bound) dependencies to be installed.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from verticals import upload


@pytest.fixture
def google_api():
    """Inject mock google client modules and wire up a fake YouTube service.

    Yields a namespace of the key mocks so tests can assert on calls and
    tweak behavior (expired creds, upload progress, API errors).
    """
    creds_cls = MagicMock(name="Credentials")
    request_cls = MagicMock(name="Request")
    build_fn = MagicMock(name="build")
    media_upload_cls = MagicMock(name="MediaFileUpload")

    # Default credentials: valid, not expired.
    creds = MagicMock(name="creds")
    creds.expired = False
    creds.refresh_token = "refresh-xyz"
    creds.to_json.return_value = '{"token": "new"}'
    creds_cls.from_authorized_user_file.return_value = creds

    # Fake YouTube service: youtube.videos().insert(...).next_chunk() -> response
    youtube = MagicMock(name="youtube")
    insert_req = MagicMock(name="insert_req")
    insert_req.next_chunk.return_value = (None, {"id": "VID123"})
    youtube.videos.return_value.insert.return_value = insert_req
    build_fn.return_value = youtube

    modules = {
        "google": MagicMock(),
        "google.oauth2": MagicMock(),
        "google.oauth2.credentials": MagicMock(Credentials=creds_cls),
        "google.auth": MagicMock(),
        "google.auth.transport": MagicMock(),
        "google.auth.transport.requests": MagicMock(Request=request_cls),
        "googleapiclient": MagicMock(),
        "googleapiclient.discovery": MagicMock(build=build_fn),
        "googleapiclient.http": MagicMock(MediaFileUpload=media_upload_cls),
    }

    ns = MagicMock(name="google_api_ns")
    ns.creds_cls = creds_cls
    ns.creds = creds
    ns.request_cls = request_cls
    ns.build_fn = build_fn
    ns.media_upload_cls = media_upload_cls
    ns.youtube = youtube
    ns.insert_req = insert_req

    with patch.dict(sys.modules, modules):
        with patch("verticals.upload.get_youtube_token_path", return_value="/tmp/tok.json"), \
             patch("verticals.upload.write_secret_file") as write_secret:
            ns.write_secret = write_secret
            yield ns


@pytest.fixture
def video_file(tmp_path):
    p = tmp_path / "final.mp4"
    p.write_bytes(b"fake video")
    return p


@pytest.fixture
def basic_draft():
    return {
        "news": "Something happened",
        "youtube_title": "A Great Title",
        "youtube_description": "The description.",
        "youtube_tags": "ai,tech,news",
    }


class TestUploadHappyPath:
    def test_returns_youtube_url(self, google_api, video_file, basic_draft):
        url = upload.upload_to_youtube(video_file, basic_draft)
        assert url == "https://youtu.be/VID123"

    def test_builds_snippet_body_correctly(self, google_api, video_file, basic_draft):
        upload.upload_to_youtube(video_file, basic_draft, lang="es")
        _, kwargs = google_api.youtube.videos.return_value.insert.call_args
        body = kwargs["body"]
        # The " #Shorts" suffix is deliberate (ed8bd32) — it is what tells
        # YouTube to file the upload as a Short rather than a regular video.
        assert body["snippet"]["title"] == "A Great Title #Shorts"
        assert body["snippet"]["description"] == "The description."
        assert body["snippet"]["tags"] == ["ai", "tech", "news"]
        assert body["snippet"]["defaultLanguage"] == "es"
        assert body["status"]["privacyStatus"] == "private"
        assert body["status"]["selfDeclaredMadeForKids"] is False

    def test_title_stays_within_youtube_limit(self, google_api, video_file):
        # YouTube rejects titles over 100 chars. The body is cut at 90 so the
        # 8-char " #Shorts" suffix always survives truncation — asserting the
        # invariant rather than the exact 98, which is an implementation detail.
        draft = {"news": "n", "youtube_title": "T" * 250}
        upload.upload_to_youtube(video_file, draft)
        _, kwargs = google_api.youtube.videos.return_value.insert.call_args
        title = kwargs["body"]["snippet"]["title"]
        assert len(title) <= 100
        assert title.endswith(" #Shorts")

    def test_title_falls_back_to_news(self, google_api, video_file):
        draft = {"news": "Fallback headline"}
        upload.upload_to_youtube(video_file, draft)
        _, kwargs = google_api.youtube.videos.return_value.insert.call_args
        assert kwargs["body"]["snippet"]["title"] == "Fallback headline #Shorts"

    def test_progress_status_is_handled(self, google_api, video_file, basic_draft):
        # First next_chunk reports progress, second returns the response.
        status = MagicMock()
        status.progress.return_value = 0.5
        google_api.insert_req.next_chunk.side_effect = [
            (status, None),
            (None, {"id": "VID999"}),
        ]
        url = upload.upload_to_youtube(video_file, basic_draft)
        assert url == "https://youtu.be/VID999"
        assert google_api.insert_req.next_chunk.call_count == 2


class TestCredentialRefresh:
    def test_expired_creds_with_refresh_token_refreshes(self, google_api, video_file, basic_draft):
        google_api.creds.expired = True
        google_api.creds.refresh_token = "refresh-xyz"
        upload.upload_to_youtube(video_file, basic_draft)
        google_api.creds.refresh.assert_called_once()
        # Refreshed token is persisted back to disk.
        google_api.write_secret.assert_called_once()

    def test_expired_creds_without_refresh_token_raises(self, google_api, video_file, basic_draft):
        google_api.creds.expired = True
        google_api.creds.refresh_token = None
        # upload_to_youtube is wrapped in with_retry; patch sleep to keep it fast.
        with patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="expired and has no refresh token"):
                upload.upload_to_youtube(video_file, basic_draft)

    def test_valid_creds_not_refreshed(self, google_api, video_file, basic_draft):
        google_api.creds.expired = False
        upload.upload_to_youtube(video_file, basic_draft)
        google_api.creds.refresh.assert_not_called()
        google_api.write_secret.assert_not_called()


class TestCaptionsAndThumbnail:
    def test_srt_uploaded_when_present(self, google_api, video_file, basic_draft, tmp_path):
        srt = tmp_path / "captions.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
        upload.upload_to_youtube(video_file, basic_draft, srt_path=srt)
        google_api.youtube.captions.return_value.insert.assert_called_once()

    def test_srt_skipped_when_missing(self, google_api, video_file, basic_draft, tmp_path):
        srt = tmp_path / "does_not_exist.srt"
        upload.upload_to_youtube(video_file, basic_draft, srt_path=srt)
        google_api.youtube.captions.return_value.insert.assert_not_called()

    def test_srt_skipped_when_none(self, google_api, video_file, basic_draft):
        upload.upload_to_youtube(video_file, basic_draft, srt_path=None)
        google_api.youtube.captions.return_value.insert.assert_not_called()

    def test_thumbnail_uploaded_when_present(self, google_api, video_file, basic_draft, tmp_path):
        thumb = tmp_path / "thumb.png"
        thumb.write_bytes(b"\x89PNG")
        upload.upload_to_youtube(video_file, basic_draft, thumbnail_path=thumb)
        google_api.youtube.thumbnails.return_value.set.assert_called_once()

    def test_thumbnail_skipped_when_missing(self, google_api, video_file, basic_draft, tmp_path):
        thumb = tmp_path / "nope.png"
        upload.upload_to_youtube(video_file, basic_draft, thumbnail_path=thumb)
        google_api.youtube.thumbnails.return_value.set.assert_not_called()

    def test_caption_failure_does_not_break_upload(self, google_api, video_file, basic_draft, tmp_path):
        srt = tmp_path / "captions.srt"
        srt.write_text("subtitle")
        google_api.youtube.captions.return_value.insert.side_effect = RuntimeError("quota")
        # Caption errors are swallowed; the video URL is still returned.
        url = upload.upload_to_youtube(video_file, basic_draft, srt_path=srt)
        assert url == "https://youtu.be/VID123"

    def test_thumbnail_failure_does_not_break_upload(self, google_api, video_file, basic_draft, tmp_path):
        thumb = tmp_path / "thumb.png"
        thumb.write_bytes(b"\x89PNG")
        google_api.youtube.thumbnails.return_value.set.side_effect = RuntimeError("bad image")
        url = upload.upload_to_youtube(video_file, basic_draft, thumbnail_path=thumb)
        assert url == "https://youtu.be/VID123"
