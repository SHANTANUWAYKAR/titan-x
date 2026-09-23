# Trading Mastery Roadmap — built from 11 videos, measured against this repo

Dated 2026-09-22.

**Three kinds of statement appear in this document and they are always labelled:**

| Tag | Meaning |
|---|---|
| **[VIDEO]** | Taken from one of the 11 transcripts. Attributed, not endorsed. |
| **[MEASURED]** | A number produced by a run in *this repo* on *this repo's data*. |
| **[RESEARCH]** | From a named external source I verified. Cited at the end. |

---

## 0. What I actually accessed

I could not play the videos. I pulled the **full caption transcripts** with
`youtube_transcript_api` and read them. **11 of 11 succeeded** — 16.4 hours of
material, ~915,000 characters. Titles and channels came from YouTube's oEmbed
endpoint.

| # | Channel | Title | Length | Transcript |
|---|---|---|---|---|
| 01 | Lewis Jackson | How To Build A Self-Improving AI Trading Agent | 18.0 m | 20,689 ch |
| 02 | Mind Math Money | ULTIMATE Market Structure Course (Part 1) | 30.0 m | 26,650 ch |
| 03 | Mind Math Money | MASTER Candlestick Patterns in 125 Minutes | 125.2 m | 113,923 ch |
| 04 | Mind Math Money | MASTER Smart Money Concepts in 49 Minutes | 49.1 m | 44,082 ch |
| 05 | Mind Math Money | MASTER Day Trading in 2026 | 105.6 m | 102,415 ch |
| 06 | Mind Math Money | Build a Trading Strategy From Scratch | 76.2 m | 70,755 ch |
| 07 | Mind Math Money | Fibonacci Trading Full Course | 50.0 m | 44,031 ch |
| 08 | Mind Math Money | MASTER Liquidity Concepts in 93 Minutes | 93.2 m | 85,248 ch |
| 09 | Mulham Trading | This 1 Candle Reveals What the Market Is Doing | 16.4 m | 16,544 ch |
| 10 | My Audiobook Shelf | *High Probability Trading Strategies* — Robert C. Miner | 389.6 m | 361,437 ch |
| 11 | Mulham Trading | How to Read Market Structure & Ranges Like a Pro | 31.9 m | 29,647 ch |

**What I did not have:** the on-screen charts. Where a presenter said "as you
can see here," I have the words and not the picture. Everything below comes
from what was *spoken*. Nothing is invented to fill a gap.

**Corpus composition matters.** 7 of 11 videos are one channel (Mind Math
Money), 2 are another (Mulham). So **9 of 11 are retail discretionary technical
analysis from two creators**, both funnelling to paid products. One is an
AI-agent build. One is a Wiley-published book by a 20-year educator. That
imbalance shapes everything in section 4.

---

## 1. Video-by-video analysis

### 01 — Lewis Jackson: Self-Improving AI Trading Agent (18 min)

**Extractable substance is thin; the framework is the useful part.**

Four criteria for a trading agent **[VIDEO]**:
1. **Accurate** — is the incoming data actually right? He claims he tested
   "every single AI in existence" and found inaccuracy in market data retrieval.
2. **Reliable** — runs 24/7 independent of your machine (he hosts on Railway).
3. **Well-defined goal** — *"90% of people don't have a definition of what
   achieving the goal actually looks like."* Define success AND failure
   numerically: target Sharpe, max drawdown, target return.
4. **Self-improving** — form a hypothesis about why a result happened, a second
   hypothesis about what to change, then **change one variable at a time**
   (he explicitly invokes the scientific method).

**Concrete claims:** trading real money; "1.5 million data points"; target
return **4.7 = 47% per 30 days**; "10x in 6 months"; minimum Sharpe of 1; a
"£50,000 to £500,000 in a year" challenge.

**Tooling:** Claude Code + a one-shot prompt + "Hermes agent" + Railway hosting.
The prompt lives behind a free-signup community ("01 Systems").

**My assessment — this is the most dangerous video in the set for you.**
The self-improvement loop as described is *iterate on the same data until the
metric improves*. That is the exact mechanism your own audit proved manufactures
false edge: at proper grid size, **150 of 150 pure-noise paths produced
"passing" candidates** and grade inflation put 2,906 candidates at A on no null
evidence **[MEASURED]**. An agent automating that loop doesn't find edge faster;
it overfits faster and with more confidence. The one genuinely good idea here —
change one variable at a time — is also in video 06, stated better.

---

### 02 — Market Structure Part 1 (30 min)

Highest signal-to-noise of the Mind Math Money set. **[VIDEO]** throughout:

- **The fundamental pattern (ABCD):** impulse → pullback → impulse. Underlies
  Elliott and Gann alike.
- **Why it happens:** a large buyer cannot fill at once without moving price
  against itself, so it scales in, pauses, lets price cool, resumes.
- **Markets are fractal** — a part of the pattern resembles the whole. This is
  *why* a daily strategy tends to work on the 1h.
- **Identifying impulse moves:** larger bodies, steeper slope, more momentum
  than the pullback.
- **MACD settings (3, 10, 16, SMA, no histogram)** — attributed to **Adam
  Grimes**. Used to confirm an impulse printed a higher momentum high.
- **Momentum divergence = do not trade the following pullback.** Stated as a
  rule, not a suggestion.
- **Trend climax:** parabolic, pullbacks vanishing. Detect with Bollinger
  **"free bars"** — a candle *entirely* outside the band. Warning, not entry.
- **Simple vs complex pullbacks.** Complex ones are the norm; a trend
  alternates between them.
- **Fibonacci as a depth gauge:** anchor swing low → swing high. Pullbacks
  typically end **38.2%–61.8%** (broad range 25–75%).
- **Measured move objective:** impulse legs tend to be similar length, so
  target = pullback low + prior impulse length.
- **Multi-timeframe veto:** a clean 4h downtrend inside a daily uptrend is not
  a short. Explicitly demonstrated.

**Rules for a high-probability pullback** (his, consolidated): strong prior
impulse · no momentum divergence · retrace ends in the 38.2–61.8 zone · not
deeper than ~0.7 · aligned with the higher timeframe.

---

### 03 — Candlestick Patterns (125 min)

Structure: reading candles → classification → reversal patterns → continuation
patterns → doji/spinning tops. **[VIDEO]**:

- OHLC anatomy, body vs wick, and the crucial point that **a candle tells you
  open/high/low/close and nothing about the path between them**.
- **Two candles with identical high, low, open and close tell different
  stories depending on body position** — this is the whole basis of wick
  analysis.
- **Every pattern has three attributes:** complexity level, direction, type
  (reversal / continuation / indecision). Useful taxonomy.
- Patterns covered include: engulfing (bullish/bearish), hammer, inverted
  hammer, hanging man, shooting star, doji, spinning top, piercing pattern,
  dark cloud.
- **The load-bearing rule, repeated across videos 03/04/05:** *a pattern in the
  middle of nowhere is noise.* Patterns only carry information **at a level**.

---

### 04 — Smart Money Concepts (49 min)

The cleanest SMC explanation in the set. **[VIDEO]**:

