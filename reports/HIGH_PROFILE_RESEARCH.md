# High-Profile Setups — what the sources actually say, and what this book measures

Dated 2026-09-22. Every number in the "measured" columns comes from a run in
this repo on this repo's data; every number in the "claimed" columns is quoted
from its source and is **not** independently verified here.

---

## 1. The YouTube strategy, decoded

**Source:** *"If You Only Have $50 To Start Trading, Do This Every Morning"* —
Scarface Trades, `youtu.be/DkGzf86tqOs`. Full transcript extracted (17,770
characters).

### The rules, complete

1. At the NYSE open (9:30 ET) mark the **high and low of the first 5 minutes**.
2. Wait for price to **break** that range. Up = buyers in control, down = sellers.
3. Enter on the **retest**, explicitly not the break — *"just because a stock
   breaks out of the 5-minute high or 5-minute low is not the entry... I need to
   wait for the retest opportunity for the highest probability trade."*
4. Stop: price closing back through the 5-minute level.
5. Target: minimum **2R**.
6. Size: risk **10% of the current balance**, so it scales down after losses.

### What is correct in it

The risk-reward argument is sound and is the same arithmetic this repo uses:

| Reward:risk | Win rate needed to break even |
|---|---|
| 1:1 | 50% (60% after costs, as he states) |
| **1:2** | **33.3%** |

His instrument comparison is also accurate and is the relevant one for a $50
account:

| Vehicle | Capital to risk ~$75 at 2R |
|---|---|
| Stocks outright | ~$300,000 (500 SPY shares) |
| Micro futures | $500–1,500 |
| Options | ~$3,000 |

### What does not hold

- **His worked example contradicts itself.** The 25-trade illustration shows 10
  wins of 25, which is 40%, and then states *"our win percentage was about
  27%."* The $500 → $637.42 result follows from the 40% assumption. At 27% the
  same example loses money.
- **He needs 40%. This book measures 31.94%** on the same structure
  (below). The gap between those two numbers is the entire difference between
  a plan and a drawdown.
- **10% risk per trade is above full Kelly even if his claim is true.** Kelly at
  40% and 2R is exactly 10.00%, so his rule is *precisely* full Kelly — the
  size that maximises growth and also maximises the chance of a deep drawdown.
  Six losses in a row, entirely normal at a 40% win rate, is −47%.

---

## 2. The academic literature

### Zarattini, Barbon & Aziz (2024) — "A Profitable Day Trading Strategy for the U.S. Equity Market"

| Rule | Value |
|---|---|
| Opening range | first **5 minutes** |
| Direction | sign of the first 5-minute candle; doji = no trade |
| Entry | stop order beyond the opening-range extreme |
| Stop | **10% of the 14-day ATR** |
| Target | **end of day** — no fixed R target |
| Sizing | 1% risk per position, **4× leverage cap** |
| Universe | price > $5, 14-day volume ≥ 1M shares, 14-day ATR > $0.50 |
| **Selection** | rank by **opening relative volume**, trade only the **top 20** |
| Commission | $0.0035/share |

**Reported results:**

| | Total return | Annualised | Sharpe | Win rate | Max DD |
|---|---|---|---|---|---|
| Unfiltered | 29% | 3.2% | **0.48** | 41.4% | 13% |
| RVOL-filtered | 1,637% | 41.6% | **2.81** | 48.4% | 12% |

The opening-range length sweep is the most load-bearing parameter in the paper:
**5-min 1,637% · 15-min 272% · 30-min 21% · 60-min 39%.**

> **The finding is not the breakout. It is the selection.** The same rules score
> 0.48 and 2.81. What changed was *which instrument* the breakout was taken on.

### Zarattini & Aziz (SSRN 4416622) — the QQQ/TQQQ version

Stop at the opposite extreme of the opening candle, target 10R or end of day.
QQQ: 676% total, 33% annualised, Sharpe 1.13, **win rate 24%**, expectancy
+0.13R, max DD 22%. TQQQ: 1,484%, Sharpe 1.19, max DD 28%. No slippage modelled.

