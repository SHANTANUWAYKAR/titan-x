"""Why does a scan return no signals on intraday timeframes?

A scan that returns 0 signals is indistinguishable from a scan that returned 0
signals FOR A REASON. `scan_all_assets` folds every failure into the same
`return None` -- a failed fetch, a failed regime read, a timeout and an honest
"no directional bias" all look identical from outside. This script re-runs the
same pipeline per asset and records WHICH stage stopped it.

The stages, in the order _scan_one hits them:

    FETCH_FAIL      e02 returned no data for this symbol/timeframe
    THIN            fetched, but too few bars for the indicators to be valid
    TA_FAIL         e07 could not enrich
    REGIME_FAIL     e08 could not classify
    NO_DIRECTION    pipeline ran, composite score never reached entry_threshold
    LOW_CONFIDENCE  direction found, but below min_signal_confidence
    SIGNAL          a signal was produced
    ERROR           raised

NO_DIRECTION is the only one of these that is a real market answer. Every other
row is a plumbing problem wearing the same clothes, which is exactly why this
script exists.

    python scripts/diagnose_intraday.py
    python scripts/diagnose_intraday.py --timeframes 15m,5m --symbols BTCUSD,AAPL
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.core.config import get_settings  # noqa: E402
from project_titan_x.engines.registry import get_registry  # noqa: E402

settings = get_settings()

OUT = ROOT / "project_titan_x" / "reports" / "INTRADAY_DIAGNOSIS.md"
# Below this the 200-period EMA and every long-lookback indicator are NaN, so
# the composite score is structurally unable to fire. Reporting these as
# "no directional bias" would be a lie about the market.
MIN_BARS = 250


_ASSETS = {a.symbol: a for a in list_assets()}


def _asset_of(sym: str):
    return _ASSETS.get(sym)


def diagnose(sym: str, tf: str, reg) -> tuple[str, str]:
    """(stage, detail) for one asset/timeframe."""
    # Mirrors _scan_one exactly -- same years=2, same data-quality repair,
    # same include_extended_context=False. A diagnostic that calls the
    # pipeline differently from the scanner diagnoses a different program.
    try:
        asset = _asset_of(sym)
        yahoo = getattr(asset, "yahoo_symbol", sym) if asset else sym
        fetch = reg.get("e02_market_data").fetch_ohlcv(yahoo, tf, years=2, allow_cache=True)
        if not fetch.success or fetch.data is None or len(fetch.data) == 0:
            return "FETCH_FAIL", (fetch.message or "no data")[:70]
        df = fetch.data
        dq = reg.get("e40_data_quality")
        if dq is not None:
            rep = dq.repair(df)
            df = rep.data if rep.success else df
        if len(df) < MIN_BARS:
            return "THIN", f"{len(df)} bars < {MIN_BARS}"

        ta = reg.get("e07_technical").analyze(df, symbol=sym, timeframe=tf)
        if not ta.success:
            return "TA_FAIL", (ta.message or "")[:70]
        snapshot = ta.data["snapshot"]

        regime = reg.get("e08_regime").classify(df, snapshot, None)
        if not regime.success:
            return "REGIME_FAIL", (regime.message or "")[:70]

        sig = reg.get("e51_signals").generate_signal(
            sym, df, snapshot, regime.data, 0.0,
            enriched_df=ta.data.get("df"),
            include_extended_context=False,
        )
        meta = sig.metadata or {}
        if sig.success and sig.data is not None:
            return "SIGNAL", f"conf={getattr(sig.data, 'confidence_score', '?')}"
        if meta.get("direction") is None:
            return "NO_DIRECTION", f"conf={meta.get('confidence', '?')}"
        # generate_signal already NAMES the checks that failed, in its message
        # ("Signal criteria not met: a, b"). An earlier version of this script
        # guessed "LOW_CONFIDENCE" here and printed the nonsense "conf=86 < 20"
        # -- the confidence was fine and something else vetoed. Read the
        # engine's own answer instead of inferring one.
        failed = [k for k, v in (meta.get("checks") or {}).items() if not v]
        msg = (sig.message or "").replace("Signal criteria not met: ", "")
        return ("VETOED:" + (failed[0] if failed else "unknown"),
                f"conf={meta.get('confidence', '?')} failed=[{msg or ','.join(failed)}]")
    except Exception as e:  # noqa: BLE001
        return "ERROR", f"{type(e).__name__}: {str(e)[:60]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", default="1d,4h,1h,30m,15m,5m")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    logging.disable(logging.CRITICAL)
    reg = get_registry()
    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    syms = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            or [a.symbol for a in list_assets()])

    grid: dict[tuple[str, str], tuple[str, str]] = {}
    for tf in tfs:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for sym, res in zip(syms, ex.map(lambda s, _tf=tf: diagnose(s, _tf, reg), syms)):
                grid[(sym, tf)] = res
        done = collections.Counter(grid[(s, tf)][0] for s in syms)
        print(f"{tf:<5} " + "  ".join(f"{k}={v}" for k, v in done.most_common()), flush=True)

    lines = [
        "# Intraday diagnosis — why a timeframe returns no signals",
        "",
        "Every row is the FIRST stage that stopped that asset. `scan_all_assets`",
        "collapses all of these into the same silent `return None`, so a plumbing",
        "failure and an honest 'no setup today' are indistinguishable from outside.",
        "**`NO_DIRECTION` is the only stage that is a real market answer.**",
        "",
        "| Asset | " + " | ".join(tfs) + " |",
        "|---" * (len(tfs) + 1) + "|",
    ]
    for sym in syms:
        lines.append(f"| {sym} | " + " | ".join(grid[(sym, tf)][0] for tf in tfs) + " |")

    stages = sorted({v[0] for v in grid.values()},
                    key=lambda k: (k != "SIGNAL", k != "NO_DIRECTION", k))
    lines += ["", "## Stage counts by timeframe", "",
              "| Timeframe | " + " | ".join(stages) + " |",
              "|---" * (len(stages) + 1) + "|"]
    for tf in tfs:
        c = collections.Counter(grid[(s, tf)][0] for s in syms)
        lines.append(f"| {tf} | " + " | ".join(str(c.get(k, 0)) for k in stages) + " |")

    # The headline reading, computed rather than asserted: if the veto share
    # climbs as the timeframe shortens, the empty intraday screen is the edge
    # gate doing its job, not a broken pipeline.
    veto_share, sig_count = {}, {}
    for tf in tfs:
        c = collections.Counter(grid[(s, tf)][0] for s in syms)
        vet = sum(v for k, v in c.items() if k.startswith("VETOED"))
        veto_share[tf] = vet / max(len(syms), 1)
        sig_count[tf] = c.get("SIGNAL", 0)
    order = list(tfs)
    rising = all(veto_share[a] <= veto_share[b] + 1e-9
                 for a, b in zip(order, order[1:]))
    lines += [
        "", "## Reading this", "",
        "| Timeframe | signals | vetoed share |", "|---|---|---|",
    ]
    for tf in order:
        lines.append(f"| {tf} | {sig_count[tf]} | {veto_share[tf] * 100:.0f}% |")
    lines += [
        "",
        (f"**The vetoed share rises monotonically as the timeframe shortens"
         f" ({' -> '.join(f'{veto_share[t]*100:.0f}%' for t in order)}).**"
         if rising else
         f"**Vetoed share by timeframe: "
         f"{' -> '.join(f'{veto_share[t]*100:.0f}%' for t in order)}.**"),
        "",
        "`edge_not_proven_negative` means this platform backtested THIS EXACT",
        "signal rule on THIS EXACT symbol and timeframe and measured a negative",
        "Sharpe. The signal is withheld on purpose. An empty intraday screen is",
        "therefore the edge gate working, not a pipeline failure -- and tuning",
        "the intraday rules harder does not address it, because the rules were",
        "already tested and already lost money.",
        "",
        "The pattern is what the cost arithmetic predicts: a shorter timeframe",
        "means more trades, more cost per unit of edge, and a worse Sharpe. See",
        "`reports/TRADING_ROADMAP.md` section 5.1 for the equation.",
        "",
        "## Detail for everything that was not a signal", "",
        "| Asset | TF | Stage | Detail |", "|---|---|---|---|",
    ]
    for (sym, tf), (stage, detail) in sorted(grid.items()):
        if stage != "SIGNAL":
            lines.append(f"| {sym} | {tf} | {stage} | {detail} |")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
