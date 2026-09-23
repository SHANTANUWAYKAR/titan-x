"""
Module: orb_setup.py
Description: 15-minute Opening Range Breakout with VWAP and volume-profile
    context, built as a testable setup rather than a chart annotation.

    WHY THIS ONE IS WORTH BUILDING WHEN THE OTHERS WERE NOT. Every signal family
    tested in this audit collapsed into the same thing: 16 "informative"
    indicators reduced to two redundant groups plus directional beta, 27
    parameter variants measured 0.974 mean correlation, five learners spanning
    linear to 600-tree forests landed within 0.019 AUC of each other. They were
    all transforms of one price series.

    ORB is not. Its levels come from WHEN, not from a moving average: the high
    and low of the session's first 15 minutes. Session structure is information
    the EMA/MACD/ADX/RSI composite has no access to, which is the first time
    that has been true in this project.

    WHAT IS IMPLEMENTED, FROM THE SOURCE MATERIAL
      ORB levels        high/low of the session's opening 15 minutes
      VWAP filter       session-anchored; above VWAP for longs, below for shorts
      Momentum entry    break of the ORB level with the bar closing beyond it
      Retest entry      break, then return to the level and hold it
                        (declared in ORBConfig from the start but NOT wired
                        into extract_orb_signals until 2026-09-22 -- every
                        ORB result dated before that is the MOMENTUM model,
                        whatever entry_model was set to)
      Range veto        no trade while price is still inside the ORB band
      Volume profile    POC / VAH / VAL over the session, as CONTEXT features

    WHAT IS NOT, AND WHY
      Bid/ask DELTA and the LIQUIDITY HEATMAP cannot be computed from OHLCV
      bars. Delta needs the trade side of every print; a heatmap needs resting
      L2 depth. Neither exists in this data at any timeframe, and approximating
      them from bar volume would invent a signal rather than measure one. They
      are omitted rather than faked.

    SESSION HANDLING. US equities carry 13:00-20:00 UTC bars, which is the
    regular NY session, so the opening range is unambiguous. A 24-hour market
    (crypto, spot FX) has no natural open, so the NY session start is imposed
    and the result should be read as "does the NY open matter for this
    instrument" rather than as a true opening range.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

COST_ROUND_TRIP = 0.003


@dataclass
class ORBConfig:
    # 13:30 UTC is the NY equity open; 13:30-13:45 is the opening 15 minutes.
    session_start_utc: str = "13:30"
    session_end_utc: str = "20:00"
    orb_minutes: int = 15

    entry_model: str = "momentum"      # "momentum" | "retest" | "both"
    require_vwap: bool = True          # above VWAP for longs, below for shorts
    require_close_beyond: bool = True  # the break bar must CLOSE past the level

    atr_mult: float = 1.0
    reward_risk: float = 2.0
    horizon_bars: int = 16             # ~4h on 15m bars; the session's remainder
    risk_pct: float = 0.01
    max_leverage: float = 3.0

    # One trade per side per day. Without this a choppy day around the level
    # produces a dozen entries and the result becomes a measure of chop, not of
    # the setup.
    one_trade_per_side: bool = True

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def session_vwap(df: pd.DataFrame, day_key: pd.Series) -> pd.Series:
    """VWAP anchored to each session, not a rolling window.

    Anchored because that is what the source material means by VWAP and what a
    trader sees on the chart: cumulative typical price x volume since the open,
    reset daily. A rolling VWAP would be a different indicator wearing the name.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = tp * df["volume"].fillna(0)
    cum_pv = pv.groupby(day_key).cumsum()
    cum_v = df["volume"].fillna(0).groupby(day_key).cumsum()
    return cum_pv / cum_v.replace(0, np.nan)


def volume_profile(day_df: pd.DataFrame, bins: int = 24) -> tuple[float, float, float]:
    """(POC, VAH, VAL) for one session, from volume-by-price.

    An approximation, stated plainly: real volume profile distributes each
    trade at its own print price, while OHLCV bars only say how much traded
    somewhere between high and low. Here each bar's volume is assigned to its
    typical price. That is coarse but unbiased -- it does not systematically
    push the POC up or down -- and it is the most the data supports.

    The value area is the smallest contiguous band around the POC holding ~70%
    of volume, expanded a bin at a time toward whichever side holds more.
    """
    if day_df.empty or day_df["volume"].fillna(0).sum() <= 0:
        return (np.nan, np.nan, np.nan)
    tp = ((day_df["high"] + day_df["low"] + day_df["close"]) / 3.0).to_numpy(float)
    vol = day_df["volume"].fillna(0).to_numpy(float)
    lo, hi = float(np.nanmin(day_df["low"])), float(np.nanmax(day_df["high"]))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return (np.nan, np.nan, np.nan)
    edges = np.linspace(lo, hi, bins + 1)
    idx = np.clip(np.digitize(tp, edges) - 1, 0, bins - 1)
    hist = np.zeros(bins)
    np.add.at(hist, idx, vol)
    if hist.sum() <= 0:
        return (np.nan, np.nan, np.nan)
    centers = (edges[:-1] + edges[1:]) / 2.0
    poc_i = int(np.argmax(hist))
    target = 0.70 * hist.sum()
    lo_i = hi_i = poc_i
    acc = hist[poc_i]
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        down = hist[lo_i - 1] if lo_i > 0 else -1.0
        up = hist[hi_i + 1] if hi_i < bins - 1 else -1.0
        if up >= down:
            hi_i += 1
            acc += max(up, 0.0)
        else:
            lo_i -= 1
            acc += max(down, 0.0)
    return (float(centers[poc_i]), float(centers[hi_i]), float(centers[lo_i]))


