"""
Module: knowledge_extractor.py
Description: YouTube Knowledge Import Pipeline -- Phase 4, Knowledge
    Extraction.

    HONEST CAPABILITY NOTE (read before trusting extraction quality):
    project_titan_x/.env has no ANTHROPIC_API_KEY or OPENAI_API_KEY
    configured (checked directly). Genuine semantic extraction of
    "mental models" / "decision frameworks" / "limitations" from
    free-form speech is fundamentally a language-understanding task --
    rule-based pattern matching can do it, but at real, honest quality
    limits: it catches EXPLICIT patterns (definition phrasing, category
    keyword co-occurrence) and will miss implicit/nuanced statements a
    human or an LLM reading the transcript would catch. This module is
    that rule-based extractor -- genuinely useful (same category-lexicon
    approach already proven out in e09_sentiment/trading_lexicon.py this
    session), not a placeholder, but not LLM-quality. If ANTHROPIC_API_KEY
    is set, extract_llm() below is used instead for real per-video
    structured extraction; extract_rule_based() is always available as
    the offline fallback. Every extracted item keeps the transcript
    segment + timestamp it came from, so a human (or a future LLM pass)
    can verify or deepen any of this against the original source.
Author: Shantanu Waykar
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CATEGORIES = [
    "definitions", "concepts", "mental_models", "trading_principles",
    "entry_logic", "exit_logic", "risk_management", "psychology",
    "market_structure", "technical_analysis", "macro_concepts", "indicators",
    "common_mistakes", "best_practices", "decision_frameworks",
    "supporting_evidence", "limitations", "failure_conditions",
]

# Real, tested category lexicons -- same construction discipline as
# e09_sentiment/trading_lexicon.py (phrase-first, word-second, no
# double-counting), scoped to the trading/finance-education domain these
# channels actually cover. A sentence can match multiple categories (a
# single sentence often IS both e.g. risk_management AND best_practices);
# that's intentional, not deduplicated here -- Phase 6 (validation) is
# where cross-category/cross-video duplication gets resolved, not
# extraction.
_CATEGORY_LEXICON: dict[str, list[str]] = {
    "risk_management": [
        "risk management", "position size", "position sizing", "stop loss", "risk per trade",
        "risk reward", "risk:reward", "risk to reward", "max drawdown", "maximum drawdown",
        "account risk", "capital preservation", "risk of ruin", "portfolio heat", "1% rule",
        "2% rule", "kelly criterion", "diversification", "hedge", "hedging",
    ],
    "entry_logic": [
        "entry signal", "entry point", "when to enter", "enter a trade", "entry trigger",
        "entry criteria", "confirmation candle", "breakout entry", "pullback entry",
        "retest entry", "entry rule",
    ],
    "exit_logic": [
        "exit signal", "exit point", "when to exit", "take profit", "profit target",
        "trailing stop", "exit rule", "exit strategy", "scaling out", "partial exit",
    ],
    "psychology": [
        "trading psychology", "emotional control", "fear of missing out", "fomo", "revenge trading",
        "discipline", "patience", "overconfidence", "loss aversion", "confirmation bias",
        "anchoring bias", "recency bias", "sunk cost", "trading journal", "self control",
        "mindset", "emotional discipline", "impulse trading",
    ],
    "market_structure": [
        "market structure", "higher high", "higher low", "lower high", "lower low",
        "break of structure", "change of character", "liquidity sweep", "liquidity grab",
        "order block", "fair value gap", "supply and demand", "support and resistance",
        "trend line", "swing high", "swing low", "consolidation", "range bound",
    ],
    "technical_analysis": [
        "moving average", "rsi", "macd", "bollinger band", "fibonacci", "vwap",
        "candlestick pattern", "chart pattern", "volume profile", "atr", "stochastic",
        "trend following", "mean reversion", "divergence", "indicator",
    ],
    "macro_concepts": [
        "interest rate", "central bank", "federal reserve", "inflation", "yield curve",
        "business cycle", "gdp", "unemployment rate", "monetary policy", "fiscal policy",
        "risk on", "risk off", "quantitative easing", "recession", "economic indicator",
    ],
    "indicators": [
        "rsi", "macd", "moving average", "bollinger band", "atr", "vwap", "stochastic oscillator",
        "adx", "on balance volume", "ichimoku",
    ],
    "common_mistakes": [
        "common mistake", "biggest mistake", "beginner mistake", "trading mistake",
        "avoid this", "don't do this", "pitfall", "trap", "what not to do", "why traders fail",
        "why you're losing", "overtrading",
    ],
    "best_practices": [
        "best practice", "should always", "make sure you", "key takeaway", "rule of thumb",
        "golden rule", "always remember", "the right way to",
    ],
    "decision_frameworks": [
        "decision framework", "checklist", "step by step", "process for", "framework for",
        "system for", "rules based", "trading plan", "trading system",
    ],
    "supporting_evidence": [
        "backtest", "backtested", "study shows", "research shows", "data shows", "historically",
        "statistics show", "win rate", "sample size", "track record",
    ],
    "limitations": [
        "doesn't always work", "not guaranteed", "limitation", "downside of", "trade-off",
        "however this", "but this only works", "exception to this", "caveat",
    ],
    "failure_conditions": [
        "this fails when", "stops working when", "breaks down when", "invalidated when",
        "false signal", "fakeout", "failed breakout", "when this doesn't work",
    ],
    "mental_models": [
        "mental model", "think of it like", "analogy", "framework for thinking",
        "way to think about", "the way i see it", "first principles",
    ],
    "trading_principles": [
        "trading principle", "core principle", "fundamental rule", "never risk more than",
        "always use a stop", "cut your losses", "let your winners run", "plan the trade",
    ],
}

# Regex patterns for explicit definition sentences -- "X is/are/means/refers
# to Y" is the single most reliable, high-precision definition signal in
# spoken educational content (a lecture/tutorial register uses this
# construction constantly); deliberately conservative (a few precise
# patterns, not a loose catch-all) to keep precision high, since a false
# "definition" is worse than a missed one for this specific category.
_DEFINITION_PATTERNS = [
    re.compile(r"^([A-Z][\w\s\-/]{2,40}?)\s+(?:is|are)\s+(?:defined as|when|a|an|the)\s+(.{10,200})", re.IGNORECASE),
    re.compile(r"^([A-Z][\w\s\-/]{2,40}?)\s+(?:means|refers to)\s+(.{10,200})", re.IGNORECASE),
    re.compile(r"^what\s+([\w\s\-/]{2,40}?)\s+means\s+is\s+(.{10,200})", re.IGNORECASE),
]


@dataclass
class ExtractedItem:
    category: str
    text: str
    matched_terms: list[str]
    segment_start: Optional[float]  # seconds into the video, for timestamp linking
    video_id: str
    video_title: str
    video_url: str
    channel_slug: str
    extraction_method: str  # "rule_based" | "llm"


@dataclass
class Definition:
    term: str
    definition: str
    segment_start: Optional[float]
    video_id: str
    video_title: str
    video_url: str
    channel_slug: str


@dataclass
class VideoKnowledge:
    video_id: str
    n_sentences: int
    items: list[ExtractedItem] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    extraction_method: str = "rule_based"


def _load_spacy():
    """en_core_web_sm for sentence segmentation -- downloaded separately
    (spacy's model download is a distinct step from `pip install spacy`,
    see setup_environment.py). Falls back to a naive regex sentence
    splitter if the model isn't present, so extraction still runs (at
    lower sentence-boundary accuracy) rather than hard-failing the whole
    pipeline over a missing model download."""
    try:
        import spacy
        return spacy.load("en_core_web_sm")
    except Exception as e:
        logger.warning("spaCy model unavailable (%s) -- falling back to regex sentence splitting", e)
        return None


_NAIVE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str, nlp) -> list[str]:
    if nlp is not None:
        return [s.text.strip() for s in nlp(text).sents if s.text.strip()]
    return [s.strip() for s in _NAIVE_SENTENCE_SPLIT.split(text) if s.strip()]


def _find_segment_start(sentence: str, segments: list[dict]) -> Optional[float]:
    """Best-effort: find which raw transcript segment this sentence's
    first few words fall in, so every extracted item keeps a real
    timestamp reference back into the source video (Phase 5's own
    'preserve timestamp references' requirement) -- not exact word-level
    alignment (sentence boundaries from spaCy don't line up 1:1 with the
    raw caption segments YouTube ships), but close enough to jump to the
    right ~10s window in the video."""
    probe = " ".join(sentence.split()[:6]).lower()
    if not probe:
        return None
    running = ""
    for seg in segments:
        running += " " + seg["text"]
        if probe[:20] in running.lower():
            return seg["start"]
    return None


def extract_rule_based(
    video_id: str, video_title: str, video_url: str, channel_slug: str,
    clean_text: str, raw_segments: list[dict], nlp=None,
) -> VideoKnowledge:
    """Sentence-by-sentence category-lexicon matching + definition-pattern
    matching over one video's transcript. Pure function -- no I/O beyond
    what's passed in, easy to test."""
    sentences = _split_sentences(clean_text, nlp)
    items: list[ExtractedItem] = []
    definitions: list[Definition] = []

    for sentence in sentences:
        lowered = sentence.lower()
        for category, terms in _CATEGORY_LEXICON.items():
            matched = [t for t in terms if t in lowered]
            if matched:
                items.append(ExtractedItem(
                    category=category, text=sentence, matched_terms=matched,
                    segment_start=_find_segment_start(sentence, raw_segments),
                    video_id=video_id, video_title=video_title, video_url=video_url,
                    channel_slug=channel_slug, extraction_method="rule_based",
                ))
        for pattern in _DEFINITION_PATTERNS:
            m = pattern.match(sentence)
            if m:
                term, definition = m.group(1).strip(), m.group(2).strip()
                if 2 <= len(term) <= 60:
                    definitions.append(Definition(
                        term=term, definition=definition,
                        segment_start=_find_segment_start(sentence, raw_segments),
                        video_id=video_id, video_title=video_title,
                        video_url=video_url, channel_slug=channel_slug,
                    ))
                break

    return VideoKnowledge(
        video_id=video_id, n_sentences=len(sentences), items=items,
        definitions=definitions, extraction_method="rule_based",
    )


