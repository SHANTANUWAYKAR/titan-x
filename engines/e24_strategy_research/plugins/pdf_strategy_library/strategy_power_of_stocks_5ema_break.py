"""
Module: strategy_power_of_stocks_5ema_break.py
Source document(s): POWER OF STOCKS STRATEGY.txt
Description: THIN CONSOLIDATION NOTE -- this document describes the exact same core rule as
    "5EMA TRADING STRATEGY POWEROFSTOCKS.txt", already implemented in
    strategy_5ema_low_high_break_powerofstocks.py (batch 1, converted 2026-09-12): find a
    candle whose low/high never touches the 5 EMA (signal candle), then enter when the NEXT
    candle breaks that signal candle's low (sell) or high (buy). Confirmed by reading both
    documents in full -- both are "Power of Stocks" 5-EMA guides with the identical mechanic,
    just from different days of the same educational series ("Day 13" here). No new function
    is written here per the interface spec's near-duplicate consolidation rule; this module
    re-exports the existing implementation under this document's own descriptive name so the
    strategy is still discoverable/traceable to THIS source document in an index or grep.
"""
from __future__ import annotations

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_5ema_low_high_break_powerofstocks import (
    strategy_5ema_low_high_break_powerofstocks as strategy_power_of_stocks_5ema_break,
)

__all__ = ["strategy_power_of_stocks_5ema_break"]
