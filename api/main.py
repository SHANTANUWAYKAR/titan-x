"""
Module: main.py
Description: FastAPI application entry point for PROJECT TITAN-X.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func

from project_titan_x import __version__
from project_titan_x.core.config import (
    get_asset,
    get_settings,
    is_asset_supported,
    list_assets,
)
from project_titan_x.core.database import (
    NewsEvent,
    OptionChainOISnapshot,
    Signal,
    SignalContextSnapshot,
    Trade,
    TradeIntent,
    get_db_session,
)
from project_titan_x.engines.e03_news.enrichment import (
    classify_event_type,
    extract_entities,
    market_impact_score,
    normalized_content_hash,
)
from project_titan_x.engines.e45_risk import FUNDINGPIPS_PROFILES, TradeRiskProposal
from project_titan_x.core import heartbeat as _heartbeat
from project_titan_x.engines.registry import get_registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
def _warn_if_exposed() -> None:
    """Say plainly, at startup, when the API is reachable without a key.

    An unauthenticated service is a configuration state, not an error, so it
    must not raise -- but it must not be silent either. The loud branch is
    the genuinely dangerous combination: a non-loopback bind with no key,
    which is what "just make it reachable from my phone" quietly produces.
    """
    loopback = settings.api_host in ("127.0.0.1", "localhost", "::1")
    if settings.api_key:
        logger.info("API key auth ENABLED (X-API-Key required); bound to %s", settings.api_host)
    elif loopback:
        logger.warning(
            "API key NOT set -- all routes are unauthenticated. Safe only because the "
            "bind address is loopback (%s). Set API_KEY before exposing this port.",
            settings.api_host,
        )
    else:
        logger.error(
            "SECURITY: API bound to %s with NO API key. Every route, including "
            "market-data fetch and the brain workflow runner, is reachable "
            "without authentication by anything that can route to this host. "
            "Set API_KEY, or bind 127.0.0.1.",
            settings.api_host,
        )


async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    _warn_if_exposed()
    registry = get_registry()
    init_results = registry.initialize_all()
    logger.info("Engine initialization: %s", init_results)

    # Real cost found and fixed 2026-07-20: the sentence-transformers
    # embedding model (core.vector_store.client._get_embedding_model) is
    # deliberately lazy-loaded on first actual use, NOT at import/registry-
    # construction time -- importing transformers+torch alone measured
    # ~23s, so this was deferred to avoid paying it on every process start
    # regardless of whether semantic search was ever used. That trade-off
    # is wrong for THIS entry point specifically: a real running server's
    # dashboard touches knowledge-base search (e07_technical's own
    # knowledge_context, e51_signals') on nearly every single/scan
    # request, so "lazy" here just meant "whichever user's request happens
    # to go first eats a ~20-25s stall with no warning" -- profiled live:
    # 1st call 22.8s, every call after 0.0-2.0s. Warmed explicitly here so
    # the cost is paid once, predictably, during startup (which the user
    # already expects to wait through) instead of silently during
    # whatever real request is unlucky enough to be first.
    try:
        t0 = time.time()
        from project_titan_x.core.vector_store.client import _get_embedding_model
        _get_embedding_model()
        logger.info("Embedding model warmed in %.1fs -- knowledge/semantic search is now fast for every request", time.time() - t0)
    except Exception as e:
        logger.warning("Embedding model warm-up failed (%s) -- first real knowledge-search request will pay this cost instead", e)

    # Background auto-scan (added 2026-08-09, per user request): runs the
    # SAME real scan_all_assets() the dashboard's own "Scan" button calls
    # (never a second/duplicate scan implementation) on a recurring
    # interval via E00 Titan Brain's own existing TaskScheduler --
    # "nothing scheduled by default anywhere in this codebase" per that
    # scheduler's own docstring, until now, opted into explicitly here.
    # 1d timeframe specifically (not 1h): confirmed live 2026-08-09 this
    # is the timeframe with real validated strategy overrides/positive
    # backtested edge -- 1h currently has no validated edge for any
    # asset (see CLAUDE.md's own documented finding), so auto-scanning 1h
    # would just burn real API calls for a result that always resolves to
    # "no signal," not a useful background feature.
    # 45 minutes: conservative relative to the real external rate-limiting
    # (Yahoo Finance) this platform hit live under concurrent load this
    # same session -- frequent enough to be useful, not so frequent it
    # risks tripping that limit on an unattended, unsupervised loop.
    try:
        titan_brain = registry.get("e00_titan_brain")
        signal_engine = registry.get("e51_signals")
        if titan_brain is not None and signal_engine is not None:
            def _background_scan() -> None:
                try:
                    result = signal_engine.scan_all_assets(
                        registry.get("e02_market_data"), registry.get("e07_technical"),
                        registry.get("e08_regime"), registry.get("e04_macro"), "1d",
                        fundamental_engine=registry.get("e06_fundamental"),
                        data_quality_engine=registry.get("e40_data_quality"),
                    )
                    n_signals = len(result.data) if result.success and result.data else 0
                    logger.info("Background auto-scan: %s (%d signal(s))", result.message, n_signals)
                    titan_brain.publish("background_scan_complete", {"n_signals": n_signals, "success": result.success})
                    # Heartbeat: without this, a scan that stops running is
                    # indistinguishable from a market with no signals.
                    _heartbeat.record_success("background_auto_scan", 45 * 60)
                except Exception as e:
                    logger.error("Background auto-scan failed: %s", e)
                    _heartbeat.record_failure("background_auto_scan", str(e), 45 * 60)

            titan_brain.scheduler.schedule_interval("background_auto_scan", 45 * 60, _background_scan)
            logger.info("Background auto-scan scheduled: every 45 minutes on the 1d timeframe")
    except Exception as e:
        logger.warning("Could not schedule background auto-scan (%s) -- server still starts, scanning stays manual (dashboard 'Scan' button)", e)

    # Forward test (added 2026-09-15). reports/statergy.txt NON-NEGOTIABLE #14
    # requires forward testing to precede live trading, and both currently-live
    # overrides (BTC-USD_1d dual_thrust, ETH-USD_1d mss_trend_hold) earned their
    # VALIDATED tags from historical evidence only -- an in-sample sweep, a
    # walk-forward split and a synthetic-null percentile, every one of them
    # computed over bars that already existed when the search ran.
    #
    # Scheduled rather than left to scripts/run_forward_test.py because the
    # integrity rules make a missed run UNRECOVERABLE by design:
    # forward_test.record_signal refuses any bar more than three bars stale, so
    # a day nobody remembered to run the script is a permanent gap in the
    # evidence. A forward test that depends on remembering is one that quietly
    # stops being a forward test.
    #
    # 6 hours, not 45 minutes like the scan above: these are 1d strategies, so
    # there is at most one new bar per day, and a second call inside the same
    # bar is a deduplicated no-op. Four attempts per day is redundancy against
    # restarts and fetch failures, not extra sampling.
    try:
        titan_brain = registry.get("e00_titan_brain")
        if titan_brain is not None:
            from project_titan_x.engines.e24_strategy_research import forward_test as _ft

            def _forward_test_tick() -> None:
                try:
                    # Resolve BEFORE recording, so one tick can never both
                    # create a prediction and settle it.
                    resolved = _ft.resolve_pending(_ft.registry_bars_resolver(registry))
                    out = _ft.scan_and_record(registry, source="api.lifespan.forward_test")
                    logger.info(
                        "Forward test: %d resolved, %d recorded, %d skipped, %d silent",
                        len(resolved), len(out["recorded"]), len(out["skipped"]),
                        len(out["silent"]),
                    )
                    for label, why in out["skipped"]:
                        logger.warning("Forward test skipped %s -- %s", label, why)
                    # Heartbeat: a forward test that silently stops running is
                    # the worst case here -- the log stops growing, and an
                    # empty log reads as "no signals" rather than "no longer
                    # looking". Missed bars cannot be backfilled by design.
                    _heartbeat.record_success("forward_test", 6 * 60 * 60)
                except Exception as e:
                    # Never fabricate a record on failure; a gap is recoverable
                    # evidence-wise, a fabricated prediction is not.
                    logger.error("Forward test tick failed: %s", e)
                    _heartbeat.record_failure("forward_test", str(e), 6 * 60 * 60)

            titan_brain.scheduler.schedule_interval(
                "forward_test", 6 * 60 * 60, _forward_test_tick)
            n_live = len(_ft.validated_overrides())
            logger.info(
                "Forward test scheduled: every 6 hours, tracking %d VALIDATED override(s)",
                n_live)
    except Exception as e:
        logger.warning(
            "Could not schedule the forward test (%s) -- server still starts, but live "
            "strategies then accumulate NO out-of-sample evidence unless "
            "scripts/run_forward_test.py is run manually once per bar", e)

    # ------------------------------------------------------------------
    # Options-surface recorder.
    #
    # Scheduled for the same reason the forward test is: the data only exists
    # while it is being collected. Deribit serves the CURRENT chain -- there is
    # no endpoint, and no vendor at any price, that will sell back the surface
    # from a day nobody recorded. Before this job, `data/models/
    # e13_derivatives/` held one realized-vol baseline and no implied vol at
    # all, which made every IV-based level permanently un-backtestable.
    #
    # Hourly, matching chain_recorder's own dedup window, so a server that
    # restarts repeatedly cannot flood the history with near-identical rows.
    # BTC/ETH only: Deribit is this platform's sole free options source and
    # lists nothing else. Index options would need a paid feed.
    # ------------------------------------------------------------------
    try:
        if titan_brain is not None:
            from project_titan_x.engines.e13_derivatives import chain_recorder as _cr

            def _chain_record_tick() -> None:
                try:
                    deriv = registry.get("e13_derivatives")
                    if deriv is None:
                        raise RuntimeError("e13_derivatives not in registry")
                    out = _cr.record_all(deriv)
                    logger.info(
                        "Option chains: %d recorded, %d skipped, %d failed",
                        len(out["recorded"]), len(out["skipped"]), len(out["failed"]),
                    )
                    for sym, why in out["failed"].items():
                        logger.warning("Option chain failed for %s -- %s", sym, why)
                    _heartbeat.record_success("option_chain_record", 60 * 60)
                except Exception as e:
                    # A gap is recoverable in the sense that later rows still
                    # accrue; a fabricated surface would poison every level
                    # derived from it. So: log, never invent.
                    logger.error("Option chain tick failed: %s", e)
                    _heartbeat.record_failure("option_chain_record", str(e), 60 * 60)

            titan_brain.scheduler.schedule_interval(
                "option_chain_record", 60 * 60, _chain_record_tick)
            _summary = _cr.summarise()
            logger.info(
                "Option chain recorder scheduled: hourly (history has %d row(s))",
                _summary.get("rows", 0))
    except Exception as e:
        logger.warning(
            "Could not schedule the option chain recorder (%s) -- server still starts, "
            "but no implied-vol history accumulates unless "
            "scripts/record_option_chains.py is run on a schedule", e)

    yield
    logger.info("PROJECT TITAN-X shutting down")


# --------------------------------------------------------------------------
# API KEY GATE
#
# Every route except this exempt set requires a matching X-API-Key header
# WHEN settings.api_key is set. Health and docs stay open so a container
# healthcheck and a human orienting themselves do not need the secret.
#
# When api_key is unset the gate is inert and the API is open. That is only
# defensible because api_host now defaults to loopback; if someone binds a
# non-loopback interface without setting a key, the startup warning below
# says so explicitly rather than letting it pass silently.
_AUTH_EXEMPT_PATHS = frozenset({"/", "/health", "/docs", "/redoc", "/openapi.json"})


async def require_api_key(request: Request) -> None:
    """Reject requests without a valid X-API-Key, when a key is configured."""
    if request.url.path in _AUTH_EXEMPT_PATHS:
        return
    expected = settings.api_key
    if not expected:
        return
    provided = request.headers.get("X-API-Key") or ""
    # compare_digest, not ==, so a wrong key cannot be recovered a character
    # at a time by timing the response.
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


app = FastAPI(
    title="PROJECT TITAN-X",
    description="Institutional-Grade Trading Intelligence Platform (Small Capital Mode)",
    version=__version__,
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)

_CORS_ORIGINS = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]

# Explicit origins, not "*". The previous ["*"] + allow_credentials=True is a
# combination the CORS spec forbids and browsers refuse, so it granted nothing
# while disabling the origin check for every non-credentialed request.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


class SignalRequest(BaseModel):
    asset: str
    direction: str = Field(pattern="^(LONG|SHORT)$")
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_percent: float = 0.5
    confidence_score: int = Field(ge=0, le=100)
    regime: str = ""


class FundedAccountActivateRequest(BaseModel):
    profile: str = Field(description=f"One of: {sorted(FUNDINGPIPS_PROFILES.keys())}")
    account_size: float = Field(gt=0, description="Real, current account balance -- never guessed")
    current_equity: Optional[float] = Field(default=None, description="Defaults to account_size if omitted")


class FundedAccountEquityUpdateRequest(BaseModel):
    current_equity: float


class FetchDataRequest(BaseModel):
    symbol: str
    timeframe: str = "1d"
    years: int = 2


class KellyRequest(BaseModel):
    win_rate: float = Field(gt=0, lt=1)
    avg_win: float = Field(gt=0)
    avg_loss: float = Field(gt=0)
    fraction_cap: float = Field(default=0.25, gt=0, le=1)


class BayesianWinRateRequest(BaseModel):
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    prior_alpha: float = Field(default=1.0, gt=0)
    prior_beta: float = Field(default=1.0, gt=0)


class SentimentRequest(BaseModel):
    text: str = Field(min_length=1)


class SentimentBatchRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class BlackLittermanApiRequest(BaseModel):
    symbols: list[str] = Field(min_length=2)
    market_weights: list[float]
    P: list[list[float]]
    Q: list[float]
    timeframe: str = "1d"
    years: int = 2
    risk_aversion: float = 2.5
    tau: float = Field(default=0.05, gt=0)


class VolatilityTargetApiRequest(BaseModel):
    symbols: list[str] = Field(min_length=2)
    weights: list[float]
    target_vol: float = Field(ge=0)
    timeframe: str = "1d"
    years: int = 2
    max_leverage: float = Field(default=3.0, gt=0)


class TradeCreate(BaseModel):
    """A manually-logged, already-closed trade -- this platform has no
    execution engine (Rule 5), so every trade is a retrospective journal
    entry, optionally linked back to the E51 signal that prompted it."""

    symbol: str
    direction: str = Field(pattern="^(long|short)$")
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl_r: float
    pnl_percent: float
    strategy_name: str = "unspecified"
    confidence_at_entry: Optional[int] = Field(default=None, ge=0, le=100)
    regime_at_entry: Optional[str] = None
    session_tag: Optional[str] = None
    notes: Optional[str] = None
    # Links back to the exact Signal row _persist_signal() created when this
    # trade's originating signal was generated (see /signals/generate and
    # /signals/scan) -- was previously always None in practice since nothing
    # ever populated the `signals` table for this to point at.
    signal_id: Optional[int] = None
    # Added 2026-08-21 for the self-improvement journal's
    # position_size_exceeded/revenge_trade mistake checks -- this platform
    # has no execution engine and captures no real position-size data
    # (Rule 5), so this is an OPTIONAL, honestly-labeled self-report of
    # the risk % actually used, not persisted as a Trade column (see
    # PerformanceAnalyticsEngine.log_trade's own docstring) -- only fed
    # into mistake-tag computation and recorded in that tag's own detail.
    risk_percent_used: Optional[float] = Field(default=None, ge=0)
    # Added 2026-09-13, Phase 9. setup/timeframe/screenshot_url/slippage_r
    # are real Trade columns. stop_loss_price is transient like
    # risk_percent_used above -- never persisted itself, used only to
    # convert a real OHLCV-measured price excursion into an R-multiple for
    # mae_r/mfe_r (see PerformanceAnalyticsEngine.compute_mae_mfe_r). Both
    # mae_r/mfe_r are deliberately absent from this schema: they are
    # server-computed from real price history, never client-supplied.
    setup: Optional[str] = None
    timeframe: Optional[str] = None
    screenshot_url: Optional[str] = Field(default=None, max_length=500)
    slippage_r: Optional[float] = None
    stop_loss_price: Optional[float] = None


def _validate_asset(symbol: str) -> str:
    """Validate asset is supported (no equities)."""
    if not is_asset_supported(symbol):
        asset = get_asset(symbol)
        if asset is None:
            raise HTTPException(
                400,
                f"Asset '{symbol}' not supported. Equities excluded. "
                f"Use forex, crypto, commodities, or indices only.",
            )
    return symbol


def _prepare_ohlcv(symbol: str, timeframe: str, years: int = 2):
    """Fetch, validate asset, clean OHLCV data."""
    _validate_asset(symbol)
    registry = get_registry()
    md_engine = registry.get("e02_market_data")
    if not md_engine:
        raise HTTPException(500, "Market Data Engine not available")

    asset = get_asset(symbol)
    yahoo_symbol = asset.yahoo_symbol if asset else symbol

    fetch = md_engine.fetch_ohlcv(yahoo_symbol, timeframe, years=years)
    if not fetch.success:
        raise HTTPException(400, fetch.message)

    df = fetch.data
    dq_engine = registry.get("e40_data_quality")
    if dq_engine:
        repaired = dq_engine.repair(df)
        df = repaired.data if repaired.success else df
    return df, asset


def _persist_signal(signal) -> Optional[int]:
    """Best-effort persistence of a real generated TradingSignal into the
    `signals` table -- returns its new id, or None on any failure (DB
    unreachable, etc.), never raising and never blocking the response the
    signal itself came from.

    This closes a real, previously-dead gap: Trade.signal_id has always
    existed as a foreign key intended to link a logged trade back to the
    exact signal that prompted it (including its full supporting_evidence,
    e.g. whether a news/sentiment confluence check agreed or disagreed with
    the direction) -- but nothing ever actually wrote a row to `signals`,
    so that link could never be made. Wiring this in means: (a) every real
    signal is now a real, queryable, permanent record, not just an
    ephemeral API response, and (b) once trades get logged against these
    signal_ids, it becomes possible to honestly ask "historically, when
    sentiment confluence agreed with the direction, did those trades
    actually win more often?" from real accumulated evidence -- something
    that was previously unanswerable since E03 only ever sees LIVE
    headlines (no historical news archive exists to backtest against
    directly)."""
    try:
        with get_db_session() as session:
            row = Signal(
                asset=signal.asset,
                direction=signal.direction,
                entry_price=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit_1=signal.take_profit_1,
                take_profit_2=signal.take_profit_2,
                risk_percent=signal.risk_percent,
                confidence_score=signal.confidence_score,
                expected_value=signal.expected_value,
                regime=signal.regime,
                evidence=list(signal.supporting_evidence),
                invalidation=signal.invalidation,
                status=signal.status,
            )
            session.add(row)
            session.flush()
            signal_id = row.id
            # Added 2026-08-21 for the self-improvement journal: real
            # context captured at generation time, before any human
            # click -- see SignalContextSnapshot's own docstring for why
            # confidence_score/regime/evidence aren't duplicated here
            # (they already live on `row` above, this only adds the one
            # genuinely new piece of context).
            try:
                from project_titan_x.engines.e07_technical.killzones import active_killzones_at
                active_zones = active_killzones_at(signal.created_at)
                session.add(SignalContextSnapshot(
                    signal_id=signal_id, killzone_active=bool(active_zones),
                    active_killzones=[z.value for z in active_zones],
                ))
            except Exception as e:
                logger.warning("Could not compute killzone context for signal %s (non-fatal): %s", signal_id, e)
            return signal_id
    except Exception as e:
        logger.warning("Could not persist signal (non-fatal, response unaffected): %s", e)
        return None


def _db_reachable() -> bool:
    """Cheap up-front reachability probe -- same ~2s connect_timeout cost
    as a single _persist_signal call, but paid ONCE instead of once per
    signal. Real bug found and fixed 2026-07-20: scan_signals used to call
    _persist_signal() in a loop for every returned signal with no such
    check -- when Postgres is down, that's N sequential ~2s connection
    timeouts (a real scan returning 15-20 signals added 30-40s of pure
    dead-connection retries AFTER scan_all_assets' own work already
    finished, unbounded by that method's internal circuit breaker, which
    only wraps the engine-level work, not this route's post-processing).
    Same "check once, skip the whole batch if unreachable" discipline
    already applied to e01_knowledge._load_seed_data this same session.

    Real bug found IN THIS FIX, same session: get_db_session() opens a
    SQLAlchemy Session lazily -- `SessionLocal()` alone never actually
    connects, only the first real query does. The first version of this
    check was `with get_db_session(): return True`, which entered the
    context and exited without ever issuing a query -- so it reported
    "reachable" unconditionally regardless of whether Postgres was really
    up, and every _persist_signal call in the loop below still paid its
    own full connect_timeout. Fixed by actually executing a trivial query,
    which is the only thing that forces the real connection attempt."""
    try:
        from sqlalchemy import text
        with get_db_session() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("Postgres appears unreachable (%s) -- skipping signal persistence for this request", e)
        return False


@app.get("/")
def root():
    """Root path -- redirects straight to the dashboard so opening this URL
    in a browser (whether by the startup script's auto-open, a bookmark, or
    typing it manually) always lands on the actual UI instead of raw JSON.
    Programmatic API info moved to /api/v1/info (used by the dashboard's own
    fetch, which needs JSON, not a redirect)."""
    return RedirectResponse(url="/dashboard")


@app.get("/api/v1/info")
def api_info():
    """API/platform info -- same content the root path used to return."""
    return {
        "name": "PROJECT TITAN-X",
        "version": __version__,
        "author": "Shantanu Waykar",
        "philosophy": "Risk First. Evidence Always. Capital Protected.",
        "mode": "small_capital",
        "equities_enabled": settings.equities_enabled,
        "starting_capital": settings.starting_capital,
        "capital_currency": settings.capital_currency,
        "execution_mode": settings.execution_mode,
    }


# Scheduled jobs that OUGHT to be running, and how often. Listing a job here
# is what makes its ABSENCE detectable: core.heartbeat.check reports a name it
# has never seen as `never_run` rather than omitting it, so a job that died
# before its first success, or was never registered because its try/except in
# lifespan swallowed a startup error, shows up instead of silently not
# existing. Previously this endpoint returned a hardcoded "healthy" and could
# not report a problem of any kind.
_EXPECTED_JOBS = {
    "background_auto_scan": 45 * 60,
    "forward_test": 6 * 60 * 60,
    "option_chain_record": 60 * 60,
}


def _ft_bar_time(df):
    """Timestamp of the newest bar in an OHLCV frame, whatever its shape.

    Delegates to forward_test.bar_timestamp rather than reading `df.index[-1]`:
    this platform's frames use a RangeIndex with the time in a `timestamp`
    column, so the obvious expression returns a row number. It did, on the
    forward test's first live run -- the integer 729 reached a date parser.
    """
    from project_titan_x.engines.e24_strategy_research import forward_test as _ft
    return _ft.bar_timestamp(df)


def _data_staleness() -> list[dict]:
    """Age of the newest bar for each instrument currently trading live.

    A stale feed is the failure this platform is least equipped to notice on
    its own: signals keep being produced, with full confidence, against bars
    that stopped updating. Only VALIDATED overrides are checked -- those are
    the only instruments a stale feed could actually cost money on.
    """
    from project_titan_x.engines.e24_strategy_research import forward_test as _ft

    out = []
    for ov in _ft.validated_overrides():
        ysym, tf = ov["yahoo_symbol"], ov["timeframe"]
        path = Path(__file__).parent.parent / "data" / "processed" / f"{ysym}_{tf}.parquet"
        row = {"symbol": ysym, "timeframe": tf, "strategy": ov["strategy"]}
        if not path.exists():
            out.append({**row, "state": "missing",
                        "detail": "no processed data file for a live-traded instrument"})
            continue
        try:
            import pandas as _pd
            last = _ft.bar_timestamp(_pd.read_parquet(path, columns=["timestamp"]))
            # Asset-class aware: a blanket 3-bar rule would flag every equity,
            # forex, index and commodity instrument as stale EVERY weekend,
            # and an alarm that fires 104 days a year is one nobody reads by
            # the time it matters. Shared with the signal path so the endpoint
            # that reports staleness and the one that refuses to act on it
            # cannot disagree.
            v = _heartbeat.data_staleness_verdict(ysym, tf, last)
            out.append({**row, "last_bar": last.isoformat(), **v})
        except Exception as e:  # noqa: BLE001
            out.append({**row, "state": "unknown", "detail": f"could not read: {e}"})
    return out


@app.get("/health")
def health():
    """System health check.

    `status` is `degraded` whenever any expected scheduled job is missing,
    stale or failing, or any live-traded instrument's data has gone stale. It
    is `healthy` only when nothing is wrong -- a health endpoint that cannot
    report a problem is decoration, which is what this one was.
    """
    from project_titan_x.core import heartbeat

    jobs = heartbeat.check(_EXPECTED_JOBS)
    feeds = _data_staleness()
    status = heartbeat.overall_state(jobs)
    if any(f["state"] in ("stale", "missing") for f in feeds):
        status = "degraded"

    problems = [f"job {j.name}: {j.state} -- {j.detail}" for j in jobs if not j.healthy]
    problems += [f"data {f['symbol']} {f['timeframe']}: {f['state']} -- {f['detail']}"
                 for f in feeds if f["state"] in ("stale", "missing")]

    return {
        "status": status,
        "problems": problems,
        "scheduled_jobs": [asdict_status(j) for j in jobs],
        "data_freshness": feeds,
        "engines": get_registry().health_check_all(),
    }


def asdict_status(s) -> dict:
    return {
        "name": s.name, "state": s.state, "detail": s.detail,
        "seconds_since_success": (round(s.seconds_since_success, 1)
                                  if s.seconds_since_success is not None else None),
        "expected_interval_seconds": s.expected_interval_seconds,
        "consecutive_failures": s.consecutive_failures,
    }


@app.get("/api/v1/engines")
def list_engines():
    """List all registered engines."""
    return get_registry().list_engines()


@app.get("/api/v1/brain/health")
def brain_health_snapshot():
    """Titan Brain (E00) platform-wide health: per-engine health, active
    scheduled tasks, and recent event-bus history."""
    brain = get_registry().get("e00_titan_brain")
    if not brain:
        raise HTTPException(500, "Titan Brain not available")
    result = brain.health_snapshot()
    return result.data


@app.post("/api/v1/brain/workflows/{workflow_name}/run")
def brain_run_workflow(workflow_name: str, symbol: str = Query(...), timeframe: str = Query("1d")):
    """Run a named orchestrated workflow (currently: signal_generation) end
    to end, returning a full per-step audit trail."""
    brain = get_registry().get("e00_titan_brain")
    if not brain:
        raise HTTPException(500, "Titan Brain not available")
    result = brain.run_workflow(workflow_name, symbol=symbol, timeframe=timeframe)
    if result.data is None:
        raise HTTPException(400, result.message)
    workflow_result = result.data
    return {
        "message": result.message,
        **workflow_result.to_dict(),
        "signal": workflow_result.final_data["signal"].to_dict() if workflow_result.final_data and workflow_result.final_data.get("signal") else None,
    }


@app.get("/api/v1/brain/workflows")
def brain_list_workflows():
    brain = get_registry().get("e00_titan_brain")
    if not brain:
        raise HTTPException(500, "Titan Brain not available")
    return {"workflows": brain.list_workflows()}


@app.get("/api/v1/brain/events")
def brain_recent_events(event_type: str | None = None, limit: int = Query(50, ge=1, le=500)):
    brain = get_registry().get("e00_titan_brain")
    if not brain:
        raise HTTPException(500, "Titan Brain not available")
    events = brain.event_bus.history(event_type=event_type, limit=limit)
    return [e.to_dict() for e in events]


@app.get("/api/v1/assets")
def get_supported_assets():
    """List supported assets (forex, crypto, commodities, indices — no equities)."""
    return [
        {
            "symbol": a.symbol,
            "name": a.name,
            "class": a.asset_class.value,
            "yahoo_symbol": a.yahoo_symbol,
            "min_lot_note": a.min_lot_note,
        }
        for a in list_assets()
    ]


@app.get("/api/v1/fx-rate")
def fx_rate(pair: str = Query(..., description="A supported forex pair, e.g. USDINR")):
    """Latest real close for a supported forex pair -- used client-side by
    the dashboard's position-sizing math when the chosen capital currency
    differs from an instrument's quote currency (e.g. capital entered in
    INR, sizing a USD-quoted commodity)."""
    df, asset = _prepare_ohlcv(pair, "1d", years=1)
    return {
        "pair": asset.symbol if asset else pair,
        "rate": float(df["close"].iloc[-1]),
        "as_of": str(df["timestamp"].iloc[-1]),
    }


@app.get("/api/v1/market-data/closes")
def recent_closes(
    symbol: str = Query(..., description="Supported asset symbol, e.g. GOLD"),
    timeframe: str = Query("1d"),
    limit: int = Query(60, ge=5, le=500),
):
    """Last `limit` closing prices for a supported asset -- lightweight,
    read-only, used for the dashboard's sparkline. Not a new analysis
    engine, just a thin slice of the same OHLCV _prepare_ohlcv already
    fetches for every other endpoint."""
    df, asset = _prepare_ohlcv(symbol, timeframe)
    tail = df.tail(limit)
    return {
        "symbol": asset.symbol if asset else symbol,
        "timeframe": timeframe,
        "closes": [float(c) for c in tail["close"]],
        "timestamps": [str(t) for t in tail["timestamp"]],
    }


@app.post("/api/v1/market-data/fetch")
def fetch_market_data(req: FetchDataRequest):
    """Fetch OHLCV data for a supported asset."""
    df, asset = _prepare_ohlcv(req.symbol, req.timeframe, req.years)
    return {
        "symbol": asset.symbol if asset else req.symbol,
        "timeframe": req.timeframe,
        "rows": len(df),
        "latest": {
            "timestamp": str(df["timestamp"].iloc[-1]),
            "close": float(df["close"].iloc[-1]),
        },
    }


@app.get("/api/v1/market-data/funding-rate")
def funding_rate(symbol: str = Query(..., description="BTCUSD or ETHUSD -- funding rate only applies to crypto perpetual futures")):
    """Current perpetual-futures funding rate via Binance's public API (no key needed)."""
    engine = get_registry().get("e02_market_data")
    if not engine:
        raise HTTPException(500, "Market Data Engine not available")
    result = engine.fetch_funding_rate(symbol)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"symbol": symbol, "available": result.data is not None, "data": result.data, "message": result.message}


