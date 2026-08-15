"""Tests for the remaining topic sources: newsapi, rss, twitter, google_trends, tiktok.

(base, manual, and reddit are covered in test_topics.py.)
"""

import sys
from unittest.mock import MagicMock, patch

from verticals.topics.newsapi import NewsAPISource
from verticals.topics.rss import RSSSource
from verticals.topics.twitter import TwitterSource
from verticals.topics.google_trends import GoogleTrendsSource
from verticals.topics.tiktok import TikTokSource


# --------------------------------------------------------------------------- #
# NewsAPI
# --------------------------------------------------------------------------- #
class TestNewsAPISource:
    def test_unavailable_without_key(self):
        with patch("verticals.topics.newsapi.get_newsapi_key", return_value=""):
            src = NewsAPISource()
            assert src.is_available is False
            assert src.fetch_topics() == []  # short-circuits, no request

    def test_available_with_key(self):
        with patch("verticals.topics.newsapi.get_newsapi_key", return_value="k"):
            assert NewsAPISource().is_available is True

    def test_niche_maps_to_query(self):
        with patch("verticals.topics.newsapi.get_newsapi_key", return_value="k"), \
             patch("verticals.topics.newsapi.requests.get") as mock_get:
            mock_get.return_value = MagicMock()
            mock_get.return_value.json.return_value = {"articles": []}
            NewsAPISource({"niche": "gaming"}).fetch_topics()
            _, kwargs = mock_get.call_args
            assert kwargs["params"]["q"] == "gaming video games"

    def test_explicit_query_overrides_niche(self):
        with patch("verticals.topics.newsapi.get_newsapi_key", return_value="k"), \
             patch("verticals.topics.newsapi.requests.get") as mock_get:
            mock_get.return_value = MagicMock()
            mock_get.return_value.json.return_value = {"articles": []}
            NewsAPISource({"niche": "gaming", "query": "custom"}).fetch_topics()
            _, kwargs = mock_get.call_args
            assert kwargs["params"]["q"] == "custom"

    def test_api_key_sent_via_header_not_url(self):
        with patch("verticals.topics.newsapi.get_newsapi_key", return_value="secret"), \
             patch("verticals.topics.newsapi.requests.get") as mock_get:
            mock_get.return_value = MagicMock()
            mock_get.return_value.json.return_value = {"articles": []}
            NewsAPISource().fetch_topics()
            _, kwargs = mock_get.call_args
            assert kwargs["headers"]["X-Api-Key"] == "secret"
            assert "apiKey" not in kwargs["params"]

    def test_pagesize_capped_at_20(self):
        with patch("verticals.topics.newsapi.get_newsapi_key", return_value="k"), \
             patch("verticals.topics.newsapi.requests.get") as mock_get:
            mock_get.return_value = MagicMock()
            mock_get.return_value.json.return_value = {"articles": []}
            NewsAPISource().fetch_topics(limit=100)
            _, kwargs = mock_get.call_args
            assert kwargs["params"]["pageSize"] == 20

    def test_parses_articles_with_decaying_score(self):
        articles = [
            {"title": "First", "description": "d1", "url": "u1"},
            {"title": "Second", "description": "d2", "url": "u2"},
        ]
        with patch("verticals.topics.newsapi.get_newsapi_key", return_value="k"), \
             patch("verticals.topics.newsapi.requests.get") as mock_get:
            resp = MagicMock()
            resp.json.return_value = {"articles": articles}
            mock_get.return_value = resp
            topics = NewsAPISource().fetch_topics()
        assert [t.title for t in topics] == ["First", "Second"]
        assert topics[0].trending_score == 1.0
        assert topics[0].trending_score > topics[1].trending_score
        assert topics[0].url == "u1"

    def test_skips_removed_and_empty_titles(self):
        articles = [
            {"title": "[Removed]", "url": "u"},
            {"title": "   ", "url": "u"},
            {"title": None, "url": "u"},
            {"title": "Real", "url": "u"},
        ]
        with patch("verticals.topics.newsapi.get_newsapi_key", return_value="k"), \
             patch("verticals.topics.newsapi.requests.get") as mock_get:
            resp = MagicMock()
            resp.json.return_value = {"articles": articles}
            mock_get.return_value = resp
            topics = NewsAPISource().fetch_topics()
        assert [t.title for t in topics] == ["Real"]

    def test_fetch_handles_request_error(self):
        with patch("verticals.topics.newsapi.get_newsapi_key", return_value="k"), \
             patch("verticals.topics.newsapi.requests.get", side_effect=Exception("boom")):
            assert NewsAPISource().fetch_topics() == []


