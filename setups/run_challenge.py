"""Growth-challenge ladder: $1 -> $10 -> $100 -> $1,000 and up.

WHAT THIS ANSWERS. Not "can it be done" -- someone somewhere always does it --
but "what fraction of accounts running THIS edge, at THIS risk, on THIS
instrument, arrive before they are broke". Together with the ruin rate and the
zero-edge null, that is the whole honest answer.

THREE SOURCES OF TRADES, and the difference between them is the point:

  --from-hp       the realised per-trade R multiples from
                  setups/run_high_profile.py -- a real, fat-tailed distribution
                  measured on this book's own data.
  --from-orb      the ORB backtest's win rate and reward:risk, expanded into a
                  binary pool. Honest for a fixed-target setup, where every
                  win IS the same size.
  --win-rate/--rr a CLAIMED edge, so a claim can be run through the identical
                  machine as a measurement and the two compared directly.

Costs must already be inside the R multiples. Feeding gross R in removes the
term that decides the answer, which is the single most common way a challenge
plan is made to look survivable.

    python setups/run_challenge.py --from-hp --instrument mnq --risk 0.01
    python setups/run_challenge.py --win-rate 0.40 --rr 2.0 --risk 0.10
    python setups/run_challenge.py --from-orb --instrument crypto --risk 0.02
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_titan_x.setups.challenge import (  # noqa: E402
    DEFAULT_LADDER, MIN_RISK_USD, kelly_fraction, run_ladder,
)

MODELS = ROOT / "project_titan_x" / "data" / "models" / "setups"
HP_JSON = MODELS / "high_profile_setup.json"
ORB_JSON = MODELS / "orb_backtest.json"
OUT_MD = ROOT / "project_titan_x" / "reports" / "CHALLENGES.md"
OUT_JSON = MODELS / "challenge_ladder.json"


def _pool_from_hp(path: Path, filtered: bool) -> tuple[np.ndarray, str]:
    d = json.loads(path.read_text(encoding="utf-8"))
    key = "r_net_rvol_filtered" if filtered else "r_net_all"
    # The R multiples live in a compact sibling file; older results embedded
    # them directly, so both are accepted.
    sib = path.with_name(d.get("r_multiples_file")
                         or (path.stem + "_rmultiples.json"))
    pool = []
    if sib.exists():
        pool = json.loads(sib.read_text(encoding="utf-8")).get(key) or []
    if not pool:
        pool = d.get(key) or []
    if not pool:
        raise SystemExit(
            f"{path.name} has no '{key}'. Re-run setups/run_high_profile.py "
            "-- older report files predate the R-multiple dump.")
    cfg = d.get("config", {})
    label = (f"high-profile ORB ({'RVOL top-N' if filtered else 'unfiltered'}), "
             f"{cfg.get('orb_minutes', '?')}-min range, {cfg.get('stop_model', '?')} stop, "
             f"{cfg.get('cost_bps_round_trip', '?')} bps round-trip cost")
    return np.asarray(pool, dtype=float), label


def _pool_from_orb(path: Path, n: int = 20_000) -> tuple[np.ndarray, str]:
    d = json.loads(path.read_text(encoding="utf-8"))
    pooled, cfg = d.get("pooled", {}), d.get("config", {})
    wr = float(pooled.get("win_rate", 0.0))
    rr = float(cfg.get("reward_risk", 2.0))
    cost_r = 0.0
    net = pooled.get("net_pct_per_trade")
    gross = pooled.get("gross_pct_per_trade")
    risk = float(cfg.get("risk_pct", 0.01))
    if net is not None and gross is not None and risk > 0:
        # net and gross are percent of account; the gap is cost, converted back
        # into R by dividing by the risk fraction. Carrying it explicitly keeps
        # the pool NET, which is what the ladder requires.
        cost_r = (float(gross) - float(net)) / (risk * 100.0)
    wins = int(round(n * wr))
    pool = np.concatenate([np.full(wins, rr - cost_r),
                           np.full(n - wins, -1.0 - cost_r)])
    label = (f"ORB backtest: {pooled.get('trades', 0):,} trades, win {wr*100:.2f}%, "
             f"{rr:.1f}R target, cost {cost_r:.4f} R/trade")
    return pool, label


def _pool_from_claim(win_rate: float, rr: float, cost_r: float,
                     n: int = 20_000) -> tuple[np.ndarray, str]:
    wins = int(round(n * win_rate))
    pool = np.concatenate([np.full(wins, rr - cost_r),
                           np.full(n - wins, -1.0 - cost_r)])
    return pool, (f"CLAIMED edge: {win_rate*100:.1f}% win rate at {rr:.1f}R, "
                  f"cost {cost_r:.4f} R/trade -- not measured on this book")


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--from-hp", action="store_true",
                     help="realised R multiples from the high-profile backtest")
    src.add_argument("--from-orb", action="store_true",
                     help="win rate and R:R from the ORB backtest")
    ap.add_argument("--rvol-filtered", action="store_true",
                    help="with --from-hp, use the RVOL top-N subset")
    ap.add_argument("--hp-json", default=None,
                    help="a suffixed high-profile result file, e.g. orbstop_cost30")
    ap.add_argument("--win-rate", type=float, default=None)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--claim-cost-r", type=float, default=0.0,
                    help="cost in R per trade for a claimed edge (0 = the claim's own assumption)")
    ap.add_argument("--risk", type=float, default=0.01,
                    help="intended fraction of the balance risked per trade")
    ap.add_argument("--instrument", default="none", choices=sorted(MIN_RISK_USD))
    ap.add_argument("--min-risk-usd", type=float, default=None,
                    help="override the instrument's minimum ticket")
    ap.add_argument("--sims", type=int, default=4000)
    ap.add_argument("--max-trades", type=int, default=2000)
    ap.add_argument("--start", type=float, default=None,
                    help="single custom rung start, used with --target")
    ap.add_argument("--target", type=float, default=None)
    ap.add_argument("--out-suffix", default="")
    args = ap.parse_args()

    if args.from_hp:
        path = (MODELS / f"high_profile_setup_{args.hp_json}.json"
                if args.hp_json else HP_JSON)
        if not path.exists():
            raise SystemExit(f"{path} does not exist -- run setups/run_high_profile.py first")
        pool, label = _pool_from_hp(path, args.rvol_filtered)
    elif args.from_orb:
        pool, label = _pool_from_orb(ORB_JSON)
    elif args.win_rate is not None:
        pool, label = _pool_from_claim(args.win_rate, args.rr, args.claim_cost_r)
    else:
        ap.error("pick a source: --from-hp, --from-orb, or --win-rate")

    out_md, out_json = OUT_MD, OUT_JSON
    if args.out_suffix:
        out_md = OUT_MD.with_name("CHALLENGES_" + args.out_suffix + ".md")
        out_json = OUT_JSON.with_name("challenge_ladder_" + args.out_suffix + ".json")

    ladder = DEFAULT_LADDER
    if args.start is not None and args.target is not None:
        ladder = ((args.start, args.target),)

    res = run_ladder(pool, ladder=ladder, risk_frac=args.risk,
                     instrument=args.instrument, min_risk_usd=args.min_risk_usd,
                     n_sims=args.sims, max_trades=args.max_trades)
    if res is None:
        print("trade pool too small (<30)")
        return 1

    floor = (MIN_RISK_USD[args.instrument] if args.min_risk_usd is None
             else args.min_risk_usd)
    kelly = kelly_fraction(res.win_rate, res.reward_risk)

    lines = [
        "# Challenges — $1 to $100, $100 to $1,000, and up",
        "",
        f"**Edge under test:** {label}",
        "",
        f"Win rate **{res.win_rate*100:.2f}%** · reward:risk **{res.reward_risk:.2f}** · "
        f"expectancy **{res.expectancy_r:+.4f} R** · pool {res.n_trades_in_pool:,} trades.",
        "",
        f"Intended risk **{args.risk*100:.2f}%** of balance per trade · instrument "
        f"**{args.instrument}** · minimum ticket risk **${floor:,.2f}** · "
        f"{args.sims:,} simulations per rung · at most {args.max_trades:,} trades per path.",
        "",
        f"**Kelly fraction at this edge: {kelly*100:+.2f}%.** "
        + ("Negative, which means the size that loses least is zero -- every rung below "
           "is a measurement of how fast the account dies, not of how it grows."
           if kelly < 0 else
           f"Risking {args.risk*100:.2f}% is "
           f"{'below' if args.risk < kelly else 'ABOVE'} full Kelly."),
        "",
        "| Rung | x | Reach | Null | **Lift** | Ruin | Timeout | Median trades | Median end | Forced risk |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in res.rungs:
        if not r.possible:
            lines.append(
                f"| ${r.start:,.0f} to ${r.target:,.0f} | {r.multiple:.0f}x | "
                f"**IMPOSSIBLE** | — | — | — | — | — | — | "
                f"{r.forced_risk_frac_at_start*100:.0f}% |")
            continue
        mt = f"{r.median_trades_to_target:,.0f}" if r.median_trades_to_target else "—"
        lines.append(
            f"| ${r.start:,.0f} to ${r.target:,.0f} | {r.multiple:.0f}x | "
            f"{r.pass_rate*100:.2f}% | {r.null_pass_rate*100:.2f}% | "
            f"**{r.edge_lift*100:+.2f} pt** | {r.ruin_rate*100:.2f}% | "
            f"{r.timeout_rate*100:.2f}% | {mt} | ${r.median_final:,.2f} | "
            f"{r.forced_risk_frac_at_start*100:.2f}% |")

    impossible = [r for r in res.rungs if not r.possible]
    if impossible:
        lines += ["", "## Rungs that are a funding problem, not a trading problem", ""]
        for r in impossible:
            lines.append(f"- **${r.start:,.2f} to ${r.target:,.2f}** — {r.reason}")

    lines += [
        "",
        "## How to read this",
        "",
        "- **Reach** is the share of simulated accounts that touched the target before",
        "  they could no longer place a trade. **Null** is the same simulation with the",
        "  expectancy recentred to exactly zero and the win rate and R:R shape left",
        "  intact. **Lift** is the difference — the only part the edge earned.",
        "- **Forced risk** is what the FIRST trade actually risks once the minimum",
        "  ticket is applied. When it is far above the intended risk, the plan on paper",
        "  is not the plan being executed.",
        "- Trades are resampled i.i.d., so losing streaks never cluster the way a real",
        "  regime makes them. Every reach rate here is an **upper bound**.",
        "- Timeout means the path neither arrived nor died inside the trade budget.",
        "  A high timeout rate at a negative expectancy is not survival; it is an",
        "  account grinding down slowly enough to run out of simulation first.",
    ]
    lines += ["", "## Caveats carried from the simulator", ""]
    lines += [f"- {n}" for n in res.notes]

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(
        {"source": label, "risk_frac": args.risk, "instrument": args.instrument,
         "min_risk_usd": floor, "kelly_fraction": kelly, **res.to_dict()},
        indent=2, default=str), encoding="utf-8")

    print(f"\n{label}")
    print(f"win {res.win_rate*100:.2f}% · RR {res.reward_risk:.2f} · "
          f"expectancy {res.expectancy_r:+.4f} R · Kelly {kelly*100:+.2f}%")
    for r in res.rungs:
        if not r.possible:
            print(f"  ${r.start:>9,.0f} -> ${r.target:>9,.0f}  IMPOSSIBLE "
                  f"(min ticket = {r.forced_risk_frac_at_start*100:.0f}% of account)")
        else:
            print(f"  ${r.start:>9,.0f} -> ${r.target:>9,.0f}  reach {r.pass_rate*100:6.2f}%  "
                  f"null {r.null_pass_rate*100:6.2f}%  lift {r.edge_lift*100:+6.2f} pt  "
                  f"ruin {r.ruin_rate*100:6.2f}%")
    print(f"Wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