@app.get("/api/v1/market-data/open-interest")
def open_interest(symbol: str = Query(..., description="BTCUSD or ETHUSD -- open interest only applies to crypto perpetual futures")):
    """Current perpetual-futures open interest via Binance's public API (no key needed)."""
    engine = get_registry().get("e02_market_data")
    if not engine:
        raise HTTPException(500, "Market Data Engine not available")
    result = engine.fetch_open_interest(symbol)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"symbol": symbol, "available": result.data is not None, "data": result.data, "message": result.message}


@app.get("/api/v1/market-data/cot-report")
def cot_report(
    symbol: str = Query(..., description="A supported asset with a US-listed futures contract (EURUSD, GBPUSD, USDJPY, GOLD, SILVER, CRUDE, BTCUSD, ETHUSD)"),
    limit: int = Query(52, ge=1, le=260, description="Number of most recent weekly reports"),
):
    """Weekly CFTC Commitment of Traders report (hedger vs. speculator
    positioning) via CFTC's free public Socrata API. USDINR/NIFTY50/
    BANKNIFTY have no US futures contract, so no CFTC data exists for them."""
    engine = get_registry().get("e02_market_data")
    if not engine:
        raise HTTPException(500, "Market Data Engine not available")
    result = engine.fetch_cot_report(symbol, limit=limit)
    if not result.success:
        raise HTTPException(400, result.message)
    if result.data is None:
        return {"symbol": symbol, "available": False, "message": result.message}
    df = result.data
    return {
        "symbol": symbol,
        "available": True,
        "market": result.metadata.get("market"),
        "reports": [
            {
                "report_date": row["report_date"].isoformat(),
                "open_interest": row.get("open_interest_all"),
                "noncommercial_long": row.get("noncomm_positions_long_all"),
                "noncommercial_short": row.get("noncomm_positions_short_all"),
                "commercial_long": row.get("comm_positions_long_all"),
                "commercial_short": row.get("comm_positions_short_all"),
            }
            for _, row in df.iterrows()
        ],
    }


