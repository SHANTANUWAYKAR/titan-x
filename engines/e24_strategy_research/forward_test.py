"""
Module: forward_test.py
Description: reports/statergy.txt NON-NEGOTIABLE #14 -- "Paper trading /
    forward testing must precede live trading" -- and #12, "NEVER deploy a
    strategy directly to live trading".

    THE GAP THIS CLOSES. Two overrides currently carry an explicit
    `stage0.status == "VALIDATED"` tag and therefore drive live signals
    (BTC-USD_1d and ETH-USD_1d, both `mss_trend_hold`). Both earned that tag
    from HISTORICAL evidence only: an in-sample sweep, a walk-forward split and
    a synthetic-null percentile, all computed over bars that already existed
    when the search ran. Nothing in this project has ever recorded what a
    validated strategy said BEFORE the outcome was knowable, so there is no
    evidence anywhere on disk that distinguishes "this rule has an edge" from
    "this rule fit the history it was selected on". That distinction is the
    entire purpose of a forward test, and real money is now involved.

    WHY THIS IS NOT JUST ANOTHER BACKTEST. A forward test is defined by WHEN
    the record was written, not by what it contains. If records can be
    generated retroactively by replaying a strategy over past bars, the log is
    a backtest wearing a forward test's name -- and it would be a uniquely
    dangerous one, because it would carry the authority of the word "forward"
    while inheriting every selection bias of the search that produced the
    strategy. So the anti-backfill rule here is STRUCTURAL, not advisory:

      * the log's first line is an immutable inception timestamp;
      * a record whose bar is older than inception is REFUSED;
      * a record whose bar is newer than the wall clock is REFUSED;
      * a record for a bar more than `max_staleness_bars` old is REFUSED.

    These are enforced in `record_signal`, which raises rather than returning
    a status, so a caller cannot ignore the failure by accident. This cannot
    stop someone who deletes the log and starts over -- nothing can, the disk
    belongs to the user -- but it does mean contamination requires a
    deliberate, visible act instead of an ordinary mistake.

    APPEND-ONLY, RESOLUTIONS ARE SEPARATE ROWS. Outcomes are never written
    back into the row that made the prediction. A resolution is its own
    appended line keyed by `record_id`, so the original prediction stays
    byte-for-byte as it was written, and `load_log()` folds the two together
    at read time. A prediction that has been edited after the fact is not
    evidence, and the file format makes such an edit visible rather than
    convenient.

    AMBIGUOUS BARS RESOLVE AGAINST THE STRATEGY. When a bar's range contains
    both the stop and the target, OHLC data cannot say which was touched
    first. This module counts that bar as a STOP and flags it
    (`ambiguous_bar`). The convention is deliberately pessimistic, and
    `summarise()` reports the ambiguous fraction, because a forward result
    assembled mostly from ambiguous bars is soft regardless of which way the
    convention breaks.

    REUSES E12 FOR THE STATISTICS. The forward-vs-backtest comparison is a
    Beta-Binomial update, already implemented and documented in
    e12_quant_research as `bayesian_win_rate_update` (with a 90% credible
    interval, which is the point -- a thin forward sample must show a WIDE
    interval rather than a confident-looking point estimate). It is reused
    directly here. Nothing in this module invents a second statistic for a
    question the platform already answers one way.

    THE COMPARISON IS REPORTED TWICE, ON PURPOSE. Using the backtest as a
    Bayesian prior is the textbook move, but it is exactly wrong when the
    question under test IS whether the backtest is trustworthy: an overfit
    prior with 71 pseudo-observations behind it would swamp the first dozen
    honest forward trades and hide the degradation it was supposed to reveal.
    So `compare_to_backtest` returns both the blended posterior AND the
    forward-evidence-only posterior under a uniform prior, and draws its
    verdict from the LATTER. The blended figure is reported for context, never
    for the decision.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = _ROOT / "data" / "models" / "e24_strategy_research" / "forward_test_log.jsonl"

# Seconds per bar, used only to judge how stale a bar is at record time and to
# size a horizon in wall-clock terms. Kept local and explicit rather than
# imported so that an unknown timeframe fails loudly here instead of silently
# taking some other module's default.
TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1wk": 604800,
}

# A bar older than this many bars at record time is refused. Three is generous
# enough to survive a runner that missed a scheduled scan or two, and tight
# enough that replaying a month of history can never slip through.
DEFAULT_MAX_STALENESS_BARS = 3

# Below this many resolved forward trades, `compare_to_backtest` refuses to
# issue a verdict. 20 is not a magic number and is not claimed to be one: it is
# the point at which a Beta-Binomial 90% interval on a ~60% win rate is still
# roughly +/-18 points wide. It is a floor on absurdity, not a threshold for
# confidence -- see `observations_needed_to_detect` for the honest answer to
# "how many do I actually need".
MIN_DECIDABLE_TRADES = 20


class ForwardTestIntegrityError(RuntimeError):
    """A record was rejected because accepting it would corrupt the log's
    meaning. Raised, never returned as a status code, so a caller cannot
    accidentally proceed as though the record had been written."""


@dataclass
class ForwardTestRecord:
    """One prediction, written before its outcome was knowable."""

    record_id: str
    symbol: str
    timeframe: str
    strategy: str
    direction: str
    bar_time: str          # the bar the decision was made on (ISO 8601, UTC)
    recorded_at: str       # wall clock at the moment of writing (ISO 8601, UTC)
    entry: float
    stop_loss: float
    take_profit: float
    horizon_bars: int
    params: dict = field(default_factory=dict)
    confidence: Optional[int] = None
    source: str = ""
    # Frozen copy of what the override CLAIMED when this prediction was made.
    # Stored per-record rather than looked up at report time because the
    # override file is mutable: re-promoting or re-tagging a strategy later
    # would otherwise silently rewrite the claim this record was testing.
    backtest_claim: dict = field(default_factory=dict)

    # Filled by fold-in at read time from a separate resolution row; never
    # written into the prediction line itself.
    outcome: Optional[str] = None            # "target" | "stop" | "horizon"
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    r_multiple: Optional[float] = None
    bars_held: Optional[int] = None
    ambiguous_bar: Optional[bool] = None
    resolved_at: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.outcome is not None

    @property
    def is_win(self) -> Optional[bool]:
        """A win is a positive R outcome, not merely a target hit -- a horizon
        exit above entry counts as one, and a stop-out never does."""
        if self.r_multiple is None:
            return None
        return self.r_multiple > 0


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: Any) -> datetime:
    """Parse an ISO string, datetime or pandas Timestamp into aware UTC.

    Raises ForwardTestIntegrityError rather than ValueError on anything else.
    This caught a real defect on the first live run: `df.index[-1]` was handed
    in as a bar time, but this platform's frames carry a RangeIndex with the
    time in a `timestamp` COLUMN, so the integer `729` arrived here. A bare
    ValueError deep in a date parser gave no hint that the caller had passed a
    row number as a timestamp.
    """
    if isinstance(ts, pd.Timestamp):
        dt = ts.to_pydatetime()
    elif isinstance(ts, datetime):
        dt = ts
    else:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise ForwardTestIntegrityError(
                f"Cannot read {ts!r} ({type(ts).__name__}) as a bar timestamp. If this is a "
                f"row number, the caller passed a positional index where a time was expected "
                f"-- this platform's OHLCV frames use a RangeIndex with the time in a "
                f"'timestamp' column, so use bar_timestamp(df), not df.index[-1]."
            ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Columns that may carry the bar time when a frame is not indexed by it.
# `date` is listed after `timestamp` deliberately: this project's processed
# parquets contain BOTH, and `date` is entirely null in them (3674 of 3674 rows
# on ETH-USD_1d), so preferring it would turn every bar time into NaT.
_TIME_COLUMNS = ("timestamp", "datetime", "date", "Date", "Datetime")


def as_time_indexed(bars: pd.DataFrame) -> pd.DataFrame:
    """Return `bars` indexed by a tz-aware UTC DatetimeIndex.

    Accepts either an already-indexed frame or this platform's native shape (a
    RangeIndex plus a time column). Returns a copy; the caller's frame is never
    mutated.
    """
    df = bars.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in _TIME_COLUMNS:
            if col in df.columns and df[col].notna().any():
                df = df.set_index(pd.to_datetime(df[col], utc=True, errors="coerce"))
                df = df[df.index.notna()]
                break
        else:
            raise ForwardTestIntegrityError(
                f"bars are not time-indexed and carry no usable time column "
                f"(looked for {_TIME_COLUMNS}); cannot resolve a forward-test record "
                f"against them."
            )
    idx = df.index
    df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return df.sort_index()


def bar_timestamp(bars: pd.DataFrame, position: int = -1) -> datetime:
    """The timestamp of one bar (last by default), whatever the frame's shape."""
    return _parse(as_time_indexed(bars).index[position])


