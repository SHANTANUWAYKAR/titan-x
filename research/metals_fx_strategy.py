"""
Module: metals_fx_strategy.py
Description: STRATEGY LOGIC ONLY for the London-Sweep Continuation model on
    Gold, Silver and major FX. Backtesting, validation and reporting live
    in metals_fx_backtest.py -- this module holds no measurement code.

    THESIS (approved 2026-08-25). The edge claimed is not "sweeps work".
    It is narrower: resting stop orders cluster at the previous day's
    high/low and the Asian-range extremes, and the London open is the
    first moment each day with enough volume to fill them. When London
    opens INTO that cluster, the fill itself produces a temporary,
    non-informational move -- an order-flow event, not a chart pattern.
    The trade fades that move once it fails to hold, then rides the
    genuine flow behind it.

    Two things make this specific to these instruments rather than generic
    TA. Metals and FX have a hard session structure crypto lacks, so
    "where the stops are" and "when they can be filled" are separable and
    knowable. And gold's DIRECTION is macro-driven (DXY, real yields,
    safe-haven flow), so the sweep supplies TIMING only -- the
    higher-timeframe trend has to supply direction. That is why the HTF
    bias gate is mandatory here and not an optional filter.

    DESIGN CONSTRAINT FROM THIS PROJECT'S OWN EVIDENCE. A prior ablation
    over 23 filter tests on three markets found that stacking ICT/SMC
    confluence SUBTRACTED expectancy in 22 of 23 cases -- each added
    condition narrowed the sample without improving it. This model is
    therefore deliberately thin: HTF bias, sweep, structure shift, session
    gate. Nothing else is added unless it earns its place in an ablation.

    REUSE, NOT DUPLICATION. Session windows come from
    e07_technical.killzones; displacement/MSS/PDH-PDL from
    research.ict_concepts. No detection logic is reimplemented here.

    RESEARCH CODE -- outside engines/, nothing live imports it.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.killzones import Killzone, killzone_mask
from project_titan_x.research.ict_concepts import (
    displacement,
    market_structure_shift,
    period_levels,
)


# ---------------------------------------------------------------------------
# INSTRUMENT-SPECIFIC PARAMETERS
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InstrumentParams:
    """Per-instrument settings. These are NOT shared -- that is the point.

    stop_atr / target_atr differ because the instruments genuinely differ:
      GOLD   ~1.0-1.5% daily range, deep book, cleanest ICT behaviour.
      SILVER 2-3x gold's volatility on a thinner book, so the same
             multiplier that survives on gold gets run on silver. Its stop
             is deliberately WIDER in ATR terms and its size smaller.
      FX     far tighter ranges; USDJPY is separated from EUR/GBP because
             it is the carry pair -- it trends on rate differentials and
             behaves differently around the Tokyo fix, so a London-centric
             model has a weaker prior on it.

    max_risk_pct is per-instrument for the same reason: silver's thinner
    liquidity means slippage on exit is worse than its ATR suggests.
    """

    symbol: str
    stop_atr: float                # stop distance, in ATR
    target_atr: float              # first target, in ATR
    max_risk_pct: float            # % of capital risked per trade
    sessions: tuple[Killzone, ...] # which killzones may trade
    min_atr_pct: float = 0.0       # skip dead-volatility bars
    correlation_group: str = ""    # for stacked-exposure detection


# Shared across every instrument (documented as shared, per the spec).
SHARED = {
    "htf_ema": 200,          # higher-timeframe bias filter
    "sweep_lookback": 1,     # previous DAY's levels
    "max_bars_to_entry": 8,  # sweep -> structure shift must be prompt
    "displacement_atr": 1.2, # what counts as an impulsive move
}

INSTRUMENTS: dict[str, InstrumentParams] = {
    # --- METALS ---
    "GOLD": InstrumentParams(
        symbol="GOLD", stop_atr=1.5, target_atr=4.5, max_risk_pct=1.0,
        sessions=(Killzone.LONDON_OPEN, Killzone.NY_OPEN),
        min_atr_pct=0.05, correlation_group="metals",
    ),
    "SILVER": InstrumentParams(
        # Wider stop and HALF the risk: 2-3x gold's volatility on a thinner
        # book. Sharing gold's numbers here is the single most likely way
        # to lose money on a "metals" strategy.
        symbol="SILVER", stop_atr=2.2, target_atr=5.5, max_risk_pct=0.5,
        sessions=(Killzone.LONDON_OPEN, Killzone.NY_OPEN),
        min_atr_pct=0.10, correlation_group="metals",
    ),
    # --- FX MAJORS ---
    "EURUSD": InstrumentParams(
        symbol="EURUSD", stop_atr=1.2, target_atr=3.0, max_risk_pct=1.0,
        sessions=(Killzone.LONDON_OPEN, Killzone.NY_OPEN),
        min_atr_pct=0.02, correlation_group="eur_block",
    ),
    "GBPUSD": InstrumentParams(
        # Wider than EUR: cable's London-open range is structurally larger.
        symbol="GBPUSD", stop_atr=1.4, target_atr=3.5, max_risk_pct=0.8,
        sessions=(Killzone.LONDON_OPEN, Killzone.NY_OPEN),
        min_atr_pct=0.02, correlation_group="eur_block",
    ),
    "USDJPY": InstrumentParams(
        # The carry pair. Own group -- it is NOT a EUR-block proxy, and
        # NY_OPEN only, since its London behaviour is the weakest case for
        # this model.
        symbol="USDJPY", stop_atr=1.3, target_atr=3.2, max_risk_pct=0.8,
        sessions=(Killzone.NY_OPEN,),
        min_atr_pct=0.02, correlation_group="jpy_block",
    ),
}

# Instruments inside a group move together often enough that holding both
# is closer to one double-sized trade than two independent ones. The risk
# guard is told about this rather than left to discover it.
CORRELATION_GROUPS = {
    "metals": ("GOLD", "SILVER"),      # historically ~0.75-0.85 correlated
    "eur_block": ("EURUSD", "GBPUSD"), # both short-USD expressions
    "jpy_block": ("USDJPY",),
}


# ---------------------------------------------------------------------------
# SIGNAL
# ---------------------------------------------------------------------------
def london_sweep_continuation(
    enriched: pd.DataFrame,
    params: InstrumentParams,
    htf_ema: int = SHARED["htf_ema"],
    max_bars_to_entry: int = SHARED["max_bars_to_entry"],
    displacement_atr: float = SHARED["displacement_atr"],
    stop_atr: Optional[float] = None,
    target_atr: Optional[float] = None,
) -> pd.Series:
    """+1 long / -1 short / 0 flat.

    Sequence, in order:
      1. SESSION   bar sits inside one of this instrument's allowed
                   killzones. Outside them the fills that create the edge
                   do not happen, so nothing trades.
      2. SWEEP     price takes out the PREVIOUS DAY's high or low and
                   closes back inside -- the stop cluster being filled.
      3. SHIFT     within `max_bars_to_entry`, a displacement-confirmed
                   market structure shift shows the OPPOSITE direction.
                   A CHoCH alone is not enough: without displacement the
                   break is the kind that fails.
      4. BIAS      the trade must agree with the HTF EMA. Gold's direction
                   is macro-driven, so this gate supplies what the sweep
                   cannot.
      5. VOLATILITY ATR must exceed min_atr_pct -- a dead-range sweep is
                   noise, and its stop is too tight to survive.

    Exit is an ATR stop/target, both instrument-specific. No trailing:
    fixing the exit keeps the R-multiple comparable across instruments,
    which is what per-instrument reporting requires.

    Strictly causal -- every input is prior-bar or current-bar only.
    """
    n = len(enriched)
    if n < htf_ema + 50:
        return pd.Series(0, index=enriched.index, dtype=int)

    s_atr = params.stop_atr if stop_atr is None else stop_atr
    t_atr = params.target_atr if target_atr is None else target_atr

    close = enriched["close"]
    atr = enriched["atr"] if "atr" in enriched else (enriched["high"] - enriched["low"]).rolling(14).mean()
    ema = close.ewm(span=htf_ema, adjust=False).mean()

    # 1. session gate -- union of this instrument's allowed killzones
    if "timestamp" in enriched.columns:
        allowed = np.zeros(n, dtype=bool)
        for kz in params.sessions:
            allowed |= killzone_mask(enriched, kz).to_numpy(dtype=bool)
    else:
        allowed = np.ones(n, dtype=bool)

    # 2. previous-day sweep
    lv = period_levels(enriched, "D")
    prev_high = lv["prev_high"].to_numpy(float)
    prev_low = lv["prev_low"].to_numpy(float)

    # 3. displacement-confirmed structure shift
    mss = market_structure_shift(enriched, atr_mult=displacement_atr).to_numpy()

    h = enriched["high"].to_numpy(float)
    l = enriched["low"].to_numpy(float)
    c = close.to_numpy(float)
    a = atr.to_numpy(float)
    e = ema.to_numpy(float)

    out = np.zeros(n, dtype=np.int8)
    position = 0
    stop = target = 0.0
    swept_dir = 0          # +1 = low swept (long bias), -1 = high swept
    swept_at = -10_000

    for i in range(n):
        # ---- manage an open position first ----
        if position != 0:
            if position == 1 and (l[i] <= stop or h[i] >= target):
                position = 0
            elif position == -1 and (h[i] >= stop or l[i] <= target):
                position = 0
            out[i] = position
            if position != 0:
                continue

        if np.isnan(a[i]) or a[i] <= 0:
            continue
        # 5. volatility floor, expressed relative to price so it is
        # comparable across a $4,600 instrument and a 1.08 one
        if (a[i] / c[i] * 100.0) < params.min_atr_pct:
            continue

        # 2. record a sweep (wick through, close back inside)
        if not np.isnan(prev_low[i]) and l[i] < prev_low[i] <= c[i]:
            swept_dir, swept_at = 1, i
        elif not np.isnan(prev_high[i]) and h[i] > prev_high[i] >= c[i]:
            swept_dir, swept_at = -1, i

        if swept_dir == 0 or i - swept_at > max_bars_to_entry:
            continue
        if not allowed[i]:          # 1. session gate
            continue
        if mss[i] != swept_dir:     # 3. structure shift must confirm the sweep
            continue
        # 4. HTF bias must agree
        if swept_dir == 1 and not c[i] > e[i]:
            continue
        if swept_dir == -1 and not c[i] < e[i]:
            continue

        position = swept_dir
        if position == 1:
            stop, target = c[i] - s_atr * a[i], c[i] + t_atr * a[i]
        else:
            stop, target = c[i] + s_atr * a[i], c[i] - t_atr * a[i]
        swept_dir = 0               # consume the sweep
        out[i] = position

    return pd.Series(out, index=enriched.index, dtype=int)


# ---------------------------------------------------------------------------
# CONFLUENCE SCORE (0-100, matching the platform's existing scale)
# ---------------------------------------------------------------------------
def confluence_score(enriched: pd.DataFrame, params: InstrumentParams) -> pd.Series:
    """0-100 conviction, on the same scale e51_signals already uses.

    Weights are stated, not tuned: 40 for the structure shift (the ablation
    showed structure is the only component with consistent standalone
    edge), 25 for the sweep, 20 for HTF agreement, 15 for session. They sum
    to 100 by construction. Deliberately NOT fitted to returns -- a scoring
    function optimised on the same data it is scored against is just
    another overfit parameter.
    """
    n = len(enriched)
    close = enriched["close"]
    atr = enriched["atr"] if "atr" in enriched else (enriched["high"] - enriched["low"]).rolling(14).mean()
    ema = close.ewm(span=SHARED["htf_ema"], adjust=False).mean()

    score = np.zeros(n, dtype=float)
    mss = market_structure_shift(enriched, atr_mult=SHARED["displacement_atr"]).to_numpy()
    score += (mss != 0) * 40.0

    lv = period_levels(enriched, "D")
    swept = ((enriched["low"] < lv["prev_low"]) & (close > lv["prev_low"])) | \
            ((enriched["high"] > lv["prev_high"]) & (close < lv["prev_high"]))
    score += swept.fillna(False).to_numpy() * 25.0

    aligned = ((mss == 1) & (close > ema).to_numpy()) | ((mss == -1) & (close < ema).to_numpy())
    score += aligned * 20.0

    if "timestamp" in enriched.columns:
        allowed = np.zeros(n, dtype=bool)
        for kz in params.sessions:
            allowed |= killzone_mask(enriched, kz).to_numpy(dtype=bool)
        score += allowed * 15.0

    return pd.Series(np.clip(score, 0, 100), index=enriched.index)


def correlated_exposure(open_symbols: list[str]) -> list[tuple[str, tuple[str, ...]]]:
    """Report which open positions are effectively the same trade.

    Returned for the risk guard to consume rather than acted on here --
    holding GOLD and SILVER simultaneously is closer to one double-sized
    metals position than two independent trades, and portfolio heat that
    counts them separately understates real exposure.
    """
    hits = []
    for group, members in CORRELATION_GROUPS.items():
        overlap = tuple(s for s in members if s in open_symbols)
        if len(overlap) > 1:
            hits.append((group, overlap))
    return hits
