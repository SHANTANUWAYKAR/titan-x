"""
Module: classification.py
Description: Automatic topic classification for Engine 01's ingested
    chunks, into the fixed 23-category taxonomy (models.KnowledgeCategory).

    Method: embedding-similarity against a short anchor description per
    category, using the SAME sentence-transformer the document store
    already embeds chunks with (no separate model, no labeled training
    set required). This is honestly a zero-shot heuristic, not a trained
    classifier -- confidence is the cosine similarity to the closest
    anchor, not a calibrated probability. Good enough to route/tag
    content; not a claim of ground-truth accuracy.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from project_titan_x.engines.e01_knowledge.models import KnowledgeCategory

EmbedFn = Callable[[str], list[float]]

CATEGORY_ANCHORS: dict[KnowledgeCategory, str] = {
    KnowledgeCategory.TECHNICAL_ANALYSIS: "chart patterns, trend lines, moving averages, RSI, MACD, support and resistance, price action technical indicators",
    KnowledgeCategory.SMART_MONEY_CONCEPTS: "order blocks, liquidity zones, liquidity sweeps, fair value gaps, institutional order flow, smart money concepts",
    KnowledgeCategory.ICT: "inner circle trader ICT concepts, market structure shift, optimal trade entry, killzones, judas swing",
    KnowledgeCategory.WYCKOFF: "Wyckoff method, accumulation and distribution, composite man, spring, upthrust, Wyckoff phases",
    KnowledgeCategory.VOLUME_PROFILE: "volume profile, point of control, value area, high volume node, low volume node",
    KnowledgeCategory.MARKET_PROFILE: "market profile, time price opportunity TPO, initial balance, value area",
    KnowledgeCategory.ELLIOTT_WAVE: "Elliott wave theory, impulse waves, corrective waves, wave counting, Fibonacci wave relationships",
    KnowledgeCategory.HARMONICS: "harmonic chart patterns, Gartley, butterfly, bat, crab pattern, Fibonacci ratios in price",
    KnowledgeCategory.CANDLESTICK_PATTERNS: "candlestick patterns, doji, hammer, engulfing pattern, Japanese candlesticks",
    KnowledgeCategory.RISK_MANAGEMENT: "position sizing, stop loss placement, risk of ruin, drawdown control, risk per trade, Kelly criterion",
    KnowledgeCategory.PORTFOLIO_MANAGEMENT: "portfolio construction, asset allocation, diversification, rebalancing, portfolio management",
    KnowledgeCategory.QUANTITATIVE_FINANCE: "quantitative finance, factor models, backtesting, algorithmic trading, statistical arbitrage, alpha research",
    KnowledgeCategory.MACHINE_LEARNING: "machine learning, neural networks, feature engineering, supervised learning, model training and validation",
    KnowledgeCategory.STATISTICS: "probability theory, statistical significance, regression analysis, hypothesis testing, standard deviation",
    KnowledgeCategory.BEHAVIORAL_FINANCE: "trading psychology, cognitive biases, loss aversion, overconfidence, behavioral finance",
    KnowledgeCategory.MACROECONOMICS: "GDP growth, inflation, interest rates, central bank policy, monetary policy, macroeconomic cycles",
    KnowledgeCategory.FIXED_INCOME: "government and corporate bonds, yield curve, duration, credit spread, treasury notes",
    KnowledgeCategory.OPTIONS: "options trading, calls and puts, implied volatility, delta gamma theta vega, options greeks",
    KnowledgeCategory.FUTURES: "futures contracts, margin requirements, contango, backwardation, futures trading",
    KnowledgeCategory.FOREX: "currency pairs, forex trading, pips, carry trade, central bank currency interventions",
    KnowledgeCategory.CRYPTO: "bitcoin, cryptocurrency, blockchain, on-chain metrics, decentralized finance, crypto trading",
    KnowledgeCategory.COMMODITIES: "gold, oil, agricultural commodities, supply and demand fundamentals, commodity trading",
    KnowledgeCategory.INVESTING_PSYCHOLOGY: "investor psychology, trading discipline, emotional control, mindset, patience under uncertainty",
}


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


class TopicClassifier:
    """Classifies text into 1+ KnowledgeCategory values by embedding
    similarity against fixed anchor descriptions."""

    def __init__(self, embed_fn: EmbedFn, top_k: int = 3, threshold: float = 0.15) -> None:
        self._embed_fn = embed_fn
        self.top_k = top_k
        self.threshold = threshold
        self._anchor_vectors: dict[KnowledgeCategory, np.ndarray] = {}

    def _ensure_anchors(self) -> None:
        if self._anchor_vectors:
            return
        for category, description in CATEGORY_ANCHORS.items():
            self._anchor_vectors[category] = np.asarray(self._embed_fn(description))

    def classify(self, text: str) -> tuple[list[KnowledgeCategory], float]:
        """Returns (topics, confidence) where confidence is the cosine
        similarity of the single best-matching category. Always returns
        at least one topic (the best match), even if below threshold --
        an empty topic list would be less useful than a low-confidence guess."""
        self._ensure_anchors()
        return self.classify_vector(np.asarray(self._embed_fn(text)))

    def classify_vector(self, vector: np.ndarray) -> tuple[list[KnowledgeCategory], float]:
        """Same as classify(), but takes an already-computed embedding --
        for bulk ingestion, where the chunk's vector was already produced
        once for storage and re-embedding the same text here would be
        pure waste (confirmed ~5x slower than batching at ingestion scale)."""
        self._ensure_anchors()
        scored = [(category, _cosine(vector, anchor)) for category, anchor in self._anchor_vectors.items()]
        scored.sort(key=lambda pair: pair[1], reverse=True)

        top_topics = [category for category, score in scored[: self.top_k] if score >= self.threshold]
        if not top_topics:
            top_topics = [scored[0][0]]
        confidence = scored[0][1]
        return top_topics, confidence
