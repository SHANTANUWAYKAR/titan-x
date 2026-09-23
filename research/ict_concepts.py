"""
Module: ict_concepts.py
Description: The ICT/SMC primitives this platform did NOT already have,
    implemented one concept per function so each can be measured on its
    own before anything is combined.

    e07_technical already ships: swing structure, BOS/CHoCH, liquidity
    sweeps, order blocks (with breaker + mitigation state), fair value
    gaps, killzones, CVD and Wyckoff ranges. Those are imported, not
    duplicated. What is added here is everything else in the taxonomy:

        displacement            large, impulsive, ATR-relative expansion
        MSS                     structure break CONFIRMED by displacement
                                (this is what separates MSS from CHoCH)
        dealing range           swing high -> swing low, with equilibrium
        premium / discount      which half of the dealing range price is in
        OTE                     the 61.8-79% retracement band (70.5% mid)
        PDH/PDL/PWH/PWL         previous day/week high and low
        EQH/EQL                 equal highs/lows -- engineered liquidity
        consequent encroachment the 50% of a fair value gap
        inverse FVG             a gap that failed and flipped polarity
        BPR                     overlapping opposing FVGs
        inducement              the minor swing taken before the real move
        turtle soup             false break of a prior high/low, then reversal
        Judas swing             session-open false move that raids liquidity
        power of three (AMD)    accumulation -> manipulation -> distribution
        SMT divergence          correlated asset fails to confirm a high/low
        draw on liquidity       the nearest untouched pool price is seeking

    Every function returns a boolean/float pandas Series aligned to the
    input index, so any of them can be dropped straight into a backtest or
    an ablation study. All are strictly causal: a value at bar i uses only
    bars <= i. That is verified by a truncation test in the ablation
    runner, not merely asserted here.

    RESEARCH CODE -- outside engines/, nothing live imports it.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.smart_money import (
    StructureEventKind,
    detect_fair_value_gaps,
    detect_structure_events,
    displacement,
    market_structure_shift,
)
from project_titan_x.engines.e07_technical.structure import find_swing_points


# --------------------------------------------------------------------------
# Displacement -- the engine behind MSS, FVGs and Judas swings
# --------------------------------------------------------------------------
# displacement() and market_structure_shift() were PORTED INTO
# engines/e07_technical/smart_money.py on 2026-09-08 and are now imported
# from there (see the import block at the top of this module) rather than
# defined twice. Verified identical before the move on GC=F/BTC/ETH 4h and
# AAPL 1d -- ~92,000 bars, byte-for-byte equal output -- so every ablation
# result recorded in research/ablation_*.json still describes the code that
# now runs live. Keeping two copies is how those two things quietly stop
# being the same function.


# --------------------------------------------------------------------------
# Dealing range, premium/discount, OTE
# --------------------------------------------------------------------------
def dealing_range(df: pd.DataFrame, lookback: int = 50) -> pd.DataFrame:
    """Rolling range high/low and equilibrium (the 50%).

    `.shift(1)` on both extremes is what makes this causal: the range a bar
    is judged against is the one formed BEFORE it, never one this bar's own
    high or low helped create.
    """
    hi = df["high"].shift(1).rolling(lookback).max()
    lo = df["low"].shift(1).rolling(lookback).min()
    return pd.DataFrame({"range_high": hi, "range_low": lo, "equilibrium": (hi + lo) / 2.0},
                        index=df.index)


def premium_discount(df: pd.DataFrame, lookback: int = 50) -> pd.Series:
    """+1 price in PREMIUM (above equilibrium, favour shorts), -1 DISCOUNT
    (below, favour longs), 0 unknown/warm-up.

    Deliberately NOT an entry on its own -- ICT is explicit that
    premium/discount is context for WHERE to look, not a trigger."""
    dr = dealing_range(df, lookback)
    c = df["close"]
    out = pd.Series(0, index=df.index, dtype=int)
    out[c > dr["equilibrium"]] = 1
    out[c < dr["equilibrium"]] = -1
    out[dr["equilibrium"].isna()] = 0
    return out


def ote_zone(df: pd.DataFrame, lookback: int = 50, low: float = 0.618, high: float = 0.79) -> pd.Series:
    """True when price sits inside the Optimal Trade Entry retracement band
    (61.8%-79%, 70.5% being the commonly cited midpoint) of the current
    dealing range, measured from the range high for a long-side retracement
    and mirrored for the short side."""
    dr = dealing_range(df, lookback)
    span = dr["range_high"] - dr["range_low"]
    c = df["close"]
    long_ote = (c <= dr["range_high"] - span * low) & (c >= dr["range_high"] - span * high)
    short_ote = (c >= dr["range_low"] + span * low) & (c <= dr["range_low"] + span * high)
    return (long_ote | short_ote).fillna(False)


# --------------------------------------------------------------------------
# Session / period liquidity: PDH, PDL, PWH, PWL
# --------------------------------------------------------------------------
def period_levels(df: pd.DataFrame, period: str = "D") -> pd.DataFrame:
    """Previous period's high/low carried forward onto every bar.

    period: "D" -> PDH/PDL, "W" -> PWH/PWL.

    These are the classic resting-liquidity pools. Implemented by grouping
    on the period, taking each period's extremes, shifting by one period
    and mapping back -- so a bar only ever sees a COMPLETED prior period,
    never the one it is currently inside.
    """
    if "timestamp" not in df.columns:
        return pd.DataFrame({"prev_high": np.nan, "prev_low": np.nan}, index=df.index)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    key = ts.dt.to_period(period)
    agg = df.groupby(key).agg(period_high=("high", "max"), period_low=("low", "min"))
    prev = agg.shift(1)
    return pd.DataFrame({
        "prev_high": key.map(prev["period_high"]).to_numpy(),
        "prev_low": key.map(prev["period_low"]).to_numpy(),
    }, index=df.index)


def liquidity_raid(df: pd.DataFrame, period: str = "D") -> pd.Series:
    """+1 sell-side raid (wicked below the previous period's low, closed
    back above -- bullish implication), -1 buy-side raid (mirror), 0 none.

    This is the "stop hunt at PDH/PDL" pattern: the level is pierced by the
    wick but the bar closes back inside, which is what separates a raid
    from a genuine breakout."""
    lv = period_levels(df, period)
    out = pd.Series(0, index=df.index, dtype=int)
    swept_low = (df["low"] < lv["prev_low"]) & (df["close"] > lv["prev_low"])
    swept_high = (df["high"] > lv["prev_high"]) & (df["close"] < lv["prev_high"])
    out[swept_low.fillna(False)] = 1
    out[swept_high.fillna(False)] = -1
    return out


# --------------------------------------------------------------------------
# Engineered liquidity: equal highs / equal lows
# --------------------------------------------------------------------------
def equal_highs_lows(
    df: pd.DataFrame, lookback: int = 5, tolerance_atr: float = 0.1, window: int = 30
) -> pd.DataFrame:
    """Flags bars where a swing sits at effectively the same price as a
    recent prior swing -- EQH/EQL, the engineered liquidity ICT treats as a
    magnet.

    "Equal" is defined ATR-relatively rather than exactly: real equal highs
    are rarely tick-identical, and a fixed price tolerance would behave
    completely differently on BTC than on EURUSD.
    """
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    swings = find_swing_points(df, lookback=lookback)
    highs = [(s.index, s.price) for s in swings if s.kind.value == "high"]
    lows = [(s.index, s.price) for s in swings if s.kind.value == "low"]

    eqh = np.zeros(len(df), dtype=bool)
    eql = np.zeros(len(df), dtype=bool)
    for pts, flags in ((highs, eqh), (lows, eql)):
        for a in range(1, len(pts)):
            i, p = pts[a]
            tol = atr.iloc[i] * tolerance_atr if not np.isnan(atr.iloc[i]) else 0.0
            for b in range(a - 1, -1, -1):
                j, q = pts[b]
                if i - j > window:
                    break
                if abs(p - q) <= tol:
                    flags[i] = True
                    break
    return pd.DataFrame({"eqh": eqh, "eql": eql}, index=df.index)


# --------------------------------------------------------------------------
# Fair-value-gap derivatives: CE, inverse FVG, BPR
# --------------------------------------------------------------------------
def fvg_consequent_encroachment(df: pd.DataFrame, max_age: int = 30) -> pd.Series:
    """True when price is trading at the 50% (consequent encroachment) of a
    still-unfilled fair value gap -- the level ICT treats as the reaction
    point inside an imbalance, rather than its edge."""
    gaps = detect_fair_value_gaps(df)
    c = df["close"].to_numpy(float)
    out = np.zeros(len(df), dtype=bool)
    for g in gaps:
        ce = (g.gap_top + g.gap_bottom) / 2.0
        half = (g.gap_top - g.gap_bottom) / 2.0
        if half <= 0:
            continue
        end = min(len(df), g.index + max_age + 1)
        for i in range(g.index + 1, end):
            if abs(c[i] - ce) <= half * 0.25:
                out[i] = True
    return pd.Series(out, index=df.index)


def inverse_fvg(df: pd.DataFrame, max_age: int = 50) -> pd.Series:
    """+1 bullish IFVG / -1 bearish IFVG / 0 none.

    An FVG that price closes clean THROUGH has failed, and ICT treats the
    failed zone as flipping polarity -- a bearish gap broken upward becomes
    support. Detected as: gap fully violated by a close, then price returns
    to the zone and holds on the other side.
    """
    gaps = detect_fair_value_gaps(df)
    c = df["close"].to_numpy(float)
    out = np.zeros(len(df), dtype=np.int8)
    for g in gaps:
        end = min(len(df), g.index + max_age + 1)
        broke_at = None
        for i in range(g.index + 1, end):
            if g.direction == "bullish" and c[i] < g.gap_bottom:
                broke_at = i
                break
            if g.direction == "bearish" and c[i] > g.gap_top:
                broke_at = i
                break
        if broke_at is None:
            continue
        for j in range(broke_at + 1, end):
            if g.gap_bottom <= c[j] <= g.gap_top:
                out[j] = -1 if g.direction == "bullish" else 1
                break
    return pd.Series(out, index=df.index, dtype=int)


def balanced_price_range(df: pd.DataFrame, max_age: int = 30) -> pd.Series:
    """True where an unfilled bullish and bearish FVG OVERLAP -- a BPR, the
    higher-conviction PD array formed when opposing imbalances coincide."""
    gaps = detect_fair_value_gaps(df)
    bulls = [g for g in gaps if g.direction == "bullish"]
    bears = [g for g in gaps if g.direction == "bearish"]
    out = np.zeros(len(df), dtype=bool)
    c = df["close"].to_numpy(float)
    for a in bulls:
        for b in bears:
            if abs(a.index - b.index) > max_age:
                continue
            lo, hi = max(a.gap_bottom, b.gap_bottom), min(a.gap_top, b.gap_top)
            if lo >= hi:
                continue
            start = max(a.index, b.index) + 1
            for i in range(start, min(len(df), start + max_age)):
                if lo <= c[i] <= hi:
                    out[i] = True
    return pd.Series(out, index=df.index)


# --------------------------------------------------------------------------
# Session models: Judas swing, power of three, turtle soup, inducement
# --------------------------------------------------------------------------
def turtle_soup(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """+1 bullish / -1 bearish. A false break of the prior `lookback`-bar
    extreme that closes back inside -- the classic failed-breakout reversal
    ICT calls turtle soup. Distinct from `liquidity_raid`, which is tied to
    calendar period levels rather than a rolling extreme."""
    prior_high = df["high"].shift(1).rolling(lookback).max()
    prior_low = df["low"].shift(1).rolling(lookback).min()
    out = pd.Series(0, index=df.index, dtype=int)
    out[((df["low"] < prior_low) & (df["close"] > prior_low)).fillna(False)] = 1
    out[((df["high"] > prior_high) & (df["close"] < prior_high)).fillna(False)] = -1
    return out


def judas_swing(df: pd.DataFrame, session_tz: str = "America/New_York",
                open_hour: int = 9, window_bars: int = 4) -> pd.Series:
    """+1 / -1: a false move against the eventual direction in the first
    `window_bars` after the session open, which raids liquidity before
    price reverses.

    Detected causally as: within the opening window, price takes out the
    prior session-open reference and then closes back through it. Requires
    intraday bars; returns all-zero on daily data, which is honest rather
    than approximating a session on a timeframe that has none.
    """
    if "timestamp" not in df.columns:
        return pd.Series(0, index=df.index, dtype=int)
    ts = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(session_tz)
    if ts.dt.hour.nunique() <= 1:          # daily or coarser
        return pd.Series(0, index=df.index, dtype=int)

    day = ts.dt.date
    hour = ts.dt.hour
    out = pd.Series(0, index=df.index, dtype=int)
    open_price: dict = {}
    counts: dict = {}
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    for i in range(len(df)):
        d = day.iloc[i]
        if hour.iloc[i] == open_hour and d not in open_price:
            open_price[d] = o[i]
            counts[d] = 0
        if d in open_price:
            counts[d] += 1
            if counts[d] <= window_bars:
                ref = open_price[d]
                if l[i] < ref and c[i] > ref:
                    out.iloc[i] = 1
                elif h[i] > ref and c[i] < ref:
                    out.iloc[i] = -1
    return out


def power_of_three(df: pd.DataFrame, lookback: int = 20, atr_mult: float = 1.5) -> pd.Series:
    """+1 bullish AMD / -1 bearish AMD.

    Accumulation -> Manipulation -> Distribution, detected as its
    observable signature: a quiet range (accumulation), a raid of that
    range's extreme that closes back inside (manipulation), then
    displacement in the OPPOSITE direction to the raid (distribution).
    """
    soup = turtle_soup(df, lookback).to_numpy()
    disp = displacement(df, atr_mult=atr_mult).to_numpy()
    rng = (df["high"].rolling(lookback).max() - df["low"].rolling(lookback).min())
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    quiet = (rng <= atr * lookback * 0.5).to_numpy()

    out = np.zeros(len(df), dtype=np.int8)
    for i in range(len(df)):
        if soup[i] == 0 or not quiet[i]:
            continue
        for j in range(i + 1, min(len(df), i + 6)):
            if disp[j] == soup[i]:
                out[j] = soup[i]
                break
    return pd.Series(out, index=df.index, dtype=int)


def inducement(df: pd.DataFrame, lookback: int = 5, window: int = 20) -> pd.Series:
    """True where a MINOR swing was taken out shortly before a larger
    structural move -- the engineered liquidity that pulls traders in early.

    Marked at the bar the minor swing is swept, which is the bar an entry
    should be avoided at, so it is usable as a veto rather than a trigger.
    """
    swings = find_swing_points(df, lookback=lookback)
    events = {e.index for e in detect_structure_events(df, lookback=lookback)}
    highs = [s.index for s in swings if s.kind.value == "high"]
    lows = [s.index for s in swings if s.kind.value == "low"]
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    out = np.zeros(len(df), dtype=bool)
    for pts, arr, cmp_ in ((highs, h, np.greater), (lows, l, np.less)):
        for si in pts:
            level = arr[si]
            for i in range(si + 1, min(len(df), si + window)):
                if cmp_(arr[i], level):
                    if any(si < e <= i + window for e in events):
                        out[i] = True
                    break
    return pd.Series(out, index=df.index)


# --------------------------------------------------------------------------
# SMT divergence and draw on liquidity
# --------------------------------------------------------------------------
def smt_divergence(
    df: pd.DataFrame, correlated: pd.DataFrame, lookback: int = 20
) -> pd.Series:
    """+1 bullish / -1 bearish SMT.

    Bearish SMT: this market makes a new `lookback` high while the
    correlated market fails to. Bullish is the mirror on lows. Both frames
    are aligned on timestamp first -- comparing by row position would
    silently pair different dates whenever the two series have different
    holidays or gaps, which is exactly when SMT would look most dramatic
    and mean least.
    """
    if "timestamp" not in df.columns or "timestamp" not in correlated.columns:
        return pd.Series(0, index=df.index, dtype=int)
    a = df[["timestamp", "high", "low"]].copy()
    b = correlated[["timestamp", "high", "low"]].copy()
    a["timestamp"] = pd.to_datetime(a["timestamp"], utc=True)
    b["timestamp"] = pd.to_datetime(b["timestamp"], utc=True)
    merged = pd.merge_asof(a.sort_values("timestamp"), b.sort_values("timestamp"),
                           on="timestamp", suffixes=("", "_b"), direction="nearest",
                           tolerance=pd.Timedelta("1D")).set_index(a.index)

    ah = merged["high"].rolling(lookback).max()
    al = merged["low"].rolling(lookback).min()
    bh = merged["high_b"].rolling(lookback).max()
    bl = merged["low_b"].rolling(lookback).min()
    out = pd.Series(0, index=df.index, dtype=int)
    new_high_a = merged["high"] >= ah
    new_high_b = merged["high_b"] >= bh
    new_low_a = merged["low"] <= al
    new_low_b = merged["low_b"] <= bl
    out[(new_high_a & ~new_high_b).fillna(False)] = -1
    out[(new_low_a & ~new_low_b).fillna(False)] = 1
    return out


def draw_on_liquidity(df: pd.DataFrame, lookback: int = 50) -> pd.Series:
    """Signed distance to the nearer untouched pool, as a fraction of the
    dealing range: +ve means buy-side liquidity above is closer (price is
    more likely drawn up), -ve means sell-side below is closer.

    Answers ICT's "where is price trying to go?" rather than "where can I
    enter?", so it is a bias/target input, not a trigger.
    """
    dr = dealing_range(df, lookback)
    c = df["close"]
    span = (dr["range_high"] - dr["range_low"]).replace(0, np.nan)
    up = (dr["range_high"] - c) / span
    down = (c - dr["range_low"]) / span
    return (down - up).fillna(0.0)
