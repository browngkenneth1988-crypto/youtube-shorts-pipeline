"""Tests for verticals/__main__.py — CLI command functions and dispatch.

The command functions import their dependencies lazily, so patches target the
source modules (e.g. verticals.draft.generate_draft), which the `from X import Y`
statements resolve at call time.
"""

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from verticals import __main__ as cli
from verticals.topics.base import TopicCandidate


# --------------------------------------------------------------------------- #
# cmd_draft
# --------------------------------------------------------------------------- #
class TestCmdDraft:
    def test_generates_and_saves_draft(self, tmp_path):
        fake_draft = {
            "script": "the script",
            "youtube_title": "Title",
            "broll_prompts": ["p1", "p2", "p3"],
        }
        args = Namespace(
            news="big news", context="ctx", niche="tech",
            platform="shorts", provider="claude",
        )
        with patch("verticals.__main__.DRAFTS_DIR", tmp_path), \
             patch("verticals.draft.generate_draft", return_value=dict(fake_draft)) as gen:
            out = cli.cmd_draft(args)

        assert out.parent == tmp_path
        saved = json.loads(out.read_text())
        assert saved["script"] == "the script"
        assert "job_id" in saved
        assert saved["_pipeline_state"]["draft"]["status"] == "done"
        # Args threaded through to generate_draft.
        assert gen.call_args.args[0] == "big news"
        assert gen.call_args.kwargs["niche"] == "tech"
        assert gen.call_args.kwargs["platform"] == "shorts"
        assert gen.call_args.kwargs["provider"] == "claude"

    def test_defaults_when_attrs_missing(self, tmp_path):
        args = Namespace(news="topic")  # no niche/platform/provider/context
        with patch("verticals.__main__.DRAFTS_DIR", tmp_path), \
             patch("verticals.draft.generate_draft",
                   return_value={"script": "s", "broll_prompts": []}) as gen:
            cli.cmd_draft(args)
        assert gen.call_args.kwargs["niche"] == "general"
        assert gen.call_args.kwargs["platform"] == "shorts"


# --------------------------------------------------------------------------- #
# cmd_produce
# --------------------------------------------------------------------------- #
def _write_draft(tmp_path, **extra):
    draft = {"job_id": "j1", "script": "hello world", "broll_prompts": ["a", "b", "c"],
             "niche": "general"}
    draft.update(extra)
    p = tmp_path / "draft.json"
    p.write_text(json.dumps(draft))
    return p


