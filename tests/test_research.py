"""Tests for pipeline/research.py — keyword extraction + research."""

from unittest.mock import MagicMock, patch

import pytest

from verticals import research
from verticals.config import extract_keywords


class TestExtractKeywords:
    def test_basic(self):
        result = extract_keywords("India wins VCT Pacific 2026")
        words = result.split()
        assert len(words) <= 4
        # Stopwords removed
        assert "the" not in words

    def test_removes_stopwords(self):
        result = extract_keywords("The new update is available for all users")
        words = result.split()
        assert "the" not in words
        assert "is" not in words
        assert "for" not in words
        assert "new" not in words

    def test_removes_short_words(self):
        result = extract_keywords("An AI is on a new PC")
        words = result.split()
        for w in words:
            assert len(w) > 2

    def test_strips_punctuation(self):
        result = extract_keywords('Hello, "world!" says (test)')
        words = result.split()
        for w in words:
            assert "," not in w
            assert '"' not in w
            assert "!" not in w

    def test_max_four_words(self):
        result = extract_keywords("one two three four five six seven eight nine ten")
        words = result.split()
        assert len(words) <= 4

    def test_empty_input(self):
        result = extract_keywords("")
        assert result == ""

    def test_all_stopwords(self):
        result = extract_keywords("the and or but in on at")
        assert result == ""


class TestFetchDdg:
    def test_returns_response_text(self):
        resp = MagicMock()
        resp.text = "<html>results</html>"
        with patch("verticals.research.requests.post", return_value=resp):
            assert research._fetch_ddg("keywords") == "<html>results</html>"

    def test_raises_on_http_error(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = RuntimeError("503")
        with patch("verticals.research.requests.post", return_value=resp), \
             patch("verticals.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="503"):
                research._fetch_ddg("keywords")


class TestResearchTopic:
    _HTML = (
        '<a class="result__snippet">First fact about the topic.</a>'
        '<a class="result__snippet">Second relevant fact.</a>'
    )

    def test_parses_snippets(self):
        with patch("verticals.research._fetch_ddg", return_value=self._HTML):
            out = research.research_topic("some news")
        assert "First fact about the topic." in out
        assert "Second relevant fact." in out

    def test_fallback_when_no_snippets(self):
        with patch("verticals.research._fetch_ddg", return_value="<html>nothing</html>"):
            out = research.research_topic("my headline")
        assert "my headline" in out
        assert "No live research available" in out

    def test_fallback_on_fetch_error(self):
        with patch("verticals.research._fetch_ddg", side_effect=RuntimeError("network")):
            out = research.research_topic("my headline")
        assert "my headline" in out
        assert "No live research available" in out

    def test_truncates_snippets_to_300_chars(self):
        long = "x" * 500
        html = f'<a class="result__snippet">{long}</a>'
        with patch("verticals.research._fetch_ddg", return_value=html):
            out = research.research_topic("news")
        assert "x" * 300 in out
        assert "x" * 301 not in out

    def test_caps_at_eight_snippets(self):
        html = "".join(
            f'<a class="result__snippet">snippet number {i}</a>' for i in range(20)
        )
        with patch("verticals.research._fetch_ddg", return_value=html):
            out = research.research_topic("news")
        assert out.count("snippet number") == 8
