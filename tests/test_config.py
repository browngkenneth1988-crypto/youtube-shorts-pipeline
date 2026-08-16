"""Tests for pipeline/config.py — key resolution, utilities."""

import json
import os
import stat
import sys
from unittest.mock import MagicMock, patch

import pytest

from verticals import config
from verticals.config import _get_key, extract_keywords, load_config


class TestGetKey:
    def test_env_var_priority(self):
        with patch.dict(os.environ, {"TEST_API_KEY": "from_env"}):
            assert _get_key("TEST_API_KEY") == "from_env"

    def test_returns_empty_for_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _get_key("NONEXISTENT_KEY_XYZ") == ""

    @patch("verticals.config.CONFIG_FILE")
    def test_reads_from_config(self, mock_path):
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = json.dumps({"MY_KEY": "from_config"})

        with patch.dict(os.environ, {}, clear=True):
            result = _get_key("MY_KEY")
            assert result == "from_config"


class TestExtractKeywords:
    def test_basic_extraction(self):
        result = extract_keywords("The quick brown fox jumps over the lazy dog")
        words = result.split()
        assert "the" not in words
        assert "over" not in words
        assert len(words) <= 4

    def test_lowercase(self):
        result = extract_keywords("UPPER Case Words HERE")
        for w in result.split():
            assert w == w.lower()


class TestLoadConfig:
    @patch("verticals.config.CONFIG_FILE")
    def test_loads_valid_json(self, mock_path):
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = json.dumps({"key": "value"})
        assert load_config() == {"key": "value"}

    @patch("verticals.config.CONFIG_FILE")
    def test_returns_empty_for_missing(self, mock_path):
        mock_path.exists.return_value = False
        assert load_config() == {}

    @patch("verticals.config.CONFIG_FILE")
    def test_returns_empty_for_invalid_json(self, mock_path):
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "not json"
        assert load_config() == {}


class TestGetKeyConfigFallback:
    @patch("verticals.config.CONFIG_FILE")
    def test_env_beats_config(self, mock_path):
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = json.dumps({"K": "from_config"})
        with patch.dict(os.environ, {"K": "from_env"}):
            assert _get_key("K") == "from_env"

    @patch("verticals.config.CONFIG_FILE")
    def test_bad_config_json_returns_empty(self, mock_path):
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "{ not valid json"
        with patch.dict(os.environ, {}, clear=True):
            assert _get_key("K") == ""

    @patch("verticals.config.CONFIG_FILE")
    def test_missing_key_in_config_returns_empty(self, mock_path):
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = json.dumps({"OTHER": "x"})
        with patch.dict(os.environ, {}, clear=True):
            assert _get_key("K") == ""


class TestTypedKeyGetters:
    """The typed getters just delegate to _get_key with the right name."""

    def test_delegation(self):
        with patch("verticals.config._get_key", return_value="v") as mk:
            assert config.get_anthropic_key() == "v"
            assert config.get_newsapi_key() == "v"
            assert config.get_elevenlabs_key() == "v"
            assert config.get_gemini_key() == "v"
        names = {c.args[0] for c in mk.call_args_list}
        assert names == {
            "ANTHROPIC_API_KEY", "NEWSAPI_KEY", "ELEVENLABS_API_KEY", "GEMINI_API_KEY",
        }


class TestExtractKeywordsMore:
    def test_strips_punctuation(self):
        assert "hello" in extract_keywords("Hello, world!").split()

    def test_drops_short_words_and_stopwords(self):
        # "is"/"an" are stopwords; "ok" is <= 2 chars.
        result = extract_keywords("ok is an amazing breakthrough").split()
        assert "ok" not in result
        assert "is" not in result
        assert "amazing" in result

    def test_caps_at_four_keywords(self):
        result = extract_keywords("alpha bravo charlie delta echo foxtrot golf")
        assert len(result.split()) == 4

    def test_empty_string(self):
        assert extract_keywords("") == ""


class TestWriteSecretFile:
    def test_writes_content(self, tmp_path):
        p = tmp_path / "secret.txt"
        config.write_secret_file(p, "top-secret")
        assert p.read_text() == "top-secret"

    def test_permissions_are_0600(self, tmp_path):
        p = tmp_path / "secret.txt"
        config.write_secret_file(p, "x")
        assert stat.S_IMODE(p.stat().st_mode) == 0o600

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "nested" / "deep" / "secret.txt"
        config.write_secret_file(p, "x")
        assert p.exists()

    def test_truncates_existing(self, tmp_path):
        p = tmp_path / "secret.txt"
        config.write_secret_file(p, "longer original content")
        config.write_secret_file(p, "short")
        assert p.read_text() == "short"


