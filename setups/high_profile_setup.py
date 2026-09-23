"""
Module: high_profile_setup.py
Description: The best-documented intraday setup in the public literature, built
    to this project's measurement rules rather than to its press release.

    WHERE THIS COMES FROM. Zarattini, Barbon & Aziz (2024), "A Profitable Day
    Trading Strategy for the U.S. Equity Market", and Zarattini & Aziz (2023,
    SSRN 4416622), "Can Day Trading Really Be Profitable?". Between them these
    are the most cited quantitative day-trading papers in circulation, and the
    reported numbers are the ones every retail course quotes second-hand.

    WHAT THE PAPERS ACTUALLY SPECIFY, AND WHAT THIS IMPLEMENTS

      Opening range     first 5 minutes. The paper's own length sweep is the
                        single most load-bearing parameter in it: 5 min gave
                        1,637% where 15 min gave 272% and 30 min gave 21%.
      Direction         the sign of the first 5-minute candle. A doji is NOT a
                        trade -- there is no direction to take.
      Entry             a stop order at the opening-range extreme, so a day
                        that never revisits the level is simply not traded.
                        The ETF paper instead enters at the open of the second
                        5-minute bar; both are available as `entry_trigger`.
      Stop              the equities paper uses 10% of the 14-day ATR, the ETF
                        paper the opposite extreme of the opening candle. Both
                        available as `stop_model`, because they are NOT close
                        to equivalent -- a 10%-ATR stop is several times
                        tighter, which is what makes the cost term decisive.
      Target            END OF DAY, capped at 10R. Not a fixed 2R. This is the
                        difference most retail retellings get wrong, and it
                        inverts the whole trade profile: the published QQQ win
                        rate is 24%, which only works because the winners are
                        not truncated at 2R.
      Sizing            1% risk per position, 4x leverage cap.

      THE SELECTION FILTER, which is the actual finding. Universe: price > $5,
      14-day average volume >= 1M shares, 14-day ATR > $0.50. Then rank by
      OPENING relative volume and trade only the top 20. The same breakout
      rules score Sharpe 0.48 unfiltered and 2.81 filtered. The edge that
      paper found is not the breakout -- it is WHICH instrument you take the
      breakout on. Everything else is the vehicle.

    WHAT ACTUALLY REPRODUCED HERE (2026-09-22, 16 instruments, 19,663 trades).
    Not the ranking. Sweeping top-N with the threshold pinned at 1.0x gives a
    FLAT curve -- -0.0727 R at top-1 against -0.0659 R at top-16 -- and on 16
    instruments "top 16" is already the whole universe, so the cross-sectional
    step this setup is famous for cannot do anything.

    The THRESHOLD is what moves. Requiring the opening window to trade at least
    0.25x-1x its 14-day norm roughly halves the gross loss (-0.1398 -> -0.057
    to -0.071) across a broad, stable band. A `rvol >= 0` control keeps 99% of
    trades and lands at -0.1401, identical to no filter, which rules out the
    obvious artifact: `NaN >= x` is False, so EVERY threshold silently drops
    each instrument's first `rvol_lookback_days` sessions along with the
    low-volume opens.

    Above 1x the curve is unordered on a collapsing sample (1.25x: -0.0127,
    2x: -0.0361, 4x: -0.0001, 6x: -0.0568). Those near-zero rows are sampling
    variation, not a better setting. Use `--sweep-rvol-min` before believing
    any single one of them.

    WHY THIS PROJECT SHOULD DISTRUST THE HEADLINE ANYWAY. An independent
    replication (github.com/giovannibrusco/zarattini-2023-orb-qqq) reproduced
    the QQQ study inside noise -- 1,775 trades against the paper's 1,795,
    Sharpe 1.06 against 1.12 -- and then priced execution in. Net PnL fell from
    $138,639 to $4,860 at 2c entry / 4c stop slippage, a 96.5% reduction, with
    break-even at roughly 2.2c per share against a spread of about 1c. The
    bootstrap 95% CI on Sharpe was [0.05, 1.41] against buy-and-hold QQQ's
    [-0.03, 1.47] -- overlapping, so no portfolio-level edge over holding. And
    76% of the surviving PnL came from 2022 alone.

    That is the same conclusion this repo reached independently on its own
    data, by its own route, which is the reason this module reports
    `breakeven_cost_bps` on every result. A strategy whose break-even cost sits
    inside its own spread has not been shown to work; it has been shown to work
    for someone who does not pay to trade.

    CAUSALITY. The opening range is fixed once the window closes. Relative
    volume compares today's opening window against the mean of the PREVIOUS
    `rvol_lookback_days` sessions' opening windows. The ATR is computed from
    completed sessions strictly BEFORE today. Entry is never on the bar that
    revealed the signal. A bar containing both stop and target is scored a
    LOSS, because OHLC cannot order two touches inside one bar.
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

# This repo's own round-trip cost assumption, in basis points of notional
# (0.1% commission + 0.05% slippage per side = 0.30%). Kept as the DEFAULT
# rather than the papers' $0.0035/share, because the papers price a
# professional equities desk and this book is not one. `breakeven_cost_bps`
# on every result is what makes the choice auditable instead of load-bearing.
DEFAULT_COST_BPS_ROUND_TRIP = 30.0


@dataclass
class HighProfileConfig:
    """Every knob, with the published value and the reason it is that value."""

    # --- session ------------------------------------------------------------
    session_start_utc: str = "13:30"      # NY equity open
    session_end_utc: str = "20:00"
    orb_minutes: int = 5                  # the paper's own sweep put 5 far ahead

    # --- entry --------------------------------------------------------------
    entry_trigger: str = "stop_order"     # "stop_order" | "open"
    skip_doji: bool = True                # no direction, no trade

    # --- stop ---------------------------------------------------------------
    stop_model: str = "atr_pct"           # "atr_pct" | "orb_opposite"
    atr_stop_pct: float = 0.10            # 10% of the 14-day ATR
    atr_lookback_days: int = 14

    # --- exit ---------------------------------------------------------------
    exit_model: str = "eod"               # "eod" | "rr"
    max_r: float = 10.0                   # cap, not a conventional target
    reward_risk: float = 2.0              # only used when exit_model == "rr"

    # --- selection ----------------------------------------------------------
    # `rvol_min` is the knob that measurably matters on this book; `rvol_top_n`
    # is the paper's cross-sectional step and did NOTHING here. Both kept: the
    # ranking is what the published result used, and a wider universe is the
    # one condition under which it might start to bite.
    # See the module docstring for the sweeps.
    use_rvol_filter: bool = True
    rvol_lookback_days: int = 14
    rvol_min: float = 1.0                 # opening relative volume >= 100%
    rvol_top_n: int = 20                  # cross-sectional, applied per day

    # --- universe gates (paper's own; skipped when data cannot support them)-
    min_price: float = 5.0
    min_daily_atr: float = 0.50

    # --- sizing -------------------------------------------------------------
    risk_pct: float = 0.01
    max_leverage: float = 4.0             # the paper's cap, not this repo's 3x
    cost_bps_round_trip: float = DEFAULT_COST_BPS_ROUND_TRIP

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _session_frame(df: pd.DataFrame, cfg: HighProfileConfig) -> Optional[pd.DataFrame]:
    """Index by UTC timestamp, keep only in-session bars, tag day and offset."""
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if "volume" not in d.columns:
        return None
    ts = (pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
          if "timestamp" in d.columns
          else pd.to_datetime(d.index, utc=True, errors="coerce"))
    d = d.loc[ts.notna()].copy()
    ts = ts[ts.notna()]
    d.index = pd.DatetimeIndex(ts)
    d = d.sort_index()

    sh, sm = (int(x) for x in cfg.session_start_utc.split(":"))
    eh, em = (int(x) for x in cfg.session_end_utc.split(":"))
    start_m, end_m = sh * 60 + sm, eh * 60 + em
    mod = d.index.hour * 60 + d.index.minute
    d = d.loc[(mod >= start_m) & (mod < end_m)].copy()
    if d.empty:
        return None
    d["_day"] = d.index.normalize()
    d["_min_since_open"] = (d.index.hour * 60 + d.index.minute) - start_m
    return d


def daily_context(d: pd.DataFrame, cfg: HighProfileConfig) -> pd.DataFrame:
    """Per-session context: opening range, relative volume, prior-day ATR.

    Every column is shifted so a session only ever sees COMPLETED earlier
    sessions. `atr14` and `rvol_base` both use `.shift(1)` before rolling for
    exactly that reason -- without it a day's own volume sits in the average it
    is being compared against, which makes every relative volume look tame and
    silently destroys the filter this setup depends on.
    """
    op = d[d["_min_since_open"] < cfg.orb_minutes]
    g = op.groupby("_day")
    ctx = pd.DataFrame({
        "orb_high": g["high"].max(),
        "orb_low": g["low"].min(),
        "orb_open": g["open"].first(),
        "orb_close": g["close"].last(),
        "orb_volume": g["volume"].sum(),
    })

    day = d.groupby("_day")
    hi, lo, cl = day["high"].max(), day["low"].min(), day["close"].last()
    prev_cl = cl.shift(1)
    tr = pd.concat([hi - lo, (hi - prev_cl).abs(), (lo - prev_cl).abs()],
                   axis=1).max(axis=1)
    ctx["atr14"] = tr.shift(1).rolling(cfg.atr_lookback_days).mean()
    ctx["prev_close"] = prev_cl
    ctx["day_volume"] = day["volume"].sum()
    ctx["avg_day_volume"] = ctx["day_volume"].shift(1).rolling(
        cfg.atr_lookback_days).mean()

    base = ctx["orb_volume"].shift(1).rolling(cfg.rvol_lookback_days).mean()
    ctx["rvol"] = ctx["orb_volume"] / base.replace(0, np.nan)
    ctx["direction"] = np.sign(ctx["orb_close"] - ctx["orb_open"])
    return ctx


def _stop_distance(row: pd.Series, direction: float, entry: float,
                   cfg: HighProfileConfig) -> float:
    """Absolute stop distance in price units, or nan when unavailable."""
    if cfg.stop_model == "orb_opposite":
        level = row["orb_low"] if direction > 0 else row["orb_high"]
        return abs(entry - float(level))
    atr = float(row["atr14"])
    if not np.isfinite(atr) or atr <= 0:
        return float("nan")
    return cfg.atr_stop_pct * atr


def extract_hp_signals(df: pd.DataFrame, cfg: HighProfileConfig,
                       symbol: str = "") -> pd.DataFrame:
    """One row per tradeable session, with its realised R multiple.

    `_r_gross` is the R multiple before cost. `_cost_r` converts this repo's
    notional cost into R units via `cost / stop_frac`: risking 1R means holding
    `risk_pct / stop_frac` of notional, so a tighter stop buys more notional
    and therefore more cost per unit of risk. That division is the entire
    reason a 10%-of-ATR stop is dangerous on a retail cost base, and hiding it
    inside a flat percentage would conceal the finding.
    """
    d = _session_frame(df, cfg)
    if d is None or d.empty:
        return pd.DataFrame()
    ctx = daily_context(d, cfg)
    cost_frac = cfg.cost_bps_round_trip / 10_000.0

    rows: list[dict[str, Any]] = []
    for day, session in d.groupby("_day"):
        if day not in ctx.index:
            continue
        row = ctx.loc[day]
        direction = float(row["direction"])
        if cfg.skip_doji and direction == 0:
            continue
        if direction == 0:
            continue
        post = session[session["_min_since_open"] >= cfg.orb_minutes]
        if len(post) < 2:
            continue

        o = post["open"].to_numpy(float)
        h = post["high"].to_numpy(float)
        low = post["low"].to_numpy(float)
        c = post["close"].to_numpy(float)

        # ---- entry ---------------------------------------------------------
        if cfg.entry_trigger == "open":
            entry, k0 = float(o[0]), 0
        else:
            level = float(row["orb_high"] if direction > 0 else row["orb_low"])
            if not np.isfinite(level):
                continue
            hit = (h >= level) if direction > 0 else (low <= level)
            if not hit.any():
                continue                     # the level was never revisited
            k0 = int(np.argmax(hit))
            # A stop order fills at its level, unless the bar opened through it.
            entry = (max(float(o[k0]), level) if direction > 0
                     else min(float(o[k0]), level))
        if not np.isfinite(entry) or entry <= 0:
            continue
        if entry < cfg.min_price:
            continue

        # ---- stop / target -------------------------------------------------
        dist = _stop_distance(row, direction, entry, cfg)
        if not np.isfinite(dist) or dist <= 0:
            continue
        atr = float(row["atr14"])
        if np.isfinite(atr) and atr < cfg.min_daily_atr:
            continue
        stop = entry - direction * dist
        cap_r = cfg.max_r if cfg.exit_model == "eod" else cfg.reward_risk
        target = entry + direction * cap_r * dist
        stop_frac = dist / entry

        # ---- walk the rest of the session ---------------------------------
        r_gross, exit_reason = None, "eod"
        for j in range(k0, len(post)):
            if (direction > 0 and low[j] <= stop) or (direction < 0 and h[j] >= stop):
                r_gross, exit_reason = -1.0, "stop"
                break
            if (direction > 0 and h[j] >= target) or (direction < 0 and low[j] <= target):
                r_gross, exit_reason = cap_r, "target"
                break
        if r_gross is None:
            r_gross = float(direction * (c[-1] - entry) / dist)

        # THE LEVERAGE CAP SCALES EVERYTHING, NOT JUST THE COST. Risking a
        # full 1R needs `risk_pct / stop_frac` of notional; when that exceeds
        # `max_leverage` the position is forced smaller, so the realised loss
        # is BELOW 1R and the cost paid is below `cost / stop_frac` by the same
        # factor. An earlier version applied the cap to the notional but not to
        # the cost, which reported >6 R of cost per trade on instruments whose
        # opening range was tight -- an artefact, not a measurement. `k` is
        # that factor, and it multiplies gross and cost together so their RATIO
        # (and therefore the break-even cost) is untouched.
        want = cfg.risk_pct / stop_frac
        notional = float(min(want, cfg.max_leverage))
        k = float(notional / want) if want > 0 else 1.0

        rows.append({
            "_sym": symbol,
            "_ts": session.index[0],
            "_day": day,
            "_dir": direction,
            "_entry": entry,
            "_stop": stop,
            "_target": target,
            "_stop_frac": stop_frac,
            "_notional": notional,
            "_size_ratio": k,
            "_r_gross": float(r_gross),
            "_r_gross_sized": float(r_gross * k),
            "_cost_r": float(k * cost_frac / stop_frac),
            "_r_net": float(k * (r_gross - cost_frac / stop_frac)),
            "_exit": exit_reason,
            "_rvol": float(row["rvol"]) if np.isfinite(row["rvol"]) else np.nan,
            "_atr14": atr,
            "_orb_high": float(row["orb_high"]),
            "_orb_low": float(row["orb_low"]),
        })
    return pd.DataFrame(rows)


def apply_rvol_selection(sig: pd.DataFrame, cfg: HighProfileConfig) -> pd.DataFrame:
    """The paper's selection step: per day, keep the top N by relative volume.

    Cross-sectional, so it only means anything on a POOLED multi-asset frame --
    on one instrument "top 20 of 1" keeps everything and the filter silently
    does nothing. Callers running a single symbol get the `rvol_min` threshold
    and nothing else, which is stated here rather than discovered later.
    """
    if sig.empty or not cfg.use_rvol_filter:
        return sig
    out = sig[sig["_rvol"] >= cfg.rvol_min].copy()
    if out.empty:
        return out
    if cfg.rvol_top_n and out["_sym"].nunique() > 1:
        out = (out.sort_values("_rvol", ascending=False)
                  .groupby("_day", group_keys=False)
                  .head(cfg.rvol_top_n))
    return out.sort_values("_ts")


def hp_economics(sig: pd.DataFrame, cfg: HighProfileConfig) -> dict[str, Any]:
    """Net R, and the cost level at which the net R would be exactly zero.

    `breakeven_cost_bps` is the number to read first. It is the round-trip cost
    this setup could absorb before its edge is gone, and it is directly
    comparable to what a retail account actually pays. The published
    replication of this same strategy put that figure at roughly 2.2c per share
    on a ~1c spread -- an edge inside its own execution noise.
    """
    if sig.empty:
        return {"trades": 0}
    r_net = sig["_r_net"].to_numpy(float)
    r_gross = sig["_r_gross"].to_numpy(float)
    k = (sig["_size_ratio"].to_numpy(float) if "_size_ratio" in sig.columns
         else np.ones(len(sig)))
    # Both terms carry the size factor, so break-even stays the honest ratio
    # of what the trade earned to what it paid per unit of cost.
    r_gross_sized = r_gross * k
    inv_stop = (k / sig["_stop_frac"]).to_numpy(float)
    # BOTH win rates, because they answer different questions and the papers
    # quote the gross one. With a 10%-of-ATR stop the cost term alone exceeds
    # 1R, so a genuinely profitable directional trade still lands in the net
    # loss column -- reporting only the net figure would read as "the entry is
    # broken" when what it actually says is "the cost assumption is decisive".
    wins = r_net > 0
    wins_gross = r_gross > 0
    n = int(len(sig))
    sd = float(r_net.std(ddof=1)) if n > 1 else float("nan")

    # mean(r_net) = mean(r_gross) - c * mean(1/stop_frac); solve for c at zero.
    be_c = (float(r_gross_sized.mean() / inv_stop.mean())
            if inv_stop.mean() > 0 else float("nan"))
    return {
        "trades": n,
        "win_rate": float(wins.mean()),
        "win_rate_gross": float(wins_gross.mean()),
        "expectancy_r_gross": float(r_gross.mean()),
        "expectancy_r_gross_sized": float(r_gross_sized.mean()),
        "mean_size_ratio": float(k.mean()),
        "expectancy_r_net": float(r_net.mean()),
        "mean_cost_r": float(sig["_cost_r"].mean()),
        "sd_r": sd,
        "sharpe_per_trade": (float(r_net.mean() / sd) if sd and np.isfinite(sd) and sd > 0
                             else float("nan")),
        "mean_stop_frac": float(sig["_stop_frac"].mean()),
        "mean_notional": float(sig["_notional"].mean()),
        "pct_pct_per_trade": float(r_net.mean() * cfg.risk_pct * 100),
        "breakeven_cost_bps": be_c * 10_000.0,
        "applied_cost_bps": cfg.cost_bps_round_trip,
        "exit_mix": sig["_exit"].value_counts().to_dict(),
        "mean_rvol": float(np.nanmean(sig["_rvol"])) if sig["_rvol"].notna().any() else float("nan"),
    }
