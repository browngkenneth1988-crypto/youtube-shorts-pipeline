"""Tests for verticals/broll.py — Gemini image generation, fallback, Ken Burns."""

import base64
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from verticals import broll
from verticals.config import VIDEO_WIDTH, VIDEO_HEIGHT


def _png_bytes(size=(64, 64), color=(10, 20, 30)):
    from io import BytesIO
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class TestGenerateImageGemini:
    def test_writes_decoded_image(self, tmp_path):
        raw = _png_bytes()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"inlineData": {"data": base64.b64encode(raw).decode()}}]}}
            ]
        }
        out = tmp_path / "img.png"
        with patch("verticals.broll.requests.post", return_value=resp):
            broll._generate_image_gemini("a cat", out, "key")
        assert out.read_bytes() == raw

    def test_non_200_raises_with_error_message(self, tmp_path):
        resp = MagicMock()
        resp.status_code = 400
        resp.json.return_value = {"error": {"message": "bad prompt"}}
        with patch("verticals.broll.requests.post", return_value=resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="bad prompt"):
                broll._generate_image_gemini("x", tmp_path / "o.png", "key")

    def test_no_image_part_raises(self, tmp_path):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "no image"}]}}]}
        with patch("verticals.broll.requests.post", return_value=resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="No image"):
                broll._generate_image_gemini("x", tmp_path / "o.png", "key")


class TestFallbackFrame:
    def test_creates_portrait_frame(self, tmp_path):
        path = broll._fallback_frame(0, tmp_path)
        assert path.exists()
        assert Image.open(path).size == (VIDEO_WIDTH, VIDEO_HEIGHT)

    def test_color_varies_by_index(self, tmp_path):
        p0 = broll._fallback_frame(0, tmp_path)
        p1 = broll._fallback_frame(1, tmp_path)
        assert Image.open(p0).getpixel((0, 0)) != Image.open(p1).getpixel((0, 0))


class TestGenerateBroll:
    def test_success_produces_portrait_frames(self, tmp_path):
        def fake_gen(prompt, out_path, api_key):
            Image.new("RGB", (200, 100), (5, 5, 5)).save(out_path)

        with patch("verticals.broll.get_gemini_key", return_value="key"), \
             patch("verticals.broll._generate_image_gemini", side_effect=fake_gen):
            frames = broll.generate_broll(["p1", "p2", "p3"], tmp_path)

        assert len(frames) == 3
        for f in frames:
            assert Image.open(f).size == (VIDEO_WIDTH, VIDEO_HEIGHT)

    def test_truncates_to_three_prompts(self, tmp_path):
        def fake_gen(prompt, out_path, api_key):
            Image.new("RGB", (200, 100), (5, 5, 5)).save(out_path)

        with patch("verticals.broll.get_gemini_key", return_value="key"), \
             patch("verticals.broll._generate_image_gemini", side_effect=fake_gen):
            frames = broll.generate_broll(["p1", "p2", "p3", "p4", "p5"], tmp_path)
        assert len(frames) == 3

    def test_falls_back_on_generation_failure(self, tmp_path):
        with patch("verticals.broll.get_gemini_key", return_value="key"), \
             patch("verticals.broll._generate_image_gemini", side_effect=RuntimeError("api down")):
            frames = broll.generate_broll(["p1"], tmp_path)
        assert len(frames) == 1
        # Fallback frame is a solid portrait image.
        assert Image.open(frames[0]).size == (VIDEO_WIDTH, VIDEO_HEIGHT)


class TestAnimateFrame:
    def _vf_for(self, effect, tmp_path):
        with patch("verticals.broll.run_cmd") as mock_run:
            broll.animate_frame(tmp_path / "in.png", tmp_path / "out.mp4", 2.0, effect)
        cmd = mock_run.call_args.args[0]
        return cmd[cmd.index("-vf") + 1]

    def test_zoom_in_expression(self, tmp_path):
        vf = self._vf_for("zoom_in", tmp_path)
        assert "zoompan" in vf and "1.12-0.12*on" in vf

    def test_pan_right_expression(self, tmp_path):
        vf = self._vf_for("pan_right", tmp_path)
        assert "0.15*iw*on" in vf

    def test_zoom_out_is_default(self, tmp_path):
        vf = self._vf_for("anything_else", tmp_path)
        assert "1.0+0.12*on" in vf

    def test_ffmpeg_invocation(self, tmp_path):
        with patch("verticals.broll.run_cmd") as mock_run:
            broll.animate_frame(tmp_path / "in.png", tmp_path / "out.mp4", 3.0)
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "ffmpeg"
        assert "-loop" in cmd
        assert str(tmp_path / "in.png") in cmd
        assert "3.0" in cmd  # duration passed to -t
