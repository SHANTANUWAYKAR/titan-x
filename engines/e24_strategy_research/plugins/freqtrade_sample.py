"""
Module: freqtrade_sample.py
Description: Port of freqtrade's shipped reference strategy
    (https://github.com/freqtrade/freqtrade, cloned read-only for
    reference; source: freqtrade/templates/sample_strategy.py,
    populate_entry_trend/populate_exit_trend).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-21
"""

import pandas as pd


def freqtrade_rsi_tema_bb(
    enriched: pd.DataFrame, buy_rsi: float = 30.0, sell_rsi: float = 70.0, tema_period: int = 9
) -> pd.Series:
    """freqtrade sample_strategy.py, ported rule for rule:

    ENTRY (populate_entry_trend): RSI crosses above `buy_rsi` (default 30,
    the template's buy_rsi default) AND TEMA <= Bollinger middle band AND
    TEMA rising AND volume > 0.
    EXIT (populate_exit_trend): RSI crosses above `sell_rsi` (default 70)
    AND TEMA > Bollinger middle band AND TEMA falling.

    LONG-ONLY, exactly like the source (a spot-exchange template with no
    short side) -- returning 0/1 only is deliberate fidelity, not an
    oversight. TEMA(9) is computed here (3*EMA1 - 3*EMA2 + EMA3, all
    backward-looking ewm) because e07_technical's enriched frame doesn't
    carry TEMA; rsi and bb_middle come from the enriched frame itself.
    "crossed_above" replicates qtpylib's definition: previous value at or
    below the threshold, current value above it.
    """
    close = enriched["close"]
    e1 = close.ewm(span=tema_period, adjust=False).mean()
    e2 = e1.ewm(span=tema_period, adjust=False).mean()
    e3 = e2.ewm(span=tema_period, adjust=False).mean()
    tema = 3 * e1 - 3 * e2 + e3

    rsi = enriched["rsi"].fillna(50)
    bb_middle = enriched["bb_middle"].fillna(close)
    volume = enriched["volume"] if "volume" in enriched.columns else pd.Series(1, index=enriched.index)
    tema_rising = tema > tema.shift(1)

    entry = (
        (rsi > buy_rsi) & (rsi.shift(1) <= buy_rsi)
        & (tema <= bb_middle) & tema_rising & (volume.fillna(0) > 0)
    )
    exit_ = (
        (rsi > sell_rsi) & (rsi.shift(1) <= sell_rsi)
        & (tema > bb_middle) & ~tema_rising
    )

    raw = pd.Series(float("nan"), index=enriched.index)
    raw[exit_] = 0
    raw[entry] = 1
    return raw.ffill().fillna(0).astype(int)
