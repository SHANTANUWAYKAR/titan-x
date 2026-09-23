# ICT Concept Diff — STAR-EA vs Titan X

**Date:** 2026-09-08. **Purpose:** establish the real scope of the brief's Phase 5 by diffing
`external/STAR-EA-v11.20/STAR_v11.20.mq5` (51,396 lines, MQL5, MIT) against what Titan X already
implements — separating what is **live** from what is **written but unreachable**.

**Method:** pattern-match each concept across three code bases independently
(`engines/e07_technical/`, `research/`, the STAR-EA source), then hand-verify every hit that changed
a verdict. Two did (§4).

---

## 1. The headline

**Titan X's ICT gap is not a knowledge gap. It is a wiring gap.**

| Where | Count | Concepts |
|---|---|---|
| **Live in E07** | 9 | FVG, FVG mitigation, order blocks, **breaker blocks**, BOS, CHoCH, liquidity sweeps, killzones, Silver Bullet |
| **Written in `research/`, never reaches a signal** | **17** | Inversion FVG, consequent encroachment, balanced price range, MSS, displacement, equal highs/lows, PDH/PDL, premium/discount, dealing range, OTE, Judas Swing, AMD, Power of 3, turtle soup, inducement, SMT divergence, draw on liquidity |
| **Only in STAR-EA** | **1** | **CRT (Candle Range Theory)** |
| **Absent everywhere** | 1 | **CISD** |

`research/ict_concepts.py` implements 17 concepts. **No engine imports it** — correctly, since Rule 2
forbids `engines/` importing `research/`. The consequence is that they are offline research and have
never influenced a live signal.

So the brief's Phase 5 — "build a deterministic specification for 28 ICT concepts" — is largely
already done. **26 of 28 exist as code.** The open questions are which of the stranded 17 deserve
porting, and whether CRT is worth building at all.

---

## 2. Full matrix

Counts are pattern hits, used for triage only; verdicts were hand-verified.

| Concept | E07 live | `research/` | STAR-EA | Verdict |
|---|---|---|---|---|
| Fair Value Gap | 10 | 13 | 331 | live |
| FVG mitigation | 6 | 5 | 250 | live |
| Order blocks | 18 | 8 | 21 | live |
| **Breaker blocks** | **9** | 1 | 311 | **live** (see §4) |
| BOS | 8 | 8 | 76 | live |
| CHoCH | 22 | 21 | 398 | live |
| Liquidity sweep | 14 | 12 | 0 | live |
| Killzones | 36 | 35 | 713 | live |
| **Silver Bullet** | **16** | 0 | 132 | **live** (see §4) |
| Inversion FVG | 0 | 5 | 0 | stranded |
| Consequent encroachment | 0 | 3 | 0 | stranded |
| Balanced price range | 0 | 8 | 1 | stranded |
| MSS | 0 | 22 | 0 | stranded |
| Displacement | 0 | 24 | 19 | stranded |
| Equal highs/lows | 0 | 17 | 0 | stranded |
| PDH/PDL | 0 | 30 | 40 | stranded |
| Premium/discount | 0 | 31 | 177 | stranded |
| Dealing range | 0 | 4 | 0 | stranded |
| OTE | 0 | 8 | 125 | stranded |
| Judas Swing | 0 | 6 | 561 | stranded |
| AMD cycle | 0 | 5 | 77 | stranded |
| Power of 3 | 0 | 3 | 0 | stranded |
| Turtle soup | 0 | 4 | 0 | stranded |
| Inducement | 0 | 5 | 0 | stranded |
| SMT divergence | 0 | 6 | 0 | stranded |
| Draw on liquidity | 0 | 3 | 0 | stranded |
| **CRT** | **0** | **0** | **92** | **new from STAR-EA** |
| **CISD** | **0** | **0** | **0** | **no source anywhere** |

---

## 3. What the ablation already decided

This is the part that matters, and it removes almost all of the judgement.

`research/ablation_{BTCUSD,ETHUSD,GOLD}_4h.json` already measured **solo expectancy per concept** on
three assets. Concepts positive on **every** asset tested:

| Concept | BTCUSD | ETHUSD | GOLD | trades (B/E/G) | status |
|---|---|---|---|---|---|
| `choch_only` | +0.748 | +1.066 | +0.208 | 52 / 60 / 40 | already live |
| `order_block` | +0.647 | +1.208 | — | 102 / 95 | already live |
| `bos_choch` | +0.597 | +1.222 | — | 103 / 96 | already live |
| **`mss`** | **+0.474** | **+0.915** | **+0.015** | **69 / 69 / 46** | **stranded** |
| **`eqh_eql`** | **+0.619** | **+0.079** | **+0.610** | **26 / 20 / 24** | **stranded** |
| **`power_of_three`** | **+0.113** | **+0.095** | **+0.022** | **50 / 32 / 29** | **stranded** |

Everything else stranded in `research/` measured **negative or mixed**:

| Concept | BTCUSD | ETHUSD | GOLD | read |
|---|---|---|---|---|
| `inverse_fvg` | −0.208 | −0.569 | −0.270 | negative on all three |
| `ce` (consequent encroachment) | −0.440 | −0.485 | −0.087 | negative on all three |
| `bpr` (balanced price range) | −0.469 | −0.052 | −0.166 | negative on all three |
| `turtle_soup` | −0.289 | −0.280 | −0.213 | negative on all three |
| `displacement` | −0.171 | −0.019 | −0.063 | negative on all three |
| `premium_discount` | +0.064 | −0.268 | −0.352 | negative on two |
| `ote` | −0.108 | −0.090 | +0.051 | negative on two |
| `liquidity_raid_d` | −0.408 | −0.501 | +0.008 | negative on two |
| `draw_on_liquidity` | −0.265 | +0.068 | +0.151 | mixed |

**Porting the negative ones would subtract expectancy.** They are not missing features; they are
tested and rejected.

Worth noting separately: **`killzone` measures −0.125 / −0.182 / +0.032** — and killzones are
already *live*. That is a live component with no demonstrated solo edge on this evidence.

---

## 4. Two corrections to `REPOSITORY_KNOWLEDGE_MAP.md`

The Phase 3 map named breaker blocks as "the highest-value ICT item identified so far" and listed
Silver Bullet as unresolved. **Both were wrong**, and both were caught by hand-verifying grep hits
rather than trusting the counts.

**Breaker blocks are already live.** `engines/e07_technical/smart_money.py` carries a
`breaker: bool` field on `OrderBlock`, set inside `detect_order_blocks` (lines 233–247). The Phase 1
audit did not find it because it is a *field on an existing dataclass*, not a separate
`detect_breaker_blocks` function. Nothing to port.

**Silver Bullet is already live.** `engines/e07_technical/killzones.py` defines
`LONDON_SILVER_BULLET`, `NY_AM_SILVER_BULLET` and `NY_PM_SILVER_BULLET` as real windows (e.g. London
10:00–11:00 Europe/London). Implemented as a time window, which is what Silver Bullet is.

The map's "genuinely new" summary should be read as superseded by §5 below.

---

## 5. What is actually worth doing

**Port one concept: `mss` (market structure shift).** It is the only stranded concept that is both
positive on all three assets *and* has adequate trade counts (46–69). It is already written in
`research/ict_concepts.py:89`.

