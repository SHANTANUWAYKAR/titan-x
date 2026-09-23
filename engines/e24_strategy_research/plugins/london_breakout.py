"""
Module: london_breakout.py
Description: London Breakout, ported from je-suis-tm/quant-trading
    ("London Breakout backtest.py", Apache-2.0).

    THE CONCEPT, in the source's own words: FX trades around the clock, but
    London is where most volume executes. Take the last trading hour before
    London opens, set thresholds from that hour's high and low, and when
    London opens, trade a decisive break of either side. Flatten by the end
    of the session rather than holding overnight.

    WHY IT IS NOT A DUPLICATE. E24 already has several breakout archetypes
    (donchian_breakout and its variants), but every one of them defines its
    threshold from a ROLLING lookback of N bars regardless of clock time.
    This defines the threshold from a specific SESSION -- the pre-London
    hour -- and only acts during a specific other session. That is a
    genuinely different hypothesis: it says the Asian range predicts the
    London expansion, not that any N-bar range predicts the next bar.

    ADAPTATIONS, and why each was necessary:

    1. The source needs 1-MINUTE data ("look at the last trading hour...
       examine the first 30 minutes"). This platform's deepest reliable
       intraday history is 15m (EURUSD/GBPUSD both hold ~580,000 real 15m
       bars back to 2003). The windows are therefore expressed in clock
       time and resolved against whatever bar size is passed, rather than
       hardcoding a bar count -- four 15m bars make the pre-London hour.

    2. Sessions use Europe/London LOCAL time via e07_technical.killzones'
       own IANA-backed convention, NOT a fixed UTC offset. London's open in
       UTC moves by an hour twice a year, and a hardcoded offset is
       silently wrong for the weeks around each DST switch. This is the
       same defect this project already documented in STAR-EA's manual
       offset table.

    3. This platform's model is a per-bar signal SERIES (-1/0/1) consumed
       by E26, not an order-placing loop with its own stops. So "clear
       positions on target/stop" becomes "hold the direction until the
       session ends, then flat" -- E26's own exit machinery (signal flip,
       or the opt-in barrier exits added 2026-09-09) supplies the rest.
       That is a real reduction in fidelity to the source and is stated
       here rather than glossed: this port tests the SESSION hypothesis,
       not the source's exact intraday money management.

    NO-LOOKAHEAD. The reference high/low come from bars strictly BEFORE
    London opens, and are frozen for the session (an expanding intraday
    max/min would let a later bar redefine the level an earlier bar was
    judged against). Every comparison a bar makes is against a level fixed
    before that bar existed.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

LONDON_TZ = "Europe/London"


def _london_local(df: pd.DataFrame) -> pd.Series:
    """Bar timestamps in London local wall-clock time.

    Requires a tz-aware `timestamp` column, the same precondition
    e07_technical.killzones.killzone_mask and
    e24_strategy_research.strategies.session_mask both impose.
    """
    ts = df["timestamp"]
    if getattr(ts.dt, "tz", None) is None:
        ts = ts.dt.tz_localize("UTC")
    return ts.dt.tz_convert(ZoneInfo(LONDON_TZ))


def london_breakout(
    df: pd.DataFrame,
    ref_start_hour: int = 6,
    ref_end_hour: int = 7,
    session_end_hour: int = 16,
    buffer_atr_mult: float = 0.0,
    atr_period: int = 14,
) -> pd.Series:
    """+1 long / -1 short / 0 flat.

    ref_start_hour..ref_end_hour  the pre-London reference window (London
                                  local time); its high/low set the levels.
    ref_end_hour..session_end_hour the trading window; a close beyond a
                                  level opens that direction.
    buffer_atr_mult               optional ATR-scaled cushion the close must
                                  clear, not just touch. 0.0 (default)
                                  reproduces the source exactly; a nonzero
                                  value is the false-breakout filter this
                                  platform already found useful in
                                  donchian_breakout_buffer_confirmed.
    """
    if len(df) == 0 or "timestamp" not in df.columns:
        return pd.Series(0, index=df.index, dtype=int)

    local = _london_local(df)
    hour = local.dt.hour.to_numpy()
    day = local.dt.normalize().to_numpy()          # London calendar day
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)

    buffer = np.zeros(len(df), dtype=float)
    if buffer_atr_mult:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        buffer = (tr.rolling(atr_period).mean() * buffer_atr_mult).to_numpy(dtype=float)

    in_ref = (hour >= ref_start_hour) & (hour < ref_end_hour)
    in_session = (hour >= ref_end_hour) & (hour < session_end_hour)

    out = np.zeros(len(df), dtype=np.int8)

    # Group by London calendar day so each session gets its OWN reference
    # range. A single rolling window would bleed one day's range into the
    # next, which is not the hypothesis being tested.
    ref_hi: dict = {}
    ref_lo: dict = {}
    for d, h, l, is_ref in zip(day, high, low, in_ref):
        if not is_ref:
            continue
        if d not in ref_hi or h > ref_hi[d]:
            ref_hi[d] = h
        if d not in ref_lo or l < ref_lo[d]:
            ref_lo[d] = l

    position = 0
    prev_day = None
    for i in range(len(df)):
        d = day[i]
        if d != prev_day:
            position = 0           # never carry a session's direction into the next
            prev_day = d
        if not in_session[i]:
            out[i] = 0
            position = 0           # flat outside the session, including the ref window
            continue
        hi, lo = ref_hi.get(d), ref_lo.get(d)
        if hi is None or lo is None:
            out[i] = 0             # no reference window for this day (holiday/gap)
            continue
        b = buffer[i]
        if b != b:                 # NaN ATR during warm-up -> no cushion
            b = 0.0
        if position == 0:
            if close[i] > hi + b:
                position = 1
            elif close[i] < lo - b:
                position = -1
        out[i] = position

    return pd.Series(out, index=df.index, dtype=int)


def london_breakout_buffered(df: pd.DataFrame, **kwargs) -> pd.Series:
    """London Breakout with a 0.25-ATR cushion on the break.

    Separate registered archetype rather than a parameter default so the
    grid can test the source's exact rule and the filtered variant against
    each other, the same way donchian_breakout and
    donchian_breakout_buffer_confirmed already coexist.
    """
    kwargs.setdefault("buffer_atr_mult", 0.25)
    return london_breakout(df, **kwargs)
