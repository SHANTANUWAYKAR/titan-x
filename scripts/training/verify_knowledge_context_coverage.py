"""
Module: verify_knowledge_context_coverage.py
Description: Rule 3.2's "book knowledge" verification, run across every
    knowledge_context-wired engine at once, against the COMBINED corpus
    (book chunks + YouTube-extracted knowledge, once both live in the
    same data/knowledge/chroma_db store -- see
    youtube_pipeline/scripts/titanx_integrator.py for how the YouTube
    side gets merged in). One real, domain-specific query per engine,
    picked to plausibly surface either source (e.g. E07's "RSI
    divergence" query is deliberately the exact concept the YouTube
    pipeline found was the single most emphasized, previously-
    uncovered idea in the Mind Math Money corpus -- a genuine test of
    whether the merge actually worked, not just a generic sanity check).

    Not a threshold-fitting calibration (same distinction
    validate_e20_factor_research.py draws) -- this only confirms real,
    relevant results come back, per Rule 3's own wording. A query
    returning zero results, or results whose score sits at/near zero,
    is flagged for manual review rather than silently passed.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "knowledge_context_coverage_report.json"

# One domain-representative query per knowledge_context-wired engine (see
# CLAUDE.md's engine roster table). MIN_RELEVANT_SCORE is a low floor, not
# a strict bar -- hybrid_search already ranks by relevance, so a real top
# result on a real corpus should clear this comfortably; anything below it
# signals "nothing relevant was actually found," worth a human look.
ENGINE_QUERIES: dict[str, str] = {
    "e04_macro": "inflation and interest rate policy",
    "e05_economic_calendar": "non-farm payrolls economic release",
    "e06_fundamental": "price to earnings ratio valuation",
    "e07_technical": "RSI divergence",
    "e08_regime": "market regime trending versus ranging",
    "e09_sentiment": "market sentiment fear and greed",
    "e10_cross_asset": "correlation between asset classes",
    "e11_microstructure": "bid ask spread liquidity",
    "e12_quant_research": "kelly criterion position sizing",
    "e13_derivatives": "options skew implied volatility",
    "e14_fixed_income": "yield curve inversion",
    "e15_credit": "credit spread sovereign risk",
    "e16_commodity": "commodity seasonality",
    "e17_crypto": "funding rate perpetual futures",
    "e19_global_liquidity": "central bank balance sheet expansion",
    "e20_factor_research": "Fama French value growth factors",
    "e27_walk_forward": "walk forward validation overfitting",
    "e28_stress_testing": "2008 financial crisis drawdown",
    "e43_committee": "trading plan discipline psychology",
    "e45_risk": "stop loss position sizing",
    "e51_signals": "breakout volume confirmation",
}
MIN_RELEVANT_SCORE = 0.05


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    store = KnowledgeEngine().document_store

    results: dict = {}
    flagged: list[str] = []
    for engine_id, query in ENGINE_QUERIES.items():
        hits = store.hybrid_search(query, limit=3)
        top = hits[0] if hits else None
        top_is_youtube = bool(top and top.chunk.chunk_id.startswith("yt_"))
        entry = {
            "query": query,
            "n_results": len(hits),
            "top_score": round(top.score, 4) if top else 0.0,
            "top_is_youtube": top_is_youtube,
            "top_source": top.chunk.source if top else None,
            "top_title": top.chunk.title if top else None,
            "top_snippet": (top.chunk.text[:200] + "...") if top else None,
        }
        results[engine_id] = entry
        ok = bool(hits) and entry["top_score"] >= MIN_RELEVANT_SCORE
        if not ok:
            flagged.append(engine_id)
        logger.info(
            "%-22s %-45s n=%d top_score=%.3f %-8s%s",
            engine_id, query, entry["n_results"], entry["top_score"],
            "[YT]" if top_is_youtube else "[book]",
            "  <-- FLAGGED (no relevant result)" if not ok else "",
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_relevant_score": MIN_RELEVANT_SCORE,
        "results": results,
        "flagged_engines": flagged,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("")
    logger.info("Report written to %s", OUTPUT_PATH)
    if flagged:
        logger.warning("Flagged (no relevant result found): %s", flagged)
    else:
        logger.info("All %d engines returned a relevant result.", len(ENGINE_QUERIES))


if __name__ == "__main__":
    main()
