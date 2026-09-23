"""
Module: hypothesis.py
Description: Explicit, queryable strategy hypotheses — `reports/upgrade
    statergy.txt` PHASE 7 ("Every strategy requires an explicit hypothesis"),
    PHASE 36 (retirement on a broken hypothesis) and PHASE 37 (research
    report), raised as **P1.2** in docs/INSTITUTIONAL_AUDIT.md.

    THE GAP, STATED PRECISELY. This project does not lack hypotheses — it
    lacks queryable ones. `plugins/dual_thrust.py` opens with a genuinely good
    account of why a close-bounded range beats a high-low Donchian, and
    `strategies.py::mss_trend_hold` explains why a sparse structural event
    needs a hold window to be tradeable at all. Both are prose in a docstring.
    Nothing can ask "which live strategies have no stated failure condition",
    and nothing can act on the answer.

    WHY THE FAILURE CONDITION IS THE FIELD THAT MATTERS. PHASE 7 asks for four
    things; the one that does real work is WHEN IT SHOULD FAIL. A strategy
    with no stated failure condition cannot be retired for cause — PHASE 36's
    "broken market hypothesis" is unusable against it — so the only available
    retirement trigger is a drawdown, which fires long after the reason did.
    `fails_when` is therefore required, not optional, and `record()` refuses a
    hypothesis without one.

    THESE ARE NOT EVIDENCE. A hypothesis is a claim about why an edge should
    exist. It is not a backtest, not a null percentile, and emphatically not a
    reason to deploy: non-negotiable 19 ("do not use complexity as a substitute
    for evidence") and the file's closing instruction ("IF SOMETHING CANNOT BE
    PROVEN WITH DATA, LABEL IT AS A HYPOTHESIS") both point the same way.
    Nothing in this module can promote a strategy or alter a Stage 0 tag. Its
    only power is to report absence.

    NOTHING IS INVENTED. Hypotheses are transcribed from what a strategy's own
    code and docstring actually claim, with the source cited per entry. Writing
    plausible-sounding rationales for 228 grid strategies would manufacture
    exactly the appearance of rigour this file exists to prevent, so coverage
    is deliberately partial and `coverage_report()` states the gap as a number
    rather than hiding it.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = _ROOT / "data" / "models" / "e24_strategy_research" / "hypotheses.json"

# Families a hypothesis can claim. Free-form would make the registry
# unqueryable, which is the whole complaint being fixed.
FAMILIES = (
    "trend_following", "mean_reversion", "breakout", "momentum",
    "statistical_arbitrage", "volatility", "event_driven", "microstructure",
    "cross_asset", "seasonality", "other",
)


class HypothesisError(ValueError):
    """A hypothesis was rejected as incomplete."""


@dataclass
class StrategyHypothesis:
    """PHASE 7's required fields, plus provenance for the claim itself."""

    strategy: str
    family: str
    works_because: str       # WHY IT SHOULD WORK
    works_when: str          # WHEN IT SHOULD WORK
    fails_when: str          # WHEN IT SHOULD FAIL -- required; see module docstring
    expected_edge: str       # what form the edge takes (not a number unless measured)
    regime: str = ""
    cost_assumptions: str = ""
    risk_model: str = ""
    source: str = ""         # where this claim was transcribed FROM
    recorded_at: str = ""
    notes: list = field(default_factory=list)

    def missing_fields(self) -> list[str]:
        required = ("strategy", "family", "works_because", "works_when",
                    "fails_when", "expected_edge")
        return [f for f in required if not str(getattr(self, f, "") or "").strip()]


def load(path: Path | None = None) -> dict[str, StrategyHypothesis]:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("hypothesis: unreadable registry at %s (%s)", p, e)
        return {}
    out: dict[str, StrategyHypothesis] = {}
    fields = set(StrategyHypothesis.__dataclass_fields__)
    for name, doc in (raw.get("hypotheses") or {}).items():
        try:
            out[name] = StrategyHypothesis(**{**{k: v for k, v in doc.items() if k in fields},
                                              "strategy": name})
        except TypeError:
            logger.warning("hypothesis: skipping unreadable entry %r", name)
    return out