def build_session_frame(df: pd.DataFrame, cfg: ORBConfig) -> Optional[pd.DataFrame]:
    """Attach session id, ORB levels, VWAP and volume-profile context.

    Every column added here is causal: ORB levels are fixed once the opening
    window closes, VWAP is cumulative-to-date, and the volume profile used on a
    given day is the PREVIOUS session's, because today's is not knowable while
    today is still trading.
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if "timestamp" in d.columns:
        ts = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(d.index, utc=True, errors="coerce")
    d = d.loc[ts.notna()].copy()
    ts = ts[ts.notna()]
    d.index = pd.DatetimeIndex(ts)
    d = d.sort_index()
    if "volume" not in d.columns:
        return None

    sh, sm = (int(x) for x in cfg.session_start_utc.split(":"))
    eh, em = (int(x) for x in cfg.session_end_utc.split(":"))
    minute_of_day = d.index.hour * 60 + d.index.minute
    start_m, end_m = sh * 60 + sm, eh * 60 + em
    in_session = (minute_of_day >= start_m) & (minute_of_day < end_m)
    d = d.loc[in_session].copy()
    if d.empty:
        return None
    minute_of_day = d.index.hour * 60 + d.index.minute

    d["_day"] = d.index.normalize()
    d["_min_since_open"] = minute_of_day - start_m
    in_orb = d["_min_since_open"] < cfg.orb_minutes

    orb_hi = d.loc[in_orb].groupby("_day")["high"].max()
    orb_lo = d.loc[in_orb].groupby("_day")["low"].min()
    d["_orb_high"] = d["_day"].map(orb_hi)
    d["_orb_low"] = d["_day"].map(orb_lo)
    # Only bars AFTER the opening window can trade it.
    d["_tradeable"] = ~in_orb & d["_orb_high"].notna() & d["_orb_low"].notna()

    d["_vwap"] = session_vwap(d, d["_day"])

    # Previous session's profile: today's is unknowable intraday.
    poc, vah, val = {}, {}, {}
    days = list(d["_day"].unique())
    for i, day in enumerate(days):
        if i == 0:
            poc[day] = vah[day] = val[day] = np.nan
            continue
        prev = d[d["_day"] == days[i - 1]]
        p, h, l = volume_profile(prev)
        poc[day], vah[day], val[day] = p, h, l
    d["_prev_poc"] = d["_day"].map(poc)
    d["_prev_vah"] = d["_day"].map(vah)
    d["_prev_val"] = d["_day"].map(val)

    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    d["_atr"] = tr.rolling(14).mean()
    return d


def extract_orb_signals(d: pd.DataFrame, cfg: ORBConfig) -> pd.DataFrame:
    """Every ORB entry with its triple-barrier outcome.

    Entry is the NEXT bar's open. The stop is checked before the target on each
    bar, so a bar containing both is scored a loss -- OHLC cannot order two
    touches inside one bar.
    """
    if d is None or d.empty:
        return pd.DataFrame()
    o, h, l, c = (d["open"].to_numpy(float), d["high"].to_numpy(float),
                  d["low"].to_numpy(float), d["close"].to_numpy(float))
    atr = d["_atr"].to_numpy(float)
    vwap = d["_vwap"].to_numpy(float)
    ohi, olo = d["_orb_high"].to_numpy(float), d["_orb_low"].to_numpy(float)
    trad = d["_tradeable"].to_numpy(bool)
    day = d["_day"].to_numpy()
    idx = d.index.to_numpy()
    n = len(d)

    model = (cfg.entry_model or "momentum").lower()
    if model not in ("momentum", "retest", "both"):
        raise ValueError(f"entry_model must be momentum|retest|both, got {cfg.entry_model!r}")

    rows = []
    taken: set[tuple[Any, int]] = set()
    # A break must be SEEN on an earlier bar before a retest of it can be taken.
    # Without this the break bar itself qualifies as its own retest -- its low
    # is usually still under the level it just closed above -- which would turn
    # the retest model back into the momentum model without any error.
    seen_break: set[tuple[Any, int]] = set()
    for i in range(n - 1):
        if not trad[i] or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        up = np.isfinite(ohi[i]) and c[i] > ohi[i]
        dn = np.isfinite(olo[i]) and c[i] < olo[i]
        if cfg.require_close_beyond:
            broke_up, broke_dn = up, dn
        else:
            broke_up = np.isfinite(ohi[i]) and h[i] > ohi[i]
            broke_dn = np.isfinite(olo[i]) and l[i] < olo[i]

        # A retest: price comes BACK to the level it broke and closes holding it.
        # Long -- the bar's low reaches down to the ORB high, the close stays
        # above it. Short is the mirror. This is the entry the source material
        # insists on: "just because a stock breaks out ... is not the entry".
        retest_up = (np.isfinite(ohi[i]) and (day[i], 1) in seen_break
                     and l[i] <= ohi[i] and c[i] > ohi[i])
        retest_dn = (np.isfinite(olo[i]) and (day[i], -1) in seen_break
                     and h[i] >= olo[i] and c[i] < olo[i])

        if model == "momentum":
            trig_up, trig_dn = broke_up, broke_dn
        elif model == "retest":
            trig_up, trig_dn = retest_up, retest_dn
        else:
            trig_up, trig_dn = (broke_up or retest_up), (broke_dn or retest_dn)

        # Record the break AFTER deciding, so this bar cannot arm and fire on
        # itself. Recorded even when the trade is vetoed below: the break
        # happened on the chart regardless of whether we were allowed to take it.
        if broke_up:
            seen_break.add((day[i], 1))
        if broke_dn:
            seen_break.add((day[i], -1))

        if not (trig_up or trig_dn):
            continue        # inside the range, or waiting for the retest
        d_ = 1 if trig_up else -1
        if cfg.require_vwap and np.isfinite(vwap[i]):
            if d_ == 1 and c[i] < vwap[i]:
                continue
            if d_ == -1 and c[i] > vwap[i]:
                continue
        if cfg.one_trade_per_side:
            key = (day[i], d_)
            if key in taken:
                continue
            taken.add(key)

        entry = o[i + 1]
        if not np.isfinite(entry) or entry <= 0:
            continue
        stop_frac = (cfg.atr_mult * atr[i]) / entry
        if not np.isfinite(stop_frac) or stop_frac <= 0:
            continue
        stop = entry - d_ * cfg.atr_mult * atr[i]
        target = entry + d_ * cfg.reward_risk * cfg.atr_mult * atr[i]
        win = None
        for j in range(i + 1, min(i + 1 + cfg.horizon_bars, n)):
            if (d_ == 1 and l[j] <= stop) or (d_ == -1 and h[j] >= stop):
                win = 0
                break
            if (d_ == 1 and h[j] >= target) or (d_ == -1 and l[j] <= target):
                win = 1
                break
        if win is None:
            continue
        rows.append({
            "_ts": idx[i], "_dir": float(d_), "_win": win,
            "_stop_frac": stop_frac,
            "_entry_model": "retest" if (d_ == 1 and retest_up) or (d_ == -1 and retest_dn) else "momentum",
            "_notional": float(min(cfg.risk_pct / stop_frac, cfg.max_leverage)),
            "_min_since_open": float(d["_min_since_open"].iloc[i]),
            "orb_width_atr": float((ohi[i] - olo[i]) / atr[i]) if np.isfinite(ohi[i]) else np.nan,
            "dist_vwap_atr": float((c[i] - vwap[i]) / atr[i]) if np.isfinite(vwap[i]) else np.nan,
            "dist_poc_atr": float((c[i] - d["_prev_poc"].iloc[i]) / atr[i])
            if np.isfinite(d["_prev_poc"].iloc[i]) else np.nan,
            "in_prev_value_area": float(
                d["_prev_val"].iloc[i] <= c[i] <= d["_prev_vah"].iloc[i])
            if np.isfinite(d["_prev_val"].iloc[i]) else np.nan,
        })
    return pd.DataFrame(rows)


def orb_economics(df: pd.DataFrame, cfg: ORBConfig) -> dict[str, Any]:
    if df.empty:
        return {"trades": 0}
    y = df["_win"].to_numpy(float)
    wr = float(y.mean())
    gross_R = wr * cfg.reward_risk - (1 - wr)
    gross = gross_R * cfg.risk_pct * 100
    cost = float((COST_ROUND_TRIP * df["_notional"]).mean()) * 100
    return {
        "trades": int(len(df)), "win_rate": wr, "gross_R": gross_R,
        "gross_pct_per_trade": gross, "cost_pct_per_trade": cost,
        "net_pct_per_trade": gross - cost,
        "breakeven_win_rate": 1.0 / (1.0 + cfg.reward_risk),
        "mean_notional": float(df["_notional"].mean()),
    }