### The independent replication — the most useful source of all

`github.com/giovannibrusco/zarattini-2023-orb-qqq` reproduced the QQQ study
inside noise (1,775 trades vs 1,795; Sharpe 1.06 vs 1.12) and then priced
execution in:

| | Net PnL |
|---|---|
| No costs | $138,639 |
| 2¢ entry / 4¢ stop slippage | **$4,860** (−96.5%) |
| With the NQ confirmation filter | $44,332 — but **76% of it is 2022 alone** |

- **Break-even at ~2.2¢/share against a ~1¢ spread.**
- Bootstrap 95% CI on Sharpe **[0.05, 1.41]** vs buy-and-hold QQQ **[−0.03, 1.47]** — overlapping.
- Lost money in 2017, 2020 and early 2023.

Its placebo control is worth copying: replacing the NQ filter with QQQ's own
09:25 pre-market bar dropped the t-statistic from 2.05 to 1.27, which is how you
show a cross-asset signal carries information rather than restating momentum.

---

## 3. What this book measures

### 3a. The YouTube rules, exactly as specified

`setups/run_orb_backtest.py --timeframe 5m --orb-minutes 5 --entry-model retest --no-vwap`

> **Note on the implementation.** `entry_model` existed in `ORBConfig` from the
> start but was **never read by `extract_orb_signals`**. Every ORB result in this
> repo dated before 2026-09-22 is the momentum model whatever the config said.
> The retest entry was written for this test.

| Variant | Trades | Win% | Net %/trade | Years positive |
|---|---|---|---|---|
| 5-min range, **retest** entry | 48,425 | **31.94%** | −0.8849% | **0 of 24** |
| 5-min range, momentum entry | 59,623 | 32.22% | −0.8748% | 0 of 24 |
| 15-min range, momentum entry | 45,764 | 31.44% | −0.8605% | 0 of 24 |

**Breakeven is 33.3%.** All three sit below it. Waiting for the retest removed
19% of the trades and moved the win rate **−0.28 points** — the opposite
direction from the claim, though inside noise.

The year-by-year table runs 2003–2026 with not one positive year. Win rates
range 27.4%–33.9%; the best single year (2023, 33.9%) is still net-negative
after costs.

### 3b. The published setup, rebuilt to its own specification

`setups/run_high_profile.py` — 19,663 trades on the **16 instruments** that pass
the paper's own gates (price > $5, 14-day ATR > $0.50): AAPL, AMZN, BTCUSD,
CRUDE, ETHUSD, GOLD, GOOGL, JPM, META, MSFT, NVDA, SILVER, SP500, TSLA, US10Y,
USDJPY. 5m bars.

| Stop model | Selection | Trades | Win% gross | Gross R | Break-even cost |
|---|---|---|---|---|---|
| ORB opposite | none | 19,663 | 17.18% | −0.1398 | −4.48 bps |
| ORB opposite | RVOL ≥ 1.0× | 7,235 | 21.16% | −0.0659 | −2.31 bps |
| 10% of ATR | none | 19,535 | 14.18% | −0.1577 | −4.65 bps |
| 10% of ATR | RVOL ≥ 1.0× | 7,235 | 13.68% | −0.1528 | −4.60 bps |

With the 10%-of-ATR stop the filter does essentially nothing (−0.1577 →
−0.1528), so whatever is happening depends on the wider opening-range stop.

#### Which variable is actually doing the work

> **A correction.** The first version of this page credited the improvement to
> the paper's cross-sectional *top-N ranking* and called it a monotone
> dose-response. That comparison moved two variables at once — top-20 at ≥1.0×
> against top-3 at ≥2.0×. Sweeping each alone says something different.

**Top-N ranking, threshold held at 1.0×** — one extraction, only the cut varies:

| Top-N | % of universe | Gross R |
|---|---|---|
| 1 | 6% | −0.0727 |
| 2 | 12% | −0.0766 |
| 3 | 19% | −0.0694 |
| 8 | 50% | −0.0658 |
| 16 | 100% | −0.0659 |

