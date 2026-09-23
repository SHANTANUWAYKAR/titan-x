"""
Module: improvement_loop.py
Description: PHASE 23 of `reports/upgrade statergy.txt` -- the continuous
    improvement engine:

        DIAGNOSE -> IDENTIFY FAILURE -> FORM HYPOTHESIS -> MODIFY -> BACKTEST
        -> OOS TEST -> STRESS TEST -> COMPARE -> ACCEPT / REJECT

    This is the honest version of a "self-improving trading agent". The pieces
    it needs already existed and were never wired into a loop: E26 grades a
    candidate, `research/concept_ablation.py` changes one thing at a time,
    `core/experiment.py` records lineage, and the Stage 0 gate decides what may
    go live. What was missing was the controller that runs them in order and,
    crucially, that COUNTS ITSELF.

    THE ONE THING MOST SELF-IMPROVING LOOPS GET WRONG. A loop that retunes
    parameters against observed results IS A SEARCH. Every iteration is another
    draw from the same distribution, so the more diligently the loop "improves",
    the more certain it becomes that the best-looking configuration is the
    luckiest rather than the best. This project has already measured the effect
    on its own data: pure noise clears its legacy selection bar **137 times in
    150** at 4h, and growing the candidate grid from 167 to ~830 left the
    >=95th-percentile bar roughly 21-32% too lenient without anyone touching a
    strategy.

    So this loop maintains `trials_consumed` and reports it with every result.
    A proposal that "wins" after 40 trials is a far weaker claim than one that
    wins on the first, and a loop that does not say which it was is not doing
    science -- it is doing p-hacking with extra steps.

    ONE VARIABLE AT A TIME, ENFORCED. `propose_variants` changes exactly one
    parameter per variant and refuses a proposal that touches two, because a
    multi-parameter jump cannot attribute the result to anything. This is the
    same discipline the ablation script already follows.

    ACCEPTANCE IS OOS-FIRST AND DELIBERATELY HARD TO SATISFY. The spec is
    explicit: "If a modification improves in-sample results but decreases OOS
    robustness: REJECT IT." So a variant is accepted only when the SELECTION
    SCORE -- min(IS Sharpe, OOS Sharpe), the same statistic the Stage 0 gate
    uses -- improves by more than `min_improvement`, AND out-of-sample Sharpe
    does not fall. An in-sample-only gain is recorded as a REJECTION with its
    reason, not discarded.

    IT CANNOT DEPLOY ANYTHING. Non-negotiable 20 ("do not automatically deploy
    strategies to live trading") and PHASE 33's human-approval requirement both
    apply. This module returns proposals and writes reports. Going live still
    requires an explicit `stage0.status == "VALIDATED"` tag written by a
    separate, deliberate pass. Nothing here writes one, and nothing here may.

    FAILED ATTEMPTS ARE KEPT. Non-negotiables 8 and 9 forbid hiding failed
    research and deleting negative results. Every variant tried is recorded
    with its outcome, including the ones that got worse -- those are the
    evidence that the accepted one was not merely the luckiest of many.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# A variant must beat the incumbent's selection score by at least this much to
# be worth anything. Not zero: with ~70-90 trades, a selection-score difference
# below ~0.05 is comfortably inside the noise of which bars landed in which
# walk-forward split, so accepting on a smaller margin would be accepting on
# the split rather than on the strategy.
DEFAULT_MIN_IMPROVEMENT = 0.05

# Hard ceiling on how many variants one loop may try. This is a
# multiple-comparison control, not a runtime budget: every trial makes the
# best-of-N score climb on noise alone, and an unbounded loop eventually
# "improves" any strategy to a number that means nothing.
DEFAULT_MAX_TRIALS = 40


@dataclass
class Diagnosis:
    """What is actually wrong with a strategy, before anything is changed."""

    strategy: str
    symbol: str
    timeframe: str
    selection_score: Optional[float] = None
    is_sharpe: Optional[float] = None
    oos_sharpe: Optional[float] = None
    trades: Optional[int] = None
    bar: Optional[float] = None
    failures: list = field(default_factory=list)
    primary_failure: str = ""

    @property
    def margin(self) -> Optional[float]:
        if self.selection_score is None or self.bar is None:
            return None
        return self.selection_score - self.bar


@dataclass
class Variant:
    """One proposed single-parameter change, with the reason it was proposed."""

    params: dict
    changed_key: str
    from_value: Any
    to_value: Any
    hypothesis: str


@dataclass
class TrialResult:
    variant: Variant
    selection_score: Optional[float]
    is_sharpe: Optional[float]
    oos_sharpe: Optional[float]
    trades: Optional[int]
    accepted: bool
    reason: str


def diagnose(
    strategy: str,
    symbol: str,
    timeframe: str,
    metrics: dict,
    bar: Optional[float] = None,
    min_trades: int = 60,
) -> Diagnosis:
    """Name what is failing, in priority order, before proposing any change.

    The spec's own instruction is "Never optimize blindly" -- a loop that
    starts mutating parameters without first stating what it is trying to fix
    is a random walk through the parameter space with a scientific-sounding
    name attached.
    """
    is_s = metrics.get("is_sharpe")
    oos_s = metrics.get("oos_sharpe")
    trades = metrics.get("is_trades") or metrics.get("trades")
    sel = (min(is_s, oos_s) if is_s is not None and oos_s is not None else None)

    d = Diagnosis(strategy=strategy, symbol=symbol, timeframe=timeframe,
                  selection_score=sel, is_sharpe=is_s, oos_sharpe=oos_s,
                  trades=trades, bar=bar)

    if trades is not None and trades < min_trades:
        d.failures.append(
            f"sample too thin: {trades} trades against a {min_trades} floor -- any metric "
            f"computed on this is dominated by which trades happened to land in the window")
    if is_s is not None and oos_s is not None:
        if oos_s < is_s * 0.5 and is_s > 0:
            d.failures.append(
                f"severe in-sample/out-of-sample decay: IS {is_s:.3f} -> OOS {oos_s:.3f} "
                f"({100 * (1 - oos_s / is_s):.0f}% lost). The rule fits the training window "
                f"better than it fits the market")
        if oos_s <= 0:
            d.failures.append(
                f"out-of-sample Sharpe is {oos_s:.3f} -- the strategy does not work outside "
                f"the window it was selected on")
    if bar is not None and sel is not None:
        if sel < bar:
            d.failures.append(
                f"below the Stage 0 bar: selection {sel:.4f} < {bar} (short by "
                f"{bar - sel:.4f})")
        elif sel - bar < 0.05:
            d.failures.append(
                f"indistinguishable from the Stage 0 bar: selection {sel:.4f} vs {bar} "
                f"(margin {sel - bar:+.4f}) -- inside the noise of the walk-forward split")

    d.primary_failure = d.failures[0] if d.failures else "no failure identified"
    return d


def propose_variants(
    base_params: dict,
    grid: dict,
    diagnosis: Diagnosis,
    max_variants: int = DEFAULT_MAX_TRIALS,
) -> list[Variant]:
    """Single-parameter neighbours of `base_params` drawn from the real grid.

    Variants come from the parameter values this project ALREADY searches
    (`DEFAULT_STRATEGY_GRID`), not from freshly invented ranges. Inventing new
    values would widen the search space beyond anything the null campaigns were
    calibrated against, which would make the resulting percentile meaningless
    in exactly the way this module is built to avoid.

    Exactly one key differs per variant -- a multi-key jump cannot attribute
    its result to any single change.
    """
    candidates = grid.get(diagnosis.strategy) or []
    seen: set[tuple] = set()
    out: list[Variant] = []

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        diff = [k for k in set(base_params) | set(cand)
                if base_params.get(k) != cand.get(k)]
        if len(diff) != 1:
            continue                      # zero = the incumbent; 2+ = unattributable
        k = diff[0]
        key = (k, repr(cand.get(k)))
        if key in seen:
            continue
        seen.add(key)
        out.append(Variant(
            params=dict(cand),
            changed_key=k,
            from_value=base_params.get(k),
            to_value=cand.get(k),
            hypothesis=(
                f"Changing only `{k}` from {base_params.get(k)!r} to {cand.get(k)!r}. "
                f"Targeting: {diagnosis.primary_failure}"),
        ))
        if len(out) >= max_variants:
            break
    return out


def evaluate(
    variants: list[Variant],
    run_candidate: Callable[[dict], Optional[dict]],
    incumbent_selection: Optional[float],
    incumbent_oos: Optional[float],
    min_improvement: float = DEFAULT_MIN_IMPROVEMENT,
    max_trials: int = DEFAULT_MAX_TRIALS,
) -> tuple[list[TrialResult], int]:
    """Test each variant and accept only genuine out-of-sample improvement.

    `run_candidate(params) -> metrics dict | None` is injected so this stays
    testable without standing up E07/E26, and so the loop never decides for
    itself how a backtest is run.

    Returns (results, trials_consumed). The trial count is returned rather
    than merely logged because it is part of the RESULT: a variant that wins
    on trial 38 of 40 is a much weaker claim than one that wins on trial 2,
    and any report that omits the count is hiding the multiple-comparison
    problem rather than managing it.
    """
    results: list[TrialResult] = []
    trials = 0

    for v in variants:
        if trials >= max_trials:
            logger.info("improvement_loop: stopping at the %d-trial ceiling", max_trials)
            break
        trials += 1

        m = run_candidate(v.params)
        if not m:
            results.append(TrialResult(v, None, None, None, None, False,
                                       "candidate did not run"))
            continue

        is_s, oos_s = m.get("is_sharpe"), m.get("oos_sharpe")
        trades = m.get("is_trades") or m.get("trades")
        sel = min(is_s, oos_s) if is_s is not None and oos_s is not None else None

        if sel is None:
            results.append(TrialResult(v, None, is_s, oos_s, trades, False,
                                       "no selection score computable"))
            continue

        # Rule 1: out-of-sample must not degrade. The spec is explicit --
        # an in-sample gain bought with an out-of-sample loss is REJECTED.
        if incumbent_oos is not None and oos_s is not None and oos_s < incumbent_oos:
            results.append(TrialResult(
                v, sel, is_s, oos_s, trades, False,
                f"REJECTED: out-of-sample Sharpe fell {incumbent_oos:.3f} -> {oos_s:.3f}. "
                f"An in-sample improvement bought with an out-of-sample loss is overfitting, "
                f"not progress"))
            continue

        # Rule 2: the selection score must improve by more than noise.
        if incumbent_selection is not None and sel < incumbent_selection + min_improvement:
            results.append(TrialResult(
                v, sel, is_s, oos_s, trades, False,
                f"REJECTED: selection {sel:.4f} vs incumbent {incumbent_selection:.4f} "
                f"(needs +{min_improvement}). Inside the noise of the walk-forward split"))
            continue

        results.append(TrialResult(
            v, sel, is_s, oos_s, trades, True,
            f"improves selection {incumbent_selection:.4f} -> {sel:.4f} with out-of-sample "
            f"holding at {oos_s:.3f}" if incumbent_selection is not None
            else f"selection {sel:.4f}"))

    return results, trials


def summarise_run(
    diagnosis: Diagnosis,
    results: list[TrialResult],
    trials: int,
    max_trials: int = DEFAULT_MAX_TRIALS,
) -> dict:
    """The loop's own result, stated so the trial count cannot be dropped."""
    accepted = [r for r in results if r.accepted]
    best = max(accepted, key=lambda r: r.selection_score or float("-inf"), default=None)

    caveats = [
        f"{trials} variant(s) were tried. Best-of-{trials} on noise alone climbs with the "
        f"trial count, so this proposal is only as strong as that number is small.",
        "Accepting a proposal here changes NOTHING that trades. Going live requires a "
        "separate, deliberate Stage 0 tag; this loop cannot write one.",
    ]
    if trials >= max_trials:
        caveats.append(
            f"The {max_trials}-trial ceiling was reached, so the search was truncated. "
            f"Treat any winner as the best of a capped search, not as the best available.")
    if best and trials > 10:
        caveats.append(
            f"The winner emerged after {trials} trials. At that many comparisons the "
            f"Stage 0 percentile this project uses is NOT valid for it -- the null was "
            f"calibrated against a fixed grid, not against a grid plus this search.")

    return {
        "strategy": diagnosis.strategy,
        "symbol": diagnosis.symbol,
        "timeframe": diagnosis.timeframe,
        "diagnosis": {
            "primary_failure": diagnosis.primary_failure,
            "all_failures": diagnosis.failures,
            "selection_score": diagnosis.selection_score,
            "bar": diagnosis.bar,
            "margin": diagnosis.margin,
        },
        "trials_consumed": trials,
        "n_accepted": len(accepted),
        "n_rejected": len(results) - len(accepted),
        "proposal": None if best is None else {
            "params": best.variant.params,
            "changed": f"{best.variant.changed_key}: {best.variant.from_value!r} -> "
                       f"{best.variant.to_value!r}",
            "hypothesis": best.variant.hypothesis,
            "selection_score": best.selection_score,
            "is_sharpe": best.is_sharpe,
            "oos_sharpe": best.oos_sharpe,
            "trades": best.trades,
            "reason": best.reason,
        },
        "rejections": [
            {"changed": f"{r.variant.changed_key}: {r.variant.from_value!r} -> "
                        f"{r.variant.to_value!r}",
             "selection_score": r.selection_score,
             "oos_sharpe": r.oos_sharpe,
             "reason": r.reason}
            for r in results if not r.accepted
        ],
        "caveats": caveats,
        "deployed": False,
    }


