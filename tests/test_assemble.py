"""Tests for pipeline/assemble.py — audio duration parsing + video assembly."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from verticals import assemble
from verticals.assemble import get_audio_duration


class TestGetAudioDuration:
    @patch("verticals.assemble.run_cmd")
    def test_parses_duration(self, mock_cmd):
        mock_result = MagicMock()
        mock_result.stdout = "65.432000\n"
        mock_cmd.return_value = mock_result

        duration = get_audio_duration(Path("/tmp/test.mp3"))
        assert abs(duration - 65.432) < 0.001

    @patch("verticals.assemble.run_cmd")
    def test_parses_short_duration(self, mock_cmd):
        mock_result = MagicMock()
        mock_result.stdout = "3.5\n"
        mock_cmd.return_value = mock_result

        duration = get_audio_duration(Path("/tmp/test.mp3"))
        assert abs(duration - 3.5) < 0.001

    @patch("verticals.assemble.run_cmd")
    def test_calls_ffprobe(self, mock_cmd):
        mock_result = MagicMock()
        mock_result.stdout = "10.0\n"
        mock_cmd.return_value = mock_result

        get_audio_duration(Path("/tmp/audio.mp3"))
        args = mock_cmd.call_args[0][0]
        assert "ffprobe" in args
        # str(Path(...)) so this passes on Windows, where the separator differs.
        assert str(Path("/tmp/audio.mp3")) in args


@pytest.fixture
def assemble_env(tmp_path):
    """Patch out ffmpeg, frame animation, duration probing, and MEDIA_DIR."""
    media = tmp_path / "media"
    media.mkdir()
    with patch("verticals.assemble.get_audio_duration", return_value=6.0), \
         patch("verticals.assemble.animate_frame") as anim, \
         patch("verticals.assemble.run_cmd") as run, \
         patch("verticals.assemble.MEDIA_DIR", media):
        yield {"anim": anim, "run": run, "media": media, "tmp": tmp_path}


def _frames(tmp_path, n=3):
    frames = []
    for i in range(n):
        p = tmp_path / f"frame_{i}.png"
        p.write_bytes(b"x")
        frames.append(p)
    return frames


class TestAssembleVideo:
    def test_returns_path_in_media_dir(self, assemble_env):
        tmp = assemble_env["tmp"]
        out = assemble.assemble_video(
            _frames(tmp), tmp / "vo.mp3", tmp, job_id="j1", lang="en"
        )
        assert out == assemble_env["media"] / "verticals_j1_en.mp4"

    def test_animates_every_frame(self, assemble_env):
        tmp = assemble_env["tmp"]
        assemble.assemble_video(_frames(tmp, 3), tmp / "vo.mp3", tmp, job_id="j")
        assert assemble_env["anim"].call_count == 3

    def test_writes_concat_file(self, assemble_env):
        tmp = assemble_env["tmp"]
        assemble.assemble_video(_frames(tmp, 3), tmp / "vo.mp3", tmp, job_id="j")
        concat = (tmp / "concat.txt").read_text()
        assert concat.count("file '") == 3

    def test_concat_escapes_single_quotes(self, assemble_env):
        # An output dir containing a single quote must be escaped for ffmpeg.
        weird = assemble_env["tmp"] / "o'dir"
        weird.mkdir()
        assemble.assemble_video(_frames(weird, 1), weird / "vo.mp3", weird, job_id="j")
        concat = (weird / "concat.txt").read_text()
        assert "'\\''" in concat

    def test_no_music_no_captions_copies_video(self, assemble_env):
        tmp = assemble_env["tmp"]
        assemble.assemble_video(_frames(tmp), tmp / "vo.mp3", tmp, job_id="j")
        final_cmd = assemble_env["run"].call_args_list[-1].args[0]
        assert "copy" in final_cmd
        assert "-filter_complex" not in final_cmd

    def test_captions_applied_when_ass_exists(self, assemble_env):
        tmp = assemble_env["tmp"]
        ass = tmp / "caps.ass"
        ass.write_text("[Events]")
        assemble.assemble_video(_frames(tmp), tmp / "vo.mp3", tmp, job_id="j", ass_path=str(ass))
        final_cmd = assemble_env["run"].call_args_list[-1].args[0]
        vf = final_cmd[final_cmd.index("-vf") + 1]
        assert "ass=" in vf
        assert "libx264" in final_cmd  # re-encode required for the filter

    def test_music_branch_mixes_and_ducks(self, assemble_env):
        tmp = assemble_env["tmp"]
        music = tmp / "bg.mp3"
        music.write_bytes(b"m")
        assemble.assemble_video(
            _frames(tmp), tmp / "vo.mp3", tmp, job_id="j",
            music_path=str(music), duck_filter="volume=0.1",
        )
        final_cmd = assemble_env["run"].call_args_list[-1].args[0]
        assert "-filter_complex" in final_cmd
        fc = final_cmd[final_cmd.index("-filter_complex") + 1]
        assert "amix" in fc
        assert "volume=0.1" in fc  # duck filter woven in

    def test_missing_music_file_ignored(self, assemble_env):
        tmp = assemble_env["tmp"]
        assemble.assemble_video(
            _frames(tmp), tmp / "vo.mp3", tmp, job_id="j",
            music_path=str(tmp / "nope.mp3"),
        )
        final_cmd = assemble_env["run"].call_args_list[-1].args[0]
        assert "-filter_complex" not in final_cmd