> **UPDATE 2026-09-12: done.** `market_structure_shift` (already live in `engines/e07_technical/
> smart_money.py`, ported from `research/` per this recommendation) is now wired into two
> `e24_strategy_research` strategies -- `mss_trend_hold` (raw signal, held `hold_bars` bars) and
> `mss_trend_filtered` (same, gated by the 200-EMA trend direction) -- and added to
> `DEFAULT_STRATEGY_GRID`, making it reachable by the grid search and promotable to a live
> `e51_signals` override for the first time. Real result: `mss_trend_hold` cleared Stage 0 and was
> promoted live for **GOLD 1h** (IS Sharpe 2.84, OOS 3.56, 139 trades, 56.1% win) and **GOLD 4h**
> (IS 2.55, OOS 3.41, 66 trades, 63.6% win) -- GOLD had ZERO validated strategies at any timeframe
> before this. Also promoted for **ETHUSD 1d**, replacing the previous `dual_thrust` override with a
> stronger one (IS 1.12 vs 0.70, OOS 1.08 vs 0.62). See `A_PLUS_GOLD_SILVER_BTC_ETH_REPORT.md` for
> the full sweep. One caveat carried forward, not fixed: `market_structure_shift` inherits
> `alternate_swings`' documented unbounded-lookforward property (CLAUDE.md Rule 4) -- measured
> directly across 4 assets x 9 truncation cuts, this produces exactly 1 mismatched bar (13 bars from
> the truncation boundary, on BTC-USD_4h only) out of thousands checked. Real, narrow, and now
> live-reachable for the first time (previously zero live exposure) -- worth the same bounded-
> lookforward fix CLAUDE.md already flags as deferred, but too small to have driven any of the
> Stage-0 passes above (each rests on 64-139 trades; a single mispredicted bar 13 bars from a
> truncation boundary that never occurs in a live/production run, only in this offline test's
> synthetic truncation, does not explain a 2.5-3.6 Sharpe).

**Two candidates with a real caveat:** `eqh_eql` and `power_of_three` are positive on all three
assets, but on **20–50 trades each**. That is below the old 30-trade bar and far below the 60-trade
floor Stage 0 just adopted. Their positive expectancy rests on sample sizes this project has
explicitly decided are too thin to promote on. Either gather more trades before porting, or accept
them as low-confidence.

**Build nothing for the other 14 stranded concepts.** They are measured negative or mixed. This is a
completed experiment, not a backlog.

**CRT is the only genuinely new concept**, and it is **unmeasured**. STAR-EA implements it with real
enums (`ENUM_CRT_TYPE`: BULLISH/BEARISH/NEUTRAL; `ENUM_CRT_STATUS`: FORMING/…). Porting it means
MQL→Python translation plus a full ablation run before it could be considered — it must clear E26
like any other candidate (Rule 3), and the Stage 0 bar now applies.

**CISD has no source at all** — not in STAR-EA, not in Tradecraft (which the brief credited), not in
Titan X. It would have to be specified from public ICT literature from scratch.

---

## 6. Recommended Phase 5 rewrite

The brief's Phase 5 asks for deterministic specifications of 28 concepts. Given 26 already exist as
code and 14 of those are measured negative, the honest version is:

1. **Port `mss` from `research/` into `engines/e07_technical/`**, with multi-truncation no-lookahead tests (Rule 7). One concept, already written, already measured.
2. **Decide on `eqh_eql` / `power_of_three`** — port with the thin-sample caveat recorded, or gather more trades first. This is a judgement call about evidence standards, not a technical question.
3. **Document the 14 rejected concepts as rejected**, so nobody re-proposes them from the same repos in six months.
4. **Optionally translate CRT** from STAR-EA and run it through the ablation harness. Treat as research, not a port.
5. **Drop CISD** unless it is independently wanted; there is no source.

**Do not** write 28 specifications. The specifications largely exist as working code, and the
measurement that matters has already been done.

---

## 7. Caveats

- The ablation covers **3 assets, 4h only, ~3,700–4,400 bars**. It is not a broad test, and GOLD's numbers are notably weaker than the crypto pair's across the board.
- Solo expectancy is **not** the promotion bar. A concept with positive solo expectancy still has to clear E26 and now the Stage 0 timeframe floors as part of a full strategy.
- Prior work on this platform found that **confluence stacking subtracted expectancy in 22 of 23 tests**. That argues against porting several concepts at once and combining them.
- Pattern counts in §2 are triage only. Every verdict-changing hit was hand-verified; the rest were not, so a concept implemented under an unexpected name could still be miscounted.
- STAR-EA has not been read line by line. Its *concept coverage* is established; its *definitions* have not been compared against Titan X's, so "already live" means the concept exists, not that the two implementations agree.
