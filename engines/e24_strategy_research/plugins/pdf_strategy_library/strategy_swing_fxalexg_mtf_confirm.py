"""
Module: strategy_swing_fxalexg_mtf_confirm.py
Source document(s): SWING TRADING STRATEGY FXALEXG.txt
Description: THIN CONSOLIDATION NOTE -- this document describes the same core mechanic as
    "FXAlexG Swing Trading Strategy (Step-by-Step Guide).txt", already implemented in
    strategy_fxalexg_mtf_swing.py (batch 2, converted 2026-09-12): multi-timeframe trend
    alignment + S/R "area of interest" + lower-timeframe confirmation pattern (engulfing / EMA
    rejection). Text differs (different write-up of the same trader's method) but the rule
    itself is functionally identical -- confirmed by reading both documents in full. No new
    function is written here per the interface spec's near-duplicate consolidation rule; this
    module re-exports the existing implementation under this document's own descriptive name.
"""
from __future__ import annotations

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_fxalexg_mtf_swing import (
    strategy_fxalexg_mtf_swing as strategy_swing_fxalexg_mtf_confirm,
)

__all__ = ["strategy_swing_fxalexg_mtf_confirm"]
