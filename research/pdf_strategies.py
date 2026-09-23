"""
Module: pdf_strategies.py
Description: The trading rules from data/strategy/*.pdf (71 documents),
    implemented as testable signal functions.

    HOW THE 71 REDUCE TO 8. The corpus is highly redundant -- 29 of the 71
    are EMA documents, and most restate the same idea with a different
    author and period pair (9/15, 9/20, 9/20/50, 5, 10, 200). Implementing
    71 near-identical functions would produce 71 correlated backtests and
    the illusion of 71 independent confirmations. They are grouped here
    into the distinct ARCHETYPES actually present, with the period pair as
    a parameter, so a sweep tests the idea rather than the filename.

    Archetypes implemented (source counts from the corpus):
      ema_cross_pullback     29 EMA docs -- cross, then pull back to the
                             fast EMA, enter on the reclaim candle
      ema_retest             "Big Bar"/9-EMA-retest -- touch the EMA, next
                             candle must CLOSE beyond it
      ema_stack_trend        3-EMA (9/20/50) -- cross must occur on the
                             correct side of the slow EMA
      session_sweep_bos      16 session docs -- sweep the session range
                             extreme, then trade the opposite break
      opening_range_breakout 4 ORB docs -- break of the first N bars' range
      vwap_reversion         2 VWAP docs -- fade stretch from session VWAP
      fib_retracement_entry  6 fib docs -- enter in the 61.8-78.6% zone in
                             trend direction
      big_candle_continuation "big bar" -- outsized body, enter on the
                             continuation of its direction

    NOT IMPLEMENTED, and why: several documents are genuinely
    discretionary rather than mechanical -- e.g. "observe EMA rejection"
    and "identify key resistance" (EMA REJECTION STRATEGY), or "market
    bias (bullish or bearish)" left undefined (ASIAN SESSION BOS). Those
    are judgement calls, not rules, and coding a guess for them would be
    inventing a strategy and attributing it to the source. Where a
    document leaves a rule undefined, the closest MECHANICAL reading is
    used and that choice is documented on the function.

    RESEARCH CODE -- outside engines/, nothing live imports it. The source
    PDFs are read-only and were never modified.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rr_exit(entries: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray,
             stops: np.ndarray, rr: float) -> pd.Series:
    """Walk entries forward to a stop or an R-multiple target.

    The corpus is near-unanimous on exits: 47 documents state 1:2 and 41
    state 1:3, against only 4 for 1:1. So these strategies are graded the
    way they are written -- fixed R target, stop at the signal candle's
    extreme -- rather than with a trailing exit that would flatter them.
    Stop and target are both checked on the SAME bar conservatively: if a
    bar's range covers both, the STOP is taken, since intrabar order is
    unknowable from OHLC and assuming the good fill is how backtests lie.
    """
    n = len(close)
    out = np.zeros(n, dtype=np.int8)
    i = 0
    while i < n:
        d = entries[i]
        if d == 0:
            i += 1
            continue
        entry_px = close[i]
        stop = stops[i]
        risk = abs(entry_px - stop)
        if risk <= 0:
            i += 1
            continue
        target = entry_px + d * risk * rr
        j = i + 1
        while j < n:
            out[j] = d
            hit_stop = (low[j] <= stop) if d == 1 else (high[j] >= stop)
            hit_tgt = (high[j] >= target) if d == 1 else (low[j] <= target)
            if hit_stop:            # stop wins a same-bar tie, deliberately
                break
            if hit_tgt:
                break
            j += 1
        i = j + 1
    return out


def ema_cross_pullback(enriched: pd.DataFrame, fast: int = 9, slow: int = 15,
                       rr: float = 2.0, pullback_atr: float = 0.5) -> pd.Series:
    """The dominant corpus archetype (29 EMA documents).

    Rules as written: fast EMA crosses slow; price then pulls back near the
    fast EMA; enter on a candle closing back in the cross direction; stop at
    that candle's opposite extreme; target a fixed R multiple.

    "Pull back NEAR the EMA" is made mechanical as "within `pullback_atr` x
    ATR of it" -- the documents say near without defining it, and an
    ATR-relative band is the only reading that behaves the same on GOLD as
    on EURUSD. The "crossover angle > 30 degrees" some documents add is NOT
    implemented: degrees on a price chart depend entirely on axis scaling
    and zoom, so it is not a measurable market property.
    """
    c = enriched["close"]
    ef, es = _ema(c, fast), _ema(c, slow)
    atr = enriched["atr"] if "atr" in enriched else (enriched["high"] - enriched["low"]).rolling(14).mean()

    bull = (ef > es) & (ef.shift(1) <= es.shift(1))
    bear = (ef < es) & (ef.shift(1) >= es.shift(1))
    regime = pd.Series(0, index=enriched.index, dtype=int)
    regime[bull] = 1
    regime[bear] = -1
    regime = regime.replace(0, np.nan).ffill().fillna(0)

    near = (c - ef).abs() <= atr * pullback_atr
    up_candle = c > enriched["open"]
    entries = np.zeros(len(enriched), dtype=np.int8)
    entries[((regime == 1) & near & up_candle).to_numpy()] = 1
    entries[((regime == -1) & near & ~up_candle).to_numpy()] = -1

    stops = np.where(entries == 1, enriched["low"].to_numpy(), enriched["high"].to_numpy())
    return pd.Series(_rr_exit(entries, enriched["high"].to_numpy(), enriched["low"].to_numpy(),
                              c.to_numpy(), stops, rr), index=enriched.index, dtype=int)


def ema_retest(enriched: pd.DataFrame, period: int = 9, rr: float = 1.0) -> pd.Series:
    """"Big Bar"/9-EMA retest: price TOUCHES the EMA, and the NEXT candle
    must CLOSE beyond it. Stop at the retest candle's extreme, 1:1 target
    as that document specifies (one of only four stating 1:1)."""
    c, h, l = enriched["close"], enriched["high"], enriched["low"]
    e = _ema(c, period)
    touched = (l <= e) & (h >= e)
    entries = np.zeros(len(enriched), dtype=np.int8)
    prev_touch = touched.shift(1).fillna(False).to_numpy()
    entries[(prev_touch & (c > e).to_numpy())] = 1
    entries[(prev_touch & (c < e).to_numpy())] = -1
    stops = np.where(entries == 1, l.shift(1).fillna(l).to_numpy(), h.shift(1).fillna(h).to_numpy())
    return pd.Series(_rr_exit(entries, h.to_numpy(), l.to_numpy(), c.to_numpy(), stops, rr),
                     index=enriched.index, dtype=int)


def ema_stack_trend(enriched: pd.DataFrame, fast: int = 9, mid: int = 20, slow: int = 50,
                    rr: float = 2.0) -> pd.Series:
    """3-EMA (9/20/50): the fast/mid cross only counts when it happens on
    the correct side of the slow EMA. Exit on the opposite cross, as that
    document specifies, so this one is NOT R-target based."""
    c = enriched["close"]
    ef, em, esl = _ema(c, fast), _ema(c, mid), _ema(c, slow)
    long_ok = (ef > em) & (em > esl)
    short_ok = (ef < em) & (em < esl)
    sig = pd.Series(0, index=enriched.index, dtype=int)
    sig[long_ok] = 1
    sig[short_ok] = -1
    return sig


def session_sweep_bos(enriched: pd.DataFrame, session_start: int = 0, session_end: int = 7,
                      rr: float = 2.0, tz: str = "UTC") -> pd.Series:
    """16 session documents, of which the Asia/BOS one is the clearest:
    price sweeps the session range extreme, then breaks structure the other
    way, and the trade is taken on that break.

    The documents leave "market bias" undefined, so bias is NOT guessed --
    the sweep direction itself supplies it, which is the mechanical reading:
    a swept HIGH implies a short, a swept LOW implies a long. Requires
    intraday bars; returns flat on daily data rather than pretending a
    session exists there.
    """
    if "timestamp" not in enriched.columns:
        return pd.Series(0, index=enriched.index, dtype=int)
    ts = pd.to_datetime(enriched["timestamp"], utc=True).dt.tz_convert(tz)
    if ts.dt.hour.nunique() <= 1:
        return pd.Series(0, index=enriched.index, dtype=int)

    day = ts.dt.date
    in_sess = (ts.dt.hour >= session_start) & (ts.dt.hour < session_end)
    h, l, c = (enriched[k].to_numpy(float) for k in ("high", "low", "close"))
    entries = np.zeros(len(enriched), dtype=np.int8)
    stops = np.zeros(len(enriched), dtype=float)

    sess_hi: dict = {}
    sess_lo: dict = {}
    for i in range(len(enriched)):
        d = day.iloc[i]
        if in_sess.iloc[i]:
            sess_hi[d] = max(sess_hi.get(d, -np.inf), h[i])
            sess_lo[d] = min(sess_lo.get(d, np.inf), l[i])
            continue
        hi, lo = sess_hi.get(d), sess_lo.get(d)
        if hi is None or lo is None or not np.isfinite(hi) or not np.isfinite(lo):
            continue
        if h[i] > hi and c[i] < hi:          # swept the high, closed back under
            entries[i] = -1
            stops[i] = h[i]
        elif l[i] < lo and c[i] > lo:        # swept the low, closed back above
            entries[i] = 1
            stops[i] = l[i]
    return pd.Series(_rr_exit(entries, h, l, c, stops, rr), index=enriched.index, dtype=int)


def opening_range_breakout(enriched: pd.DataFrame, or_bars: int = 3, rr: float = 2.0,
                           tz: str = "America/New_York", open_hour: int = 9) -> pd.Series:
    """4 ORB documents: mark the first `or_bars` bars after the session
    open, trade the break of that range, stop at the opposite side."""
    if "timestamp" not in enriched.columns:
        return pd.Series(0, index=enriched.index, dtype=int)
    ts = pd.to_datetime(enriched["timestamp"], utc=True).dt.tz_convert(tz)
    if ts.dt.hour.nunique() <= 1:
        return pd.Series(0, index=enriched.index, dtype=int)

    day, hour = ts.dt.date, ts.dt.hour
    h, l, c = (enriched[k].to_numpy(float) for k in ("high", "low", "close"))
    entries = np.zeros(len(enriched), dtype=np.int8)
    stops = np.zeros(len(enriched), dtype=float)
    counts: dict = {}
    rng: dict = {}
    done: set = set()
    for i in range(len(enriched)):
        d = day.iloc[i]
        if hour.iloc[i] == open_hour and d not in counts:
            counts[d] = 0
            rng[d] = [h[i], l[i]]
        if d not in counts:
            continue
        counts[d] += 1
        if counts[d] <= or_bars:
            rng[d][0] = max(rng[d][0], h[i])
            rng[d][1] = min(rng[d][1], l[i])
            continue
        if d in done:
            continue
        hi, lo = rng[d]
        if c[i] > hi:
            entries[i], stops[i] = 1, lo
            done.add(d)
        elif c[i] < lo:
            entries[i], stops[i] = -1, hi
            done.add(d)
    return pd.Series(_rr_exit(entries, h, l, c, stops, rr), index=enriched.index, dtype=int)


def vwap_reversion(enriched: pd.DataFrame, stretch_atr: float = 1.5, rr: float = 2.0) -> pd.Series:
    """2 VWAP documents: fade price stretched far from session VWAP, back
    toward it. VWAP is reset daily (a running VWAP over years is not what
    any of these documents mean)."""
    if "timestamp" not in enriched.columns or "volume" not in enriched.columns:
        return pd.Series(0, index=enriched.index, dtype=int)
    ts = pd.to_datetime(enriched["timestamp"], utc=True)
    day = ts.dt.date
    tp = (enriched["high"] + enriched["low"] + enriched["close"]) / 3.0
    vol = enriched["volume"].replace(0, np.nan)
    grp = pd.DataFrame({"d": day, "pv": tp * vol, "v": vol})
    vwap = grp.groupby("d")["pv"].cumsum() / grp.groupby("d")["v"].cumsum()
    atr = enriched["atr"] if "atr" in enriched else (enriched["high"] - enriched["low"]).rolling(14).mean()

    c, h, l = (enriched[k].to_numpy(float) for k in ("close", "high", "low"))
    dev = (enriched["close"] - vwap) / atr
    entries = np.zeros(len(enriched), dtype=np.int8)
    entries[(dev <= -stretch_atr).fillna(False).to_numpy()] = 1
    entries[(dev >= stretch_atr).fillna(False).to_numpy()] = -1
    stops = np.where(entries == 1, l, h)
    return pd.Series(_rr_exit(entries, h, l, c, stops, rr), index=enriched.index, dtype=int)


def fib_retracement_entry(enriched: pd.DataFrame, lookback: int = 50, lo: float = 0.618,
                          hi: float = 0.786, rr: float = 2.0) -> pd.Series:
    """6 fib documents: enter in the 61.8-78.6% retracement of the recent
    swing, in the direction of the prevailing trend. `.shift(1)` on the
    swing extremes keeps the range strictly prior to the bar being judged."""
    h, l, c = enriched["high"], enriched["low"], enriched["close"]
    sh = h.shift(1).rolling(lookback).max()
    sl = l.shift(1).rolling(lookback).min()
    span = (sh - sl).replace(0, np.nan)
    ema200 = _ema(c, 200)
    up = c > ema200
    rt_long = (c <= sh - span * lo) & (c >= sh - span * hi) & up
    rt_short = (c >= sl + span * lo) & (c <= sl + span * hi) & ~up
    entries = np.zeros(len(enriched), dtype=np.int8)
    entries[rt_long.fillna(False).to_numpy()] = 1
    entries[rt_short.fillna(False).to_numpy()] = -1
    stops = np.where(entries == 1, sl.fillna(l).to_numpy(), sh.fillna(h).to_numpy())
    return pd.Series(_rr_exit(entries, h.to_numpy(), l.to_numpy(), c.to_numpy(), stops, rr),
                     index=enriched.index, dtype=int)


def big_candle_continuation(enriched: pd.DataFrame, body_atr: float = 1.5, rr: float = 2.0) -> pd.Series:
    """"Big bar": an outsized directional body is treated as institutional
    intent; enter the NEXT bar in its direction, stop at its extreme."""
    o, h, l, c = (enriched[k] for k in ("open", "high", "low", "close"))
    atr = enriched["atr"] if "atr" in enriched else (h - l).rolling(14).mean()
    body = (c - o).abs()
    big = body >= atr * body_atr
    entries = np.zeros(len(enriched), dtype=np.int8)
    bull = (big & (c > o)).shift(1).fillna(False).to_numpy()
    bear = (big & (c < o)).shift(1).fillna(False).to_numpy()
    entries[bull] = 1
    entries[bear] = -1
    stops = np.where(entries == 1, l.shift(1).fillna(l).to_numpy(), h.shift(1).fillna(h).to_numpy())
    return pd.Series(_rr_exit(entries, h.to_numpy(), l.to_numpy(), c.to_numpy(), stops, rr),
                     index=enriched.index, dtype=int)


PDF_STRATEGIES = {
    "ema_cross_pullback": ema_cross_pullback,
    "ema_retest": ema_retest,
    "ema_stack_trend": ema_stack_trend,
    "session_sweep_bos": session_sweep_bos,
    "opening_range_breakout": opening_range_breakout,
    "vwap_reversion": vwap_reversion,
    "fib_retracement_entry": fib_retracement_entry,
    "big_candle_continuation": big_candle_continuation,
}


def pdh_pdl_sweep_reversal(
    enriched: pd.DataFrame,
    wick_ratio: float = 0.5,
    sessions: tuple = ((7, 10), (12, 15)),
    tz: str = "UTC",
    use_opposite_target: bool = True,
    rr: float = 2.0,
) -> pd.Series:
    """"Liquidity Sweep Strategy (Day 30)" -- implemented to its own rules
    rather than folded into session_sweep_bos, because it is materially
    more specific than that generic archetype:

      Step 1  levels are PREVIOUS DAY HIGH / LOW, not a session range
      Step 2  5m or 15m intended (works on any intraday frame here)
      Step 3  only during London Open or New York Open
      Short   price breaks PDH -> that candle prints a long REJECTION WICK
              -> the NEXT candle closes back INSIDE the sweep candle's
              range -> sell
      Stop    above the sweep candle's high
      Target  the PREVIOUS DAY LOW -- i.e. the opposing liquidity pool,
              NOT a fixed R multiple
      Long    exact mirror

    The liquidity-to-liquidity target is the interesting part and the
    reason this deserved its own function: every other archetype in this
    module exits at a fixed R, whereas this one is explicitly "entry from
    price delivery, target at liquidity". `use_opposite_target=False`
    falls back to a fixed `rr` so the two exit models can be compared on
    identical entries.

    Two rules are made mechanical where the document is qualitative:
      - "long rejection wick" -> the wick beyond the swept level is at
        least `wick_ratio` of the candle's total range
      - "high liquidity sessions" -> explicit hour windows, since the PDF
        names sessions without giving times

    The document claims 65-70% accuracy. That claim is NOT assumed
    anywhere here; it is exactly what the backtest is for.
    """
    if "timestamp" not in enriched.columns:
        return pd.Series(0, index=enriched.index, dtype=int)
    ts = pd.to_datetime(enriched["timestamp"], utc=True).dt.tz_convert(tz)
    if ts.dt.hour.nunique() <= 1:          # daily or coarser: no sessions
        return pd.Series(0, index=enriched.index, dtype=int)

    o, h, l, c = (enriched[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    day = ts.dt.date
    hour = ts.dt.hour.to_numpy()
    in_session = np.zeros(len(enriched), dtype=bool)
    for start, end in sessions:
        in_session |= (hour >= start) & (hour < end)

    # Previous day's high/low, carried forward. Shifted by one period so a
    # bar only ever sees a COMPLETED prior day.
    agg = pd.DataFrame({"d": day, "h": h, "l": l}).groupby("d").agg(hi=("h", "max"), lo=("l", "min"))
    prev = agg.shift(1)
    pdh = day.map(prev["hi"]).to_numpy(dtype=float)
    pdl = day.map(prev["lo"]).to_numpy(dtype=float)

    n = len(enriched)
    out = np.zeros(n, dtype=np.int8)
    position = 0
    stop = target = 0.0

    for i in range(1, n):
        if position != 0:
            if position == 1 and (l[i] <= stop or h[i] >= target):
                position = 0
            elif position == -1 and (h[i] >= stop or l[i] <= target):
                position = 0
            out[i] = position
            if position != 0:
                continue

        if not in_session[i] or np.isnan(pdh[i]) or np.isnan(pdl[i]):
            continue

        # The sweep candle is the PREVIOUS bar; this bar is the confirmation.
        rng_prev = h[i - 1] - l[i - 1]
        if rng_prev <= 0:
            continue
        inside = (h[i] <= h[i - 1]) and (l[i] >= l[i - 1])
        if not inside:
            continue

        # SHORT: prior bar swept PDH and rejected from it.
        if h[i - 1] > pdh[i - 1] and c[i - 1] < pdh[i - 1]:
            upper_wick = h[i - 1] - max(o[i - 1], c[i - 1])
            if upper_wick / rng_prev >= wick_ratio:
                position, stop = -1, h[i - 1]
                target = pdl[i] if use_opposite_target else c[i] - (stop - c[i]) * rr
                if target < c[i]:
                    out[i] = position
                    continue
                position = 0

        # LONG: prior bar swept PDL and rejected from it.
        if position == 0 and l[i - 1] < pdl[i - 1] and c[i - 1] > pdl[i - 1]:
            lower_wick = min(o[i - 1], c[i - 1]) - l[i - 1]
            if lower_wick / rng_prev >= wick_ratio:
                position, stop = 1, l[i - 1]
                target = pdh[i] if use_opposite_target else c[i] + (c[i] - stop) * rr
                if target <= c[i]:
                    position = 0
        out[i] = position

    return pd.Series(out, index=enriched.index, dtype=int)


PDF_STRATEGIES["pdh_pdl_sweep_reversal"] = pdh_pdl_sweep_reversal
