# Net-of-Cost Edge Surface

Live rule · 1d · 29 instruments · resolve within 60 bars · risk 1%/trade · round-trip cost 0.30% of notional · leverage cap 3.0x.

Each cell is **net % of equity per trade** after costs. Wider stops deploy less
notional (`risk/stop_distance`) and so pay less cost, but hit their target less
often — the grid shows where, if anywhere, that trade is worth making.

| ATR mult | RR 1.0 | RR 1.5 | RR 2.0 | RR 3.0 | RR 5.0 |
|---|---|---|---|---|---|
| 0.5 | -0.4074 | -0.3554 | -0.3249 | -0.2804 | -0.2320 |
| 1.0 | -0.1744 | -0.1487 | -0.1297 | -0.1025 | -0.1037 |
| 2.0 | -0.0635 | -0.0478 | -0.0475 | -0.1004 | -0.3560 |
| 3.0 | -0.0266 | -0.0299 | -0.0765 | -0.2577 | -0.6192 |
| 5.0 | **+0.0275** | -0.0657 | -0.2281 | -0.5364 | -0.8004 |
| 8.0 | **+0.1049** | -0.1350 | -0.3723 | -0.6511 | -0.8492 |

**2 of 30 cells are net-positive.**

| ATR | RR | trades | win% | gross R | notional | cost %/tr | **net %/tr** |
|---|---|---|---|---|---|---|---|
| 8.0 | 1.0 | 36,261 | 56.5% | +0.1309 | 0.087x | 0.0260% | **+0.1049%** |
| 5.0 | 1.0 | 71,195 | 53.4% | +0.0678 | 0.135x | 0.0404% | **+0.0275%** |

## Reading this

- One positive cell in a field of negatives is selection, not a finding. A result
  counts only if neighbouring cells are positive too — an isolated winner is what
  a 30-cell search produces from noise.
- In-sample, on the decade everything else was fitted to.
- Bars containing both stop and target are scored LOSSES.
- Costs are modelled flat. Real spreads widen exactly when these signals fire.