class TestRunCmd:
    def test_capture_returns_result(self):
        with patch("verticals.config.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="out")
            r = config.run_cmd(["echo", "hi"], capture=True)
            assert r.stdout == "out"
            _, kwargs = mock_run.call_args
            assert kwargs["capture_output"] is True
            assert kwargs["text"] is True

    def test_capture_raises_on_nonzero(self):
        with patch("verticals.config.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="the error")
            with pytest.raises(RuntimeError, match="the error"):
                config.run_cmd(["false"], capture=True)

    def test_capture_no_check_does_not_raise(self):
        with patch("verticals.config.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="err")
            r = config.run_cmd(["false"], capture=True, check=False)
            assert r.returncode == 1

    def test_non_capture_delegates_to_subprocess(self):
        with patch("verticals.config.subprocess.run") as mock_run:
            config.run_cmd(["ls"], check=True)
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs["check"] is True


class TestHasClaudeCli:
    def test_true_when_found(self):
        with patch("shutil.which", return_value="/usr/bin/claude"):
            assert config.has_claude_cli() is True

    def test_false_when_absent(self):
        with patch("shutil.which", return_value=None):
            assert config.has_claude_cli() is False


class TestClaudeMaxCredentials:
    @patch("verticals.config.CLAUDE_CREDENTIALS")
    def test_false_when_file_missing(self, mock_creds):
        mock_creds.exists.return_value = False
        assert config._has_claude_max_credentials() is False

    @patch("verticals.config.CLAUDE_CREDENTIALS")
    def test_true_with_access_token(self, mock_creds):
        mock_creds.exists.return_value = True
        mock_creds.read_text.return_value = json.dumps(
            {"claudeAiOauth": {"accessToken": "tok"}}
        )
        assert config._has_claude_max_credentials() is True

    @patch("verticals.config.CLAUDE_CREDENTIALS")
    def test_false_without_access_token(self, mock_creds):
        mock_creds.exists.return_value = True
        mock_creds.read_text.return_value = json.dumps({"claudeAiOauth": {}})
        assert config._has_claude_max_credentials() is False

    @patch("verticals.config.CLAUDE_CREDENTIALS")
    def test_false_on_bad_json(self, mock_creds):
        mock_creds.exists.return_value = True
        mock_creds.read_text.return_value = "not json"
        assert config._has_claude_max_credentials() is False


class TestCallClaudeCli:
    def test_raises_when_cli_missing(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="claude CLI not found"):
                config.call_claude_cli("hi")

    def test_returns_stripped_stdout(self):
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("verticals.config.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="  answer  ")
            assert config.call_claude_cli("hi") == "answer"

    def test_strips_max_turns_suffix(self):
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("verticals.config.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="real answer Error: Reached max turns (3)"
            )
            assert config.call_claude_cli("hi") == "real answer"

    def test_raises_on_nonzero_returncode(self):
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("verticals.config.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="cli boom")
            with pytest.raises(RuntimeError, match="claude CLI failed"):
                config.call_claude_cli("hi")

    def test_strips_claudecode_env_var(self):
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("verticals.config.subprocess.run") as mock_run, \
             patch.dict(os.environ, {"CLAUDECODE": "1", "PATH": "/usr/bin"}, clear=True):
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            config.call_claude_cli("hi")
            _, kwargs = mock_run.call_args
            assert "CLAUDECODE" not in kwargs["env"]
            assert kwargs["env"]["PATH"] == "/usr/bin"


class TestGetAnthropicClient:
    def test_returns_client_with_key(self):
        fake_anthropic = MagicMock()
        with patch.dict(sys.modules, {"anthropic": fake_anthropic}), \
             patch("verticals.config.get_anthropic_key", return_value="sk-ant"):
            client = config.get_anthropic_client()
        fake_anthropic.Anthropic.assert_called_once_with(api_key="sk-ant")
        assert client is fake_anthropic.Anthropic.return_value

    def test_returns_none_without_key(self):
        fake_anthropic = MagicMock()
        with patch.dict(sys.modules, {"anthropic": fake_anthropic}), \
             patch("verticals.config.get_anthropic_key", return_value=""):
            assert config.get_anthropic_client() is None


class TestGetClaudeBackend:
    def test_api_when_key_present(self):
        with patch("verticals.config.get_anthropic_key", return_value="sk-ant"):
            assert config.get_claude_backend() == "api"

    def test_cli_when_max_available(self):
        with patch("verticals.config.get_anthropic_key", return_value=""), \
             patch("verticals.config.has_claude_cli", return_value=True), \
             patch("verticals.config._has_claude_max_credentials", return_value=True):
            assert config.get_claude_backend() == "cli"

    def test_raises_when_nothing_available(self):
        with patch("verticals.config.get_anthropic_key", return_value=""), \
             patch("verticals.config.has_claude_cli", return_value=False), \
             patch("verticals.config._has_claude_max_credentials", return_value=False):
            with pytest.raises(RuntimeError, match="No Claude access found"):
                config.get_claude_backend()


class TestGetYoutubeTokenPath:
    def test_returns_path_when_exists(self, tmp_path):
        (tmp_path / "youtube_token.json").write_text("{}")
        with patch("verticals.config.SKILL_DIR", tmp_path):
            assert config.get_youtube_token_path() == tmp_path / "youtube_token.json"

    def test_raises_when_missing(self, tmp_path):
        with patch("verticals.config.SKILL_DIR", tmp_path):
            with pytest.raises(FileNotFoundError, match="YouTube OAuth token not found"):
                config.get_youtube_token_path()


class TestSaveConfig:
    def test_writes_json_with_restricted_perms(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("verticals.config.SKILL_DIR", tmp_path), \
             patch("verticals.config.CONFIG_FILE", cfg_file):
            config.save_config({"A": "1", "B": "2"})
        assert json.loads(cfg_file.read_text()) == {"A": "1", "B": "2"}
        assert stat.S_IMODE(cfg_file.stat().st_mode) == 0o600

    def test_roundtrip_with_load_config(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("verticals.config.SKILL_DIR", tmp_path), \
             patch("verticals.config.CONFIG_FILE", cfg_file):
            config.save_config({"KEY": "val"})
            assert config.load_config() == {"KEY": "val"}


class TestRunSetup:
    def test_saves_entered_keys_and_exits(self, tmp_path):
        # Inputs, in prompt order: anthropic, elevenlabs (skipped), gemini,
        # leonardo (skipped), oauth prompt (no).
        inputs = iter(["sk-ant", "", "gem-key", "", "n"])
        with patch("verticals.config.SKILL_DIR", tmp_path), \
             patch("builtins.input", lambda _: next(inputs)), \
             patch("builtins.print"), \
             patch("verticals.config.save_config") as mock_save, \
             patch("verticals.config.subprocess.run") as mock_sub:
            with pytest.raises(SystemExit) as exc:
                config.run_setup()
        assert exc.value.code == 0
        saved = mock_save.call_args.args[0]
        assert saved["ANTHROPIC_API_KEY"] == "sk-ant"
        assert saved["GEMINI_API_KEY"] == "gem-key"
        assert "ELEVENLABS_API_KEY" not in saved  # blank input skipped
        assert "LEONARDO_API_KEY" not in saved    # blank input skipped
        mock_sub.assert_not_called()  # oauth declined

    def test_saves_leonardo_key_when_entered(self, tmp_path):
        inputs = iter(["sk-ant", "", "gem-key", "leo-key", "n"])
        with patch("verticals.config.SKILL_DIR", tmp_path), \
             patch("builtins.input", lambda _: next(inputs)), \
             patch("builtins.print"), \
             patch("verticals.config.save_config") as mock_save, \
             patch("verticals.config.subprocess.run"):
            with pytest.raises(SystemExit):
                config.run_setup()
        assert mock_save.call_args.args[0]["LEONARDO_API_KEY"] == "leo-key"

    def test_runs_oauth_when_confirmed(self, tmp_path):
        inputs = iter(["sk-ant", "el-key", "gem-key", "leo-key", "y"])
        with patch("verticals.config.SKILL_DIR", tmp_path), \
             patch("builtins.input", lambda _: next(inputs)), \
             patch("builtins.print"), \
             patch("verticals.config.save_config"), \
             patch("verticals.config.subprocess.run") as mock_sub:
            with pytest.raises(SystemExit):
                config.run_setup()
        # OAuth script is launched via subprocess (the repo ships the script).
        mock_sub.assert_called_once()
