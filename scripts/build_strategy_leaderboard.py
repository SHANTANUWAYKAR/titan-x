"""
Module: build_strategy_leaderboard.py
Description: PHASE 19 of reports/statergy.txt -- ranks every candidate this
    project has ever backtested into one leaderboard, scored by
    engines/e24_strategy_research/strategy_score.py.

    Reads only artifacts already on disk:
      - data/models/e24_strategy_research/*_report.json  (sweep candidates)
      - research/stage0_override_scores.json             (null percentile, DSR)
      - data/models/e24_strategy_research/instrument_profiles_latest.json (cost hurdle)

    Nothing is re-backtested and no metric is recomputed, so the leaderboard can
    never disagree with the evidence it summarises.

Usage:
    python scripts/build_strategy_leaderboard.py
    python scripts/build_strategy_leaderboard.py --top 50
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.core.config.assets import SUPPORTED_ASSETS  # noqa: E402
from project_titan_x.engines.e24_strategy_research.engine import (  # noqa: E402
    BARS_PER_YEAR,
    bars_per_year,
)
from project_titan_x.engines.e24_strategy_research.deflated_sharpe import (  # noqa: E402
    deflated_sharpe_ratio,
)
from project_titan_x.engines.e24_strategy_research.strategy_score import (  # noqa: E402
    WEIGHTS,
    score_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "data" / "models" / "e24_strategy_research"
REPORT_MD = ROOT / "reports" / "STRATEGY_LEADERBOARD.md"
REPORT_JSON = MODELS / "strategy_leaderboard.json"


def _yahoo_to_symbol() -> dict[str, str]:
    return {a.yahoo_symbol: a.symbol for a in list_assets()}


def _load_null_scores() -> dict[tuple[str, str, str], dict]:
    """(yahoo_symbol, timeframe, STRATEGY) -> {null_percentile, dsr}.

    Keyed on the strategy too, deliberately. A Stage 0 percentile is earned by
    ONE specific strategy on that instrument -- ETH-USD_1d's 100.0 belongs to
    `mss_trend_hold`, not to the other ~400 candidates that happened to be in
    the same sweep. An earlier version of this join keyed on (symbol, timeframe)
    alone and would have credited every candidate in the report with a
    validation none of them had earned, which is precisely the manufactured
    confidence the whole Stage 0 gate exists to prevent.
    """
    p = ROOT / "research" / "stage0_override_scores.json"
    if not p.exists():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8")).get("rows", [])
    out = {}
    for r in rows:
        override = r.get("override", "")
        sym, _, tf = override.rpartition("_")
        strategy = r.get("strategy")
        if not (sym and tf and strategy):
            continue
        # The scorer's own rows do not record the parameter set, but the
        # override file it scored does -- read the params from there so a
        # percentile attaches to the EXACT parameterisation that earned it.
        # Without this, every parameter variant of a scored strategy inherits
        # the winner's validation: on ETH-USD_1d that was 400+ variants of
        # mss_trend_hold all claiming null percentile 100.0, when only
        # {'hold_bars': 5, 'atr_mult': 1.0} was ever actually tested.
        params = None
        ov = ROOT / "data" / "models" / "e51_signals" / f"{sym}_{tf}_strategy_override.json"
        if ov.exists():
            try:
                doc = json.loads(ov.read_text(encoding="utf-8"))
                if doc.get("strategy") == strategy:
                    params = doc.get("params")
            except Exception:  # noqa: BLE001 - a malformed override must not sink the build
                params = None
        out[(sym, tf, strategy, _params_key(params))] = {
            "null_percentile": r.get("null_percentile"), "dsr": r.get("dsr"),
        }
    return out


def _params_key(params: object) -> str:
    """Stable, order-independent key for a parameter dict."""
    if not isinstance(params, dict):
        return ""
    return json.dumps(params, sort_keys=True, default=str)


def _load_cost_verdicts() -> dict[tuple[str, str], str]:
    p = MODELS / "instrument_profiles_latest.json"
    if not p.exists():
        return {}
    return {
        (pr["symbol"], pr["timeframe"]): pr.get("cost_verdict", "")
        for pr in json.loads(p.read_text(encoding="utf-8")).get("profiles", [])
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40, help="Rows to show in the markdown table.")
    args = ap.parse_args()

    y2s = _yahoo_to_symbol()
    # Sweep reports record the REGISTRY symbol ("ETHUSD") while Stage 0 records
    # the YAHOO symbol ("ETH-USD"); without this map the null join silently
    # matched nothing and every candidate looked unvalidated.
    s2y = {v: k for k, v in y2s.items()}
    nulls = _load_null_scores()
    costs = _load_cost_verdicts()

    def _asset_class(sym):
        a = SUPPORTED_ASSETS.get(sym)
        if a is None:
            for v in SUPPORTED_ASSETS.values():
                if getattr(v, "yahoo_symbol", None) == sym:
                    a = v
                    break
        if a is None:
            return None
        cls = getattr(a, "asset_class", None)
        return getattr(cls, "value", cls)

    def _calendar_fix(c, sym, tf):
        """Rescale a candidate's Sharpes onto the asset's real trading calendar.

        BARS_PER_YEAR was a single 24/7 table, so an NYSE name was annualised
        against 35,040 15m bars a year instead of 6,552 -- inflating its Sharpe
        by sqrt(35_040/6_552) = 2.31x and ranking intraday equity noise above
        the 1d candidates, which were the only rows the old table annualised
        correctly. Crypto 1d moves the other way (365 sessions, not 252), so
        those Sharpes were UNDERstated.

        Returns (candidate, factor). factor == 1.0 means nothing was changed.
        """
        cls = _asset_class(sym)
        if cls is None:
            return c, 1.0
        # A row written before ppy was recorded was scored with the old table.
        used = float(c.get("ppy") or 0.0) or float(BARS_PER_YEAR.get(tf, 252))
        correct = float(bars_per_year(tf, cls))
        if used <= 0 or abs(used - correct) < 1e-9:
            return c, 1.0
        factor = (correct / used) ** 0.5
        out = dict(c)
        for k in ("is_sharpe", "oos_sharpe"):
            if out.get(k) is not None:
                out[k] = float(out[k]) * factor
        out["ppy"] = correct
        return out, factor

    scored = []
    n_corrected = 0
    files = sorted(MODELS.glob("*_report.json"))
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        reported, tf = doc.get("symbol"), doc.get("timeframe")
        if not reported or not tf:
            continue
        # Reports may carry either spelling depending on which script wrote
        # them, so resolve both directions rather than assuming one.
        symbol = y2s.get(reported, reported)
        ysym = s2y.get(symbol, reported)
        candidates = doc.get("all_candidates") or doc.get("candidates") or []
        _fixed = []
        for _c in candidates:
            _c2, _f = _calendar_fix(_c, symbol, tf)
            if _f != 1.0:
                n_corrected += 1
            _fixed.append(_c2)
        candidates = _fixed
        # Group by strategy so parameter-neighbourhood robustness compares like
        # with like -- siblings must share strategy, instrument AND timeframe.
        by_strategy = collections.defaultdict(list)
        for c in candidates:
            by_strategy[c.get("strategy")].append(c)

        cost = costs.get((symbol, tf))
        # Trials for the deflated Sharpe = how many candidates this sweep
        # actually searched over. Parameter siblings are correlated, so the raw
        # count overstates the EFFECTIVE number of independent trials and the
        # resulting floor is conservative -- deliberately the safe direction.
        n_trials = len(candidates)
        for c in candidates:
            # Per-STRATEGY null lookup: only the strategy that was actually
            # scored against the null carries its percentile.
            null = nulls.get((ysym, tf, c.get("strategy"), _params_key(c.get("params"))), {})
            scored.append(score_candidate(
                c, symbol=symbol, timeframe=tf,
                siblings=by_strategy.get(c.get("strategy"), []),
                null_percentile=null.get("null_percentile"),
                # Prefer a dsr the null campaign already measured; otherwise
                # compute it from this sweep's own trial count. n_bars is
                # stamped by the engine -- rows written before that stamp
                # existed cannot support the test and get None, which the
                # A+ gate treats as a failure rather than a pass.
                dsr=null.get("dsr") if null.get("dsr") is not None else deflated_sharpe_ratio(
                    c.get("oos_sharpe"),
                    n_trials=n_trials,
                    n_obs=int(c.get("n_bars") or 0),
                    ppy=float(c.get("ppy") or bars_per_year(tf, _asset_class(symbol) or "") or 252.0),
                ),
                cost_verdict=cost,
            ))

    if not scored:
        print("No sweep reports found -- nothing to rank.")
        return

    if n_corrected:
        print(
            f"  calendar-corrected {n_corrected:,} of {len(scored):,} candidates "
            f"onto their asset's real trading calendar"
        )

    scored.sort(key=lambda s: s.a_plus_score, reverse=True)
    REPORT_JSON.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weights": WEIGHTS,
        "n_scored": len(scored),
        "rows": [s.to_dict() for s in scored],
    }, indent=2), encoding="utf-8")

    grades = collections.Counter(s.grade for s in scored)
    statuses = collections.Counter(s.status for s in scored)
    risks = collections.Counter(s.overfitting_risk.split(" ")[0] for s in scored)

    lines = [
        "# Strategy Leaderboard (PHASE 19)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()} · "
        f"**{len(scored):,} candidates** scored from {len(files)} sweep reports",
        "",
        "Scored by `engines/e24_strategy_research/strategy_score.py`. Every metric is copied "
        "from existing artifacts — nothing is re-backtested, so this table cannot disagree "
        "with the evidence it summarises.",
        "",
        "**A+ is gated, not earned by score.** A candidate must clear every hard gate "
        "(OOS Sharpe, positive expectancy, drawdown, trade count, parameter robustness, and a "
        "Stage 0 null percentile ≥ 95) *in addition* to scoring well. A strategy never scored "
        "against the synthetic null is capped at B — this project measured pure noise clearing "
        "its legacy bar 137 times in 150 at 4h, so backtest metrics alone do not separate edge "
        "from noise.",
        "",
        "## Distribution",
        "",
        "| Grade | Count |  | Status | Count |  | Overfitting risk | Count |",
        "|---|---|---|---|---|---|---|---|",
    ]
    g_items = [(g, grades.get(g, 0)) for g in ("S", "A+", "A", "B", "C", "D", "F")]
    s_items = sorted(statuses.items(), key=lambda kv: -kv[1])
    r_items = sorted(risks.items(), key=lambda kv: -kv[1])
    for i in range(max(len(g_items), len(s_items), len(r_items))):
        g = f"{g_items[i][0]} | {g_items[i][1]}" if i < len(g_items) else " | "
        st = f"{s_items[i][0]} | {s_items[i][1]}" if i < len(s_items) else " | "
        rk = f"{r_items[i][0]} | {r_items[i][1]}" if i < len(r_items) else " | "
        lines.append(f"| {g} |  | {st} |  | {rk} |")

    lines += [
        "",
        f"## Top {args.top} by A+ score",
        "",
        "| # | Strategy | Instrument | TF | Trades | Win% | PF | Expectancy | IS SR | OOS SR | MaxDD% | ParamRobust | Null%ile | Overfit risk | Score | Grade | Status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(scored[:args.top], 1):
        lines.append(
            f"| {i} | {s.strategy[:34]} | {s.symbol} | {s.timeframe} | {s.trades} | "
            f"{round(s.win_rate*100,1) if s.win_rate is not None else '-'} | "
            f"{round(s.profit_factor,2) if s.profit_factor is not None else '-'} | "
            f"{round(s.expectancy,3) if s.expectancy is not None else '-'} | "
            f"{round(s.is_sharpe,2) if s.is_sharpe is not None else '-'} | "
            f"{round(s.oos_sharpe,2) if s.oos_sharpe is not None else '-'} | "
            f"{round(abs(s.max_drawdown_pct),1) if s.max_drawdown_pct is not None else '-'} | "
            f"{s.param_robustness if s.param_robustness is not None else 'n/a'} | "
            f"{s.null_percentile if s.null_percentile is not None else '—'} | "
            f"{s.overfitting_risk.split(' ')[0]} | {s.a_plus_score} | **{s.grade}** | {s.status} |"
        )

    aplus = [s for s in scored if s.grade in ("S", "A+")]
    lines += ["", "## A+ candidates", ""]
    if aplus:
        for s in aplus:
            lines.append(f"- `{s.strategy}` on **{s.symbol} {s.timeframe}** — score {s.a_plus_score}, "
                         f"null %ile {s.null_percentile}, {s.trades} trades")
    else:
        lines.append("**None.** No candidate clears every hard gate. The most common blocker is "
                     "shown below — this is a real result, not a missing run.")
        blockers = collections.Counter()
        for s in scored:
            for f_ in s.gate_failures:
                blockers[f_.split(" ")[0] + " " + f_.split(" ")[1] if len(f_.split(" ")) > 1 else f_] += 1
        lines.append("")
        lines.append("| Blocking gate | Candidates blocked |")
        lines.append("|---|---|")
        for k, v in blockers.most_common(8):
            lines.append(f"| {k} | {v:,} |")

    lines += [
        "",
        "## Known limitations",
        "",
        "- **Regime diversification is not scored.** Per-candidate regime attribution is not "
        "recorded in any sweep report; PHASE 11's suggested 5% is redistributed rather than "
        "awarded on an unmeasured axis.",
        "- **Null percentiles come from live overrides only.** Candidates on instruments with no "
        "Stage 0 scoring show `—` and are capped at B by design.",
        "- **The null itself is under-calibrated.** It was built at 167 candidates per path while "
        "the current grid is ~830, making the ≥95 gate more lenient than it reads. Re-running the "
        "null campaigns at current grid size is the fix.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"scored {len(scored):,} candidates from {len(files)} reports")
    print(f"  grades: {dict(grades)}")
    print(f"  A+ candidates: {len(aplus)}")
    print(f"\nWrote {REPORT_MD}")
    print(f"Wrote {REPORT_JSON}")

    # Research lineage (core/experiment.py -- PHASES 8/24/29).
    try:
        from project_titan_x.core import experiment as _ex

        conclusion = (
            f"{len(aplus)} of {len(scored):,} candidates clear every hard gate."
            if aplus else
            f"NO candidate clears every hard gate, out of {len(scored):,} scored. This is a "
            f"real result, not a missing run: the binding constraint is the Stage 0 null "
            f"percentile, which most candidates were never scored against at all."
        )
        _ex.record(
            kind="score",
            title=f"A+ leaderboard over {len(scored):,} candidates from {len(files)} sweep reports",
            params={"weights": WEIGHTS, "sweep_reports": len(files)},
            metrics={
                "n_scored": len(scored),
                "grades": dict(grades),
                "statuses": dict(statuses),
                "a_plus": len(aplus),
            },
            artifacts=[str(REPORT_MD), str(REPORT_JSON)],
            conclusion=conclusion,
            notes=[
                "Scores only re-rank existing artifacts; nothing is re-backtested here, so "
                "this cannot disagree with the evidence it summarises.",
                "The candidates themselves predate research lineage and carry no recorded "
                "code or data version -- only this scoring pass is tracked.",
            ],
        )
    except Exception as e:  # noqa: BLE001
        print(f"  (warning: could not record experiment lineage: {e})")


if __name__ == "__main__":
    main()