def record(h: StrategyHypothesis, path: Path | None = None) -> StrategyHypothesis:
    """Add or replace one strategy's hypothesis.

    Replacement IS allowed here, unlike the experiment log: a hypothesis is a
    current claim about the world, and revising it when the world turns out
    differently is the correct behaviour rather than a loss of history. What
    must not be lost is the EVIDENCE, and that lives in the append-only
    experiment log and sweep reports, not here.
    """
    missing = h.missing_fields()
    if missing:
        raise HypothesisError(
            f"{h.strategy or '<unnamed>'}: hypothesis is missing {missing}. "
            f"`fails_when` in particular is required -- a strategy with no stated failure "
            f"condition cannot be retired for cause (PHASE 36), leaving drawdown as the only "
            f"trigger, which fires long after the reason did."
        )
    if h.family not in FAMILIES:
        raise HypothesisError(f"{h.strategy}: unknown family {h.family!r}; known: {list(FAMILIES)}")

    p = Path(path) if path else DEFAULT_PATH
    existing = load(p)
    h.recorded_at = h.recorded_at or datetime.now(timezone.utc).isoformat()
    existing[h.strategy] = h

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hypotheses": {n: {k: v for k, v in asdict(x).items() if k != "strategy"}
                       for n, x in sorted(existing.items())},
    }, indent=2), encoding="utf-8")
    return h


def get(strategy: str, path: Path | None = None) -> Optional[StrategyHypothesis]:
    return load(path).get(strategy)


def coverage_report(
    known_strategies: list[str],
    live_strategies: Optional[list[str]] = None,
    path: Path | None = None,
) -> dict:
    """Which strategies have a stated hypothesis and which do not.

    `live_strategies` is reported separately and is the number that matters: a
    strategy driving real money with no stated failure condition is a different
    problem from one sitting unused in a 228-entry search grid.
    """
    have = load(path)
    known = sorted(set(known_strategies))
    live = sorted(set(live_strategies or []))
    missing = [s for s in known if s not in have]
    live_missing = [s for s in live if s not in have]
    return {
        "known": len(known),
        "with_hypothesis": len([s for s in known if s in have]),
        "missing": missing,
        "coverage_pct": round(100 * (len(known) - len(missing)) / len(known), 1) if known else 0.0,
        "live": len(live),
        "live_with_hypothesis": len(live) - len(live_missing),
        "live_missing": live_missing,
        "verdict": (
            "every live strategy states why it should work and when it should fail"
            if live and not live_missing else
            f"{len(live_missing)} LIVE strategy/strategies have no stated hypothesis"
            if live_missing else
            "no live strategies to check"
        ),
    }


# --------------------------------------------------------------------------
# Seed entries for the strategies currently driving live signals.
#
# Transcribed from each strategy's own code and docstring, with the source
# cited. Nothing here is inferred from performance: a hypothesis justified by
# its own backtest is circular, and this project has already measured what
# backtest-justified selection produces (noise clears the legacy bar 137 times
# in 150 at 4h).
# --------------------------------------------------------------------------