class TestCmdProduce:
    def _patches(self, tmp_path, srt):
        return [
            patch("verticals.__main__.MEDIA_DIR", tmp_path / "media"),
            patch("verticals.broll.generate_broll", return_value=[tmp_path / "f0.png"]),
            patch("verticals.tts.generate_voiceover", return_value=tmp_path / "vo.mp3"),
            patch("verticals.captions.generate_captions",
                  return_value={"srt_path": str(srt), "ass_path": "caps.ass"}),
            patch("verticals.music.select_and_prepare_music",
                  return_value={"track_path": "t.mp3", "duck_filter": "volume=0.1"}),
            patch("verticals.assemble.assemble_video", return_value=tmp_path / "out.mp4"),
        ]

    def test_runs_all_stages(self, tmp_path):
        (tmp_path / "media").mkdir()
        srt = tmp_path / "caps.srt"
        srt.write_text("1\n")
        draft_path = _write_draft(tmp_path)
        args = Namespace(draft=str(draft_path), lang="en", voice=None, script=None, force=False)

        from contextlib import ExitStack
        with ExitStack() as es:
            mocks = [es.enter_context(p) for p in self._patches(tmp_path, srt)]
            video = cli.cmd_produce(args)

        assert video == tmp_path / "out.mp4"
        saved = json.loads(draft_path.read_text())
        assert saved["video_en"] == str(tmp_path / "out.mp4")
        # SRT copied into the media dir and recorded on the draft.
        assert saved["srt_en"].endswith("verticals_j1_en.srt")
        # assemble received the generated frames + voiceover.
        assemble = mocks[-1]
        assert assemble.call_args.kwargs["job_id"] == "j1"

    def test_skips_completed_stages(self, tmp_path):
        (tmp_path / "media").mkdir()
        state = {
            "broll": {"status": "done", "artifacts": {"frames": [str(tmp_path / "f.png")]}},
            "voiceover": {"status": "done", "artifacts": {"path": str(tmp_path / "vo.mp3")}},
            "captions": {"status": "done", "artifacts": {"srt_path": "", "ass_path": ""}},
            "music": {"status": "done", "artifacts": {"track_path": "", "duck_filter": ""}},
            "assemble": {"status": "done", "artifacts": {"video_path": str(tmp_path / "v.mp4")}},
        }
        draft_path = _write_draft(tmp_path, _pipeline_state=state)
        args = Namespace(draft=str(draft_path), lang="en", voice=None, script=None, force=False)

        with patch("verticals.__main__.MEDIA_DIR", tmp_path / "media"), \
             patch("verticals.broll.generate_broll") as gb, \
             patch("verticals.tts.generate_voiceover") as gv, \
             patch("verticals.assemble.assemble_video") as av:
            video = cli.cmd_produce(args)

        # Nothing regenerated; the saved artifact path is reused.
        gb.assert_not_called()
        gv.assert_not_called()
        av.assert_not_called()
        assert video == tmp_path / "v.mp4"


# --------------------------------------------------------------------------- #
# cmd_upload
# --------------------------------------------------------------------------- #
class TestCmdUpload:
    def test_uploads_with_thumbnail(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"vid")
        draft_path = _write_draft(tmp_path, video_en=str(video))
        args = Namespace(draft=str(draft_path), lang="en", force=False)

        with patch("verticals.__main__.MEDIA_DIR", tmp_path), \
             patch("verticals.thumbnail.generate_thumbnail", return_value=tmp_path / "thumb.png"), \
             patch("verticals.upload.upload_to_youtube", return_value="https://youtu.be/AAA") as up:
            url = cli.cmd_upload(args)

        assert url == "https://youtu.be/AAA"
        saved = json.loads(draft_path.read_text())
        assert saved["youtube_url_en"] == "https://youtu.be/AAA"
        assert up.call_args.args[0] == video  # video path passed

    def test_missing_video_exits(self, tmp_path):
        # Point at a path that definitely does not exist.
        draft_path = _write_draft(tmp_path, video_en=str(tmp_path / "missing.mp4"))
        args = Namespace(draft=str(draft_path), lang="en", force=False)
        with patch("verticals.__main__.MEDIA_DIR", tmp_path):
            with pytest.raises(SystemExit) as exc:
                cli.cmd_upload(args)
        assert exc.value.code == 1

    def test_thumbnail_failure_still_uploads(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"vid")
        draft_path = _write_draft(tmp_path, video_en=str(video))
        args = Namespace(draft=str(draft_path), lang="en", force=False)

        with patch("verticals.__main__.MEDIA_DIR", tmp_path), \
             patch("verticals.thumbnail.generate_thumbnail", side_effect=RuntimeError("no key")), \
             patch("verticals.upload.upload_to_youtube", return_value="https://youtu.be/BBB") as up:
            url = cli.cmd_upload(args)

        assert url == "https://youtu.be/BBB"
        # Uploaded without a thumbnail (None passed as thumbnail arg).
        assert up.call_args.args[4] is None

    def test_skips_completed_thumbnail_and_upload(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"vid")
        thumb = tmp_path / "thumb.png"
        thumb.write_bytes(b"png")
        state = {
            "thumbnail": {"status": "done", "artifacts": {"path": str(thumb)}},
            "upload": {"status": "done", "artifacts": {"url": "https://youtu.be/OLD"}},
        }
        draft_path = _write_draft(tmp_path, video_en=str(video), _pipeline_state=state)
        args = Namespace(draft=str(draft_path), lang="en", force=False)

        with patch("verticals.__main__.MEDIA_DIR", tmp_path), \
             patch("verticals.thumbnail.generate_thumbnail") as gt, \
             patch("verticals.upload.upload_to_youtube") as up:
            url = cli.cmd_upload(args)

        # Both stages reused from state; nothing regenerated or re-uploaded.
        gt.assert_not_called()
        up.assert_not_called()
        assert url == "https://youtu.be/OLD"


