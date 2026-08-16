"""Tests for verticals/broll.py — Gemini image generation, fallback, Ken Burns."""

import base64
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from verticals import broll
from verticals.config import VIDEO_HEIGHT, VIDEO_WIDTH


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


class TestGeminiErrorBodyParsing:
    def test_unparseable_error_body_falls_back_to_text(self, tmp_path):
        # A 502 from a proxy is usually HTML, so .json() raises and the raw
        # text has to carry the diagnosis instead.
        resp = MagicMock()
        resp.status_code = 502
        resp.json.side_effect = ValueError("not json")
        resp.text = "<html>Bad Gateway</html>"
        with patch("verticals.broll.requests.post", return_value=resp):
            with pytest.raises(RuntimeError, match="Bad Gateway"):
                broll._generate_image_gemini("p", tmp_path / "o.png", "key")

    def test_api_key_sent_as_header_not_query_param(self, tmp_path):
        raw = _png_bytes()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"inlineData": {"data": base64.b64encode(raw).decode()}}]}}
            ]
        }
        with patch("verticals.broll.requests.post", return_value=resp) as post:
            broll._generate_image_gemini("p", tmp_path / "o.png", "sekret")
        assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "sekret"
        assert "sekret" not in post.call_args.args[0]


class TestBurnQuoteOnFrame:
    def _frame(self, tmp_path):
        p = tmp_path / "frame.png"
        Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (5, 5, 5)).save(p)
        return p

    def test_modifies_the_image_in_place(self, tmp_path):
        p = self._frame(tmp_path)
        before = p.read_bytes()
        broll.burn_quote_on_frame(p, "Be kind to yourself today")
        assert p.read_bytes() != before

    def test_output_stays_rgb_and_same_size(self, tmp_path):
        p = self._frame(tmp_path)
        broll.burn_quote_on_frame(p, "A quote")
        img = Image.open(p)
        assert img.mode == "RGB"
        assert img.size == (VIDEO_WIDTH, VIDEO_HEIGHT)

    @pytest.mark.parametrize("position", ["top", "lower_third", "center", "unrecognised"])
    def test_all_positions_render(self, tmp_path, position):
        # An unknown position must fall through to centre rather than raise.
        p = self._frame(tmp_path)
        broll.burn_quote_on_frame(p, "Some words here", position=position)
        assert Image.open(p).size == (VIDEO_WIDTH, VIDEO_HEIGHT)

    def test_long_quote_is_wrapped(self, tmp_path):
        p = self._frame(tmp_path)
        captured = []
        real_wrap = broll.textwrap.wrap

        def spy(*a, **k):
            out = real_wrap(*a, **k)
            captured.append(out)
            return out

        with patch("verticals.broll.textwrap.wrap", side_effect=spy):
            broll.burn_quote_on_frame(p, "word " * 60)
        assert len(captured[0]) > 1

    def test_falls_back_through_font_candidates(self, tmp_path):
        # Neither arial nor DejaVu present — must still render via the default.
        # load_default has to be patched too: in current Pillow it calls
        # truetype() internally, so stubbing truetype alone breaks the very
        # fallback under test.
        p = self._frame(tmp_path)
        real_default = broll.ImageFont.load_default()
        with patch("verticals.broll.ImageFont.truetype", side_effect=OSError("no font")), \
             patch("verticals.broll.ImageFont.load_default", return_value=real_default):
            broll.burn_quote_on_frame(p, "A quote")
        assert Image.open(p).mode == "RGB"

    def test_uses_dejavu_when_arial_missing(self, tmp_path):
        p = self._frame(tmp_path)
        real = broll.ImageFont.load_default()
        with patch("verticals.broll.ImageFont.truetype",
                   side_effect=[OSError("no arial"), real]) as tt:
            broll.burn_quote_on_frame(p, "A quote")
        assert tt.call_count == 2
        assert "DejaVu" in tt.call_args_list[1].args[0]


class TestGetReferenceImages:
    def test_empty_when_niche_has_no_character(self):
        with patch("verticals.broll.load_niche", return_value={}):
            assert broll._get_reference_images("general") == []

    def test_returns_only_existing_files(self, tmp_path):
        present = tmp_path / "otto.png"
        present.write_bytes(b"x")
        profile = {"character": {"reference_images": ["otto.png", "missing.png"]}}
        with patch("verticals.broll.load_niche", return_value=profile), \
             patch("verticals.broll.NICHES_DIR", tmp_path / "niches"):
            assert broll._get_reference_images("pets") == [present]