def record_run(summary: dict, log_path=None) -> Optional[str]:
    """Write the whole run -- including every rejection -- to the experiment log."""
    try:
        from project_titan_x.core import experiment as _ex
    except Exception as e:  # noqa: BLE001
        logger.warning("improvement_loop: experiment lineage unavailable (%s)", e)
        return None

    prop = summary.get("proposal")
    conclusion = (
        f"After {summary['trials_consumed']} single-variable trials: "
        + (f"PROPOSAL (not deployed) {prop['changed']}, selection "
           f"{prop['selection_score']:.4f}. " if prop else "NO variant improved on the "
           "incumbent out of sample. ")
        + f"{summary['n_rejected']} rejected, kept for the record."
    )
    try:
        rec = _ex.record(
            kind="robustness",
            title=(f"Improvement loop: {summary['symbol']} {summary['timeframe']} "
                   f"{summary['strategy']} ({summary['trials_consumed']} trials)"),
            symbol=summary["symbol"], timeframe=summary["timeframe"],
            strategy=summary["strategy"],
            params=(prop or {}).get("params", {}),
            metrics={"trials_consumed": summary["trials_consumed"],
                     "n_accepted": summary["n_accepted"],
                     "n_rejected": summary["n_rejected"],
                     "diagnosis": summary["diagnosis"],
                     "proposal": prop},
            conclusion=conclusion,
            notes=summary["caveats"] + [
                "Rejected variants are recorded deliberately (non-negotiables 8 and 9): "
                "they are the evidence that the winner was not merely the luckiest draw.",
            ],
            log_path=log_path,
        )
        return rec.experiment_id
    except Exception as e:  # noqa: BLE001
        logger.warning("improvement_loop: could not record run (%s)", e)
        return None
