"""
Module: news_impact.py
Description: Event study -- what price ACTUALLY did after past macro
    releases, per symbol, so a live release can be read against its own
    historical precedent instead of a guess.

    The question this answers: "this number just came out -- based on
    every prior time this same release printed a reading this unusual,
    which way did this market go, how far, and how often?"

    DATA REALITY, stated up front because it bounds what is claimable:
      - data/macro/economic_calendar_history.parquet holds 110,971 events
        (2011-2021), of which 9,383 are flagged High Volatility Expected.
      - Its `surprise` column is UNUSABLE: every value is the string
        'nan'. `forecast` is almost entirely empty too. So the textbook
        surprise (actual - forecast) CANNOT be computed from this dataset.
      - `actual` IS populated and numeric. Surprise is therefore derived
        here as a z-score of `actual` against the trailing history of the
        SAME event name -- "was this reading unusual for this release?".
        That is a proxy, not the market's true expectation, and it is
        labelled as such everywhere it appears.
      - The archive ends in 2021, so this measures a historical
        relationship. It is evidence about how a market has reacted, not
        a promise about the next print.

    Direction is never asserted from the headline's wording. It is
    measured from real forward returns on real OHLCV, and reported with
    the sample size and consistency behind it -- a 3-sample "edge" is
    shown as a 3-sample edge.

    RESEARCH CODE, outside engines/ (see research/__init__.py). Nothing
    live imports it.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_CALENDAR = Path(__file__).resolve().parents[1] / "data" / "macro" / "economic_calendar_history.parquet"

# Minimum prior occurrences before a per-event reaction is reported at all.
# Below this the "hit rate" is noise dressed as a statistic.
MIN_SAMPLES = 12


@dataclass
class EventReaction:
    """Measured forward reaction to one class of macro release."""

    event: str
    country: str
    horizon_bars: int
    n_samples: int
    mean_return_pct: float
    median_return_pct: float
    up_rate: float                     # share of occurrences that closed higher
    mean_abs_move_pct: float           # typical MAGNITUDE, direction aside
    std_return_pct: float
    directional_confidence: float      # 0-100, see _confidence()
    surprise_bucket: str = "all"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "event": self.event, "country": self.country,
            "horizon_bars": self.horizon_bars, "n_samples": self.n_samples,
            "mean_return_pct": round(self.mean_return_pct, 4),
            "median_return_pct": round(self.median_return_pct, 4),
            "up_rate": round(self.up_rate, 4),
            "mean_abs_move_pct": round(self.mean_abs_move_pct, 4),
            "std_return_pct": round(self.std_return_pct, 4),
            "directional_confidence": round(self.directional_confidence, 1),
            "surprise_bucket": self.surprise_bucket,
            "notes": self.notes,
        }


def _confidence(up_rate: float, n: int) -> float:
    """Directional confidence as a percentage, penalised for small samples.

    Deliberately NOT just `up_rate * 100`: a 100% up-rate from 3
    observations is not 100% confidence in anything. Uses the lower bound
    of the Wilson score interval on the distance from a coin flip, so
    confidence rises with BOTH consistency and sample size, and a tiny
    sample cannot produce a large number however lopsided it looks.
    """
    if n <= 0:
        return 0.0
    p = max(up_rate, 1.0 - up_rate)          # strength of whichever side won
    z = 1.96
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * np.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0)) / denom
    lower = max(centre - margin, 0.5)        # never claim worse than a coin flip
    return float((lower - 0.5) * 200.0)      # 0.5 -> 0, 1.0 -> 100


def load_high_impact_events(country: Optional[str] = None) -> pd.DataFrame:
    """High-volatility scheduled releases, with a derived surprise z-score.

    `surprise_z` is `actual` standardised against the trailing 20
    occurrences of the SAME event name -- expanding/rolling and shifted by
    one, so a given row never sees its own value or any future one. This
    is the honest substitute for the unusable `surprise` column, not a
    reconstruction of the real consensus.
    """
    df = pd.read_parquet(_CALENDAR)
    df = df[df["impact"].astype(str).str.contains("High", na=False)].copy()
    if country:
        df = df[df["country"] == country]
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")

    g = df.groupby("event")["actual"]
    mean = g.transform(lambda s: s.shift(1).rolling(20, min_periods=6).mean())
    std = g.transform(lambda s: s.shift(1).rolling(20, min_periods=6).std())
    df["surprise_z"] = (df["actual"] - mean) / std.replace(0, np.nan)
    return df


def measure_reaction(
    price: pd.DataFrame,
    events: pd.DataFrame,
    horizon_bars: int = 6,
    min_abs_z: float = 0.0,
    event_name: Optional[str] = None,
) -> Optional[EventReaction]:
    """Forward return from the first bar CLOSING AFTER each event, held
    `horizon_bars`.

    Entering on the first bar that closes after the release is what a
    reader of this signal could actually have done -- using the bar the
    release lands inside would book part of the move before it was
    knowable.
    """
    if event_name:
        events = events[events["event"] == event_name]
    if min_abs_z > 0:
        events = events[events["surprise_z"].abs() >= min_abs_z]
    if events.empty or price.empty:
        return None

    px = price.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    # Compare in epoch nanoseconds, not as datetimes. Price parquet files
    # here are inconsistently tz-aware (some carry UTC, some are naive),
    # and numpy's searchsorted raises outright on a naive/aware mix -- so
    # both sides are normalised to UTC and reduced to int64 once, which is
    # both unambiguous and faster than per-row Timestamp comparisons.
    ts = pd.to_datetime(px["timestamp"], utc=True)
    ts_ns = ts.astype("int64").to_numpy()
    ev_ns = pd.to_datetime(events["timestamp"], utc=True).astype("int64").to_numpy()
    closes = px["close"].to_numpy(float)

    rets: list[float] = []
    for event_ns in ev_ns:
        entry = int(np.searchsorted(ts_ns, event_ns, side="right"))
        exit_i = entry + horizon_bars
        if entry <= 0 or exit_i >= len(closes):
            continue
        base = closes[entry]
        if base <= 0:
            continue
        rets.append((closes[exit_i] - base) / base * 100.0)

    if len(rets) < MIN_SAMPLES:
        return None

    arr = np.asarray(rets, dtype=float)
    up_rate = float((arr > 0).mean())
    notes: list[str] = []
    if min_abs_z > 0:
        notes.append(f"surprise proxy |z|>={min_abs_z} (derived, not true consensus surprise)")
    notes.append("calendar archive ends 2021 -- historical relationship, not a forecast")

    return EventReaction(
        event=event_name or "ALL high-impact",
        country=str(events["country"].mode().iloc[0]) if not events["country"].empty else "?",
        horizon_bars=horizon_bars,
        n_samples=len(arr),
        mean_return_pct=float(arr.mean()),
        median_return_pct=float(np.median(arr)),
        up_rate=up_rate,
        mean_abs_move_pct=float(np.abs(arr).mean()),
        std_return_pct=float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        directional_confidence=_confidence(up_rate, len(arr)),
        surprise_bucket=f"|z|>={min_abs_z}" if min_abs_z > 0 else "all",
        notes=notes,
    )


def rank_event_reactions(
    price: pd.DataFrame, events: pd.DataFrame, horizon_bars: int = 6,
    min_abs_z: float = 0.0, top_n: int = 15,
) -> list[EventReaction]:
    """Every event type with enough history, ranked by directional
    confidence -- i.e. which releases this market has actually reacted to
    consistently, rather than which ones are assumed to matter."""
    out: list[EventReaction] = []
    for name in events["event"].dropna().unique():
        r = measure_reaction(price, events, horizon_bars, min_abs_z, event_name=name)
        if r:
            out.append(r)
    out.sort(key=lambda r: -r.directional_confidence)
    return out[:top_n]