class TestGenerateBrollLeonardoPath:
    LEO_PROFILE = {"visuals": {"leonardo": {"provider": "leonardo", "init_strength": 0.5}}}

    def test_uses_leonardo_when_configured_and_keyed(self, tmp_path):
        with patch("verticals.broll.load_niche", return_value=self.LEO_PROFILE), \
             patch("verticals.broll._get_reference_images", return_value=[]), \
             patch("verticals.leonardo.get_leonardo_key", return_value="lk"), \
             patch("verticals.leonardo.generate_image_leonardo") as gen, \
             patch("verticals.broll._resize_to_portrait"), \
             patch("verticals.broll._generate_image_gemini") as gemini:
            frames = broll.generate_broll(["p1"], tmp_path, niche="pets")
        gen.assert_called_once()
        gemini.assert_not_called()
        assert frames == [tmp_path / "broll_0.png"]
        assert gen.call_args.kwargs["init_strength"] == 0.5

    def test_alternates_reference_images(self, tmp_path):
        refs = [tmp_path / "a.png", tmp_path / "b.png"]
        with patch("verticals.broll.load_niche", return_value=self.LEO_PROFILE), \
             patch("verticals.broll._get_reference_images", return_value=refs), \
             patch("verticals.leonardo.get_leonardo_key", return_value="lk"), \
             patch("verticals.leonardo.generate_image_leonardo") as gen, \
             patch("verticals.broll._resize_to_portrait"):
            broll.generate_broll(["p1", "p2", "p3"], tmp_path, niche="pets")
        used = [c.kwargs["reference_image_path"] for c in gen.call_args_list]
        assert used == [refs[0], refs[1], refs[0]]

    def test_falls_back_to_gemini_without_leonardo_key(self, tmp_path):
        with patch("verticals.broll.load_niche", return_value=self.LEO_PROFILE), \
             patch("verticals.broll._get_reference_images", return_value=[]), \
             patch("verticals.leonardo.get_leonardo_key", return_value=""), \
             patch("verticals.leonardo.generate_image_leonardo") as gen, \
             patch("verticals.broll.get_gemini_key", return_value="gk"), \
             patch("verticals.broll._generate_image_gemini") as gemini, \
             patch("verticals.broll._resize_to_portrait"):
            broll.generate_broll(["p1"], tmp_path, niche="pets")
        gen.assert_not_called()
        gemini.assert_called_once()

    def test_leonardo_failure_falls_back_to_gemini(self, tmp_path):
        with patch("verticals.broll.load_niche", return_value=self.LEO_PROFILE), \
             patch("verticals.broll._get_reference_images", return_value=[]), \
             patch("verticals.leonardo.get_leonardo_key", return_value="lk"), \
             patch("verticals.leonardo.generate_image_leonardo",
                   side_effect=RuntimeError("leonardo down")), \
             patch("verticals.broll.get_gemini_key", return_value="gk"), \
             patch("verticals.broll._generate_image_gemini") as gemini, \
             patch("verticals.broll._resize_to_portrait"):
            frames = broll.generate_broll(["p1"], tmp_path, niche="pets")
        gemini.assert_called_once()
        assert frames == [tmp_path / "broll_0.png"]

    def test_both_providers_failing_yields_fallback_frame(self, tmp_path):
        with patch("verticals.broll.load_niche", return_value=self.LEO_PROFILE), \
             patch("verticals.broll._get_reference_images", return_value=[]), \
             patch("verticals.leonardo.get_leonardo_key", return_value="lk"), \
             patch("verticals.leonardo.generate_image_leonardo", side_effect=RuntimeError("x")), \
             patch("verticals.broll.get_gemini_key", return_value="gk"), \
             patch("verticals.broll._generate_image_gemini", side_effect=RuntimeError("y")):
            frames = broll.generate_broll(["p1"], tmp_path, niche="pets")
        # Graceful degradation: the pipeline still gets a usable frame.
        assert frames[0].exists()
        assert Image.open(frames[0]).size == (VIDEO_WIDTH, VIDEO_HEIGHT)
