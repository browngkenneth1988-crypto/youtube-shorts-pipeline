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


LEO_PROFILE = {
    "visuals": {
        "leonardo": {"provider": "leonardo", "contrast": 3.0},
        "subjects": {"avoid": ["text or lettering"]},
        "color_palette": ["#1D3A53"],
    }
}


class TestThumbnailProviderSelection:
    """Was Gemini-only, whose image model has zero free-tier allocation, so
    every thumbnail 429'd and uploads shipped without one."""

    DRAFT = {"thumbnail_prompt": "a doorway", "youtube_title": "T",
             "job_id": "j1", "niche": "curious_classroom"}

    def test_uses_leonardo_when_niche_declares_it(self, tmp_path):
        with patch("verticals.thumbnail.load_niche", return_value=LEO_PROFILE), \
             patch("verticals.leonardo.get_leonardo_key", return_value="lk"), \
             patch("verticals.leonardo.generate_image_leonardo") as leo, \
             patch("verticals.thumbnail._generate_thumb_image") as gem, \
             patch("verticals.thumbnail._overlay_title"):
            thumbnail.generate_thumbnail(self.DRAFT, tmp_path)
        leo.assert_called_once()
        gem.assert_not_called()
        assert leo.call_args.kwargs["width"] == thumbnail.LEO_WIDTH   # 16:9
        assert leo.call_args.kwargs["height"] == thumbnail.LEO_HEIGHT

    def test_negative_prompt_passed_so_lettering_does_not_fight_the_overlay(self, tmp_path):
        with patch("verticals.thumbnail.load_niche", return_value=LEO_PROFILE), \
             patch("verticals.leonardo.get_leonardo_key", return_value="lk"), \
             patch("verticals.leonardo.generate_image_leonardo") as leo, \
             patch("verticals.thumbnail._overlay_title"):
            thumbnail.generate_thumbnail(self.DRAFT, tmp_path)
        assert "gibberish text" in leo.call_args.kwargs["negative_prompt"]

    def test_falls_back_to_gemini_without_leonardo_key(self, tmp_path):
        with patch("verticals.thumbnail.load_niche", return_value=LEO_PROFILE), \
             patch("verticals.leonardo.get_leonardo_key", return_value=""), \
             patch("verticals.leonardo.generate_image_leonardo") as leo, \
             patch("verticals.thumbnail._generate_thumb_image") as gem, \
             patch("verticals.thumbnail.get_gemini_key", return_value="gk"), \
             patch("verticals.thumbnail._overlay_title"):
            thumbnail.generate_thumbnail(self.DRAFT, tmp_path)
        leo.assert_not_called()
        gem.assert_called_once()

    def test_leonardo_failure_falls_back_to_gemini(self, tmp_path):
        with patch("verticals.thumbnail.load_niche", return_value=LEO_PROFILE), \
             patch("verticals.leonardo.get_leonardo_key", return_value="lk"), \
             patch("verticals.leonardo.generate_image_leonardo",
                   side_effect=RuntimeError("leonardo down")), \
             patch("verticals.thumbnail._generate_thumb_image") as gem, \
             patch("verticals.thumbnail.get_gemini_key", return_value="gk"), \
             patch("verticals.thumbnail._overlay_title"):
            thumbnail.generate_thumbnail(self.DRAFT, tmp_path)
        gem.assert_called_once()

    def test_both_providers_failing_still_yields_a_thumbnail(self, tmp_path):
        with patch("verticals.thumbnail.load_niche", return_value=LEO_PROFILE), \
             patch("verticals.leonardo.get_leonardo_key", return_value="lk"), \
             patch("verticals.leonardo.generate_image_leonardo", side_effect=RuntimeError("x")), \
             patch("verticals.thumbnail._generate_thumb_image", side_effect=RuntimeError("y")), \
             patch("verticals.thumbnail.get_gemini_key", return_value="gk"):
            final = thumbnail.generate_thumbnail(self.DRAFT, tmp_path)
        # A flat brand-coloured card with the title still beats YouTube
        # picking an arbitrary frame out of the video.
        assert final.exists()
        assert Image.open(final).size == (THUMB_WIDTH, THUMB_HEIGHT)

    def test_niche_read_from_draft_when_not_passed(self, tmp_path):
        with patch("verticals.thumbnail.load_niche", return_value=LEO_PROFILE) as ln, \
             patch("verticals.leonardo.get_leonardo_key", return_value="lk"), \
             patch("verticals.leonardo.generate_image_leonardo"), \
             patch("verticals.thumbnail._overlay_title"):
            thumbnail.generate_thumbnail(self.DRAFT, tmp_path)
        ln.assert_called_once_with("curious_classroom")


class TestFallbackThumb:
    def test_uses_first_palette_colour(self, tmp_path):
        out = tmp_path / "f.png"
        thumbnail._fallback_thumb(out, {"visuals": {"color_palette": ["#FF0000"]}})
        assert Image.open(out).getpixel((10, 10)) == (255, 0, 0)

    def test_survives_a_malformed_palette(self, tmp_path):
        out = tmp_path / "f.png"
        thumbnail._fallback_thumb(out, {"visuals": {"color_palette": ["notacolour"]}})
        assert Image.open(out).size == (THUMB_WIDTH, THUMB_HEIGHT)

    def test_survives_no_palette(self, tmp_path):
        out = tmp_path / "f.png"
        thumbnail._fallback_thumb(out, {})
        assert Image.open(out).size == (THUMB_WIDTH, THUMB_HEIGHT)


class TestOverlayFontSizing:
    def test_title_is_rendered_at_a_readable_size(self, tmp_path):
        """Regression: the font candidates were macOS+Linux only, so Windows
        fell through to load_default(), a bitmap font that ignores font_size.
        Thumbnails shipped with an unreadable ~10px title."""
        src = tmp_path / "raw.png"
        Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), (0, 0, 0)).save(src)
        out = tmp_path / "out.png"
        thumbnail._overlay_title(src, "A Readable Title", out)

        # Measure the painted text: count non-black rows in the lower third.
        img = Image.open(out).convert("L")
        crop = img.crop((0, THUMB_HEIGHT * 2 // 3, THUMB_WIDTH, THUMB_HEIGHT))
        rows_with_text = sum(
            1 for y in range(crop.height)
            if any(crop.getpixel((x, y)) > 128 for x in range(0, crop.width, 4))
        )
        # 64pt caps are ~45px tall; the old bitmap default painted under 12.
        assert rows_with_text > 25, f"title looks too small ({rows_with_text}px tall)"
