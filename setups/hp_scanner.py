"""
Module: hp_scanner.py
Description: Live scanner for the high-profile ORB setup, emitting the SAME
    signal shape the platform's own scanner emits -- asset, direction, entry,
    stop_loss, take_profit_1, take_profit_2, risk_percent, expected_value,
    confidence_score, regime, supporting_evidence, invalidation,
    historical_context, checks_passed -- so it drops into the existing API and
    dashboard contract without a second format to maintain.

    WHAT MAKES THIS A SCANNER AND NOT A BACKTEST REPLAY. The signal is produced
    at the moment the opening range closes, from information available then: the
    range extremes, the opening relative volume against the previous
    `rvol_lookback_days` sessions, and an ATR built from completed prior
    sessions. The entry is a RESTING STOP ORDER at the range extreme, which is
    the only part of this setup that can honestly be published in advance --
    the fill is whatever the market gives when the level trades.

    CONFIDENCE IS TIED TO MEASUREMENT, NOT TO CONVICTION. `confidence_score`
    reads the per-asset numbers from `data/models/setups/high_profile_setup.json`
    -- the backtest this repo actually ran -- and is CAPPED AT 25 for any
    instrument whose measured net expectancy is negative. A scanner that prints
    a confident signal for a setup its own backtest scored below zero is not a
    scanner, it is an advert. Where no measurement exists for an asset the score
    is capped at 20 and the evidence line says so.

    `expected_value` likewise carries the MEASURED net expectancy per trade in
    percent of account, not a forward projection. It is negative wherever the
    measurement was negative, and it is meant to be read that way.

    CROSS-SECTIONAL SELECTION. The published result rests on ranking the whole
    universe by opening relative volume and taking the top N. `scan_all` does
    that across every symbol scanned in the same call, which is the only place
    the ranking means anything -- a per-symbol scan can apply the `rvol_min`
    threshold and nothing more.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from project_titan_x.setups.high_profile_setup import (
    HighProfileConfig, _session_frame, _stop_distance, daily_context,
)

logger = logging.getLogger(__name__)

MEASURED_PATH = (Path(__file__).resolve().parents[1]
                 / "data" / "models" / "setups" / "high_profile_setup.json")

# Ceilings, not scores. Both exist so a signal can never present itself as
# better evidenced than the measurement behind it.
CAP_NEGATIVE_EXPECTANCY = 25
CAP_UNMEASURED = 20


def load_measured(path: Path = MEASURED_PATH) -> dict[str, Any]:
    """Per-asset backtest numbers, or {} when the backtest has not been run."""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("by_asset", {}) or {}
    except (OSError, ValueError):
        return {}


def _confidence(measured: Optional[dict], rvol: float, cfg: HighProfileConfig) -> tuple[int, str]:
    """A score and the sentence that justifies it. Never one without the other."""
    if not measured or not measured.get("trades"):
        return CAP_UNMEASURED, (
            "No backtest exists for this instrument in this setup, so the score "
            f"is capped at {CAP_UNMEASURED}. Run setups/run_high_profile.py.")

    net = float(measured.get("expectancy_r_net", 0.0))
    n = int(measured.get("trades", 0))
    wr = float(measured.get("win_rate_gross", 0.0)) * 100
    be = float(measured.get("breakeven_cost_bps", 0.0))

    # Relative volume is the paper's own selection variable, so it is the one
    # thing allowed to move the score within the ceiling it is given.
    rv = 0.0 if not np.isfinite(rvol) else float(np.clip((rvol - 1.0) / 2.0, 0.0, 1.0))

    if net <= 0:
        score = int(round(CAP_NEGATIVE_EXPECTANCY * (0.4 + 0.6 * rv)))
        why = (f"Measured net expectancy on {n:,} trades is {net:+.4f} R -- NEGATIVE, "
               f"so the score is capped at {CAP_NEGATIVE_EXPECTANCY}. Gross win rate "
               f"{wr:.1f}%; break-even round-trip cost {be:.1f} bps.")
    else:
        score = int(round(min(85, 45 + 40 * rv)))
        why = (f"Measured net expectancy on {n:,} trades is {net:+.4f} R, gross win "
               f"rate {wr:.1f}%, break-even round-trip cost {be:.1f} bps.")
    return int(np.clip(score, 1, 100)), why


def scan_symbol(
    df: pd.DataFrame,
    symbol: str,
    cfg: Optional[HighProfileConfig] = None,
    measured: Optional[dict[str, Any]] = None,
    as_of: Optional[pd.Timestamp] = None,
) -> Optional[dict[str, Any]]:
    """One signal for the most recent session, or None with nothing to say.

    `as_of` pins the session to evaluate, which is what makes this testable:
    the same function that scans today can be pointed at any past session and
    must produce exactly what it would have produced then.
    """
    cfg = cfg or HighProfileConfig()
    d = _session_frame(df, cfg)
    if d is None or d.empty:
        return None
    ctx = daily_context(d, cfg)
    if ctx.empty:
        return None

    day = (ctx.index[-1] if as_of is None
           else pd.Timestamp(as_of).tz_localize("UTC").normalize()
           if pd.Timestamp(as_of).tzinfo is None
           else pd.Timestamp(as_of).normalize())
    if day not in ctx.index:
        return None
    row = ctx.loc[day]

    direction = float(row["direction"])
    rvol = float(row["rvol"]) if np.isfinite(row["rvol"]) else float("nan")
    atr = float(row["atr14"]) if np.isfinite(row["atr14"]) else float("nan")
    level = float(row["orb_high"] if direction > 0 else row["orb_low"])

    checks = {
        "opening_range_formed": bool(np.isfinite(row["orb_high"]) and np.isfinite(row["orb_low"])),
        "directional_opening_candle": bool(direction != 0),
        "atr_available": bool(np.isfinite(atr)),
        "atr_above_floor": bool(np.isfinite(atr) and atr >= cfg.min_daily_atr),
        "price_above_floor": bool(np.isfinite(level) and level >= cfg.min_price),
        "relative_volume_ok": bool(np.isfinite(rvol) and rvol >= cfg.rvol_min),
    }
    # A doji has no direction to take, and without an ATR there is no stop.
    # Both are hard vetoes rather than a lowered score: there is no trade to
    # score, and emitting one at low confidence would still put it on a screen.
    if not checks["directional_opening_candle"] or not checks["opening_range_formed"]:
        return None
    if not checks["atr_available"] and cfg.stop_model == "atr_pct":
        return None

    dist = _stop_distance(row, direction, level, cfg)
    if not np.isfinite(dist) or dist <= 0:
        return None

    entry = level
    stop = entry - direction * dist
    # tp1 is a practical partial at 2R; tp2 is the paper's 10R cap. The setup's
    # real exit is the session close, which no price level can express -- so it
    # is stated in `invalidation` instead of being faked as a third target.
    tp1 = entry + direction * 2.0 * dist
    tp2 = entry + direction * cfg.max_r * dist

    m = (measured or {}).get(symbol)
    score, why = _confidence(m, rvol, cfg)
    net_r = float(m.get("expectancy_r_net", 0.0)) if m else 0.0

    evidence = [
        f"Opening {cfg.orb_minutes}-minute range {row['orb_low']:.4f} - {row['orb_high']:.4f}; "
        f"the opening candle closed {'up' if direction > 0 else 'down'}, so the "
        f"{'high' if direction > 0 else 'low'} is the trigger.",
        (f"Opening relative volume {rvol:.2f}x the {cfg.rvol_lookback_days}-session average "
         f"({'at or above' if np.isfinite(rvol) and rvol >= cfg.rvol_min else 'BELOW'} "
         f"the {cfg.rvol_min:.2f}x floor)."
         if np.isfinite(rvol) else
         f"Opening relative volume unavailable: fewer than {cfg.rvol_lookback_days} prior sessions."),
        (f"Stop is {cfg.atr_stop_pct:.0%} of the 14-day ATR ({atr:.4f}), i.e. {dist:.4f}."
         if cfg.stop_model == "atr_pct" else
         f"Stop is the opposite extreme of the opening range, i.e. {dist:.4f} away."),
        why,
    ]

    return {
        "asset": symbol,
        "setup": "high_profile_orb",
        "direction": "LONG" if direction > 0 else "SHORT",
        "entry": round(entry, 4),
        "stop_loss": round(stop, 4),
        "take_profit_1": round(tp1, 4),
        "take_profit_2": round(tp2, 4),
        "risk_percent": round(cfg.risk_pct * 100, 4),
        # Measured, not projected: net R per trade converted to percent of the
        # account at the configured risk. Negative where the backtest was.
        "expected_value": round(net_r * cfg.risk_pct * 100, 4),
        "confidence_score": score,
        "regime": "intraday_opening_range",
        "supporting_evidence": evidence,
        "invalidation": (
            f"{'Trade below' if direction > 0 else 'Trade above'} {stop:.4f} ends it. "
            f"The setup's real exit is the session close ({cfg.session_end_utc} UTC) "
            f"whatever price is doing -- tp2 at {tp2:.4f} is the {cfg.max_r:.0f}R cap, "
            f"not the plan."),
        "historical_context": (
            f"{int(m['trades']):,} measured trades on {symbol}: gross win rate "
            f"{m['win_rate_gross']*100:.1f}%, net expectancy {m['expectancy_r_net']:+.4f} R, "
            f"break-even round-trip cost {m['breakeven_cost_bps']:.1f} bps."
            if m and m.get("trades") else
            "No measurement exists for this instrument in this setup."),
        "status": "pending",
        "checks_passed": checks,
        "rvol": (round(rvol, 3) if np.isfinite(rvol) else None),
        "atr14": (round(atr, 6) if np.isfinite(atr) else None),
        "session_day": str(day.date()),
    }


def scan_all(
    frames: dict[str, pd.DataFrame],
    cfg: Optional[HighProfileConfig] = None,
    measured: Optional[dict[str, Any]] = None,
    as_of: Optional[pd.Timestamp] = None,
) -> list[dict[str, Any]]:
    """Scan every symbol, then apply the paper's cross-sectional RVOL cut.

    The top-N ranking is the whole point of the published result, and it only
    exists across a universe -- so it is applied here and nowhere else. Signals
    that survive the threshold but miss the top N are RETURNED with
    `checks_passed['rvol_top_n']` False rather than dropped, because "this
    setup fired and was ranked out" is information a scanner should show.
    """
    cfg = cfg or HighProfileConfig()
    measured = load_measured() if measured is None else measured

    out: list[dict[str, Any]] = []
    for sym, df in frames.items():
        try:
            sig = scan_symbol(df, sym, cfg=cfg, measured=measured, as_of=as_of)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hp_scanner: %s failed: %s", sym, exc)
            continue
        if sig is not None:
            out.append(sig)

    if cfg.use_rvol_filter and out:
        ranked = sorted(
            [s for s in out if s.get("rvol") is not None],
            key=lambda s: s["rvol"], reverse=True)
        keep = {s["asset"] for s in ranked[:cfg.rvol_top_n]
                if s["rvol"] >= cfg.rvol_min}
        for s in out:
            s["checks_passed"]["rvol_top_n"] = s["asset"] in keep

    out.sort(key=lambda s: (-s["confidence_score"], -(s.get("rvol") or 0.0)))
    return out
