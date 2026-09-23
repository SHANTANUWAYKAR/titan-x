# Synthetic null campaigns calibrated at 167 candidates/path

Archived 2026-09-15 before re-running at the current grid size (830
candidates/path, 4.97x). Kept, not overwritten: `reports/upgrade statergy.txt`
non-negotiable 9 ("do not delete negative results") and 15 ("do not silently
change historical results").

These are the nulls that produced every `stage0` tag currently on disk,
including the two VALIDATED overrides driving live signals
(`BTC-USD_1d dual_thrust` at percentile 98.0, `ETH-USD_1d mss_trend_hold` at
100.0). If the re-calibrated nulls move those percentiles, these files are the
record of what the earlier decision was actually based on.

Their known limitation is the reason for the re-run: a null built from 167
candidates per path understates how high the best-of-N score climbs when the
real search tries 830, so the >=95th-percentile bar they define is roughly
21-32% too lenient (see reports/STRATEGY_LEADERBOARD.md).
