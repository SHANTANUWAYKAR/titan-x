"""
Module: heartbeat.py
Description: Liveness tracking for scheduled work and data feeds --
    `reports/upgrade statergy.txt` PHASE 25 (observability) and PHASE 27
    (failure engineering), raised as **P0.2** in docs/INSTITUTIONAL_AUDIT.md.

    THE FAILURE MODE THIS CLOSES. Before this, nothing in the platform could
    detect that a scheduled job had stopped running. That failure is silent in
    both directions and both directions are dangerous:

      * a dead scheduler looks exactly like a quiet market -- the forward-test
        log simply stops growing, and an empty log reads as "no signals" rather
        than "no longer looking";
      * a stale data feed looks exactly like a calm one -- signals keep being
        generated, confidently, against bars that stopped updating.

    `/health` made this worse rather than better: it returned a hardcoded
    `"status": "healthy"` regardless of anything, so the one endpoint whose job
    is to say when something is wrong could never say so.

    WHY A FILE AND NOT A METRICS BACKEND. PHASE 25 ultimately wants Prometheus
    or equivalent. That is P3 in the audit, deliberately: until something
    records which jobs exist and when they last succeeded, there is nothing for
    a metrics backend to scrape. This module is the missing prerequisite, not a
    substitute -- a few hundred bytes of JSON under `data/state/` (an existing
    directory; no new folder is created) that survives a restart, which an
    in-memory counter would not.

    NEVER-RUN IS NOT HEALTHY. The most important distinction here. A job that
    has never executed reports `never_run`, never `ok`. The whole point is to
    catch work that silently stopped or never started, and defaulting an
    unknown job to healthy would reintroduce exactly the blindness this exists
    to remove.

    RECORDING IS BEST-EFFORT, READING IS NOT. `record_success`/`record_failure`
    swallow their own errors: a heartbeat write must never take down the real
    work it was observing. `check()` does not swallow -- a caller asking "is
    anything wrong" deserves an answer or an exception, not a reassuring empty
    list.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = _ROOT / "data" / "state" / "heartbeats.json"

# How far past its expected interval a job may drift before it is called stale.
# 2.0 rather than 1.0 because a job that runs every 6 hours will not run exactly
# on the hour -- startup time, a slow fetch and clock skew all push it later,
# and a monitor that cries stale on every ordinary late run gets ignored, which
# is worse than no monitor at all.
STALE_MULTIPLIER = 2.0

# Consecutive failures before a job is reported as failing rather than merely
# having had a bad run. One transient fetch error is normal operation.
FAILING_AFTER_CONSECUTIVE = 3


@dataclass
class Heartbeat:
    name: str
    expected_interval_seconds: Optional[float] = None
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0


@dataclass
class HeartbeatStatus:
    name: str
    state: str                      # ok | stale | failing | never_run
    detail: str
    seconds_since_success: Optional[float] = None
    expected_interval_seconds: Optional[float] = None
    consecutive_failures: int = 0

    @property
    def healthy(self) -> bool:
        return self.state == "ok"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def load(state_path: Path | None = None) -> dict[str, Heartbeat]:
    """Every recorded heartbeat, keyed by name. Empty when nothing has run."""
    p = Path(state_path) if state_path else DEFAULT_STATE_PATH
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("heartbeat: unreadable state at %s (%s); treating as empty", p, e)
        return {}
    out: dict[str, Heartbeat] = {}
    for name, doc in (raw.get("heartbeats") or {}).items():
        try:
            out[name] = Heartbeat(**{**doc, "name": name})
        except TypeError:
            # An entry written by a newer/older version must not sink the rest.
            logger.warning("heartbeat: skipping unreadable entry %r", name)
    return out


def _save(beats: dict[str, Heartbeat], state_path: Path | None = None) -> None:
    """Atomic write: a crash mid-write must not leave a truncated state file
    that then reads as 'nothing has ever run' and hides every real problem."""
    p = Path(state_path) if state_path else DEFAULT_STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _utcnow().isoformat(),
        "heartbeats": {n: {k: v for k, v in asdict(b).items() if k != "name"}
                       for n, b in beats.items()},
    }
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_success(
    name: str,
    expected_interval_seconds: Optional[float] = None,
    state_path: Path | None = None,
    now: Optional[datetime] = None,
) -> None:
    """Note that `name` just completed successfully. Best-effort: a failure to
    record a heartbeat must never take down the work it was observing."""
    try:
        beats = load(state_path)
        b = beats.get(name) or Heartbeat(name=name)
        b.last_success = (now or _utcnow()).isoformat()
        b.consecutive_failures = 0
        b.last_error = None
        b.total_successes += 1
        if expected_interval_seconds is not None:
            b.expected_interval_seconds = float(expected_interval_seconds)
        beats[name] = b
        _save(beats, state_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("heartbeat: could not record success for %r: %s", name, e)


def record_failure(
    name: str,
    error: str,
    expected_interval_seconds: Optional[float] = None,
    state_path: Path | None = None,
    now: Optional[datetime] = None,
) -> None:
    """Note that `name` ran and failed. Same best-effort contract."""
    try:
        beats = load(state_path)
        b = beats.get(name) or Heartbeat(name=name)
        b.last_failure = (now or _utcnow()).isoformat()
        b.last_error = str(error)[:500]
        b.consecutive_failures += 1
        b.total_failures += 1
        if expected_interval_seconds is not None:
            b.expected_interval_seconds = float(expected_interval_seconds)
        beats[name] = b
        _save(beats, state_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("heartbeat: could not record failure for %r: %s", name, e)


def check(
    expected: Optional[dict[str, float]] = None,
    state_path: Path | None = None,
    now: Optional[datetime] = None,
) -> list[HeartbeatStatus]:
    """Current state of every known job, worst first.

    `expected` names jobs that OUGHT to exist, mapped to their interval in
    seconds. A name listed there with no recorded heartbeat reports
    `never_run` -- which is the entire point: a job that was never registered,
    or that died before its first success, is exactly the thing that would
    otherwise be invisible.
    """
    at = now or _utcnow()
    beats = load(state_path)
    names = set(beats) | set(expected or {})
    out: list[HeartbeatStatus] = []

    for name in sorted(names):
        b = beats.get(name)
        interval = (expected or {}).get(name)
        if b is not None and b.expected_interval_seconds is not None and interval is None:
            interval = b.expected_interval_seconds

        if b is None or not b.last_success:
            failed = b.consecutive_failures if b else 0
            detail = (f"never succeeded ({failed} failure(s) recorded, last: {b.last_error})"
                      if failed and b else "has never run")
            out.append(HeartbeatStatus(
                name=name, state="never_run", detail=detail,
                expected_interval_seconds=interval, consecutive_failures=failed))
            continue

        last = _parse(b.last_success)
        age = (at - last).total_seconds() if last else None

        if b.consecutive_failures >= FAILING_AFTER_CONSECUTIVE:
            out.append(HeartbeatStatus(
                name=name, state="failing",
                detail=(f"{b.consecutive_failures} consecutive failures since last success "
                        f"{b.last_success}; last error: {b.last_error}"),
                seconds_since_success=age, expected_interval_seconds=interval,
                consecutive_failures=b.consecutive_failures))
            continue

        if interval and age is not None and age > interval * STALE_MULTIPLIER:
            out.append(HeartbeatStatus(
                name=name, state="stale",
                detail=(f"last succeeded {age / 3600:.1f}h ago, expected every "
                        f"{interval / 3600:.1f}h -- the job may have stopped running"),
                seconds_since_success=age, expected_interval_seconds=interval,
                consecutive_failures=b.consecutive_failures))
            continue

        out.append(HeartbeatStatus(
            name=name, state="ok",
            detail=f"last succeeded {age / 3600:.1f}h ago" if age is not None else "ok",
            seconds_since_success=age, expected_interval_seconds=interval,
            consecutive_failures=b.consecutive_failures))

    order = {"never_run": 0, "failing": 1, "stale": 2, "ok": 3}
    out.sort(key=lambda s: (order.get(s.state, 9), s.name))
    return out


def overall_state(statuses: list[HeartbeatStatus]) -> str:
    """`healthy` only when nothing is wrong. Anything else is `degraded`.

    Not graded further on purpose: a health endpoint exists to answer one
    question, and a spectrum of reassuring-sounding intermediate states is how
    a monitor stops being read.
    """
    return "healthy" if all(s.healthy for s in statuses) else "degraded"


# Seconds per bar, for judging how old a dataset's newest bar is.
_BAR_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1wk": 604800,
}

# Bars of tolerance before data is called stale, by whether the market trades
# continuously. Crypto is 24/7, so 3 bars is a real gap. Everything else closes
# on weekends and holidays: a Friday daily close is legitimately ~3 days old by
# Monday morning, and a long weekend stretches that further.
#
# This distinction is not cosmetic. A blanket 3-bar rule flags every equity,
# forex, index and commodity instrument as stale every single weekend, and a
# staleness alarm that fires on all of them 104 days a year is one nobody reads
# by the time it matters.
_STALE_BARS_CONTINUOUS = 3.0
_STALE_BARS_SESSION_BASED = 5.0
_CONTINUOUS_CLASSES = {"crypto"}


def data_staleness_verdict(
    symbol: str,
    timeframe: str,
    last_bar: datetime,
    now: Optional[datetime] = None,
) -> dict:
    """Is this instrument's newest bar too old to act on?

    Returns `{state, age_seconds, age_bars, tolerance_bars, detail}` where
    state is `ok` or `stale`. Shared by `/health` and the live signal path so
    the endpoint that reports staleness and the endpoint that refuses to act on
    it cannot disagree.
    """
    at = now or _utcnow()
    bar = _BAR_SECONDS.get(timeframe)
    if not bar:
        return {"state": "unknown", "detail": f"unknown timeframe {timeframe!r}",
                "age_seconds": None, "age_bars": None, "tolerance_bars": None}

    if last_bar.tzinfo is None:
        last_bar = last_bar.replace(tzinfo=timezone.utc)
    age = (at - last_bar.astimezone(timezone.utc)).total_seconds()

    continuous = True
    try:
        from project_titan_x.core.config.assets import get_asset
        asset = get_asset(symbol)
        if asset is not None and asset.asset_class is not None:
            continuous = str(asset.asset_class.value) in _CONTINUOUS_CLASSES
    except Exception:  # noqa: BLE001 - an unknown asset is treated as continuous,
        # which is the STRICTER of the two tolerances; a staleness check should
        # not become more permissive because it failed to identify something.
        continuous = True

    tol = _STALE_BARS_CONTINUOUS if continuous else _STALE_BARS_SESSION_BASED
    age_bars = age / bar
    stale = age_bars > tol
    return {
        "state": "stale" if stale else "ok",
        "age_seconds": round(age, 1),
        "age_bars": round(age_bars, 2),
        "tolerance_bars": tol,
        "continuous_market": continuous,
        "detail": (f"newest bar is {age / 3600:.1f}h old ({age_bars:.1f} bars; "
                   f"tolerance {tol:g} for a "
                   f"{'24/7' if continuous else 'session-based'} market)"),
    }


def guard(name: str, expected_interval_seconds: Optional[float] = None,
          state_path: Path | None = None) -> Any:
    """Context manager recording success or failure around a block of work.

    Re-raises whatever the block raised -- this observes, it never swallows.
    """
    import contextlib

    @contextlib.contextmanager
    def _cm():
        try:
            yield
        except Exception as e:
            record_failure(name, str(e), expected_interval_seconds, state_path)
            raise
        else:
            record_success(name, expected_interval_seconds, state_path)

    return _cm()
