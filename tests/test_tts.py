"""Tests for verticals/tts.py — provider resolution, routing, fallbacks."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from verticals import tts


# --------------------------------------------------------------------------- #
# get_tts_provider
# --------------------------------------------------------------------------- #
class TestGetTtsProvider:
    def test_explicit_name_lowercased(self):
        assert tts.get_tts_provider("ElevenLabs") == "elevenlabs"

    def test_auto_falls_through_to_env(self, monkeypatch):
        monkeypatch.setenv("TTS_PROVIDER", "say")
        assert tts.get_tts_provider("auto") == "say"

    def test_env_used_when_no_name(self, monkeypatch):
        monkeypatch.setenv("TTS_PROVIDER", "edge")
        assert tts.get_tts_provider(None) == "edge"

    def test_config_used(self, monkeypatch):
        monkeypatch.delenv("TTS_PROVIDER", raising=False)
        with patch("verticals.config.load_config", return_value={"TTS_PROVIDER": "elevenlabs"}):
            assert tts.get_tts_provider(None) == "elevenlabs"

    # Autodetect tries `import edge_tts` first, so these three have to force
    # that import to fail. They used to rely on edge-tts simply being absent
    # from the environment — true in CI, false on any dev box that installed
    # requirements.txt, where all three failed. Setting the sys.modules entry
    # to None makes the import raise ImportError deterministically.
    @staticmethod
    def _no_edge(monkeypatch):
        monkeypatch.setitem(sys.modules, "edge_tts", None)

    def test_autodetect_elevenlabs_when_no_edge(self, monkeypatch):
        self._no_edge(monkeypatch)
        monkeypatch.delenv("TTS_PROVIDER", raising=False)
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.tts.get_elevenlabs_key", return_value="k"):
            assert tts.get_tts_provider(None) == "elevenlabs"

    def test_autodetect_edge_wins_when_importable(self, monkeypatch):
        # The other side of the branch: with edge_tts present it takes priority
        # over a configured ElevenLabs key.
        monkeypatch.setitem(sys.modules, "edge_tts", MagicMock())
        monkeypatch.delenv("TTS_PROVIDER", raising=False)
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.tts.get_elevenlabs_key", return_value="k"):
            assert tts.get_tts_provider(None) == "edge"

    def test_autodetect_say_last_resort(self, monkeypatch):
        self._no_edge(monkeypatch)
        monkeypatch.delenv("TTS_PROVIDER", raising=False)
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.tts.get_elevenlabs_key", return_value=""), \
             patch("shutil.which", return_value="/usr/bin/say"):
            assert tts.get_tts_provider(None) == "say"

    def test_raises_when_nothing_available(self, monkeypatch):
        self._no_edge(monkeypatch)
        monkeypatch.delenv("TTS_PROVIDER", raising=False)
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.tts.get_elevenlabs_key", return_value=""), \
             patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="No TTS provider available"):
                tts.get_tts_provider(None)


# --------------------------------------------------------------------------- #
# generate_voiceover routing + fallbacks
# --------------------------------------------------------------------------- #
class TestGenerateVoiceoverRouting:
    def test_edge_success(self, tmp_path):
        with patch("verticals.tts.get_tts_provider", return_value="edge"), \
             patch("verticals.tts._generate_edge_tts", return_value=Path("/x/edge.mp3")) as edge:
            out = tts.generate_voiceover("hi", tmp_path)
        assert out == Path("/x/edge.mp3")
        edge.assert_called_once()

    def test_edge_failure_falls_back_to_elevenlabs(self, tmp_path):
        with patch("verticals.tts.get_tts_provider", return_value="edge"), \
             patch("verticals.tts._generate_edge_tts", side_effect=RuntimeError("no net")), \
             patch("verticals.tts.get_elevenlabs_key", return_value="k"), \
             patch("verticals.tts._generate_elevenlabs", return_value=Path("/x/el.mp3")) as el:
            out = tts.generate_voiceover("hi", tmp_path)
        assert out == Path("/x/el.mp3")
        el.assert_called_once()

    def test_edge_failure_falls_back_to_say_without_key(self, tmp_path, monkeypatch):
        # The last-resort branch is platform-dependent, so pin the platform
        # instead of inheriting the host's. On Windows this routes to pyttsx3.
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch("verticals.tts.get_tts_provider", return_value="edge"), \
             patch("verticals.tts._generate_edge_tts", side_effect=RuntimeError("no net")), \
             patch("verticals.tts.get_elevenlabs_key", return_value=""), \
             patch("verticals.tts._generate_say", return_value=Path("/x/say.mp3")) as say:
            out = tts.generate_voiceover("hi", tmp_path)
        assert out == Path("/x/say.mp3")
        say.assert_called_once()

    def test_edge_failure_falls_back_to_pyttsx3_on_windows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        with patch("verticals.tts.get_tts_provider", return_value="edge"), \
             patch("verticals.tts._generate_edge_tts", side_effect=RuntimeError("no net")), \
             patch("verticals.tts.get_elevenlabs_key", return_value=""), \
             patch("verticals.tts._generate_pyttsx3", return_value=Path("/x/win.mp3")) as win:
            out = tts.generate_voiceover("hi", tmp_path)
        assert out == Path("/x/win.mp3")
        win.assert_called_once()

    def test_elevenlabs_success(self, tmp_path):
        with patch("verticals.tts.get_tts_provider", return_value="elevenlabs"), \
             patch("verticals.tts._generate_elevenlabs", return_value=Path("/x/el.mp3")) as el:
            out = tts.generate_voiceover("hi", tmp_path, voice_config={"voice_id": "v1"})
        assert out == Path("/x/el.mp3")
        assert el.call_args.kwargs["voice_id"] == "v1"

    def test_elevenlabs_failure_falls_back_to_say(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch("verticals.tts.get_tts_provider", return_value="elevenlabs"), \
             patch("verticals.tts._generate_elevenlabs", side_effect=RuntimeError("402")), \
             patch("verticals.tts._generate_say", return_value=Path("/x/say.mp3")) as say:
            out = tts.generate_voiceover("hi", tmp_path)
        assert out == Path("/x/say.mp3")
        say.assert_called_once()

    def test_say_provider(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch("verticals.tts.get_tts_provider", return_value="say"), \
             patch("verticals.tts._generate_say", return_value=Path("/x/say.mp3")) as say:
            out = tts.generate_voiceover("hi", tmp_path)
        assert out == Path("/x/say.mp3")
        say.assert_called_once()

    def test_say_provider_routes_to_pyttsx3_on_windows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        with patch("verticals.tts.get_tts_provider", return_value="say"), \
             patch("verticals.tts._generate_pyttsx3", return_value=Path("/x/win.mp3")) as win:
            out = tts.generate_voiceover("hi", tmp_path)
        assert out == Path("/x/win.mp3")
        win.assert_called_once()

    def test_pyttsx3_missing_module_gives_actionable_error(self, tmp_path, monkeypatch):
        # Regression guard: this used to surface as a bare ModuleNotFoundError
        # and kill the scheduled run instead of explaining the fix.
        monkeypatch.setitem(sys.modules, "pyttsx3", None)
        with pytest.raises(RuntimeError, match="pip install pyttsx3"):
            tts._generate_pyttsx3("hi", tmp_path)

    def test_unknown_provider_raises(self, tmp_path):
        with patch("verticals.tts.get_tts_provider", return_value="bogus"):
            with pytest.raises(ValueError, match="Unknown TTS provider"):
                tts.generate_voiceover("hi", tmp_path)


# --------------------------------------------------------------------------- #
# ElevenLabs internals
# --------------------------------------------------------------------------- #
class TestElevenLabs:
    def test_call_returns_content(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"audio-bytes"
        with patch("verticals.tts.requests.post", return_value=resp):
            assert tts._call_elevenlabs("hi", "vid", "key") == b"audio-bytes"

    def test_call_non_200_raises(self):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "unauthorized"
        with patch("verticals.tts.requests.post", return_value=resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="ElevenLabs 401"):
                tts._call_elevenlabs("hi", "vid", "key")

    def test_generate_requires_key(self, tmp_path):
        with patch("verticals.tts.get_elevenlabs_key", return_value=""):
            with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY not set"):
                tts._generate_elevenlabs("hi", tmp_path, "en")

    def test_generate_writes_audio(self, tmp_path):
        with patch("verticals.tts.get_elevenlabs_key", return_value="k"), \
             patch("verticals.tts._call_elevenlabs", return_value=b"mp3data"):
            out = tts._generate_elevenlabs("hi", tmp_path, "en")
        assert out.read_bytes() == b"mp3data"
        assert out.name == "voiceover_en.mp3"


# --------------------------------------------------------------------------- #
# macOS say + edge wrappers
# --------------------------------------------------------------------------- #
class TestSay:
    def test_runs_say_then_ffmpeg(self, tmp_path):
        with patch("verticals.tts.run_cmd") as mock_run:
            out = tts._generate_say("hello", tmp_path)
        assert out == tmp_path / "voiceover_say.mp3"
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0].args[0][0] == "say"
        assert mock_run.call_args_list[1].args[0][0] == "ffmpeg"


class TestEdge:
    def test_generate_edge_uses_default_voice(self, tmp_path):
        # Force a plain MagicMock so the async _edge_tts_generate isn't wrapped
        # in an AsyncMock (which would leave an unawaited coroutine).
        with patch("verticals.tts._edge_tts_generate", new_callable=MagicMock) as gen, \
             patch("asyncio.get_running_loop", side_effect=RuntimeError), \
             patch("asyncio.run") as arun:
            out = tts._generate_edge_tts("hi", tmp_path, "en")
        assert out == tmp_path / "voiceover_en.mp3"
        arun.assert_called_once()
        # Default English Edge voice selected.
        assert gen.call_args.args[1] == tts.EDGE_VOICES["en"]

    def test_generate_edge_voice_override(self, tmp_path):
        with patch("verticals.tts._edge_tts_generate", new_callable=MagicMock) as gen, \
             patch("asyncio.get_running_loop", side_effect=RuntimeError), \
             patch("asyncio.run"):
            tts._generate_edge_tts("hi", tmp_path, "en", voice_override="custom-voice")
        assert gen.call_args.args[1] == "custom-voice"