# --------------------------------------------------------------------------- #
# RSS
# --------------------------------------------------------------------------- #
class TestRSSSource:
    def test_default_feed(self):
        assert RSSSource().feeds == ["https://hnrss.org/frontpage"]

    def test_custom_feeds(self):
        src = RSSSource({"feeds": ["https://a.com/rss", "https://b.com/rss"]})
        assert src.feeds == ["https://a.com/rss", "https://b.com/rss"]

    def test_is_available_when_feedparser_installed(self):
        # feedparser is a project dependency and installed in the test env.
        assert RSSSource().is_available is True

    def test_parses_entries(self):
        feed = MagicMock()
        feed.feed.get.return_value = "Hacker News"
        feed.entries = [
            {"title": "Post A", "summary": "sum a", "link": "https://a"},
            {"title": "Post B", "summary": "sum b", "link": "https://b"},
        ]
        with patch("feedparser.parse", return_value=feed):
            topics = RSSSource({"feeds": ["https://x/rss"]}).fetch_topics(limit=10)
        assert len(topics) == 2
        assert topics[0].title == "Post A"
        assert topics[0].trending_score == 0.5
        assert topics[0].source.startswith("rss/")

    def test_respects_limit_across_feeds(self):
        feed = MagicMock()
        feed.feed.get.return_value = "F"
        feed.entries = [{"title": f"E{i}", "summary": "", "link": ""} for i in range(10)]
        with patch("feedparser.parse", return_value=feed):
            # two feeds, limit 4 -> per_feed = 2 each -> 4 total
            topics = RSSSource({"feeds": ["u1", "u2"]}).fetch_topics(limit=4)
        assert len(topics) == 4

    def test_bad_feed_is_skipped(self):
        with patch("feedparser.parse", side_effect=Exception("parse error")):
            topics = RSSSource({"feeds": ["u1"]}).fetch_topics()
        assert topics == []


# --------------------------------------------------------------------------- #
# Twitter
# --------------------------------------------------------------------------- #
class TestTwitterSource:
    def test_disabled_by_default(self):
        assert TwitterSource().is_available is False

    def test_enabled_via_config(self):
        assert TwitterSource({"enabled": True}).is_available is True

    def test_parses_trends(self):
        with patch("verticals.topics.twitter.requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "data": [
                    {"trend_name": "#Trending", "tweet_count": 5000},
                    {"trend_name": "#Second", "tweet_count": 100},
                ]
            }
            mock_get.return_value = resp
            topics = TwitterSource({"enabled": True}).fetch_topics(limit=10)
        assert [t.title for t in topics] == ["#Trending", "#Second"]
        assert topics[0].trending_score == 0.7
        assert topics[0].metadata["tweet_count"] == 5000

    def test_non_200_returns_empty_fallback(self):
        with patch("verticals.topics.twitter.requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 429
            mock_get.return_value = resp
            assert TwitterSource({"enabled": True}).fetch_topics() == []

    def test_exception_returns_empty_fallback(self):
        with patch("verticals.topics.twitter.requests.get", side_effect=Exception("blocked")):
            assert TwitterSource({"enabled": True}).fetch_topics() == []


# --------------------------------------------------------------------------- #
# Google Trends
# --------------------------------------------------------------------------- #
class TestGoogleTrendsSource:
    def test_default_geo(self):
        assert GoogleTrendsSource().geo == "IN"

    def test_custom_geo(self):
        assert GoogleTrendsSource({"geo": "US"}).geo == "US"

    def test_is_available_false_without_pytrends(self):
        # pytrends is not installed in the test environment.
        assert GoogleTrendsSource().is_available is False

    def test_geo_to_pn_mapping(self):
        assert GoogleTrendsSource({"geo": "US"})._geo_to_pn() == "united_states"
        assert GoogleTrendsSource({"geo": "GB"})._geo_to_pn() == "united_kingdom"
        # Unknown geo falls back to india.
        assert GoogleTrendsSource({"geo": "ZZ"})._geo_to_pn() == "india"

    def test_fetch_parses_trending_searches(self):
        # Build a fake pytrends module so the lazy import resolves to our mock.
        trending = MagicMock()
        trending.head.return_value.iterrows.return_value = [
            (0, ["Topic One"]),
            (1, ["Topic Two"]),
        ]
        instance = MagicMock()
        instance.trending_searches.return_value = trending
        trendreq_cls = MagicMock(return_value=instance)

        fake_request = MagicMock(TrendReq=trendreq_cls)
        modules = {
            "pytrends": MagicMock(request=fake_request),
            "pytrends.request": fake_request,
        }
        with patch.dict(sys.modules, modules):
            topics = GoogleTrendsSource({"geo": "US"}).fetch_topics(limit=5)

        assert [t.title for t in topics] == ["Topic One", "Topic Two"]
        assert topics[0].source == "google_trends"
        assert topics[0].trending_score == 1.0
        assert topics[0].trending_score > topics[1].trending_score
        # geo "US" is translated for the pytrends call.
        instance.trending_searches.assert_called_once_with(pn="united_states")


# --------------------------------------------------------------------------- #
# TikTok (stub source)
# --------------------------------------------------------------------------- #
class TestTikTokSource:
    def test_disabled_by_default(self):
        assert TikTokSource().is_available is False

    def test_enabled_via_config(self):
        assert TikTokSource({"enabled": True}).is_available is True

    def test_fetch_returns_empty_stub(self):
        assert TikTokSource({"enabled": True}).fetch_topics() == []