- **Three market states:** uptrend (HH + HL), downtrend (LH + LL), range.
- **BOS (Break of Structure):** price breaks a high in an uptrend / low in a
  downtrend. Trend continuation.
- **CHoCH (Change of Character):** price breaks the most recent *opposing*
  swing. First warning the trend may be ending.
- **Internal vs external** BOS/CHoCH — the same events on LTF vs HTF.
- **Strong vs weak levels** — the key idea most SMC content omits:
  - A **strong** level is the *origin of a move that broke structure*.
  - A **weak** level is the origin of a move that *failed* to break structure.
- **Supply/demand zone construction:** find a momentum candle (body ≥ 2× the
  previous candles, preferably 3–5×) → take the candle **before** it → draw the
  zone from that candle's high to its low.
- **High-quality zones = supply/demand *at* strong highs/lows.** Combining
  structure with S/D is the actual method; S/D alone is not.
- **Fair Value Gap:** 3-candle pattern; gap between candle 1's high and candle
  3's low. Unlike S/D zones, FVGs can appear mid-move.
- **Liquidity grab vs CHoCH — the distinction that matters:** a grab *wicks*
  through and closes back inside; a real CHoCH requires a **close** beyond.
- **Entry/stop/target:** enter at the close of the confirming candle; stop below
  the zone or pattern; **target just *below* the prior high**, not above —
  because a double-top rejection is common and you still bank the trade.

---

### 05 — Day Trading (106 min)

**[VIDEO]:**

- Day trading = open and close within the session. 1m–15m timeframes;
  **15m recommended for beginners** (more thinking time, less randomness).
- **Market structure = macro view (where to look). Price action = micro view
  (when to act).** The best one-line framing in the entire corpus.
- Support/resistance are **zones, not lines**. Levels flip role after a break.
- **Momentum candle definition:** real body ≥ 2× the previous three candles,
  preferably 3–4×.
- **Volume is the second data axis.** Same breakout, 10 units vs 1,000 units of
  volume = different trade. High volume on a breakout = conviction; low volume
  = trap risk.
- **Three day-trading indicators:** VWAP (institutional benchmark, acts as a
  magnet, resets daily), his own Pivot Zones (auto S/R from clustered pivot
  points), his own Volume Strength Candles. **The latter two are paywalled.**
- **Two complete setups:** (a) **Pullback** — entry at support *or* at the
  breakout of the pullback; stop below the pullback low; target prior high or
  2R. (b) **Failure test** — enter at the close back inside, stop past the
  failed wick, 2R target.
- **Risk:** 1% per trade (2–3% acceptable); **daily loss limit of 2–3 losses**,
  then stop for the day.
- **Psychology:** revenge trading, FOMO; *"one good setup beats ten average
  ones."*
- **AI section:** connect Claude to TradingView via a community MCP
  (he cites ~5.9k GitHub stars); use AI as an **assistant**, verify everything,
  *"you are responsible for whether you click buy or sell."*

> **⚠️ FACTUAL ERROR IN THIS VIDEO.** He states Claude's model *"Fable 5 was so
> strong the US government banned it, or they banned another version called
> Mythos 5."* **This did not happen.** No Claude model has been banned by the
> US government, and there is no model called Mythos 5. Treat this as a marker
> for how much else in the corpus is unverified enthusiasm.

---

### 06 — Build a Trading Strategy From Scratch (76 min)

**The most structurally valuable video in the set.** Its framework is the
backbone of the roadmap below. **[VIDEO]:**

> **A trading strategy is a fixed set of rules for entry and exit. If you
> cannot write it down as simple rules, it is not a strategy yet.**

**THE FOUR PILLARS**

| Pillar | Question | Options |
|---|---|---|
| **1. Level** | *Where* am I watching? | S/R zones, supply/demand, order blocks, liquidity levels, trend lines, MAs, chart patterns |
| **2. Trigger** | *What* puts me in? | Candlestick patterns, breakouts, failure tests, breakout-retest |
| **3. Confirmation** | *What agrees?* | RSI/MACD divergence, volume, another timeframe, order flow |
| **4. Risk management** | *How much?* | Position size, stop, target, R:R |

**The pillars are slots, not answers.** Swap the contents and you have a
different strategy with the same skeleton. That is the transferable idea.

Other substance:
- **Failure test mechanics:** breakout traders' stops cluster beyond the level;
  the break triggers them (fuel up), then the reversal triggers the *breakout
  buyers'* stops (fuel down). You enter where others are forced to exit.
- **Breakout quality:** close *far* beyond the level, high volume, momentum
  candle. A marginal close is a weak breakout.
- **RSI divergence:** bullish → compare **lows only**; bearish → **highs only**.
  He names confusing the two as the single most common beginner error.
- **Drawdown math:** −50% needs +100% to recover.
- **Confluence:** each additional agreeing signal improves the odds; the example
  given is 55% → 62% win rate, which over 1,000 trades is decisive.
- **Testing:** backtest → forward test → paper trade → journal (including *how
  you felt*). **Change one rule at a time.**
- **You need positive expected value.** Stated explicitly.

---

### 07 — Fibonacci (50 min)

**[VIDEO]:**

- Ratios: **0.618 = n−1/n**, **0.382 = n−2/n**, **0.5 is not a Fibonacci number**
  — it is plain geometry.
- **Retracement = entries. Extension = targets.** Different tools, different jobs.
- Draw wick-to-wick **or** close-to-close — *"it doesn't matter which; it matters
  that you are consistent."*
- **Golden Zone = 0.5–0.618.**
- **0.382–0.5 is the underrated zone** and is better in *strong* trends, where
  pullbacks are shallow and never reach 0.618.
- **Best beginner setting: 0.382–0.618** — one broad band, captures both.
- **Break below 0.618 = warning the trend may be over.**
- **Extension targets: 1.0 (measured move) and 1.618**; 2.618 for all-time-high
  breakouts.

> **Credit where due.** On the "golden pocket" (0.618–0.65) he says plainly:
> *"0.65 is pretty much arbitrary... there's no mathematical or geometrical
> explanation behind it... I'm actually not even using this zone."* That is
> the single most intellectually honest moment in the nine retail videos, and
> it is the standard everything else in the corpus should have been held to.

---

### 08 — Liquidity (93 min)

The most technically deep retail video here. **[VIDEO]:**

- **Liquidity** = how easily you can transact without moving price. Low-liquidity
  charts look "ugly" — flat candles, no wicks, gaps on a 5m chart. **Avoid them.**
- **Three order types:** market (now, any price), limit (better than current —
  buy *below* / sell *above*), stop (worse than current — buy *above* / sell
  *below*, invisible until triggered). **Your stop-loss on a long is a sell
  stop; your take-profit is a sell limit.**
- **Order book:** bid/ask, depth, spread, market makers. **The core rule:
  price moves when market orders overwhelm limit orders.** Limit orders sit;
  market orders consume. This is the mechanical truth under every chart pattern.
- **BSL / SSL:** buy-stop clusters above swing highs, sell-stop clusters below
  swing lows. Predictable because *everyone puts stops in the same places.*
