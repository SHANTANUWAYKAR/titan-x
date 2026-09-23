"""
Module: dual_thrust.py
Description: Dual Thrust range-breakout, ported from research/ after it
    beat the live override on BOTH crypto daily markets.

    Source: je-suis-tm/quant-trading (Apache-2.0, cloned read-only for
    reference; "Dual Thrust backtest.py"). Logic was read and rewritten in
    this module's style -- nothing copied. Originally prototyped in
    research/quant_trading_ports.py and promoted here deliberately, which
    is the one-way path research/__init__.py describes: research may
    import engines, engines never import research, and anything that earns
    its place gets ported with its own tests and a real validation sweep.

    WHY THIS IS NOT JUST ANOTHER DONCHIAN. The range is built from highs
    against CLOSES, not highs against lows:

        range = max( HH(n) - LC(n),  HC(n) - LL(n) )
        upper = open + k1 * range
        lower = open - k2 * range

    A single spike wick inflates a high-low range and widens a Donchian
    channel for the whole lookback; mixing highs against closes bounds
    that, so the threshold reflects where price actually SETTLED. k1 and
    k2 are separate on purpose -- an asymmetric threshold is the
    strategy's own idea, letting the long and short triggers sit at
    different distances from the open.

    EVIDENCE FOR THE PORT (E26's unweakened bar, real 10y data):
      ETHUSD 1d  dual_thrust(8, 0.7)  55.0% win, 3.89R, OOS 1.01, 40 trades
                 vs incumbent donchian_breakout 45.2% win, OOS 0.63
      BTCUSD 1d  dual_thrust(8, 0.5)  45.1% win, 2.60R, OOS 0.72, 113 trades
                 vs incumbent trend_pullback_atr_trail 31.8% win, OOS 0.69
    The BTCUSD case is the stronger one: higher win rate AND nearly double
    the trade count, so it is not buying accuracy by trading less.

    Robustness was checked as a parameter PLATEAU, not a single point: all
    16 combinations of lookback (4-10) x k (0.5-0.8) returned positive
    expectancy on ETHUSD 1d, ranging 1.54 to 34.97. Note the trade-off
    inside that plateau -- the highest expectancy readings come from the
    fewest trades (34.97 from just 20 trades, below E26's 30-trade floor),
    so the selected configurations are the ones with real sample size, not
    the biggest number.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-23
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def dual_thrust(
    enriched: pd.DataFrame, lookback: int = 8, k1: float = 0.7, k2: float = 0.7
) -> pd.Series:
    """Dual Thrust breakout. +1 long / -1 short, held until the opposite
    threshold breaks.

    No lookahead: every component of `range` is `.shift(1)`-ed before the
    rolling window, so the band a bar is judged against is built strictly
    from PRIOR bars. Verified at four truncation points (0.4/0.6/0.8/0.93)
    on real ETHUSD 1d data.

    The reference implementation clears positions at the end of each
    session; that is meaningless on the daily/4h bars this platform
    validates on, so the position is instead held until the opposite
    threshold triggers -- the standard stop-and-reverse reading, and the
    one every result quoted above was measured with.
    """
    high, low, close = enriched["high"], enriched["low"], enriched["close"]

    hh = high.shift(1).rolling(lookback).max()
    lc = close.shift(1).rolling(lookback).min()
    hc = close.shift(1).rolling(lookback).max()
    ll = low.shift(1).rolling(lookback).min()
    rng = pd.concat([hh - lc, hc - ll], axis=1).max(axis=1)

    reference = enriched["open"]
    upper = reference + k1 * rng
    lower = reference - k2 * rng

    signal = pd.Series(0, index=enriched.index, dtype=int)
    signal[(close > upper).fillna(False)] = 1
    signal[(close < lower).fillna(False)] = -1
    # Stop-and-reverse: carry the last real trigger until the other side
    # fires. Only ever looks backward, so this introduces no lookahead.
    return signal.replace(0, np.nan).ffill().fillna(0).astype(int)


def heikin_ashi_frame(enriched: pd.DataFrame) -> pd.DataFrame:
    """Heikin-Ashi transform, returned with the SAME column names so any
    existing strategy in this module can be run on smoothed bars without
    modification -- that reusability is why it is worth having, more than
    the trend rule built on it.

        HA close = (O + H + L + C) / 4
        HA open  = (prev HA open + prev HA close) / 2
        HA high  = max(H, HA open, HA close)
        HA low   = min(L, HA open, HA close)

    HA open is genuinely recursive -- each bar depends on the previous HA
    bar rather than on raw price -- so it is accumulated explicitly rather
    than vectorised. Strictly causal.
    """
    o = enriched["open"].to_numpy(dtype=float)
    h = enriched["high"].to_numpy(dtype=float)
    low = enriched["low"].to_numpy(dtype=float)
    c = enriched["close"].to_numpy(dtype=float)

    ha_close = (o + h + low + c) / 4.0
    ha_open = np.empty(len(enriched), dtype=float)
    ha_open[0] = (o[0] + c[0]) / 2.0
    for i in range(1, len(enriched)):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0

    out = enriched.copy()
    out["open"] = ha_open
    out["close"] = ha_close
    out["high"] = np.maximum.reduce([h, ha_open, ha_close])
    out["low"] = np.minimum.reduce([low, ha_open, ha_close])
    return out


def heikin_ashi_trend(enriched: pd.DataFrame, confirm: int = 2) -> pd.Series:
    """Trade Heikin-Ashi bar colour, requiring `confirm` consecutive bars
    of the same colour.

    The confirmation count is what makes this more than a close-vs-open
    rule: a single HA bar still flips in chop, which is exactly the noise
    the transform exists to suppress. Validated as the best archetype for
    SILVER 4h (OOS 0.74) and USDJPY 4h (OOS 1.74) in the porting sweep.
    """
    ha = heikin_ashi_frame(enriched)
    bull = (ha["close"] > ha["open"]).to_numpy()
    bear = (ha["close"] < ha["open"]).to_numpy()

    out = np.zeros(len(enriched), dtype=np.int8)
    run_up = run_down = 0
    for i in range(len(enriched)):
        run_up = run_up + 1 if bull[i] else 0
        run_down = run_down + 1 if bear[i] else 0
        if run_up >= confirm:
            out[i] = 1
        elif run_down >= confirm:
            out[i] = -1
        else:
            out[i] = out[i - 1] if i else 0
    return pd.Series(out, index=enriched.index, dtype=int)
