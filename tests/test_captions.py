"""Tests for pipeline/captions.py — word grouping, ASS generation, SRT formatting."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from verticals import captions
from verticals.captions import (
    _group_words,
    _format_ass_time,
    _generate_ass,
    _generate_srt,
    _srt_time,
)


class TestWordGrouping:
    def test_group_words_default_size(self, sample_words):
        groups = _group_words(sample_words)
        assert len(groups) == 3  # 12 words / 4 = 3 groups
        assert len(groups[0]) == 4
        assert len(groups[1]) == 4
        assert len(groups[2]) == 4

    def test_group_words_custom_size(self, sample_words):
        groups = _group_words(sample_words, group_size=3)
        assert len(groups) == 4  # 12 / 3 = 4
        assert len(groups[0]) == 3

    def test_group_words_single_word(self):
        words = [{"word": "Hello", "start": 0.0, "end": 0.5}]
        groups = _group_words(words)
        assert len(groups) == 1
        assert len(groups[0]) == 1

    def test_group_words_empty(self):
        groups = _group_words([])
        assert groups == []

    def test_group_words_uneven(self):
        words = [
            {"word": "one", "start": 0.0, "end": 0.3},
            {"word": "two", "start": 0.3, "end": 0.6},
            {"word": "three", "start": 0.6, "end": 0.9},
            {"word": "four", "start": 0.9, "end": 1.2},
            {"word": "five", "start": 1.2, "end": 1.5},
        ]
        groups = _group_words(words, group_size=4)
        assert len(groups) == 2
        assert len(groups[0]) == 4
        assert len(groups[1]) == 1


class TestASSTimeFormat:
    def test_zero(self):
        assert _format_ass_time(0.0) == "0:00:00.00"

    def test_seconds(self):
        assert _format_ass_time(5.5) == "0:00:05.50"

    def test_minutes(self):
        assert _format_ass_time(65.25) == "0:01:05.25"

    def test_hours(self):
        assert _format_ass_time(3661.75) == "1:01:01.75"

    def test_small_centiseconds(self):
        assert _format_ass_time(0.05) == "0:00:00.05"


class TestSRTTimeFormat:
    def test_zero(self):
        assert _srt_time(0.0) == "00:00:00,000"

    def test_seconds(self):
        assert _srt_time(5.5) == "00:00:05,500"

    def test_minutes(self):
        assert _srt_time(125.123) == "00:02:05,123"


class TestASSGeneration:
    def test_generates_file(self, sample_words, tmp_work_dir):
        output = tmp_work_dir / "test.ass"
        _generate_ass(sample_words, output)
        assert output.exists()
        content = output.read_text()
        assert "[Script Info]" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content

    def test_contains_dialogue_lines(self, sample_words, tmp_work_dir):
        output = tmp_work_dir / "test.ass"
        _generate_ass(sample_words, output)
        content = output.read_text()
        assert "Dialogue:" in content

    def test_highlight_color_in_events(self, sample_words, tmp_work_dir):
        output = tmp_work_dir / "test.ass"
        _generate_ass(sample_words, output)
        content = output.read_text()
        # Yellow highlight in ASS &HAABBGGRR& format (#FFFF00 -> alpha 00, B 00, G FF, R FF)
        assert "\\c&H0000FFFF&" in content

    def test_word_count_events(self, sample_words, tmp_work_dir):
        """Each word in each group gets one dialogue line as active."""
        output = tmp_work_dir / "test.ass"
        _generate_ass(sample_words, output)
        content = output.read_text()
        dialogue_count = content.count("Dialogue:")
        # 3 groups * 4 words each = 12 dialogue lines
        assert dialogue_count == 12


class TestSRTGeneration:
    def test_generates_file(self, sample_words, tmp_work_dir):
        output = tmp_work_dir / "test.srt"
        _generate_srt(sample_words, output)
        assert output.exists()

    def test_srt_format(self, sample_words, tmp_work_dir):
        output = tmp_work_dir / "test.srt"
        _generate_srt(sample_words, output)
        content = output.read_text()
        assert "-->" in content
        assert "This is a test" in content

    def test_srt_group_count(self, sample_words, tmp_work_dir):
        output = tmp_work_dir / "test.srt"
        _generate_srt(sample_words, output)
        content = output.read_text()
        # 3 groups = 3 subtitle entries
        assert "1\n" in content
        assert "2\n" in content
        assert "3\n" in content


class TestAssColorFallback:
    def test_non_six_char_color_uses_fallback(self, sample_words, tmp_work_dir):
        output = tmp_work_dir / "test.ass"
        # A 3-char hex isn't the expected 6-char form -> fallback yellow.
        _generate_ass(sample_words, output, highlight_color="#FFF")
        assert "\\c&H0000FFFF&" in output.read_text()


class TestHasAssFilter:
    def test_true_when_ass_listed(self):
        result = MagicMock()
        result.stdout = "... ass  subtitles ..."
        with patch("subprocess.run", return_value=result):
            assert captions._has_ass_filter() is True

    def test_false_on_exception(self):
        with patch("subprocess.run", side_effect=OSError("no ffmpeg")):
            assert captions._has_ass_filter() is False


class TestWhisperWordTimestamps:
    def test_returns_empty_when_whisper_missing(self, tmp_path):
        # whisper is not installed in the test env -> ImportError -> [].
        assert captions._whisper_word_timestamps(tmp_path / "a.mp3") == []

    def test_parses_segments(self, tmp_path):
        model = MagicMock()
        model.transcribe.return_value = {
            "segments": [
                {"words": [
                    {"word": " Hello", "start": 0.0, "end": 0.4},
                    {"word": " world", "start": 0.4, "end": 0.9},
                ]}
            ]
        }
        fake_whisper = MagicMock()
        fake_whisper.load_model.return_value = model
        with patch.dict(sys.modules, {"whisper": fake_whisper}):
            words = captions._whisper_word_timestamps(tmp_path / "a.mp3", "en")
        assert words == [
            {"word": "Hello", "start": 0.0, "end": 0.4},
            {"word": "world", "start": 0.4, "end": 0.9},
        ]


class TestGenerateCaptions:
    def test_generates_srt_and_ass(self, sample_words, tmp_path):
        with patch("verticals.captions._whisper_word_timestamps", return_value=sample_words):
            result = captions.generate_captions(tmp_path / "vo.mp3", tmp_path, "en")
        assert Path(result["srt_path"]).exists()
        assert Path(result["ass_path"]).exists()
        assert result["words"] == sample_words

    def test_cli_fallback_when_no_words(self, tmp_path):
        audio = tmp_path / "vo.mp3"
        audio.write_bytes(b"x")
        # The CLI is mocked; pre-create the .srt it would have produced.
        (tmp_path / "out.srt").write_text("1\n00:00 --> 00:01\nhi\n")
        with patch("verticals.captions._whisper_word_timestamps", return_value=[]), \
             patch("verticals.config.run_cmd"):
            result = captions.generate_captions(audio, tmp_path, "en")
        assert result["words"] == []
        assert result["srt_path"] == str(audio.with_suffix(".srt"))
        assert Path(result["srt_path"]).exists()

    def test_cli_fallback_failure_is_swallowed(self, tmp_path):
        audio = tmp_path / "vo.mp3"
        audio.write_bytes(b"x")
        with patch("verticals.captions._whisper_word_timestamps", return_value=[]), \
             patch("verticals.config.run_cmd", side_effect=RuntimeError("whisper cli missing")):
            result = captions.generate_captions(audio, tmp_path, "en")
        assert result["words"] == []
        assert "srt_path" not in result
