"""
Module: strategy_best_fibonacci_strategy.py
STATUS: this file previously contained a PLACEHOLDER body that always returned a
    zero signal (it never traded). That was a real defect in the original first-pass
    PDF conversion. This concept has since been properly implemented -- real logic,
    no-lookahead verified, smoke-tested on real data, and wired into the live engine.

    This module now re-exports that REAL implementation, so importing from here gives
    you a working strategy function rather than a hollow stub.

Real implementation: project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_fibonacci_deep_retracement_pullback
Function: strategy_fibonacci_deep_retracement_pullback

See that module's own docstring for the exact source document(s), the trading rules,
and every interpretive assumption made during conversion.
"""
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_fibonacci_deep_retracement_pullback import strategy_fibonacci_deep_retracement_pullback

# Backwards-compatible alias: the name this file originally (nominally) provided.
strategy_best_fibonacci_strategy = strategy_fibonacci_deep_retracement_pullback

__all__ = ["strategy_fibonacci_deep_retracement_pullback", "strategy_best_fibonacci_strategy"]
