"""Tests for verticals/thumbnail.py — Gemini image, text overlay, word wrap."""

import base64
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw, ImageFont

from verticals import thumbnail
from verticals.thumbnail import THUMB_HEIGHT, THUMB_WIDTH


def _png_bytes(size=(320, 180), color=(30, 40, 50)):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class TestGenerateThumbImage:
    def test_writes_decoded_image(self, tmp_path):
        raw = _png_bytes()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"inlineData": {"data": base64.b64encode(raw).decode()}}]}}
            ]
        }
        out = tmp_path / "raw.png"
        with patch("verticals.thumbnail.requests.post", return_value=resp):
            thumbnail._generate_thumb_image("prompt", out, "key")
        assert out.read_bytes() == raw

    def test_non_200_raises(self, tmp_path):
        resp = MagicMock()
        resp.status_code = 500
        resp.json.return_value = {"error": {"message": "server error"}}
        with patch("verticals.thumbnail.requests.post", return_value=resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="server error"):
                thumbnail._generate_thumb_image("x", tmp_path / "o.png", "key")

    def test_no_image_raises(self, tmp_path):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"candidates": [{"content": {"parts": []}}]}
        with patch("verticals.thumbnail.requests.post", return_value=resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="No image"):
                thumbnail._generate_thumb_image("x", tmp_path / "o.png", "key")


class TestWrapText:
    def _draw(self):
        return ImageDraw.Draw(Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT)))

    def test_short_text_single_line(self):
        font = ImageFont.load_default()
        lines = thumbnail._wrap_text(self._draw(), "Short", font, 1000)
        assert lines == ["Short"]

    def test_long_text_wraps(self):
        font = ImageFont.load_default()
        text = "word " * 40
        lines = thumbnail._wrap_text(self._draw(), text.strip(), font, 200)
        assert len(lines) > 1

    def test_empty_text(self):
        font = ImageFont.load_default()
        assert thumbnail._wrap_text(self._draw(), "", font, 500) == []


class TestOverlayTitle:
    def test_output_is_thumbnail_sized(self, tmp_path):
        raw = tmp_path / "raw.png"
        Image.new("RGB", (400, 300), (100, 100, 100)).save(raw)
        out = tmp_path / "final.png"
        thumbnail._overlay_title(raw, "My Great Video Title", out)
        assert out.exists()
        assert Image.open(out).size == (THUMB_WIDTH, THUMB_HEIGHT)


class TestGenerateThumbnail:
    def test_end_to_end_with_mocked_generation(self, tmp_path):
        def fake_gen(prompt, out_path, api_key):
            Image.new("RGB", (320, 180), (12, 34, 56)).save(out_path)

        draft = {
            "thumbnail_prompt": "a dramatic scene",
            "youtube_title": "Big News Today",
            "job_id": "job42",
        }
        with patch("verticals.thumbnail.get_gemini_key", return_value="key"), \
             patch("verticals.thumbnail._generate_thumb_image", side_effect=fake_gen):
            final = thumbnail.generate_thumbnail(draft, tmp_path)

        assert final == tmp_path / "thumb_job42.png"
        assert Image.open(final).size == (THUMB_WIDTH, THUMB_HEIGHT)

    def test_falls_back_to_news_for_title(self, tmp_path):
        def fake_gen(prompt, out_path, api_key):
            Image.new("RGB", (320, 180), (0, 0, 0)).save(out_path)

        draft = {"news": "headline only"}  # no youtube_title/job_id
        with patch("verticals.thumbnail.get_gemini_key", return_value="key"), \
             patch("verticals.thumbnail._generate_thumb_image", side_effect=fake_gen):
            final = thumbnail.generate_thumbnail(draft, tmp_path)
        # job_id defaults to "unknown".
        assert final == tmp_path / "thumb_unknown.png"
        assert final.exists()
