"""Backtest the 15-minute ORB setup across every asset, with a year-by-year cut.

The year cut is not optional here. Five leads in this audit passed a pooled
number and died the moment they were split by period -- the long bias (+9.6 in
2017, -3.6 in 2026), relative strength (sign flip every other year), wider stops
(65% of trades silently excluded), and both live A+ strategies. A pooled ORB
result means nothing until it is cut the same way.

Also reported: the same setup with the VWAP filter OFF. If VWAP is doing real
work the gap is visible; if the numbers are the same, the filter is decoration.

    python setups/run_orb_backtest.py
    python setups/run_orb_backtest.py --timeframe 15m --rr 2.0
    python setups/run_orb_backtest.py --no-vwap
    # the "9:30 candle" variant: 5-minute range, retest entry only
    python setups/run_orb_backtest.py --orb-minutes 5 --entry-model retest --out-suffix 5m_retest
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.core.config.assets import SUPPORTED_ASSETS  # noqa: E402
from project_titan_x.setups.orb_setup import (  # noqa: E402
    ORBConfig, build_session_frame, extract_orb_signals, orb_economics,
)

DATA = ROOT / "project_titan_x" / "data" / "processed"
OUT_MD = ROOT / "project_titan_x" / "reports" / "ORB_BACKTEST.md"
OUT_JSON = ROOT / "project_titan_x" / "data" / "models" / "setups" / "orb_backtest.json"


def _yahoo(s):
    a = SUPPORTED_ASSETS.get(s)
    return getattr(a, "yahoo_symbol", s) if a else s


def _load(sym, tf):
    for c in (_yahoo(sym), sym):
        h = glob.glob(str(DATA / f"{c}_{tf}.parquet"))
        if h:
            return pd.read_parquet(h[0])
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="15m")
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--atr-mult", type=float, default=1.0)
    ap.add_argument("--horizon", type=int, default=16)
    ap.add_argument("--orb-minutes", type=int, default=15,
                    help="opening-range length; 5 is the '9:30 candle' variant")
    ap.add_argument("--entry-model", default="momentum",
                    choices=["momentum", "retest", "both"])
    ap.add_argument("--out-suffix", default="",
                    help="suffix for the report files, so variants do not overwrite each other")
    ap.add_argument("--no-vwap", action="store_true")
    args = ap.parse_args()

    common = dict(reward_risk=args.rr, atr_mult=args.atr_mult,
                  horizon_bars=args.horizon, orb_minutes=args.orb_minutes,
                  entry_model=args.entry_model)
    cfg = ORBConfig(require_vwap=not args.no_vwap, **common)
    cfg_novwap = ORBConfig(require_vwap=False, **common)
    out_md, out_json = OUT_MD, OUT_JSON
    if args.out_suffix:
        out_md = OUT_MD.with_name("ORB_BACKTEST_" + args.out_suffix + ".md")
        out_json = OUT_JSON.with_name("orb_backtest_" + args.out_suffix + ".json")

    per_asset, frames, frames_nv = {}, [], []
    for a in list_assets():
        raw = _load(a.symbol, args.timeframe)
        if raw is None or len(raw) < 2000:
            continue
        try:
            d = build_session_frame(raw, cfg)
            if d is None or d.empty:
                continue
            sig = extract_orb_signals(d, cfg)
            # With --no-vwap the two configs are identical; extracting twice
            # would just double the runtime for the same numbers.
            sig_nv = sig if args.no_vwap else extract_orb_signals(d, cfg_novwap)
        except Exception as e:  # noqa: BLE001
            print(f"  {a.symbol:<12} error {str(e)[:40]}", flush=True)
            continue
        if sig.empty:
            continue
        sig["_sym"] = a.symbol
        frames.append(sig)
        if not sig_nv.empty:
            sig_nv["_sym"] = a.symbol
            frames_nv.append(sig_nv)
        e = orb_economics(sig, cfg)
        per_asset[a.symbol] = e
        print(f"  {a.symbol:<12} {e['trades']:>5} tr  win {e['win_rate']*100:5.1f}%  "
              f"net {e['net_pct_per_trade']:+.4f}%", flush=True)

    if not frames:
        print("no ORB signals -- check session hours for this timeframe")
        return 1
    allsig = pd.concat(frames, ignore_index=True)
    pooled = orb_economics(allsig, cfg)
    pooled_nv = orb_economics(pd.concat(frames_nv, ignore_index=True), cfg_novwap) \
        if frames_nv else {"trades": 0}

    allsig["_year"] = pd.to_datetime(allsig["_ts"], utc=True).dt.year
    by_year = []
    for y, g in allsig.groupby("_year"):
        if len(g) < 30:
            continue
        e = orb_economics(g, cfg)
        by_year.append((int(y), e))

    be = 1.0 / (1.0 + cfg.reward_risk)
    lines = [
        f"# {cfg.orb_minutes}-Minute ORB — Backtest ({cfg.entry_model} entry)",
        "",
        f"{len(per_asset)} assets · {args.timeframe} · NY session "
        f"{cfg.session_start_utc}-{cfg.session_end_utc} UTC · opening range "
        f"{cfg.orb_minutes} min · entry **{cfg.entry_model}** · reward:risk "
        f"{cfg.reward_risk}:1 · breakeven "
        f"{be*100:.1f}% · VWAP filter {'OFF' if args.no_vwap else 'ON'}.",
        "",
        f"**Pooled: {pooled['trades']:,} trades · win {pooled['win_rate']*100:.2f}% · "
        f"net {pooled['net_pct_per_trade']:+.4f}%/trade**",
        "",
    ]
    # With --no-vwap the two configs ARE the same config, so this block would
    # compare the run to itself and print "removes 0% of signals". Suppressed
    # rather than printed as a finding.
    if pooled_nv.get("trades") and not args.no_vwap:
        lines += [
            f"With the VWAP filter OFF: {pooled_nv['trades']:,} trades · "
            f"win {pooled_nv['win_rate']*100:.2f}% · net {pooled_nv['net_pct_per_trade']:+.4f}%. "
            f"The filter removes {100*(1-pooled['trades']/pooled_nv['trades']):.0f}% of signals "
            f"and moves the win rate {((pooled['win_rate']-pooled_nv['win_rate'])*100):+.2f} pt.",
            "",
        ]
    lines += [
        "## Year by year",
        "",
        "The cut that killed five previous leads. A setup that only works in some years",
        "is regime exposure, not edge.",
        "",
        "| Year | Trades | Win% | Net %/trade |",
        "|---|---|---|---|",
    ]
    for y, e in by_year:
        mark = "**" if e["net_pct_per_trade"] > 0 else ""
        lines.append(f"| {y} | {e['trades']:,} | {e['win_rate']*100:.1f}% | "
                     f"{mark}{e['net_pct_per_trade']:+.4f}%{mark} |")
    pos_years = sum(1 for _, e in by_year if e["net_pct_per_trade"] > 0)
    lines += [
        "",
        f"**{pos_years} of {len(by_year)} years net-positive.**",
        "",
        "## By asset",
        "",
        "| Asset | Trades | Win% | Net %/trade |",
        "|---|---|---|---|",
    ]
    for sym, e in sorted(per_asset.items(), key=lambda kv: -kv[1]["net_pct_per_trade"]):
        mark = "**" if e["net_pct_per_trade"] > 0 else ""
        lines.append(f"| {sym} | {e['trades']:,} | {e['win_rate']*100:.1f}% | "
                     f"{mark}{e['net_pct_per_trade']:+.4f}%{mark} |")
    lines += [
        "",
        "## Reading this",
        "",
        "- ORB levels are fixed once the opening window closes; VWAP is cumulative to",
        "  date; the volume profile used is the PREVIOUS session's. All causal.",
        "- Entry is the next bar's open, never the close that revealed the break.",
        "- Bars containing both stop and target are scored LOSSES.",
        "- A 24-hour instrument has no natural open, so the NY session is imposed. Read",
        "  those rows as 'does the NY open matter here', not as a true opening range.",
        "- Delta and liquidity-heatmap confluence are NOT included: neither can be",
        "  computed from OHLCV bars, and approximating them would invent a signal.",
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(
        {"config": cfg.to_dict(), "pooled": pooled,
         "pooled_no_vwap": pooled_nv,
         "by_year": {str(y): e for y, e in by_year},
         "by_asset": per_asset}, indent=2, default=str), encoding="utf-8")
    print(f"\npooled {pooled['trades']:,} trades · win {pooled['win_rate']*100:.2f}% · "
          f"net {pooled['net_pct_per_trade']:+.4f}%/trade · {pos_years}/{len(by_year)} years positive")
    print(f"Wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
