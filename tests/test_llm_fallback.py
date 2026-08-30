"""Provider fallback — the thing that keeps the 6am job alive.

Regression cover for Aug 2026: Gemini's free tier hit its daily quota, call_llm
retried the same exhausted key three times and raised, and the scheduled run
reported success anyway. Every test here is one step of that failure.
"""

from unittest.mock import patch

import pytest

from verticals import llm


@pytest.fixture
def only_gemini_and_claude():
    """Pretend gemini and claude are configured and nothing else is."""
    with patch.object(llm, "_provider_configured",
                      side_effect=lambda n: n in ("gemini", "claude")):
        yield


class TestBuildFallbackChain:
    def test_preferred_provider_is_first(self, only_gemini_and_claude):
        with patch.object(llm, "get_provider", return_value="claude"):
            assert llm.build_fallback_chain("claude")[0] == "claude"

    def test_chain_includes_other_configured_providers(self, only_gemini_and_claude):
        with patch.object(llm, "get_provider", return_value="gemini"):
            assert llm.build_fallback_chain("gemini") == ["gemini", "claude"]

    def test_unconfigured_providers_are_skipped(self, only_gemini_and_claude):
        with patch.object(llm, "get_provider", return_value="gemini"):
            chain = llm.build_fallback_chain("gemini")
        assert "openai" not in chain
        assert "ollama" not in chain

    def test_no_duplicate_when_preferred_is_also_in_order(self, only_gemini_and_claude):
        with patch.object(llm, "get_provider", return_value="gemini"):
            chain = llm.build_fallback_chain("gemini")
        assert len(chain) == len(set(chain))


class TestCallLlmFallthrough:
    def test_returns_first_provider_result_without_calling_others(self):
        with patch.object(llm, "build_fallback_chain", return_value=["gemini", "claude"]), \
             patch.object(llm, "_call_provider", return_value="  answer  ") as call:
            assert llm.call_llm("prompt") == "  answer  "
        assert call.call_count == 1

    def test_quota_error_falls_through_to_next_provider(self):
        def flaky(provider, *a, **kw):
            if provider == "gemini":
                raise RuntimeError("Gemini API 429: quota exceeded")
            return "from claude"

        with patch.object(llm, "build_fallback_chain", return_value=["gemini", "claude"]), \
             patch.object(llm, "_call_provider", side_effect=flaky):
            assert llm.call_llm("prompt") == "from claude"

    def test_permission_denied_also_falls_through(self):
        def flaky(provider, *a, **kw):
            if provider == "gemini":
                raise RuntimeError("Gemini API 403: PERMISSION_DENIED")
            return "from claude"

        with patch.object(llm, "build_fallback_chain", return_value=["gemini", "claude"]), \
             patch.object(llm, "_call_provider", side_effect=flaky):
            assert llm.call_llm("prompt") == "from claude"

    def test_raises_only_when_every_provider_fails(self):
        with patch.object(llm, "build_fallback_chain", return_value=["gemini", "claude"]), \
             patch.object(llm, "_call_provider", side_effect=RuntimeError("down")):
            with pytest.raises(RuntimeError, match="Every configured LLM provider failed"):
                llm.call_llm("prompt")

    def test_final_error_names_each_provider_that_failed(self):
        with patch.object(llm, "build_fallback_chain", return_value=["gemini", "claude"]), \
             patch.object(llm, "_call_provider", side_effect=RuntimeError("down")):
            with pytest.raises(RuntimeError) as exc:
                llm.call_llm("prompt")
        assert "gemini" in str(exc.value)
        assert "claude" in str(exc.value)

    def test_json_mode_is_forwarded(self):
        with patch.object(llm, "build_fallback_chain", return_value=["gemini"]), \
             patch.object(llm, "_call_provider", return_value="{}") as call:
            llm.call_llm("prompt", json_mode=True)
        assert call.call_args.kwargs["json_mode"] is True


class TestThrottle:
    """Pacing keeps the free tier's requests-per-minute ceiling from 429ing."""

    def setup_method(self):
        llm._last_call_at.clear()

    def test_first_call_does_not_wait(self):
        with patch.object(llm.time, "sleep") as slept:
            llm._throttle("gemini")
        slept.assert_not_called()

    def test_second_call_waits_for_the_gap(self):
        with patch.object(llm.time, "sleep") as slept:
            llm._throttle("gemini")
            llm._throttle("gemini")
        assert slept.called
        assert slept.call_args[0][0] > 0

    def test_unthrottled_provider_never_waits(self):
        with patch.object(llm.time, "sleep") as slept:
            llm._throttle("claude")
            llm._throttle("claude")
        slept.assert_not_called()

    def test_providers_are_paced_independently(self):
        with patch.object(llm.time, "sleep") as slept:
            llm._throttle("gemini")
            llm._throttle("openai")
        slept.assert_not_called()