@app.get("/api/v1/market-data/fear-greed")
def fear_greed_index(limit: int = Query(30, ge=1, le=365)):
    """Crypto Fear & Greed Index via alternative.me's free public API -- market-wide, not asset-specific."""
    engine = get_registry().get("e02_market_data")
    if not engine:
        raise HTTPException(500, "Market Data Engine not available")
    result = engine.fetch_fear_greed_index(limit=limit)
    if not result.success:
        raise HTTPException(400, result.message)
    df = result.data
    return {
        "latest_value": result.metadata.get("latest_value"),
        "latest_classification": result.metadata.get("latest_classification"),
        "history": [
            {"timestamp": row["timestamp"].isoformat(), "value": int(row["value"]), "classification": row["classification"]}
            for _, row in df.iterrows()
        ],
    }


@app.get("/api/v1/market-data/catalog")
def market_data_catalog():
    """Latest catalog entry for every dataset e02_market_data has fetched --
    symbol, timeframe, source, rows, date range, quality score, checksum, version."""
    engine = get_registry().get("e02_market_data")
    if not engine:
        raise HTTPException(500, "Market Data Engine not available")
    result = engine.get_catalog_summary()
    return {"datasets": result.data}


@app.get("/api/v1/market-data/audit-log")
def market_data_audit_log(limit: int = Query(100, ge=1, le=1000)):
    """Most recent fetch events across every dataset, newest first."""
    engine = get_registry().get("e02_market_data")
    if not engine:
        raise HTTPException(500, "Market Data Engine not available")
    result = engine.get_audit_log(limit=limit)
    return {"entries": result.data}


@app.get("/api/v1/macro/analyze")
def analyze_macro():
    """Run macro intelligence analysis."""
    engine = get_registry().get("e04_macro")
    if not engine:
        raise HTTPException(500, "Macro Engine not available")
    result = engine.analyze()
    if not result.success:
        raise HTTPException(400, result.message)
    s = result.data
    return {
        "risk_on_off_score": s.risk_on_off_score,
        "regime_label": s.regime_label,
        "liquidity_signal": s.liquidity_signal,
        "currency_strength": s.currency_strength,
        "indicators": s.indicators,
        "notes": s.notes,
        "timestamp": s.timestamp.isoformat(),
    }


@app.get("/api/v1/news/headlines")
def news_headlines(
    limit_per_feed: int = Query(10, gt=0, le=50),
    sources: str = Query(None, description="Comma-separated subset of feed names, e.g. cnbc_markets,marketwatch"),
):
    """Fetch latest headlines from configured financial RSS feeds (no API key required)."""
    engine = get_registry().get("e03_news")
    if not engine:
        raise HTTPException(500, "News Intelligence Engine not available")
    source_list = [s.strip() for s in sources.split(",")] if sources else None
    result = engine.fetch_headlines(limit_per_feed=limit_per_feed, sources=source_list)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"count": len(result.data), "items": [i.to_dict() for i in result.data]}


@app.get("/api/v1/news/extract")
def news_extract_article(url: str = Query(..., description="Article URL, typically from /news/headlines")):
    """Extract full article text from a URL via newspaper3k."""
    engine = get_registry().get("e03_news")
    if not engine:
        raise HTTPException(500, "News Intelligence Engine not available")
    result = engine.extract_article(url)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"text": result.data, **result.metadata}


@app.post("/api/v1/sentiment/analyze")
def sentiment_analyze(req: SentimentRequest):
    """Score sentiment for a single piece of text (FinBERT if available, else VADER+TextBlob ensemble)."""
    engine = get_registry().get("e09_sentiment")
    if not engine:
        raise HTTPException(500, "Sentiment Intelligence Engine not available")
    result = engine.analyze_text(req.text)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data.to_dict()


@app.post("/api/v1/sentiment/analyze-batch")
def sentiment_analyze_batch(req: SentimentBatchRequest):
    """Score sentiment for multiple texts and return an aggregate read."""
    engine = get_registry().get("e09_sentiment")
    if not engine:
        raise HTTPException(500, "Sentiment Intelligence Engine not available")
    result = engine.analyze_batch(req.texts)
    if not result.success:
        raise HTTPException(400, result.message)
    data = result.data
    return {
        "results": [r.to_dict() for r in data["results"]],
        "aggregate_score": data["aggregate_score"],
        "aggregate_label": data["aggregate_label"],
        "n": data["n"],
    }


# positive/negative/neutral (E09's SentimentResult.label, unchanged --
# other callers of E09 already depend on that exact vocabulary) mapped to
# the bullish/bearish/neutral vocabulary docs/UPGRADE_BRIEF.md Phase 11
# specifically asks for on a per-news-item basis. Purely a rename at this
# call site, not a change to E09 itself.
_SENTIMENT_TO_DIRECTIONAL_LABEL = {"positive": "bullish", "negative": "bearish", "neutral": "neutral"}


@app.get("/api/v1/news/sentiment")
def news_sentiment(
    limit_per_feed: int = Query(10, gt=0, le=50),
    sources: str = Query(None, description="Comma-separated subset of feed names"),
    as_of: Optional[datetime] = Query(None, description="Lookahead-safety cut: drop items published after this time"),
):
    """
    Fetch latest headlines, score their sentiment, and run the Phase 11
    enrichment pipeline (entity extraction, event-type classification,
    market-impact scoring, duplicate-news detection) -- E03 News
    Intelligence feeding E09 Sentiment Intelligence feeding this route's
    own deterministic enrichment stages. New (non-duplicate) items are
    persisted to news_events for later querying; already-seen items
    (matched by a normalized-title content hash) are still returned but
    flagged is_new=False and not re-inserted.
    """
    news_engine = get_registry().get("e03_news")
    sentiment_engine = get_registry().get("e09_sentiment")
    if not news_engine or not sentiment_engine:
        raise HTTPException(500, "News or Sentiment Intelligence Engine not available")

    source_list = [s.strip() for s in sources.split(",")] if sources else None
    news_result = news_engine.fetch_headlines(limit_per_feed=limit_per_feed, sources=source_list, as_of=as_of)
    if not news_result.success:
        raise HTTPException(400, news_result.message)

    items = news_result.data
    if not items:
        return {"count": 0, "items": [], "aggregate_score": 0.0, "aggregate_label": "neutral"}

    sentiment_result = sentiment_engine.analyze_batch([i.title for i in items])
    scored = sentiment_result.data["results"] if sentiment_result.success else []

    # Enrichment (entity extraction, event classification, market impact)
    # is pure computation -- runs regardless of DB availability, same
    # "live feature still works if Postgres is down" discipline as the
    # rest of this route always had.
    enriched = []
    for idx, item in enumerate(items):
        sentiment = scored[idx] if idx < len(scored) else None
        sentiment_score = sentiment.compound_score if sentiment else None
        text_for_entities = f"{item.title} {item.summary}"
        event_type = classify_event_type(text_for_entities)
        enriched.append(
            {
                "item": item,
                "sentiment": sentiment,
                "content_hash": normalized_content_hash(item.title),
                "entities": extract_entities(text_for_entities),
                "event_type": event_type,
                "market_impact_score": market_impact_score(sentiment_score, event_type),
                "directional_label": _SENTIMENT_TO_DIRECTIONAL_LABEL.get(sentiment.label) if sentiment else None,
            }
        )

    # Dedup + persistence is best-effort: a DB outage degrades is_new to
    # None (unknown, never fabricated as True/False) rather than failing
    # this otherwise-live feature -- same non-fatal-DB convention
    # _persist_signal above already established.
    is_new_by_hash: dict[str, bool] = {}
    try:
        with get_db_session() as session:
            seen_hashes_in_batch: set[str] = set()
            for row in enriched:
                content_hash = row["content_hash"]
                already_in_batch = content_hash in seen_hashes_in_batch
                seen_hashes_in_batch.add(content_hash)
                existing = (
                    None
                    if already_in_batch
                    else session.query(NewsEvent).filter(NewsEvent.content_hash == content_hash).first()
                )
                is_new = not already_in_batch and existing is None
                is_new_by_hash[content_hash] = is_new
                if is_new:
                    item = row["item"]
                    sentiment = row["sentiment"]
                    session.add(
                        NewsEvent(
                            title=item.title,
                            link=item.link,
                            source=item.source,
                            summary=item.summary,
                            content_hash=content_hash,
                            source_timestamp=item.published,
                            entities=row["entities"],
                            event_type=row["event_type"],
                            sentiment_label=row["directional_label"],
                            sentiment_score=sentiment.compound_score if sentiment else None,
                            market_impact_score=row["market_impact_score"],
                        )
                    )
    except Exception as e:
        logger.warning("Could not persist/dedup news events (non-fatal, response unaffected): %s", e)
        is_new_by_hash = {}

    combined = [
        {
            **row["item"].to_dict(),
            "sentiment": row["sentiment"].to_dict() if row["sentiment"] else None,
            "directional_label": row["directional_label"],
            "entities": row["entities"],
            "event_type": row["event_type"],
            "market_impact_score": row["market_impact_score"],
            "is_new": is_new_by_hash.get(row["content_hash"]),
        }
        for row in enriched
    ]

    return {
        "count": len(combined),
        "items": combined,
        "aggregate_score": sentiment_result.data["aggregate_score"] if sentiment_result.success else 0.0,
        "aggregate_label": sentiment_result.data["aggregate_label"] if sentiment_result.success else "neutral",
    }


def _structure_event_dict(e) -> dict:
    return {"index": int(e.index), "kind": e.kind.value, "broken_level": float(e.broken_level)}


def _liquidity_sweep_dict(s) -> dict:
    return {
        "index": int(s.index), "direction": s.direction,
        "swept_level": float(s.swept_level), "wick_price": float(s.wick_price),
    }


def _order_block_dict(b) -> dict:
    return {
        "index": int(b.index), "direction": b.direction,
        "open": float(b.open), "high": float(b.high), "low": float(b.low), "close": float(b.close),
        "breaker": bool(b.breaker),
        "mitigated_index": int(b.mitigated_index) if b.mitigated_index is not None else None,
    }


def _fvg_dict(g) -> dict:
    return {
        "index": int(g.index), "direction": g.direction,
        "gap_top": float(g.gap_top), "gap_bottom": float(g.gap_bottom), "filled": bool(g.filled),
    }


def _volume_profile_dict(v) -> Optional[dict]:
    if v is None:
        return None
    return {
        "poc_price": float(v.poc_price),
        "value_area_high": float(v.value_area_high),
        "value_area_low": float(v.value_area_low),
        "value_area_volume_pct": float(v.value_area_volume_pct),
        "high_volume_nodes": [float(x) for x in v.high_volume_nodes],
        "low_volume_nodes": [float(x) for x in v.low_volume_nodes],
    }


def _trading_range_dict(r) -> Optional[dict]:
    if r is None:
        return None
    return {
        "support": float(r.support), "resistance": float(r.resistance),
        "start_index": int(r.start_index), "end_index": int(r.end_index),
    }


def _wyckoff_event_dict(e) -> dict:
    return {"index": int(e.index), "kind": e.kind, "level": float(e.level), "wick_price": float(e.wick_price)}


def _harmonic_pattern_dict(p) -> dict:
    return {
        "name": p.name, "direction": p.direction,
        "x_index": int(p.x_index), "a_index": int(p.a_index), "b_index": int(p.b_index),
        "c_index": int(p.c_index), "d_index": int(p.d_index),
        "x_price": float(p.x_price), "a_price": float(p.a_price), "b_price": float(p.b_price),
        "c_price": float(p.c_price), "d_price": float(p.d_price),
        "ab_xa_ratio": float(p.ab_xa_ratio), "bc_ab_ratio": float(p.bc_ab_ratio),
        "cd_bc_ratio": float(p.cd_bc_ratio), "ad_xa_ratio": float(p.ad_xa_ratio),
    }


def _rsi_divergence_dict(d) -> dict:
    return {
        "first_index": int(d.first_index), "second_index": int(d.second_index), "kind": d.kind.value,
        "price_first": float(d.price_first), "price_second": float(d.price_second),
        "rsi_first": float(d.rsi_first), "rsi_second": float(d.rsi_second),
    }


def _crt_setup_dict(s) -> dict:
    return {
        "signal_index": int(s.signal_index), "range_bar_index": int(s.range_bar_index),
        "direction": s.direction,
        "range_high": float(s.range_high), "range_low": float(s.range_low), "range_atr": float(s.range_atr),
        "body_ratio": float(s.body_ratio), "retrace": float(s.retrace),
        "entry": float(s.entry), "stop": float(s.stop),
        "tp1": float(s.tp1), "tp2": float(s.tp2), "tp3": float(s.tp3),
        "risk_reward": float(s.risk_reward), "quality": s.quality,
    }


def _cisd_setup_dict(s) -> dict:
    return {
        "signal_index": int(s.signal_index), "break_bar_index": int(s.break_bar_index),
        "original_fvg_index": int(s.original_fvg_index), "direction": s.direction,
        "entry_zone_low": float(s.entry_zone_low), "entry_zone_high": float(s.entry_zone_high),
        "stop": float(s.stop) if s.stop is not None else None,
    }


def _chart_pattern_dict(p) -> dict:
    return {
        "kind": p.kind.value, "direction": p.direction,
        "point_indices": [int(i) for i in p.point_indices],
        "point_prices": [float(x) for x in p.point_prices],
        "breakout_level": float(p.breakout_level), "target_price": float(p.target_price),
        "confirmed": bool(p.confirmed),
        "confirmed_index": int(p.confirmed_index) if p.confirmed_index is not None else None,
    }


