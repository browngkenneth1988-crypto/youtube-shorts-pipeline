"""Tests for pipeline/music.py — duck filter generation, speech region merging."""

from unittest.mock import patch

from verticals import music
from verticals.music import build_duck_filter


class TestBuildDuckFilter:
    def test_empty_regions(self):
        result = build_duck_filter([])
        assert result == "volume=0.25"

    def test_single_region(self):
        result = build_duck_filter([(1.0, 3.0)])
        assert "volume=" in result
        assert "between(t," in result
        assert "0.12" in result
        assert "0.25" in result

    def test_multiple_regions(self, sample_speech_regions):
        result = build_duck_filter(sample_speech_regions)
        assert result.count("between(t,") == 2
        assert "0.12" in result
        assert "0.25" in result
        assert "eval=frame" in result

    def test_buffer_applied(self):
        result = build_duck_filter([(1.0, 2.0)], buffer=0.5)
        # Start should be max(0, 1.0-0.5) = 0.5
        # End should be 2.0+0.5 = 2.5
        assert "0.50" in result
        assert "2.50" in result

    def test_buffer_no_negative_start(self):
        result = build_duck_filter([(0.1, 1.0)], buffer=0.3)
        # Start should be max(0, 0.1-0.3) = 0.0
        assert "0.00" in result

    def test_returns_ffmpeg_filter_format(self, sample_speech_regions):
        result = build_duck_filter(sample_speech_regions)
        # Should be a valid ffmpeg volume filter
        assert result.startswith("volume=")
        assert ":eval=frame" in result

    def test_if_expression_structure(self):
        result = build_duck_filter([(5.0, 10.0)])
        assert "if(" in result
        assert ", 0.12, 0.25)" in result


class TestFindTracks:
    def test_empty_when_dir_missing(self, tmp_path):
        with patch("verticals.music.MUSIC_DIR", tmp_path / "nope"):
            assert music._find_tracks() == []

    def test_finds_and_sorts_mp3s(self, tmp_path):
        for name in ["b.mp3", "a.mp3", "c.txt"]:
            (tmp_path / name).write_bytes(b"x")
        with patch("verticals.music.MUSIC_DIR", tmp_path):
            tracks = music._find_tracks()
        assert [t.name for t in tracks] == ["a.mp3", "b.mp3"]  # sorted, .txt excluded


class TestGetSpeechRegions:
    def test_merges_close_words_and_splits_on_gaps(self, tmp_path):
        words = [
            {"word": "a", "start": 0.0, "end": 0.3},
            {"word": "b", "start": 0.5, "end": 1.0},   # gap 0.2 < 0.5 -> merge
            {"word": "c", "start": 2.0, "end": 2.5},   # gap 1.0 >= 0.5 -> new region
        ]
        with patch("verticals.captions._whisper_word_timestamps", return_value=words):
            regions = music._get_speech_regions(tmp_path / "vo.mp3")
        assert regions == [(0.0, 1.0), (2.0, 2.5)]

    def test_falls_back_to_duration_when_no_words(self, tmp_path):
        with patch("verticals.captions._whisper_word_timestamps", return_value=[]), \
             patch("verticals.assemble.get_audio_duration", return_value=42.0):
            regions = music._get_speech_regions(tmp_path / "vo.mp3")
        assert regions == [(0.0, 42.0)]

    def test_final_fallback_on_total_failure(self, tmp_path):
        with patch("verticals.captions._whisper_word_timestamps", side_effect=RuntimeError), \
             patch("verticals.assemble.get_audio_duration", side_effect=RuntimeError):
            regions = music._get_speech_regions(tmp_path / "vo.mp3")
        assert regions == [(0.0, 60.0)]


class TestSelectAndPrepareMusic:
    def test_no_tracks_returns_empty(self, tmp_path):
        with patch("verticals.music._find_tracks", return_value=[]):
            assert music.select_and_prepare_music(tmp_path / "vo.mp3", tmp_path) == {}

    def test_returns_track_and_duck_filter(self, tmp_path):
        track = tmp_path / "song.mp3"
        track.write_bytes(b"x")
        with patch("verticals.music._find_tracks", return_value=[track]), \
             patch("verticals.music.random.choice", return_value=track), \
             patch("verticals.music._get_speech_regions", return_value=[(0.0, 3.0)]):
            result = music.select_and_prepare_music(tmp_path / "vo.mp3", tmp_path)
        assert result["track_path"] == str(track)
        assert result["duck_filter"].startswith("volume=")