- **Three patterns:** **sweep** (slow break, traps, reverses) · **grab** (fast
  wick through, immediate reversal) · **run** (breaks and *keeps going* — a real
  breakout; look for a close far beyond with a small wick and high volume).
- **Trendline liquidity** — stops cluster along sloping lines too. Generalised
  into the best sentence in the video: ***"Any tool that produces predictable
  behaviour creates predictable liquidity."***
- **Liquidity void** is the umbrella term; **FVG** is one type; a true **gap**
  (no trading at all) is the strong form and only exists in markets that close.
- **Order flow tools:** volume profile (POC, high/low volume nodes), footprint
  charts, anchored VWAP.
- **Liquidity heatmap:** walls, clouds, withdrawals, flips. Absorption vs
  aggression.

> **Credit again:** on FVGs he says *"the more you look at fair value gaps the
> more you will notice the problems... many traders are over-hyping them"* and
> *"you will find these fair value gaps all the time."* Correct, and rare.

---

### 09 — Mulham: Higher-Timeframe Candle Bias (16 min)

Confluence #6 of his series. **[VIDEO]:**

- Take the setup that **aligns with the higher-timeframe candle's bias**. If HTF
  is bullish, LTF shorts are lower probability — full stop.
- **Timeframe pairs:** Weekly→4h · Daily→1h · 4h→15m · 15m→1m.
- Bias comes from **how the candle opened and whether it displaced**: take the
  previous candle's low and *fail to displace* below → reversal/long bias.
- Tool named: *"ICT higher timeframe candles by fatty"* (TradingView).
- **His claim:** after three consecutive candles in one direction, weakness
  tends to follow — *"based on my backtesting."* No numbers given.

---

### 10 — Robert C. Miner, *High Probability Trading Strategies* (6.5 h)

**This is the only professionally published, editorially reviewed source in the
corpus (John Wiley & Sons), and it is a different class of material.** It is
also the only one that repeatedly argues *against* its own author's interest.

**THE FOUR FACTORS** — momentum, pattern, price, time.

| Ch | Content |
|---|---|
| 2 | Multiple/dual time frame momentum |
| 3 | Simplified Elliott — trend vs correction |
| 4 | Dynamic price: retracements + **alternate price projections** |
| 5 | Dynamic time: time targets for reversal |
| 6 | Two objective entry strategies + position size |
| 7 | Exit strategies and trade management |
| 8 | "Real Traders, Real Time" — student examples |

**Dual-timeframe momentum, stated as rules [VIDEO]:**
> **Rule 1.** Only trade in the direction of the larger timeframe momentum trend
> *unless* it is overbought/oversold. The larger timeframe **defines direction;
> it does not trigger a trade.**
> **Rule 2.** Execute after a *smaller* timeframe momentum reversal in the
> direction of the larger timeframe trend.

**Leading vs lagging — a distinction none of the other 10 videos make:**
> *"Every indicator or oscillator in every trading platform is a lagging
> indicator."* Price and time projections are **leading** — they prepare you in
> advance. Momentum is only useful as a *filter*, inside a plan that has leading
> components.

**Dynamic price [VIDEO]:** internal retracements (38.2 / 50 / 61.8 / 78.6 —
most corrections end at or near **50% or 61.8%**) **qualified by alternate price
projections** (APs). Corrective AP ratios **0.618 / 1.0 / 1.618**; trend AP
ratios **0.382 / 0.618 / 1.0**. **The 100% AP is the most frequent target.**
Where an AP coincides with a retracement you get a narrow, high-probability
reversal zone. Where no AP sits near the 61.8%, *the 61.8% probably won't hold* —
this is the mechanism that tells you **which retracement matters in advance.**

**Two entry strategies [VIDEO]:**
1. **Trailing one-bar high/low (TR1BHL):** after the LTF momentum reversal,
   trail a buy stop **one tick above the last completed bar's high**. Initial
   stop **one tick beyond the swing low made prior to entry.** If momentum
   reverses back or hits the opposite OB/OS zone before you fill, **the setup is
   cancelled.** Lowest capital exposure; may never fill.
2. **Swing entry:** require price to take out a **prior swing** high/low. Larger
   exposure, higher probability. *"Every entry strategy has a trade-off.
   Entering earlier gives lower risk but lower certainty."*

> **The rule that contradicts most of this corpus:** ***"Never buy or sell at a
> target price. Always require the market to move in the direction of the
> anticipated trend to execute a trade."***

**Stops:** *"Stops are always placed at the exact price that voids the setup.
What can the market do that will void the very condition that prompted the
trade?"* Not an arbitrary distance. Not a round number.

**Position size [VIDEO]:**
- **3% max capital exposure per trade. 6% max across all open trades. 10% max
  monthly drawdown — then stop trading for the month.**
- `max size = (account × 3%) ÷ (capital exposure per unit)`
- He started on Gann's 10% rule and *"learned expensively that 10% is far too
  much."*
- He distinguishes **risk** (a probability) from **capital exposure** (a dollar
  amount). Most educators conflate them.

**Win rates [VIDEO]:**
> *"The best professional traders rarely have a greater than 50% win rate...
> If you get good at trading, you will likely have around a 30 to 40% win rate.
> That is why it is absolutely critical that losses are small and profits are
> large."*

**Two-unit trading [VIDEO]:** every position has ≥ 2 units. Unit 1 exits early
on the assumption you were wrong and this is only a correction. Unit 2 is held
for the trend on the assumption you were right. **You can be wrong about the
big picture and still make money.**

**On reward:risk ratios [VIDEO]** — contrarian and correct:
> *"The risk side is known in advance... But what about the reward? The reward
> is an estimate. It is a projection. It is not known."*

**On indicators [VIDEO]** — the passage that matters most to you:
> *"Don't let anyone sell you on some magical mystical indicator... All momentum
> indicators represent the same momentum cycles and most make reversals about
> the same time... **There are only so many ways to process the open, high, low,
> close of price bars. Most variations arrive at similar results.**"*
> *"Many so-called systems optimize settings based on past data and claim
> impressive results, but they fail in real conditions. I've also seen entire
> trading plans built around price-momentum divergence supported by carefully
> selected examples. However, for every example that worked, there are usually
> many that [failed]."*

**On day trading [VIDEO]** — directly opposed to video 05:
> *"The odds of being successful are stacked much higher against the day trader
> than the swing or position trader... Day traders trade for ticks, not for
> points... **Trade for points, not for ticks.**"*
> *"**If you can't make money with unleveraged trades, you'll never make money
> with leveraged trades.**"*
> *"Until you have developed a consistently successful trading plan, your
> objective is not to make money, but to learn to trade."*

**On the education industry [VIDEO]:**
> *"The legitimate trading educators never make results-based claims... You
> can't buy success."*

---

### 11 — Mulham: Ranges & Valid Market Structure (32 min)

Confluence #2 of his series. **[VIDEO]:**

> *"Trading is all about one thing: finding a high-probability range and
> positioning yourself inside it."*

**His 3-point range checklist** (his stated original contribution):
1. **Anchored** — the base of the range is held by another key level/imbalance,
   not floating in the middle of nowhere.
2. **Displacement** — a genuine break with *multiple* candles and distance, not
   one candle closing past a level.