@app.get("/api/v1/technical/analyze")
def analyze_technical(
    symbol: str = Query(..., description="Asset symbol"),
    timeframe: str = Query("1d"),
):
    """Run technical analysis on a supported asset."""
    df, asset = _prepare_ohlcv(symbol, timeframe)
    registry = get_registry()
    ta_engine = registry.get("e07_technical")
    if not ta_engine:
        raise HTTPException(500, "Technical Engine not available")

    result = ta_engine.analyze(df, symbol=asset.symbol if asset else symbol, timeframe=timeframe)
    if not result.success:
        raise HTTPException(400, result.message)

    snapshot = result.data["snapshot"]
    # Market structure / ICT-SMC fields added 2026-09-13 (docs/UPGRADE_
    # BRIEF.md Phase 12): the engine already computes all of this (see
    # TechnicalSnapshot's own docstring -- "empty list/None otherwise,
    # never fabricated"), it just wasn't serialized out by this route
    # before now. No new computation, only exposing what already exists.
    try:
        from project_titan_x.engines.e07_technical.killzones import active_killzones_at
        active_zones = [z.value for z in active_killzones_at(datetime.now(timezone.utc))]
    except Exception as e:
        logger.warning("Could not compute active killzones (non-fatal): %s", e)
        active_zones = []
    return {
        "symbol": snapshot.symbol,
        "timeframe": snapshot.timeframe,
        "trend": snapshot.trend.value,
        "structure": snapshot.structure,
        "support_levels": snapshot.support_levels,
        "resistance_levels": snapshot.resistance_levels,
        "indicators": snapshot.indicators,
        "signals": snapshot.signals,
        "score": snapshot.score,
        "structure_events": [_structure_event_dict(e) for e in snapshot.structure_events],
        "liquidity_sweeps": [_liquidity_sweep_dict(s) for s in snapshot.liquidity_sweeps],
        "order_blocks": [_order_block_dict(b) for b in snapshot.order_blocks],
        "fair_value_gaps": [_fvg_dict(g) for g in snapshot.fair_value_gaps],
        "volume_profile": _volume_profile_dict(snapshot.volume_profile),
        "wyckoff_range": _trading_range_dict(snapshot.wyckoff_range),
        "wyckoff_phase": snapshot.wyckoff_phase,
        "wyckoff_springs": [_wyckoff_event_dict(e) for e in snapshot.wyckoff_springs],
        "wyckoff_upthrusts": [_wyckoff_event_dict(e) for e in snapshot.wyckoff_upthrusts],
        "harmonic_patterns": [_harmonic_pattern_dict(p) for p in snapshot.harmonic_patterns],
        "rsi_divergences": [_rsi_divergence_dict(d) for d in snapshot.rsi_divergences],
        "active_killzones": active_zones,
        # NOT YET ABLATED (docs/UPGRADE_ROADMAP.md P1 item 2) -- exposed
        # for research/inspection only, never fed into `score` above.
        "crt_setups": [_crt_setup_dict(s) for s in snapshot.crt_setups],
        # NOT YET ABLATED (docs/UPGRADE_ROADMAP.md P2 item 6) -- same.
        "cisd_setups": [_cisd_setup_dict(s) for s in snapshot.cisd_setups],
        # NOT YET ABLATED (chart_patterns.py, added 2026-09-13) -- same
        # inspection-only convention as crt_setups/cisd_setups above.
        "chart_patterns": [_chart_pattern_dict(p) for p in snapshot.chart_patterns],
    }


@app.get("/api/v1/microstructure/analyze")
def analyze_microstructure(
    symbol: str = Query(..., description="Asset symbol"),
    timeframe: str = Query("1d"),
):
    """
    Estimated execution-risk read (Engine 11) for a supported asset: effective
    spread (Corwin-Schultz estimator from OHLCV -- no order book/Level 2 feed
    exists for free, so this estimates rather than fabricates quote data),
    relative volume, and FX session liquidity (forex only). Informational --
    does not change any other engine's confidence or direction.
    """
    df, asset = _prepare_ohlcv(symbol, timeframe)
    engine = get_registry().get("e11_microstructure")
    if not engine:
        raise HTTPException(500, "Market Microstructure Engine not available")

    asset_class = asset.asset_class.value if asset else ""
    result = engine.analyze(df, symbol=asset.symbol if asset else symbol, timeframe=timeframe, asset_class=asset_class)
    if not result.success:
        raise HTTPException(400, result.message)

    snapshot = result.data
    return {
        "symbol": snapshot.symbol,
        "timeframe": snapshot.timeframe,
        "estimated_spread_pct": snapshot.estimated_spread_pct,
        "estimated_spread_percentile": snapshot.estimated_spread_percentile,
        "relative_volume": snapshot.relative_volume,
        "volume_label": snapshot.volume_label,
        "amihud_illiquidity_x1e6": snapshot.amihud_illiquidity_x1e6,
        "amihud_illiquidity_percentile": snapshot.amihud_illiquidity_percentile,
        "session": snapshot.session,
        "execution_risk": snapshot.execution_risk,
        "notes": snapshot.notes,
        "method": snapshot.method,
    }


@app.get("/api/v1/fundamental/analyze")
def analyze_fundamental():
    """
    Macro-fundamental value drivers for this platform's actual asset
    universe: US Treasury yield curve shape, real-yield proxy (gold/silver
    driver), WTI-Brent spread (crude oil driver). Does NOT cover company
    fundamentals (no stocks in the watchlist), crypto on-chain data, or
    foreign sovereign yields -- see coverage_notes in the response.
    """
    engine = get_registry().get("e06_fundamental")
    if not engine:
        raise HTTPException(500, "Fundamental Analysis Engine not available")
    result = engine.analyze()
    if not result.success:
        raise HTTPException(400, result.message)
    s = result.data
    return {
        "timestamp": s.timestamp.isoformat(),
        "yield_curve": s.yield_curve.__dict__ if s.yield_curve else None,
        "real_yield": s.real_yield.__dict__ if s.real_yield else None,
        "crude_oil": s.crude_oil.__dict__ if s.crude_oil else None,
        "coverage_notes": s.coverage_notes,
    }


@app.get("/api/v1/economic-calendar/upcoming")
def upcoming_economic_events(
    lookahead_days: int = Query(14, ge=1, le=90),
    symbol: Optional[str] = Query(None, description="Supported asset symbol (e.g. EURUSD, GOLD, BTCUSD) for a per-asset expected_volatility_multiplier instead of the cross-asset average"),
):
    """
    Upcoming high-impact recurring macro releases. Only covers event types
    with a deterministic, published release rule (currently: US Non-Farm
    Payrolls, first Friday of the month) -- no paid calendar API is used or
    required. expected_volatility_multiplier is calibrated per asset from
    real historical price reactions (see
    scripts/training/train_e05_economic_calendar.py) -- pass `symbol` to
    get that specific asset's own multiplier (e.g. GOLD reacts differently
    than EURUSD); omitting it returns the cross-asset average. Falls back
    to 1.0 ("no calibration yet") for any event type not yet trained at all.
    """
    engine = get_registry().get("e05_economic_calendar")
    if not engine:
        raise HTTPException(500, "Economic Calendar Intelligence Engine not available")
    result = engine.analyze(lookahead_days=lookahead_days, symbol=symbol)
    if not result.success:
        raise HTTPException(400, result.message)
    snapshot = result.data
    return {
        "as_of": snapshot.as_of.isoformat(),
        "high_impact_within_24h": snapshot.high_impact_within_24h,
        "high_impact_within_1h": snapshot.high_impact_within_1h,
        "upcoming_events": [
            {
                "name": e.name,
                "date": e.date.isoformat(),
                "impact": e.impact.value,
                "date_confirmed": e.date_confirmed,
                "expected_volatility_multiplier": e.expected_volatility_multiplier,
                "notes": e.notes,
            }
            for e in snapshot.upcoming_events
        ],
    }


@app.get("/api/v1/cross-asset/snapshot")
def cross_asset_snapshot():
    """
    Current read on 10 cross-asset relationships: the master prompt's 6
    named pairs (DXY/Gold, Bonds/Stocks, Oil/CAD, Yields/USD, VIX/Risk
    Assets, Copper/Global Growth) plus 4 forex cross-asset pairs (EUR/USD
    vs GBP/USD, USD/JPY vs Yields, USD/JPY vs VIX, AUD/USD vs Copper) --
    current rolling correlation vs. each pair's long-run calibrated
    baseline (see scripts/training/train_e10_cross_asset.py), plus a
    simple dependency graph. Flags pairs whose relationship is weakening,
    breaking down, or inverting relative to its baseline; reports
    regime="uncalibrated" for any pair if the training script hasn't been
    run yet.
    """
    engine = get_registry().get("e10_cross_asset")
    if not engine:
        raise HTTPException(500, "Cross-Asset Intelligence Engine not available")
    result = engine.analyze()
    if not result.success:
        raise HTTPException(400, result.message)
    snapshot = result.data
    return {
        "timestamp": snapshot.timestamp.isoformat(),
        "pairs": [
            {
                "name": p.name,
                "label_a": p.label_a,
                "label_b": p.label_b,
                "current_correlation": p.current_correlation,
                "full_period_correlation": p.full_period_correlation,
                "baseline_correlation": p.baseline_correlation,
                "delta_vs_baseline": p.delta_vs_baseline,
                "regime": p.regime,
            }
            for p in snapshot.pairs
        ],
        "dependency_graph": snapshot.dependency_graph,
        "flagged_pairs": snapshot.flagged_pairs,
        "notes": snapshot.notes,
    }


@app.get("/api/v1/derivatives/snapshot")
def derivatives_snapshot(symbol: str = Query("BTCUSD", description="BTCUSD or ETHUSD -- the only assets with real options data behind this engine")):
    """
    Options-market read for BTCUSD/ETHUSD via Deribit's free public API:
    put/call ratio (open interest + volume), implied-volatility term
    structure, a 10%-OTM put-vs-call skew proxy, real ATM greeks
    (delta/gamma/theta/vega/rho), and today's 30-day realized volatility
    classified against a real historical percentile baseline (see
    scripts/training/train_e13_derivatives.py) -- plus the plain IV-minus-RV
    spread (volatility risk premium), un-classified since no historical
    implied-vol series exists to say whether the spread itself is rich or
    cheap. No free options data source exists for this platform's
    forex/commodity/index assets (CME/OCC feeds are paid) -- passing any
    other supported symbol returns an honest capability gap instead of
    fabricated data.
    """
    engine = get_registry().get("e13_derivatives")
    if not engine:
        raise HTTPException(500, "Derivatives Intelligence Engine not available")
    result = engine.analyze(symbol=symbol)
    if not result.success:
        raise HTTPException(400, result.message)
    if result.data is None:
        return {"symbol": symbol, "available": False, "message": result.message}
    s = result.data
    return {
        "symbol": symbol,
        "available": True,
        "timestamp": s.timestamp.isoformat(),
        "currency": s.currency,
        "spot_price": s.spot_price,
        "put_call_ratio_oi": s.put_call_ratio_oi,
        "put_call_ratio_volume": s.put_call_ratio_volume,
        "nearest_expiry": s.nearest_expiry.isoformat() if s.nearest_expiry else None,
        "nearest_expiry_atm_iv": s.nearest_expiry_atm_iv,
        "term_structure": [
            {
                "expiry": pt.expiry.isoformat(),
                "days_to_expiry": pt.days_to_expiry,
                "atm_strike": pt.atm_strike,
                "atm_iv": pt.atm_iv,
            }
            for pt in s.term_structure
        ],
        "skew_proxy": s.skew_proxy,
        "skew_label": s.skew_label,
        "atm_greeks": s.atm_greeks,
        "realized_vol_30d": s.realized_vol_30d,
        "realized_vol_regime": s.realized_vol_regime,
        "iv_minus_rv": s.iv_minus_rv,
        "notes": s.notes,
    }


def _oi_changes_and_persist(symbol: str, expiry, rows) -> dict:
    """docs/UPGRADE_ROADMAP.md P1 item 5: look up the most recent PRIOR
    persisted OI batch for this (symbol, expiry) via MAX(captured_at),
    diff this read's OI against it per (strike, option_type), then
    persist this read as the new batch. Best-effort/non-fatal like
    Phase 11's news_sentiment persistence -- a DB outage degrades every
    oi_change to None (unknown, never fabricated 0) rather than breaking
    the live option-chain read. Returns {(strike, "CE"|"PE"): change or None}."""
    changes: dict = {}
    try:
        with get_db_session() as session:
            latest_captured_at = session.query(func.max(OptionChainOISnapshot.captured_at)).filter(
                OptionChainOISnapshot.symbol == symbol, OptionChainOISnapshot.expiry == expiry,
            ).scalar()
            prior_oi = {}
            if latest_captured_at is not None:
                prior_rows = session.query(OptionChainOISnapshot).filter(
                    OptionChainOISnapshot.symbol == symbol, OptionChainOISnapshot.expiry == expiry,
                    OptionChainOISnapshot.captured_at == latest_captured_at,
                ).all()
                prior_oi = {(float(p.strike), p.option_type): float(p.oi) for p in prior_rows}

            # Windows' wall clock has ~15.6ms granularity, so two batches
            # written inside the same tick get the IDENTICAL timestamp --
            # measured directly: six consecutive datetime.now() calls returned
            # one distinct value. That collides with the unique constraint on
            # (symbol, expiry, strike, option_type, captured_at), and the whole
            # persist is swallowed by the non-fatal handler below, so the batch
            # silently never lands. Stepping past the previous batch keeps
            # captured_at strictly increasing, which is also what the MAX()
            # lookup above depends on to diff against the RIGHT prior batch.
            batch_time = datetime.now(timezone.utc)
            if latest_captured_at is not None:
                prev = latest_captured_at
                if prev.tzinfo is None:
                    prev = prev.replace(tzinfo=timezone.utc)
                if batch_time <= prev:
                    batch_time = prev + timedelta(microseconds=1)
            for r in rows:
                for leg, oi in (("CE", r.ce_oi), ("PE", r.pe_oi)):
                    if oi is None:
                        continue
                    key = (r.strike, leg)
                    prior = prior_oi.get(key)
                    changes[key] = (float(oi) - prior) if prior is not None else None
                    session.add(OptionChainOISnapshot(
                        symbol=symbol, expiry=expiry, strike=r.strike, option_type=leg,
                        oi=oi, captured_at=batch_time,
                    ))
    except Exception as e:
        logger.warning("Could not compute/persist option chain OI changes (non-fatal): %s", e)
        return {}
    return changes


@app.get("/api/v1/derivatives/india-option-chain")
def india_option_chain(
    symbol: str = Query("NIFTY50", description="NIFTY50 or BANKNIFTY -- the only Indian indices with real option-chain support"),
    expiry: Optional[str] = Query(None, description="YYYY-MM-DD; omit to use the nearest real, live-discovered expiry"),
):
    """
    Real NIFTY50/BANKNIFTY option chain via Zerodha Kite Connect -- added
    2026-08-21, closing the "no free options-chain data source for...
    indices" gap the crypto-focused /derivatives/snapshot route above has
    always been honest about. Per-strike CE/PE last price, open interest,
    and Black-Scholes implied volatility + Greeks (delta/gamma/theta/vega/
    rho) inverted from that real traded price -- not a broker-published
    IV like Deribit's mark_iv, since Kite doesn't publish one.

    Requires a paid Zerodha Kite Connect developer subscription
    (developers.kite.trade) and a daily-refreshed access token configured
    via kite_api_key/kite_access_token -- returns an honest
    available=false gap (not fabricated data) if unconfigured, same
    convention as every other optional data source on this platform.

    oi_change (added 2026-09-13, docs/UPGRADE_ROADMAP.md P1 item 5): each
    leg's OI change since the most recently persisted prior read of this
    same symbol+expiry. None on the very first read ever for a given
    symbol+expiry (no prior to diff against -- honest gap, never a
    fabricated 0) or if OI itself is unavailable for that leg.
    """
    engine = get_registry().get("e13_derivatives")
    if not engine:
        raise HTTPException(500, "Derivatives Intelligence Engine not available")
    result = engine.analyze_index_option_chain(symbol=symbol, expiry=expiry)
    if not result.success:
        raise HTTPException(400, result.message)
    if result.data is None:
        return {"symbol": symbol, "available": False, "message": result.message}
    s = result.data
    oi_changes = _oi_changes_and_persist(s.underlying_symbol, s.expiry, s.rows)
    return {
        "symbol": s.underlying_symbol,
        "available": True,
        "timestamp": s.timestamp.isoformat(),
        "expiry": s.expiry.isoformat(),
        "spot_price": s.spot_price,
        "atm_strike": s.atm_strike,
        "pcr_oi": s.pcr_oi,
        "pcr_volume": s.pcr_volume,
        "max_pain": s.max_pain,
        "rows": [
            {
                "strike": r.strike,
                "ce": {"ltp": r.ce_ltp, "oi": r.ce_oi, "oi_change": oi_changes.get((r.strike, "CE")),
                       "volume": r.ce_volume, "iv": r.ce_iv,
                       "greeks": r.ce_greeks, "moneyness": r.ce_moneyness},
                "pe": {"ltp": r.pe_ltp, "oi": r.pe_oi, "oi_change": oi_changes.get((r.strike, "PE")),
                       "volume": r.pe_volume, "iv": r.pe_iv,
                       "greeks": r.pe_greeks, "moneyness": r.pe_moneyness},
            }
            for r in s.rows
        ],
        "notes": s.notes,
    }


