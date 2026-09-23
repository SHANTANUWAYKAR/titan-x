# ICT Formal Specification — Phase 5 (rewritten scope)

**Date:** 2026-09-08. **Scope:** one concept (CRT), one decision record (CISD), one rejection
register (14 concepts). See `docs/UPGRADE_BRIEF.md` Phase 5 for why this is not 28 specifications.

**Source:** `external/STAR-EA-v11.20/STAR_v11.20.mq5` (MIT), functions `DetectCRTSetups`
(line 38457), `UpdateCRTSetups` (38564), enums at 2293–2310, inputs at 5533–5548. Every rule below
is read from that code, not from ICT prose.

---

# 1. CRT — Candle Range Theory

## 1.1 Concept

A single candle whose range is *significant relative to volatility* becomes a reference range. The
**next** candle breaking one side of that range defines direction; the range then projects forward
to give entry, stop and targets. It is a range-expansion setup, not a structure-break setup — which
is what makes it non-redundant with BOS/CHoCH/MSS.

## 1.2 Mathematical definition

For a candidate bar `i` with `O_i, H_i, L_i, C_i` and `ATR_i` (14-period Wilder-equivalent, the same
`_average_true_range` E07 already uses):

```
range_i        = H_i − L_i
range_atr_i    = range_i / ATR_i
body_ratio_i   = |C_i − O_i| / range_i
```

Bar `i` qualifies as a **range bar** iff:

```
MIN_RANGE_ATR ≤ range_atr_i ≤ MAX_RANGE_ATR        (defaults 0.8, 3.0)
body_ratio_i  ≥ MIN_BODY_RATIO                      (default 0.3)
```

Let `k = i + 1` (the chronologically next bar). Define:

```
broke_high = H_k > H_i
broke_low  = L_k < L_i
```

**Direction** (exclusive-or — both or neither is rejected):

```
CRT_BULLISH  if  broke_high ∧ ¬broke_low
CRT_BEARISH  if  broke_low  ∧ ¬broke_high
otherwise      reject
```

**Optional retrace filter** (`REQUIRE_RETRACE`, default on):

```
bullish:  retrace = (H_i − C_k) / range_i
bearish:  retrace = (C_k − L_i) / range_i
require   retrace ≥ 0.25
```

**Levels** (bullish; mirror for bearish):

```
entry   = (H_i + L_i) / 2
stop    = L_i − 0.2 · ATR_i
tp1     = H_i + 0.5 · range_i · PROJECTION_MULT      (default 1.0)
tp2     = H_i + range_i · PROJECTION_MULT
tp3     = H_i + range_i · EXTENSION_LEVEL            (default 1.618)
R:R     = |tp2 − entry| / |entry − stop|
```

**Quality tiers** (from `range_atr_i`): A ≥ 1.5, B ≥ 1.2, C ≥ 0.9, else D.

## 1.3 Detection algorithm (Python, ascending index)

```
for i in range(len(df) - 1):
    if not finite(ATR[i]) or ATR[i] <= 0:            continue
    rng = H[i] - L[i]
    if rng <= 0:                                     continue
    r_atr = rng / ATR[i]
    if not (MIN_RANGE_ATR <= r_atr <= MAX_RANGE_ATR): continue
    if abs(C[i] - O[i]) / rng < MIN_BODY_RATIO:       continue

    k = i + 1
    broke_high, broke_low = H[k] > H[i], L[k] < L[i]
    if broke_high == broke_low:                       continue   # both or neither

    if REQUIRE_RETRACE:
        retrace = (H[i] - C[k]) / rng if broke_high else (C[k] - L[i]) / rng
        if retrace < 0.25:                            continue

    emit signal at index k          # NOT at index i -- see 1.4
```

## 1.4 ⚠ The translation trap — emit at `k`, not `i`

**MQL5 arrays here are series-indexed** (`ArraySetAsSeries(..., true)`), so index 0 is the *newest*
bar and `i-1` is chronologically **after** `i`. STAR-EA's `brokeHigh = high[i-1] > high[i]` therefore
means *"the next bar broke above bar i's high."*

