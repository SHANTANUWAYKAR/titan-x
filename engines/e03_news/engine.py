"""
Module: engine.py
Description: Engine 07 — News Intelligence (financial RSS ingestion +
             full-article extraction).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-14
"""

import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import feedparser

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

# Public financial RSS feeds -- no API key required. Curated for breadth
# across general markets/macro news sources.
DEFAULT_FEEDS: dict[str, str] = {
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "cnbc_markets": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "investing_com": "https://www.investing.com/rss/news_25.rss",
    "marketwatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
}


@dataclass
class NewsItem:
    """A single ingested news item."""

    title: str
    link: str
    source: str
    published: Optional[datetime]
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "link": self.link,
            "source": self.source,
            "published": self.published.isoformat() if self.published else None,
            "summary": self.summary,
        }


class NewsIntelligenceEngine(BaseEngine):
    """
    News Intelligence Engine — financial news ingestion.

    Pulls headlines from public financial RSS feeds (no API key required)
    and, on request, extracts full article text via newspaper3k.

    Deliberately scoped to ingestion/extraction only -- sentiment scoring
    is E09 Sentiment Intelligence's job, not this engine's, matching the
    same separation of concerns the platform's other engines use (e.g.
    E02 Market Data fetches OHLCV, E06 Technical Analysis scores it).
    """

    engine_id = "e03_news"
    engine_name = "News Intelligence Engine"
    version = "1.0.0"

    def __init__(self, feeds: Optional[dict[str, str]] = None) -> None:
        super().__init__()
        self.feeds = feeds or DEFAULT_FEEDS

    def initialize(self) -> EngineResult:
        """Initialize the news engine (stateless -- nothing to warm up)."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(
            success=True,
            message="News Intelligence Engine initialized",
            metadata={"feeds": list(self.feeds.keys())},
        )

    def health_check(self) -> EngineResult:
        """Verify at least one configured feed is reachable."""
        try:
            for source, url in self.feeds.items():
                parsed = feedparser.parse(url)
                if getattr(parsed, "bozo", 1) == 0 and parsed.entries:
                    return EngineResult(success=True, message=f"Healthy ({source} reachable)")
            return EngineResult(success=False, message="No configured feed returned entries")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def fetch_headlines(
        self,
        limit_per_feed: int = 10,
        sources: Optional[list[str]] = None,
        as_of: Optional[datetime] = None,
    ) -> EngineResult:
        """
        Fetch latest headlines from configured RSS feeds.

        Args:
            limit_per_feed: Max items to keep per feed.
            sources: Optional subset of configured feed names to query
                (defaults to all configured feeds).
            as_of: Lookahead-safety guard (docs/UPGRADE_BRIEF.md Phase 11).
                When given, any item whose published (source-claimed) time
                is strictly after as_of is dropped -- a point-in-time cut
                for future backtesting use. Nothing in this codebase wires
                news/sentiment into backtesting today (confirmed: E24/E26
                never call generate_signal or touch news/sentiment), so
                this guard is currently dormant, but the brief requires the
                capability to exist before that wiring is ever added rather
                than being retrofitted under time pressure later. Items
                with no published time are always kept -- there's no
                timestamp to compare, so dropping them would be a guess,
                not a genuine lookahead prevention.

        Returns:
            EngineResult with a list[NewsItem] in data, newest first. A
            single feed failing (network hiccup, feed schema change) is
            logged and skipped -- doesn't fail the whole fetch.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            targets = {k: v for k, v in self.feeds.items() if not sources or k in sources}
            if not targets:
                return EngineResult(success=False, message="No matching feed sources configured")

            items: list[NewsItem] = []
            for source, url in targets.items():
                try:
                    parsed = feedparser.parse(url)
                    for entry in parsed.entries[:limit_per_feed]:
                        items.append(
                            NewsItem(
                                title=entry.get("title", ""),
                                link=entry.get("link", ""),
                                source=source,
                                published=self._parse_published(entry),
                                summary=entry.get("summary", ""),
                            )
                        )
                except Exception as e:
                    logger.warning("Feed fetch failed for %s (%s): %s", source, url, e)

            if as_of is not None:
                items = [i for i in items if i.published is None or i.published <= as_of]

            items.sort(
                key=lambda i: i.published or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=items,
                message=f"Fetched {len(items)} headline(s) from {len(targets)} feed(s)",
                metadata={"sources": list(targets.keys()), "count": len(items)},
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Headline fetch failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def extract_article(self, url: str) -> EngineResult:
        """
        Extract full article text from a URL via newspaper3k.

        Args:
            url: Article URL (typically a NewsItem.link).

        Returns:
            EngineResult with the extracted article text in data.
        """
        try:
            from newspaper import Article

            article = Article(url)
            article.download()
            article.parse()
            if not article.text:
                return EngineResult(success=False, message="No article text extracted")
            return EngineResult(
                success=True,
                data=article.text,
                message=f"Extracted {len(article.text)} character(s)",
                metadata={
                    "title": article.title,
                    "authors": article.authors,
                    "publish_date": str(article.publish_date) if article.publish_date else None,
                },
            )
        except Exception as e:
            logger.warning("Article extraction failed for %s: %s", url, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _parse_published(entry) -> Optional[datetime]:
        """Parse a feed entry's published time to an aware UTC datetime."""
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if not parsed_time:
            return None
        try:
            # feedparser normalizes *_parsed to a UTC struct_time already --
            # time.mktime() wrongly treats it as local time and shifts it by
            # the server's UTC offset; calendar.timegm() is the UTC-correct
            # inverse of time.gmtime().
            return datetime.fromtimestamp(calendar.timegm(parsed_time), tz=timezone.utc)
        except (OverflowError, ValueError, TypeError):
            return None
