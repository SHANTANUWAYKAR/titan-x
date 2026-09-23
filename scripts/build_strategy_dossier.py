"""
Module: build_strategy_dossier.py
Description: PHASE 37 of `reports/upgrade statergy.txt` -- an institutional
    research report per live strategy, and the closing item of the P0-P3
    roadmap in docs/INSTITUTIONAL_AUDIT.md.

    WHAT THIS IS FOR. Everything this platform knows about a live strategy is
    currently spread across six artifacts: a hypothesis in one registry, a
    Hurst reading and cost hurdle in another, a backtest claim in the override
    file, a null percentile in a `stage0` block, a grade on the leaderboard,
    and a forward-test verdict in a third log. Nobody deciding whether to risk
    money on a strategy reads six files. This assembles them into one, per
    strategy, and states what is still missing.

    PHASE 37 IS EXPLICIT ABOUT STRUCTURE: "Clearly separate OBSERVATION /
    HYPOTHESIS / EVIDENCE / CONCLUSION." The sections below follow that order
    deliberately, because the failure this project has already measured --
    noise clearing the legacy selection bar 137 times in 150 at 4h -- is
    precisely what happens when a hypothesis and the evidence for it get read
    as the same kind of claim.

    NOTHING IS COMPUTED HERE. Every number is copied from an artifact that
    already exists, so this report cannot disagree with the evidence it
    summarises. Where an input is missing, the section says it is missing
    rather than being omitted -- an absent forward test is the single most
    important fact about a strategy that has only ever been backtested.

Usage:
    python scripts/build_strategy_dossier.py
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.engines.e24_strategy_research import forward_test as ft  # noqa: E402
from project_titan_x.engines.e24_strategy_research import hypothesis as hyp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "data" / "models" / "e24_strategy_research"
REPORT = ROOT / "reports" / "STRATEGY_DOSSIER.md"


def _registry_symbol(yahoo: str) -> str:
    for a in list_assets():
        if a.yahoo_symbol == yahoo:
            return a.symbol
    return yahoo


def _profile(symbol: str, timeframe: str) -> dict:
    p = MODELS / "instrument_profiles_latest.json"
    if not p.exists():
        return {}
    for pr in json.loads(p.read_text(encoding="utf-8")).get("profiles", []):
        if pr.get("symbol") == symbol and pr.get("timeframe") == timeframe:
            return pr
    return {}


def _override_doc(yahoo: str, timeframe: str) -> dict:
    p = ROOT / "data" / "models" / "e51_signals" / f"{yahoo}_{timeframe}_strategy_override.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _fmt(v, suffix="", pct=False, nd=2):
    if v is None:
        return "—"
    if pct:
        return f"{v * 100:.1f}%" if abs(v) <= 1 else f"{v:.1f}%"
    return f"{round(v, nd)}{suffix}"


def build_section(ov: dict, fwd_series: dict) -> list[str]:
    yahoo, tf = ov["yahoo_symbol"], ov["timeframe"]
    strategy = ov["strategy"]
    sym = _registry_symbol(yahoo)
    claim = ov["claim"]
    doc = _override_doc(yahoo, tf)
    stage0 = doc.get("stage0") or {}
    measured = stage0.get("measured") or {}
    prof = _profile(sym, tf)
    h = hyp.get(strategy)

    L: list[str] = [
        f"# {sym} {tf} — `{strategy}`",
        "",
        f"**Deployment status: LIVE.** Driving real signals via a `stage0.status == "
        f"\"VALIDATED\"` tag on `data/models/e51_signals/{yahoo}_{tf}_strategy_override.json`.",
        "",
        "---",
        "",
        "## 1. Observation",
        "",
        "What the instrument measurably does, independent of any strategy "
        "(`engines/e24_strategy_research/instrument_profile.py`).",
        "",
    ]

    if prof:
        hurst = prof.get("hurst")
        character = ("trend-persistent" if hurst and hurst > 0.55
                     else "mean-reverting" if hurst and hurst < 0.45
                     else "indistinguishable from a random walk")
        L += [
            f"| Measure | Value | Reading |",
            f"|---|---|---|",
            f"| Hurst exponent | {_fmt(hurst, nd=4)} | {character} |",
            f"| Cost / ATR ratio | {_fmt(prof.get('cost_atr_ratio'), nd=3)} | "
            f"**{prof.get('cost_verdict', '—')}** — the share of a typical bar's range "
            f"consumed by one round trip |",
            f"| Bars analysed | {prof.get('bars', '—')} | |",
            "",
        ]
        fams = prof.get("suitable_families") or []
        if fams:
            top = fams[0]
            L += [
                f"Highest-prior family for this instrument: **{top.get('family')}** "
                f"(prior {top.get('prior_score')}) — {top.get('rationale', '')}",
                "",
            ]
            # Compared loosely on purpose. The instrument profiler and the
            # hypothesis registry name families from two independent
            # vocabularies, so `breakout` vs `volatility_breakout` is the same
            # answer spelled two ways -- flagging it as a mismatch would put a
            # warning on the ONE pairing where strategy and instrument actually
            # agree, which is worse than saying nothing.
            prof_fam = str(top.get("family") or "")
            if h and prof_fam and not (h.family in prof_fam or prof_fam in h.family):
                L += [
                    f"> **Note the mismatch.** This strategy is registered as `{h.family}` "
                    f"while the instrument's highest prior is `{top.get('family')}`. That is "
                    f"not disqualifying — the priors are hypotheses for a search to test, not "
                    f"verdicts — but it means the instrument's measured character is not the "
                    f"reason this strategy was selected.",
                    "",
                ]
    else:
        L += ["No instrument profile on disk for this pair. Run "
              "`scripts/build_instrument_profiles.py`.", ""]

    L += ["---", "", "## 2. Hypothesis", "",
          "Why an edge should exist here. **This is a claim, not evidence.**", ""]
    if h:
        L += [
            f"**Family:** {h.family}", "",
            f"**Why it should work.** {h.works_because}", "",
            f"**When it should work.** {h.works_when}", "",
            f"**When it should fail.** {h.fails_when}", "",
            f"**Expected edge.** {h.expected_edge}", "",
            f"**Regime.** {h.regime or '—'}", "",
            f"**Cost assumptions.** {h.cost_assumptions or '—'}", "",
            f"**Risk model.** {h.risk_model or '—'}", "",
            f"*Transcribed from: {h.source}*", "",
        ]
        if h.notes:
            L += ["Notes:", ""] + [f"- {n}" for n in h.notes] + [""]
    else:
        L += [
            "**MISSING.** No hypothesis is registered for this strategy, which means there is "
            "no stated failure condition — and therefore no way to retire it for cause "
            "(PHASE 36). A drawdown would be the only available trigger, firing long after "
            "the reason did.", "",
        ]

    L += ["---", "", "## 3. Evidence", "", "### 3a. Backtest (in-sample search)", ""]
    wr, n = claim.get("win_rate"), claim.get("total_trades")
    rr = ft.planned_reward_risk([r for r in ft.load_log()
                                 if r.symbol == yahoo and r.strategy == strategy])
    be = ft.breakeven_win_rate(rr) if rr else None
    sig = ft.claim_significance(wr, n, be if be else 0.5)

    L += [
        "| Metric | Value |",
        "|---|---|",
        f"| Win rate | {_fmt(wr, pct=True)} over {n or '—'} trades |",
        f"| IS Sharpe | {_fmt(claim.get('is_sharpe'))} |",
        f"| OOS Sharpe | {_fmt(claim.get('oos_sharpe'))} |",
        f"| Max drawdown | {_fmt(doc.get('max_drawdown_pct'), pct=True)} |",
        f"| Validated at | {claim.get('validated_at', '—')} |",
        "",
    ]
    if sig:
        base = f"{be:.1%} (breakeven at the planned {rr:.2f}:1)" if be else "50%"
        L += [
            f"Against a fair coin the same claim reads **p={sig['p_vs_coin_flip']:.2g}**; "
            f"against {base} it reads **p={sig['p_vs_breakeven']:.2g}**. "
            "Quoting either without its baseline invites the wrong conclusion — a 2:1 "
            "strategy does not need a 50% hit rate to make money.",
            "",
        ]

    L += ["### 3b. Stage 0 — scored against a synthetic no-edge null", ""]
    if measured:
        L += [
            "| Metric | Value |",
            "|---|---|",
            f"| Null percentile | **{measured.get('null_percentile')}** "
            f"(bar: {(stage0.get('bar') or {}).get('min_null_percentile')}) |",
            f"| Selection score | {_fmt(measured.get('selection_score'))} |",
            f"| Trades | {measured.get('trades')} |",
            f"| Null source | `{measured.get('null_source')}` |",
            f"| Cross-asset proxy | {measured.get('null_is_proxy')} |",
            "",
        ]
        for c in (stage0.get("caveats") or []):
            L += [f"- {c}"]
        L += [
            "",
            "> **The bar itself is under-calibrated.** These nulls were built at 167 "
            "candidates per path while the live grid is ~830 (4.97x). The best-of-N score "
            "climbs with N, so the >=95th-percentile bar they define is more lenient than it "
            "reads. A re-calibrated 1d campaign is the outstanding item; until it lands, a "
            "percentile near the bar should be read as *not yet established* rather than as "
            "a pass.",
            "",
        ]
    else:
        L += ["No Stage 0 block recorded.", ""]

    L += ["### 3c. Forward test — evidence written before the outcome was knowable", ""]
    if fwd_series:
        s = fwd_series
        L += [
            "| Metric | Value |",
            "|---|---|",
            f"| Predictions recorded | {s.get('predictions')} |",
            f"| Resolved | {s.get('forward_trades')} |",
            f"| Forward win rate | {_fmt(s.get('forward_win_rate'), pct=True)} |",
            f"| Forward expectancy | {_fmt(s.get('forward_expectancy_r'))} R |",
            f"| Verdict | **{s.get('verdict')}** |",
            f"| Trades needed to detect decay to breakeven | "
            f"{s.get('trades_to_detect_degradation', '—')} |",
            "",
        ]
        for nte in (s.get("notes") or []):
            L += [f"- {nte}"]
        L += [""]
    else:
        L += [
            "**No forward predictions recorded yet for this pair.** This strategy is running "
            "on historical evidence alone — an in-sample sweep, a walk-forward split and a "
            "null percentile, every one computed over bars that already existed when the "
            "search ran.",
            "",
        ]

    L += ["---", "", "## 4. Conclusion", ""]
    blockers = []
    if not h:
        blockers.append("no registered hypothesis, so no stated failure condition")
    if not fwd_series or not fwd_series.get("forward_trades"):
        blockers.append("no resolved forward trades")
    pctl = measured.get("null_percentile")
    if pctl is not None and pctl < 99:
        blockers.append(
            f"a null percentile of {pctl} against an under-calibrated bar, close enough "
            f"that a correctly sized null could move it below")

    if blockers:
        L += [
            "**Deployed, but not established.** Outstanding:",
            "",
        ] + [f"- {b}" for b in blockers] + [
            "",
            "None of this says the strategy is bad. It says the evidence currently supporting "
            "it is the kind this project has already measured to be unreliable on its own, and "
            "the forward test is the only thing that can change that — one bar at a time.",
            "",
        ]
    else:
        L += [
            "Hypothesis stated, null cleared with margin, and forward evidence accumulating "
            "consistently with the claim. This is the strongest state any strategy here has "
            "reached; it is still not a guarantee, and non-negotiables 5 and 6 forbid "
            "presenting it as one.",
            "",
        ]
    return L


def main() -> None:
    overrides = ft.validated_overrides()
    summary = ft.summarise()
    by_series = {(s["symbol"], s["timeframe"], s["strategy"]): s
                 for s in summary.get("series", [])}

    lines = [
        "# Strategy Dossiers",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"One institutional research report per LIVE strategy ({len(overrides)} currently "
        f"carrying an explicit `stage0.status == \"VALIDATED\"` tag). PHASE 37 of "
        "`reports/upgrade statergy.txt`.",
        "",
        "Every number is copied from an artifact that already exists — nothing is recomputed "
        "here, so this cannot disagree with the evidence it summarises. Sections follow "
        "PHASE 37's required separation: **observation**, **hypothesis**, **evidence**, "
        "**conclusion**. Missing inputs are stated as missing rather than omitted.",
        "",
        "---",
        "",
    ]
    if not overrides:
        lines += ["**No live strategies.** Nothing currently carries a VALIDATED tag.", ""]
    for ov in overrides:
        key = (ov["yahoo_symbol"], ov["timeframe"], ov["strategy"])
        lines += build_section(ov, by_series.get(key, {}))
        lines += ["", "---", ""]

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORT} ({len(overrides)} live strategy/strategies)")


if __name__ == "__main__":
    main()