@app.get("/api/v1/fixed-income/snapshot")
def fixed_income_snapshot():
    """
    Fixed income read: empirical duration/convexity for government bond
    ETFs (SHY/IEF/TLT/TIP -- regressed against real 10Y Treasury yield
    changes, see scripts/training/train_e14_fixed_income.py), live
    investment-grade and high-yield credit spreads (LQD/HYG yield minus a
    Treasury benchmark, classified against static documented market
    conventions), and a credit-stress regime read (HYG-vs-Treasury rolling
    correlation vs. its real historical baseline). Does not repeat
    e06_fundamental's Treasury yield-curve shape or TIPS real-yield read --
    see that engine for those.
    """
    engine = get_registry().get("e14_fixed_income")
    if not engine:
        raise HTTPException(500, "Fixed Income Intelligence Engine not available")
    result = engine.analyze()
    if not result.success:
        raise HTTPException(400, result.message)
    s = result.data
    return {
        "timestamp": s.timestamp.isoformat(),
        "duration_convexity": [
            {
                "ticker": dc.ticker,
                "label": dc.label,
                "empirical_duration": dc.empirical_duration,
                "convexity": dc.convexity,
                "r_squared": dc.r_squared,
            }
            for dc in s.duration_convexity
        ],
        "credit_spread": {
            "ig_spread_pct": s.credit_spread.ig_spread_pct,
            "hy_spread_pct": s.credit_spread.hy_spread_pct,
            "ig_regime": s.credit_spread.ig_regime,
            "hy_regime": s.credit_spread.hy_regime,
        } if s.credit_spread else None,
        "credit_stress": {
            "current_correlation": s.credit_stress.current_correlation,
            "baseline_correlation": s.credit_stress.baseline_correlation,
            "delta_vs_baseline": s.credit_stress.delta_vs_baseline,
            "regime": s.credit_stress.regime,
        } if s.credit_stress else None,
        "notes": s.notes,
    }


@app.get("/api/v1/credit/snapshot")
def credit_snapshot():
    """
    Credit intelligence read: real, live sovereign credit spread (EMB
    emerging-market sovereign bond ETF yield minus a Treasury benchmark),
    market-implied 1-year default probability for corporate IG/HY (reusing
    e14_fixed_income's spread) and sovereign credit (via the standard
    credit-spread-to-hazard-rate approximation, under a documented
    recovery-rate assumption -- 40% corporate, 25% sovereign, standard
    ISDA/CDS-market conventions, not fitted), and a sovereign credit-stress
    regime read (EMB-vs-Treasury rolling correlation vs. its real
    historical baseline). CDS spreads and company-level corporate debt
    analysis are explicitly not covered -- see the response's notes field.
    """
    engine = get_registry().get("e15_credit")
    if not engine:
        raise HTTPException(500, "Credit Intelligence Engine not available")
    result = engine.analyze()
    if not result.success:
        raise HTTPException(400, result.message)
    s = result.data
    return {
        "timestamp": s.timestamp.isoformat(),
        "sovereign_credit": {
            "spread_pct": s.sovereign_credit.spread_pct,
            "regime": s.sovereign_credit.regime,
        } if s.sovereign_credit else None,
        "default_probabilities": [
            {
                "source": dp.source,
                "spread_pct": dp.spread_pct,
                "recovery_rate_assumption": dp.recovery_rate_assumption,
                "implied_hazard_rate_pct": dp.implied_hazard_rate_pct,
                "implied_1yr_default_probability_pct": dp.implied_1yr_default_probability_pct,
                "implied_5yr_default_probability_pct": dp.implied_5yr_default_probability_pct,
            }
            for dp in s.default_probabilities
        ],
        "sovereign_credit_stress": {
            "current_correlation": s.sovereign_credit_stress.current_correlation,
            "baseline_correlation": s.sovereign_credit_stress.baseline_correlation,
            "delta_vs_baseline": s.sovereign_credit_stress.delta_vs_baseline,
            "regime": s.sovereign_credit_stress.regime,
        } if s.sovereign_credit_stress else None,
        "notes": s.notes,
    }


@app.get("/api/v1/commodity/snapshot")
def commodity_snapshot(symbol: str = Query("GOLD", description="GOLD, SILVER, or CRUDE -- the only commodities this engine covers")):
    """
    Commodity intelligence read for GOLD/SILVER/CRUDE: a statistically
    tested seasonality read (one-sample t-test per calendar month on real
    historical monthly returns -- only p<0.05 months are called
    "significant", not every month with a positive average) for the
    CURRENT calendar month, and a commercial (producer/hedger) positioning
    read from CFTC's real COT data, classified against a real historical
    percentile distribution (calibrated from history back to 1986 for
    GOLD). Copper/natural gas/agriculture aren't tradable instruments in
    this platform's watchlist, so passing any other supported symbol
    returns an honest capability gap.
    """
    engine = get_registry().get("e16_commodity")
    if not engine:
        raise HTTPException(500, "Commodity Intelligence Engine not available")
    result = engine.analyze(symbol=symbol)
    if not result.success:
        raise HTTPException(400, result.message)
    if result.data is None:
        return {"symbol": symbol, "available": False, "message": result.message}
    c = result.data.commodities[0]
    return {
        "symbol": c.symbol,
        "available": True,
        "timestamp": result.data.timestamp.isoformat(),
        "seasonality": {
            "month": c.seasonality.month,
            "month_name": c.seasonality.month_name,
            "mean_return_pct": c.seasonality.mean_return_pct,
            "p_value": c.seasonality.p_value,
            "n_years": c.seasonality.n_years,
            "significant": c.seasonality.significant,
            "direction": c.seasonality.direction,
        } if c.seasonality else None,
        "commercial_positioning": {
            "net_positioning_pct": c.commercial_positioning.net_positioning_pct,
            "percentile_rank": c.commercial_positioning.percentile_rank,
            "regime": c.commercial_positioning.regime,
        } if c.commercial_positioning else None,
        "notes": result.data.notes,
    }


@app.get("/api/v1/regime/classify")
def classify_regime(
    symbol: str = Query(...),
    timeframe: str = Query("1d"),
):
    """Classify market regime for an asset."""
    df, asset = _prepare_ohlcv(symbol, timeframe)
    registry = get_registry()

    ta = registry.get("e07_technical").analyze(df, symbol=asset.symbol if asset else symbol, timeframe=timeframe)
    if not ta.success:
        raise HTTPException(400, ta.message)

    macro = registry.get("e04_macro").analyze()
    macro_data = macro.data if macro.success else None

    regime = registry.get("e08_regime").classify(df, ta.data["snapshot"], macro_data)
    if not regime.success:
        raise HTTPException(400, regime.message)

    r = regime.data
    return {
        "primary_regime": r.primary_regime.value,
        "secondary_regime": r.secondary_regime.value if r.secondary_regime else None,
        "confidence": r.confidence,
        "macro_alignment": r.macro_alignment,
        "suitable_strategies": r.suitable_strategies,
        "avoid_strategies": r.avoid_strategies,
        "evidence": r.evidence,
    }


@app.get("/api/v1/signals/generate")
def generate_signal(
    symbol: str = Query(...),
    timeframe: str = Query("1d"),
):
    """Generate a validated trading signal for an asset."""
    df, asset = _prepare_ohlcv(symbol, timeframe)
    registry = get_registry()

    ta = registry.get("e07_technical").analyze(df, symbol=asset.symbol if asset else symbol, timeframe=timeframe)
    if not ta.success:
        raise HTTPException(400, ta.message)

    macro = registry.get("e04_macro").analyze()
    macro_data = macro.data if macro.success else None
    macro_score = macro_data.risk_on_off_score if macro_data else 0.0

    fundamental = registry.get("e06_fundamental").analyze()
    fundamental_data = fundamental.data if fundamental.success else None

    regime = registry.get("e08_regime").classify(df, ta.data["snapshot"], macro_data)
    if not regime.success:
        raise HTTPException(400, regime.message)

    # PHASE 27 ("never generate a trade simply because a subsystem stopped
    # responding"). Until 2026-09-15 this path had NO recency check at all: if
    # the fetch chain fell back to a cached parquet, or the upstream provider
    # started returning a stale frame, this endpoint returned a fully
    # confident signal computed on old bars with nothing to say so. Tolerance
    # is asset-class aware, so a Friday close read on a Sunday is not treated
    # as a fault for a market that was simply closed.
    staleness = None
    try:
        staleness = _heartbeat.data_staleness_verdict(
            asset.yahoo_symbol if asset else symbol, timeframe, _ft_bar_time(df))
    except Exception as e:  # noqa: BLE001 - never fail a good request on the check itself
        logger.warning("Could not assess data staleness for %s %s: %s", symbol, timeframe, e)

    if staleness and staleness["state"] == "stale":
        raise HTTPException(409, (
            f"Refusing to generate a signal for {symbol} {timeframe}: {staleness['detail']}. "
            f"The data feed is behind, so any signal would describe a market that has "
            f"already moved on. Re-fetch, or check /health."
        ))

    sig = registry.get("e51_signals").generate_signal(
        asset.symbol if asset else symbol,
        df,
        ta.data["snapshot"],
        regime.data,
        macro_score,
        macro_snapshot=macro_data,
        fundamental_snapshot=fundamental_data,
        enriched_df=ta.data.get("df"),
    )
    if not sig.success:
        raise HTTPException(400, sig.message)
    if sig.data is None:
        return {"signal": None, "message": sig.message, "metadata": sig.metadata}

    # Committee evaluation
    committee = registry.get("e43_committee").evaluate_signal(
        sig.data,
        macro_regime=macro_data.regime_label if macro_data else "Neutral",
        macro_score=macro_score,
        risk_approved=True,
    )
    decision = committee.data if committee.success else None
    signal_id = _persist_signal(sig.data)

    return {
        "signal": sig.data.to_dict(),
        "signal_id": signal_id,
        "committee": {
            "consensus": decision.consensus if decision else "N/A",
            "cio_recommendation": decision.cio_recommendation if decision else "",
            "risk_veto": decision.risk_veto if decision else False,
            "votes": [
                {"agent": v.agent_name, "vote": v.vote, "reasoning": v.reasoning}
                for v in (decision.votes if decision else [])
            ],
        } if decision else None,
    }


@app.get("/api/v1/signals/validate-edge")
def validate_signal_edge(
    symbol: str = Query(...),
    timeframe: str = Query("1d"),
):
    """
    Backtest E16's own direction rule against real history for one asset --
    the same edge-gate check generate_signal() runs automatically, exposed
    standalone for research (e.g. checking an asset before it ever produces
    a live signal, or auditing why one was vetoed).
    """
    df, asset = _prepare_ohlcv(symbol, timeframe, years=2)
    registry = get_registry()
    signals_engine = registry.get("e51_signals")
    ta_engine = registry.get("e07_technical")
    bt_engine = registry.get("e26_backtesting")
    if not (signals_engine and ta_engine and bt_engine):
        raise HTTPException(500, "Required engines not available")

    result = signals_engine.validate_historical_edge(
        asset.symbol if asset else symbol, df, ta_engine, bt_engine
    )
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data.to_dict()


@app.get("/api/v1/signals/scan")
def scan_signals(
    timeframe: str = Query("1d"),
    symbols: Optional[str] = Query(
        None,
        description=(
            "Optional comma-separated asset symbols to scan (e.g. 'BTCUSD,ETHUSD'). "
            "Omit to scan every supported asset. Lets a caller that only wants one "
            "market pay for that market instead of scanning all 29 and discarding "
            "the rest -- the dashboard's market filter uses this."
        ),
    ),
):
    """Scan all supported assets for trading signals."""
    registry = get_registry()
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    result = registry.get("e51_signals").scan_all_assets(
        registry.get("e02_market_data"),
        registry.get("e07_technical"),
        registry.get("e08_regime"),
        registry.get("e04_macro"),
        timeframe,
        fundamental_engine=registry.get("e06_fundamental"),
        data_quality_engine=registry.get("e40_data_quality"),
        symbols=symbol_list,
    )
    if not result.success:
        raise HTTPException(400, result.message)
    db_ok = _db_reachable() if result.data else False
    signals_out = []
    for s in result.data:
        payload = s.to_dict()
        payload["signal_id"] = _persist_signal(s) if db_ok else None
        signals_out.append(payload)
    meta = result.metadata or {}
    return {
        "count": len(result.data),
        "signals": signals_out,
        # An empty `signals` list is ambiguous on its own -- a quiet market and
        # a scan where every candidate was VETOED look identical. These fields
        # are what tell them apart, and on intraday timeframes the answer is
        # usually the veto: measured 2026-09-22, 15m and 5m returned 0 signals
        # because `edge_not_proven_negative` fired on every asset, i.e. the
        # platform had backtested that exact rule on that exact symbol and
        # found a negative Sharpe.
        "suppressed_count": meta.get("suppressed_count", 0),
        "suppressed_by_reason": meta.get("suppressed_by_reason", {}),
        "suppressed": meta.get("suppressed", []),
        "note": (
            f"{meta.get('suppressed_count', 0)} candidate(s) were suppressed. "
            "`edge_not_proven_negative` means this platform backtested this exact "
            "signal logic on this exact symbol and timeframe and measured a negative "
            "Sharpe -- the signal is withheld deliberately, not missing."
            if meta.get("suppressed_count") else None
        ),
    }


# This project's own style convention, same mapping reports/
# MASTER_BACKTEST_RESULTS.csv's tf_style column uses and the
# strategies_by_style/{INTRADAY,SWING,POSITIONAL} directories follow --
# not invented here.
_TF_STYLE = {
    "1m": "Intraday", "5m": "Intraday", "15m": "Intraday", "30m": "Intraday",
    "1h": "Swing", "4h": "Swing",
    "1d": "Positional", "1wk": "Positional",
}
# Default scan set. Deliberately NOT all 8 supported timeframes: each
# timeframe is a full re-scan of every asset (fetch + E40 + E07 + E08 +
# E04 + E06 + E51 per asset), so "all timeframes" over 29 assets is 232
# complete analyses. These four cover every style once (one Intraday, two
# Swing, one Positional) at roughly half the cost of the full set. Pass
# `timeframes` explicitly to widen it.
_SCAN_ALL_DEFAULT_TFS = "15m,1h,4h,1d"


