"""
Module: synthetic_null.py
Description: Stage 0's synthetic-null baseline -- how often does the E24->E26
    loop declare a winner on data that has NO edge?

    THE QUESTION. E24 searches 167 candidates and E26 passes any that clear
    IS trades>=30, IS Sharpe>0.5, maxDD<25%, OOS Sharpe>0. Nobody has ever
    measured what that bar does against pure noise. If 12 of 167 candidates
    "pass validation" on a series with no predictability, then a real sweep
    returning 12 passes is reporting the false-positive rate, not an edge.

    WHY A BLOCK BOOTSTRAP AND NOT GBM OR AN IID SHUFFLE. The null has to be
    hard enough to be honest. An IID shuffle of returns destroys volatility
    clustering, and a Gaussian random walk has neither fat tails nor
    clustering -- both produce a null that is far tamer than real markets,
    so the pipeline would look better against them than it deserves. The
    stationary block bootstrap (Politis & Romano) resamples runs of
    consecutive bars, so within-block dynamics survive while any
    predictable structure spanning more than a block is destroyed.

    THE TENSION, STATED RATHER THAN HIDDEN. Preserving within-block
    dynamics means short-horizon momentum survives inside each block, so
    for a momentum strategy this null is not perfectly null -- it retains a
    little of the very thing being tested. There is no block length that
    escapes this: short blocks destroy the volatility clustering that makes
    the null realistic, long blocks preserve more real structure. That is
    why THREE block lengths are run and the sensitivity is reported, rather
    than one being picked and called correct.

    WHOLE BARS, NOT CLOSES. Several strategies in the grid read high/low
    (donchian_breakout, opening_range_breakout, the session-sweep
    archetypes). Resampling closes and synthesising highs and lows would
    break those strategies rather than test them, so each drawn bar keeps
    its own intrabar geometry -- open, high and low are carried across as
    ratios to that bar's own close. High >= max(open, close) holds
    automatically because the shape came from a real bar.

    RESEARCH CODE. Imports engines/, never the reverse. Reports only;
    promotes nothing.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import warnings
from dataclasses import dataclass, field
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

DATA = ROOT / "project_titan_x" / "data" / "processed"
OUT = Path(__file__).resolve().parent
BLOCK_LENGTHS = (10, 50, 200)          # bars; sensitivity is the point, not one "right" value


def stationary_bootstrap_ohlc(df: pd.DataFrame, mean_block: int,
                              rng: np.random.Generator) -> pd.DataFrame:
    """One synthetic OHLCV path with the same length as `df`.

    Close-to-close log returns are resampled in geometrically-distributed
    blocks (Politis & Romano's stationary bootstrap, which keeps the
    resampled series stationary in a way fixed-length blocks do not), and
    each drawn bar's own intrabar geometry rides along with its return.
    """
    c = df["close"].to_numpy(dtype=float)
    if len(c) < 3:
        raise ValueError("need at least 3 bars")
    ret = np.diff(np.log(np.maximum(c, 1e-12)))            # n-1 close-to-close moves
    n = len(ret)

    # Intrabar shape of the bar each return LANDS on, so shape and move
    # stay attached to the same real bar.
    o = np.log(np.maximum(df["open"].to_numpy(dtype=float)[1:], 1e-12) / np.maximum(c[1:], 1e-12))
    h = np.log(np.maximum(df["high"].to_numpy(dtype=float)[1:], 1e-12) / np.maximum(c[1:], 1e-12))
    lo = np.log(np.maximum(df["low"].to_numpy(dtype=float)[1:], 1e-12) / np.maximum(c[1:], 1e-12))
    vol = df["volume"].to_numpy(dtype=float)[1:] if "volume" in df else np.ones(n)

    p = 1.0 / max(1, mean_block)
    idx = np.empty(n, dtype=np.int64)
    i = 0
    while i < n:
        start = rng.integers(0, n)
        # Geometric run length, wrapped circularly so every bar can start a block.
        run = min(n - i, 1 + int(rng.geometric(p)))
        for k in range(run):
            idx[i + k] = (start + k) % n
        i += run

    synth_ret, synth_o, synth_h, synth_l, synth_v = ret[idx], o[idx], h[idx], lo[idx], vol[idx]
    close = c[0] * np.exp(np.cumsum(synth_ret))
    out = pd.DataFrame({
        "open": close * np.exp(synth_o),
        "high": close * np.exp(synth_h),
        "low": close * np.exp(synth_l),
        "close": close,
        "volume": synth_v,
    })
    # A drawn bar's own high/low bracket its own close, but the OPEN comes
    # from that same bar too, so the bracket must be re-established against
    # the reconstructed open rather than assumed.
    out["high"] = out[["high", "open", "close"]].max(axis=1)
    out["low"] = out[["low", "open", "close"]].min(axis=1)
    if "timestamp" in df:
        out["timestamp"] = df["timestamp"].to_numpy()[1:]
    return out


def _run_one_null_path(job: tuple) -> dict:
    """One synthetic path, start to finish. Module-level so it pickles.

    Parallelism is at the PATH level, not the candidate level: paths are
    completely independent (own bootstrap draw, own TA enrichment, own 167
    backtests), so there is no shared state to get wrong. Measured on this
    machine at 12,000 bars, one path costs ~258s sequentially -- 150 paths
    would be 10.8h, against a 4h budget. A 6-way pool brings that to ~1.8h
    without touching history length or dropping strategies from the grid.

    Capped at 6 workers to match the cap E24's own pool already uses after
    a 16-worker pool was found to lose an entire run when one child died.
    """
    real_records, bl, j, timeframe, grid, seed = job
    import numpy as np
    import pandas as pd
    from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
    from project_titan_x.engines.e24_strategy_research.engine import (
        BARS_PER_YEAR, _run_one_candidate_worker, _selection_score)
    from project_titan_x.engines.e26_backtesting.deflated_sharpe import trial_geometry

    real = pd.DataFrame(real_records)
    rng = np.random.default_rng(seed)
    ta = TechnicalAnalysisEngine(); ta.initialize()
    ppy = BARS_PER_YEAR.get(timeframe, 252)

    synth = stationary_bootstrap_ohlc(real, bl, rng)
    enriched = ta.analyze(synth).data["df"]
    rows, streams = [], []
    for strat, plist in grid.items():
        for params in plist:
            r = _run_one_candidate_worker(enriched, strat, params, None, ppy,
                                          0.0005, 0.0002, capture_returns=True)
            if r is None:
                continue
            rows.append(r)
            if r.get("bar_returns") is not None:
                streams.append(r["bar_returns"])
    passed = [r for r in rows if r["passed_validation"]]
    geom = trial_geometry(streams) if streams else None
    best = max(passed, key=_selection_score) if passed else None
    return {
        "block_length": bl, "path": j, "n_candidates": len(rows), "n_passed": len(passed),
        "best_selection_score": float(_selection_score(best)) if best else float("-inf"),
        "best_is_sharpe": float(best["is_sharpe"]) if best else 0.0,
        "best_oos_sharpe": float(best["oos_sharpe"]) if best else 0.0,
        "effective_rank": float(geom.effective_rank) if geom else 0.0,
        "n_clusters": int(geom.n_clusters or 0) if geom else 0,
    }


@dataclass
class NullPathResult:
    block_length: int
    path: int
    n_candidates: int
    n_passed: int
    best_selection_score: float
    best_is_sharpe: float
    best_oos_sharpe: float
    effective_rank: float = 0.0
    n_clusters: int = 0


@dataclass
class NullCampaign:
    symbol: str
    timeframe: str
    paths: list[NullPathResult] = field(default_factory=list)

    def percentile_of(self, score: float, block_length: int | None = None) -> float:
        """Where a real sweep's winning score sits in the null distribution.

        99 means only 1% of no-edge paths produced a winner this good.
        Computed across ALL block lengths by default -- pooling is the
        conservative reading when the three disagree, since it keeps the
        tail from whichever block length was most permissive.
        """
        pool = [p.best_selection_score for p in self.paths
                if block_length is None or p.block_length == block_length]
        if not pool:
            return float("nan")
        return float(100.0 * np.mean([s <= score for s in pool]))


def run_campaign(symbol: str, timeframe: str, k_paths: int, grid: dict,
                 block_lengths=BLOCK_LENGTHS, seed: int = 0,
                 checkpoint: Path | None = None, workers: int = 6,
                 bars: int = 0, resume: bool = False,
                 expect_candidates: int | None = None) -> NullCampaign:
    """Run the full E24->E26 loop on synthetic no-edge data, pooled by path."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    path = DATA / f"{symbol}_{timeframe}.parquet"
    if not path.exists():
        raise SystemExit(f"no local data: {path}")
    real = pd.read_parquet(path).reset_index(drop=True)
    if bars:
        real = real.tail(bars).reset_index(drop=True)
    records = real.to_dict("list")
    camp = NullCampaign(symbol=symbol, timeframe=timeframe)

    # RESUME (added 2026-09-19). A 1d campaign at the current grid size takes
    # ~2.5 hours and this one already died once at 95/150 when its session
    # ended, losing every completed path. Checkpoints were being written the
    # whole time and simply never read back.
    #
    # The reload is guarded on candidates_per_path. Paths computed against a
    # DIFFERENT grid size do not describe the same search -- best-of-N climbs
    # with N -- so silently pooling 167-candidate paths with 799-candidate ones
    # would produce a null that matches no search anyone actually ran. That is
    # the precise error this whole re-calibration exists to correct, so it must
    # not be reintroduced by the resume path.
    done_keys: set[tuple[int, int]] = set()
    if resume and checkpoint and checkpoint.exists():
        try:
            prior = json.loads(checkpoint.read_text(encoding="utf-8"))
            # Compare against the GRID SIZE the checkpoint was written with, not
            # against each path's realised n_candidates. Those are different
            # numbers and always will be: the grid holds 830 parameterisations
            # while a path records only the ~799 that actually returned a result
            # (a candidate whose backtest yields None is skipped). Keying the
            # guard on n_candidates discarded 95 perfectly valid completed paths
            # on this script's first resume, because 799 != 830 every time.
            prior_grid = prior.get("grid_candidates")
            kept, dropped = [], 0
            if expect_candidates and prior_grid is not None and prior_grid != expect_candidates:
                dropped = len(prior.get("paths", []))
                print(f"  checkpoint was built against a {prior_grid}-candidate grid, "
                      f"this run uses {expect_candidates} -- discarding all {dropped} "
                      f"path(s): they describe a different search")
            else:
                if prior_grid is None:
                    print("  checkpoint predates grid-size stamping -- assuming it matches "
                          "this grid; delete it instead if that is wrong")
                for row in prior.get("paths", []):
                    kept.append(NullPathResult(**row))
            camp.paths.extend(kept)
            done_keys = {(p.block_length, p.path) for p in camp.paths}
            print(f"  resuming: {len(kept)} completed path(s) reloaded from checkpoint"
                  + (f", {dropped} DISCARDED (different candidate count -- "
                     f"not the same search)" if dropped else ""))
        except Exception as e:  # noqa: BLE001
            print(f"  resume failed ({str(e)[:80]}) -- starting clean")
            camp.paths.clear()
            done_keys = set()

    jobs = [(records, bl, j, timeframe, grid, seed * 100003 + bl * 1009 + j)
            for bl in block_lengths for j in range(k_paths)
            if (bl, j) not in done_keys]
    total, done, t0 = len(jobs), 0, time.time()
    if not jobs:
        print("  nothing left to run -- every path already in the checkpoint")
        return camp
    print(f"  {total} paths over {workers} workers ({len(real):,} bars each)")

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_one_null_path, j): j for j in jobs}
        for fut in as_completed(futures):
            try:
                camp.paths.append(NullPathResult(**fut.result()))
            except Exception as e:
                # One dead path must not lose the campaign -- the whole
                # point is a distribution, and it survives a missing draw.
                print(f"    path failed ({str(e)[:70]}) -- continuing", flush=True)
            done += 1
            el = time.time() - t0
            if camp.paths:
                last = camp.paths[-1]
                print(f"  [{done}/{total}] block {last.block_length:>3} "
                      f"{last.n_passed:>3}/{last.n_candidates} passed  "
                      f"best={last.best_selection_score:>6.2f}  "
                      f"eff_rank={last.effective_rank:>5.1f}  "
                      f"[{el/done:.0f}s/path, ~{(total-done)*el/done/60:.0f}m left]", flush=True)
            if checkpoint and done % 5 == 0:
                checkpoint.write_text(json.dumps(
                    {"symbol": symbol, "timeframe": timeframe,
                     # Stamp the GRID size so a later --resume can tell whether
                     # these paths describe the same search. Without it the
                     # guard has to infer identity from a derived count, which
                     # is what threw away 95 completed paths on the first try.
                     "grid_candidates": expect_candidates,
                     "paths": [p.__dict__ for p in camp.paths]}, indent=1), encoding="utf-8")
    return camp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="GC=F")
    ap.add_argument("--timeframe", default="4h")
    ap.add_argument("--paths", type=int, default=50, help="paths PER block length")
    ap.add_argument("--bars", type=int, default=0, help="tail N bars of real data (0=all)")
    ap.add_argument("--strategies", default="", help="comma-separated subset")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--resume", action="store_true",
                    help="Reload completed paths from the checkpoint and run only what is "
                         "missing. Paths whose candidate count differs from the current grid "
                         "are DISCARDED, not pooled -- they describe a different search.")
    args = ap.parse_args()

    grid = DEFAULT_STRATEGY_GRID
    if args.strategies:
        want = {s.strip() for s in args.strategies.split(",") if s.strip()}
        grid = {k: v for k, v in grid.items() if k in want}
    n_cand = sum(len(v) for v in grid.values())
    print(f"synthetic null: {args.symbol} {args.timeframe}  "
          f"{args.paths} paths x {len(BLOCK_LENGTHS)} block lengths x {n_cand} candidates")

    ck = OUT / f"synthetic_null_{args.symbol.replace('=','')}_{args.timeframe}.checkpoint.json"
    camp = run_campaign(args.symbol, args.timeframe, args.paths, grid, checkpoint=ck,
                        resume=args.resume, expect_candidates=n_cand,
                        workers=args.workers, bars=args.bars)

    dest = OUT / f"synthetic_null_{args.symbol.replace('=','')}_{args.timeframe}.json"
    by_block = {}
    for bl in BLOCK_LENGTHS:
        sub = [p for p in camp.paths if p.block_length == bl]
        if not sub:
            continue
        finite = [p.best_selection_score for p in sub if np.isfinite(p.best_selection_score)]
        by_block[str(bl)] = {
            "paths": len(sub),
            "mean_passed": float(np.mean([p.n_passed for p in sub])),
            "max_passed": int(max(p.n_passed for p in sub)),
            "paths_with_zero_passes": int(sum(1 for p in sub if p.n_passed == 0)),
            "best_score_p50": float(np.percentile(finite, 50)) if finite else None,
            "best_score_p95": float(np.percentile(finite, 95)) if finite else None,
            "best_score_max": float(max(finite)) if finite else None,
            "mean_effective_rank": float(np.mean([p.effective_rank for p in sub])),
        }
    dest.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol, "timeframe": args.timeframe,
        "block_lengths": list(BLOCK_LENGTHS), "paths_per_block": args.paths,
        "candidates_per_path": n_cand,
        "by_block_length": by_block,
        "paths": [p.__dict__ for p in camp.paths],
    }, indent=2), encoding="utf-8")

    print("\nBLOCK LENGTH SENSITIVITY")
    print(f"  {'block':>6} {'paths':>6} {'mean passed':>12} {'max':>5} "
          f"{'zero':>5} {'p50 score':>10} {'p95 score':>10}")
    for bl, s in by_block.items():
        print(f"  {bl:>6} {s['paths']:>6} {s['mean_passed']:>12.1f} {s['max_passed']:>5} "
              f"{s['paths_with_zero_passes']:>5} "
              f"{s['best_score_p50'] if s['best_score_p50'] is None else round(s['best_score_p50'],2):>10} "
              f"{s['best_score_p95'] if s['best_score_p95'] is None else round(s['best_score_p95'],2):>10}")
    print(f"\nSaved to {dest}")

    # Research lineage (core/experiment.py -- PHASES 8/24/29). A null campaign
    # is the single most consequential experiment this project runs: it defines
    # the bar every strategy is judged against, and the previous campaigns were
    # calibrated at 167 candidates per path while the grid grew to ~830,
    # leaving the >=95th-percentile bar roughly 21-32% too lenient. That drift
    # went unnoticed for weeks precisely because nothing recorded what a
    # campaign was run against. This does.
    try:
        from project_titan_x.core import experiment as _ex

        bars_note = f"{args.bars} tail bars" if args.bars else "all available bars"
        _ex.record(
            kind="null_campaign",
            title=(f"Synthetic no-edge null: {args.symbol} {args.timeframe}, "
                   f"{n_cand} candidates/path"),
            symbol=args.symbol,
            timeframe=args.timeframe,
            params={
                "paths_per_block": args.paths,
                "block_lengths": list(BLOCK_LENGTHS),
                "candidates_per_path": n_cand,
                "strategies_in_grid": len(grid),
                "bars": bars_note,
                "workers": args.workers,
            },
            metrics={"by_block_length": by_block},
            artifacts=[str(dest)],
            conclusion=(
                f"Calibrated the no-edge null at {n_cand} candidates per path. "
                f"This defines the selection bar; a campaign run at a DIFFERENT "
                f"candidate count does not describe the same search and its "
                f"percentiles are not comparable."
            ),
            notes=[
                "Percentiles are not comparable across timeframes, or across campaigns "
                "with different candidates_per_path.",
                "This null is computed on one symbol and acts as a CROSS-ASSET PROXY for "
                "every other symbol at this timeframe.",
            ],
        )
    except Exception as e:  # noqa: BLE001 - a bookkeeping failure must not
        # invalidate a campaign that took hours of real compute.
        print(f"  (warning: could not record experiment lineage: {e})")


if __name__ == "__main__":
    main()
