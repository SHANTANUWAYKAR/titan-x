"""
Module: instrument_profile.py
Description: PHASE 3 of reports/statergy.txt -- an individual research profile
    per (instrument, timeframe), so strategy families are chosen from what an
    instrument actually DOES rather than applied uniformly to all 29 assets.

    THE GAP THIS CLOSES. statergy.txt PHASE 3 is emphatic: "Do NOT use one
    universal strategy for every market... Do NOT force a strategy onto an
    instrument simply because it performs well elsewhere." Before this module
    there was no per-asset characterisation anywhere in the project -- confirmed
    by grep across engines/, research/ and scripts/ for instrument_profile /
    asset_profile / research_profile, which returned nothing. Every sweep ran
    the same 830-candidate grid against every instrument and timeframe with no
    prior on which families were even plausible.

    REUSES, NEVER REIMPLEMENTS. Trend persistence (Hurst), mean-reversion
    tendency (Ornstein-Uhlenbeck half-life) and stationarity all come from
    e12_quant_research, which already implements them and documents a real bug
    it fixed along the way (classical R/S must run on a series' INCREMENTS, not
    its level). Recomputing them here with a second convention would give this
    module a different answer from the rest of the platform for the same
    question. ATR comes from e07_technical's enriched frame for the same reason.

    THE HEADLINE NUMBER IS THE COST HURDLE. `cost_atr_ratio` = one round trip's
    modelled cost (2 x (commission + slippage), i.e. 0.3% at E26's defaults)
    divided by the median bar range as a fraction of price. It answers the
    question that decides whether a timeframe is tradeable at all: how much of a
    typical bar's movement is consumed just entering and exiting? A ratio near
    or above 1.0 means the average bar cannot pay for the trade, and no entry
    rule can fix that -- it is a property of the instrument and timeframe, not
    of the strategy. This number is absent everywhere else in the project and
    explains, without any reference to signal quality, why this platform's
    intraday backtests have consistently produced tiny or negative expectancy.

    FAMILY SUITABILITY IS A HYPOTHESIS, NOT A VERDICT. `suitable_families`
    ranks strategy families by how well the measured character matches what each
    family needs. statergy.txt requires distinguishing HYPOTHESIS from
    STATISTICAL EVIDENCE, so these are explicitly labelled priors for the search
    to test -- they narrow where to look, they never substitute for E26
    validation or the Stage 0 null, and nothing here can promote a strategy.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_PROFILE_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e24_strategy_research"

# E26's own defaults (engines/e26_backtesting/engine.py: commission_pct=0.001,
# slippage_pct=0.0005), charged on entry AND exit -- so a round trip is twice
# their sum. Imported as constants rather than hardcoded numbers so this stays
# honest if E26's cost model changes.
DEFAULT_COMMISSION_PCT = 0.001
DEFAULT_SLIPPAGE_PCT = 0.0005

# Hurst bands. 0.5 is a random walk by construction; the tolerance around it
# marks "indistinguishable from a random walk at this sample size" rather than
# pretending a reading of 0.51 is meaningfully trending.
_HURST_RANDOM_WALK_TOLERANCE = 0.05

# A cost hurdle at or above this fraction of a typical bar's range makes an
# average bar unable to pay for its own round trip. Not a fitted threshold --
# it is arithmetic about whether the median bar covers costs at all.
COST_HURDLE_SEVERE = 0.5
COST_HURDLE_PROHIBITIVE = 1.0

# The score every family is given when its own test fails. A ranking whose
# best entry is at or below this carries no information -- see the
# none_indicated branch in _rank_families.
_NO_SIGNAL_BASELINE = 0.2

# Longest OU half-life still worth calling tradeable mean reversion.
#
# Real defect found 2026-09-15 on the first full 116-profile run: E12's
# `mean_reverting` flag is True whenever the fitted theta is positive -- i.e.
# whenever ANY pull toward the mean exists -- and it came back True on 101 of
# 116 profiles, with half-lives up to 33,138 bars. At daily resolution that is
# roughly 130 years. Treating that boolean as "this instrument mean-reverts"
# scored mean_reversion above trend_following on 61 profiles whose Hurst
# exponent simultaneously said "trending", which is a contradiction the
# ranking presented as a recommendation.
#
# A reversion edge is only harvestable if price returns to the mean well
# within a plausible holding period; at a half-life of several hundred bars
# the decay is far too slow to pay for a round trip. 50 bars is a deliberately
# generous ceiling (a position would typically be held a fraction of one
# half-life) and is a documented convention, not a fitted value.
MAX_TRADEABLE_HALF_LIFE_BARS = 50.0


@dataclass
class InstrumentProfile:
    symbol: str
    timeframe: str
    bars: int
    generated_at: str

    # Character (all from e12_quant_research)
    hurst: Optional[float] = None
    hurst_interpretation: str = ""
    hurst_r_squared: Optional[float] = None
    mean_reverting: bool = False
    half_life_periods: Optional[float] = None
    is_stationary: bool = False

    # Volatility / cost
    annualised_vol_pct: Optional[float] = None
    median_bar_range_pct: Optional[float] = None
    cost_per_round_trip_pct: Optional[float] = None
    cost_atr_ratio: Optional[float] = None
    cost_verdict: str = ""
    vol_clustering: Optional[float] = None

    # Behaviour
    trend_share_pct: Optional[float] = None   # share of bars with ADX > 25
    gap_median_pct: Optional[float] = None
    autocorr_lag1: Optional[float] = None

    suitable_families: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _annualisation_factor(timeframe: str) -> float:
    """Bars per year, for annualising volatility. Crypto trades 24/7; the
    rest do not, so these are approximations and are labelled as such rather
    than presented as exact."""
    per_year = {
        "1m": 525_600, "5m": 105_120, "15m": 35_040, "30m": 17_520,
        "1h": 8_760, "4h": 2_190, "1d": 252, "1wk": 52,
    }
    return float(per_year.get(timeframe, 252))


def _vol_clustering(returns: np.ndarray) -> Optional[float]:
    """Lag-1 autocorrelation of ABSOLUTE returns -- the standard cheap read on
    volatility clustering (big moves follow big moves). Distinct from
    `autocorr_lag1` on signed returns, which measures momentum/mean reversion.
    """
    a = np.abs(returns)
    if len(a) < 30:
        return None
    a = a - a.mean()
    denom = float((a * a).sum())
    if denom == 0:
        return None
    return round(float((a[:-1] * a[1:]).sum() / denom), 4)


def build_profile(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    quant_engine: Optional[Any] = None,
    commission_pct: float = DEFAULT_COMMISSION_PCT,
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
) -> InstrumentProfile:
    """Characterise one (instrument, timeframe) from real OHLCV.

    `df` may be raw OHLCV or an e07-enriched frame; `atr`/`adx` are used when
    present and derived from high/low otherwise, so this works on either
    without requiring the caller to enrich first.
    """
    from project_titan_x.engines.e12_quant_research.engine import QuantResearchEngine

    if quant_engine is None:
        quant_engine = QuantResearchEngine()
        quant_engine.initialize()

    close = df["close"].to_numpy(float)
    profile = InstrumentProfile(
        symbol=symbol, timeframe=timeframe, bars=len(df),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    if len(df) < 100:
        profile.notes.append(f"only {len(df)} bars -- too few for a reliable profile")
        return profile

    returns = np.diff(close) / close[:-1]

    # --- character, delegated to E12 ---
    h = quant_engine.hurst_exponent(close)
    if h.success and h.data is not None:
        profile.hurst = h.data.hurst_exponent
        profile.hurst_r_squared = h.data.r_squared
        # E12's own label, then refined: a reading within tolerance of 0.5 is
        # not meaningfully different from a random walk however confident the
        # fit looks, and saying "trending" there would overstate the evidence.
        if profile.hurst is not None and abs(profile.hurst - 0.5) <= _HURST_RANDOM_WALK_TOLERANCE:
            profile.hurst_interpretation = "indistinguishable from random walk"
        else:
            profile.hurst_interpretation = h.data.interpretation

    hl = quant_engine.half_life_of_mean_reversion(close)
    if hl.success and hl.data is not None:
        profile.mean_reverting = bool(hl.data.mean_reverting)
        profile.half_life_periods = hl.data.half_life_periods

    st = quant_engine.test_stationarity(close)
    if st.success and st.data is not None:
        profile.is_stationary = bool(st.data.is_stationary)

    # --- volatility and the cost hurdle ---
    profile.annualised_vol_pct = round(float(returns.std() * np.sqrt(_annualisation_factor(timeframe)) * 100), 2)
    profile.vol_clustering = _vol_clustering(returns)

    if "atr" in df.columns and df["atr"].notna().any():
        bar_range = (df["atr"] / df["close"]).dropna()
    else:
        bar_range = ((df["high"] - df["low"]) / df["close"]).dropna()
    if len(bar_range):
        profile.median_bar_range_pct = round(float(bar_range.median() * 100), 4)

    round_trip = 2.0 * (commission_pct + slippage_pct) * 100
    profile.cost_per_round_trip_pct = round(round_trip, 4)
    if profile.median_bar_range_pct:
        profile.cost_atr_ratio = round(round_trip / profile.median_bar_range_pct, 3)
        if profile.cost_atr_ratio >= COST_HURDLE_PROHIBITIVE:
            profile.cost_verdict = "prohibitive"
            profile.notes.append(
                f"Costs ({round_trip:.2f}%/round trip) EXCEED the median bar range "
                f"({profile.median_bar_range_pct:.3f}%). The average bar cannot pay for a "
                "trade here; no entry rule fixes this."
            )
        elif profile.cost_atr_ratio >= COST_HURDLE_SEVERE:
            profile.cost_verdict = "severe"
            profile.notes.append(
                f"Costs consume {profile.cost_atr_ratio:.0%} of the median bar range -- only "
                "strategies holding well beyond one bar can overcome this."
            )
        else:
            profile.cost_verdict = "workable"

    # --- behaviour ---
    if "adx" in df.columns and df["adx"].notna().any():
        profile.trend_share_pct = round(float((df["adx"] > 25).mean() * 100), 1)
    if len(returns) > 2:
        r = returns - returns.mean()
        denom = float((r * r).sum())
        profile.autocorr_lag1 = round(float((r[:-1] * r[1:]).sum() / denom), 4) if denom else None
    if "open" in df.columns and len(df) > 1:
        gaps = ((df["open"].to_numpy(float)[1:] - close[:-1]) / close[:-1])
        profile.gap_median_pct = round(float(np.median(np.abs(gaps)) * 100), 4)

    profile.suitable_families = _rank_families(profile)
    return profile


def _rank_families(p: InstrumentProfile) -> list[dict]:
    """Rank strategy families by fit to the measured character.

    HYPOTHESES for the search to test, never conclusions -- each carries the
    measurement that motivated it so a reader can judge the reasoning rather
    than trust a bare score. A family scoring well here has NOT been shown to
    work on this instrument; it has been shown to be worth testing.
    """
    out: list[dict] = []

    def add(name: str, score: float, why: str) -> None:
        out.append({"family": name, "prior_score": round(max(0.0, min(1.0, score)), 3), "rationale": why})

    trending = p.hurst is not None and p.hurst > 0.5 + _HURST_RANDOM_WALK_TOLERANCE

    # Reversion counts only when it is FAST enough to trade -- see
    # MAX_TRADEABLE_HALF_LIFE_BARS for the measured reason this gate exists.
    # A Hurst below the random-walk band is direct evidence of anti-persistence
    # and stands on its own; the OU flag additionally needs a short half-life.
    fast_reversion = (
        p.mean_reverting
        and p.half_life_periods is not None
        and 0 < p.half_life_periods <= MAX_TRADEABLE_HALF_LIFE_BARS
    )
    reverting = (p.hurst is not None and p.hurst < 0.5 - _HURST_RANDOM_WALK_TOLERANCE) or fast_reversion

    if trending:
        add("trend_following", 0.5 + (p.hurst - 0.5), f"Hurst {p.hurst} > 0.5 -- moves persist")
        add("breakout", 0.45 + (p.hurst - 0.5), f"Hurst {p.hurst} favours continuation over reversal")
    else:
        add("trend_following", 0.2, f"Hurst {p.hurst} gives no persistence edge")

    if reverting:
        hl = f", half-life {p.half_life_periods} bars" if p.half_life_periods else ""
        add("mean_reversion", 0.7, f"Hurst {p.hurst} and/or fast OU reversion{hl}")
    elif p.mean_reverting and p.half_life_periods:
        # Distinguish "no reversion" from "reversion too slow to harvest" --
        # they are different findings and the second is the common one here.
        add("mean_reversion", 0.2,
            f"OU reversion exists but half-life {p.half_life_periods:.0f} bars exceeds the "
            f"{MAX_TRADEABLE_HALF_LIFE_BARS:.0f}-bar tradeable ceiling -- too slow to harvest")
    else:
        add("mean_reversion", 0.2, "no measured reversion tendency")

    if p.vol_clustering is not None and p.vol_clustering > 0.1:
        add("volatility_breakout", 0.4 + p.vol_clustering,
            f"volatility clusters (|return| lag-1 autocorr {p.vol_clustering}) -- quiet periods precede expansion")

    if p.trend_share_pct is not None:
        if p.trend_share_pct >= 40:
            add("trend_pullback", 0.6, f"{p.trend_share_pct}% of bars have ADX>25 -- trends are common enough to pull back within")
        elif p.trend_share_pct <= 20:
            add("range_fade", 0.55, f"only {p.trend_share_pct}% of bars trend -- ranging conditions dominate")

    # The cost hurdle overrides character: a family needing many short holds
    # cannot work where a round trip eats the bar, however good the signal.
    if p.cost_verdict == "prohibitive":
        for entry in out:
            entry["prior_score"] = round(entry["prior_score"] * 0.25, 3)
            entry["rationale"] += " [heavily discounted: costs exceed median bar range]"
    elif p.cost_verdict == "severe":
        for entry in out:
            entry["prior_score"] = round(entry["prior_score"] * 0.6, 3)
            entry["rationale"] += " [discounted: high cost hurdle]"

    ranked = sorted(out, key=lambda e: e["prior_score"], reverse=True)

    # When nothing scores above the "no signal" baseline, say so instead of
    # letting sort order surface an arbitrary winner. Every family that fails
    # its test is assigned the same 0.2 baseline, so on an instrument with
    # neither persistence nor reversion the top row was being decided by tie
    # ordering -- which reads as a recommendation when it is the opposite.
    # statergy.txt requires separating HYPOTHESIS from ASSUMPTION; an
    # arbitrary tiebreak presented as a prior is exactly the confusion it
    # forbids.
    if not ranked or ranked[0]["prior_score"] <= _NO_SIGNAL_BASELINE:
        return [{
            "family": "none_indicated",
            "prior_score": 0.0,
            "rationale": (
                f"No family clears the baseline: Hurst {p.hurst} is within "
                f"{_HURST_RANDOM_WALK_TOLERANCE} of a random walk, no reversion measured"
                + (f", and the cost hurdle is {p.cost_verdict}" if p.cost_verdict in ("severe", "prohibitive") else "")
                + ". Searching here is lower-value than on an instrument with measured character."
            ),
        }] + ranked

    return ranked


def save_profiles(profiles: list[InstrumentProfile], path: Optional[Path] = None) -> Path:
    """Persist profiles. Never overwrites previous research: statergy.txt's
    NON-NEGOTIABLE #7 is "NEVER delete failed research results", so each run
    writes a timestamped file alongside a `_latest` pointer rather than
    replacing history."""
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path or (_PROFILE_DIR / f"instrument_profiles_{stamp}.json")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_model": {"commission_pct": DEFAULT_COMMISSION_PCT, "slippage_pct": DEFAULT_SLIPPAGE_PCT},
        "profiles": [p.to_dict() for p in profiles],
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (_PROFILE_DIR / "instrument_profiles_latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target