@app.get("/api/v1/research/forward-test")
def forward_test_status():
    """Out-of-sample evidence accumulated since the forward test began.

    READ-ONLY. Recording happens on the scheduler (see lifespan) or via
    scripts/run_forward_test.py -- never on a GET, because a prediction created
    by whoever happened to open a dashboard would be a biased sample of bars,
    and mixing that into a systematic log would quietly corrupt the win rate it
    reports.

    `verdict` per series is drawn from FORWARD evidence alone. A `consistent`
    verdict means the backtest claim has not yet been contradicted -- it is not
    confirmation, and below the trade floor no verdict is issued at all.
    """
    from project_titan_x.engines.e24_strategy_research import forward_test as _ft

    summary = _ft.summarise()
    live = _ft.validated_overrides()
    summary["tracked_overrides"] = [
        {"symbol": o["yahoo_symbol"], "timeframe": o["timeframe"],
         "strategy": o["strategy"], "claim": o["claim"]}
        for o in live
    ]
    if summary["total_resolved"] == 0:
        summary["headline"] = (
            f"{len(live)} live strategy/strategies are running on HISTORICAL evidence only. "
            f"{summary['total_predictions']} forward prediction(s) recorded, none resolved yet."
        )
    else:
        summary["headline"] = (
            f"{summary['total_resolved']} of {summary['total_predictions']} forward "
            f"prediction(s) resolved since {summary['inception']}."
        )
    return summary


@app.get("/api/v1/signals/scan-high-profile")
def scan_high_profile_setup(
    timeframe: str = Query("5m"),
    stop_model: str = Query("orb_opposite", description="orb_opposite | atr_pct"),
    rvol_min: float = Query(1.0),
    rvol_top_n: int = Query(20),
    as_of: Optional[str] = Query(
        None, description="YYYY-MM-DD session to scan; omit for the latest."),
    tail_bars: int = Query(
        6000,
        description=(
            "Bars read per asset. The scan needs one session plus its lookback "
            "windows, so reading 887k BTC bars to score one day is the difference "
            "between seconds and minutes. 0 reads the whole file."
        ),
    ),
):
    """The published 'stocks in play' ORB setup, in the same signal shape as /signals/scan.

    SEPARATE ROUTE ON PURPOSE. This is not the platform's composite rule with a
    different filter -- it is a different setup, from
    Zarattini/Barbon/Aziz, with its own entry, stop and exit. Folding it into
    /signals/scan would silently change what that endpoint means.

    CONFIDENCE IS CAPPED BY MEASUREMENT. Every score here is bounded by what
    `setups/run_high_profile.py` actually measured for that instrument -- at most
    25 where the measured net expectancy is negative, at most 20 where no
    measurement exists. `expected_value` is the measured net expectancy per
    trade, not a forecast, and it is negative wherever the backtest was.
    """
    import glob as _glob

    import pandas as _pd

    from project_titan_x.setups.high_profile_setup import HighProfileConfig
    from project_titan_x.setups.hp_scanner import load_measured, scan_all

    if stop_model not in ("orb_opposite", "atr_pct"):
        raise HTTPException(400, "stop_model must be orb_opposite or atr_pct")

    data_dir = Path(__file__).resolve().parents[1] / "data" / "processed"
    frames = {}
    for asset in list_assets():
        cand = getattr(asset, "yahoo_symbol", asset.symbol) or asset.symbol
        hits = _glob.glob(str(data_dir / f"{cand}_{timeframe}.parquet")) or             _glob.glob(str(data_dir / f"{asset.symbol}_{timeframe}.parquet"))
        if not hits:
            continue
        df = _pd.read_parquet(hits[0])
        if len(df) > 100:
            frames[asset.symbol] = df.tail(tail_bars) if tail_bars else df

    if not frames:
        raise HTTPException(404, f"no cached {timeframe} data for any asset")

    cfg = HighProfileConfig(stop_model=stop_model, rvol_min=rvol_min,
                            rvol_top_n=rvol_top_n)
    signals = scan_all(frames, cfg=cfg, measured=load_measured(),
                       as_of=_pd.Timestamp(as_of) if as_of else None)
    return {
        "setup": "high_profile_orb",
        "timeframe": timeframe,
        "config": cfg.to_dict(),
        "assets_scanned": len(frames),
        "signals": signals,
        "count": len(signals),
        "reading_note": (
            "expected_value is the MEASURED net expectancy per trade in percent of "
            "account, from this repo's own backtest of this setup -- not a forecast. "
            "Where it is negative the setup lost money on the data it was measured "
            "on. See reports/HIGH_PROFILE_RESEARCH.md."
        ),
    }


@app.get("/api/v1/signals/scan-all")
def scan_all_timeframes(
    timeframes: str = Query(
        _SCAN_ALL_DEFAULT_TFS,
        description=(
            "Comma-separated timeframes to scan. Default covers each trading style once "
            "(15m Intraday, 1h+4h Swing, 1d Positional). Widening this multiplies the work: "
            "every timeframe is a full re-scan of every asset."
        ),
    ),
    symbols: Optional[str] = Query(
        None, description="Optional comma-separated assets. Omit to scan every supported asset."
    ),
    min_confidence: int = Query(
        0, ge=0, le=100,
        description="Drop signals below this confidence. 0 returns everything found.",
    ),
):
    """Scan every asset across MULTIPLE timeframes in one call, grouped by trading style.

    The single-timeframe /signals/scan above answers "what is live on 1d";
    this answers "what is live anywhere", which otherwise took one manual
    call per timeframe and a spreadsheet to reconcile.

    One timeframe failing (no data for that asset/interval, a provider
    outage) degrades to an error entry for THAT timeframe and the rest of
    the scan still returns -- a partial answer beats losing a 4-timeframe
    scan because one interval had no data.
    """
    registry = get_registry()
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    tf_list = [t.strip() for t in timeframes.split(",") if t.strip()]
    if not tf_list:
        raise HTTPException(400, "No timeframes given")

    signals_engine = registry.get("e51_signals")
    started = time.monotonic()
    all_signals: list[dict] = []
    errors: dict[str, str] = {}
    db_ok: Optional[bool] = None

    for tf in tf_list:
        try:
            result = signals_engine.scan_all_assets(
                registry.get("e02_market_data"),
                registry.get("e07_technical"),
                registry.get("e08_regime"),
                registry.get("e04_macro"),
                tf,
                fundamental_engine=registry.get("e06_fundamental"),
                data_quality_engine=registry.get("e40_data_quality"),
                symbols=symbol_list,
            )
        except Exception as e:  # noqa: BLE001 - one timeframe must not sink the scan
            errors[tf] = str(e)
            continue
        if not result.success:
            errors[tf] = result.message
            continue
        if db_ok is None:
            db_ok = _db_reachable() if result.data else False
        for s in result.data:
            payload = s.to_dict()
            if payload.get("confidence_score", 0) < min_confidence:
                continue
            payload["timeframe"] = tf
            payload["style"] = _TF_STYLE.get(tf, "Unknown")
            payload["signal_id"] = _persist_signal(s) if db_ok else None
            all_signals.append(payload)

    all_signals.sort(key=lambda p: p.get("confidence_score", 0), reverse=True)
    by_style: dict[str, list[dict]] = {}
    for p in all_signals:
        by_style.setdefault(p["style"], []).append(p)

    return {
        "timeframes_requested": tf_list,
        "timeframes_failed": errors,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "total_signals": len(all_signals),
        "count_by_style": {k: len(v) for k, v in by_style.items()},
        "count_by_timeframe": {
            tf: sum(1 for p in all_signals if p["timeframe"] == tf) for tf in tf_list
        },
        "by_style": by_style,
        "signals": all_signals,
    }


@app.post("/api/v1/risk/evaluate")
def evaluate_risk(req: SignalRequest):
    """Evaluate a trade proposal against CRO risk rules."""
    _validate_asset(req.asset)
    engine = get_registry().get("e45_risk")
    if not engine:
        raise HTTPException(500, "Risk Engine not available")

    proposal = TradeRiskProposal(
        asset=req.asset,
        direction=req.direction,
        entry_price=req.entry_price,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
        risk_percent=req.risk_percent,
        confidence_score=req.confidence_score,
        regime=req.regime,
    )
    result = engine.evaluate_trade(proposal)
    if not result.success:
        raise HTTPException(400, result.message)

    check = result.data
    pos = engine.calculate_position_size(
        settings.starting_capital,
        req.entry_price,
        req.stop_loss,
        check.adjusted_risk_pct or req.risk_percent,
    )
    return {
        "verdict": check.verdict.value,
        "approved": check.approved,
        "messages": check.messages,
        "veto_reason": check.veto_reason,
        "adjusted_risk_pct": check.adjusted_risk_pct,
        "position_size": pos.data if pos.success else None,
        "capital": settings.starting_capital,
        "currency": settings.capital_currency,
    }


@app.get("/api/v1/risk/funded-account/profiles")
def list_funded_account_profiles():
    """Real, web-verified funded-account rule presets (see
    e45_risk.FUNDINGPIPS_PROFILES source_notes for exactly what was
    confirmed vs. inferred). Not a live execution mode -- activating one
    only tightens which signals CRO will approve, per this platform's
    no-execution-engine governance (CLAUDE.md Rule 5)."""
    return {
        key: {
            "name": p.name, "profit_target_pct": p.profit_target_pct,
            "max_daily_loss_pct": p.max_daily_loss_pct, "max_overall_drawdown_pct": p.max_overall_drawdown_pct,
            "drawdown_type": p.drawdown_type, "min_trading_days": p.min_trading_days, "source_note": p.source_note,
        }
        for key, p in FUNDINGPIPS_PROFILES.items()
    }


@app.post("/api/v1/risk/funded-account/activate")
def activate_funded_account(req: FundedAccountActivateRequest):
    """Enter your real funded-account details -- from this call on, every
    signal is checked against YOUR account's actual daily-loss/drawdown
    rules (authoritative over this platform's generic small-capital
    defaults), including a proactive check that blocks a trade whose own
    worst case alone could breach today's floor, not just one already
    breached."""
    profile = FUNDINGPIPS_PROFILES.get(req.profile)
    if profile is None:
        raise HTTPException(400, f"Unknown profile {req.profile!r} -- see /api/v1/risk/funded-account/profiles")
    engine = get_registry().get("e45_risk")
    if not engine:
        raise HTTPException(500, "Risk Engine not available")
    result = engine.activate_funded_account(profile, req.account_size, req.current_equity)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"success": True, "message": result.message, "metadata": result.metadata}


@app.post("/api/v1/risk/funded-account/update-equity")
def update_funded_account_equity(req: FundedAccountEquityUpdateRequest):
    """Mark-to-market -- call whenever your real account equity changes."""
    engine = get_registry().get("e45_risk")
    if not engine:
        raise HTTPException(500, "Risk Engine not available")
    result = engine.update_funded_account_equity(req.current_equity)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"success": True, "message": result.message}


@app.post("/api/v1/risk/funded-account/deactivate")
def deactivate_funded_account():
    engine = get_registry().get("e45_risk")
    if not engine:
        raise HTTPException(500, "Risk Engine not available")
    result = engine.deactivate_funded_account()
    return {"success": True, "message": result.message}


@app.get("/api/v1/risk/funded-account/status")
def funded_account_status():
    engine = get_registry().get("e45_risk")
    if not engine:
        raise HTTPException(500, "Risk Engine not available")
    profile = engine._funded_profile
    if profile is None:
        return {"active": False}
    return {
        "active": True,
        "profile": profile.name,
        "account_start_balance": engine._funded_account_start_balance,
        "daily_start_balance": engine._funded_daily_start_balance,
        "current_equity": engine._funded_current_equity,
        "max_daily_loss_pct": profile.max_daily_loss_pct,
        "max_overall_drawdown_pct": profile.max_overall_drawdown_pct,
    }


@app.get("/api/v1/quant/risk-metrics")
def quant_risk_metrics(
    symbol: str = Query(...),
    timeframe: str = Query("1d"),
    years: int = Query(2),
    risk_free_rate: float = Query(0.0),
    var_confidence: float = Query(0.95, gt=0, lt=1),
):
    """Sharpe/Sortino/Calmar/CAGR/max-drawdown/VaR/CVaR for a supported asset's price history."""
    df, asset = _prepare_ohlcv(symbol, timeframe, years)
    engine = get_registry().get("e12_quant_research")
    if not engine:
        raise HTTPException(500, "Quant Research Engine not available")

    returns = df["close"].pct_change().dropna().to_numpy()
    result = engine.compute_risk_metrics(returns, risk_free_rate=risk_free_rate, var_confidence=var_confidence)
    if not result.success:
        raise HTTPException(400, result.message)

    m = result.data
    return {
        "symbol": asset.symbol if asset else symbol,
        "n_periods": m.n_periods,
        "sharpe_ratio": m.sharpe_ratio,
        "sortino_ratio": m.sortino_ratio,
        "calmar_ratio": m.calmar_ratio,
        "cagr_pct": m.cagr_pct,
        "max_drawdown_pct": m.max_drawdown_pct,
        "value_at_risk_pct": m.value_at_risk_pct,
        "conditional_var_pct": m.conditional_var_pct,
        "var_confidence": m.var_confidence,
    }


@app.post("/api/v1/quant/kelly")
def quant_kelly(req: KellyRequest):
    """Kelly Criterion position sizing from a known win-rate and average win/loss."""
    engine = get_registry().get("e12_quant_research")
    if not engine:
        raise HTTPException(500, "Quant Research Engine not available")
    result = engine.kelly_criterion(req.win_rate, req.avg_win, req.avg_loss, req.fraction_cap)
    if not result.success:
        raise HTTPException(400, result.message)
    k = result.data
    return {
        "kelly_fraction": k.kelly_fraction,
        "half_kelly_fraction": k.half_kelly_fraction,
        "edge": k.edge,
        "win_rate": k.win_rate,
        "win_loss_ratio": k.win_loss_ratio,
        "recommendation": k.recommendation,
    }


@app.get("/api/v1/quant/correlation")
def quant_correlation(
    symbols: str = Query(..., description="Comma-separated list, e.g. XAUUSD,EURUSD,BTCUSD"),
    timeframe: str = Query("1d"),
    years: int = Query(2),
    high_correlation_threshold: float = Query(0.7, gt=0, le=1),
):
    """
    Correlation matrix + PCA concentration-risk analysis across multiple
    assets. Series are aligned by taking each asset's last N closes (N = the
    shortest history among the requested symbols) -- a position-based
    alignment, not an exact calendar-date join, since different asset
    classes trade on different calendars (crypto 24/7 vs forex 24/5 vs
    indices weekdays-only). Good enough for a concentration-risk read; not
    precise enough for point-in-time backtesting.
    """
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(symbol_list) < 2:
        raise HTTPException(400, "Provide at least 2 comma-separated symbols")

    engine = get_registry().get("e12_quant_research")
    if not engine:
        raise HTTPException(500, "Quant Research Engine not available")

    returns_by_symbol = {}
    resolved_names = {}
    for sym in symbol_list:
        df, asset = _prepare_ohlcv(sym, timeframe, years)
        returns_by_symbol[sym] = df["close"].pct_change().dropna().to_numpy()
        resolved_names[sym] = asset.symbol if asset else sym

    min_len = min(len(r) for r in returns_by_symbol.values())
    if min_len < 10:
        raise HTTPException(400, "Not enough overlapping history across the requested symbols")
    aligned = {resolved_names[s]: r[-min_len:] for s, r in returns_by_symbol.items()}

    result = engine.correlation_clustering(aligned, high_correlation_threshold=high_correlation_threshold)
    if not result.success:
        raise HTTPException(400, result.message)

    c = result.data
    return {
        "symbols": c.symbols,
        "aligned_periods": min_len,
        "correlation_matrix": c.correlation_matrix,
        "explained_variance_ratio": c.explained_variance_ratio,
        "n_components_for_90pct": c.n_components_for_90pct,
        "diversification_ratio": c.diversification_ratio,
        "highly_correlated_pairs": c.highly_correlated_pairs,
    }