3. **Range fill** — a meaningful retracement into the range (50%, 61.8%, **70.5%**,
   79%). *No range fill = low probability*, because price will eventually reverse
   to fill it and you can't know when.

Other content: **continuation vs reversal** structure (continuation is higher
probability, cleaner targets); reversals are **only valid at higher-timeframe key
levels** and should target *nearby* levels (often just the 50% of the range);
**external (macro) vs internal (micro)** structure; **the highest probability
case is when internal aligns with external.**

---

## 2. Combined knowledge — what all 11 actually amount to

Stripped of branding, the corpus teaches **one strategy skeleton** with
interchangeable parts:

```
        CONTEXT                LOCATION           TRIGGER          SIZE
   ┌──────────────┐      ┌──────────────┐   ┌─────────────┐  ┌──────────┐
   │ HTF direction│ ───▶ │ A level worth│──▶│ Something   │─▶│ Fixed %  │
   │ + trend/range│      │ reacting at  │   │ happens HERE│  │ risk     │
   └──────────────┘      └──────────────┘   └─────────────┘  └──────────┘
    v02 fractal            v04 strong lvl     v03 candles      v06 1–2%
    v09 HTF candle         v08 liquidity      v06 failure test v10 3%/6%
    v10 DTF momentum       v11 valid range    v10 TR1BHL       v10 2-unit
    v11 external/internal  v07 fib zone       v08 sweep/grab   v05 daily cap
```

**Every one of the 11 videos is describing some cell of that grid.** They differ
in vocabulary, not in structure:

| Same idea | v02 | v04 | v08 | v10 | v11 |
|---|---|---|---|---|---|
| Trend continues | impulse | BOS | liquidity run | trend | continuation |
| Trend may be ending | climax | CHoCH | — | wave 5 / OB-OS | reversal |
| Big TF vs small TF | multi-TF | internal/external | — | DTF momentum | macro/micro |
| Stop hunt | — | liquidity grab | sweep/grab | — | — |
| Pullback depth | fib 38–61.8 | — | — | internal retracement | range fill |
| Origin of a strong move | — | strong level | — | — | anchored |

**The unification is worth internalising**: "order block," "strong low,"
"demand zone," and "anchored range base" are **four names for the same object** —
the origin of a move that broke structure. Learn it once.

---

## 3. Overlaps, unique content, contradictions, gaps

### 3a. What overlaps (learn once, ignore the renaming)

| Concept | Appears in |
|---|---|
| Structure = HH/HL vs LH/LL | 02, 04, 05, 09, 11 |
| Momentum candle ≥ 2× previous bodies | 04, 05, 06, 08 |
| Levels are zones, not lines | 04, 05, 06, 08 |
| Patterns only matter at levels | 03, 04, 05, 06 |
| Higher timeframe governs the lower | 02, 05, 09, 10, 11 |
| Stop-hunt / failure test / liquidity grab | 04, 05, 06, 08 |
| Fibonacci 38.2–61.8 retracement zone | 02, 07, 10, 11 |
| Measured move / 100% projection as target | 02, 07, 10 |
| Change one variable at a time | 01, 06 |
| Journal every trade + emotions | 05, 06 |

### 3b. What is genuinely unique to one source

| Unique content | Source | Worth it? |
|---|---|---|
| **Alternate price projections qualifying retracements** | 10 | **Yes — the single best idea in the corpus.** Tells you *which* retracement matters *before* price gets there. |
| **Dynamic time targets** (when, not just where) | 10 | Yes. Nobody else models the time axis at all. |
| **Leading vs lagging indicator distinction** | 10 | Yes. Reframes what indicators are for. |
| **Two-unit trade management** | 10 | Yes. Lets you be half-wrong and still profit. |
| **3%/6%/10% exposure limits** | 10 | Yes, with caveats (see 3c). |
| **Order book mechanics, BSL/SSL, liquidity heatmap** | 08 | Yes. The only mechanical "why" in the retail set. |
| **Strong vs weak levels** | 04 | Yes. Turns S/D from arbitrary to conditional. |
| **Four Pillars framework** | 06 | Yes — as a *checklist*, not a strategy. |
| **Anchored / displacement / range-fill checklist** | 11 | Maybe. Plausible, entirely unvalidated. |
| **HTF candle bias + TF pairing table** | 09 | Maybe. The TF ladder is useful; the "3 candles then weakness" claim is unsupported. |
| **Adam Grimes MACD (3,10,16,SMA)** | 02 | Yes as a pointer — Grimes is a credible primary source. |
| **Self-improving agent loop** | 01 | **No.** See section 5. |

### 3c. Direct contradictions between the sources

**These are real and they matter. The corpus does not agree with itself.**

| # | Question | Position A | Position B |
|---|---|---|---|
| **1** | **Enter at the level, or wait for it to move?** | **04, 11:** enter *at* the zone/FVG/key level on a confirming candle | **10:** ***"Never buy or sell at a target price."*** Require the market to move your way first (trailing-bar or swing entry). |
| **2** | **Risk per trade** | **05, 06:** 1–2% | **10:** 3% per trade, 6% total open |
| **3** | **Fixed R:R targets?** | **05, 06:** aim for a 2:1 | **10:** R:R is *misused* — risk is known, reward is **an estimate**. Don't filter trades on a guess. |
| **4** | **Should a beginner day trade?** | **05:** yes, here's a full course, 15m timeframe | **10:** ***no*** — learn swing/position trading unleveraged first; day trading has the *worst* return on time and capital. |
| **5** | **Is divergence a reliable signal?** | **02, 06:** yes — a core confirmation | **10:** *"entire trading plans built around price-momentum divergence supported by carefully selected examples... for every one that worked there are many that didn't."* |
| **6** | **Does the indicator choice matter?** | **05:** here are the 3 best day-trading indicators (2 paywalled) | **10:** *"All momentum indicators represent the same momentum cycles... most variations arrive at similar results."* |
| **7** | **Win rate to expect** | **06:** a good strategy might do 60–70% | **10:** *"If you get good you will likely have around a **30 to 40%** win rate."* |

**How to resolve each — my recommendation:**

1. **Miner wins.** Requiring price to move first converts a *prediction* into a
   *conditional order*, and it makes non-events free. This is also what your own
   ORB work does correctly (stop order at the level, not a limit).
2. **Start at 1%.** Miner's 3% assumes his setup quality and his 30-year
   experience. **[MEASURED]** In your challenge ladder, at a *negative* edge the
   difference between 1% and 10% risk was 95.23% vs 100% ruin — but with a real
   edge, 10% cost 6 points of extra ruin versus 1%. **Size is a lever that only
   helps if the edge is real; it always hurts when it isn't.**
3. **Miner is right in principle, the others in practice.** Use fixed R:R as a
   *reporting* convention (so backtests are comparable) but never reject a good
   setup because a projected target doesn't clear an arbitrary ratio.
4. **Miner wins, and the evidence is overwhelming — see section 5.**
5. **Miner wins.** Your own repo found the same thing: 16 "informative" features
   collapsed to two redundant groups **[MEASURED]**.
