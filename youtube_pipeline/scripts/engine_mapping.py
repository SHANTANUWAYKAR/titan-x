"""
Module: engine_mapping.py
Description: Maps extracted-knowledge categories (see knowledge_extractor.py's
    CATEGORIES) onto (a) e01_knowledge's existing fixed KnowledgeCategory
    taxonomy, for chunks that go into the shared document store, and (b)
    the specific project_titan_x ENGINE each category is most relevant
    to, for Phase 7's Engine Distribution Report and for deciding which
    engines' own upgrade work this knowledge should actually inform.

    HONEST LIMITATION: neither mapping is a clean 1:1 -- e01's taxonomy
    was built for book content (Technical Analysis, Wyckoff, ICT, ...),
    not for categories like "common_mistakes" or "decision_frameworks",
    and project_titan_x has no dedicated "trader psychology coaching"
    engine (e09_sentiment analyzes MARKET/crowd sentiment, not an
    individual trader's own discipline -- a real, different thing this
    platform doesn't currently have an engine for). Where no honest fit
    exists, the mapping says so explicitly rather than forcing one.
Author: Shantanu Waykar
"""

from __future__ import annotations

from typing import Optional

# category -> list of e01_knowledge.models.KnowledgeCategory VALUES
# (kept as strings here to avoid a hard import dependency until actually
# needed -- converted to the real enum in titanx_integrator.py). Multiple
# tags per category are fine (Chunk.topics is a list); an empty list
# means "no honest fit in the existing fixed taxonomy."
CATEGORY_TO_KNOWLEDGE_TAXONOMY: dict[str, list[str]] = {
    "definitions": [],
    "concepts": [],
    "mental_models": ["Investing Psychology"],
    "trading_principles": ["Risk Management"],
    "entry_logic": ["Technical Analysis"],
    "exit_logic": ["Technical Analysis"],
    "risk_management": ["Risk Management"],
    "psychology": ["Investing Psychology"],
    "market_structure": ["Smart Money Concepts"],
    "technical_analysis": ["Technical Analysis"],
    "macro_concepts": ["Macroeconomics"],
    "indicators": ["Technical Analysis"],
    "common_mistakes": ["Investing Psychology"],
    "best_practices": [],
    "decision_frameworks": ["Portfolio Management"],
    "supporting_evidence": ["Quantitative Finance"],
    "limitations": [],
    "failure_conditions": ["Risk Management"],
}

# category -> (engine_id, confidence_note). engine_id is None where this
# platform genuinely has no matching engine -- e.g. personal trading
# psychology/discipline coaching is a real, distinct thing from
# e09_sentiment (which reads MARKET/crowd sentiment from news/social
# text, not an individual trader's own behavior). Reported honestly in
# Phase 7 as a suggested gap, not silently mapped to the nearest
# unrelated engine.
CATEGORY_TO_ENGINE: dict[str, tuple[Optional[str], str]] = {
    "definitions": (None, "general reference -- belongs in the knowledge base itself, not a specific engine"),
    "concepts": (None, "general reference -- belongs in the knowledge base itself, not a specific engine"),
    "mental_models": (None, "no dedicated trader-psychology engine exists on this platform (e09_sentiment reads MARKET sentiment, not individual trader behavior) -- candidate for a new engine, not a forced fit"),
    "trading_principles": ("e51_signals", "direction/confidence rule design"),
    "entry_logic": ("e51_signals", "direction/confidence rule design"),
    "exit_logic": ("e51_signals", "stop-loss/take-profit level logic"),
    "risk_management": ("e45_risk", "position sizing, veto rules, drawdown limits"),
    "psychology": (None, "no dedicated trader-psychology engine exists on this platform -- same gap as mental_models"),
    "market_structure": ("e07_technical", "SMC/ICT/Wyckoff structural detection"),
    "technical_analysis": ("e07_technical", "indicator/pattern detection"),
    "macro_concepts": ("e04_macro", "macro regime/risk-on-off scoring"),
    "indicators": ("e07_technical", "indicator computation/thresholds"),
    "common_mistakes": ("e41_explainable_ai", "caveats/failure-mode disclosure in signal explanations"),
    "best_practices": ("e43_committee", "agent voting heuristics"),
    "decision_frameworks": ("e43_committee", "multi-agent decision structure"),
    "supporting_evidence": ("e26_backtesting", "validation methodology"),
    "limitations": ("e38_alpha_decay_monitor", "known conditions where an edge degrades"),
    "failure_conditions": ("e28_stress_testing", "scenario/regime conditions where a strategy breaks"),
}


def engine_distribution(category_counts: dict[str, int]) -> dict[str, int]:
    """Aggregates per-category item counts into per-ENGINE counts (for
    Phase 7's Engine Distribution Report). Items whose category has no
    engine mapping accumulate under the literal key 'unmapped' rather
    than being silently dropped from the total."""
    dist: dict[str, int] = {}
    for category, count in category_counts.items():
        engine_id, _ = CATEGORY_TO_ENGINE.get(category, (None, "unknown category"))
        key = engine_id or "unmapped"
        dist[key] = dist.get(key, 0) + count
    return dist
