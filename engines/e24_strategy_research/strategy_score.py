"""
Module: strategy_score.py
Description: PHASES 11 and 19 of reports/statergy.txt -- a composite A+ strategy
    score with strict grades, and the leaderboard that ranks every candidate the
    project has ever backtested.

    WHY A COMPOSITE SCORE. statergy.txt PHASE 11: "Do NOT make the score depend
    only on profit... A strategy cannot receive A+ merely because it makes large
    profits." This project already computes every ingredient (E26 metrics, Stage 0
    null percentiles, deflated Sharpe, PBO) but had nowhere that combined them
    into one ranked decision -- confirmed by grep: no `leaderboard`, no
    `a_plus_score`, nothing. So the evidence existed and was unreadable.

    TWO DELIBERATE DEVIATIONS FROM THE PROMPT'S SUGGESTED WEIGHTS, both because
    the data to support them honestly does not exist:

    1. Regime diversification (5% suggested) is NOT scored. Per-candidate regime
       attribution is not recorded in any sweep report -- awarding 5% on an
       unmeasured axis would be inventing precision. Its weight is redistributed
       and the omission is reported on every row rather than hidden.

    2. Robustness (15%) is computed from PARAMETER-NEIGHBOURHOOD DISPERSION, not
       from E26's `robustness` field. That field is `_parameter_sensitivity`,
       which perturbs risk_pct/commission -- and as E26's own docstring states,
       "strategy_fn's output depends only on df, never on risk_pct/commission/
       slippage". It measures sizing/cost sensitivity, which is a real thing but
       is NOT what PHASE 8 asks for ("Slightly change parameters. EMA 50 ->
       45/48/50/52/55. If performance collapses from tiny parameter changes, flag
       the strategy as fragile"). Real parameter robustness is computable from
       data already on disk: a sweep tests many parameter sets of the same
       strategy on the same instrument, so the DISPERSION of selection score
       across those siblings is exactly the requested measurement.

    THE A+ GATE IS HARD, NOT A HIGH SCORE. A candidate cannot be graded A+ on
    composite score alone. It must additionally clear every gate in
    `_APLUS_GATES` -- including a Stage 0 null percentile. A strategy that has
    never been scored against the synthetic no-edge null is capped at B
    regardless of how good its backtest looks, because this project has direct
    measured evidence (137/150 noise paths clearing the legacy bar at 4h) that
    backtest metrics alone do not distinguish edge from noise.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)

# PHASE 11's suggested weighting, with regime diversification's 5% redistributed
# (see module docstring) proportionally across the axes that ARE measurable.
WEIGHTS: dict[str, float] = {
    "oos_strength": 0.263,        # 25% suggested
    "risk_adjusted": 0.211,       # 20%
    "drawdown_quality": 0.158,    # 15%
    "robustness": 0.158,          # 15%
    "consistency": 0.105,         # 10%
    "execution_realism": 0.053,   # 5%
    "simplicity": 0.052,          # 5%
}

# Normalisation anchors. Deliberately fixed conventions, not fitted to this
# book -- fitting the scale to the candidates being scored would let a weak
# field grade itself generously.
_SHARPE_FULL_CREDIT = 2.0     # OOS Sharpe at/above this scores 1.0
_MAX_DD_BUDGET_PCT = 25.0     # E26's own max-drawdown bar
_MIN_TRADES_FULL_CREDIT = 100
_SIMPLICITY_FULL_CREDIT = 0   # zero free parameters
_SIMPLICITY_ZERO_CREDIT = 6

# Hard gates for A+ / S. Every one must pass; the composite score alone is
# never sufficient.
_APLUS_GATES = {
    "min_oos_sharpe": 0.5,
    "min_expectancy": 0.0,        # strictly positive
    "max_drawdown_pct": 25.0,
    "min_trades": 60,             # Stage 0's own floor
    "min_null_percentile": 95.0,  # must have been scored against the null AND cleared it
    "min_robustness": 0.4,
    # Deflated Sharpe: the probability the edge survives the SEARCH that found
    # it. See deflated_sharpe.py -- at this project's own grid size the Sharpe
    # a zero-edge strategy reaches by luck is ~1.01, while min_oos_sharpe above
    # asks for 0.5. Without this gate the A+ bar sits a factor of two below the
    # noise floor, which is the arithmetic behind this project's own measured
    # 137-of-150 noise pass rate. 0.95 is the paper's conventional bar.
    "min_dsr": 0.95,
}

# Below this many trades a backtest carries too little information for any
# grade above C, whatever its composite score. Half of _APLUS_GATES'
# min_trades: deliberately looser than A+ demands, because this is a floor on
# "is there a sample at all", not on "is this good".
_MIN_TRADES_FOR_GRADE = 30

GRADES = ("S", "A+", "A", "B", "C", "D", "F")


@dataclass
class ScoredStrategy:
    strategy: str
    symbol: str
    timeframe: str
    params: dict = field(default_factory=dict)

    # raw metrics (copied, never recomputed)
    trades: Optional[int] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    expectancy: Optional[float] = None
    is_sharpe: Optional[float] = None
    oos_sharpe: Optional[float] = None
    selection_score: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    null_percentile: Optional[float] = None
    dsr: Optional[float] = None

    # computed components
    components: dict = field(default_factory=dict)
    param_robustness: Optional[float] = None
    overfitting_risk: str = "unknown"
    a_plus_score: float = 0.0
    grade: str = "F"
    status: str = "RESEARCH"
    gate_failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def parameter_robustness(candidate: dict, siblings: list[dict]) -> Optional[float]:
    """Dispersion of selection score across parameter siblings of the SAME
    strategy on the SAME instrument/timeframe -- PHASE 8's "slightly change
    parameters" test, computed from sweep data already on disk.

    Returns 1.0 when siblings perform uniformly (a plateau -- robust) and falls
    toward 0 as their spread widens relative to the candidate's own score (a
    spike -- fragile). None when a strategy has too few parameter sets to say
    anything, which is honest rather than defaulting to a flattering number.
    """
    scores = [_selection(s) for s in siblings]
    scores = [s for s in scores if s is not None]
    if len(scores) < 3:
        return None
    own = _selection(candidate)
    if own is None:
        return None
    mean = sum(scores) / len(scores)
    var = sum((s - mean) ** 2 for s in scores) / len(scores)
    sd = math.sqrt(var)
    scale = max(abs(own), 0.25)      # floor stops a near-zero score inflating the ratio
    return round(_clamp(1.0 - (sd / scale)), 4)


def _selection(c: dict) -> Optional[float]:
    """min(IS, OOS) -- this project's own selection score, not a new one."""
    a, b = c.get("is_sharpe"), c.get("oos_sharpe")
    if a is None or b is None:
        return None
    return min(float(a), float(b))


