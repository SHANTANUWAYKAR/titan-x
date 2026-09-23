"""
Module: strategy_fabio_valentini_scalping_strategy.py
STATUS: this file previously contained a PLACEHOLDER body that always returned a
    zero signal (it never traded). That was a real defect in the original first-pass
    PDF conversion. This concept has since been properly implemented -- real logic,
    no-lookahead verified, smoke-tested on real data, and wired into the live engine.

    This module now re-exports that REAL implementation, so importing from here gives
    you a working strategy function rather than a hollow stub.

Real implementation: project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_fabio_valentini_pullback_scalp
Function: strategy_fabio_valentini_pullback_scalp

See that module's own docstring for the exact source document(s), the trading rules,
and every interpretive assumption made during conversion.
"""
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_fabio_valentini_pullback_scalp import strategy_fabio_valentini_pullback_scalp

# Backwards-compatible alias: the name this file originally (nominally) provided.
strategy_fabio_valentini_scalping_strategy = strategy_fabio_valentini_pullback_scalp

__all__ = ["strategy_fabio_valentini_pullback_scalp", "strategy_fabio_valentini_scalping_strategy"]
