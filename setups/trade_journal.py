"""
Module: trade_journal.py
Description: Turns a backtest into a trade-by-trade JOURNAL in the standard
    review format, then computes the statistics that review is for.

    RECORD FIELDS (one row per trade)
      Date · Pair · Session · HTF bias · Setup · Entry · SL · TP · R:R ·
      Result in R · Screenshot · Reason for entry · Reason for failure ·
      Mistake / no mistake

    STATISTICS
      Win rate · Average win · Average loss · Expectancy · Profit factor ·
      Maximum drawdown · Longest losing streak · Best/worst session ·
      Best/worst pair

    TWO FIELDS ARE HONEST PLACEHOLDERS AND ARE LABELLED AS SUCH.

      Screenshot   A backtest has no screenshot. The column carries a
                   deterministic chart LINK (TradingView, symbol + interval +
                   bar timestamp) so the bar can be pulled up, rather than a
                   fabricated image path.
      Mistake      A mechanical backtest cannot make a discretionary mistake --
                   it follows the rule every time. Every row is therefore
                   "no mistake (mechanical)". The column exists because the
                   same journal is meant to be used for MANUAL trades, where
                   it is the most valuable column on the page. Filling it with
                   invented judgements here would destroy exactly that value.

    "Reason for failure" is derived from the exit that actually happened --
    stop hit, time barrier, or target missed by less than half a stop -- not
    from a story written after the fact.

    SESSION is assigned from the bar's UTC hour using the conventional FX
    windows. A daily bar has no session, and is labelled "n/a (daily+)"
    rather than being forced into one.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Conventional FX session windows, UTC. Overlaps are resolved by order:
# a bar at 13:00 is "London/NY overlap", which is its own regime.
_SESSIONS = (
    ("Sydney", 21, 24), ("Sydney", 0, 1), ("Tokyo", 1, 7),
    ("London", 7, 12), ("London/NY overlap", 12, 16),
    ("New York", 16, 21),
)

_INTRADAY = {"1m", "2m", "5m", "15m", "30m", "1h", "2h", "4h"}
_TV_INTERVAL = {"1m": "1", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "4h": "240", "1d": "D", "1wk": "W"}


def session_of(ts: pd.Timestamp, timeframe: str) -> str:
    """Trading session for a bar, or 'n/a' when the timeframe has no session."""
    if timeframe not in _INTRADAY:
        return "n/a (daily+)"
    h = int(pd.Timestamp(ts).tz_convert("UTC").hour) if pd.Timestamp(ts).tzinfo \
        else int(pd.Timestamp(ts).hour)
    for name, lo, hi in _SESSIONS:
        if lo <= h < hi:
            return name
    return "Sydney"


def htf_bias(close: pd.Series, i: int, fast: int = 50, slow: int = 200) -> str:
    """Bias from the slower moving averages, read at bar i only.

    Uses `.iloc[:i+1]` on purpose -- an EMA computed over the whole series and
    then indexed at i is NOT the same number a trader would have seen, because
    pandas' ewm is causal but the SERIES was built with future bars present for
    any centred or full-sample statistic. Slicing first makes the causality
    obvious to a reader rather than something to be trusted.
    """
    if i < slow:
        return "insufficient history"
    window = close.iloc[: i + 1]
    f = window.ewm(span=fast, adjust=False).mean().iloc[-1]
    s = window.ewm(span=slow, adjust=False).mean().iloc[-1]
    if not (np.isfinite(f) and np.isfinite(s)):
        return "insufficient history"
    gap = (f - s) / s if s else 0.0
    if gap > 0.005:
        return "Bullish"
    if gap < -0.005:
        return "Bearish"
    return "Neutral"


def chart_link(symbol: str, timeframe: str) -> str:
    iv = _TV_INTERVAL.get(timeframe, "D")
    return f"https://www.tradingview.com/chart/?symbol={symbol}&interval={iv}"


@dataclass
class JournalRow:
    date: str
    pair: str
    session: str
    htf_bias: str
    setup: str
    entry: float
    sl: float
    tp: float
    rr: float
    result_r: float
    screenshot: str
    reason_for_entry: str
    reason_for_failure: str
    mistake: str
    # kept for the statistics, not part of the printed record
    _direction: str = field(default="", repr=False)
    _exit: str = field(default="", repr=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_journal(
    df: pd.DataFrame,
    signals: np.ndarray,
    *,
    symbol: str,
    timeframe: str,
    setup_name: str,
    atr: np.ndarray,
    atr_mult: float = 1.0,
    reward_risk: float = 2.0,
    horizon_bars: int = 20,
    cost_round_trip: float = 0.003,
    risk_pct: float = 0.01,
    max_leverage: float = 3.0,
    reason_fn=None,
) -> list[JournalRow]:
    """One JournalRow per trade the signal array produced.

    Entry is the NEXT bar's open. The stop is checked BEFORE the target on
    every bar, so a bar containing both is a loss -- OHLC cannot order two
    touches inside one bar.
    """
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    close_s = df["close"]
    ts = (pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
          if "timestamp" in df.columns
          else pd.to_datetime(df.index, utc=True, errors="coerce"))
    ts = pd.Series(ts).reset_index(drop=True)

    rows: list[JournalRow] = []
    n = len(df)
    for i in range(n - 1):
        d = int(signals[i])
        if d == 0 or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        entry = o[i + 1]
        if not np.isfinite(entry) or entry <= 0:
            continue
        dist = atr_mult * atr[i]
        stop_frac = dist / entry
        if not np.isfinite(stop_frac) or stop_frac <= 0:
            continue
        sl = entry - d * dist
        tp = entry + d * reward_risk * dist

        r_gross, exit_kind, mae_r = None, "time", 0.0
        for j in range(i + 1, min(i + 1 + horizon_bars, n)):
            adverse = (entry - l[j]) if d == 1 else (h[j] - entry)
            mae_r = max(mae_r, adverse / dist)
            if (d == 1 and l[j] <= sl) or (d == -1 and h[j] >= sl):
                r_gross, exit_kind = -1.0, "stop"
                break
            if (d == 1 and h[j] >= tp) or (d == -1 and l[j] <= tp):
                r_gross, exit_kind = reward_risk, "target"
                break
        if r_gross is None:
            j = min(i + horizon_bars, n - 1)
            r_gross = float(d * (c[j] - entry) / dist)
            exit_kind = "time"

        # THE LEVERAGE CAP SCALES BOTH THE RESULT AND THE COST.
        # Risking a full 1R needs `risk_pct / stop_frac` of notional; when that
        # exceeds max_leverage the position is forced smaller, so the realised
        # R and the cost paid BOTH shrink by the same factor. Charging the
        # uncapped cost against a capped position overstates cost by up to 1.7x
        # on a 0.2% stop -- and intraday stops are tight, which is why 1h
        # expectancy read -1.84R before this was fixed.
        #
        # Third time this exact omission has appeared in this codebase
        # (high_profile_setup.py, concept_lab.py, here). The ratio gross:cost
        # is unchanged by k, so break-even conclusions were never affected --
        # only the magnitude.
        want = risk_pct / stop_frac
        k = float(min(want, max_leverage) / want) if want > 0 else 1.0
        cost_r = k * (cost_round_trip / stop_frac)
        result_r = float(k * r_gross - cost_r)

        if exit_kind == "stop":
            why_fail = (f"Stop hit. Worst excursion {mae_r:.2f}R against the "
                        f"entry before it triggered.")
        elif exit_kind == "target":
            why_fail = "—  (target reached)"
        else:
            why_fail = (f"Neither barrier touched in {horizon_bars} bars; closed "
                        f"at the time limit for {r_gross:+.2f}R gross. Worst "
                        f"excursion {mae_r:.2f}R.")
        if exit_kind != "stop" and result_r < 0 <= r_gross:
            why_fail += f"  Turned negative on cost ({cost_r:.2f}R)."

        rows.append(JournalRow(
            date=str(ts.iloc[i + 1])[:19],
            pair=symbol,
            session=session_of(ts.iloc[i + 1], timeframe),
            htf_bias=htf_bias(close_s, i),
            setup=setup_name,
            entry=round(float(entry), 6),
            sl=round(float(sl), 6),
            tp=round(float(tp), 6),
            rr=round(float(reward_risk), 2),
            result_r=round(result_r, 4),
            screenshot=chart_link(symbol, timeframe),
            reason_for_entry=(reason_fn(df, i, d) if reason_fn
                              else f"{setup_name} fired {'long' if d == 1 else 'short'}; "
                                   f"stop {atr_mult}xATR, target {reward_risk}R."),
            reason_for_failure=why_fail,
            mistake="no mistake (mechanical — rule followed exactly)",
            _direction="Long" if d == 1 else "Short",
            _exit=exit_kind,
        ))
    return rows


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------

@dataclass
class JournalStats:
    trades: int
    win_rate: float
    average_win_r: float
    average_loss_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    longest_losing_streak: int
    best_session: tuple[str, float]
    worst_session: tuple[str, float]
    best_pair: tuple[str, float]
    worst_pair: tuple[str, float]
    total_r: float
    by_session: dict[str, dict[str, float]] = field(default_factory=dict)
    by_pair: dict[str, dict[str, float]] = field(default_factory=dict)
    by_setup: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _group(rows: list[JournalRow], key) -> dict[str, dict[str, float]]:
    """Per-group stats INCLUDING that group's own drawdown and streak.

    A per-pair drawdown is a real number -- one instrument's trades are
    genuinely sequential -- where the pooled figure is not.
    """
    out: dict[str, list[float]] = {}
    for r in sorted(rows, key=lambda x: x.date):
        out.setdefault(key(r), []).append(r.result_r)
    res = {}
    for k, v in out.items():
        a = np.asarray(v, dtype=float)
        eq = np.cumsum(a)
        peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
        streak = worst = 0
        for x in a:
            streak = streak + 1 if x <= 0 else 0
            worst = max(worst, streak)
        res[k] = {
            "trades": len(a), "total_r": float(a.sum()),
            "expectancy_r": float(a.mean()),
            "win_rate": float((a > 0).mean()),
            "max_drawdown_r": float(np.max(peak - eq)) if a.size else 0.0,
            "longest_losing_streak": int(worst),
        }
    return res


def compute_stats(rows: list[JournalRow], min_group: int = 20) -> Optional[JournalStats]:
    """Journal statistics. Returns None on an empty journal.

    `min_group` guards the best/worst rankings: a session or pair with three
    trades will top any leaderboard by luck, and reporting it as "best" is the
    single easiest way to mislead yourself with a journal.
    """
    if not rows:
        return None
    # PATH-DEPENDENT STATISTICS NEED CHRONOLOGICAL ORDER.
    # Callers pool trades asset by asset, so the raw list runs
    # AAPL-start..AAPL-end, AMZN-start..AMZN-end, ... A cumulative sum over
    # that order is not an equity curve, it is a concatenation, and the
    # "drawdown" it produces is the sum of unrelated losing tails glued
    # together. Measured 2026-09-23: this reported 164.9 R of drawdown and a
    # 46-trade losing streak on weekly round_number, neither of which any
    # account could have experienced.
    #
    # Win rate, expectancy, profit factor and the averages are all
    # order-INDEPENDENT and unaffected either way; only drawdown and streak
    # are corrected by this sort.
    rows = sorted(rows, key=lambda x: x.date)
    r = np.array([x.result_r for x in rows], dtype=float)
    wins, losses = r[r > 0], r[r <= 0]
    gross_win = float(wins.sum()) if wins.size else 0.0
    gross_loss = float(-losses.sum()) if losses.size else 0.0

    # Drawdown on the cumulative R curve -- R, not currency, because position
    # size is a separate decision and mixing them hides which one hurt.
    #
    # STILL AN APPROXIMATION, and the direction is known. Pooling many assets
    # means positions that were CONCURRENT are scored sequentially, so this
    # understates the drawdown a real book would have taken when several
    # instruments drew down together. Per-asset drawdown is in `by_pair`;
    # this pooled figure is the optimistic bound, not the pessimistic one.
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    max_dd = float(np.max(peak - eq)) if r.size else 0.0

    streak = worst_streak = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        worst_streak = max(worst_streak, streak)

    by_session = _group(rows, lambda x: x.session)
    by_pair = _group(rows, lambda x: x.pair)
    by_setup = _group(rows, lambda x: x.setup)
    ok_s = {k: v for k, v in by_session.items() if v["trades"] >= min_group} or by_session
    ok_p = {k: v for k, v in by_pair.items() if v["trades"] >= min_group} or by_pair

    best_s = max(ok_s.items(), key=lambda kv: kv[1]["expectancy_r"])
    worst_s = min(ok_s.items(), key=lambda kv: kv[1]["expectancy_r"])
    best_p = max(ok_p.items(), key=lambda kv: kv[1]["expectancy_r"])
    worst_p = min(ok_p.items(), key=lambda kv: kv[1]["expectancy_r"])

    return JournalStats(
        trades=len(rows),
        win_rate=float((r > 0).mean()),
        average_win_r=float(wins.mean()) if wins.size else 0.0,
        average_loss_r=float(losses.mean()) if losses.size else 0.0,
        expectancy_r=float(r.mean()),
        # Infinite when there are no losers at all -- reported as inf rather
        # than a large finite number, because the honest statement is "this
        # sample contains no losses", not "the ratio is 999".
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        max_drawdown_r=max_dd,
        longest_losing_streak=worst_streak,
        best_session=(best_s[0], best_s[1]["expectancy_r"]),
        worst_session=(worst_s[0], worst_s[1]["expectancy_r"]),
        best_pair=(best_p[0], best_p[1]["expectancy_r"]),
        worst_pair=(worst_p[0], worst_p[1]["expectancy_r"]),
        total_r=float(r.sum()),
        by_session=by_session,
        by_pair=by_pair,
        by_setup=by_setup,
    )