6. **Miner wins decisively.** **[MEASURED]** 27 parameter variants in your sweep
   measured **0.974 mean pairwise correlation** and agreed on 87.2% of bars. He
   wrote that in 2008 from intuition; you proved it in 2026 with data.
7. **Miner.** The 60–70% figure in video 06 is stated as an aspiration, not a
   measurement. Real intraday win rates in your book: **31.94%** at 2R
   **[MEASURED]**.

### 3d. What is missing from all 11 videos

**These gaps are why the corpus cannot, on its own, make anyone profitable:**

| Missing | Why it's fatal |
|---|---|
| **Costs modelled properly** | Not one video computes spread + commission + slippage as a fraction of the edge. **[RESEARCH]** In Taiwan, day traders lost **7 bps/day gross** but **23.9 bps/day net** — costs *more than tripled* the loss. **[MEASURED]** Your book: gross edge +0.0076 R vs **0.0603 R of cost**. |
| **Statistical significance / null testing** | No video asks "would noise have produced this?" **[MEASURED]** 150 of 150 synthetic-noise paths generated "passing" candidates in your pipeline. |
| **Sample size and multiple-testing** | Every video teaches by showing 3–10 hand-picked charts. None mentions that testing 800 variants guarantees a winner by luck. |
| **Out-of-sample / walk-forward** | "Backtest it" is said; *purged, embargoed, out-of-sample* is not. |
| **Survivorship + selection bias in the examples** | Every chart shown is one where the pattern worked. |
| **Execution reality** | Slippage on stop orders, partial fills, spread widening at the open, gaps through stops. |
| **Regime dependence** | No video cuts results by year. **[MEASURED]** That single cut killed five of your leads and gave ORB 0 of 24 positive years. |
| **Tax and funding costs** | Never mentioned. In India, STT/stamp/GST on intraday is material. |
| **Base rates for retail outcomes** | See section 5 — the numbers are known and none of them appear. |

---

## 4. Verified vs claimed — fact-check table

| Claim | Source | Verdict |
|---|---|---|
| *"Fable 5 banned by the US government / model called Mythos 5"* | v05 | **FALSE.** No such ban; no such model. |
| *"47% return per 30 days, 10× in 6 months"* as a system goal | v01 | Not impossible to *state*; no evidence offered. Sustained 47%/month would make him one of the best-performing traders in history. Treat as a marketing target. |
| *"90% of traders fail"* | v11 | Directionally right, imprecise. **[RESEARCH]** ESMA-mandated broker disclosures put it at **74–89% of retail CFD accounts losing money** — an audited, standardised figure. |
| *"95% of accounts lose money and close within 6 months"* | v10 | Attributed by Miner to private broker conversations, explicitly *"I don't have any hard statistics."* Honest framing of an unverified number. |
| Day trading is hard for retail | v10 | **[RESEARCH] Strongly confirmed.** Brazil: of 19,646 who started day-trading index futures, **97% of those persisting >300 days lost money**; only 1.1% earned above minimum wage; **no evidence of learning with experience.** Taiwan: <1% predictably earn positive abnormal returns net of fees. |
| Candlestick patterns work | v03 | **[RESEARCH] Mixed and mostly weak.** Most patterns' mean returns are **not statistically distinguishable from zero**; the significant ones carry high variance. Results do not generalise across markets or periods. Lo, Mamaysky & Wang (2000, *Journal of Finance*) did find technical patterns carry *incremental information* — which is a much weaker claim than "tradeable edge." |
| 0.65 "golden pocket" is arbitrary | v07 | **Correct**, and he says so himself. |
| All momentum indicators are ~equivalent | v10 | **[MEASURED] Confirmed in your own data**: 27 variants at 0.974 correlation. |
| Fibonacci levels are special | v02, 07, 10 | Unresolved. They are **self-fulfilling to the extent that everyone watches them** — which is v08's *"any tool that produces predictable behaviour creates predictable liquidity."* That is the honest defence, and it is a liquidity argument, not a mathematical one. |
| ORB / opening-range breakouts are profitable | not in corpus, but adjacent | **[MEASURED] Not on your book.** 48,425 trades, 31.94% win vs 33.3% breakeven, **0 of 24 years positive.** |

---

## 5. The upgrade — what the corpus should have said

This section is my addition. It is the difference between *knowing the patterns*
and *knowing whether they pay.*

### 5.1 The equation the videos never write

```
   Expectancy per trade  =  (Win% × AvgWin) − (Loss% × AvgLoss) − Cost
```

**Cost is not a footnote; it is usually the largest term.**

Express cost in **R** (units of the amount you risk), not in percent:

```
   cost_R  =  round_trip_cost_fraction ÷ stop_distance_fraction
```

This one line explains almost every failure in your repo and in the literature:

- A **tight stop** buys *more notional* per unit of risk, so it pays **more cost
  per R**. **[MEASURED]** A 10%-of-ATR stop produced **1.02 R of cost per trade**
  on your book — a strategy would need to be extraordinary to overcome that.
- **[RESEARCH]** It is why Taiwanese day traders were −7 bps gross and −23.9 bps
  net: the strategy was mildly bad, the *costs* were catastrophic.
- **[MEASURED]** It is why your composite earns +0.0076 R gross against
  0.0603 R of cost — the signal is real and roughly **8× too small for the
  turnover.**

**Practical rule: before you trade any setup, compute `cost_R`. If it exceeds
~0.15, the setup must be exceptional to survive. If it exceeds 0.5, stop.**

### 5.2 Break-even cost — the metric to demand of any strategy

Instead of asking "is this profitable," ask **"at what cost does this become
unprofitable?"** and compare that to what you actually pay.

```
   breakeven_cost = mean(gross_R) ÷ mean(1 / stop_fraction)
```

**[MEASURED]** Your high-profile ORB implementation reports this on every run.
It came back **negative at every parameter setting** — meaning gross expectancy
was below zero *before a single cent of cost*, so no execution improvement could
rescue it. **[RESEARCH]** The independent replication of the most-cited ORB paper
found break-even at **~2.2¢/share against a ~1¢ spread** — an edge living
entirely inside its own execution noise.

**This is the single most useful number you can compute about a strategy, and
not one of the 11 videos mentions it.**

### 5.3 The null baseline

Every result needs the question: **what would randomness have scored?**

- Shuffle/bootstrap your data, re-run the identical selection, record the best
  score. Do it 150+ times. Your strategy must beat the **95th percentile** of
  that distribution.
- **[MEASURED]** When you applied this, the sole A+ candidate scored at the
  **85.3rd percentile** — it failed. Grade counts went A: 2,906 → 4.
- For any "pass rate" style metric, compute the same figure with expectancy
  forced to zero. **[MEASURED]** In your challenge ladder, a zero-edge strategy
  reaches $1,000 from $100 about **9% of the time** on variance alone. Both of
  your measured edges scored *below* that.

### 5.4 Multiple testing

If you try N variants, the best one looks good by luck. Correct for it:

**Deflated Sharpe Ratio** — the expected maximum Sharpe from N independent trials:

```
   E[max SR] ≈ √(1/(n−1)) · [ (1−γ)·z(1−1/N) + γ·z(1−1/(N·e)) ]
```

