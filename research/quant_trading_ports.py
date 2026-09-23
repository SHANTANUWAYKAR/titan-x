"""
Module: quant_trading_ports.py
Description: Techniques ported from je-suis-tm/quant-trading (Apache-2.0,
    cloned read-only for reference), reimplemented in this project's own
    style rather than copied.

    WHAT WAS ACTUALLY NEW. Of the repo's 12 backtest scripts, this
    platform already covers MACD, Bollinger, RSI patterns, London
    breakout (session logic) and pair trading (cointegration lives in
    e12_quant_research). Options Straddle and the VIX Calculator are a
    different asset domain, and the "project" folders are quantamental
    studies rather than tradeable rules. Four techniques were genuinely
    absent and are ported here:

      heikin_ashi            a real noise-reduction transform this
                             platform had nowhere -- HA bars filter the
                             chop that whipsaws every EMA rule we run
      dual_thrust            opening-range breakout using an ASYMMETRIC
                             threshold built from a multi-day range
      parabolic_sar          the classic accelerating trailing stop
      awesome_oscillator     5/34 SMA of the median price, a momentum
                             read independent of close-only measures

    Two of these are worth more as INFRASTRUCTURE than as strategies:
    heikin_ashi is a transform any existing strategy can be run on, and
    parabolic_sar is an exit rule that could replace the ATR trail. Both
    are exposed as standalone functions for exactly that reason.

    ATTRIBUTION AND DIFFERENCES: logic was read from the source and
    rewritten. Two deliberate corrections were needed --
      - the source's Heikin-Ashi seeds HA-open with a Python loop and
        indexes with chained assignment; vectorised here, and the
        recursive HA-open is computed with an explicit accumulator since
        it genuinely cannot be vectorised.
      - the source's SAR takes positions with `np.where(sar < close, 1, 0)`
        which is LONG-ONLY and never shorts. Mirrored here so the short
        side actually trades, since every other strategy in this project
        is two-sided and a long-only comparison would be misleading.

    RESEARCH CODE -- outside engines/, nothing live imports it.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Heikin-Ashi transform. Returns a frame with the SAME column names
    (open/high/low/close) so any existing strategy can be run on it
    unchanged -- that reusability is the point.

        HA close = (O + H + L + C) / 4
        HA open  = (prev HA open + prev HA close) / 2   [recursive]
        HA high  = max(H, HA open, HA close)
        HA low   = min(L, HA open, HA close)

    HA open is genuinely recursive -- each value depends on the previous
    HA bar, not on raw price -- so it is accumulated explicitly. Strictly
    causal: bar i uses only bars <= i.
    """
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ha_close = (o + h + l + c) / 4.0
    ha_open = np.empty(len(df), dtype=float)
    ha_open[0] = (o[0] + c[0]) / 2.0
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
    out = df.copy()
    out["open"] = ha_open
    out["close"] = ha_close
    out["high"] = np.maximum.reduce([h, ha_open, ha_close])
    out["low"] = np.minimum.reduce([l, ha_open, ha_close])
    return out


def heikin_ashi_trend(enriched: pd.DataFrame, confirm: int = 2) -> pd.Series:
    """Trade HA bar colour, requiring `confirm` consecutive same-colour
    bars. The confirmation is what makes HA useful rather than just
    another close-vs-open rule: single HA bars still flip in chop."""
    ha = heikin_ashi(enriched)
    bull = (ha["close"] > ha["open"]).to_numpy()
    bear = (ha["close"] < ha["open"]).to_numpy()
    out = np.zeros(len(enriched), dtype=np.int8)
    run_up = run_dn = 0
    for i in range(len(enriched)):
        run_up = run_up + 1 if bull[i] else 0
        run_dn = run_dn + 1 if bear[i] else 0
        if run_up >= confirm:
            out[i] = 1
        elif run_dn >= confirm:
            out[i] = -1
        else:
            out[i] = out[i - 1] if i else 0
    return pd.Series(out, index=enriched.index, dtype=int)


