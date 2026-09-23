"""
Module: build_instrument_profiles.py
Description: Builds a PHASE 3 research profile for every (instrument, timeframe)
    from real cached OHLCV, and writes both a JSON artifact and a readable
    report. See engines/e24_strategy_research/instrument_profile.py for what is
    measured and why.

    Reads data/processed/*.parquet only -- no network, no fetching. That keeps
    a full 29-instrument run to seconds of local compute rather than an hour of
    API calls, and makes it reproducible: the same parquet files produce the
    same profiles.

Usage:
    python scripts/build_instrument_profiles.py
    python scripts/build_instrument_profiles.py --timeframes 1h 4h 1d
    python scripts/build_instrument_profiles.py --symbols GOLD BTCUSD
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd  # noqa: E402

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine  # noqa: E402
from project_titan_x.engines.e12_quant_research.engine import QuantResearchEngine  # noqa: E402
from project_titan_x.engines.e24_strategy_research.instrument_profile import (  # noqa: E402
    build_profile,
    save_profiles,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "INSTRUMENT_PROFILES.md"
DEFAULT_TIMEFRAMES = ["15m", "1h", "4h", "1d"]
MAX_BARS = 5000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", nargs="*", default=DEFAULT_TIMEFRAMES)
    ap.add_argument("--symbols", nargs="*", default=None, help="Registry symbols; default = all supported assets.")
    args = ap.parse_args()

    assets = list_assets()
    if args.symbols:
        wanted = {s.upper() for s in args.symbols}
        assets = [a for a in assets if a.symbol.upper() in wanted]

    te = TechnicalAnalysisEngine(); te.initialize()
    qe = QuantResearchEngine(); qe.initialize()

    profiles = []
    for asset in assets:
        for tf in args.timeframes:
            pq = DATA_DIR / f"{asset.yahoo_symbol}_{tf}.parquet"
            if not pq.exists():
                continue
            df = pd.read_parquet(pq).tail(MAX_BARS).reset_index(drop=True)
            # Enrich so atr/adx are the platform's own values rather than a
            # second derivation -- build_profile falls back to high/low when
            # enrichment is unavailable, but that is the degraded path.
            try:
                res = te.analyze(df, symbol=asset.yahoo_symbol, timeframe=tf)
                enriched = res.data["df"] if res.success and res.data else df
            except Exception as e:  # noqa: BLE001
                logging.warning("%s %s: enrichment failed (%s) -- profiling raw OHLCV", asset.symbol, tf, e)
                enriched = df

            p = build_profile(enriched, asset.symbol, tf, quant_engine=qe)
            profiles.append(p)
            top = p.suitable_families[0]["family"] if p.suitable_families else "-"
            print(f"{asset.symbol:11} {tf:4} bars={p.bars:5} H={str(p.hurst):6} "
                  f"cost/ATR={str(p.cost_atr_ratio):6} ({p.cost_verdict:11}) -> {top}", flush=True)

    if not profiles:
        print("No profiles built -- no matching parquet files found.")
        return

    target = save_profiles(profiles)

    lines = [
        "# Instrument Research Profiles (PHASE 3)",
        "",
        f"Generated: {profiles[0].generated_at} · {len(profiles)} (instrument, timeframe) profiles",
        "",
        "Per `reports/statergy.txt` PHASE 3. `suitable_families` are **hypotheses for the "
        "search to test**, not validated edges — nothing here promotes a strategy or "
        "substitutes for E26 validation and the Stage 0 null.",
        "",
        "**cost/ATR** = one round trip's modelled cost (0.30% at E26 defaults) ÷ median bar "
        "range. At ≥1.0 the average bar cannot pay for the trade — a property of the "
        "instrument and timeframe, not of any strategy.",
        "",
        "| Instrument | TF | Bars | Hurst | Character | Vol% | Bar range% | cost/ATR | Cost verdict | Top family prior |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in profiles:
        top = f"{p.suitable_families[0]['family']} ({p.suitable_families[0]['prior_score']})" if p.suitable_families else "-"
        lines.append(
            f"| {p.symbol} | {p.timeframe} | {p.bars} | {p.hurst} | {p.hurst_interpretation} | "
            f"{p.annualised_vol_pct} | {p.median_bar_range_pct} | {p.cost_atr_ratio} | "
            f"{p.cost_verdict} | {top} |"
        )

    prohibitive = [p for p in profiles if p.cost_verdict == "prohibitive"]
    severe = [p for p in profiles if p.cost_verdict == "severe"]
    lines += [
        "",
        "## Cost-hurdle summary",
        "",
        f"- **prohibitive** (costs ≥ median bar range): {len(prohibitive)} of {len(profiles)}",
        f"- **severe** (costs ≥ 50% of median bar range): {len(severe)}",
        f"- **workable**: {len(profiles) - len(prohibitive) - len(severe)}",
        "",
    ]
    if prohibitive:
        lines.append("Prohibitive combinations — trading these at this timeframe is arithmetically "
                     "unattractive before any signal is considered:")
        lines.append("")
        for p in prohibitive:
            lines.append(f"- `{p.symbol} {p.timeframe}` — cost/ATR {p.cost_atr_ratio}")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {target}")
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