A naive Python port using ascending indices reads `i-1` as the **previous** bar and silently
implements a different, wrong algorithm.

The consequence that matters for Rule 7: **the setup is not knowable at bar `i`.** It requires bar
`i+1` to have closed. Any implementation that records the signal at index `i` is **lookahead** — it
would place a signal on a bar whose defining information did not yet exist. The specification is
therefore: *detect using `i` and `i+1`, emit at `i+1`.*

This is the same defect class as the order-block bug that reported a 94.8% win rate, and the same
one that made my first MSS truncation tests vacuous. It must be asserted by the deterministic test
required in §1.11, not by a prefix-comparison test.

## 1.5 Required data

OHLC (all four) plus a 14-period ATR. **Volume is not used.** Minimum history: `ATR_PERIOD + 2`
bars; below that, emit nothing rather than a partial result.

## 1.6 Timeframes

STAR-EA runs it on intraday charts and disables related mechanisms on H4/D1 (its own comment: `TF
guard: H4/D1 → AMD disabled`). Titan X should evaluate CRT at **1h and 4h first**, since those are
the two timeframes with usable Stage 0 nulls and where every other ICT concept on this platform was
measured. 1d is admissible but its null rests on only 39 winning paths of 150.

## 1.7 Confirmation logic

Three gates, in increasing strictness:

1. **Break** (mandatory) — exclusive-or as defined above.
2. **Retrace ≥ 25%** (default on) — the breaking bar must close back inside a meaningful part of the range, not run away from it.
3. **Confluence with FVG or order block** (default **off** in STAR-EA, `MIN_CONFLUENCE = 2`) — **recommend leaving off.** Prior work on this platform found confluence stacking *subtracted* expectancy in 22 of 23 tests. Enabling a confluence gate by default would contradict that measurement.

## 1.8 Edge cases

| Case | Required behaviour |
|---|---|
| `range_i == 0` (flat bar) | Reject; never divide by zero |
| `ATR` NaN (warm-up window) | Reject |
| `ATR == 0` (flat series) | Reject — STAR-EA sets `rangeInATR = 0`, which then fails the min filter anyway |
| Last bar of the series | No `i+1` exists — cannot emit. Loop must stop at `len − 1` |
| Both sides broken | Reject (outside bar) — explicitly not neutral, not a coin flip |
| Neither side broken | Reject |
| Duplicate detection on the same bar | STAR-EA dedupes on `rangeTime`; a vectorised Python port emits once per index and does not need this |
| Gapped bar (`L_k > H_i`) | Counts as `broke_high`; retrace will typically fail, which is the correct conservative outcome |

## 1.9 False-positive conditions

- **Wide-range indecision bars.** `body_ratio ≥ 0.3` is a weak filter — a bar with a 30% body and two long wicks still qualifies. Titan X's own `displacement` uses **0.6**. Expect CRT to fire on bars `displacement` would reject.
- **Volatility-cluster clustering.** `range_atr` compares a bar to a *trailing* ATR, so during a volatility expansion many consecutive bars qualify. Expect bursts, not isolated signals.
- **The `range_atr ≤ 3.0` cap silently discards genuine shocks.** A 4×ATR bar — often the most meaningful expansion — is rejected. That is a deliberate choice in the source, and worth ablating separately.
- **Quality tier is not evidence.** A/B/C/D derive from `range_atr` alone and have never been validated against outcomes on this platform. Treat as a label, not a score.

## 1.10 Two bugs in the source, not to be reproduced

**Bug 1 — `CRT_RequireBreak` is dead code.**

```mql5
if(!brokeHigh && !brokeLow) continue;
if(CRT_RequireBreak && !brokeHigh && !brokeLow) continue;   // unreachable
```

The first line already guarantees at least one is true, so the input flag does nothing. Either drop
the parameter or give it real meaning; do not port a no-op switch that implies configurability it
does not have.

**Bug 2 — `wickRatio` is misnamed.**

```mql5
double wickRatio = candleRange > 0 ? bodySize / candleRange : 0;
if(wickRatio < 0.3) continue;
```