def _bar_seconds(timeframe: str) -> int:
    try:
        return TIMEFRAME_SECONDS[timeframe]
    except KeyError:
        raise ForwardTestIntegrityError(
            f"Unknown timeframe {timeframe!r}: cannot judge whether a bar is stale, and a "
            f"forward test that cannot tell stale from fresh is not a forward test. "
            f"Known timeframes: {sorted(TIMEFRAME_SECONDS)}"
        ) from None


# --------------------------------------------------------------------------
# Log I/O -- append-only
# --------------------------------------------------------------------------

def _ensure_inception(log_path: Path, now: Optional[datetime] = None) -> datetime:
    """Return the log's inception time, creating the log with an inception
    line if it does not yet exist.

    Inception is what makes backfill detectable at all: without a recorded
    "this log began here", a record dated last year is indistinguishable from
    one dated this morning.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size > 0:
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if doc.get("kind") == "inception":
                    return _parse(doc["created_at"])
                # A log whose first meaningful line is not an inception marker
                # predates this format or was hand-edited. Refuse rather than
                # silently adopting "now" as inception, which would make every
                # historical row look legitimately forward-dated.
                raise ForwardTestIntegrityError(
                    f"{log_path} has no inception line. Refusing to guess when this log "
                    f"began -- without it, backfilled rows cannot be distinguished from "
                    f"genuine ones. Move the file aside to start a clean forward test."
                )
    # Honour a caller-pinned clock. A caller that pins `now` must get a FULLY
    # pinned run: taking inception from the real clock while the record's bar
    # time came from the pinned one silently makes the guard depend on the
    # wall date, which is exactly how this module's own tests broke four days
    # after they were written.
    created = now or _utcnow()
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "kind": "inception",
            "created_at": _iso(created),
            "note": (
                "Forward test inception. Predictions dated before this moment are refused "
                "by engines/e24_strategy_research/forward_test.py -- see its module docstring. "
                "Deleting or editing this file resets the forward test and invalidates every "
                "conclusion drawn from it."
            ),
        }) + "\n")
    return created


def inception_time(log_path: Path | None = None) -> Optional[datetime]:
    """Inception of an existing log, or None if it has not been started."""
    p = Path(log_path) if log_path else DEFAULT_LOG_PATH
    if not p.exists() or p.stat().st_size == 0:
        return None
    return _ensure_inception(p)


def _append(log_path: Path, doc: dict) -> None:
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, default=str) + "\n")


def load_log(log_path: Path | None = None) -> list[ForwardTestRecord]:
    """Read the log, folding each resolution row into the prediction it
    resolves. Predictions keep the values they were written with; only the
    outcome fields come from the resolution row."""
    p = Path(log_path) if log_path else DEFAULT_LOG_PATH
    if not p.exists():
        return []

    preds: dict[str, ForwardTestRecord] = {}
    resolutions: dict[str, dict] = {}
    field_names = {f for f in ForwardTestRecord.__dataclass_fields__}

    with p.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("forward_test: skipping malformed line %d of %s", lineno, p)
                continue
            kind = doc.get("kind")
            if kind == "inception":
                continue
            if kind == "resolution":
                rid = doc.get("record_id")
                if rid:
                    # First resolution wins. A second one for the same record
                    # means something tried to re-resolve an already-settled
                    # prediction; keeping the first preserves the original.
                    resolutions.setdefault(rid, doc)
                continue
            if kind == "prediction":
                rid = doc.get("record_id")
                if not rid or rid in preds:
                    continue
                try:
                    preds[rid] = ForwardTestRecord(**{
                        k: v for k, v in doc.items() if k in field_names
                    })
                except TypeError as e:
                    # A row missing a required field (a truncated write, a
                    # hand-edit) must not take the whole log down with it --
                    # the remaining predictions are still real evidence.
                    logger.warning(
                        "forward_test: skipping unreadable prediction on line %d of %s (%s)",
                        lineno, p, e)

    for rid, res in resolutions.items():
        rec = preds.get(rid)
        if rec is None:
            continue
        rec.outcome = res.get("outcome")
        rec.exit_price = res.get("exit_price")
        rec.exit_time = res.get("exit_time")
        rec.r_multiple = res.get("r_multiple")
        rec.bars_held = res.get("bars_held")
        rec.ambiguous_bar = res.get("ambiguous_bar")
        rec.resolved_at = res.get("resolved_at")

    return sorted(preds.values(), key=lambda r: r.bar_time)


# --------------------------------------------------------------------------
# Recording -- the integrity boundary
# --------------------------------------------------------------------------

def record_signal(
    *,
    symbol: str,
    timeframe: str,
    strategy: str,
    direction: str,
    bar_time: Any,
    entry: float,
    stop_loss: float,
    take_profit: float,
    horizon_bars: int,
    params: Optional[dict] = None,
    confidence: Optional[int] = None,
    source: str = "",
    backtest_claim: Optional[dict] = None,
    log_path: Path | None = None,
    max_staleness_bars: int = DEFAULT_MAX_STALENESS_BARS,
    now: Optional[datetime] = None,
) -> Optional[ForwardTestRecord]:
    """Append one prediction to the forward-test log.

    Returns the record, or None if this exact (symbol, timeframe, strategy,
    bar_time, direction) was already recorded -- re-running the scanner
    within the same bar is normal operation, not an error.

    Raises ForwardTestIntegrityError if accepting the record would make the
    log something other than a forward test. See the module docstring; these
    raise rather than return so a caller cannot proceed as though the write
    had happened.
    """
    p = Path(log_path) if log_path else DEFAULT_LOG_PATH
    wall = _parse(now) if now is not None else _utcnow()
    bar_dt = _parse(bar_time)
    bar_secs = _bar_seconds(timeframe)

    if direction.upper() not in ("LONG", "SHORT"):
        raise ForwardTestIntegrityError(
            f"direction must be LONG or SHORT, got {direction!r}"
        )
    direction = direction.upper()

    risk = (entry - stop_loss) if direction == "LONG" else (stop_loss - entry)
    if not risk > 0:
        raise ForwardTestIntegrityError(
            f"{symbol} {timeframe} {direction}: stop ({stop_loss}) is not on the losing "
            f"side of entry ({entry}), so this prediction has no risk denominator and no "
            f"R-multiple can ever be computed for it."
        )

    inception = _ensure_inception(p, now=wall)

    if bar_dt > wall + pd.Timedelta(seconds=bar_secs).to_pytimedelta():
        raise ForwardTestIntegrityError(
            f"{symbol} {timeframe}: bar_time {bar_dt.isoformat()} is in the future relative "
            f"to now ({wall.isoformat()}). Refusing to record a prediction about a bar that "
            f"has not happened."
        )

    # The floor is inception MINUS the staleness tolerance, not inception
    # itself. A log started at 14:00 must still accept today's 1d bar, which is
    # stamped 00:00 and so predates inception by fourteen hours through no
    # fault of anyone's -- rejecting it would make the guard fire on the first
    # legitimate record every time the log is created. Allowing the same
    # `max_staleness_bars` window used everywhere else keeps one consistent
    # rule rather than inventing a second, looser one for the first bar.
    floor = inception - pd.Timedelta(seconds=max_staleness_bars * bar_secs).to_pytimedelta()
    if bar_dt < floor:
        raise ForwardTestIntegrityError(
            f"{symbol} {timeframe}: bar_time {bar_dt.isoformat()} predates this log's "
            f"inception ({inception.isoformat()}) by more than {max_staleness_bars} bars. "
            f"Backfilling past bars into a forward test would make it a backtest -- which "
            f"this strategy already has, and which is exactly the evidence a forward test "
            f"exists to supplement."
        )

    staleness = (wall - bar_dt).total_seconds()
    if staleness > max_staleness_bars * bar_secs:
        raise ForwardTestIntegrityError(
            f"{symbol} {timeframe}: bar_time {bar_dt.isoformat()} is {staleness / bar_secs:.1f} "
            f"bars old at record time (limit {max_staleness_bars}). A prediction written long "
            f"after its bar closed had the outcome available to it and is not forward evidence."
        )

    existing = load_log(p)
    for rec in existing:
        if (rec.symbol == symbol and rec.timeframe == timeframe
                and rec.strategy == strategy and rec.direction == direction
                and _parse(rec.bar_time) == bar_dt):
            return None

    record = ForwardTestRecord(
        record_id=uuid.uuid4().hex[:16],
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy,
        direction=direction,
        bar_time=_iso(bar_dt),
        recorded_at=_iso(wall),
        entry=float(entry),
        stop_loss=float(stop_loss),
        take_profit=float(take_profit),
        horizon_bars=int(horizon_bars),
        params=dict(params or {}),
        confidence=confidence,
        source=source,
        backtest_claim=dict(backtest_claim or {}),
    )
    doc = {"kind": "prediction"}
    doc.update({k: v for k, v in asdict(record).items()
                if k not in ("outcome", "exit_price", "exit_time", "r_multiple",
                             "bars_held", "ambiguous_bar", "resolved_at")})
    _append(p, doc)
    logger.info("forward_test: recorded %s %s %s %s @ %s",
                symbol, timeframe, strategy, direction, record.bar_time)
    return record


# --------------------------------------------------------------------------
# Resolution -- from real bars, never from the prediction itself
# --------------------------------------------------------------------------

def resolve_record(record: ForwardTestRecord, bars: pd.DataFrame,
                   now: Optional[datetime] = None) -> Optional[dict]:
    """Resolve one prediction against real OHLC bars.

    `bars` must be indexed by timestamp and contain high/low/close. Only bars
    strictly AFTER the prediction's own bar are considered -- resolving a
    prediction on the bar that generated it would let the entry bar's own
    range decide the outcome, which is the classic lookahead error.

    Returns None when the prediction has not matured yet (fewer than
    horizon_bars of subsequent data exist and neither level has been touched),
    which is a normal state, not a failure.
    """
    if bars is None or bars.empty:
        return None

    # Accepts this platform's native frame shape (RangeIndex + `timestamp`
    # column) as well as an already-indexed one. Requiring a DatetimeIndex here
    # was a real defect: every frame e02_market_data returns would have been
    # rejected, so no prediction could ever have been resolved.
    df = as_time_indexed(bars)
    cols = {c.lower(): c for c in df.columns}
    for need in ("high", "low", "close"):
        if need not in cols:
            logger.warning("forward_test: bars missing %r column; cannot resolve %s",
                           need, record.record_id)
            return None
    hi_c, lo_c, cl_c = cols["high"], cols["low"], cols["close"]

    bar_dt = _parse(record.bar_time)
    future = df[df.index > pd.Timestamp(bar_dt)]
    if future.empty:
        return None
    future = future.iloc[: record.horizon_bars]

    long = record.direction == "LONG"
    risk = (record.entry - record.stop_loss) if long else (record.stop_loss - record.entry)

    outcome = exit_price = exit_time = None
    ambiguous = False
    bars_held = 0

    for i, (ts, row) in enumerate(future.iterrows(), start=1):
        high, low = float(row[hi_c]), float(row[lo_c])
        if long:
            hit_stop = low <= record.stop_loss
            hit_target = high >= record.take_profit
        else:
            hit_stop = high >= record.stop_loss
            hit_target = low <= record.take_profit

        if hit_stop and hit_target:
            # OHLC cannot order two touches inside one bar. Resolve against
            # the strategy and say so, rather than picking the flattering one.
            outcome, exit_price, exit_time, ambiguous, bars_held = (
                "stop", record.stop_loss, ts, True, i)
            break
        if hit_stop:
            outcome, exit_price, exit_time, bars_held = "stop", record.stop_loss, ts, i
            break
        if hit_target:
            outcome, exit_price, exit_time, bars_held = "target", record.take_profit, ts, i
            break

    if outcome is None:
        # Not matured: neither level touched and the horizon has not elapsed.
        if len(future) < record.horizon_bars:
            return None
        last_ts = _parse(future.index[-1])
        # A horizon exit settles at a CLOSE, so that bar must actually have
        # closed. Resolutions are first-wins and never revisited, so taking a
        # forming bar's provisional close would bake a price that was never
        # final into the R-multiple permanently. An intrabar stop/target touch
        # above is different -- a high is a high whether or not the bar is done.
        if last_ts + pd.Timedelta(seconds=_bar_seconds(record.timeframe)).to_pytimedelta() > (
                _parse(now) if now is not None else _utcnow()):
            return None
        outcome = "horizon"
        exit_price = float(future.iloc[-1][cl_c])
        exit_time = last_ts
        bars_held = len(future)

    move = (exit_price - record.entry) if long else (record.entry - exit_price)
    r_multiple = move / risk

    return {
        "kind": "resolution",
        "record_id": record.record_id,
        "outcome": outcome,
        "exit_price": round(float(exit_price), 8),
        "exit_time": _iso(_parse(exit_time)),
        "r_multiple": round(float(r_multiple), 4),
        "bars_held": int(bars_held),
        "ambiguous_bar": bool(ambiguous),
        "resolved_at": _iso(_utcnow()),
    }


def resolve_pending(
    bars_for: Any,
    log_path: Path | None = None,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Resolve every unresolved prediction for which data now exists.

    `bars_for(symbol, timeframe)` supplies OHLC. It is injected rather than
    imported so that resolution can be tested against known bars, and so this
    module never decides for itself where market data comes from.
    """
    p = Path(log_path) if log_path else DEFAULT_LOG_PATH
    records = [r for r in load_log(p) if not r.resolved]
    if not records:
        return []

    by_series: dict[tuple[str, str], list[ForwardTestRecord]] = {}
    for r in records:
        by_series.setdefault((r.symbol, r.timeframe), []).append(r)

    written: list[dict] = []
    for (symbol, timeframe), recs in by_series.items():
        try:
            bars = bars_for(symbol, timeframe)
        except Exception as e:  # noqa: BLE001 - one bad series must not sink the rest
            logger.warning("forward_test: no bars for %s %s: %s", symbol, timeframe, e)
            continue
        if bars is None or getattr(bars, "empty", True):
            continue
        for rec in recs:
            res = resolve_record(rec, bars, now=now)
            if res is not None:
                _append(p, res)
                written.append(res)
    return written