**Flat, and marginally worse at the hardest cuts.** The ranking does nothing
here — and on 16 instruments it cannot do much, since "top 16" is already the
whole universe.

**Threshold, ranking disabled** — with a `≥ 0` control that drops only the
sessions whose relative volume is undefined (the first 14 of each instrument):

| RVOL ≥ | Trades | % kept | Win% gross | Gross R |
|---|---|---|---|---|
| *(no filter)* | 19,663 | 100% | 17.18% | −0.1398 |
| **0× (control)** | 19,476 | 99% | 17.12% | **−0.1401** |
| 0.25× | 13,536 | 69% | 20.34% | **−0.0575** |
| 0.5× | 12,326 | 63% | 20.79% | −0.0573 |
| 0.75× | 10,375 | 53% | 21.24% | −0.0708 |
| 1× | 7,235 | 37% | 21.16% | −0.0659 |
| 1.25× | 4,335 | 22% | 21.18% | −0.0127 |
| 1.5× | 3,121 | 16% | 19.77% | −0.0253 |
| 2× | 2,096 | 11% | 18.27% | −0.0361 |
| 3× | 1,336 | 7% | 16.99% | −0.0375 |
| 4× | 967 | 5% | 17.68% | −0.0001 |
| 6× | 591 | 3% | 16.24% | −0.0568 |

Three things to read off this:

1. **The control passes.** `≥ 0` keeps 99% of trades and lands at −0.1401,
   indistinguishable from no filter at all. Dropping the undefined sessions
   explains *none* of the effect — which is the artifact this table was built to
   rule out.
2. **There is a real effect, and it is a plateau rather than a slope.** Any
   threshold from 0.25× to 1× roughly halves the gross loss (−0.14 → −0.057 to
   −0.071) while retaining 37–69% of trades. A broad stable band is what a real
   effect looks like; it does not depend on picking the threshold well.
3. **Above 1× it is noise.** 1.25× (−0.0127) and 4× (−0.0001) look near
   breakeven, but 1.5×, 2× and 3× sit at −0.025 to −0.038 between them and 6×
   reverts to −0.057. An unordered curve on a collapsing sample is sampling
   variation, not a better setting. **The 4× row is the single most tempting
   number on this page and it should be ignored.**

**Nothing crosses zero.** Break-even cost stays negative at every threshold and
every cut, so gross expectancy is below zero before a single cent of cost and no
cost assumption rescues it.

> **Breadth remains a hypothesis, not a finding.** The paper ranks ~1,000 US
> equities down to 20 (a 2% cut); 16 instruments cannot support that at all, and
> the ranking measurably does nothing here. That is *consistent with* needing a
> wider universe, but it is not evidence for it — the experiment that would test
> it has not been run, because the instruments to run it on do not exist in this
> book yet.

---

## 4. Challenges — $1 → $100 → $1,000

`setups/run_challenge.py`. Multiplicative equity, minimum-ticket floor, 4,000
simulations per rung, each against its own zero-expectancy null.

### The two bottom rungs are a funding problem, not a trading problem

| Rung | Minimum ticket (micro futures) | First trade risks |
|---|---|---|
| $1 → $10 | $20 | **2,000% of the account** |
| $10 → $100 | $20 | **200% of the account** |

No trade is placeable. These rungs are reported IMPOSSIBLE rather than
simulated into a 0% that reads like bad luck. **$1 → $100 is not a hard trading
problem. It is not a trading problem at all.**

### $100 → $1,000, the first rung that can be traded

| Edge | Win rate | Reach | Null | **Lift** | Ruin |
|---|---|---|---|---|---|
| **Claimed** (video), 10% risk | 40.00% | 57.35% | 9.28% | **+48.08 pt** | 42.65% |
| **Claimed** (video), 1% risk | 40.00% | 63.68% | 9.85% | **+53.83 pt** | 36.33% |
| **Measured** ORB, 10% risk | 31.94% | 4.78% | 8.97% | **−4.20 pt** | **95.23%** |
| **Measured** high-profile ORB | 15.72% | 0.00% | 8.35% | **−8.35 pt** | **100.00%** |