It is a **body** ratio. Porting the name would invert a future reader's understanding of the filter.

## 1.11 Backtesting requirements

Non-negotiable, per Rules 3, 4 and 7:

1. **Emit at `i+1`**, and prove it with the deterministic test in §1.4 — construct cases where the break happens after bar `i` and assert nothing is recorded at `i`.
2. **Multi-truncation no-lookahead** at 0.35 / 0.5 / 0.65 / 0.8 / 0.93, **plus** a deterministic discriminator. Truncation alone is insufficient — proven vacuous on MSS.
3. **Enter as an E24 candidate** in `DEFAULT_STRATEGY_GRID`, graded by E26's unweakened bar.
4. **Clear the Stage 0 floor** for its timeframe: min(IS, OOS) ≥ 2.34 (1h) / 1.49 (4h) / 0.59 (1d), and ≥ 60 trades.
5. **Ablate solo first**, against the same three assets as `research/ablation_*.json`, before any confluence variant. If solo expectancy is negative, stop — that is the answer.
6. **Do not tune to pass.** Rule 6: fails walk-forward or 2× costs → dropped, not re-optimised.

### 1.11.1 Real measured result (2026-09-13)

Implemented in `engines/e07_technical/crt.py` per this spec exactly (multi-
truncation no-lookahead verified in `tests/unit/test_crt.py`, including the
translation-trap test §1.4 demands), then ablated solo at 4h against the
same three assets as the rejection register in §3:

| Asset | Trades | Win% | R:R | Expectancy | PF | Verdict |
|---|---|---|---|---|---|---|
| GOLD | 123 | 46.3% | 0.87R | **−0.161** | 0.75 | Negative |
| BTCUSD | 151 | 50.3% | 0.91R | **−0.084** | 0.92 | Negative |
| ETHUSD | 153 | 51.6% | 1.26R | **+0.467** | 1.35 | Positive, best solo concept that run, well above the 60-trade floor |

**Verdict: mixed, not a general edge.** Negative on 2 of 3 assets — per
this section's own rule ("if solo expectancy is negative, stop") CRT does
NOT clear the bar as a platform-wide concept and is **not** being added
to `DEFAULT_STRATEGY_GRID` on the strength of this result. The ETHUSD
result specifically (153 trades, PF 1.35, comfortably above the 60-trade
floor) is real and strong enough to be worth a dedicated, asset-specific
E24 candidate if that's ever prioritized — but that is a genuinely
separate, larger step (a real strategy function, IS/OOS split, Stage 0
null-percentile check) than this ablation screening, and has NOT been
done here. Filed as a possible future item, not executed speculatively.

This closes the "not yet ported/ablated" status this spec and
`docs/REPOSITORY_INTELLIGENCE.md`'s STAR-EA entry both previously carried
for CRT.

## 1.12 Example signal structure

```json
{
  "concept": "crt",
  "direction": "LONG",
  "signal_index": 1043,
  "range_bar_index": 1042,
  "range_high": 2412.80, "range_low": 2398.20, "range_atr": 1.34,
  "body_ratio": 0.61, "retrace": 0.38,
  "entry": 2405.50, "stop": 2396.14,
  "tp1": 2419.10, "tp2": 2427.40, "tp3": 2436.42,
  "risk_reward": 2.34,
  "quality": "B",
  "notes": ["emitted at the breaking bar, not the range bar"]
}
```

`entry`/`stop`/`tp*` are **specification outputs, not validated levels** — E26 exits on signal flip
and does not test stops or targets (see `REPOSITORY_FEATURE_MATRIX.md` §5). Until barrier-aware
exits exist, these levels are untested by any backtest on this platform.

---

# 2. CISD — Change in State of Delivery

> **Correction (2026-09-08, same day).** An earlier version of this document, and
> `REPOSITORY_KNOWLEDGE_MAP.md` §19, stated CISD had **no source anywhere** and recommended dropping
> it. **That was wrong.** My search matched *directory names*, not file contents. Grepping contents
> finds a full `## CISD — Change in State of Delivery` section in
> `external/Tradecraft/plugins/tradecraft/skills/ict-smart-money/SKILL.md` (13 hits across two
> files). It is prose, not code — which is exactly the input Phase 5 asks to convert into a
> deterministic algorithm. CISD is therefore **specifiable**, and specified below.