# --------------------------------------------------------------------------
# Comparison against the backtest claim
# --------------------------------------------------------------------------

def _posterior(wins: int, losses: int, prior_alpha: float, prior_beta: float) -> Optional[dict]:
    """Beta-Binomial posterior via E12, which already implements and documents
    this. Returns None if E12 is unavailable, rather than substituting a
    hand-rolled approximation that would answer the same question differently
    from the rest of the platform."""
    try:
        from project_titan_x.engines.e12_quant_research.engine import QuantResearchEngine
    except Exception as e:  # noqa: BLE001
        logger.warning("forward_test: E12 unavailable (%s); no posterior computed", e)
        return None
    res = QuantResearchEngine().bayesian_win_rate_update(
        wins=wins, losses=losses, prior_alpha=prior_alpha, prior_beta=prior_beta
    )
    if not res.success or res.data is None:
        logger.warning("forward_test: E12 posterior failed: %s", res.message)
        return None
    return {
        "mean": res.data.posterior_mean,
        "ci_90": list(res.data.credible_interval_90pct),
    }


def compare_to_backtest(
    records: list[ForwardTestRecord],
    backtest_win_rate: Optional[float],
    backtest_trades: Optional[int] = None,
    min_decidable: int = MIN_DECIDABLE_TRADES,
) -> dict:
    """Compare resolved forward outcomes against what the backtest claimed.

    The verdict is drawn from the forward evidence ALONE (uniform prior). The
    backtest-as-prior posterior is reported alongside for context but never
    decides, because the trustworthiness of that backtest is the question.
    """
    resolved = [r for r in records if r.resolved and r.r_multiple is not None]
    n = len(resolved)
    wins = sum(1 for r in resolved if r.is_win)
    losses = n - wins
    ambiguous = sum(1 for r in resolved if r.ambiguous_bar)

    out: dict[str, Any] = {
        "forward_trades": n,
        "wins": wins,
        "losses": losses,
        "forward_win_rate": round(wins / n, 4) if n else None,
        "forward_expectancy_r": round(sum(r.r_multiple for r in resolved) / n, 4) if n else None,
        "forward_total_r": round(sum(r.r_multiple for r in resolved), 4) if n else None,
        "ambiguous_resolutions": ambiguous,
        "ambiguous_fraction": round(ambiguous / n, 4) if n else None,
        "backtest_win_rate": backtest_win_rate,
        "unresolved": len(records) - n,
        "notes": [],
    }

    if n == 0:
        out["verdict"] = "no_forward_evidence"
        out["notes"].append(
            "No resolved forward trades yet. Nothing here supports or contradicts the "
            "backtest; the strategy is running on historical evidence alone."
        )
        return out

    forward_only = _posterior(wins, losses, 1.0, 1.0)
    out["posterior_forward_only"] = forward_only

    if backtest_win_rate is not None and backtest_trades:
        a = max(backtest_win_rate * backtest_trades, 1e-6)
        b = max((1.0 - backtest_win_rate) * backtest_trades, 1e-6)
        out["posterior_with_backtest_prior"] = _posterior(wins, losses, a, b)
        out["notes"].append(
            "The backtest-prior posterior is context only. It carries "
            f"{backtest_trades} pseudo-observations and would swamp {n} forward trades, "
            "which is precisely what must not decide whether the backtest held up."
        )

    if ambiguous:
        out["notes"].append(
            f"{ambiguous} of {n} resolutions came from bars whose range contained both the "
            "stop and the target; OHLC cannot order those touches, and each was counted as a "
            "stop. The true result is no worse than this and may be better."
        )

    if n < min_decidable:
        out["verdict"] = "insufficient_evidence"
        out["notes"].append(
            f"{n} resolved forward trades is below the {min_decidable}-trade floor for any "
            "verdict. The numbers above are real but not yet decidable."
        )
        return out

    if backtest_win_rate is None:
        out["verdict"] = "no_claim_to_test"
        out["notes"].append(
            "No backtest win rate was recorded with these predictions, so forward results "
            "cannot be compared against a claim."
        )
        return out

    if forward_only is None:
        # Kept distinct from `no_claim_to_test` deliberately. Both used to
        # return the same verdict, which meant a broken E12 import reported
        # itself as "this strategy never made a claim" -- a silent downgrade
        # that looked like a property of the data instead of a broken
        # dependency, and would have gone unnoticed indefinitely.
        out["verdict"] = "statistics_unavailable"
        out["notes"].append(
            "A backtest claim exists but the Beta-Binomial posterior could not be computed "
            "(e12_quant_research unavailable -- see the log). This is a broken dependency, "
            "not a finding about the strategy."
        )
        return out

    lo, hi = forward_only["ci_90"]
    if backtest_win_rate > hi:
        out["verdict"] = "degraded"
        out["notes"].append(
            f"The backtest claim ({backtest_win_rate:.1%}) sits ABOVE the 90% credible "
            f"interval of forward evidence ({lo:.1%}-{hi:.1%}). Live behaviour is worse than "
            "the result that justified deploying this strategy."
        )
    elif backtest_win_rate < lo:
        out["verdict"] = "better_than_claim"
        out["notes"].append(
            f"Forward results ({lo:.1%}-{hi:.1%}) exceed the backtest claim "
            f"({backtest_win_rate:.1%}). Pleasant, but treat it as unexplained rather than "
            "as licence to size up -- an unexpected direction is still an unmodelled one."
        )
    else:
        out["verdict"] = "consistent"
        out["notes"].append(
            f"The backtest claim ({backtest_win_rate:.1%}) falls inside the 90% credible "
            f"interval of forward evidence ({lo:.1%}-{hi:.1%}). Consistent so far."
        )
    return out