def dual_thrust(enriched: pd.DataFrame, lookback: int = 4, k1: float = 0.5,
                k2: float = 0.5) -> pd.Series:
    """Dual Thrust opening-range breakout.

        range = max( HH(n) - LC(n),  HC(n) - LL(n) )
        upper = open + k1 * range
        lower = open - k2 * range

    The range definition is the interesting part and the reason this is
    not just another Donchian: it mixes highs against CLOSES rather than
    highs against lows, so a single spike wick cannot inflate it the way
    it inflates a high-low range.

    k1 and k2 are deliberately separate -- an asymmetric threshold is the
    strategy's own idea, letting the long and short trigger sit at
    different distances. All inputs are shifted so the range and the
    session open are strictly prior to the bar being evaluated.
    """
    h, l, c = enriched["high"], enriched["low"], enriched["close"]
    hh = h.shift(1).rolling(lookback).max()
    lc = c.shift(1).rolling(lookback).min()
    hc = c.shift(1).rolling(lookback).max()
    ll = l.shift(1).rolling(lookback).min()
    rng = pd.concat([hh - lc, hc - ll], axis=1).max(axis=1)

    ref = enriched["open"]
    upper = ref + k1 * rng
    lower = ref - k2 * rng
    out = pd.Series(0, index=enriched.index, dtype=int)
    out[(c > upper).fillna(False)] = 1
    out[(c < lower).fillna(False)] = -1
    return out.replace(0, np.nan).ffill().fillna(0).astype(int)


def parabolic_sar(df: pd.DataFrame, initial_af: float = 0.02, step_af: float = 0.02,
                  end_af: float = 0.2) -> pd.Series:
    """Parabolic SAR level (not a signal -- see parabolic_sar_trend).

    Standard Wilder construction: SAR accelerates toward price as the
    extreme point extends, the acceleration factor stepping up only when a
    NEW extreme prints and resetting on a flip. The prior two bars'
    extremes clamp the SAR so it can never sit inside the current bar's
    range, which is the detail most simplified implementations drop.

    Exposed separately because its real value here is as an EXIT rule --
    a drop-in alternative to the ATR trail used by trend_pullback_atr_trail
    and donchian_atr_trail.
    """
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    n = len(df)
    sar = np.zeros(n)
    if n < 3:
        return pd.Series(sar, index=df.index)

    trend = 1 if h[1] >= h[0] else -1
    sar[1] = l[0] if trend > 0 else h[0]
    ep = h[1] if trend > 0 else l[1]
    af = initial_af
    for i in range(2, n):
        prior = sar[i - 1] + af * (ep - sar[i - 1])
        if trend > 0:
            prior = min(prior, l[i - 1], l[i - 2])      # never inside recent range
            if l[i] < prior:                            # flip to downtrend
                trend, sar[i], ep, af = -1, ep, l[i], initial_af
            else:
                sar[i] = prior
                if h[i] > ep:
                    ep, af = h[i], min(end_af, af + step_af)
        else:
            prior = max(prior, h[i - 1], h[i - 2])
            if h[i] > prior:
                trend, sar[i], ep, af = 1, ep, h[i], initial_af
            else:
                sar[i] = prior
                if l[i] < ep:
                    ep, af = l[i], min(end_af, af + step_af)
    return pd.Series(sar, index=df.index)


def parabolic_sar_trend(enriched: pd.DataFrame, initial_af: float = 0.02,
                        step_af: float = 0.02, end_af: float = 0.2) -> pd.Series:
    """+1 when price is above SAR, -1 below.

    The source implementation is LONG-ONLY (`np.where(sar < close, 1, 0)`).
    Mirrored here so the short side genuinely trades -- every other
    strategy in this project is two-sided, and comparing a long-only rule
    against them would flatter or damn it for the wrong reason.
    """
    sar = parabolic_sar(enriched, initial_af, step_af, end_af)
    out = pd.Series(0, index=enriched.index, dtype=int)
    out[(enriched["close"] > sar)] = 1
    out[(enriched["close"] < sar)] = -1
    out.iloc[:2] = 0                       # SAR undefined over its own seed bars
    return out


def awesome_oscillator(enriched: pd.DataFrame, fast: int = 5, slow: int = 34) -> pd.Series:
    """AO = SMA(median price, 5) - SMA(median price, 34).

    Median price (H+L)/2 rather than close is the point: it reads momentum
    from where price actually traded during the bar, independent of where
    it happened to settle, so it does not agree with every close-based
    oscillator this platform already has.
    """
    median = (enriched["high"] + enriched["low"]) / 2.0
    return median.rolling(fast).mean() - median.rolling(slow).mean()


def awesome_oscillator_trend(enriched: pd.DataFrame, fast: int = 5, slow: int = 34) -> pd.Series:
    """Trade AO zero-line crosses."""
    ao = awesome_oscillator(enriched, fast, slow)
    out = pd.Series(0, index=enriched.index, dtype=int)
    out[ao > 0] = 1
    out[ao < 0] = -1
    out[ao.isna()] = 0
    return out


QT_STRATEGIES = {
    "heikin_ashi_trend": heikin_ashi_trend,
    "dual_thrust": dual_thrust,
    "parabolic_sar_trend": parabolic_sar_trend,
    "awesome_oscillator_trend": awesome_oscillator_trend,
}