@app.get("/api/v1/quant/rolling-correlation")
def quant_rolling_correlation(
    symbols: str = Query(..., description="Comma-separated list, e.g. XAUUSD,EURUSD,BTCUSD"),
    timeframe: str = Query("1d"),
    years: int = Query(2),
    window: int = Query(30, gt=5, description="Recent-window length in periods"),
    shift_threshold: float = Query(0.3, gt=0, le=2, description="Absolute correlation change to flag as a regime shift"),
):
    """
    Rolling vs. full-period cross-asset correlation -- flags pairs whose
    recent correlation has moved sharply away from their full-period
    correlation (a correlation regime shift), which the static
    /quant/correlation snapshot can't see on its own.
    """
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(symbol_list) < 2:
        raise HTTPException(400, "Provide at least 2 comma-separated symbols")

    engine = get_registry().get("e12_quant_research")
    if not engine:
        raise HTTPException(500, "Quant Research Engine not available")

    returns_by_symbol = {}
    resolved_names = {}
    for sym in symbol_list:
        df, asset = _prepare_ohlcv(sym, timeframe, years)
        returns_by_symbol[sym] = df["close"].pct_change().dropna().to_numpy()
        resolved_names[sym] = asset.symbol if asset else sym

    min_len = min(len(r) for r in returns_by_symbol.values())
    if min_len < window + 5:
        raise HTTPException(400, f"Not enough overlapping history for a {window}-period rolling window")
    aligned = {resolved_names[s]: r[-min_len:] for s, r in returns_by_symbol.items()}

    result = engine.rolling_correlation(aligned, window=window, shift_threshold=shift_threshold)
    if not result.success:
        raise HTTPException(400, result.message)

    r = result.data
    return {
        "symbols": r.symbols,
        "aligned_periods": min_len,
        "window": r.window,
        "recent_correlation_matrix": r.recent_correlation_matrix,
        "full_period_correlation_matrix": r.full_period_correlation_matrix,
        "correlation_regime_shifts": r.correlation_regime_shifts,
    }


@app.get("/api/v1/quant/cointegration")
def quant_cointegration(
    symbol_a: str = Query(...),
    symbol_b: str = Query(...),
    timeframe: str = Query("1d"),
    years: int = Query(2),
):
    """Engle-Granger cointegration test between two assets' price history -- the standard first check before trusting a pairs/stat-arb strategy."""
    df_a, asset_a = _prepare_ohlcv(symbol_a, timeframe, years)
    df_b, asset_b = _prepare_ohlcv(symbol_b, timeframe, years)

    engine = get_registry().get("e12_quant_research")
    if not engine:
        raise HTTPException(500, "Quant Research Engine not available")

    min_len = min(len(df_a), len(df_b))
    series_a = df_a["close"].to_numpy()[-min_len:]
    series_b = df_b["close"].to_numpy()[-min_len:]

    result = engine.test_cointegration(series_a, series_b)
    if not result.success:
        raise HTTPException(400, result.message)

    r = result.data
    return {
        "symbol_a": asset_a.symbol if asset_a else symbol_a,
        "symbol_b": asset_b.symbol if asset_b else symbol_b,
        "aligned_periods": min_len,
        "t_statistic": r.t_statistic,
        "p_value": r.p_value,
        "critical_values": r.critical_values,
        "is_cointegrated": r.is_cointegrated,
        "confidence_level": r.confidence_level,
    }


@app.post("/api/v1/quant/bayesian-win-rate")
def quant_bayesian_win_rate(req: BayesianWinRateRequest):
    """Beta-Binomial Bayesian update of a strategy's true win rate, with a 90% credible interval."""
    engine = get_registry().get("e12_quant_research")
    if not engine:
        raise HTTPException(500, "Quant Research Engine not available")
    result = engine.bayesian_win_rate_update(req.wins, req.losses, req.prior_alpha, req.prior_beta)
    if not result.success:
        raise HTTPException(400, result.message)
    r = result.data
    return {
        "posterior_alpha": r.posterior_alpha,
        "posterior_beta": r.posterior_beta,
        "posterior_mean": r.posterior_mean,
        "credible_interval_90pct": r.credible_interval_90pct,
    }


@app.post("/api/v1/performance/trades", status_code=201)
def log_trade(req: TradeCreate):
    """
    Log a closed trade (Engine #35). This platform has no execution engine
    (Rule 5) -- every trade here is a manually-entered, already-closed
    record, optionally linked back to the E51 signal (signal_id) that
    prompted it.
    """
    _validate_asset(req.symbol)
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    result = engine.log_trade(**req.model_dump())
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data


@app.get("/api/v1/performance/trades")
def list_logged_trades(
    symbol: Optional[str] = Query(None),
    strategy_name: Optional[str] = Query(None),
    regime_at_entry: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    result = engine.list_trades(symbol, strategy_name, regime_at_entry, limit)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"count": len(result.data), "trades": result.data}


@app.get("/api/v1/performance/summary")
def performance_summary(
    symbol: Optional[str] = Query(None),
    strategy_name: Optional[str] = Query(None),
    regime_at_entry: Optional[str] = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
):
    """KPIs (win rate, profit factor, expectancy, max drawdown) computed
    from the logged trade journal, optionally filtered."""
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    result = engine.summarize(symbol, strategy_name, regime_at_entry, limit)
    if not result.success:
        raise HTTPException(404, result.message)
    return result.data.to_dict()


@app.get("/api/v1/performance/signal-conversion-rate")
def signal_conversion_rate(
    symbol: Optional[str] = Query(None),
    limit: int = Query(20000, ge=1, le=100_000),
):
    """docs/UPGRADE_BRIEF.md Phase 9: "signals not taken" discipline
    metric -- how many generated E51 signals actually became a logged
    trade, overall and per symbol."""
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    result = engine.signal_conversion_rate(symbol, limit)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data


@app.get("/api/v1/performance/attribution")
def performance_attribution(
    field: str = Query("strategy_name", description="One of: strategy_name, regime_at_entry, session_tag, symbol, direction"),
    limit: int = Query(5000, ge=1, le=20000),
):
    """
    Trade Attribution (Engine #34): groups the logged trade journal by the
    given field and reports each group's own performance -- which
    conditions this actually performs well or badly under.
    """
    engine = get_registry().get("e34_trade_attribution")
    if not engine:
        raise HTTPException(500, "Trade Attribution Engine not available")
    result = engine.attribute_by_field(field, limit)
    if not result.success:
        raise HTTPException(400, result.message)
    return {
        "groups": {k: v.to_dict() for k, v in result.data["groups"].items()},
        "best_group": result.data["best_group"],
        "worst_group": result.data["worst_group"],
    }


@app.get("/api/v1/performance/confluence-scoreboard")
def confluence_scoreboard(limit: int = Query(5000, ge=1, le=20000)):
    """
    Confluence-accuracy scoreboard (Engine #34), added 2026-08-21:
    "when engine E## agreed vs. disagreed with the trade's direction,
    did we actually win more often" -- computed from each trade's real
    linked-signal evidence (never fabricated: a tag only appears here if
    that trade's signal genuinely mentioned it). Closes the loop
    _persist_signal's own docstring flagged as open since real evidence
    became queryable: nothing had actually analyzed it until now.
    """
    engine = get_registry().get("e34_trade_attribution")
    if not engine:
        raise HTTPException(500, "Trade Attribution Engine not available")
    result = engine.attribute_by_confluence_tag(limit)
    if not result.success:
        raise HTTPException(404, result.message)
    return {tag: {cls: summary.to_dict() for cls, summary in classes.items()} for tag, classes in result.data.items()}


# ============================================================
# Self-improvement trade journal -- added 2026-08-21. See
# engines/e35_performance_analytics/mistake_tagging.py for the
# rule-detection logic and its own docstring for full provenance
# (5-repo audit, and why every rule is computed automatically rather
# than relying on a manual pre-trade checklist).
# ============================================================


class MistakeRuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    params: Optional[dict] = None


class TradeTagCreate(BaseModel):
    """Manually attach a tag to a logged trade -- the path for psychology
    tags (category="psychology"), which need human judgment rather than
    automatic detection. rule_adherence/behavioral tags are always
    computed automatically by log_trade() and shouldn't be posted here."""

    category: str = Field(pattern="^(psychology|setup)$")
    tag_key: str
    negative: bool = True
    detail: Optional[dict] = None


class TradeIntentCreate(BaseModel):
    """Manual 'I took this trade' acknowledgment -- captures the intended
    entry snapshot at the moment of decision, before hindsight bias sets
    in. Records that a human says they acted; does not act. No execution
    engine, no order, no broker call anywhere in this path (Rule 5)."""

    signal_id: Optional[int] = None
    symbol: str
    direction: str = Field(pattern="^(long|short)$")
    intended_entry_price: Optional[float] = None


@app.get("/api/v1/performance/mistake-rules")
def list_mistake_rules():
    """Your own small, editable set of rules every logged trade is
    automatically checked against. Seeded with sensible defaults on
    first call if none exist yet."""
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    engine.ensure_default_mistake_rules()
    result = engine.get_mistake_rules()
    if not result.success:
        raise HTTPException(400, result.message)
    return {"rules": result.data}


@app.patch("/api/v1/performance/mistake-rules/{rule_key}")
def update_mistake_rule(rule_key: str, req: MistakeRuleUpdate):
    """Toggle a rule on/off, or retune its threshold (e.g.
    {"min_confidence": 70}) -- never changes what it detects."""
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    result = engine.update_mistake_rule(rule_key, enabled=req.enabled, params=req.params)
    if not result.success:
        raise HTTPException(404, result.message)
    return {"message": result.message}


@app.get("/api/v1/performance/trades/{trade_id}/tags")
def list_trade_tags(trade_id: int):
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    result = engine.list_trade_tags(trade_id)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"tags": result.data}


@app.post("/api/v1/performance/trades/{trade_id}/tags", status_code=201)
def add_trade_tag(trade_id: int, req: TradeTagCreate):
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    result = engine.add_trade_tag(trade_id, req.category, req.tag_key, req.negative, req.detail)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data


@app.get("/api/v1/performance/mistake-summary")
def mistake_summary(days: int = Query(30, ge=1, le=3650)):
    """Phase 4 self-improvement feedback loop: which mistake tag has cost
    the most cumulative real R over the last `days` days, computed
    directly from your own logged trade journal. SUGGESTION only --
    nothing here reads or adjusts any live trading parameter."""
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = engine.aggregate_mistake_costs(since=since)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data


@app.post("/api/v1/performance/trade-intents", status_code=201)
def create_trade_intent(req: TradeIntentCreate):
    """Manual acknowledgment that a signal was acted on -- see
    TradeIntentCreate's own docstring. Purely a journaling snapshot, not
    an order; this platform has no execution engine (Rule 5)."""
    try:
        with get_db_session() as session:
            intent = TradeIntent(
                signal_id=req.signal_id, symbol=req.symbol.upper(),
                direction=req.direction, intended_entry_price=req.intended_entry_price,
            )
            session.add(intent)
            session.flush()
            intent_id = intent.id
        return {"intent_id": intent_id}
    except Exception as e:
        raise HTTPException(500, f"Failed to record trade intent: {e}")


@app.get("/api/v1/performance/trade-intents")
def list_trade_intents(
    symbol: Optional[str] = Query(None),
    limit: int = Query(100, gt=0, le=1000),
):
    """List logged trade intents -- added 2026-09-13 (docs/UPGRADE_BRIEF.md
    Phase 12, "Positions" dashboard surface) as the read side of the
    existing write-only POST above. This platform has no execution engine
    (Rule 5), so "positions" here means the honest equivalent: intents a
    human marked as acted-on, not live broker positions.

    Each intent's `closed` field is best-effort, never guessed: True if a
    Trade row with the same signal_id exists (the position was later
    logged as closed), False if not, None when the intent has no
    signal_id at all (a purely discretionary intent -- there is no join
    key to check against, so "still open" would be a fabricated claim,
    not a real one)."""
    engine = get_registry().get("e35_performance_analytics")
    if not engine:
        raise HTTPException(500, "Performance Analytics Engine not available")
    try:
        with get_db_session() as session:
            query = session.query(TradeIntent)
            if symbol:
                query = query.filter(TradeIntent.symbol == symbol.upper())
            intents = query.order_by(TradeIntent.marked_at.desc()).limit(limit).all()

            signal_ids = {i.signal_id for i in intents if i.signal_id is not None}
            closed_signal_ids = set()
            if signal_ids:
                closed_signal_ids = {
                    row[0] for row in session.query(Trade.signal_id)
                    .filter(Trade.signal_id.in_(signal_ids)).all()
                }

            items = [
                {
                    "id": i.id,
                    "signal_id": i.signal_id,
                    "symbol": i.symbol,
                    "direction": i.direction,
                    "intended_entry_price": float(i.intended_entry_price) if i.intended_entry_price is not None else None,
                    "marked_at": i.marked_at.isoformat(),
                    "closed": (i.signal_id in closed_signal_ids) if i.signal_id is not None else None,
                }
                for i in intents
            ]
        return {"count": len(items), "intents": items}
    except Exception as e:
        raise HTTPException(500, f"Failed to list trade intents: {e}")


def _returns_and_cov_for_symbols(symbols: list[str], timeframe: str, years: int):
    """Real historical returns + covariance matrix for a list of this
    platform's own supported symbols -- fetches actual OHLCV per symbol
    (same _prepare_ohlcv every other symbol-based endpoint uses), aligns by
    taking each asset's last N closes (N = shortest history among the
    requested symbols, same position-based alignment convention
    /quant/correlation already uses)."""
    from project_titan_x.engines.e31_portfolio_construction import covariance_matrix_from_returns

    returns_by_symbol: dict[str, Any] = {}
    resolved_names: dict[str, str] = {}
    for sym in symbols:
        df, asset = _prepare_ohlcv(sym, timeframe, years)
        returns_by_symbol[sym] = df["close"].pct_change().dropna().to_numpy()
        resolved_names[sym] = asset.symbol if asset else sym

    min_len = min(len(r) for r in returns_by_symbol.values())
    if min_len < 10:
        raise HTTPException(400, "Not enough overlapping history across the requested symbols")
    aligned = {resolved_names[s]: r[-min_len:] for s, r in returns_by_symbol.items()}
    ordered_symbols, cov = covariance_matrix_from_returns(aligned)
    mean_returns = [float(np.mean(aligned[s])) for s in ordered_symbols]
    return ordered_symbols, mean_returns, cov


@app.get("/api/v1/portfolio/min-variance")
def portfolio_min_variance(
    symbols: str = Query(..., description="Comma-separated list, e.g. GOLD,SILVER,BTCUSD"),
    timeframe: str = Query("1d"),
    years: int = Query(2),
    long_only: bool = Query(False),
):
    """Minimum-variance portfolio weights (Engine #31) across the given symbols'
    real historical returns."""
    engine = get_registry().get("e31_portfolio_construction")
    if not engine:
        raise HTTPException(500, "Portfolio Construction Engine not available")
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(symbol_list) < 2:
        raise HTTPException(400, "Provide at least 2 comma-separated symbols")
    ordered_symbols, _, cov = _returns_and_cov_for_symbols(symbol_list, timeframe, years)
    result = engine.min_variance(ordered_symbols, cov, long_only)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data.to_dict()