SEED_HYPOTHESES = [
    StrategyHypothesis(
        strategy="dual_thrust",
        family="breakout",
        works_because=(
            "Builds its trigger range from highs against CLOSES rather than highs against "
            "lows: range = max(HH(n) - LC(n), HC(n) - LL(n)). A single spike wick inflates a "
            "high-low range and widens a Donchian channel for the whole lookback; mixing "
            "highs against closes bounds that, so the threshold reflects where price actually "
            "settled rather than where it was briefly printed. k1 and k2 are separate, "
            "letting the long and short triggers sit at different distances from the open, "
            "which is the strategy's own idea rather than a symmetry assumption."
        ),
        works_when=(
            "Markets that trend after leaving a settled range, on timeframes where a bar's "
            "typical movement comfortably exceeds round-trip cost. Crypto daily qualifies on "
            "the cost test; 15m does not for any instrument in this platform "
            "(instrument_profile.py measured 0 of 29 cost-viable there)."
        ),
        fails_when=(
            "Choppy ranges that repeatedly cross the threshold without following through -- "
            "each crossing pays the full round trip. Also when volatility collapses so the "
            "computed range shrinks below the cost hurdle, making every breakout trigger "
            "unprofitable regardless of direction accuracy."
        ),
        expected_edge=(
            "Asymmetric payoff from occasional sustained moves, not hit rate. The live "
            "BTC-USD 1d configuration plans roughly 2:1 reward:risk, where breakeven is a "
            "33.3% win rate -- its 52.5% backtest claim is significant against THAT baseline "
            "(p=0.0003) and indistinguishable from a coin flip against 50% (p=0.37)."
        ),
        regime="Trending / expansion; degrades in compression.",
        cost_assumptions="E26 defaults: 0.1% commission + 0.05% slippage per side, 0.30% round trip.",
        risk_model="ATR-derived stop with a fixed reward:risk target; sized by e45_risk.",
        source="engines/e24_strategy_research/plugins/dual_thrust.py module docstring and implementation.",
        notes=[
            "Ported from je-suis-tm/quant-trading (Apache-2.0), logic rewritten not copied.",
            "Parameter PLATEAU was checked, not a single point: all 16 combinations of "
            "lookback 4-10 x k 0.5-0.8 gave positive expectancy on ETHUSD 1d.",
            "LIVE on BTC-USD 1d with {'lookback': 10, 'k1': 0.5, 'k2': 0.5}.",
        ],
    ),
    StrategyHypothesis(
        strategy="mss_trend_hold",
        family="trend_following",
        works_because=(
            "Trades e07_technical.smart_money.market_structure_shift's +1/-1/0 event series. "
            "A market structure shift marks the point where price stops making lows in one "
            "direction and starts making them in the other; the claim is that such a shift "
            "is followed by directional continuation more often than chance. The event is "
            "sparse, so it is held for `hold_bars` bars to be tradeable at all, and an "
            "opposite-direction event overrides the hold immediately rather than waiting for "
            "it to expire."
        ),
        works_when=(
            "Instruments and timeframes where structure is legible -- enough bars per swing "
            "for a shift to be distinguishable from noise. Daily crypto has this; the same "
            "logic intraday mostly detects microstructure noise."
        ),
        fails_when=(
            "Ranging markets, where structure shifts fire repeatedly in both directions and "
            "each is reversed within the hold window. Also whenever hold_bars is longer than "
            "the continuation it is trying to capture, which converts a winning signal into "
            "a round trip through a reversal."
        ),
        expected_edge=(
            "Directional continuation after a structural break. Backtest claim on ETH-USD 1d "
            "is a 62.5% win rate over 64 trades (p=0.030 against a fair coin) -- the stronger "
            "of the two live claims on hit rate, though with roughly half the per-trade "
            "expectancy of dual_thrust."
        ),
        regime="Trending; explicitly not range-bound.",
        cost_assumptions="E26 defaults: 0.1% commission + 0.05% slippage per side, 0.30% round trip.",
        risk_model="ATR-based stop (atr_mult), fixed hold window; sized by e45_risk.",
        source="engines/e24_strategy_research/strategies.py::mss_trend_hold docstring and implementation.",
        notes=[
            "Causality is established rather than assumed: forward-fill-with-limit only "
            "propagates into LATER bars, and market_structure_shift is separately proven causal.",
            "hold_bars is a free grid parameter, so it is re-searched against current data "
            "rather than inherited from the ablation's fixed HOLD=10.",
            "LIVE on ETH-USD 1d with {'hold_bars': 5, 'atr_mult': 1.0}.",
        ],
    ),
]


def seed(path: Path | None = None) -> list[StrategyHypothesis]:
    """Write the seed hypotheses for the currently-live strategies."""
    return [record(h, path) for h in SEED_HYPOTHESES]