def breakeven_win_rate(reward_risk: float) -> Optional[float]:
    """The win rate at which a strategy with this reward:risk stops making
    money: 1 / (1 + RR).

    This exists because testing a win rate against 50% silently assumes an even
    bet, and almost nothing here is one. BTC-USD's live `dual_thrust` signal
    plans a stop 3,229 below entry and a target 6,458 above it -- 2:1 -- where
    breakeven is 33.3%, not 50%. Asking "when would I notice this fall to a
    coin flip" of a 2:1 strategy asks when it would fall far BELOW breakeven,
    which is both the wrong question and a far slower one to answer.
    """
    if reward_risk is None or reward_risk <= 0:
        return None
    return 1.0 / (1.0 + reward_risk)


def planned_reward_risk(records: list[ForwardTestRecord]) -> Optional[float]:
    """Median planned reward:risk across predictions, from the levels actually
    recorded at decision time.

    Median, not mean: one signal with an unusually distant target would
    otherwise drag the breakeven estimate and with it every derived count.
    """
    ratios = []
    for r in records:
        long = r.direction == "LONG"
        risk = (r.entry - r.stop_loss) if long else (r.stop_loss - r.entry)
        reward = (r.take_profit - r.entry) if long else (r.entry - r.take_profit)
        if risk > 0 and reward > 0:
            ratios.append(reward / risk)
    if not ratios:
        return None
    ratios.sort()
    mid = len(ratios) // 2
    return ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2