def score_candidate(
    candidate: dict,
    symbol: str,
    timeframe: str,
    siblings: Optional[list[dict]] = None,
    null_percentile: Optional[float] = None,
    dsr: Optional[float] = None,
    cost_verdict: Optional[str] = None,
) -> ScoredStrategy:
    """Score one backtested candidate. Copies metrics; never recomputes them."""
    s = ScoredStrategy(
        strategy=str(candidate.get("strategy", "?")), symbol=symbol, timeframe=timeframe,
        params=candidate.get("params") or {},
        trades=candidate.get("is_trades"), win_rate=candidate.get("win_rate"),
        profit_factor=candidate.get("profit_factor"), expectancy=candidate.get("expectancy"),
        is_sharpe=candidate.get("is_sharpe"), oos_sharpe=candidate.get("oos_sharpe"),
        max_drawdown_pct=candidate.get("is_max_dd"),
        null_percentile=null_percentile, dsr=dsr,
    )
    s.selection_score = _selection(candidate)
    s.param_robustness = parameter_robustness(candidate, siblings or [])

    oos = float(s.oos_sharpe) if s.oos_sharpe is not None else 0.0
    sel = float(s.selection_score) if s.selection_score is not None else 0.0
    dd = abs(float(s.max_drawdown_pct)) if s.max_drawdown_pct is not None else _MAX_DD_BUDGET_PCT

    comp: dict[str, float] = {}
    comp["oos_strength"] = _clamp(oos / _SHARPE_FULL_CREDIT)
    comp["risk_adjusted"] = _clamp(sel / _SHARPE_FULL_CREDIT)
    comp["drawdown_quality"] = _clamp(1.0 - dd / _MAX_DD_BUDGET_PCT)

    if s.param_robustness is None:
        # Not measurable for this strategy (too few parameter sets). Scoring it
        # as 0 would punish single-parameter archetypes for a property of the
        # grid rather than of the strategy; scoring it as 1 would reward them.
        # Use the neutral midpoint and say so on the row.
        comp["robustness"] = 0.5
        s.notes.append("parameter robustness not measurable (<3 sibling parameter sets) -- scored neutral")
    else:
        comp["robustness"] = s.param_robustness

    if s.is_sharpe is not None and s.oos_sharpe is not None:
        denom = max(abs(float(s.is_sharpe)), abs(float(s.oos_sharpe)), 1e-9)
        comp["consistency"] = _clamp(1.0 - abs(float(s.is_sharpe) - float(s.oos_sharpe)) / denom)
    else:
        comp["consistency"] = 0.0

    trades = int(s.trades or 0)
    realism = _clamp(trades / _MIN_TRADES_FULL_CREDIT)
    if cost_verdict == "prohibitive":
        realism *= 0.2
        s.notes.append("instrument/timeframe cost hurdle is prohibitive -- execution realism heavily discounted")
    elif cost_verdict == "severe":
        realism *= 0.6
        s.notes.append("instrument/timeframe cost hurdle is severe -- execution realism discounted")
    comp["execution_realism"] = realism

    n_params = len(s.params or {})
    comp["simplicity"] = _clamp(
        1.0 - (n_params - _SIMPLICITY_FULL_CREDIT) / max(_SIMPLICITY_ZERO_CREDIT - _SIMPLICITY_FULL_CREDIT, 1)
    )

    s.components = {k: round(v, 4) for k, v in comp.items()}
    s.a_plus_score = round(sum(WEIGHTS[k] * comp[k] for k in WEIGHTS), 4)
    s.overfitting_risk = _overfitting_risk(s)
    s.grade, s.gate_failures = _grade(s)
    s.status = _status(s)
    s.notes.append("regime diversification not scored -- per-candidate regime attribution is not recorded")
    return s