## 2.1 Source definition (verbatim)

> "When a breakout candle through a FVG simultaneously creates a *new* FVG that overlaps the IFVG
> zone. Two signals merge into one candle."
>
> Conditions: occurs at the end of a trend (after a liquidity sweep or at an HTF key level); the
> overlapping area of the original IFVG + new FVG is the entry zone. SL beyond the most recent
> swing. — `Tradecraft/.../ict-smart-money/SKILL.md`

## 2.2 It is composable from primitives Titan X already has

| Component | Where it already lives | Status |
|---|---|---|
| FVG detection | `engines/e07_technical/smart_money.detect_fair_value_gaps` | **live** |
| IFVG (failed FVG, polarity flip) | `research/ict_concepts.inverse_fvg` | stranded in `research/` |
| Displacement (breakout candle) | `engines/e07_technical/smart_money.displacement` | **live** (ported 2026-09-08) |
| Swing points (for the stop) | `engines/e07_technical/structure.find_swing_points` | **live** |

No new primitive is required. CISD is a *composition rule* over three existing detectors.

## 2.3 Deterministic definition

Let `G` be an FVG detected at index `g` with bounds `[gap_bottom, gap_top]` and a direction.

**Step 1 — the FVG fails (IFVG forms).** At some bar `b > g`, price closes clean through:

```
bullish G fails  iff  C_b < gap_bottom(G)
bearish G fails  iff  C_b > gap_top(G)
```

**Step 2 — the same breaking bar leaves a new, opposite-direction FVG.** Using E07's 3-candle
definition centred on `b`, i.e. the window `(b−1, b, b+1)`:

```
new bullish FVG at b  iff  H_{b-1} < L_{b+1}   → zone [H_{b-1}, L_{b+1}]
new bearish FVG at b  iff  L_{b-1} > H_{b+1}   → zone [H_{b+1}, L_{b-1}]
```

Require `direction(new FVG) == opposite(direction(G))` — the source's "opposite direction imbalance."

**Step 3 — the two zones overlap.**

```
overlap_low  = max(zone_low(IFVG),  zone_low(newFVG))
overlap_high = min(zone_high(IFVG), zone_high(newFVG))
require overlap_high > overlap_low
```

**Signal.** Direction = direction of the new FVG. Entry zone = `[overlap_low, overlap_high]`.
Stop = beyond the most recent swing point before `b` (`find_swing_points`), on the far side.

**Emit at `b+1`**, not `b` — Step 2 needs bar `b+1` to exist. Same trap as CRT §1.4.

## 2.4 Edge cases

| Case | Behaviour |
|---|---|
| `b` is the last bar | No `b+1` — cannot evaluate Step 2. Emit nothing |
| `b == g + 1` | The FVG fails on the bar immediately after forming; allowed, but the zones will usually not overlap |
| Multiple FVGs fail on the same bar | Each is a separate candidate; emit at most one signal per direction per bar |
| Zones touch but do not overlap (`overlap_high == overlap_low`) | Reject — a zero-width entry zone is not a zone |
| `max_age` exceeded | `inverse_fvg` caps the search at 50 bars; reuse that bound rather than inventing a second one |

## 2.5 ⚠ Prior evidence argues against this working

**Its core component measured negative on every asset tested.** `inverse_fvg` scored
**−0.208 / −0.569 / −0.270** (BTCUSD / ETHUSD / GOLD) in `research/ablation_*.json`. CISD is a
*stricter* filter on top of IFVG, so it will fire less often on the same failed-gap population.

That cuts two ways and neither is knowable in advance: a stricter filter may isolate the subset that
works, or it may simply produce fewer instances of something that does not. **The honest prior is
unfavourable**, and the trade count will be low — likely below the 60-trade Stage 0 floor, which
would make it unpromotable regardless of expectancy.