def claim_significance(
    win_rate: Optional[float],
    trades: Optional[int],
    breakeven: Optional[float],
) -> Optional[dict]:
    """How unlikely the backtest's win rate would be if the strategy only ever
    hit its breakeven rate -- i.e. if it had no edge beyond paying for itself.

    Reported because a raw win rate invites exactly one misreading, and this
    module's own author made it: `dual_thrust`'s 52.5% looks like noise against
    50% (p=0.37) and is strongly significant against the 33.3% it actually has
    to beat (p=0.0003). Both numbers are returned so the comparison cannot be
    quoted without its baseline.

    This describes the BACKTEST, not forward evidence. It is context for
    reading the claim, never a substitute for testing it forward.
    """
    if not win_rate or not trades or breakeven is None:
        return None
    try:
        from scipy import stats as scipy_stats
    except Exception:  # noqa: BLE001
        return None
    wins = round(win_rate * trades)
    return {
        "wins": wins,
        "trades": trades,
        "breakeven_win_rate": round(breakeven, 4),
        "p_vs_breakeven": float(scipy_stats.binom.sf(wins - 1, trades, breakeven)),
        "p_vs_coin_flip": float(scipy_stats.binom.sf(wins - 1, trades, 0.5)),
    }


def observations_needed_to_detect(
    claimed_win_rate: float,
    degraded_win_rate: float,
    confidence: float = 0.95,
    max_n: int = 2000,
) -> Optional[int]:
    """Smallest number of forward trades at which, if the true win rate were
    `degraded_win_rate`, the evidence would place `claimed_win_rate` outside
    the posterior's upper bound.

    This is the number the user actually needs: it converts "let it run and
    see" into a concrete count, and for a daily strategy it is usually large
    enough to be sobering. Returns None if `max_n` is reached, which is itself
    the answer -- a degradation that small is not detectable in any practical
    horizon.
    """
    try:
        from scipy import stats as scipy_stats
    except Exception as e:  # noqa: BLE001
        logger.warning("forward_test: scipy unavailable (%s)", e)
        return None
    if not (0.0 < degraded_win_rate < claimed_win_rate < 1.0):
        return None
    for n in range(5, max_n + 1):
        wins = degraded_win_rate * n
        upper = float(scipy_stats.beta.ppf(confidence, 1.0 + wins, 1.0 + (n - wins)))
        if upper < claimed_win_rate:
            return n
    return None