def _overfitting_risk(s: ScoredStrategy) -> str:
    """PHASE 9. Combines IS->OOS decay, the null percentile when available, and
    parameter fragility. 'unknown' is a real answer when the null has not been
    run -- it is not the same as 'low'."""
    if s.null_percentile is None:
        return "unknown (never scored against the null)"
    decay = None
    if s.is_sharpe is not None and s.oos_sharpe is not None and abs(float(s.is_sharpe)) > 1e-9:
        decay = (float(s.is_sharpe) - float(s.oos_sharpe)) / abs(float(s.is_sharpe))
    flags = 0
    if s.null_percentile < 95:
        flags += 2
    if decay is not None and decay > 0.5:
        flags += 1
    if s.param_robustness is not None and s.param_robustness < 0.4:
        flags += 1
    if (s.trades or 0) < 60:
        flags += 1
    return {0: "low", 1: "moderate", 2: "elevated"}.get(flags, "high")


def _grade(s: ScoredStrategy) -> tuple[str, list[str]]:
    """Grade with HARD gates. Composite score alone never earns A+."""
    fails: list[str] = []
    g = _APLUS_GATES
    if (s.oos_sharpe or 0) < g["min_oos_sharpe"]:
        fails.append(f"OOS Sharpe {s.oos_sharpe} < {g['min_oos_sharpe']}")
    if (s.expectancy or 0) <= g["min_expectancy"]:
        fails.append(f"expectancy {s.expectancy} not positive")
    if abs(s.max_drawdown_pct or 99) > g["max_drawdown_pct"]:
        fails.append(f"max drawdown {s.max_drawdown_pct}% > {g['max_drawdown_pct']}%")
    if (s.trades or 0) < g["min_trades"]:
        fails.append(f"{s.trades} trades < {g['min_trades']}")
    if s.null_percentile is None:
        fails.append("never scored against the synthetic null")
    elif s.null_percentile < g["min_null_percentile"]:
        fails.append(f"null percentile {s.null_percentile} < {g['min_null_percentile']}")
    if s.param_robustness is not None and s.param_robustness < g["min_robustness"]:
        fails.append(f"parameter robustness {s.param_robustness} < {g['min_robustness']}")
    # Deflated Sharpe is only a gate where it could be COMPUTED. A missing dsr
    # means the sweep did not record the trial count or bar count this needs,
    # which is a gap in the evidence, not a pass -- so it is reported as its
    # own failure rather than waved through.
    if s.dsr is None:
        fails.append("deflated Sharpe not computable (sweep recorded no trial/bar count)")
    elif s.dsr < g["min_dsr"]:
        fails.append(f"deflated Sharpe {s.dsr:.3f} < {g['min_dsr']} -- not separable from the best of its own search")

    if not fails:
        return ("S" if s.a_plus_score >= 0.80 else "A+"), fails

    # Gates failed -> capped below A+, ranked by composite score, BUT two caps
    # bind before the score is consulted. Both were already stated in this
    # module's docstring and printed on the leaderboard; neither was enforced
    # here, which is how 2,906 candidates carrying `Null%ile --` reached A.
    #
    # Cap 1 -- no null percentile => B. The docstring's own words: "A strategy
    # that has never been scored against the synthetic no-edge null is capped
    # at B regardless of how good its backtest looks, because this project has
    # direct measured evidence (137/150 noise paths clearing the legacy bar at
    # 4h) that backtest metrics alone do not distinguish edge from noise."
    #
    # Cap 2 -- too few trades => C. `execution_realism` is the only component
    # that can see sample size and it carries 5.3% of the composite, so a
    # 2-trade fluke on TCS 15m scored 0.9095 and graded A on 1.000
    # oos_strength (Sharpe clamped down from 12.61), 1.000 risk_adjusted,
    # 1.000 drawdown_quality and 0.971 consistency. Nothing in the composite
    # can tell that the sample carries no information, so the grade must.
    _cap = None
    if s.null_percentile is None:
        _cap = "B"
    if (s.trades or 0) < _MIN_TRADES_FOR_GRADE:
        _cap = "C"

    if s.a_plus_score >= 0.65:
        return (_cap or "A"), fails
    if s.a_plus_score >= 0.50:
        return ("C" if _cap == "C" else "B"), fails
    if s.a_plus_score >= 0.35:
        return "C", fails
    if s.a_plus_score >= 0.20:
        return "D", fails
    return "F", fails


def _status(s: ScoredStrategy) -> str:
    """PHASE 19's status vocabulary."""
    if s.grade in ("S", "A+"):
        return "A+"
    if s.overfitting_risk.startswith("high"):
        return "OVERFIT"
    if s.param_robustness is not None and s.param_robustness < 0.3:
        return "FRAGILE"
    if s.grade in ("D", "F"):
        return "REJECTED"
    if s.null_percentile is not None:
        return "VALIDATION"
    return "BACKTESTING"
