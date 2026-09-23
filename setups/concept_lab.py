"""
Module: concept_lab.py
Description: Every concept from the retail-education corpus, implemented once
    and measured through ONE evaluator, so the numbers are comparable.

    WHY A SHARED EVALUATOR. The reason "does SMC work?" has no answer in public
    is that every test uses a different exit, a different cost assumption and a
    different sample. Comparing those numbers is meaningless. Here every
    concept produces the same thing -- a direction at a bar -- and is scored by
    the same triple barrier, the same costs and the same null. The ranking is
    then about the concepts and nothing else.

    WHAT THE PUBLISHED EVIDENCE SAYS, so the priors are on the record before
    the measurement (sources in reports/CONCEPT_LAB.md):

      Support/resistance      The STRONGEST academic backing of anything here.
                              Osler (J. Finance 2003; FRBNY 2000) showed
                              take-profit orders cluster AT round numbers and
                              stop-loss orders cluster JUST BEYOND them, which
                              predicts both reversal at a level and
                              acceleration through it. A microstructure
                              mechanism, not a chart-reading claim.
      Liquidity sweep         Reported as the most robust SMC edge, but the
                              sources are practitioner blogs, not journals.
      Order blocks            Weak: t = +1.22 on SPY in one published backtest,
                              below the conventional |t| > 2. 648 ICT backtests
                              reportedly failed to beat buy-and-hold.
      Fair value gaps         "Fill ~70% of the time" -- a fill RATE is not an
                              edge; it says nothing about the payoff when it
                              does not fill. Tested here for expectancy.
      Candlestick patterns    Academic results mixed; most patterns' mean
                              returns are not distinguishable from zero.

    EVERY CONCEPT IS CAUSAL. A concept may only look at bars up to and
    including i, and entry is always the open of i+1. The negative-control
    test in tests/unit/test_concept_lab.py asserts that truncating the data
    cannot change an earlier signal.

    NOT INCLUDED, DELIBERATELY. Anything needing order flow (bid/ask delta,
    L2 depth, real liquidity heatmaps) cannot be computed from OHLCV and is
    omitted rather than approximated -- an approximation would invent the
    signal it claims to measure.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# E26's own assumption: 0.1% commission + 0.05% slippage per side.
COST_ROUND_TRIP = 0.003


@dataclass
class LabConfig:
    atr_mult: float = 1.0          # stop distance, in ATR
    reward_risk: float = 2.0       # target = reward_risk x stop
    horizon_bars: int = 20         # time barrier
    risk_pct: float = 0.01
    max_leverage: float = 3.0
    cost_round_trip: float = COST_ROUND_TRIP
    # A concept firing on < this many bars cannot be judged. Reported as
    # "insufficient", never as a result.
    min_trades: int = 100
    swing_lookback: int = 5        # bars each side for a confirmed swing
    level_tolerance_atr: float = 0.25  # "at a level" means within this
    momentum_mult: float = 2.0     # a momentum candle is >= this x recent bodies
    # Default TRUE. Excluding unresolved trades is how the wider-stop lead
    # died on this book once already; making the honest treatment opt-out
    # rather than opt-in means the flattering number is never the default.
    mark_unresolved_to_market: bool = True
    engulfing_level_tolerance_atr: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


# ---------------------------------------------------------------------------
# shared primitives -- every concept is built from these, so a bug in one
# place is a bug everywhere and shows up in the negative-control test
# ---------------------------------------------------------------------------

def _swings(h: np.ndarray, l: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Confirmed swing highs/lows.

    A swing at i is only CONFIRMED once k bars have printed after it, so the
    arrays are shifted forward by k. Marking it at i would let a strategy see
    a pivot k bars before the market could.
    """
    n = len(h)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for i in range(k, n - k):
        w_h, w_l = h[i - k:i + k + 1], l[i - k:i + k + 1]
        if h[i] == w_h.max() and (w_h.argmax() == k):
            sh[i + k] = True          # known only at i+k
        if l[i] == w_l.min() and (w_l.argmin() == k):
            sl[i + k] = True
    return sh, sl