**Recommendation: specify it (done), but rank it below CRT.** Build it only if the ablation on
`inverse_fvg` is worth revisiting, and expect a thin sample.

## 2.6 Backtesting requirements

Identical to CRT §1.11: emit at `b+1` with a deterministic lookahead test, enter as an E24
candidate, clear E26 and the Stage 0 floor, ablate solo first. Additionally: **report trade count
prominently** — this concept's most likely failure mode is being unmeasurable, not being wrong.

## 2.7 Real measured result (2026-09-13)

Implemented in `engines/e07_technical/cisd.py` per this spec exactly (translation-trap and
multi-truncation no-lookahead tests in `tests/unit/test_cisd.py`, including a swing-revision-
tolerant check for the `stop` field specifically, matching MSS's own established tolerance for
that same class of noise). Ablated solo at 4h against the same three assets:

| Asset | Trades | Win% | R:R | Expectancy | PF | Verdict |
|---|---|---|---|---|---|---|
| GOLD | 123 | 38.2% | 1.22R | **−0.144** | 0.75 | Negative |
| BTCUSD | 168 | 47.0% | 1.18R | **+0.053** | 1.05 | Barely positive |
| ETHUSD | 158 | 43.7% | 1.38R | **+0.130** | 1.07 | Mildly positive |

**Verdict: mixed and weak, not promoted.** Sample sizes were healthy on all three (123-168 trades,
well above the 60-trade floor) — the spec's own prediction of a likely-unmeasurable thin sample did
NOT materialize. But expectancy is negative on GOLD and only barely above breakeven on the other
two (PF 1.05/1.07, a razor-thin edge easily erased by any cost/slippage this ablation didn't model).
Not added to `DEFAULT_STRATEGY_GRID` — same standard applied to CRT's own mixed result (§1.11.1):
2-of-3 weak-or-negative does not clear the bar, even though the sample-size concern specifically
did not apply here.

---

# 3. Rejection register — do not re-propose

Measured in `research/ablation_{BTCUSD,ETHUSD,GOLD}_4h.json`. Solo expectancy per asset:

| Concept | BTCUSD | ETHUSD | GOLD | Verdict |
|---|---|---|---|---|
| `inverse_fvg` | −0.208 | −0.569 | −0.270 | Negative on all three |
| `ce` (consequent encroachment) | −0.440 | −0.485 | −0.087 | Negative on all three |
| `bpr` (balanced price range) | −0.469 | −0.052 | −0.166 | Negative on all three |
| `turtle_soup` | −0.289 | −0.280 | −0.213 | Negative on all three |
| `displacement` (solo) | −0.171 | −0.019 | −0.063 | Negative on all three |
| `premium_discount` | +0.064 | −0.268 | −0.352 | Negative on two |
| `ote` | −0.108 | −0.090 | +0.051 | Negative on two |
| `liquidity_raid_d` | −0.408 | −0.501 | +0.008 | Negative on two |
| `draw_on_liquidity` | −0.265 | +0.068 | +0.151 | Mixed |
| `killzone` (already live) | −0.125 | −0.182 | +0.032 | **Live with no solo edge** |

These are implemented and tested. They are not a backlog — they are a completed experiment. The
correct action for all of them is **`KEEP EXISTING` in `research/`, do not port**.

**Open decisions, not rejections:** `eqh_eql` (+0.619/+0.079/+0.610) and `power_of_three`
(+0.113/+0.095/+0.022) are positive everywhere but rest on 20–50 trades — below the 60-trade floor
Stage 0 adopted. This is an evidence-standards call for the owner.

---

# 4. Caveats on everything above

- The ablation covers **3 assets, 4h only, ~3,700–4,400 bars**. Not a broad test.
- **Solo expectancy is not the promotion bar.** A concept can be positive solo and still fail E26 and Stage 0 as part of a full strategy.
- **CRT is completely unmeasured on this platform.** Nothing in this specification says it works. It says precisely what would have to be built in order to find out.
- STAR-EA has not been read line by line. The CRT functions have; the rest of its 51,396 lines have not.
