"""Tests for verticals/topics/engine.py — TopicEngine source loading, discovery, auto-pick."""

from unittest.mock import MagicMock, patch

from verticals.topics.base import TopicCandidate
from verticals.topics.engine import TopicEngine


class FakeSource:
    """Minimal stand-in for a TopicSource used in discover() tests."""

    def __init__(self, name, topics=None, available=True, error=None):
        self.name = name
        self._topics = topics or []
        self.is_available = available
        self._error = error

    def fetch_topics(self, limit=10):
        if self._error:
            raise self._error
        return self._topics


def make_engine(config=None, niche="general"):
    """Build a TopicEngine with load_config patched so no real config.json is read."""
    with patch("verticals.topics.engine.load_config", return_value=config or {}):
        return TopicEngine(niche=niche)


# --------------------------------------------------------------------------- #
# _load_sources
# --------------------------------------------------------------------------- #
class TestLoadSources:
    def test_default_sources_for_general(self):
        engine = make_engine()
        names = {s.name for s in engine._sources}
        # reddit, rss, google_trends, newsapi are on by default; twitter/tiktok off.
        assert {"reddit", "rss", "google_trends", "newsapi"} <= names
        assert "twitter" not in names
        assert "tiktok" not in names

    def test_none_niche_defaults_to_general(self):
        engine = make_engine(niche=None)
        assert engine._niche == "general"

    def test_twitter_enabled_via_config(self):
        engine = make_engine({"topic_sources": {"twitter": {"enabled": True}}})
        assert "twitter" in {s.name for s in engine._sources}

    def test_reddit_disabled_via_config(self):
        engine = make_engine({"topic_sources": {"reddit": {"enabled": False}}})
        assert "reddit" not in {s.name for s in engine._sources}

    def test_niche_applies_reddit_subreddits(self):
        # Assert the wiring, not the contents of niches/gaming.yaml. This used
        # to hardcode ["gaming", "pcgaming"] and broke the moment the profile
        # was tuned — a data edit should not fail a plumbing test.
        from verticals.niche import get_discovery_config, load_niche

        expected = get_discovery_config(load_niche("gaming"))["reddit"]["subreddits"]
        engine = make_engine(niche="gaming")
        reddit = next(s for s in engine._sources if s.name == "reddit")
        assert reddit.subreddits == expected
        assert "gaming" in reddit.subreddits  # profile actually populated

    def test_user_subreddits_override_niche_defaults(self):
        engine = make_engine(
            {"topic_sources": {"reddit": {"subreddits": ["custom"]}}}, niche="gaming"
        )
        reddit = next(s for s in engine._sources if s.name == "reddit")
        assert reddit.subreddits == ["custom"]

    def test_niche_applies_newsapi_niche(self):
        engine = make_engine(niche="gaming")
        newsapi = next(s for s in engine._sources if s.name == "newsapi")
        assert newsapi._niche == "gaming"

    def test_source_init_failure_is_caught(self):
        # A source whose constructor throws must not abort loading the rest.
        with patch("verticals.topics.reddit.RedditSource", side_effect=RuntimeError("boom")):
            engine = make_engine()
        names = {s.name for s in engine._sources}
        assert "reddit" not in names
        assert "rss" in names  # others still loaded


