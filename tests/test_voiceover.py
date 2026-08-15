"""Tests for verticals/voiceover.py — legacy shim delegating to tts."""

from verticals import voiceover
from verticals.tts import generate_voiceover as tts_generate_voiceover


def test_reexports_tts_generate_voiceover():
    # The legacy module simply forwards to tts.generate_voiceover.
    assert voiceover.generate_voiceover is tts_generate_voiceover


def test_all_exports():
    assert voiceover.__all__ == ["generate_voiceover"]
