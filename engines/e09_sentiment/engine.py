"""
Module: engine.py
Description: Engine 09 — Sentiment Intelligence (financial text sentiment
             scoring).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-14
"""

import importlib.util
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e09_sentiment.trading_lexicon import score_trading_lexicon

logger = logging.getLogger(__name__)

# find_spec checks whether the PACKAGE is installed without importing it
# (or its heavy torch dependency) -- the actual `from transformers import
# pipeline` is deferred to _get_finbert_pipeline(), its first real use.
# Importing transformers eagerly here measured ~18-23s of a ~30s server
# cold start (paid on every launch whether or not FinBERT was ever
# actually used that session) despite initialize()'s own docstring
# already promising "FinBERT loads lazily... to keep startup fast" --
# the pipeline OBJECT was lazy, but the library import wasn't.
TRANSFORMERS_AVAILABLE = importlib.util.find_spec("transformers") is not None
if not TRANSFORMERS_AVAILABLE:
    logger.warning("transformers not installed; FinBERT sentiment disabled, using VADER/TextBlob only")

FINBERT_MODEL = "ProsusAI/finbert"


@lru_cache
def _get_finbert_pipeline():
    """Process-wide cached FinBERT pipeline. Loading it is a one-time cost
    (first run also downloads ~440MB from the HuggingFace Hub) -- must not
    be paid per analyze_text() call."""
    from transformers import pipeline

    return pipeline("text-classification", model=FINBERT_MODEL)


@dataclass
class SentimentResult:
    """Composite sentiment read for a piece of text."""

    text: str
    compound_score: float  # -1 (very negative) to +1 (very positive)
    label: str  # "positive" | "negative" | "neutral"
    method: str  # "finbert" | "finbert_lexicon_override" | "vader_textblob_lexicon_ensemble"
    finbert_label: Optional[str] = None
    finbert_confidence: Optional[float] = None
    vader_compound: float = 0.0
    textblob_polarity: float = 0.0
    lexicon_score: float = 0.0  # trading_lexicon.py's directional read; 0.0 = no lexicon terms matched
    knowledge_context: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "compound_score": self.compound_score,
            "label": self.label,
            "method": self.method,
            "finbert_label": self.finbert_label,
            "finbert_confidence": self.finbert_confidence,
            "vader_compound": self.vader_compound,
            "textblob_polarity": self.textblob_polarity,
            "lexicon_score": self.lexicon_score,
            "knowledge_context": self.knowledge_context,
        }


