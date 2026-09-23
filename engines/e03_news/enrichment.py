"""
Module: enrichment.py
Description: Deterministic enrichment stages for the E03 -> E09 news
             pipeline (docs/UPGRADE_BRIEF.md Phase 11): entity extraction,
             event-type classification, market-impact scoring, and
             duplicate-news detection.

             Every function here is pure keyword/hash matching against
             this platform's own known data (core.config.assets'
             SUPPORTED_ASSETS universe, a fixed event-keyword table) --
             never a trained NLP/NER/classifier model. This mirrors the
             project's own stated Phase 5 discipline ("convert subjective
             terminology into deterministic algorithms, do not implement
             vague natural-language rules") and its Rule 4 ban on
             fabricating results from data/models that don't exist here.

             Known, accepted limitation: whole-word keyword matching can
             still false-positive on short/ambiguous tickers that are also
             common words or unrelated acronyms (e.g. "ITC" the ticker vs.
             "ITC" the US International Trade Commission; "META" the
             ticker vs. "meta-analysis"). This is the same category of
             limitation engines/e51_signals/engine.py's own _NEWS_ALIASES
             mechanism already accepts for its 12-symbol macro subset --
             not a new risk class introduced here.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-09-13
"""

import hashlib
import re
from typing import Optional

from project_titan_x.core.config.assets import SUPPORTED_ASSETS

# Deterministic keyword -> symbol table covering this platform's full
# SUPPORTED_ASSETS universe (not just the 12-symbol macro subset
# e51_signals._NEWS_ALIASES uses for its own narrower confluence check --
# that mechanism is untouched by this module). Keywords are matched as
# whole words/phrases, case-insensitive, against title + summary text.
ENTITY_KEYWORDS: dict[str, list[str]] = {
    "EURUSD": ["euro"],
    "GBPUSD": ["pound", "sterling", "gbp"],
    "USDJPY": ["yen", "boj"],
    "USDINR": ["rupee", "usdinr"],
    "BTCUSD": ["bitcoin", "btc"],
    "ETHUSD": ["ethereum", "eth"],
    "GOLD": ["gold", "xauusd"],
    "SILVER": ["silver", "xagusd"],
    "CRUDE": ["crude", "oil", "wti", "opec"],
    "NIFTY50": ["nifty", "nifty50"],
    "BANKNIFTY": ["bank nifty", "banknifty"],
    "US10Y": ["treasury yield", "10-year treasury", "us10y"],
    "SP500": ["s&p 500", "s&p500", "sp500"],
    "AAPL": ["apple", "aapl"],
    "MSFT": ["microsoft", "msft"],
    "NVDA": ["nvidia", "nvda"],
    "GOOGL": ["alphabet", "google", "googl"],
    "AMZN": ["amazon", "amzn"],
    "TSLA": ["tesla", "tsla"],
    "META": ["meta platforms", "facebook", "meta"],
    "JPM": ["jpmorgan", "jp morgan", "jpm"],
    "RELIANCE": ["reliance industries", "reliance"],
    "TCS": ["tata consultancy", "tcs"],
    "HDFCBANK": ["hdfc bank"],
    "INFY": ["infosys"],
    "ICICIBANK": ["icici bank"],
    "SBIN": ["state bank of india", "sbin"],
    "BHARTIARTL": ["bharti airtel", "airtel"],
    "ITC": ["itc ltd", "itc limited"],
}

assert set(ENTITY_KEYWORDS) <= set(SUPPORTED_ASSETS), "ENTITY_KEYWORDS references an unknown symbol"


def _compile_keyword_patterns() -> dict[str, list[re.Pattern]]:
    patterns: dict[str, list[re.Pattern]] = {}
    for symbol, keywords in ENTITY_KEYWORDS.items():
        patterns[symbol] = [re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in keywords]
    return patterns


_KEYWORD_PATTERNS = _compile_keyword_patterns()


def extract_entities(text: str) -> list[str]:
    """
    Match known instrument symbols in free text via deterministic
    whole-word/phrase keyword matching (see ENTITY_KEYWORDS).

    Args:
        text: Headline and/or summary text.

    Returns:
        Sorted list of matched SUPPORTED_ASSETS symbols (empty if none).
    """
    if not text:
        return []
    matched = {symbol for symbol, patterns in _KEYWORD_PATTERNS.items() if any(p.search(text) for p in patterns)}
    return sorted(matched)


