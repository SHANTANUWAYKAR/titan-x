"""Unit tests for News Intelligence Engine (E07)."""

import calendar
from datetime import datetime, timedelta, timezone

import pytest

from project_titan_x.engines.e03_news import NewsIntelligenceEngine


@pytest.fixture
def news_engine() -> NewsIntelligenceEngine:
    engine = NewsIntelligenceEngine()
    engine.initialize()
    return engine


def test_engine_initialization(news_engine: NewsIntelligenceEngine):
    result = news_engine.initialize()
    assert result.success
    assert "feeds" in result.metadata


def test_fetch_headlines_rejects_unknown_sources(news_engine: NewsIntelligenceEngine):
    result = news_engine.fetch_headlines(sources=["not_a_real_feed"])
    assert not result.success


def _struct_time_at(dt: datetime):
    return dt.utctimetuple()


def test_fetch_headlines_as_of_drops_items_published_after_the_cut(monkeypatch):
    """Phase 11 lookahead-safety guard: an as_of cut must drop items whose
    source-claimed published time is strictly after it, and keep items at
    or before it -- a synthetic, deterministic check since nothing wires
    a real as_of caller in yet (see fetch_headlines' own docstring)."""
    engine = NewsIntelligenceEngine(feeds={"fake": "http://example.invalid/rss"})
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    before = as_of - timedelta(hours=1)
    after = as_of + timedelta(hours=1)

    class _FakeParsed:
        entries = [
            {"title": "before cut", "link": "http://x/1", "published_parsed": _struct_time_at(before)},
            {"title": "at cut", "link": "http://x/2", "published_parsed": _struct_time_at(as_of)},
            {"title": "after cut", "link": "http://x/3", "published_parsed": _struct_time_at(after)},
            {"title": "no timestamp", "link": "http://x/4"},
        ]

    import project_titan_x.engines.e03_news.engine as engine_module

    monkeypatch.setattr(engine_module.feedparser, "parse", lambda url: _FakeParsed())

    result = engine.fetch_headlines(as_of=as_of)
    assert result.success
    titles = {i.title for i in result.data}
    assert titles == {"before cut", "at cut", "no timestamp"}
    assert "after cut" not in titles


def test_fetch_headlines_without_as_of_keeps_everything(monkeypatch):
    engine = NewsIntelligenceEngine(feeds={"fake": "http://example.invalid/rss"})

    class _FakeParsed:
        entries = [
            {"title": "item 1", "link": "http://x/1", "published_parsed": _struct_time_at(datetime(2026, 1, 1, tzinfo=timezone.utc))},
            {"title": "item 2", "link": "http://x/2", "published_parsed": _struct_time_at(datetime(2027, 1, 1, tzinfo=timezone.utc))},
        ]

    import project_titan_x.engines.e03_news.engine as engine_module

    monkeypatch.setattr(engine_module.feedparser, "parse", lambda url: _FakeParsed())

    result = engine.fetch_headlines()
    assert result.success
    assert len(result.data) == 2


@pytest.mark.network
def test_health_check_reaches_a_feed(news_engine: NewsIntelligenceEngine):
    result = news_engine.health_check()
    assert result.success


@pytest.mark.network
def test_fetch_headlines_returns_items(news_engine: NewsIntelligenceEngine):
    result = news_engine.fetch_headlines(limit_per_feed=3)
    assert result.success
    assert len(result.data) > 0
    item = result.data[0]
    assert item.title
    assert item.link
    assert item.source in news_engine.feeds


@pytest.mark.network
def test_extract_article_returns_text(news_engine: NewsIntelligenceEngine):
    headlines = news_engine.fetch_headlines(limit_per_feed=1, sources=["cnbc_markets"])
    assert headlines.success and headlines.data
    result = news_engine.extract_article(headlines.data[0].link)
    assert result.success
    assert len(result.data) > 0