# --------------------------------------------------------------------------
# Orchestration
#
# These two functions know about override files and the engine chain, which
# the rest of this module deliberately does not. The registry is INJECTED
# rather than imported, for two reasons: this module stays importable (and
# testable) without standing up 60-odd engines, and both the CLI
# (scripts/run_forward_test.py) and the API's own scheduler can drive the
# same code path instead of each growing a slightly different copy of it.
# --------------------------------------------------------------------------

OVERRIDE_DIR = _ROOT / "data" / "models" / "e51_signals"

# Fallback holding period when an override's params carry none, so a
# prediction's horizon is always a recorded number rather than an implicit
# consequence of whichever engine happened to exit first.
DEFAULT_HORIZON_BARS = 10


def validated_overrides(override_dir: Path | None = None) -> list[dict]:
    """Every strategy override carrying an explicit stage0 VALIDATED tag.

    Deliberately re-implements the tag CHECK rather than importing
    `e51_signals._load_strategy_override`: that function returns the strategy
    config and discards the file identity, while this needs the symbol,
    timeframe and backtest claim to freeze into each prediction. The one thing
    it must agree on is the deny-by-default rule, which is the single
    `== "VALIDATED"` comparison below -- anything else (an explicit
    UNVALIDATED, a missing block, a malformed one) is not forward tested,
    because it is not driving live decisions either.
    """
    d = Path(override_dir) if override_dir else OVERRIDE_DIR
    out = []
    for path in sorted(d.glob("*_strategy_override.json")):
        stem = path.name.replace("_strategy_override.json", "")
        symbol, _, timeframe = stem.rpartition("_")
        if not symbol or not timeframe:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("forward_test: unreadable override %s (%s)", path.name, e)
            continue
        if (doc.get("stage0") or {}).get("status") != "VALIDATED":
            continue
        measured = (doc.get("stage0") or {}).get("measured") or {}
        out.append({
            "yahoo_symbol": symbol,
            "timeframe": timeframe,
            "strategy": doc.get("strategy"),
            "params": doc.get("params") or {},
            "claim": {
                "win_rate": doc.get("win_rate"),
                "total_trades": doc.get("total_trades"),
                "is_sharpe": doc.get("is_sharpe"),
                "oos_sharpe": doc.get("oos_sharpe"),
                "null_percentile": measured.get("null_percentile"),
                "validated_at": doc.get("validated_at"),
            },
        })
    return out