# --------------------------------------------------------------------------- #
# cmd_run
# --------------------------------------------------------------------------- #
class TestCmdRun:
    def test_dry_run_stops_after_draft(self):
        args = Namespace(dry_run=True, lang="en", voice=None)
        with patch("verticals.__main__.cmd_draft", return_value=Path("/x/d.json")) as draft, \
             patch("verticals.__main__.cmd_produce") as prod, \
             patch("verticals.__main__.cmd_upload") as up:
            cli.cmd_run(args)
        draft.assert_called_once()
        prod.assert_not_called()
        up.assert_not_called()

    def test_full_pipeline(self):
        args = Namespace(dry_run=False, lang="en", voice="edge")
        with patch("verticals.__main__.cmd_draft", return_value=Path("/x/d.json")) as draft, \
             patch("verticals.__main__.cmd_produce", return_value=Path("/x/v.mp4")) as prod, \
             patch("verticals.__main__.cmd_upload", return_value="https://youtu.be/CCC") as up:
            cli.cmd_run(args)
        draft.assert_called_once()
        # produce/upload receive the draft path from cmd_draft. Compared via
        # str(Path(...)) because cmd_run stringifies a Path, which renders with
        # backslashes on Windows — the literal "/x/d.json" only matches on POSIX.
        expected = str(Path("/x/d.json"))
        assert prod.call_args.args[0].draft == expected
        assert up.call_args.args[0].draft == expected


# --------------------------------------------------------------------------- #
# cmd_topics / cmd_niches
# --------------------------------------------------------------------------- #
class TestCmdTopics:
    def test_prints_candidates(self, capsys):
        engine = MagicMock()
        engine.discover.return_value = [
            TopicCandidate("Hot Story", "reddit", trending_score=0.8, summary="a summary"),
        ]
        args = Namespace(niche="tech", limit=5)
        with patch("verticals.topics.TopicEngine", return_value=engine):
            cli.cmd_topics(args)
        out = capsys.readouterr().out
        assert "Hot Story" in out
        engine.discover.assert_called_once_with(limit=5)

    def test_no_candidates(self, capsys):
        engine = MagicMock()
        engine.discover.return_value = []
        args = Namespace(niche="general", limit=15)
        with patch("verticals.topics.TopicEngine", return_value=engine):
            cli.cmd_topics(args)
        assert "No topics found" in capsys.readouterr().out


class TestCmdNiches:
    def test_lists_niches(self, capsys):
        cli.cmd_niches(Namespace())
        out = capsys.readouterr().out
        assert "Available niches" in out
        assert "general" in out


# --------------------------------------------------------------------------- #
# main() dispatch
# --------------------------------------------------------------------------- #
def _config_exists(exists=True):
    mock = MagicMock()
    mock.exists.return_value = exists
    return patch("verticals.__main__.CONFIG_FILE", mock)