**[MEASURED]** Implemented in your repo at `engines/e24_strategy_research/
deflated_sharpe.py`. Before it existed, your A+ bar sat a **factor of two below
the noise floor**.

### 5.5 The year-by-year cut

**Always report results by year.** It is cheap and it is the most destructive
test you can run.

**[MEASURED]** In your audit this single cut killed the long bias (+9.6 in 2017,
−3.6 in 2026), relative strength (sign flip every other year), and both live A+
strategies. ORB: **0 of 24 years positive.** A strategy that works in some years
is regime exposure wearing a strategy's clothes.

### 5.6 Selection beats signal

**[RESEARCH]** The most striking published result in this space: Zarattini,
Barbon & Aziz report the *same* opening-range rules at **Sharpe 0.48 unfiltered
and 2.81** once the universe is cut to the top 20 by opening relative volume.
The edge was never the pattern — it was **which instrument you applied it to.**

**[MEASURED]** Partially reproduces on your book. A relative-volume *threshold*
(≥0.25–1× the 14-day norm) roughly **halves** the gross loss (−0.1398 → −0.057),
and a `≥0` control confirms it isn't a data artifact. But the *cross-sectional
top-N ranking* does nothing on 16 instruments, and nothing crosses zero.

**The lesson for your study plan: spend more time on *what to trade* than on
*how to trade it*.** Nine of the 11 videos do the opposite.

### 5.7 Modern tooling the corpus omits

| Gap | What to use |
|---|---|
| Vectorised backtesting | `vectorbt`, `backtesting.py` |
| Purged/embargoed CV | `setups/ml_validation.py` (yours) or `purgedcv` |
| Triple-barrier labelling & meta-labelling | López de Prado's *Advances in Financial ML*; `mlfinpy` |
| Tear sheets | `quantstats` — **the clearest remaining gap in your repo** |
| Position sizing | Kelly, fractional Kelly, risk-parity |
| Execution research | order-book/tick data (your OHLCV cannot produce delta or L2) |

---

## 6. The roadmap

### STAGE 0 — Before anything (1 week)

**Goal: understand the odds you're playing against.**

- Read the three studies in Sources. Do not skip this.
- Internalise: **[RESEARCH]** 74–89% of retail accounts lose (ESMA);
  97% of persistent Brazilian day traders lost money; no learning effect found.
- Write down, on paper: *"My objective for the first 6 months is not to make
  money. It is to learn to trade."* (Miner)
- **Exit criterion:** you can state the base rate from memory and explain why
  costs, not signals, usually decide the outcome.

### STAGE 1 — BEGINNER (weeks 1–6)

**Order matters. Each item depends on the one above it.**

| # | Topic | Source | Why here |
|---|---|---|---|
| 1 | Candle anatomy, OHLC, body vs wick | **v03** ch1 | Everything else is built on reading one candle |
| 2 | Impulse / pullback, fractality | **v02** | The pattern under all patterns |
| 3 | Structure: HH/HL, LH/LL, ranges | **v04** ch2, **v05** | Vocabulary for everything after |
| 4 | BOS vs CHoCH | **v04** | Turns "trend" from opinion into rule |
| 5 | Support/resistance **as zones** | **v05**, **v06** | Pillar 1 |
| 6 | Order types: market / limit / stop | **v08** ch2 | **Do this before you place any order.** Most beginners don't know their stop-loss is a sell stop. |
| 7 | Risk: position sizing, the −50%/+100% math | **v06**, **v10** ch6 | Pillar 4. Learn before pillar 2. |

**Deliberately deferred:** SMC jargon, Fibonacci, indicators, liquidity theory.

**Exit criterion:** on a blank chart you can mark structure, name every swing as
BOS or CHoCH, and compute the correct position size for a given entry/stop in
under 60 seconds.

### STAGE 2 — INTERMEDIATE (weeks 7–16)

| # | Topic | Source |
|---|---|---|
| 8 | The Four Pillars framework | **v06** — *the organising idea of this whole stage* |
| 9 | Candlestick patterns as **triggers at levels** | **v03** ch3–5 |
| 10 | Failure test / false breakout | **v06**, **v05** |
| 11 | Strong vs weak levels; supply/demand | **v04** ch3–4 |
| 12 | Fair value gaps | **v04** ch5, **v08** |
| 13 | Volume as the second data axis | **v05** |
| 14 | Fibonacci retracement + extension | **v07** |
| 15 | Multi-timeframe alignment | **v09**, **v02**, **v11** |
| 16 | Trading psychology, daily loss limits | **v05** |

**Exit criterion:** you have **one written strategy** with all four pillars
filled in, specific enough that another person could execute it from the page
without asking you a question.

### STAGE 3 — ADVANCED (months 5–10)

| # | Topic | Source |
|---|---|---|
| 17 | Dual-timeframe momentum (rules 1 & 2) | **v10** ch2 |
| 18 | Leading vs lagging indicators | **v10** ch1 |
| 19 | Pattern: trend vs correction | **v10** ch3 |
| 20 | **Alternate price projections qualifying retracements** | **v10** ch4 — *highest-value single technique in the corpus* |
| 21 | Dynamic time targets | **v10** ch5 |
| 22 | TR1BHL + swing entry; stops that void the setup | **v10** ch6 |
| 23 | Two-unit trade management | **v10** ch7 |
| 24 | Order book, BSL/SSL, sweep/grab/run | **v08** |
| 25 | Order flow: volume profile, footprint, anchored VWAP | **v08** |
| 26 | Range validity: anchored/displacement/fill | **v11** |

**Exit criterion:** you can run Miner's 3-minute exercise — take any symbol and
state its position on all four factors and what it must do to become a setup.

### STAGE 4 — EXPERT / QUANT (months 11+)

**This is where you already are, and where the videos stop being useful.**

| # | Topic |
|---|---|
| 27 | Expectancy and `cost_R` on every setup |
| 28 | Break-even cost as the primary metric |
| 29 | Synthetic-null / Monte Carlo significance testing |
| 30 | Deflated Sharpe & multiple-testing correction |
| 31 | Purged + embargoed walk-forward CV |
| 32 | Triple-barrier labelling; meta-labelling |
| 33 | Regime/year-by-year decomposition |
| 34 | **Cross-sectional selection** (the RVOL finding) |
| 35 | Execution modelling: slippage, partial fills, gaps |
| 36 | Forward testing with pre-registered rules |

**Exit criterion:** you can take any claim from any of these 11 videos and, in
one session, produce a number saying whether it holds on your data — with a
null baseline beside it.

---

## 7. Practical exercises

**Stage 1**
1. **50-candle narration.** Mark 50 candles; write one sentence each on what
   buyers/sellers did. No patterns, no indicators.
2. **Structure-only markup.** 20 charts. Mark swing highs/lows, label every
   break BOS or CHoCH. No entries.
3. **Order-type drill.** In TradingView paper trading, place one of each: buy
   market, buy limit, buy stop, sell stop. Predict where each sits *before*
   placing.
4. **Position-size drill.** 20 random entry/stop pairs; compute size at 1% of a
   $10,000 account. Time yourself.

