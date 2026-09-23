"""
Module: score_overrides_stage0.py
Description: Scores every live e51_signals strategy override against Stage 0 --
    Deflated Sharpe with effective-N, and percentile against the synthetic
    no-edge null.

    REPORT ONLY. This demotes nothing, blocks nothing and writes nothing to
    the override directory. Stage 0 goes in as a measurement first because
    nobody has yet seen what it says about the existing book; wiring it to
    act before that would be enforcing a threshold whose behaviour on real
    overrides is unknown.

    WHAT EACH COLUMN MEANS.
      raw Sharpe  -- what the override was promoted on, unadjusted.
      N_eff       -- independent bets in the grid that produced it, from
                     the eigenvalue spectrum of candidate return
                     correlations. Not 167: the grid is full of near-copies.
      DSR         -- probability the true Sharpe exceeds zero GIVEN it won
                     a search of N_eff trials. Threshold 0.95.
      null pct    -- where its selection score sits against winners from
                     synthetic no-edge data. 99 means only 1% of no-edge
                     runs produced a winner this good.

    VERDICTS combine both, because they fail differently. DSR asks "is this
    Sharpe big enough to have survived the search?" and the null percentile
    asks "does the PIPELINE manufacture winners this good from noise?" A
    candidate can pass one and fail the other, and the disagreement is the
    interesting part rather than something to average away.

    THE CAVEAT THAT MUST TRAVEL WITH EVERY NUMBER HERE. DSR assumes
    near-IID returns. These strategies hold positions across many bars, so
    per-bar returns are serially dependent. The skew/kurtosis terms correct
    for distribution shape, NOT autocorrelation, and serial dependence
    overstates the effective number of independent observations -- which
    biases DSR UPWARD. Every DSR below is therefore optimistic. A borderline
    pass is not a pass.

    RESEARCH CODE. Imports engines/, never the reverse.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
from project_titan_x.engines.e24_strategy_research.engine import (  # noqa: E402
    BARS_PER_YEAR, DEFAULT_STRATEGY_GRID, _run_one_candidate_worker, _selection_score,
)
from project_titan_x.engines.e26_backtesting.deflated_sharpe import (  # noqa: E402
    deflated_sharpe, trial_geometry,
)

OVERRIDES = ROOT / "project_titan_x" / "data" / "models" / "e51_signals"
DATA = ROOT / "project_titan_x" / "data" / "processed"
OUT = Path(__file__).resolve().parent

YSYM = {"GOLD": "GC=F", "SILVER": "SI=F", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
        "SP500": "^GSPC", "NIFTY50": "^NSEI"}

DSR_THRESHOLD = 0.95
NULL_PCT_STRONG = 95.0
NULL_PCT_WEAK = 80.0


def _resolve_parquet(symbol: str, timeframe: str) -> Path | None:
    for cand in (symbol, YSYM.get(symbol.upper(), symbol)):
        p = DATA / f"{cand}_{timeframe}.parquet"
        if p.exists():
            return p
    return None


def load_null(symbol: str, timeframe: str) -> tuple[list[float], str] | tuple[None, None]:
    """Winning selection scores from the synthetic no-edge campaign, and the
    NAME of the file they came from.

    The name is returned, not just the scores, because the fallback chain can
    silently substitute a different null: a per-symbol campaign, gold as a
    cross-asset proxy, or a half-finished checkpoint all satisfy the same
    call. A percentile carries no meaning without knowing which of those
    answered, and a previous run of this pipeline reported a percentile
    computed from a leftover 6-path smoke test precisely because the source
    was not recorded. Every row now names its own null."""
    # Checkpoints are accepted so a campaign still in flight can be used.
    # A partial null is a smaller sample, not a wrong one -- the reported
    # path count says exactly how much evidence is behind each percentile.
    for name in (f"synthetic_null_{symbol.replace('=','')}_{timeframe}.json",
                 f"synthetic_null_GCF_{timeframe}.json",
                 f"synthetic_null_{symbol.replace('=','')}_{timeframe}.checkpoint.json",
                 f"synthetic_null_GCF_{timeframe}.checkpoint.json"):
        p = OUT / name
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            # ALL paths, including those where noise produced no passing
            # candidate at all (best_selection_score == -inf).
            #
            # Filtering those out was wrong. The question a percentile
            # answers is "of N no-edge runs of this pipeline, how many
            # produced a winner at least this good?" -- and a run that
            # produced NO winner did not produce one this good, so it
            # belongs in the denominator as a run the override beat.
            # Dropping it shrinks numerator and denominator together and
            # understates the percentile. Measured on the 4h campaign
            # (13 of 150 paths passed nothing): 0.3-3.5pp too low. On 1h,
            # where most paths pass nothing because 12k hourly bars is
            # only ~2 years and few candidates reach the 30-trade minimum,
            # the same bug would discard most of the distribution.
            # -inf compares correctly under <=, so no special-casing is
            # needed here; np.percentile on the null's own spread still
            # filters to finite winners, which is a different question.
            vals = [x.get("best_selection_score", float("-inf"))
                    for x in d.get("paths", [])]
            if vals:
                return vals, name
    return None, None


def verdict(dsr: float, null_pct: float | None, trades: int) -> str:
    if trades < 30:
        return "UNCERTAIN (thin)"
    if dsr >= DSR_THRESHOLD and (null_pct is None or null_pct >= NULL_PCT_STRONG):
        return "LIKELY REAL"
    if dsr < 0.5 or (null_pct is not None and null_pct < NULL_PCT_WEAK):
        return "LIKELY NOISE"
    return "UNCERTAIN"


def _score_one(job: tuple) -> dict:
    """Score one override. Module-level so it pickles into a pool."""
    stem, symbol, timeframe, want_strategy, want_params, bars = job
    import numpy as np
    import pandas as pd
    from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
    from project_titan_x.engines.e24_strategy_research.engine import (
        BARS_PER_YEAR, DEFAULT_STRATEGY_GRID, _run_one_candidate_worker, _selection_score)
    from project_titan_x.engines.e26_backtesting.deflated_sharpe import (
        deflated_sharpe, trial_geometry)

    pq = _resolve_parquet(symbol, timeframe)
    if pq is None:
        return {"override": stem, "error": "no local price data", "verdict": "NO DATA"}
    df = pd.read_parquet(pq).tail(bars).reset_index(drop=True)
    ta = TechnicalAnalysisEngine(); ta.initialize()
    enriched = ta.analyze(df).data["df"]
    ppy = BARS_PER_YEAR.get(timeframe, 252)

    streams, sharpes, this = [], [], None
    for strat, plist in DEFAULT_STRATEGY_GRID.items():
        for params in plist:
            r = _run_one_candidate_worker(enriched, strat, params, None, ppy,
                                          0.0005, 0.0002, capture_returns=True)
            if r is None:
                continue
            sharpes.append(r["is_sharpe"])
            if r.get("bar_returns") is not None:
                streams.append(r["bar_returns"])
            if strat == want_strategy and params == want_params:
                this = r
    if this is None or this.get("bar_returns") is None:
        return {"override": stem, "strategy": want_strategy,
                "error": "override params not reproducible in current grid",
                "verdict": "NOT REPRODUCIBLE"}

    geom = trial_geometry(streams)
    sv = float(np.var(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0
    d = deflated_sharpe(this["bar_returns"], this["is_sharpe"], geom.effective_rank,
                        sv, periods_per_year=ppy, threshold=DSR_THRESHOLD)
    null_scores, null_name = load_null(symbol, timeframe)
    score = _selection_score(this)
    null_pct = (float(100.0 * np.mean([x <= score for x in null_scores]))
                if null_scores else None)
    # PROXY OR NOT. The null characterises how readily a 167-candidate grid
    # manufactures a winner from a given number of bars, so gold's null is a
    # defensible stand-in for another asset at the same timeframe -- but only
    # a stand-in. Volatility structure differs by asset, so a row scored
    # against another symbol's null must say so in the row, not in a footnote
    # that travels separately from the number.
    resolved = YSYM.get(symbol.upper(), symbol).replace("=", "")
    null_symbol = (null_name.replace("synthetic_null_", "").split("_")[0]
                   if null_name else None)
    is_proxy = bool(null_name) and null_symbol != resolved
    return {
        "override": stem, "strategy": want_strategy,
        "raw_sharpe": round(this["is_sharpe"], 3),
        "oos_sharpe": round(this["oos_sharpe"], 3),
        "trades": this["is_trades"],
        "n_effective": round(geom.effective_rank, 2),
        "n_clusters": geom.n_clusters,
        "expected_max_sharpe": round(d.expected_max_sharpe, 3),
        "dsr": round(d.deflated_sharpe, 4),
        "null_percentile": None if null_pct is None else round(null_pct, 1),
        "null_paths": 0 if not null_scores else len(null_scores),
        "null_paths_with_winner": (0 if not null_scores else
                                   int(sum(1 for x in null_scores if np.isfinite(x)))),
        "null_source": null_name,
        "null_symbol": null_symbol,
        "null_timeframe": timeframe,
        "null_is_proxy": is_proxy,
        "null_from_checkpoint": bool(null_name) and "checkpoint" in null_name,
        "timeframe": timeframe,
        "verdict": verdict(d.deflated_sharpe, null_pct, this["is_trades"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bars", type=int, default=12000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    files = sorted(OVERRIDES.glob("*_strategy_override.json"))
    if args.limit:
        files = files[:args.limit]

    jobs = []
    for f in files:
        stem = f.name.replace("_strategy_override.json", "")
        symbol, _, timeframe = stem.rpartition("_")
        ov = json.loads(f.read_text(encoding="utf-8"))
        jobs.append((stem, symbol, timeframe, ov.get("strategy"),
                     ov.get("params", ov.get("parameters", {})), args.bars))

    print(f"Stage 0 scoring: {len(jobs)} live overrides, {args.workers} workers")
    rows = []
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_score_one, j): j[0] for j in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            stem = futs[fut]
            try:
                row = fut.result()
            except Exception as e:
                row = {"override": stem, "error": str(e)[:120], "verdict": "ERROR"}
            rows.append(row)
            print(f"  [{i}/{len(jobs)}] {row['override']:<18} "
                  f"SR={row.get('raw_sharpe','--'):>6} N_eff={row.get('n_effective','--'):>6} "
                  f"DSR={row.get('dsr','--'):>7} "
                  f"null={row.get('null_percentile') if row.get('null_percentile') is not None else 'n/a':>5} "
                  f"-> {row['verdict']}", flush=True)
    rows.sort(key=lambda r: r["override"])

    dest = OUT / "stage0_override_scores.json"
    dest.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dsr_threshold": DSR_THRESHOLD,
        "report_only": True,
        "caveat": ("DSR assumes near-IID returns. These strategies hold positions across "
                   "many bars, so per-bar returns are serially dependent. Skew/kurtosis "
                   "correct for distribution shape, not autocorrelation; serial dependence "
                   "overstates independent observations and biases DSR UPWARD. Every DSR "
                   "here is optimistic."),
        "rows": rows,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved to {dest}")


if __name__ == "__main__":
    main()