@app.get("/api/v1/portfolio/max-sharpe")
def portfolio_max_sharpe(
    symbols: str = Query(..., description="Comma-separated list, e.g. GOLD,SILVER,BTCUSD"),
    timeframe: str = Query("1d"),
    years: int = Query(2),
    risk_free_rate: float = Query(0.0),
    long_only: bool = Query(False),
):
    """Maximum-Sharpe portfolio weights (Engine #31) across the given symbols'
    real historical returns."""
    engine = get_registry().get("e31_portfolio_construction")
    if not engine:
        raise HTTPException(500, "Portfolio Construction Engine not available")
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(symbol_list) < 2:
        raise HTTPException(400, "Provide at least 2 comma-separated symbols")
    ordered_symbols, mean_returns, cov = _returns_and_cov_for_symbols(symbol_list, timeframe, years)
    result = engine.max_sharpe(ordered_symbols, mean_returns, cov, risk_free_rate, long_only)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data.to_dict()


@app.get("/api/v1/portfolio/efficient-frontier")
def portfolio_efficient_frontier(
    symbols: str = Query(..., description="Comma-separated list, e.g. GOLD,SILVER,BTCUSD"),
    timeframe: str = Query("1d"),
    years: int = Query(2),
    n_points: int = Query(20, ge=2, le=100),
    long_only: bool = Query(True),
):
    """Efficient frontier (Engine #31): volatility-minimizing weights across a
    range of target returns, from the given symbols' real historical returns."""
    engine = get_registry().get("e31_portfolio_construction")
    if not engine:
        raise HTTPException(500, "Portfolio Construction Engine not available")
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(symbol_list) < 2:
        raise HTTPException(400, "Provide at least 2 comma-separated symbols")
    ordered_symbols, mean_returns, cov = _returns_and_cov_for_symbols(symbol_list, timeframe, years)
    result = engine.efficient_frontier(ordered_symbols, mean_returns, cov, n_points, long_only)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data.to_dict()


@app.get("/api/v1/portfolio/risk-parity")
def portfolio_risk_parity(
    symbols: str = Query(..., description="Comma-separated list, e.g. GOLD,SILVER,BTCUSD"),
    timeframe: str = Query("1d"),
    years: int = Query(2),
):
    """Risk-parity portfolio weights (Engine #31): equal RISK contribution
    (not equal capital) per asset, from real historical returns."""
    engine = get_registry().get("e31_portfolio_construction")
    if not engine:
        raise HTTPException(500, "Portfolio Construction Engine not available")
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(symbol_list) < 2:
        raise HTTPException(400, "Provide at least 2 comma-separated symbols")
    ordered_symbols, _, cov = _returns_and_cov_for_symbols(symbol_list, timeframe, years)
    result = engine.risk_parity(ordered_symbols, cov)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data.to_dict()


@app.post("/api/v1/portfolio/black-litterman")
def portfolio_black_litterman(req: BlackLittermanApiRequest):
    """
    Black-Litterman posterior expected returns (Engine #31): blends a
    caller-supplied market-weighted equilibrium prior with caller-supplied
    views (P/Q), using the given symbols' real historical covariance. This
    platform's assets have no single clean "market cap" convention the way
    equity indices do, so market_weights/P/Q are always caller-supplied,
    never fabricated here.
    """
    if len(req.market_weights) != len(req.symbols):
        raise HTTPException(400, "market_weights must have one entry per symbol")
    engine = get_registry().get("e31_portfolio_construction")
    if not engine:
        raise HTTPException(500, "Portfolio Construction Engine not available")
    ordered_symbols, _, cov = _returns_and_cov_for_symbols(req.symbols, req.timeframe, req.years)
    # Re-order market_weights to match the covariance builder's own symbol order.
    reordered_weights = [req.market_weights[req.symbols.index(s)] for s in ordered_symbols]
    result = engine.black_litterman(ordered_symbols, reordered_weights, cov, req.P, req.Q, req.risk_aversion, req.tau)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data.to_dict()


@app.post("/api/v1/portfolio/volatility-target")
def portfolio_volatility_target(req: VolatilityTargetApiRequest):
    """Scale a weight vector (Engine #31) so realized portfolio volatility
    matches a target, using the given symbols' real historical covariance."""
    if len(req.weights) != len(req.symbols):
        raise HTTPException(400, "weights must have one entry per symbol")
    engine = get_registry().get("e31_portfolio_construction")
    if not engine:
        raise HTTPException(500, "Portfolio Construction Engine not available")
    ordered_symbols, _, cov = _returns_and_cov_for_symbols(req.symbols, req.timeframe, req.years)
    reordered_weights = [req.weights[req.symbols.index(s)] for s in ordered_symbols]
    result = engine.volatility_target(ordered_symbols, reordered_weights, cov, req.target_vol, req.max_leverage)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data.to_dict()


@app.get("/api/v1/opportunities/rank")
def rank_opportunities(
    timeframe: str = Query("1d"),
    years: int = Query(2),
    symbols: Optional[str] = Query(None, description="Comma-separated subset, e.g. GOLD,BTCUSD -- omit to rank every supported asset"),
):
    """
    Opportunity Ranking (Engine #33): ranks every supported asset by E51's
    own conviction score (already blending technical/macro/confluence),
    including assets that don't clear the full tradeable-signal bar --
    "what's the best opportunity right now" across the whole watchlist,
    not just what fired.
    """
    engine = get_registry().get("e33_opportunity_ranking")
    if not engine:
        raise HTTPException(500, "Opportunity Ranking Engine not available")
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    result = engine.rank_opportunities(timeframe=timeframe, years=years, symbols=symbol_list)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"count": len(result.data), "opportunities": [r.to_dict() for r in result.data]}


@app.get("/api/v1/strategy-research/reports")
def list_strategy_research_reports():
    """Summary of every already-computed E24 strategy research report --
    added 2026-09-13 (docs/UPGRADE_BRIEF.md Phase 12, Strategy Laboratory
    / Backtesting dashboard surfaces). Read-only: this reads reports
    research scripts already wrote to disk, it never triggers a new
    research run (that stays a deliberately offline/scripted workflow,
    per Rule 3 -- nothing enters live signals except through E24 -> E26 ->
    explicit promotion)."""
    engine = get_registry().get("e24_strategy_research")
    if not engine:
        raise HTTPException(500, "Strategy Research Engine not available")
    result = engine.list_reports()
    if not result.success:
        raise HTTPException(400, result.message)
    return {"count": len(result.data), "reports": result.data}


@app.get("/api/v1/strategy-research/reports/{symbol}/{timeframe}")
def get_strategy_research_report(symbol: str, timeframe: str):
    """Full E24 research report (every candidate tried) for one
    symbol+timeframe -- see list_strategy_research_reports for the
    lighter summary view."""
    engine = get_registry().get("e24_strategy_research")
    if not engine:
        raise HTTPException(500, "Strategy Research Engine not available")
    result = engine.get_report(symbol.upper(), timeframe)
    if not result.success:
        raise HTTPException(404, result.message)
    return result.data


@app.get("/api/v1/calibration/report")
def confidence_calibration_report(
    strategy_name: Optional[str] = Query(None),
    bucket_width: int = Query(20, ge=5, le=50),
    min_trades_per_bucket: int = Query(5, ge=1),
):
    """
    Confidence Calibration (Engine #42): bins the logged trade journal by
    confidence_at_entry and compares predicted confidence against actual
    win rate per bucket -- "an 80% confidence signal should behave like
    80% over time." A bucket with too few trades reports
    status="insufficient_data" honestly rather than a noisy/fabricated
    win rate.
    """
    engine = get_registry().get("e42_confidence_calibration")
    if not engine:
        raise HTTPException(500, "Confidence Calibration Engine not available")
    result = engine.calibration_report(strategy_name, bucket_width, min_trades_per_bucket)
    if not result.success:
        raise HTTPException(404, result.message)
    return result.data.to_dict()


@app.get("/api/v1/alpha-decay/assess")
def assess_alpha_decay(
    strategy_name: Optional[str] = Query(None),
    recent_window: int = Query(20, ge=1),
    min_trades_per_window: int = Query(10, ge=1),
):
    """
    Alpha Decay Monitor (Engine #38): compares a strategy's most recent
    logged trades against its own earlier baseline, flagging statistically
    real degradation (non-overlapping 90% Bayesian credible intervals on
    win rate) rather than just a losing streak.
    """
    engine = get_registry().get("e38_alpha_decay_monitor")
    if not engine:
        raise HTTPException(500, "Alpha Decay Monitor Engine not available")
    result = engine.assess_decay(strategy_name, recent_window, min_trades_per_window)
    if not result.success:
        raise HTTPException(400, result.message)
    return result.data.to_dict()


@app.get("/api/v1/knowledge/traders")
def list_traders(category: str | None = None):
    """List trader knowledge profiles."""
    engine = get_registry().get("e01_knowledge")
    if not engine:
        raise HTTPException(500, "Knowledge Engine not available")
    result = engine.list_traders(category=category)
    return result.data if result.success else []


@app.get("/api/v1/knowledge/search")
def search_knowledge(q: str = Query(...), limit: int = 10):
    """Semantic search across knowledge base."""
    engine = get_registry().get("e01_knowledge")
    if not engine:
        raise HTTPException(500, "Knowledge Engine not available")
    result = engine.search_knowledge(q, limit=limit)
    return result.data if result.success else []


@app.post("/api/v1/knowledge/documents/ingest-all")
async def ingest_all_documents():
    """Ingest every supported document currently under data/{books,research,
    annual_reports,sec_filings,trading_journals,notes}."""
    engine = get_registry().get("e01_knowledge")
    if not engine:
        raise HTTPException(500, "Knowledge Engine not available")
    result = await engine.ingest_all()
    return {"message": result.message, "results": result.data}


@app.get("/api/v1/knowledge/documents/search")
async def search_documents(
    q: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    document_type: str | None = None,
    topic: str | None = None,
):
    """Hybrid (vector + keyword + metadata) search over ingested documents
    -- distinct from /api/v1/knowledge/search above, which searches the
    trader-profile knowledge base, not ingested documents."""
    engine = get_registry().get("e01_knowledge")
    if not engine:
        raise HTTPException(500, "Knowledge Engine not available")
    metadata_filter: dict[str, Any] = {}
    if document_type:
        from project_titan_x.engines.e01_knowledge import DocumentType
        metadata_filter["document_type"] = DocumentType(document_type)
    if topic:
        from project_titan_x.engines.e01_knowledge import KnowledgeCategory
        metadata_filter["topic"] = KnowledgeCategory(topic)
    result = await engine.search(q, limit=limit, metadata_filter=metadata_filter or None)
    return {"message": result.message, "results": [r.to_dict() for r in result.data]}


@app.get("/api/v1/knowledge/documents/answer")
async def answer_from_documents(q: str = Query(...)):
    """Extractive answer (best-matching passage + citations) -- not an
    LLM-generated summary, see KnowledgeEngine.answer()."""
    engine = get_registry().get("e01_knowledge")
    if not engine:
        raise HTTPException(500, "Knowledge Engine not available")
    result = await engine.answer(q)
    return result.data


@app.get("/api/v1/knowledge/documents/related-topics")
async def related_document_topics(topic: str = Query(...), limit: int = Query(5, ge=1, le=20)):
    engine = get_registry().get("e01_knowledge")
    if not engine:
        raise HTTPException(500, "Knowledge Engine not available")
    result = await engine.related_topics(topic, limit=limit)
    return {"topic": topic, "related": result.data}


@app.get("/api/v1/knowledge/documents/sources")
async def document_sources(topic: str | None = None):
    engine = get_registry().get("e01_knowledge")
    if not engine:
        raise HTTPException(500, "Knowledge Engine not available")
    result = await engine.get_sources(topic=topic)
    return result.data


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Serve the dashboard -- the "Aurora" premium redesign is now THE
    dashboard (promoted 2026-08-21: the old generic-styled index.html was
    deleted per explicit request, index_premium.html renamed to index.html
    in its place -- no route change needed here, this already pointed at
    dashboard/index.html)."""
    dashboard_path = Path(__file__).parent.parent / "dashboard" / "index.html"
    if dashboard_path.exists():
        return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>PROJECT TITAN-X Dashboard</h1>")


@app.get("/dashboard/premium", response_class=HTMLResponse)
def dashboard_premium():
    """Old alias, kept working rather than 404ing in case anyone bookmarked
    it -- /dashboard/premium and /dashboard now serve the exact same file."""
    return dashboard()


_DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"

# New dashboard surfaces added 2026-09-13 (docs/UPGRADE_BRIEF.md Phase 12).
# dashboard/index.html itself is explicitly off-limits ("do not touch the
# existing UI file") -- every new surface below lives in its own file
# under dashboard/pages/ and is served the exact same simple way
# dashboard() above already serves index.html (a plain read + HTMLResponse,
# not a StaticFiles mount, so these stay behind this app's own
# require_api_key dependency exactly like every other route here, rather
# than opening an unauthenticated static-file path alongside a gated API).
def _serve_dashboard_page(filename: str) -> HTMLResponse:
    path = _DASHBOARD_DIR / "pages" / filename
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    raise HTTPException(404, f"Dashboard page {filename} not found")


@app.get("/dashboard/market-structure", response_class=HTMLResponse)
def dashboard_market_structure():
    """Market Structure / ICT-SMC dashboard (order blocks, FVGs, liquidity
    sweeps, Wyckoff phase, harmonics, RSI divergence, active killzones) --
    the fields GET /api/v1/technical/analyze exposes as of this same
    Phase 12 pass (previously computed but never serialized)."""
    return _serve_dashboard_page("market_structure.html")


@app.get("/dashboard/risk", response_class=HTMLResponse)
def dashboard_risk():
    """Risk Dashboard: funded-account status/profiles + the risk-evaluate
    proposal checker (Engine #45)."""
    return _serve_dashboard_page("risk.html")


@app.get("/dashboard/portfolio", response_class=HTMLResponse)
def dashboard_portfolio():
    """Portfolio & Positions: construction/allocation routes (Engine #31)
    + opportunity ranking (Engine #33) + logged trade intents (the honest,
    no-execution-engine equivalent of "positions", Rule 5)."""
    return _serve_dashboard_page("portfolio.html")


@app.get("/dashboard/news-sentiment", response_class=HTMLResponse)
def dashboard_news_sentiment():
    """News & Sentiment: the Phase 11 enriched news/sentiment pipeline
    (entities, event type, market impact, bullish/bearish/neutral,
    duplicate detection)."""
    return _serve_dashboard_page("news_sentiment.html")


@app.get("/dashboard/options", response_class=HTMLResponse)
def dashboard_options():
    """Indian Options Chain (NIFTY50/BANKNIFTY via Kite Connect, Engine
    #13) -- PCR, max pain, ATM/ITM/OTM, Greeks."""
    return _serve_dashboard_page("options.html")


@app.get("/dashboard/strategy-lab", response_class=HTMLResponse)
def dashboard_strategy_lab():
    """Strategy Laboratory & Backtesting: browse E24's already-computed
    research reports (candidate grids, validation bar, promoted
    overrides) and run E51's live historical-edge check. Read-only over
    already-computed results -- never triggers a new research run from
    the UI (Rule 3: nothing enters live signals except through the
    offline E24 -> E26 -> explicit-promotion pipeline)."""
    return _serve_dashboard_page("strategy_lab.html")


@app.get("/dashboard/shared/{filename}")
def dashboard_shared_asset(filename: str):
    """Shared CSS/JS for the new Phase 12 pages above (see dashboard/
    shared/'s own file headers). Restricted to the two known filenames --
    this is not a general static-file server."""
    if filename not in ("tokens.css", "common.js"):
        raise HTTPException(404, "Not found")
    path = _DASHBOARD_DIR / "shared" / filename
    if not path.exists():
        raise HTTPException(404, "Not found")
    media_type = "text/css" if filename.endswith(".css") else "application/javascript"
    return Response(content=path.read_text(encoding="utf-8"), media_type=media_type)