**Stage 2**
5. **Level-first discipline.** Mark levels on 20 charts *before* looking at the
   right-hand side. Then reveal and score yourself.
6. **Pattern-in-context test.** Collect 30 engulfing candles: 15 at a marked
   level, 15 mid-range. Compare what happened next. *This is your first
   personal edge experiment.*
7. **Four-pillar autopsy.** Take 20 historical trades; for each write Level,
   Trigger, Confirmation, Risk. Any blank = not a strategy trade.
8. **Fibonacci consistency test.** 30 pullbacks measured wick-to-wick; the same
   30 close-to-close. Which is more consistent *for you*?

**Stage 3**
9. **DTF momentum log.** 40 setups: HTF direction, LTF reversal, entry per
   TR1BHL. Log the ones that **never filled** — those are the point.
10. **AP qualification test.** 30 corrections. Before price arrives, predict
    which retracement completes it using alternate price projections. Score it.
11. **Stop-placement audit.** For 20 trades, write the *specific market event*
    that would void the setup. If you can't name one, the setup was vague.
12. **Two-unit simulation.** Re-run 30 past trades with 2 units. Compare total
    P&L to single-unit.

**Stage 4**
13. **Cost-first screen.** For 10 setups compute `cost_R`. Rank. Discard the
    top half by cost.
14. **Null test.** Take your best strategy. Run 150 bootstrap-shuffled paths.
    Report your percentile. **If < 95, it is not yet evidence.**
15. **Year-by-year cut.** Split every result by calendar year. Count positive
    years.
16. **Selection experiment.** Fix the rules; vary only *which instruments*.
    Measure how much of the result was selection.

---

## 8. Projects

**Beginner**
- **P1 — Trading journal.** Date, symbol, setup, entry/stop/target, R multiple,
  emotional state. Both v05 and v06 stress the emotion column; they are right.
- **P2 — Level scanner (manual).** Every morning, mark levels on 10 instruments
  before the open. Score overnight.

**Intermediate**
- **P3 — Written strategy document.** Four pillars, explicit invalidation, a
  worked example, and a list of what would make you *abandon* it.
- **P4 — 200-trade manual backtest** of that strategy using TradingView replay.
  Record every trade including non-fills.
- **P5 — Cost calculator.** Given entry, stop, instrument and broker fees,
  output `cost_R` and break-even win rate.

**Advanced**
- **P6 — Code the strategy** in `setups/`, following the pattern of
  `orb_setup.py`: config dataclass, causal signal extraction, economics function.
- **P7 — Null-test harness** for it (you have `research/synthetic_null.py`).
- **P8 — Walk-forward with purge and embargo** (`setups/ml_validation.py`).

**Real-world**
- **P9 — Forward test with pre-registered rules.** Write the rules, hash them,
  *then* start. 95+ days minimum. You have `reports/FORWARD_TEST.md` running —
  **1 resolved trade so far; this is the binding constraint on everything.**
- **P10 — Cross-sectional selection study.** Fix ORB rules; expand the universe
  beyond 16 instruments; test whether the RVOL ranking starts to bite. **This is
  the one experiment your data actually argues for.**
- **P11 — Option-chain IV study.** Your recorder is accumulating BTC/ETH hourly.
  In ~7 months you will have the first genuinely non-price dataset this platform
  has ever had. **Nothing can accelerate this; protect the recorder.**

---

## 9. Recommended additional material

**Primary sources the videos derive from (go upstream):**
- **Adam Grimes — *The Art and Science of Technical Analysis***, and his free
  YouTube/blog material. Video 02's MACD settings come from him. He is one of
  very few educators who publishes statistical tests of his own patterns.
- **Robert C. Miner — *High Probability Trading Strategies*** (Wiley). You have
  the audiobook; **get the book** — it is chart-driven and the audio loses the
  figures, which is most of the content in chapters 4–5.
- **Steve Nison — *Japanese Candlestick Charting Techniques***. The origin of
  video 03's material.
- **Al Brooks — *Trading Price Action*** series. Dense, unglamorous, the deepest
  price-action treatment in print.

**The quantitative side the corpus entirely lacks:**
- **Marcos López de Prado — *Advances in Financial Machine Learning***. Triple
  barrier, meta-labelling, purged CV, deflated Sharpe. Directly implemented in
  your repo already.
- **Ernest Chan — *Quantitative Trading* / *Algorithmic Trading***.
- **David Bailey & López de Prado — "The Deflated Sharpe Ratio"** (paper).
- **Andreas Clenow — *Following the Trend***, for what a real, boring,
  long-horizon edge looks like.

**Channels worth adding (for the gaps, not the overlap):**
- **QuantConnect / Quantopian archives** — coded, testable strategies.
- **Concretum Group (Carlo Zarattini)** — publishes actual papers with data.
- **Darwinex / Robot Wealth** — cost modelling and edge decay.

**Do not buy:** any product promising a win rate, a monthly return, or
"institutional secrets." Miner's own test is the right one — *legitimate
educators never make results-based claims.*

---

## 10. Tools

| Layer | Tool | Note |
|---|---|---|
| Charting | **TradingView** | Used in all 9 retail videos. Replay mode is the single best learning feature. |
| Practice | **TradingView paper trading** | Free. Use it for 200 trades before real money. |
| Data | `yfinance`, exchange APIs, **your own `data/processed/` parquets** | You already have 10.5M 5m bars. |
| Backtest | `vectorbt`, `backtesting.py`, **your `engines/e26_backtesting`** | |
| Validation | `purgedcv`, `mlfinpy`, **your `setups/ml_validation.py`** | |
| Reporting | **`quantstats`** | **The clearest remaining gap in your repo — nothing produces a tear sheet.** |
| Journal | Any spreadsheet | The emotion column is not optional. |
| AI assist | **Claude + TradingView MCP** (v05) | Verify everything it draws. |

**On the AI layer — the honest framing (v05 gets this right):**
> *"You are the one responsible for whether you click buy or sell... AI can't
> predict the future."*

Use it to **accelerate testing**, not to generate conviction. **[MEASURED]** The
failure mode is in video 01: an agent that iterates until the metric improves
will find "edge" in pure noise — you have 150/150 paths proving it.

---

## 11. Mistakes to avoid

**From the videos [VIDEO]:**
1. Trading a pattern **not at a level**. (v03, v04, v05)
2. Drawing S/R as **lines instead of zones**. (v05, v06)
3. Confusing **bullish divergence highs with lows**. Named as the #1 beginner
   error. (v06)
4. Using RSI >70 as sell / <30 as buy. *"This is never how you should use RSI."* (v06)
5. **Revenge trading** after losses; no daily loss limit. (v05)
6. **FOMO** entries — which cluster near tops. (v05)
7. Cluttering the chart with every level until none mean anything. (v05)
8. Risking 10% per trade — *"I learned expensively that 10% is far too much."* (v10)
9. **Buying at a target price** instead of requiring confirmation. (v10)
10. Exiting winners too early — *"you can't go wrong taking a profit"* is
    **misleading**. (v10)
11. Day trading before you can swing trade unleveraged. (v10)
12. Changing **many variables at once** when refining. (v01, v06)

