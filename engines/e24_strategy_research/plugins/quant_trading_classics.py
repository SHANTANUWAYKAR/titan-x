"""
Module: quant_trading_classics.py
Description: Three archetypes ported from je-suis-tm/quant-trading
    (Apache-2.0) that had no equivalent in E24: Awesome Oscillator,
    Parabolic SAR, and Shooting Star.

    Dual Thrust, Heikin-Ashi, MACD and London Breakout from the same repo
    are already live elsewhere in this package; RSI and Bollinger have E24
    equivalents. These three are the remainder.

    THE SHOOTING STAR PORT FIXES THREE LOOKAHEADS IN THE SOURCE. They are
    documented at that function. The other two are clean -- verified: zero
    negative shifts and no whole-series statistics in either source file.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def awesome_oscillator(df: pd.DataFrame, fast: int = 5, slow: int = 34) -> pd.Series:
    """+1 when the AO is positive, -1 when negative.

    The standard definition, and the source's: a fast and a slow simple
    moving average of the MEDIAN price (high+low)/2 rather than the close.
    Using the median price is the whole point of the indicator -- it is
    what makes it different from a plain MA cross on closes, which E24
    already has as ma_cross_50_200.

    `.shift(1)` on the oscillator is the causality guard: the value that
    decides bar i's position is the one computed from bars up to i-1, so
    the rolling means never include the bar being traded.
    """
    median = (df["high"] + df["low"]) / 2.0
    ao = median.rolling(fast).mean() - median.rolling(slow).mean()
    prev = ao.shift(1)
    out = np.zeros(len(df), dtype=np.int8)
    out[(prev > 0).to_numpy(na_value=False)] = 1
    out[(prev < 0).to_numpy(na_value=False)] = -1
    return pd.Series(out, index=df.index, dtype=int)


def parabolic_sar(
    df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2
) -> pd.Series:
    """+1 while SAR sits below price (uptrend), -1 while above.

    Wilder's Parabolic Stop-and-Reverse, computed iteratively because it is
    genuinely path-dependent -- each bar's SAR depends on the running
    extreme point and acceleration factor since the last reversal, so there
    is no vectorised form. The source says the same ("it is very painful to
    calculate sar").

    Causal by construction: the SAR value applied at bar i is derived
    entirely from bars up to i-1, and the position is shifted one further
    bar so the reversal is acted on only after the bar that caused it has
    closed.
    """
    n = len(df)
    if n < 3:
        return pd.Series(np.zeros(n, dtype=int), index=df.index, dtype=int)

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)

    trend = np.zeros(n, dtype=np.int8)
    sar = np.full(n, np.nan, dtype=float)

    # Seed from the first two bars. Any seed converges quickly; SAR is
    # self-correcting, which is why a warm-up is acceptable rather than a
    # fabricated starting value.
    up = high[1] >= high[0]
    ep = high[1] if up else low[1]
    af = af_start
    sar[1] = low[0] if up else high[0]
    trend[1] = 1 if up else -1

    for i in range(2, n):
        prev_sar = sar[i - 1]
        cur = prev_sar + af * (ep - prev_sar)

        if up:
            # SAR may never move into the previous two bars' range.
            cur = min(cur, low[i - 1], low[i - 2])
            if low[i] < cur:                      # reversal
                up = False
                cur = ep                          # SAR jumps to the prior extreme
                ep = low[i]
                af = af_start
            elif high[i] > ep:
                ep = high[i]
                af = min(af + af_step, af_max)
        else:
            cur = max(cur, high[i - 1], high[i - 2])
            if high[i] > cur:
                up = True
                cur = ep
                ep = high[i]
                af = af_start
            elif low[i] < ep:
                ep = low[i]
                af = min(af + af_step, af_max)

        sar[i] = cur
        trend[i] = 1 if up else -1

    # Act on the trend the bar AFTER it is established, matching every other
    # strategy in this package and E26's own next-bar-open fill convention.
    return pd.Series(trend, index=df.index, dtype=int).shift(1).fillna(0).astype(int)


def shooting_star(
    df: pd.DataFrame,
    lower_bound: float = 0.2,
    body_size: float = 0.5,
    holding_period: int = 7,
    body_window: int = 50,
) -> pd.Series:
    """Shooting star reversal -- SHORT only, held `holding_period` bars.

    THREE LOOKAHEADS IN THE SOURCE, ALL FIXED HERE. Porting this file
    verbatim would produce a strategy that cannot be traded, with backtest
    numbers to match -- the same defect class as the order-block bug that
    once reported a 94.8% win rate on this platform.

    1. `condition7 = df['High'].shift(-1) <= df['High']` reads the NEXT
       bar's high.
    2. `condition8 = df['Close'].shift(-1) <= df['Close']` reads the NEXT
       bar's close.
       Both are part of the pattern's real definition (the star must be
       followed by a lower candle), so they are not dropped -- the SIGNAL
       IS EMITTED ONE BAR LATER instead, at the confirming bar, which is
       the first moment the pattern is actually knowable.

    3. `condition3` compares each bar's body against
       `np.mean(df['Open'] - df['Close'])` -- the mean over the WHOLE
       dataframe, future bars included. Replaced with a trailing rolling
       mean over `body_window` bars, so the threshold a bar is judged
       against is built only from bars before it.

    The source's own comment concedes the eight-condition definition is
    "too rigid" in practice; that is left as-is rather than loosened,
    because relaxing a rule to produce more trades is exactly the tuning
    Rule 6 forbids.
    """
    n = len(df)
    if n < 3:
        return pd.Series(np.zeros(n, dtype=int), index=df.index, dtype=int)

    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    body = np.abs(o - c)
    # Causal replacement for the source's whole-series mean.
    ref_body = pd.Series(o - c).abs().rolling(body_window, min_periods=5).mean().shift(1).to_numpy()

    with np.errstate(invalid="ignore"):
        cond1 = o >= c                                        # red / neutral candle
        cond2 = (c - lo) < lower_bound * body                 # little lower wick
        cond3 = body < ref_body * body_size                   # small body vs trailing norm
        cond4 = (h - o) >= 2.0 * (o - c)                      # long upper wick
        cond5 = np.r_[False, c[1:] >= c[:-1]]                 # uptrend into it
        cond6 = np.r_[False, False, c[1:-1] >= c[:-2]]        # ...for two bars
        cond6 = np.r_[cond6, [False]][:n]

    star = cond1 & cond2 & cond3 & cond4 & cond5 & cond6
    star &= np.isfinite(ref_body)

    out = np.zeros(n, dtype=np.int8)
    i = 0
    while i < n - 1:
        if star[i]:
            # Conditions 7 and 8, evaluated on the bar AFTER the star.
            if h[i + 1] <= h[i] and c[i + 1] <= c[i]:
                end = min(n, i + 1 + holding_period)
                out[i + 1:end] = -1
                i = end            # no overlapping entries
                continue
        i += 1
    return pd.Series(out, index=df.index, dtype=int)