_PROCESSED_DIR = _ROOT / "data" / "processed"


def registry_bars_resolver(registry: Any) -> Any:
    """A `bars_for(symbol, timeframe)` callable backed by e02_market_data,
    falling back to the processed parquet when a live fetch fails.

    Resolution must PREFER fresh data. The processed parquets are a snapshot
    from whenever the last ingest ran, and resolving against them would leave
    every prediction made since then permanently unresolved -- which would look
    like a quiet log rather than a stale one, and quietly stall the forward
    test at exactly the moment it started mattering.
    """
    def bars_for(yahoo_symbol: str, timeframe: str):
        try:
            md = registry.get("e02_market_data")
            if md is not None:
                res = md.fetch_ohlcv(yahoo_symbol, timeframe, years=1)
                if res.success and res.data is not None and not res.data.empty:
                    return res.data
        except Exception as e:  # noqa: BLE001
            logger.warning("forward_test: live fetch failed for %s %s (%s); using disk",
                           yahoo_symbol, timeframe, e)
        p = _PROCESSED_DIR / f"{yahoo_symbol}_{timeframe}.parquet"
        return pd.read_parquet(p) if p.exists() else None

    return bars_for


def scan_and_record(
    registry: Any,
    overrides: Optional[list[dict]] = None,
    log_path: Path | None = None,
    source: str = "forward_test.scan_and_record",
    now: Optional[datetime] = None,
) -> dict:
    """Run each validated override through the LIVE engine chain and log what
    it says about the latest bar, before the outcome is knowable.

    The chain is E07 -> E04 -> E06 -> E08 -> E51, in the same order and with
    the same arguments as api/main.py::generate_signal. A forward test of a
    reimplementation would measure the reimplementation.

    Any engine failure SKIPS that symbol and reports it as skipped. Nothing is
    filled in with a default, because a fabricated prediction in the one log
    that is supposed to contain only real ones would be worse than a gap.
    """
    if overrides is None:
        overrides = validated_overrides()

    recorded: list[dict] = []
    skipped: list[tuple[str, str]] = []
    silent: list[tuple[str, str]] = []

    try:
        from project_titan_x.core.config import list_assets
        assets = list_assets()
    except Exception:  # noqa: BLE001
        assets = []

    for ov in overrides:
        ysym, tf = ov["yahoo_symbol"], ov["timeframe"]
        asset = next((a for a in assets if a.yahoo_symbol == ysym), None)
        sym = asset.symbol if asset else ysym
        label = f"{sym} {tf}"

        try:
            md = registry.get("e02_market_data")
            fetch = md.fetch_ohlcv(ysym, tf, years=2)
            if not fetch.success or fetch.data is None or fetch.data.empty:
                skipped.append((label, f"market data: {fetch.message}"))
                continue
            df = fetch.data

            dq = registry.get("e40_data_quality")
            if dq is not None:
                rep = dq.repair(df)
                df = rep.data if rep.success else df

            ta = registry.get("e07_technical").analyze(df, symbol=sym, timeframe=tf)
            if not ta.success:
                skipped.append((label, f"e07_technical: {ta.message}"))
                continue

            macro = registry.get("e04_macro").analyze()
            macro_data = macro.data if macro.success else None
            macro_score = macro_data.risk_on_off_score if macro_data else 0.0

            fundamental = registry.get("e06_fundamental").analyze()
            fundamental_data = fundamental.data if fundamental.success else None

            regime = registry.get("e08_regime").classify(df, ta.data["snapshot"], macro_data)
            if not regime.success:
                skipped.append((label, f"e08_regime: {regime.message}"))
                continue

            sig = registry.get("e51_signals").generate_signal(
                sym, df, ta.data["snapshot"], regime.data, macro_score,
                macro_snapshot=macro_data, fundamental_snapshot=fundamental_data,
                enriched_df=ta.data.get("df"),
            )
        except Exception as e:  # noqa: BLE001 - one symbol must not sink the run
            skipped.append((label, f"exception: {e}"))
            continue

        if not sig.success or sig.data is None:
            # No signal is a real observation about the strategy, but it is not
            # a TRADE. Logging flat bars would pad the denominator of a win
            # rate that is about trades taken.
            silent.append((label, sig.message or "no signal"))
            continue

        s = sig.data
        horizon = int(ov["params"].get("hold_bars") or DEFAULT_HORIZON_BARS)
        try:
            rec = record_signal(
                symbol=ysym, timeframe=tf, strategy=ov["strategy"],
                direction=s.direction,
                # NOT df.index[-1]: this platform's OHLCV frames carry a
                # RangeIndex with the bar time in a `timestamp` column, so that
                # expression yields a row number. It did, on the first live run.
                bar_time=bar_timestamp(df),
                entry=float(s.entry), stop_loss=float(s.stop_loss),
                take_profit=float(s.take_profit_1), horizon_bars=horizon,
                params=ov["params"], confidence=int(s.confidence_score),
                source=source, backtest_claim=ov["claim"], log_path=log_path,
                now=now,
            )
        except ForwardTestIntegrityError as e:
            skipped.append((label, f"REFUSED: {e}"))
            continue

        if rec is None:
            silent.append((label, "already recorded for this bar"))
        else:
            recorded.append({
                "label": label, "direction": s.direction, "bar_time": rec.bar_time,
                "entry": s.entry, "stop_loss": s.stop_loss,
                "take_profit": s.take_profit_1, "confidence": s.confidence_score,
            })
            logger.info("forward_test: recorded %s %s @ %s (conf %s)",
                        label, s.direction, s.entry, s.confidence_score)

    return {"recorded": recorded, "skipped": skipped, "silent": silent}