**My additions — the ones that actually decide outcomes:**
13. **Ignoring `cost_R`.** The most common reason a "good" strategy loses.
14. **No null baseline.** Without it you cannot distinguish edge from noise,
    and noise is far more abundant.
15. **Not cutting by year.** Regime exposure looks exactly like edge until you do.
16. **Testing many variants and reporting the best one** without correcting for
    selection.
17. **Learning from curated examples.** Every chart in every video is one where
    it worked.
18. **Confusing a high win rate with an edge.** **[MEASURED]** Your
    `expected_move_fade` won 47–54% of trades and had *negative* expectancy,
    because R:R was 0.75 and breakeven needed 57%. Meanwhile `donchian_breakout`
    won **38.3%** and made money.
19. **Believing an automated self-improvement loop is validation.** It is
    accelerated overfitting unless a null test gates every promotion.
20. **Trading an instrument your account cannot size.** **[MEASURED]** At $50,
    micro futures force 40% risk per trade; spot crypto forces 0.2%. The vehicle
    decides the outcome before the strategy does.

---

## 12. Exact learning order

```
STAGE 0  ──▶ base rates (§5, Sources)                    [1 week]
              │
STAGE 1  ──▶ v03 ch1 ─▶ v02 ─▶ v04 ch2 ─▶ v05 (structure)
              └─▶ v08 ch2 (order types) ─▶ v06 pillar 4 + v10 ch6 (sizing)
              │                                          [6 weeks]
STAGE 2  ──▶ v06 (FOUR PILLARS — the hub)
              ├─▶ v03 ch3–5 (triggers)
              ├─▶ v04 ch3–5 (levels: strong/weak, S/D, FVG)
              ├─▶ v05 (volume, VWAP, two setups)
              ├─▶ v07 (fib entries + targets)
              └─▶ v09 + v11 (multi-TF, range validity)    [10 weeks]
              │
STAGE 3  ──▶ v10 ch2 ─▶ ch3 ─▶ ch4 (★APs) ─▶ ch5 ─▶ ch6 ─▶ ch7
              └─▶ v08 (order book, liquidity, order flow)  [6 months]
              │
STAGE 4  ──▶ cost_R ─▶ break-even cost ─▶ null tests ─▶ DSR
              ─▶ purged CV ─▶ year cuts ─▶ selection ─▶ forward test
```

**Dependencies you must not violate:**
- Order types **before** any live order.
- Position sizing **before** entry techniques.
- Structure **before** SMC vocabulary (SMC is structure renamed).
- The Four Pillars **before** any specific strategy.
- Fibonacci **after** structure (you cannot anchor a fib without swings).
- Miner ch4 (APs) **after** ch3 (pattern) — APs need trend/correction context.
- Cost modelling **before** any conclusion about profitability.
- Null testing **before** committing capital to any backtest result.

---

## 13. Mastery checklist

**Stage 1 — Foundation**
- [ ] Read any candle and state what buyers/sellers did
- [ ] Mark structure and label every break BOS or CHoCH
- [ ] Explain why markets are fractal and what follows from it
- [ ] Name all four order types and which one your stop-loss is
- [ ] Compute position size from entry + stop + account in < 60s
- [ ] State the −50% → +100% recovery math from memory

**Stage 2 — Strategy**
- [ ] Fill all four pillars for a strategy, in writing
- [ ] Identify 10 candlestick patterns and say which are reversal vs continuation
- [ ] Explain the failure test in terms of *whose stops* are being triggered
- [ ] Distinguish a strong level from a weak one
- [ ] Distinguish a liquidity grab from a genuine CHoCH (close vs wick)
- [ ] Draw fib retracement and extension consistently
- [ ] State your daily loss limit and have honoured it

**Stage 3 — Professional method**
- [ ] Apply DTF momentum rules 1 and 2 without looking them up
- [ ] Explain leading vs lagging and name one of each
- [ ] Use alternate price projections to pre-select which retracement matters
- [ ] Place a stop at the price that **voids the setup**, and say what that event is
- [ ] Run a two-unit trade and explain why unit 1 exits early
- [ ] Read a volume profile: POC, high/low volume nodes
- [ ] Explain why price moves (market orders consuming limit orders)
- [ ] Complete Miner's 3-minute any-symbol exercise

**Stage 4 — Evidence**
- [ ] Compute `cost_R` for any setup
- [ ] Compute break-even cost and compare it to what you pay
- [ ] Run a 150-path null test and report your percentile
- [ ] Apply a deflated Sharpe correction for N trials
- [ ] Run purged, embargoed walk-forward CV
- [ ] Cut every result by calendar year and count positive years
- [ ] Separate selection effects from signal effects
- [ ] Run a pre-registered forward test to 30+ resolved trades

**Final gate — the only one that matters**
- [ ] You have a strategy that is **net-positive after realistic costs**,
      beats its **null baseline at the 95th percentile**, is **positive in a
      majority of years**, and has **30+ resolved forward trades**.

> **[MEASURED] As of today, nothing in your repo clears that gate.** Six signal
> families measured net-negative after costs; the live readiness gate passes 2
> of 5. That is not a failure of study — it is what an honest measurement
> process looks like before it finds something. The corpus you just gave me
> contains no method for reaching that gate; sections 5 and Stage 4 do.

---

## Sources

**Verified external research [RESEARCH]:**
- Chague, De-Losso & Giovannetti — [*Day Trading for a Living?* (SSRN 3423101)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101) — 19,646 Brazilian day traders; 97% of those persisting >300 days lost money; no learning effect.
- Barber, Lee, Liu & Odean — [*Do Individual Day Traders Make Money? Evidence from Taiwan*](https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trade%20040330.pdf) — −7 bps/day gross, **−23.9 bps/day net**; <1% predictably profitable net of fees.
- [ESMA product-intervention measures on CFDs](https://www.esma.europa.eu/node/84933) — 74–89% of retail accounts lose money (regulator-mandated disclosure).
- Lo, Mamaysky & Wang (2000), *Foundations of Technical Analysis*, **Journal of Finance** 55(4):1705–1765.
- [Profitability of Candlestick Charting Patterns (SAGE Open, 2017)](https://journals.sagepub.com/doi/10.1177/2158244017736799) — most patterns' mean returns not statistically different from zero.
- Zarattini & Aziz — [*Can Day Trading Really Be Profitable?* (SSRN 4416622)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622); Zarattini, Barbon & Aziz — [Concretum Group](https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/).
- [Independent ORB replication, stress-tested for execution costs](https://github.com/giovannibrusco/zarattini-2023-orb-qqq).

**Your own measurements [MEASURED]:**
`reports/HIGH_PROFILE_RESEARCH.md` · `reports/CHALLENGES.md` ·
`reports/ORB_BACKTEST_5m_retest.md` · `reports/HIGH_PROFILE_SETUP.md` ·
`reports/EDGE_LIFT.md` · `reports/FORWARD_TEST.md` · `CLAUDE.md` (audit sections)

**Transcripts [VIDEO]:** all 11, retrieved 2026-09-22 via `youtube_transcript_api`.