class TestMain:
    def test_first_run_triggers_setup(self):
        with _config_exists(False), \
             patch("verticals.__main__.run_setup") as setup, \
             patch("sys.argv", ["verticals"]):
            cli.main()
        setup.assert_called_once()

    def test_no_command_prints_help(self, capsys):
        with _config_exists(), patch("sys.argv", ["verticals"]):
            cli.main()
        assert "usage" in capsys.readouterr().out.lower()

    def test_niches_dispatch(self):
        with _config_exists(), patch("sys.argv", ["verticals", "niches"]), \
             patch("verticals.__main__.cmd_niches") as c:
            cli.main()
        c.assert_called_once()

    def test_draft_requires_news_or_discover(self):
        with _config_exists(), patch("sys.argv", ["verticals", "draft"]):
            with pytest.raises(SystemExit) as exc:
                cli.main()
        assert exc.value.code == 1

    def test_draft_with_news_dispatches(self):
        with _config_exists(), patch("sys.argv", ["verticals", "draft", "--news", "hi"]), \
             patch("verticals.__main__.cmd_draft") as c:
            cli.main()
        c.assert_called_once()

    def test_produce_dispatch(self):
        with _config_exists(), patch("sys.argv", ["verticals", "produce", "--draft", "d.json"]), \
             patch("verticals.__main__.cmd_produce") as c:
            cli.main()
        c.assert_called_once()

    def test_upload_dispatch(self):
        with _config_exists(), patch("sys.argv", ["verticals", "upload", "--draft", "d.json"]), \
             patch("verticals.__main__.cmd_upload") as c:
            cli.main()
        c.assert_called_once()

    def test_run_dispatch(self):
        with _config_exists(), patch("sys.argv", ["verticals", "run", "--news", "hi"]), \
             patch("verticals.__main__.cmd_run") as c:
            cli.main()
        c.assert_called_once()

    def test_topics_dispatch(self):
        with _config_exists(), patch("sys.argv", ["verticals", "topics"]), \
             patch("verticals.__main__.cmd_topics") as c:
            cli.main()
        c.assert_called_once()

    def test_verbose_flag(self):
        with _config_exists(), patch("sys.argv", ["verticals", "-v", "niches"]), \
             patch("verticals.__main__.set_verbose") as sv, \
             patch("verticals.__main__.cmd_niches"):
            cli.main()
        sv.assert_called_once_with(True)

    def test_discover_auto_pick(self):
        engine = MagicMock()
        engine.discover.return_value = [TopicCandidate("Picked Topic", "rss")]
        engine.auto_pick.return_value = "Picked Topic"
        with _config_exists(), \
             patch("sys.argv", ["verticals", "draft", "--discover", "--auto-pick"]), \
             patch("verticals.topics.TopicEngine", return_value=engine), \
             patch("verticals.__main__.cmd_draft") as c:
            cli.main()
        assert c.call_args.args[0].news == "Picked Topic"

    def test_discover_no_candidates_exits(self):
        engine = MagicMock()
        engine.discover.return_value = []
        with _config_exists(), \
             patch("sys.argv", ["verticals", "draft", "--discover"]), \
             patch("verticals.topics.TopicEngine", return_value=engine):
            with pytest.raises(SystemExit) as exc:
                cli.main()
        assert exc.value.code == 1

    def test_discover_interactive_choice(self):
        engine = MagicMock()
        engine.discover.return_value = [
            TopicCandidate("Option One", "rss"),
            TopicCandidate("Option Two", "reddit"),
        ]
        with _config_exists(), \
             patch("sys.argv", ["verticals", "draft", "--discover"]), \
             patch("verticals.topics.TopicEngine", return_value=engine), \
             patch("builtins.input", return_value="2"), \
             patch("verticals.__main__.cmd_draft") as c:
            cli.main()
        assert c.call_args.args[0].news == "Option Two"

    def test_discover_custom_topic_input(self):
        engine = MagicMock()
        engine.discover.return_value = [TopicCandidate("Option One", "rss")]
        with _config_exists(), \
             patch("sys.argv", ["verticals", "draft", "--discover"]), \
             patch("verticals.topics.TopicEngine", return_value=engine), \
             patch("builtins.input", return_value="my own topic"), \
             patch("verticals.__main__.cmd_draft") as c:
            cli.main()
        assert c.call_args.args[0].news == "my own topic"