class TestExhaustion:
    """A dead quota is learned once per run, not once per topic."""

    def setup_method(self):
        llm.reset_exhausted()

    def teardown_method(self):
        llm.reset_exhausted()

    def test_quota_error_is_not_retried(self):
        """Retrying a 429 spends another of the day's 20 requests for nothing."""
        with patch.object(llm, "_dispatch",
                          side_effect=RuntimeError("Gemini API 429: quota exceeded")) as d, \
             patch.object(llm.time, "sleep"):
            with pytest.raises(llm.ProviderExhausted):
                llm._call_provider("gemini", "p", 100)
        assert d.call_count == 1

    def test_transient_error_is_retried(self):
        with patch.object(llm, "_dispatch",
                          side_effect=RuntimeError("connection reset")) as d, \
             patch.object(llm.time, "sleep"):
            with pytest.raises(RuntimeError):
                llm._call_provider("gemini", "p", 100)
        assert d.call_count == 3

    def test_exhausted_provider_is_skipped_on_later_calls(self):
        with patch.object(llm, "build_fallback_chain", return_value=["gemini"]), \
             patch.object(llm, "_call_provider",
                          side_effect=llm.ProviderExhausted("gemini exhausted")) as call:
            with pytest.raises(RuntimeError):
                llm.call_llm("first")
            with pytest.raises(RuntimeError, match="out of quota for this run"):
                llm.call_llm("second")
        # Only the first call reached the provider; the second short-circuited.
        assert call.call_count == 1

    def test_exhaustion_falls_through_to_a_live_provider(self):
        def dispatch(provider, *a, **kw):
            if provider == "gemini":
                raise RuntimeError("Gemini API 429: quota exceeded")
            return "from claude"

        with patch.object(llm, "build_fallback_chain", return_value=["gemini", "claude"]), \
             patch.object(llm, "_dispatch", side_effect=dispatch), \
             patch.object(llm.time, "sleep"):
            assert llm.call_llm("p") == "from claude"
        assert "gemini" in llm._exhausted


class TestJsonModeReachesClaude:
    """score.py asks every provider for JSON; only Gemini was ever told.

    call_llm(json_mode=True) was forwarded to _call_gemini and silently dropped
    for Claude, which then returned its JSON wrapped in a ```json fence that the
    parser had to strip. Claude cannot be configured the way Gemini is —
    `temperature` is deprecated on this model and prefill is unsupported, both
    hard 400s — so the instruction is the only available lever.
    """

    def test_dispatch_forwards_json_mode_to_claude(self):
        with patch.object(llm, "_throttle"), \
             patch.object(llm, "_call_claude", return_value="{}") as claude:
            llm._dispatch("claude", "p", 1024, json_mode=True)
        assert claude.call_args.kwargs.get("json_mode") is True

    def test_dispatch_defaults_json_mode_off(self):
        with patch.object(llm, "_throttle"), \
             patch.object(llm, "_call_claude", return_value="{}") as claude:
            llm._dispatch("claude", "p", 1024)
        assert claude.call_args.kwargs.get("json_mode") is False

    def test_json_mode_appends_an_instruction_to_the_prompt(self):
        sent = {}

        class FakeMsg:
            stop_reason = "end_turn"
            content = [type("B", (), {"type": "text", "text": "{}"})()]

        class FakeClient:
            class messages:
                @staticmethod
                def create(**kw):
                    sent.update(kw)
                    return FakeMsg()

        with patch.object(llm, "get_claude_backend", return_value="api"), \
             patch.object(llm, "get_anthropic_client", return_value=FakeClient()):
            llm._call_claude("SCORE THIS", 1024, json_mode=True)
        text = sent["messages"][0]["content"]
        assert text.startswith("SCORE THIS")
        assert "single valid JSON object" in text

    def test_prompt_is_untouched_without_json_mode(self):
        sent = {}

        class FakeMsg:
            stop_reason = "end_turn"
            content = [type("B", (), {"type": "text", "text": "{}"})()]

        class FakeClient:
            class messages:
                @staticmethod
                def create(**kw):
                    sent.update(kw)
                    return FakeMsg()

        with patch.object(llm, "get_claude_backend", return_value="api"), \
             patch.object(llm, "get_anthropic_client", return_value=FakeClient()):
            llm._call_claude("SCORE THIS", 1024)
        assert sent["messages"][0]["content"] == "SCORE THIS"