def as_trade_dicts(records: list[ForwardTestRecord]) -> list[dict]:
    """Resolved forward predictions in the shape `e38_alpha_decay_monitor`
    already consumes, most-recent-first (E35.list_trades' own ordering).

    This exists so decay detection is not written twice. E38 and this module
    answer DIFFERENT questions and both are needed:

      * `compare_to_backtest` asks whether live behaviour matches the backtest
        claim that justified deploying the strategy;
      * E38 asks whether recent live behaviour has decayed relative to EARLIER
        live behaviour, which can happen while still matching the claim, and
        can fail to happen while never matching it.

    `pnl_percent` is deliberately left as the R-multiple scaled by the risk
    percentage only when that is known; a forward record stores R, not account
    percentage, and inventing one would put a fabricated number into a decay
    test. E38 tolerates it: it checks win rate and expectancy on `pnl_r` first.
    """
    resolved = [r for r in records if r.resolved and r.r_multiple is not None]
    resolved.sort(key=lambda r: r.exit_time or r.bar_time, reverse=True)
    return [
        {
            "pnl_r": r.r_multiple,
            "pnl_percent": None,
            "strategy_name": r.strategy,
            "symbol": r.symbol,
            "direction": r.direction,
            "exit_time": r.exit_time,
        }
        for r in resolved
    ]


def decay_assessment(
    records: list[ForwardTestRecord],
    strategy_name: Optional[str] = None,
    quant_engine: Any = None,
) -> Optional[dict]:
    """Run E38's decay test over forward evidence, or None if E38 is absent.

    Returns E38's own verdict verbatim rather than a reinterpretation, so
    `e25_strategy_lifecycle`'s existing `decaying` stage keeps one definition
    of decay across the platform.
    """
    try:
        from project_titan_x.engines.e38_alpha_decay_monitor.engine import (
            assess_decay_from_trades,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("forward_test: E38 unavailable (%s); no decay assessment", e)
        return None
    trades = as_trade_dicts(records)
    if not trades:
        return None
    res = assess_decay_from_trades(trades, quant_engine, strategy_name=strategy_name)
    return res.to_dict() if hasattr(res, "to_dict") else None


def summarise(
    log_path: Path | None = None,
    min_decidable: int = MIN_DECIDABLE_TRADES,
) -> dict:
    """Per-(symbol, timeframe, strategy) forward-test state for the whole log."""
    records = load_log(log_path)
    inception = inception_time(log_path)
    groups: dict[tuple[str, str, str], list[ForwardTestRecord]] = {}
    for r in records:
        groups.setdefault((r.symbol, r.timeframe, r.strategy), []).append(r)

    series = []
    for (symbol, timeframe, strategy), recs in sorted(groups.items()):
        claim = next((r.backtest_claim for r in recs if r.backtest_claim), {})
        wr = claim.get("win_rate")
        cmp_ = compare_to_backtest(recs, wr, claim.get("total_trades"),
                                   min_decidable=min_decidable)
        entry = {
            "symbol": symbol, "timeframe": timeframe, "strategy": strategy,
            "predictions": len(recs), "backtest_claim": claim, **cmp_,
        }
        if wr:
            # "How long until this means anything", measured against the point
            # where the strategy stops PAYING rather than an arbitrary 50%.
            # For a 2:1 structure those are wildly different questions: 33.3%
            # is breakeven, and asking when it would reach 50% asks when it
            # would fall far below breakeven -- a much larger drop, and so a
            # much slower one to detect.
            rr = planned_reward_risk(recs)
            be = breakeven_win_rate(rr) if rr else None
            entry["planned_reward_risk"] = round(rr, 3) if rr else None
            entry["breakeven_win_rate"] = round(be, 4) if be else None
            threshold = be if (be is not None and be < wr) else 0.5
            entry["degradation_threshold"] = round(threshold, 4)
            need = observations_needed_to_detect(wr, threshold)
            entry["trades_to_detect_degradation"] = need

            sig = claim_significance(wr, claim.get("total_trades"), threshold)
            entry["claim_significance"] = sig
            # PHASE 35 (decay detection) via E38's existing test, so the
            # platform keeps ONE definition of decay -- the same verdict string
            # e25_strategy_lifecycle already reads for its `decaying` stage.
            entry["decay"] = decay_assessment(recs, strategy_name=strategy)
            if sig:
                entry["notes"].append(
                    f"Backtest claim read against its own breakeven ({threshold:.1%}): "
                    f"p={sig['p_vs_breakeven']:.2g}. Against a 50% baseline the same claim "
                    f"reads p={sig['p_vs_coin_flip']:.2g} -- quoting either number without "
                    f"its baseline invites the wrong conclusion. Both describe the BACKTEST, "
                    f"not forward evidence."
                )
            if be is not None and be >= wr:
                entry["notes"].append(
                    f"The claimed win rate ({wr:.1%}) is at or below the breakeven win rate "
                    f"implied by the planned {rr:.2f}:1 reward:risk ({be:.1%}). On these "
                    f"levels the strategy does not profit at its own claimed hit rate."
                )
            if need and len(recs) > 1:
                span = (_parse(recs[-1].bar_time) - _parse(recs[0].bar_time)).total_seconds()
                rate = (len(recs) - 1) / span if span > 0 else 0
                if rate > 0:
                    entry["estimated_days_to_that_many"] = round(need / rate / 86400, 1)
        series.append(entry)

    return {
        "generated_at": _iso(_utcnow()),
        "inception": _iso(inception) if inception else None,
        "total_predictions": len(records),
        "total_resolved": sum(1 for r in records if r.resolved),
        "series": series,
    }