Two things to read off this table:

1. **An 8-point win-rate difference is the whole outcome.** 40% reaches the
   target 57% of the time; 31.94% is ruined 95% of the time. Both are "a 2R
   strategy with a roughly one-in-three win rate."
2. **The measured rows sit BELOW their own noise baseline.** A zero-edge
   strategy reaches $1,000 about 9% of the time on variance alone. The measured
   edge does worse than that, which is what a negative expectancy means.
   Kelly on the measured distribution is **−42.88%**: the only size that does
   not lose money is zero.

Even with a real edge, the 10%-risk rule costs **6 points of extra ruin** on
this rung versus 1% (42.65% vs 36.33%) while *lowering* the reach rate.

---

## 5. What to take from all of this

**Confirmed, and worth acting on:**

- **A relative-volume threshold is real.** Requiring the opening window to trade
  at least ~0.25–1× its 14-day norm roughly halves the gross loss, stably across
  a 4× range of thresholds, and a `≥ 0` control rules out the obvious artifact.
  It is the only component out of everything tested in this audit that moved
  gross expectancy materially.
- **It is a threshold effect, not a ranking effect.** The paper's cross-sectional
  top-N cut does nothing measurable on 16 instruments.
- End-of-day exits and 2R exits are genuinely different strategies. The
  published 24% win rate is not comparable to a 2R win rate and should never be
  quoted against a 33.3% breakeven.

**Not confirmed:**

- The retest entry. Costs 19% of trades for −0.28 points of win rate.
- Any benefit from a HARDER relative-volume cut. Above 1× the curve is
  unordered and the sample collapses.
- The breadth hypothesis, in either direction.
- The 5-minute opening range as such. On this book it is indistinguishable from
  15-minute.
- The 10%-of-ATR stop. Worse than the opening-range stop on every cut, and it
  neutralises the relative-volume filter.
- Any version of ORB reaching positive gross expectancy on this book — 18
  instruments for the plain ORB, 16 for the published setup's own gates.

**The honest summary:** the published research is better than the YouTube
version of it, its key mechanism survives contact with this data, and it still
does not produce a positive expectancy here. The independent replication of the
most-cited paper in the field reached the same conclusion on the authors' own
instrument.

---

## Reproduce

```
python setups/run_orb_backtest.py --timeframe 5m --orb-minutes 5 \
    --entry-model retest --horizon 48 --no-vwap --out-suffix 5m_retest
python setups/run_high_profile.py --timeframe 5m --stop-model orb_opposite \
    --sweep-top-n 1,3,8,16 --sweep-rvol-min 0,0.25,0.5,0.75,1,1.25,1.5,2,3,4,6
python setups/run_challenge.py --from-hp --rvol-filtered --instrument mnq --risk 0.01
python setups/run_challenge.py --win-rate 0.40 --rr 2.0 --risk 0.10 --instrument mnq
python scripts/scan_high_profile.py --stop-model orb_opposite --top 12
```

## Sources

- [Can Day Trading Really Be Profitable? — Zarattini & Aziz (SSRN 4416622)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622)
- [A Profitable Day Trading Strategy For The U.S. Equity Market — Concretum Group](https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/)
- [Independent replication, stress-tested for execution costs](https://github.com/giovannibrusco/zarattini-2023-orb-qqq)
- [Opening Range Breakout Research: What Two Day-Trading Papers Actually Found](https://danfin.net/opening-range-breakout-research)
- [Opening Range Breakout for Stocks in Play — QuantConnect](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/)
- [Assessing the profitability of intraday opening range breakout strategies (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S1544612312000438)
- [Stocks In Play Strategy — QuantifiedStrategies](https://www.quantifiedstrategies.com/stocks-in-play-trading-strategy-day-trading/)
- [Risk of ruin — Wikipedia](https://en.wikipedia.org/wiki/Risk_of_ruin)
