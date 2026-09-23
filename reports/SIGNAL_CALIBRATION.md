# Signal Confidence Calibration

**105,404 signals** · reward:risk 2.0:1 (ATR x1.0) · resolve within 20 bars · entry at next bar's open.

Breakeven win rate at 2.0:1 is **33.3%**. A bucket below that loses money no matter how confident it sounds.

| Confidence | Signals | Realised win% | vs breakeven | Verdict |
|---|---|---|---|---|
| 20–30 | 9,234 | 33.4% | +0.1 pt | profitable |
| 30–40 | 9,538 | 33.7% | +0.4 pt | profitable |
| 40–50 | 9,573 | 32.7% | -0.7 pt | loses money |
| 50–60 | 10,256 | 33.7% | +0.4 pt | profitable |
| 60–70 | 11,418 | 34.0% | +0.7 pt | profitable |
| 70–80 | 12,826 | 33.5% | +0.2 pt | profitable |
| 80–100 | 24,490 | 33.5% | +0.1 pt | profitable |

**Overall win rate 33.6%** against a 33.3% breakeven (+0.3 pt).

**Confidence-to-outcome correlation: +0.159.** This is the number that decides
whether the confidence score is informative at all. Near zero means a signal reading
80 is no better than one reading 30, and the number should not be shown to a trader
as though it were.

## What this does not establish

- Calibration is not edge. A perfectly calibrated generator with no edge is still no
  edge -- it has merely stopped overstating its own conviction.
- Bars containing both stop and target are scored as LOSSES, because OHLC cannot order
  two touches inside one bar. Real results are never worse than this, and may be better.
- This replays history. It is not forward evidence, and cannot become forward evidence.