# Event-type keyword table, checked in this fixed priority order (a
# headline can contain keywords for more than one category -- e.g. "Fed
# raises rates ahead of Apple earnings" -- so order encodes which read
# takes priority; monetary policy/macro data are checked first since they
# are typically THE market-moving element of a headline that also
# mentions a specific company in passing).
EVENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("monetary_policy", [
        "federal reserve", "fed rate", "fed chair", "interest rate", "rate hike", "rate cut",
        "fomc", "central bank", "rbi", "reserve bank of india", "ecb", "european central bank",
        "bank of england", "monetary policy",
    ]),
    ("macro_data", [
        "gdp", "inflation", "cpi", "consumer price index", "jobs report", "unemployment",
        "nonfarm payrolls", "payrolls", "pmi", "retail sales", "trade deficit",
    ]),
    ("geopolitical", [
        "war", "sanctions", "military conflict", "tariff", "trade war", "election",
        "geopolitical", "invasion", "ceasefire",
    ]),
    ("regulatory", [
        "sec ", "lawsuit", "regulator", "antitrust", "fined", "fine of", "investigation",
        "compliance", "ftc ", "doj ",
    ]),
    ("corporate_action", [
        "merger", "acquisition", "acquires", "buyback", "stock split", "ipo", "dividend",
        "spinoff", "spin-off", "bankruptcy",
    ]),
    ("earnings", [
        "earnings", "quarterly results", "q1 results", "q2 results", "q3 results", "q4 results",
        "eps", "profit rose", "profit fell", "revenue", "guidance", "beat estimates", "miss estimates",
    ]),
]

EVENT_TYPES: tuple[str, ...] = tuple(name for name, _ in EVENT_KEYWORDS) + ("other",)

# Static severity prior per event type -- a documented, deterministic
# weighting reflecting typical market-wide impact breadth (monetary
# policy/macro data move whole asset classes; a single company's earnings
# or a corporate action is comparatively contained). NOT a fitted/trained
# weighting -- there is no labeled "actual market impact" dataset here to
# fit one against (Rule 4: don't fabricate what isn't measurable with
# what's actually available).
EVENT_TYPE_WEIGHTS: dict[str, float] = {
    "monetary_policy": 1.5,
    "macro_data": 1.4,
    "geopolitical": 1.3,
    "earnings": 1.2,
    "regulatory": 1.1,
    "corporate_action": 1.1,
    "other": 1.0,
}


def classify_event_type(text: str) -> str:
    """
    Classify a headline/summary into one of EVENT_TYPES via deterministic
    keyword matching, checked in EVENT_KEYWORDS' fixed priority order.

    Args:
        text: Headline and/or summary text.

    Returns:
        One of EVENT_TYPES; "other" if nothing matched.
    """
    if not text:
        return "other"
    lowered = text.lower()
    for event_type, keywords in EVENT_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return event_type
    return "other"


def market_impact_score(sentiment_score: Optional[float], event_type: str) -> Optional[float]:
    """
    market_impact_score = abs(sentiment_score) * EVENT_TYPE_WEIGHTS[event_type].

    A deliberately simple, fully-explainable combination of "how strongly
    directional was the sentiment read" and "how broad does this class of
    event typically matter" -- not a fabricated composite ML score for
    something never trained on real market-reaction data.

    Returns None if sentiment_score is None (honest gap, never defaulted
    to 0.0 which would misleadingly imply "confirmed no impact").
    """
    if sentiment_score is None:
        return None
    weight = EVENT_TYPE_WEIGHTS.get(event_type, 1.0)
    return round(abs(sentiment_score) * weight, 4)


_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\s]")


def normalized_content_hash(title: str) -> str:
    """
    sha256 of a normalized (lowercased, punctuation-stripped, whitespace-
    collapsed) title -- the dedup key used for NewsEvent.content_hash.
    Catches both re-fetching the same feed entry and the same wire
    headline text appearing across two different feeds.
    """
    normalized = _PUNCTUATION_RE.sub("", title.lower())
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