def _atr(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean().to_numpy(float)


def _recent_level(h: np.ndarray, l: np.ndarray, sh: np.ndarray, sl: np.ndarray,
                  i: int, lookback: int = 60) -> tuple[float, float]:
    """(nearest resistance above, nearest support below) from CONFIRMED swings."""
    lo = max(0, i - lookback)
    res = [h[j] for j in range(lo, i + 1) if sh[j] and h[j] > 0]
    sup = [l[j] for j in range(lo, i + 1) if sl[j] and l[j] > 0]
    return (min(res) if res else np.nan, max(sup) if sup else np.nan)


# ---------------------------------------------------------------------------
# the concepts. each returns an int array: +1 long, -1 short, 0 nothing.
# ---------------------------------------------------------------------------

def concept_sr_bounce(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """Price reaches a confirmed swing level and closes back away from it.

    The concept with the strongest published mechanism behind it (Osler:
    take-profit orders cluster at levels). Long when price dips to support and
    closes above it; short at resistance.
    """
    h, l, c = (df["high"].to_numpy(float), df["low"].to_numpy(float),
               df["close"].to_numpy(float))
    atr = _atr(df)
    sh, sl = _swings(h, l, cfg.swing_lookback)
    out = np.zeros(len(df), dtype=int)
    for i in range(cfg.swing_lookback, len(df)):
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        res, sup = _recent_level(h, l, sh, sl, i)
        tol = cfg.level_tolerance_atr * atr[i]
        if np.isfinite(sup) and (l[i] <= sup + tol) and c[i] > sup:
            out[i] = 1
        elif np.isfinite(res) and (h[i] >= res - tol) and c[i] < res:
            out[i] = -1
    return out


def concept_round_number(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """Osler's mechanism directly: reaction at a ROUND number.

    Tests the microstructure claim without any chart reading at all. The level
    is arithmetic -- the nearest round increment scaled to the instrument --
    so this is the cleanest available test of order clustering.
    """
    h, l, c = (df["high"].to_numpy(float), df["low"].to_numpy(float),
               df["close"].to_numpy(float))
    atr = _atr(df)
    out = np.zeros(len(df), dtype=int)
    for i in range(1, len(df)):
        if not np.isfinite(atr[i]) or atr[i] <= 0 or c[i] <= 0:
            continue
        # round increment ~1% of price, snapped to a power of ten
        step = 10.0 ** np.floor(np.log10(max(c[i], 1e-9) * 0.01))
        if step <= 0:
            continue
        tol = cfg.level_tolerance_atr * atr[i]
        lo_round = np.floor(l[i] / step) * step
        hi_round = np.ceil(h[i] / step) * step
        if (l[i] - lo_round) <= tol and c[i] > lo_round:
            out[i] = 1
        elif (hi_round - h[i]) <= tol and c[i] < hi_round:
            out[i] = -1
    return out


def concept_liquidity_sweep(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """Wick through a confirmed swing, close back inside.

    Reported as the most robust SMC idea. Long when the bar takes out a swing
    low and closes back above it -- stops triggered, then rejected.
    """
    h, l, c = (df["high"].to_numpy(float), df["low"].to_numpy(float),
               df["close"].to_numpy(float))
    atr = _atr(df)
    sh, sl = _swings(h, l, cfg.swing_lookback)
    out = np.zeros(len(df), dtype=int)
    for i in range(cfg.swing_lookback, len(df)):
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        res, sup = _recent_level(h, l, sh, sl, i)
        if np.isfinite(sup) and l[i] < sup and c[i] > sup:
            out[i] = 1
        elif np.isfinite(res) and h[i] > res and c[i] < res:
            out[i] = -1
    return out


def concept_failure_test(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """Break beyond a swing level on the PRIOR bar, close back inside on this one.

    The two-bar version of the sweep -- the retail 'failure test'. Separated
    from the sweep on purpose: if the two score differently, the difference is
    whether the trap needs a full bar to spring.
    """
    h, l, c = (df["high"].to_numpy(float), df["low"].to_numpy(float),
               df["close"].to_numpy(float))
    sh, sl = _swings(h, l, cfg.swing_lookback)
    out = np.zeros(len(df), dtype=int)
    for i in range(cfg.swing_lookback + 1, len(df)):
        res, sup = _recent_level(h, l, sh, sl, i - 1)
        if np.isfinite(sup) and c[i - 1] < sup and c[i] > sup:
            out[i] = 1
        elif np.isfinite(res) and c[i - 1] > res and c[i] < res:
            out[i] = -1
    return out


def concept_fvg_fill(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """Price returns into a fair value gap left by a momentum candle.

    A 3-bar gap is recorded, then traded when price comes back to it. The
    "fills 70% of the time" claim is about the FILL; this measures what the
    trade is worth, which is a different question.
    """
    o, h, l, c = (df["open"].to_numpy(float), df["high"].to_numpy(float),
                  df["low"].to_numpy(float), df["close"].to_numpy(float))
    body = np.abs(c - o)
    avg_body = pd.Series(body).rolling(3, min_periods=3).mean().shift(1).to_numpy(float)
    out = np.zeros(len(df), dtype=int)
    gaps: list[tuple[float, float, int]] = []   # (lo, hi, direction)
    for i in range(2, len(df)):
        # a gap is only knowable at bar i (needs bars i-2, i-1, i)
        if np.isfinite(avg_body[i - 1]) and body[i - 1] >= cfg.momentum_mult * avg_body[i - 1]:
            if l[i] > h[i - 2]:
                gaps.append((h[i - 2], l[i], 1))
            elif h[i] < l[i - 2]:
                gaps.append((h[i], l[i - 2], -1))
        for g_lo, g_hi, d in gaps[-40:]:
            if d == 1 and l[i] <= g_hi and c[i] > g_lo:
                out[i] = 1
                break
            if d == -1 and h[i] >= g_lo and c[i] < g_hi:
                out[i] = -1
                break
    return out


def concept_engulfing_at_level(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """Engulfing candle, but ONLY when it happens at a confirmed level.

    Pairs with `concept_engulfing_anywhere` to test the corpus's most repeated
    claim: "a pattern in the middle of nowhere is noise". If the claim is true
    these two must separate.
    """
    return _engulfing(df, cfg, require_level=True)


def concept_engulfing_anywhere(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """The same engulfing pattern with no location filter -- the control."""
    return _engulfing(df, cfg, require_level=False)


def _engulfing(df: pd.DataFrame, cfg: LabConfig, require_level: bool) -> np.ndarray:
    o, h, l, c = (df["open"].to_numpy(float), df["high"].to_numpy(float),
                  df["low"].to_numpy(float), df["close"].to_numpy(float))
    atr = _atr(df)
    sh, sl = _swings(h, l, cfg.swing_lookback)
    out = np.zeros(len(df), dtype=int)
    for i in range(cfg.swing_lookback + 1, len(df)):
        bull = c[i] > o[i] and c[i - 1] < o[i - 1] and c[i] >= o[i - 1] and o[i] <= c[i - 1]
        bear = c[i] < o[i] and c[i - 1] > o[i - 1] and c[i] <= o[i - 1] and o[i] >= c[i - 1]
        if not (bull or bear):
            continue
        if not require_level:
            out[i] = 1 if bull else -1
            continue
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        res, sup = _recent_level(h, l, sh, sl, i)
        # Widened from the generic tolerance: requiring the wick within
        # 0.25 ATR of a swing produced < 100 firings per asset, i.e. no
        # sample to compare the control against. The band below is still a
        # LOCATION filter -- the whole point of the control -- just one loose
        # enough to be measurable.
        tol = cfg.engulfing_level_tolerance_atr * atr[i]
        if bull and np.isfinite(sup) and abs(l[i] - sup) <= tol:
            out[i] = 1
        elif bear and np.isfinite(res) and abs(h[i] - res) <= tol:
            out[i] = -1
    return out


def concept_fib_zone(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """Pullback into the 38.2-61.8% zone of the last confirmed swing leg."""
    h, l, c = (df["high"].to_numpy(float), df["low"].to_numpy(float),
               df["close"].to_numpy(float))
    sh, sl = _swings(h, l, cfg.swing_lookback)
    out = np.zeros(len(df), dtype=int)
    last_hi = last_lo = np.nan
    hi_at = lo_at = -1
    for i in range(len(df)):
        if sh[i]:
            last_hi, hi_at = h[i - cfg.swing_lookback], i
        if sl[i]:
            last_lo, lo_at = l[i - cfg.swing_lookback], i
        if not (np.isfinite(last_hi) and np.isfinite(last_lo)) or last_hi <= last_lo:
            continue
        rng = last_hi - last_lo
        if lo_at > hi_at:                      # down leg -> look for shorts
            a, b = last_hi - 0.618 * rng, last_hi - 0.382 * rng
            if a <= c[i] <= b:
                out[i] = -1
        else:                                  # up leg -> look for longs
            a, b = last_lo + 0.382 * rng, last_lo + 0.618 * rng
            if a <= c[i] <= b:
                out[i] = 1
    return out


def concept_momentum_breakout(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """Momentum candle closing beyond a confirmed swing -- the 'liquidity run'."""
    o, h, l, c = (df["open"].to_numpy(float), df["high"].to_numpy(float),
                  df["low"].to_numpy(float), df["close"].to_numpy(float))
    body = np.abs(c - o)
    avg_body = pd.Series(body).rolling(3, min_periods=3).mean().shift(1).to_numpy(float)
    sh, sl = _swings(h, l, cfg.swing_lookback)
    out = np.zeros(len(df), dtype=int)
    for i in range(cfg.swing_lookback, len(df)):
        if not np.isfinite(avg_body[i]) or body[i] < cfg.momentum_mult * avg_body[i]:
            continue
        res, sup = _recent_level(h, l, sh, sl, i)
        if np.isfinite(res) and c[i] > res:
            out[i] = 1
        elif np.isfinite(sup) and c[i] < sup:
            out[i] = -1
    return out


def concept_trend_pullback(df: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    """Pullback to the 20 EMA inside a 200 EMA trend. The classic baseline."""
    c = df["close"]
    e20, e200 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=200, adjust=False).mean()
    cv, e20v, e200v = c.to_numpy(float), e20.to_numpy(float), e200.to_numpy(float)
    l, h = df["low"].to_numpy(float), df["high"].to_numpy(float)
    out = np.zeros(len(df), dtype=int)
    for i in range(200, len(df)):
        if cv[i] > e200v[i] and l[i] <= e20v[i] and cv[i] > e20v[i]:
            out[i] = 1
        elif cv[i] < e200v[i] and h[i] >= e20v[i] and cv[i] < e20v[i]:
            out[i] = -1
    return out


CONCEPTS: dict[str, Callable[[pd.DataFrame, LabConfig], np.ndarray]] = {
    "sr_bounce": concept_sr_bounce,
    "round_number": concept_round_number,
    "liquidity_sweep": concept_liquidity_sweep,
    "failure_test": concept_failure_test,
    "fvg_fill": concept_fvg_fill,
    "engulfing_at_level": concept_engulfing_at_level,
    "engulfing_anywhere": concept_engulfing_anywhere,
    "fib_zone": concept_fib_zone,
    "momentum_breakout": concept_momentum_breakout,
    "trend_pullback": concept_trend_pullback,
}


# ---------------------------------------------------------------------------
# one evaluator for all of them
# ---------------------------------------------------------------------------

@dataclass
class ConceptResult:
    name: str
    trades: int
    win_rate: float
    gross_r: float
    cost_r: float
    net_r: float
    breakeven_cost_bps: float
    net_pct_per_trade: float
    sd_r: float
    t_stat: float
    years_positive: int
    years_total: int
    unresolved_frac: float = 0.0
    by_year: dict[int, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["by_year"] = {str(k): round(v, 5) for k, v in self.by_year.items()}
        return d


def evaluate(df: pd.DataFrame, signals: np.ndarray, cfg: LabConfig,
             name: str = "") -> Optional[ConceptResult]:
    """Triple-barrier outcome for every firing, with costs converted into R.

    Entry is the NEXT bar's open -- the signal is only knowable once bar i
    closes. The stop is checked BEFORE the target on every bar, so a bar
    containing both is a LOSS: OHLC cannot order two touches inside one bar,
    and assuming the favourable order is how backtests flatter themselves.
    """
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = _atr(df)
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce") \
        if "timestamp" in df.columns else pd.to_datetime(df.index, utc=True, errors="coerce")
    years = pd.Series(ts).dt.year.to_numpy()

    rows: list[tuple[int, float, float]] = []   # (year, r_net, stop_frac)
    # UNRESOLVED TRADES ARE EXCLUDED FROM THE WIN RATE, and that exclusion is
    # how the "wider stops" lead died once already on this book -- it looked
    # net-positive until 65% of its trades turned out never to resolve. A wide
    # stop makes losers take LONGER to hit, so they time out and vanish while
    # winners still reach the target: survivorship bias that looks like edge.
    # Counted and reported on every row so it can never hide again.
    fired = unresolved = 0
    n = len(df)
    for i in range(n - 1):
        d = int(signals[i])
        if d == 0 or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        fired += 1
        entry = o[i + 1]
        if not np.isfinite(entry) or entry <= 0:
            continue
        dist = cfg.atr_mult * atr[i]
        stop_frac = dist / entry
        if not np.isfinite(stop_frac) or stop_frac <= 0:
            continue
        stop = entry - d * dist
        target = entry + d * cfg.reward_risk * dist
        r = None
        for j in range(i + 1, min(i + 1 + cfg.horizon_bars, n)):
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                r = -1.0
                break
            if (d == 1 and h[j] >= target) or (d == -1 and l[j] <= target):
                r = cfg.reward_risk
                break
        if r is None:
            unresolved += 1
            if cfg.mark_unresolved_to_market:
                # The honest treatment. A trade that never touched either
                # barrier did not evaporate -- a real trader closes it at the
                # time limit and books whatever it is worth. Excluding it
                # instead removes exactly the trades a WIDE stop lets run
                # (losers that had not yet reached the stop), which is
                # survivorship bias pointing the same way as the result.
                j = min(i + cfg.horizon_bars, n - 1)
                r = float(d * (c[j] - entry) / dist)
            else:
                continue
        # the leverage cap scales BOTH the realised R and the cost paid
        want = cfg.risk_pct / stop_frac
        k = min(want, cfg.max_leverage) / want if want > 0 else 1.0
        cost_r = cfg.cost_round_trip / stop_frac
        rows.append((int(years[i]) if np.isfinite(years[i]) else 0,
                     k * (r - cost_r), stop_frac))
    if len(rows) < cfg.min_trades:
        return None

    yr = np.array([x[0] for x in rows])
    net = np.array([x[1] for x in rows], dtype=float)
    sfr = np.array([x[2] for x in rows], dtype=float)
    want = cfg.risk_pct / sfr
    k = np.minimum(want, cfg.max_leverage) / want
    gross = net + k * (cfg.cost_round_trip / sfr)
    cost = k * (cfg.cost_round_trip / sfr)
    sd = float(net.std(ddof=1)) if len(net) > 1 else float("nan")

    by_year: dict[int, float] = {}
    for y in np.unique(yr):
        sel = net[yr == y]
        if sel.size >= 20:
            by_year[int(y)] = float(sel.mean())
    inv = k / sfr
    return ConceptResult(
        name=name,
        trades=len(rows),
        win_rate=float((gross > 0).mean()),
        gross_r=float(gross.mean()),
        cost_r=float(cost.mean()),
        net_r=float(net.mean()),
        breakeven_cost_bps=(float(gross.mean() / inv.mean()) * 10_000.0
                            if inv.mean() > 0 else float("nan")),
        net_pct_per_trade=float(net.mean() * cfg.risk_pct * 100),
        sd_r=sd,
        # A t-statistic on the mean net R. |t| > 2 is the conventional bar,
        # and on these sample sizes it is a LOW bar -- it does not correct for
        # the fact that ten concepts are being tested at once.
        t_stat=(float(net.mean() / (sd / np.sqrt(len(net)))) if sd and sd > 0 else float("nan")),
        years_positive=sum(1 for v in by_year.values() if v > 0),
        years_total=len(by_year),
        unresolved_frac=(unresolved / fired) if fired else 0.0,
        by_year=by_year,
    )
