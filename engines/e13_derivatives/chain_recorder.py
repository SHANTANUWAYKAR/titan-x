"""
Module: chain_recorder.py
Description: Append-only history of the options surface, so IV-based levels
    become testable later instead of never.

    WHY THIS EXISTS. e13_derivatives can read a live chain and already computes
    everything an expected-move strategy needs -- ATM IV per expiry, max pain,
    skew, the VRP spread -- and then throws all of it away. Before this module
    `data/models/e13_derivatives/` held exactly one file, a realized-vol
    percentile baseline. No implied vol had ever been persisted, which makes an
    IV-based backtest impossible: not hard, impossible, because the input does
    not exist at any price. Yahoo will sell you ten years of OHLC; nobody will
    sell you the chain you failed to record.

    That is the same trap the forward test is in (PHASE 33): evidence only
    accrues on observations actually made, and a day not recorded is lost, not
    backfillable. The cost of starting is one scheduled call; the cost of not
    starting is that the question stays unanswerable for as many months as it
    takes to notice.

    WHAT IS RECORDED. One JSON line per (timestamp, currency): spot, ATM IV and
    days-to-expiry for the nearest expiry, the full term structure, max pain,
    skew, put/call ratios, realized vol, and the expected-move LEVELS derived
    from them. Levels are stored rather than only their inputs so a later
    analysis reads the same numbers a trader would have seen, not a
    reconstruction that might drift as this code changes.

    PER-STRIKE OPEN INTEREST IS RECORDED. An earlier version of this module
    claimed the strike ladder needed a heavier call and stored only aggregates.
    That was wrong: `get_book_summary_by_currency` already returns
    `open_interest` for every instrument with strike and expiry encoded in the
    name (verified live -- 968 BTC instruments, 824 carrying OI), so the ladder
    costs nothing extra. It is stored for the nearest expiry, which is what the
    "gamma wall" reading needs: the strikes where dealer inventory concentrates
    and price tends to pin.

    APPEND-ONLY BY DESIGN. Each run appends; nothing rewrites earlier lines. A
    crash mid-write costs the current line, never the history. Re-running
    inside the same dedup window is a no-op rather than a duplicate, matching
    forward_test.record_signal's own convention.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_STORE = (
    Path(__file__).resolve().parents[2]
    / "data" / "models" / "e13_derivatives" / "chain_history.jsonl"
)

# A snapshot inside this window of the previous one for the same currency is a
# no-op. Hourly is a deliberate compromise: fine enough that a day produces
# several independent reads of the surface, coarse enough that an API server
# restarting repeatedly cannot flood the history with near-identical rows.
_DEDUP_SECONDS = 3600

# Sigma multiples stored. 1.0 is the "ceiling/floor" boundary; 0.5 is the inner
# "normal range". Both are kept so a later test can ask which one, if either,
# actually marks the extreme -- rather than baking in one choice now.
_SIGMA_LEVELS = (0.5, 1.0)


# DerivativesSnapshot stores vol as a PERCENT, not a decimal -- confirmed
# against a live Deribit read: nearest_expiry_atm_iv 40.77 with
# realized_vol_30d 36.84 and iv_minus_rv 3.93, which only reconcile as
# percentages. Feeding 40.77 into a formula expecting 0.4077 overstates every
# expected move by 100x, so the conversion happens in exactly one place here
# and the convention is asserted rather than assumed.
_IV_IS_PERCENT_ABOVE = 1.5


def _iv_to_decimal(atm_iv: float) -> float:
    """Annualised vol as a decimal, whichever convention it arrived in.

    A real annualised vol below 1.5 (150%) is already decimal; above that it
    can only be a percent, since a 150%+ decimal vol does not occur on a liquid
    ATM contract. The threshold sits above crypto's genuine range so a
    legitimately high decimal IV is never silently divided.
    """
    iv = float(atm_iv)
    return iv / 100.0 if iv > _IV_IS_PERCENT_ABOVE else iv


# A 0DTE expiry has hours of life left, not zero -- but sqrt(0/365) is exactly
# 0, which collapses every level onto spot and looks like a working
# calculation. Floor the horizon at a few hours so an expiring contract
# produces a small band rather than a meaningless one, and record the horizon
# actually used so a later reader is never guessing.
_MIN_DAYS = 0.25


def expected_move_levels(
    spot: float, atm_iv: float, days_to_expiry: float
) -> dict[str, float]:
    """Price levels implied by the option market's own expected move.

    `EM = S * sigma * sqrt(T/365)`, the one-sigma move for horizon T.
    `atm_iv` may arrive as percent or decimal; see _iv_to_decimal.

    Returns {} when the inputs cannot support the calculation, never a
    fabricated level.
    """
    if not spot or not atm_iv or days_to_expiry is None or days_to_expiry < 0:
        return {}
    try:
        days = max(float(days_to_expiry), _MIN_DAYS)
        atm_iv = _iv_to_decimal(atm_iv)
        t = math.sqrt(days / 365.0)
    except (TypeError, ValueError):
        return {}
    one_sigma = float(spot) * float(atm_iv) * t
    out: dict[str, float] = {
        "one_sigma_move": round(one_sigma, 6),
        "iv_decimal": round(float(atm_iv), 6),
        "days_used": round(days, 4),
    }
    for k in _SIGMA_LEVELS:
        out[f"ceiling_{k}"] = round(float(spot) + k * one_sigma, 6)
        out[f"floor_{k}"] = round(float(spot) - k * one_sigma, 6)
    return out


def strike_ladder(book: Any, expiry: Any, top: int = 25) -> list[dict]:
    """Open interest by strike for one expiry, largest first.

    `book` is Deribit's book-summary list; strike and right are parsed from the
    instrument name. Calls and puts are kept apart because they mean opposite
    things for dealer hedging -- collapsing them into one number per strike
    would destroy exactly the asymmetry the wall reading depends on.

    Returns [] rather than a guess when the book cannot be parsed.
    """
    if not book or expiry is None:
        return []
    try:
        from project_titan_x.engines.e13_derivatives.engine import _parse_instrument
    except Exception:  # pragma: no cover
        return []
    by_strike: dict[float, dict[str, float]] = {}
    for row in book:
        oi = row.get("open_interest")
        if not oi:
            continue
        parsed = _parse_instrument(row.get("instrument_name", ""))
        if not parsed:
            continue
        exp, strike, right = parsed
        if exp != expiry:
            continue
        slot = by_strike.setdefault(float(strike), {"call_oi": 0.0, "put_oi": 0.0})
        slot["call_oi" if right == "C" else "put_oi"] += float(oi)
    out = [
        {"strike": k, "call_oi": round(v["call_oi"], 2), "put_oi": round(v["put_oi"], 2),
         "total_oi": round(v["call_oi"] + v["put_oi"], 2)}
        for k, v in by_strike.items()
    ]
    out.sort(key=lambda r: r["total_oi"], reverse=True)
    return out[:top]


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if is_dataclass(v) and not isinstance(v, type):
        return {k: _jsonable(x) for k, x in asdict(v).items()}
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _last_timestamp(currency: str) -> Optional[datetime]:
    """Newest recorded timestamp for `currency`, or None.

    Reads the tail rather than the whole file so this stays cheap as the
    history grows.
    """
    if not _STORE.exists():
        return None
    try:
        with _STORE.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            back = min(size, 200_000)
            fh.seek(size - back)
            tail = fh.read().decode("utf-8", errors="ignore").splitlines()
    except OSError as e:
        logger.warning("chain history unreadable (%s) -- treating as empty", e)
        return None
    for line in reversed(tail):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn final line is skipped, not fatal
        if row.get("currency") == currency and row.get("timestamp"):
            try:
                return datetime.fromisoformat(row["timestamp"])
            except ValueError:
                return None
    return None


def record_snapshot(snapshot: Any, *, force: bool = False, book: Any = None) -> dict[str, Any]:
    """Append one DerivativesSnapshot to the history.

    Returns {"recorded": bool, "reason": str, ...}. A snapshot inside the dedup
    window is skipped and reported, not written twice.
    """
    if snapshot is None:
        return {"recorded": False, "reason": "no snapshot"}

    currency = getattr(snapshot, "currency", None)
    spot = getattr(snapshot, "spot_price", None)
    if not currency or not spot:
        return {"recorded": False, "reason": "snapshot missing currency/spot"}

    ts = getattr(snapshot, "timestamp", None) or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    if not force:
        prev = _last_timestamp(currency)
        if prev is not None:
            if prev.tzinfo is None:
                prev = prev.replace(tzinfo=timezone.utc)
            age = (ts - prev).total_seconds()
            if 0 <= age < _DEDUP_SECONDS:
                return {
                    "recorded": False,
                    "reason": f"within {_DEDUP_SECONDS}s dedup window ({age:.0f}s since last)",
                    "currency": currency,
                }

    atm_iv = getattr(snapshot, "nearest_expiry_atm_iv", None)
    term = getattr(snapshot, "term_structure", None) or []
    dte = None
    for p in term:
        d = getattr(p, "days_to_expiry", None)
        if d is not None:
            dte = d
            break

    # The approach this supports is WEEKLY ("Weekly Ceiling"/"Weekly Floor"),
    # while the nearest expiry is frequently 0DTE -- a different instrument
    # answering a different question. Record the expiry closest to 7 days
    # alongside it, with its own IV, so the weekly band does not have to be
    # reconstructed later from a daily one.
    weekly = None
    best = None
    for p in term:
        d = getattr(p, "days_to_expiry", None)
        iv = getattr(p, "atm_iv", None)
        if d is None or iv is None:
            continue
        gap = abs(float(d) - 7.0)
        if best is None or gap < best:
            best, weekly = gap, p

    row = {
        "timestamp": ts.isoformat(),
        "currency": currency,
        "spot_price": float(spot),
        "nearest_expiry_atm_iv": atm_iv,
        "nearest_expiry_days": dte,
        "levels": expected_move_levels(spot, atm_iv, dte) if (atm_iv and dte is not None) else {},
        "weekly_expiry_days": getattr(weekly, "days_to_expiry", None) if weekly else None,
        "weekly_atm_iv": getattr(weekly, "atm_iv", None) if weekly else None,
        "weekly_levels": (
            expected_move_levels(spot, getattr(weekly, "atm_iv", None), getattr(weekly, "days_to_expiry", None))
            if weekly else {}
        ),
        "max_pain_strike": getattr(snapshot, "max_pain_strike", None),
        "skew_proxy": getattr(snapshot, "skew_proxy", None),
        "skew_label": getattr(snapshot, "skew_label", None),
        "put_call_ratio_oi": getattr(snapshot, "put_call_ratio_oi", None),
        "put_call_ratio_volume": getattr(snapshot, "put_call_ratio_volume", None),
        "realized_vol_30d": getattr(snapshot, "realized_vol_30d", None),
        "realized_vol_regime": getattr(snapshot, "realized_vol_regime", None),
        "iv_minus_rv": getattr(snapshot, "iv_minus_rv", None),
        "term_structure": _jsonable(term),
        # Strikes where dealer inventory concentrates -- the "wall" half of the
        # expected-move approach. Nearest expiry only: that is the one whose
        # hedging flow actually pins spot today.
        "strike_ladder": strike_ladder(book, getattr(snapshot, "nearest_expiry", None)),
        # Recorded so a later reader can tell which code produced the row.
        "recorder_version": "1.0.0",
    }

    _STORE.parent.mkdir(parents=True, exist_ok=True)
    with _STORE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return {
        "recorded": True,
        "reason": "appended",
        "currency": currency,
        "timestamp": row["timestamp"],
        "has_levels": bool(row["levels"]),
    }


def record_all(engine, symbols: tuple[str, ...] = ("BTCUSD", "ETHUSD"), *, force: bool = False) -> dict:
    """Record every symbol the derivatives engine can actually price.

    One symbol failing does not stop the others -- a partial history beats no
    history, and the per-symbol reason is reported rather than swallowed.
    """
    out: dict[str, Any] = {"recorded": [], "skipped": [], "failed": {}}
    for sym in symbols:
        try:
            res = engine.analyze(sym)
        except Exception as e:  # noqa: BLE001 - one symbol must not sink the run
            out["failed"][sym] = str(e)
            continue
        if not getattr(res, "success", False) or getattr(res, "data", None) is None:
            out["failed"][sym] = getattr(res, "message", "no data")
            continue
        # The book is re-fetched here only because analyze() does not return
        # it. One extra call per symbol per hour, in exchange for the strike
        # ladder; a failure degrades to "no ladder", never to "no snapshot".
        book = None
        try:
            cur = getattr(res.data, "currency", None)
            if cur:
                book = engine._deribit.get_book_summary_by_currency(cur, "option")
        except Exception as e:  # noqa: BLE001
            logger.warning("strike ladder unavailable for %s: %s", sym, e)
        r = record_snapshot(res.data, force=force, book=book)
        (out["recorded"] if r["recorded"] else out["skipped"]).append(
            {"symbol": sym, **r}
        )
    return out


def summarise() -> dict:
    """What the history actually contains -- rows, span, and per-currency counts."""
    if not _STORE.exists():
        return {"exists": False, "rows": 0, "note": "no chain history recorded yet"}
    rows = 0
    by_cur: dict[str, int] = {}
    first = last = None
    with _STORE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows += 1
            c = r.get("currency", "?")
            by_cur[c] = by_cur.get(c, 0) + 1
            ts = r.get("timestamp")
            if ts:
                first = first or ts
                last = ts
    return {
        "exists": True,
        "rows": rows,
        "by_currency": by_cur,
        "first": first,
        "last": last,
        "path": str(_STORE),
    }