# --------------------------------------------------------------------------- #
# discover
# --------------------------------------------------------------------------- #
class TestDiscover:
    def test_aggregates_and_sorts_by_score(self):
        engine = make_engine()
        engine._sources = [
            FakeSource("a", [TopicCandidate("Low", "a", trending_score=0.2)]),
            FakeSource("b", [TopicCandidate("High", "b", trending_score=0.9)]),
            FakeSource("c", [TopicCandidate("Mid", "c", trending_score=0.5)]),
        ]
        topics = engine.discover(limit=10)
        assert [t.title for t in topics] == ["High", "Mid", "Low"]

    def test_deduplicates_by_title(self):
        engine = make_engine()
        engine._sources = [
            FakeSource("a", [TopicCandidate("Same Topic", "a", trending_score=0.9)]),
            FakeSource("b", [TopicCandidate("  same topic  ", "b", trending_score=0.3)]),
        ]
        topics = engine.discover(limit=10)
        assert len(topics) == 1
        # First-seen wins (source "a" here, whichever completes first is kept).
        assert topics[0].title.strip().lower() == "same topic"

    def test_dedup_uses_first_50_chars(self):
        long_a = "X" * 60 + "AAA"
        long_b = "X" * 60 + "BBB"  # differs only after char 50 -> treated as dup
        engine = make_engine()
        engine._sources = [
            FakeSource("a", [TopicCandidate(long_a, "a", trending_score=0.9)]),
            FakeSource("b", [TopicCandidate(long_b, "b", trending_score=0.8)]),
        ]
        topics = engine.discover(limit=10)
        assert len(topics) == 1

    def test_respects_limit(self):
        engine = make_engine()
        engine._sources = [
            FakeSource("a", [
                TopicCandidate(f"T{i}", "a", trending_score=i / 10) for i in range(10)
            ])
        ]
        topics = engine.discover(limit=3)
        assert len(topics) == 3

    def test_skips_unavailable_sources(self):
        engine = make_engine()
        engine._sources = [
            FakeSource("on", [TopicCandidate("Kept", "on", trending_score=0.5)]),
            FakeSource("off", [TopicCandidate("Skipped", "off", trending_score=0.9)], available=False),
        ]
        topics = engine.discover(limit=10)
        assert [t.title for t in topics] == ["Kept"]

    def test_source_error_does_not_break_discovery(self):
        engine = make_engine()
        engine._sources = [
            FakeSource("bad", error=RuntimeError("fetch failed")),
            FakeSource("good", [TopicCandidate("Survivor", "good", trending_score=0.5)]),
        ]
        topics = engine.discover(limit=10)
        assert [t.title for t in topics] == ["Survivor"]

    def test_empty_when_no_sources(self):
        engine = make_engine()
        engine._sources = []
        assert engine.discover() == []


# --------------------------------------------------------------------------- #
# auto_pick
# --------------------------------------------------------------------------- #
class TestAutoPick:
    def _candidates(self):
        return [
            TopicCandidate("First topic", "reddit", trending_score=0.9),
            TopicCandidate("Second topic", "rss", trending_score=0.5),
        ]

    def test_uses_api_backend(self):
        client = MagicMock()
        client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="  First topic  ")]
        )
        with patch("verticals.topics.engine.get_claude_backend", return_value="api"), \
             patch("verticals.topics.engine.get_anthropic_client", return_value=client):
            result = TopicEngine.auto_pick(TopicEngine.__new__(TopicEngine), self._candidates())
        assert result == "First topic"  # stripped
        # Prompt includes the candidate titles.
        prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "First topic" in prompt
        assert "Second topic" in prompt

    def test_uses_cli_backend(self):
        with patch("verticals.topics.engine.get_claude_backend", return_value="cli"), \
             patch("verticals.topics.engine.call_claude_cli", return_value="Second topic") as mock_cli:
            result = TopicEngine.auto_pick(TopicEngine.__new__(TopicEngine), self._candidates())
        assert result == "Second topic"
        mock_cli.assert_called_once()
        assert mock_cli.call_args.kwargs["max_tokens"] == 200

    def test_prompt_caps_at_20_candidates(self):
        many = [TopicCandidate(f"Topic {i}", "s", trending_score=0.5) for i in range(30)]
        with patch("verticals.topics.engine.get_claude_backend", return_value="cli"), \
             patch("verticals.topics.engine.call_claude_cli", return_value="x") as mock_cli:
            TopicEngine.auto_pick(TopicEngine.__new__(TopicEngine), many)
        prompt = mock_cli.call_args.args[0]
        assert "Topic 19" in prompt   # 20th (index 19) included
        assert "Topic 20" not in prompt  # 21st excluded
