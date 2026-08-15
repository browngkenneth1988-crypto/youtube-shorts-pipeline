"""Tests for verticals/llm.py — provider resolution and call routing."""

from unittest.mock import MagicMock, patch

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


class TestCallClaude:
    def test_cli_backend_delegates(self):
        with patch("verticals.llm.get_claude_backend", return_value="cli"), \
             patch("verticals.llm.call_claude_cli", return_value="cli-answer") as cli:
            assert llm._call_claude("hi", 100) == "cli-answer"
            cli.assert_called_once_with("hi", max_tokens=100)

    def test_api_backend_calls_client(self):
        client = MagicMock()
        client.messages.create.return_value = MagicMock(content=[MagicMock(text="  api-answer  ")])
        with patch("verticals.llm.get_claude_backend", return_value="api"), \
             patch("verticals.llm.get_anthropic_client", return_value=client):
            assert llm._call_claude("hi", 100) == "api-answer"
        assert client.messages.create.call_args.kwargs["max_tokens"] == 100


class TestCallGemini:
    def test_missing_key_raises(self):
        with patch("verticals.llm.get_gemini_key", return_value=""):
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY not set"):
                llm._call_gemini("hi", 100)

    def test_success_joins_parts(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Hello"}, {"text": "world"}]}}]
        }
        with patch("verticals.llm.get_gemini_key", return_value="k"), \
             patch("requests.post", return_value=resp):
            assert llm._call_gemini("hi", 100) == "Hello world"

    def test_non_200_raises(self):
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "rate limited"
        with patch("verticals.llm.get_gemini_key", return_value="k"), \
             patch("requests.post", return_value=resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="Gemini API 429"):
                llm._call_gemini("hi", 100)

    def test_empty_response_raises(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"candidates": [{"content": {"parts": []}}]}
        with patch("verticals.llm.get_gemini_key", return_value="k"), \
             patch("requests.post", return_value=resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="Empty response"):
                llm._call_gemini("hi", 100)


class TestCallOpenAI:
    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("verticals.config.load_config", return_value={}):
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY not set"):
                llm._call_openai("hi", 100)

    def test_success_returns_content(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": "  gpt answer  "}}]}
        with patch("requests.post", return_value=resp):
            assert llm._call_openai("hi", 100) == "gpt answer"

    def test_non_200_raises(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "server error"
        with patch("requests.post", return_value=resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="OpenAI API 500"):
                llm._call_openai("hi", 100)


class TestCallOllama:
    def _tags(self, models):
        tags = MagicMock()
        tags.json.return_value = {"models": [{"name": m} for m in models]}
        return tags

    def test_not_running_raises(self):
        with patch("requests.get", side_effect=OSError("refused")), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="Ollama not running"):
                llm._call_ollama("hi")

    def test_no_models_raises(self):
        with patch("requests.get", return_value=self._tags([])), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="No Ollama models"):
                llm._call_ollama("hi")

    def test_picks_preferred_model_and_returns_response(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"response": "  ollama answer  "}
        with patch("requests.get", return_value=self._tags(["mistral", "llama3.1:8b"])), \
             patch("requests.post", return_value=post_resp) as mock_post:
            assert llm._call_ollama("hi") == "ollama answer"
        # llama3.1:8b outranks mistral in the preference order.
        assert mock_post.call_args.kwargs["json"]["model"] == "llama3.1:8b"

    def test_falls_back_to_first_model(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"response": "ans"}
        with patch("requests.get", return_value=self._tags(["exotic-model:1b"])), \
             patch("requests.post", return_value=post_resp) as mock_post:
            llm._call_ollama("hi")
        assert mock_post.call_args.kwargs["json"]["model"] == "exotic-model:1b"

    def test_generate_non_200_raises(self):
        post_resp = MagicMock()
        post_resp.status_code = 500
        post_resp.text = "boom"
        with patch("requests.get", return_value=self._tags(["mistral"])), \
             patch("requests.post", return_value=post_resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="Ollama 500"):
                llm._call_ollama("hi")
