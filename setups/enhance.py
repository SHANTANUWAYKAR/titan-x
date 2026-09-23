"""
Module: enhance.py
Description: The two enhancements with real published evidence for DRAWDOWN
    reduction, implemented so their effect can be measured rather than assumed.

    WHY THESE TWO, AND NOTHING ELSE

      VOLATILITY TARGETING. Size inversely to recent realised volatility:
        fix the risk and let the position float, instead of fixing the
        position and letting risk float. This is the single best-evidenced
        drawdown tool in the literature -- a volatility-targeted S&P 500 cut
        its 2008 drawdown from -37.0% to -21.4%, and roughly 15 percentage
        points off the 2020 crash. It is also the only one here that does not
        touch the entry rule, so it cannot manufacture edge; it can only
        redistribute risk.

      REGIME FILTER. Trade only when the market is in the state the setup
        needs. Well evidenced in aggregate AND, per the same sources, "the
        easiest component of a trading system to mess up" -- it is the classic
        route to an in-sample-only result, because a filter has a free
        parameter and any free parameter can be tuned until the equity curve
        looks good. It is therefore implemented with FIXED, conventional
        thresholds and measured, never tuned.

    WHAT IS DELIBERATELY NOT HERE. Nothing that changes WHICH bars fire. An
    enhancement that alters the entry is a new strategy and has to be tested
    as one, against its own null. These two only change SIZE and WHETHER, on
    signals the setup already produced.

    HOW TO READ AN ENHANCEMENT. A drawdown reduction is only meaningful next
    to what it cost in expectancy. Halving the drawdown by halving the size
    is not an improvement -- it is the same curve on a smaller scale. The
    runner therefore reports drawdown, expectancy AND the ratio between them
    (return over max drawdown) so a pure scaling shows up as unchanged.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class EnhanceConfig:
    # --- volatility targeting -------------------------------------------
    use_vol_target: bool = False
    vol_lookback: int = 60          # bars of realised vol
    # Target is expressed as a MULTIPLE of the instrument's own median
    # volatility rather than an absolute number, because 1% daily vol means
    # something different for BTC and for EURUSD, and a single absolute
    # target would silently switch the whole book off for the quiet ones.
    vol_target_mult: float = 1.0
    vol_size_cap: float = 2.0       # never more than 2x base size
    vol_size_floor: float = 0.25    # never less than 1/4 base size

    # --- regime filter ---------------------------------------------------
    use_regime_filter: bool = False
    # "trend"  -> only trade with the 200-EMA slope
    # "vol"    -> only trade when volatility is NOT in its top decile
    # "both"   -> both conditions
    regime_mode: str = "trend"
    regime_ema: int = 200
    regime_vol_pct: float = 0.90    # skip the top decile of volatility

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def realised_vol(df: pd.DataFrame, lookback: int) -> np.ndarray:
    """Trailing realised volatility of log returns, causal.

    `.shift(1)` after the rolling window so the value at bar i uses returns
    strictly BEFORE i. Without it the current bar's own move sets the size of
    the position taken on that bar, which is look-ahead of the quietest and
    most flattering kind.
    """
    c = df["close"].astype(float)
    ret = np.log(c).diff()
    return ret.rolling(lookback, min_periods=max(10, lookback // 3)) \
              .std().shift(1).to_numpy(float)


def vol_target_multiplier(df: pd.DataFrame, cfg: EnhanceConfig) -> np.ndarray:
    """Per-bar size multiplier: target_vol / current_vol, clipped.

    The reference is this instrument's own EXPANDING median volatility, so it
    only ever uses history. A full-sample median would be look-ahead -- and a
    subtle one, because it would quietly make the size correct on average over
    exactly the period being tested.
    """
    v = realised_vol(df, cfg.vol_lookback)
    s = pd.Series(v)
    ref = s.expanding(min_periods=cfg.vol_lookback).median().to_numpy(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        mult = (cfg.vol_target_mult * ref) / v
    mult = np.where(np.isfinite(mult), mult, 1.0)
    return np.clip(mult, cfg.vol_size_floor, cfg.vol_size_cap)


def regime_ok(df: pd.DataFrame, cfg: EnhanceConfig) -> np.ndarray:
    """Per-bar boolean: is this a regime the setup should trade at all?

    Both tests are causal and use FIXED conventional thresholds. They are not
    tuned, because a tuned regime filter is the standard way to produce an
    in-sample-only result.
    """
    c = df["close"].astype(float)
    ema = c.ewm(span=cfg.regime_ema, adjust=False).mean()
    # slope of the EMA over the last 20 bars, evaluated at the PREVIOUS bar
    slope = (ema - ema.shift(20)).shift(1).to_numpy(float)
    px = c.shift(1).to_numpy(float)
    ema_v = ema.shift(1).to_numpy(float)

    trend_ok = np.where(np.isfinite(slope),
                        ((px > ema_v) & (slope > 0)) | ((px < ema_v) & (slope < 0)),
                        False)

    v = realised_vol(df, cfg.vol_lookback)
    s = pd.Series(v)
    cut = s.expanding(min_periods=cfg.vol_lookback).quantile(cfg.regime_vol_pct)
    vol_ok = np.where(np.isfinite(v) & np.isfinite(cut.to_numpy(float)),
                      v <= cut.to_numpy(float), False)

    if cfg.regime_mode == "trend":
        return trend_ok
    if cfg.regime_mode == "vol":
        return vol_ok
    return trend_ok & vol_ok


def apply_enhancements(df: pd.DataFrame, signals: np.ndarray,
                       cfg: EnhanceConfig) -> tuple[np.ndarray, np.ndarray]:
    """(filtered_signals, size_multiplier) for a setup's raw signals.

    Never changes the DIRECTION of a signal and never creates one. It can only
    switch a signal off (regime) or change how large it is (vol target), which
    is what keeps this an enhancement rather than a different strategy.
    """
    sig = signals.copy()
    if cfg.use_regime_filter:
        sig = np.where(regime_ok(df, cfg), sig, 0)
    mult = (vol_target_multiplier(df, cfg) if cfg.use_vol_target
            else np.ones(len(df), dtype=float))
    return sig, mult


def drawdown_stats(r: np.ndarray) -> dict[str, float]:
    """Max drawdown, longest losing streak and return/drawdown, on ORDERED r.

    The caller is responsible for chronological order. Return-over-drawdown is
    included because it is the number that distinguishes a real improvement
    from simply trading smaller: scaling every trade by k scales both total R
    and drawdown by k, leaving this ratio unchanged.
    """
    if r.size == 0:
        return {"max_drawdown_r": 0.0, "longest_losing_streak": 0,
                "total_r": 0.0, "return_over_maxdd": float("nan")}
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    dd = float(np.max(peak - eq))
    streak = worst = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        worst = max(worst, streak)
    total = float(eq[-1])
    return {"max_drawdown_r": dd, "longest_losing_streak": int(worst),
            "total_r": total,
            "return_over_maxdd": (total / dd) if dd > 0 else float("nan")}