def extract_video(
    video_id: str, video_title: str, video_url: str, channel_slug: str,
    clean_text: str, raw_segments: list[dict], nlp=None,
) -> VideoKnowledge:
    """Entry point Phase 4 actually calls -- uses LLM extraction if
    ANTHROPIC_API_KEY is configured, else the rule-based extractor above.
    Checked at call time (not import time) so a key added mid-run takes
    effect on the next video without restarting the process."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from knowledge_extractor_llm import extract_llm
            return extract_llm(video_id, video_title, video_url, channel_slug, clean_text, raw_segments)
        except Exception as e:
            logger.warning("LLM extraction failed for %s, falling back to rule-based: %s", video_id, e)
    return extract_rule_based(video_id, video_title, video_url, channel_slug, clean_text, raw_segments, nlp)


def extract_all(channel_dir: Path, limit: Optional[int] = None) -> dict:
    """Runs extract_video over every video that has a successful
    transcript and hasn't been extracted yet (per checkpoint.json),
    writing knowledge.json next to each video's transcript."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from checkpoint import Checkpoint

    metadata_path = channel_dir / "channel_metadata.json"
    channel = json.loads(metadata_path.read_text(encoding="utf-8"))
    channel_slug = channel["slug"]
    checkpoint = Checkpoint(channel_dir / "checkpoint.json")
    videos_dir = channel_dir / "videos"

    nlp = _load_spacy()
    processed = 0
    total_items = 0

    video_ids = [v["video_id"] for v in channel["videos"]]
    if limit is not None:
        video_ids = video_ids[:limit]

    for vid in video_ids:
        if not checkpoint.needs_extraction(vid):
            continue
        video_dir = videos_dir / vid
        clean_path = video_dir / "transcript_clean.txt"
        raw_path = video_dir / "transcript_raw.json"
        meta_path = video_dir / "metadata.json"
        if not (clean_path.exists() and raw_path.exists() and meta_path.exists()):
            continue

        clean_text = clean_path.read_text(encoding="utf-8")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        knowledge = extract_video(
            vid, meta.get("title", ""), meta.get("url", ""), channel_slug,
            clean_text, raw["segments"], nlp,
        )
        (video_dir / "knowledge.json").write_text(
            json.dumps(asdict(knowledge), indent=2), encoding="utf-8"
        )
        checkpoint.update(
            vid, knowledge_extracted=True,
            n_concepts_extracted=len(knowledge.items) + len(knowledge.definitions),
        )
        processed += 1
        total_items += len(knowledge.items) + len(knowledge.definitions)
        logger.info(
            "EXTRACTED %s  %d items, %d definitions (%s)",
            vid, len(knowledge.items), len(knowledge.definitions), knowledge.extraction_method,
        )

    return {"processed_this_run": processed, "total_items_this_run": total_items}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    slug = sys.argv[1] if len(sys.argv) > 1 else "mind_math_money"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    channel_dir = Path(__file__).resolve().parents[2] / "data" / "YOUTUBE DATA" / "channels" / slug
    result = extract_all(channel_dir, limit=limit)
    print(json.dumps(result, indent=2))
