"""Tests for verticals/llm.py — provider resolution and call routing."""

from unittest.mock import patch

import pytest

from verticals import llm


class TestGetProvider:
    def test_explicit_name_wins(self):
        # An explicit provider name short-circuits everything else.
        assert llm.get_provider("openai") == "openai"

    def test_explicit_name_is_lowercased(self):
        assert llm.get_provider("Gemini") == "gemini"

    def test_auto_falls_through_to_env(self, monkeypatch):
        # "auto" is treated as "not specified" and resolution continues.
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        assert llm.get_provider("auto") == "ollama"

    def test_env_var_used_when_no_name(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        assert llm.get_provider(None) == "openai"

    def test_env_var_is_lowercased(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "CLAUDE")
        assert llm.get_provider(None) == "claude"

    def test_config_used_when_no_name_or_env(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        with patch("verticals.config.load_config", return_value={"LLM_PROVIDER": "gemini"}):
            assert llm.get_provider(None) == "gemini"

    def test_env_takes_priority_over_config(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        with patch("verticals.config.load_config", return_value={"LLM_PROVIDER": "gemini"}):
            assert llm.get_provider(None) == "openai"

    def test_autodetect_prefers_claude(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.llm.get_anthropic_key", return_value="sk-ant-xxx"), \
             patch("verticals.llm.get_gemini_key", return_value="gem-xxx"):
            assert llm.get_provider(None) == "claude"

    def test_autodetect_falls_to_gemini(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.llm.get_anthropic_key", return_value=""), \
             patch("verticals.llm.get_gemini_key", return_value="gem-xxx"):
            assert llm.get_provider(None) == "gemini"

    def test_autodetect_falls_to_openai(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.llm.get_anthropic_key", return_value=""), \
             patch("verticals.llm.get_gemini_key", return_value=""):
            assert llm.get_provider(None) == "openai"

    def test_autodetect_falls_to_ollama(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.llm.get_anthropic_key", return_value=""), \
             patch("verticals.llm.get_gemini_key", return_value=""), \
             patch("verticals.llm._ollama_available", return_value=True):
            assert llm.get_provider(None) == "ollama"

    def test_last_resort_claude_cli(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.llm.get_anthropic_key", return_value=""), \
             patch("verticals.llm.get_gemini_key", return_value=""), \
             patch("verticals.llm._ollama_available", return_value=False), \
             patch("verticals.config.has_claude_cli", return_value=True):
            assert llm.get_provider(None) == "claude_cli"

    def test_no_provider_raises(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("verticals.config.load_config", return_value={}), \
             patch("verticals.llm.get_anthropic_key", return_value=""), \
             patch("verticals.llm.get_gemini_key", return_value=""), \
             patch("verticals.llm._ollama_available", return_value=False), \
             patch("verticals.config.has_claude_cli", return_value=False):
            with pytest.raises(RuntimeError, match="No LLM provider found"):
                llm.get_provider(None)


class TestCallLlmRouting:
    """call_llm should dispatch to the correct provider backend."""

    def test_routes_to_claude(self):
        with patch("verticals.llm.get_provider", return_value="claude"), \
             patch("verticals.llm._call_claude", return_value="claude-out") as mock_claude:
            assert llm.call_llm("hi", max_tokens=100) == "claude-out"
            mock_claude.assert_called_once_with("hi", 100)

    def test_routes_to_gemini(self):
        with patch("verticals.llm.get_provider", return_value="gemini"), \
             patch("verticals.llm._call_gemini", return_value="gemini-out") as mock_gemini:
            assert llm.call_llm("hi") == "gemini-out"
            mock_gemini.assert_called_once()

    def test_routes_to_openai(self):
        with patch("verticals.llm.get_provider", return_value="openai"), \
             patch("verticals.llm._call_openai", return_value="openai-out") as mock_openai:
            assert llm.call_llm("hi") == "openai-out"
            mock_openai.assert_called_once()

    def test_routes_to_ollama(self):
        with patch("verticals.llm.get_provider", return_value="ollama"), \
             patch("verticals.llm._call_ollama", return_value="ollama-out") as mock_ollama:
            assert llm.call_llm("hi") == "ollama-out"
            mock_ollama.assert_called_once_with("hi")

    def test_routes_to_claude_cli(self):
        with patch("verticals.llm.get_provider", return_value="claude_cli"), \
             patch("verticals.llm.call_claude_cli", return_value="cli-out") as mock_cli:
            assert llm.call_llm("hi", max_tokens=200) == "cli-out"
            mock_cli.assert_called_once_with("hi", max_tokens=200)

    def test_unknown_provider_raises(self):
        # with_retry wraps the call; the ValueError surfaces after retries.
        # Patch sleep so the backoff delays don't slow the test.
        with patch("verticals.llm.get_provider", return_value="bogus"), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(ValueError, match="Unknown LLM provider"):
                llm.call_llm("hi")


class TestOllamaAvailable:
    def test_available_when_200(self):
        # _ollama_available imports requests locally, so patch the real module.
        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            assert llm._ollama_available() is True

    def test_unavailable_on_exception(self):
        with patch("requests.get", side_effect=OSError("refused")):
            assert llm._ollama_available() is False