class SentimentIntelligenceEngine(BaseEngine):
    """
    Sentiment Intelligence Engine — scores financial text sentiment.

    Uses FinBERT (a model fine-tuned on financial text) when transformers
    is installed and the model loads successfully: general-purpose lexicon
    analyzers (VADER, TextBlob) systematically underrate financial
    vocabulary ("shares tumbled", "beat estimates") since those phrases
    aren't in their general-English sentiment lexicons. Falls back to an
    averaged VADER+TextBlob ensemble when FinBERT isn't available, which
    still works with zero heavy ML dependencies installed.
    """

    engine_id = "e09_sentiment"
    engine_name = "Sentiment Intelligence Engine"
    version = "1.0.0"

    POSITIVE_THRESHOLD = 0.15
    NEGATIVE_THRESHOLD = -0.15
    FINBERT_MAX_CHARS = 512  # FinBERT's underlying model has a 512-token context

    def __init__(self, knowledge_engine: Optional[KnowledgeEngine] = None) -> None:
        super().__init__()
        self._vader = SentimentIntensityAnalyzer()
        # Optional and None by default: without it, analyze_text()/
        # analyze_batch() behave exactly as before (no knowledge_context).
        # Pass a real instance (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        """Initialize the sentiment engine (VADER/TextBlob need no warm-up;
        FinBERT loads lazily on first use, not here, to keep startup fast)."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(
            success=True,
            message="Sentiment Intelligence Engine initialized",
            metadata={"finbert_available": TRANSFORMERS_AVAILABLE},
        )

    def health_check(self) -> EngineResult:
        """Always healthy -- VADER/TextBlob are local, no external dependency."""
        return EngineResult(success=True, message="Healthy")

    def analyze_text(self, text: str) -> EngineResult:
        """
        Score sentiment for a single piece of text (headline, article body).

        Args:
            text: Text to analyze.

        Returns:
            EngineResult with a SentimentResult in data.
        """
        try:
            result = self._score_text(text)
        except Exception as e:
            logger.error("Sentiment analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])
        if result is None:
            return EngineResult(success=False, message="Empty text")
        result.knowledge_context = self._build_knowledge_context(result.label)
        return EngineResult(success=True, data=result, message=f"Sentiment: {result.label} ({result.compound_score:.2f})")

    def _score_text(self, text: str) -> Optional[SentimentResult]:
        """Core scoring logic, without a knowledge_context lookup -- used
        directly by analyze_batch() so scoring N texts doesn't trigger N
        separate knowledge-base queries (one aggregate-level lookup is
        attached in analyze_batch() instead)."""
        if not text or not text.strip():
            return None

        vader_compound = float(self._vader.polarity_scores(text)["compound"])
        textblob_polarity = float(TextBlob(text).sentiment.polarity)
        ensemble = (vader_compound + textblob_polarity) / 2

        finbert_label, finbert_confidence = self._score_with_finbert(text)

        # Added 2026-08-01: a trading/retail-chatter directional lexicon
        # (trading_lexicon.py) -- covers a real, confirmed domain gap.
        # Tested directly against real FinBERT output: "to the moon! this
        # stock is going to explode" scores 87% NEUTRAL confidence from
        # FinBERT, "buy the dip everyone, easy money" scores 91% neutral
        # -- not close calls. FinBERT is trained on formal financial news
        # and has essentially no exposure to informal trading-chatter/
        # crowd-psychology language, so it defaults to neutral on
        # register it doesn't recognize rather than reading the real
        # directional signal a human trader would see immediately.
        lexicon_score = score_trading_lexicon(text)

        if finbert_label is not None:
            signed = {"positive": 1, "negative": -1, "neutral": 0}.get(finbert_label, 0)
            finbert_compound = signed * finbert_confidence
            if finbert_label == "neutral" and lexicon_score != 0.0:
                # FinBERT found nothing directional; the lexicon did --
                # trust the lexicon's read rather than silently keeping a
                # neutral verdict, since this exact combination (FinBERT
                # confidently neutral + genuine trading-chatter directional
                # language present) is the confirmed gap this lexicon
                # exists to cover, not a guess.
                compound = lexicon_score
                method = "finbert_lexicon_override"
            else:
                # FinBERT committed to a direction (or both FinBERT and
                # the lexicon found nothing) -- blend the lexicon in as a
                # minority vote rather than letting it override a
                # confident FinBERT directional read.
                compound = 0.8 * finbert_compound + 0.2 * lexicon_score
                method = "finbert"
            label = self._label_from_score(compound)
        else:
            compound = 0.7 * ensemble + 0.3 * lexicon_score
            label = self._label_from_score(compound)
            method = "vader_textblob_lexicon_ensemble"

        return SentimentResult(
            text=text,
            compound_score=round(compound, 4),
            label=label,
            method=method,
            finbert_label=finbert_label,
            finbert_confidence=round(finbert_confidence, 4) if finbert_confidence is not None else None,
            vader_compound=round(vader_compound, 4),
            textblob_polarity=round(textblob_polarity, 4),
            lexicon_score=round(lexicon_score, 4),
        )

    def analyze_batch(self, texts: list[str]) -> EngineResult:
        """
        Score sentiment for multiple texts and return an aggregate read.

        Args:
            texts: List of texts (e.g. headlines) to analyze.

        Returns:
            EngineResult with {"results": [SentimentResult, ...],
            "aggregate_score": float, "aggregate_label": str, "n": int,
            "knowledge_context": ...}.
        """
        try:
            if not texts:
                return EngineResult(success=False, message="No texts provided")

            results = [r for r in (self._score_text(t) for t in texts) if r is not None]
            if not results:
                return EngineResult(success=False, message="No text could be scored")

            aggregate_score = sum(r.compound_score for r in results) / len(results)
            aggregate_label = self._label_from_score(aggregate_score)

            return EngineResult(
                success=True,
                data={
                    "results": results,
                    "aggregate_score": round(aggregate_score, 4),
                    "aggregate_label": aggregate_label,
                    "n": len(results),
                    "knowledge_context": self._build_knowledge_context(aggregate_label),
                },
                message=(
                    f"Aggregate sentiment: {aggregate_label} ({aggregate_score:.2f}) "
                    f"over {len(results)} item(s)"
                ),
            )
        except Exception as e:
            logger.error("Batch sentiment analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _score_with_finbert(self, text: str) -> tuple[Optional[str], Optional[float]]:
        """Best-effort FinBERT scoring -- returns (None, None) if
        transformers isn't installed or the model fails to load/score,
        so callers fall back to the VADER/TextBlob ensemble."""
        if not TRANSFORMERS_AVAILABLE:
            return None, None
        try:
            output = _get_finbert_pipeline()(text[: self.FINBERT_MAX_CHARS])[0]
            return output["label"], float(output["score"])
        except Exception as e:
            logger.warning("FinBERT scoring failed (%s) -- using VADER/TextBlob ensemble", e)
            return None, None

    def _label_from_score(self, score: float) -> str:
        if score >= self.POSITIVE_THRESHOLD:
            return "positive"
        if score <= self.NEGATIVE_THRESHOLD:
            return "negative"
        return "neutral"

    def _build_knowledge_context(self, label: str) -> Optional[dict]:
        """Relevant behavioral-finance book content for the sentiment
        label, attached for transparency -- informational only, never
        changes compound_score/label. Best-effort: only runs if a real
        KnowledgeEngine instance was injected (see __init__ / registry.py)."""
        if self._knowledge_engine is None:
            return None
        try:
            query = f"{label} market sentiment behavioral finance psychology"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
