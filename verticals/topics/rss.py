"""RSS/Atom feed topic source."""

from ..log import log
from .base import TopicCandidate, TopicSource


class RSSSource(TopicSource):
    name = "rss"

    def __init__(self, config: dict = None):
        config = config or {}
        self.feeds = config.get("feeds", ["https://hnrss.org/frontpage"])

    @property
    def is_available(self) -> bool:
        try:
            import feedparser  # noqa: F401
            return True
        except ImportError:
            return False

    def fetch_topics(self, limit: int = 10) -> list[TopicCandidate]:
        import feedparser

        topics = []
        per_feed = max(1, limit // len(self.feeds))

        for feed_url in self.feeds:
            try:
                feed = feedparser.parse(feed_url)
                if getattr(feed, "bozo", False) and not feed.entries:
                    log(f"  rss feed unparseable ({feed_url[:60]}): {feed.bozo_exception!r}")
                if not feed.entries:
                    log(f"  rss feed empty ({feed_url[:60]}) status={getattr(feed, 'status', '?')}")
                for entry in feed.entries[:per_feed]:
                    topics.append(TopicCandidate(
                        title=entry.get("title", ""),
                        source=f"rss/{feed.feed.get('title', feed_url)[:30]}",
                        trending_score=0.5,  # RSS doesn't have scores
                        summary=entry.get("summary", "")[:200],
                        url=entry.get("link", ""),
                    ))
            except Exception as e:
                log(f"  rss feed failed ({feed_url[:60]}): {type(e).__name__}: {e}")
                continue

        if not topics:
            log(f"  rss: {len(self.feeds)} feed(s) returned nothing — {self.feeds}")
        return topics[:limit]
