"""
Module: settings.py
Description: Central configuration for PROJECT TITAN-X.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "PROJECT_TITAN_X"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change-me-in-production"

    # LOOPBACK BY DEFAULT (changed 2026-09-08). Was "0.0.0.0", which binds
    # every interface: on any shared, bridged or public Wi-Fi network that
    # exposed all 78 routes -- including POST /api/v1/market-data/fetch and
    # the brain workflow runner -- to anything that could reach the port,
    # with no authentication of any kind.
    #
    # Containers are unaffected: docker-compose.yml and the Dockerfile pass
    # `--host 0.0.0.0` on the uvicorn command line, which is correct and
    # necessary inside a container (the process must accept traffic from the
    # Docker bridge). Their exposure is controlled by which host interface
    # the port is PUBLISHED on, which is now pinned to 127.0.0.1 in
    # docker-compose.yml. This default governs bare-metal/local runs, where
    # loopback is the right answer.
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Shared-secret for the API. When set, every route except the small
    # exempt set (see api/main.py _AUTH_EXEMPT_PATHS) requires a matching
    # X-API-Key header. When unset the API is open, which is only safe
    # because api_host defaults to loopback -- api/main.py logs a warning at
    # startup naming that trade-off, loudly if the bind is NOT loopback.
    #
    # Deliberately a shared secret, not the JWT in core/security/auth.py:
    # that module implements login/roles against a user store this system
    # does not have, and has never been wired to a route. A single-operator
    # local service needs a key, not an identity system. The JWT module is
    # left untouched for whenever multi-user access is actually built.
    api_key: Optional[str] = None

    # Comma-separated CORS origin allowlist. Was allow_origins=["*"] with
    # allow_credentials=True -- a combination browsers reject outright, so
    # it bought nothing while removing the origin check. The dashboard
    # calls the API with same-origin relative paths (fetch('/api/v1/...')),
    # so it needs no cross-origin grant at all; this exists for a separately
    # hosted front end.
    cors_allow_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # PostgreSQL
    # Host port 5433, not the Postgres-standard 5432 -- matches
    # docker-compose.yml's deliberate remap (this machine also runs a
    # separate project's own Postgres container bound to 5432; see that
    # file's comment). Without a .env override, this default is the ONLY
    # thing telling the app which Postgres to talk to -- previously 5432
    # here silently connected to the OTHER project's database instead of
    # this one's, which is exactly why trade/risk-event logging was
    # failing with "password authentication failed for user titanx": it
    # was a real connection to the wrong server, not a misconfigured
    # password on this project's own database.
    # "127.0.0.1", not "localhost": when Postgres is unreachable, libpq
    # resolves "localhost" to BOTH ::1 (IPv6) and 127.0.0.1 (IPv4) and
    # tries each in turn -- connect_timeout applies PER ADDRESS, so a
    # down/unreachable DB was measured taking ~4s to fail (2x the
    # configured 2s timeout in session.py), not the ~2s intended. A
    # literal IP has only one address to try.
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5433
    postgres_user: str = "titanx"
    postgres_password: str = "titanx_secret"
    postgres_db: str = "titanx"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    # Added 2026-08-21 for e02_market_data's OHLCV fetch cache (see
    # core/cache.py and MarketDataEngine.fetch_ohlcv's own docstring for
    # the real, measured scan-performance reasoning). 180s is short
    # enough that a 1d bar (changes once per session) or a 1h bar can
    # never be served meaningfully stale, long enough to make repeated
    # scans/filter-switches within the same sitting skip the real
    # network fetch entirely.
    ohlcv_cache_ttl_seconds: int = 180

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "knowledge"

    # Capital (small-account mode)
    starting_capital: float = 10_000.0
    capital_currency: str = "INR"
    default_risk_per_trade_pct: float = 0.5
    # True since 2026-07-19 -- price/technical-only equity support added
    # (core/config/assets.py AssetClass.EQUITY). Purely a reported flag
    # (api/main.py's status endpoint); nothing else in the codebase gates
    # behavior on it -- actual equity support is controlled by whether a
    # symbol exists in assets.SUPPORTED_ASSETS.
    equities_enabled: bool = True

    # Risk limits (CRO absolute authority)
    max_daily_loss_pct: float = 2.0
    max_weekly_loss_pct: float = 5.0
    max_monthly_loss_pct: float = 10.0
    max_drawdown_pct: float = 20.0
    max_risk_of_ruin_pct: float = 1.0
    max_portfolio_heat_pct: float = 4.0
    min_risk_reward_ratio: float = 2.0
    # Added 2026-08-02 as part of e45_risk's upgrade: PortfolioRiskState
    # already carried a correlation_max field, but nothing in
    # evaluate_trade ever read it -- confirmed via a full-codebase grep
    # (correlation_max appeared exactly once, its own declaration). 0.7 is
    # a commonly-cited "highly correlated" threshold in portfolio risk
    # literature (correlation this high means two positions are close to
    # moving as one, defeating the diversification portfolio_heat_pct
    # assumes). max_consecutive_losses is a standard discretionary-risk
    # circuit breaker (halt and force a human review after a losing
    # streak, independent of whether cumulative %-loss limits have been
    # hit yet) -- also previously absent.
    max_correlation_exposure: float = 0.7
    max_consecutive_losses: int = 5
    # Added 2026-09-13, closing a real Phase 8 gap: docs/UPGRADE_BRIEF.md
    # asks for "max open positions" as its own limit, independent of
    # portfolio_heat_pct/correlation_max -- PortfolioRiskState already
    # tracked open_positions (confirmed via grep: read only by E46's own
    # risk-posture narrative, never checked as a hard limit anywhere). 10
    # is a static, documented convention for this platform's own small-
    # capital/manually-journaled mode (this project has no execution
    # engine to enforce concurrent-order limits at the broker level), not
    # a number sourced from any specific account type.
    max_open_positions: int = 10
    # Lowered from 80 -- that floor was calibrated around the OLD strict
    # EMA-stack+ADX>25 composite-score direction rule (see e51_signals'
    # _determine_direction history). The signal engine now uses a Command-
    # Center-style heuristic score (trend/25 dampened by MACD agreement,
    # averaged with RSI momentum, threshold +-0.2) whose confidence is
    # honestly |score|*100 -- NOT a calibrated probability, same explicit
    # caveat Command Center's own code documents about itself. 80 would
    # almost never be reached under this formula; 20 matches the same
    # +-0.2 combined-score threshold that determines direction in the first
    # place, so a signal that fires at all already clears this floor by
    # construction. This is a deliberate, informed trade of rigor for
    # signal frequency -- explicitly requested after being told exactly
    # that trade-off. Per-asset validated overrides (see
    # e51_signals._load_strategy_override, e.g. SP500's Donchian breakout)
    # set their own, still-real, backtest-derived floor and are unaffected.
    min_signal_confidence: int = 20
    max_risk_per_trade_pct: float = 1.0

    # Hard ceiling on position NOTIONAL as a multiple of capital, applied
    # by e45_risk.calculate_position_size. Added 2026-08-22 to close a
    # real gap: fixed-fractional sizing is risk_amount/stop_distance,
    # which says nothing about whether the resulting position is
    # affordable. Measured on a $10,000 account at the default 1% risk, a
    # 0.5% stop already implies 2x notional, a 0.25% stop 4x, and a 0.1%
    # stop 10x -- so a perfectly ordinary tight intraday stop silently
    # produced leverage the account may not have, from a setting the user
    # reads as "risk 1%". 1.0 = never exceed cash on hand; raise it
    # deliberately only for an account with real margin.
    max_position_leverage: float = 1.0

    # Data providers
    yahoo_finance_enabled: bool = True
    alpha_vantage_api_key: Optional[str] = None
    alpha_vantage_daily_limit: int = 25
    twelve_data_api_key: Optional[str] = None
    # Powers EconomicCalendarEngine's live upcoming-events feed (see
    # core.data_providers.finnhub) -- None by default, same graceful-no-op
    # convention as alpha_vantage_api_key above. Free-tier registration at
    # finnhub.io requires no payment info, but whether the free plan's key
    # actually returns data from /calendar/economic specifically hasn't
    # been confirmed (some providers gate calendar endpoints behind a paid
    # plan even with free basic quotes) -- set a real key and check the
    # engine's own live log line on first real call to find out.
    finnhub_api_key: Optional[str] = None
    # Powers E19 Global Liquidity's Fed balance sheet/M2/real-yield reads
    # (see core.data_providers.fred) -- None by default, same graceful-no-op
    # convention as alpha_vantage_api_key/finnhub_api_key above. Verified
    # live this session: an unauthenticated request to FRED's real API
    # returns a real HTTP 400 requiring "a 32 character alpha-numeric
    # lower-case string" -- a real, free, self-registered key
    # (https://fred.stlouisfed.org/docs/api/api_key.html) is required for
    # every call, no partial/anonymous access exists.
    fred_api_key: Optional[str] = None
    # Powers E13 Derivatives' NIFTY50/BANKNIFTY option-chain read (see
    # core.data_providers.kite_option_chain) -- added 2026-08-21. None by
    # default, same graceful-no-op convention as the other optional keys
    # above: analyze() reports an honest "not configured" gap rather than
    # fabricating an index options snapshot. Kite Connect access tokens
    # expire daily and must be regenerated through Zerodha's own login
    # flow (no TOTP/headless automation exists or is officially
    # supported) -- kite_access_token is expected to be refreshed by an
    # external, human-authorized process, not by this platform itself.
    # This module is read-only market data (instruments/quotes) -- it
    # never places, modifies, or cancels an order, matching Rule 5 (no
    # execution engine).
    kite_api_key: Optional[str] = None
    kite_access_token: Optional[str] = None
    # NSE has no free, real-time INR risk-free-rate feed wired into this
    # platform -- this static default (a round-number approximation of a
    # recent short-tenor Indian T-bill/repo-adjacent yield) is used only
    # as the Black-Scholes risk-free-rate input for index-option IV/greeks,
    # same "documented convention, not fabricated precision" category as
    # e13_derivatives' crypto risk_free_rate=0.0 default. Override in .env
    # with a current real rate for anything beyond casual/dev use.
    kite_risk_free_rate: float = 0.065

    # Execution mode: research | paper | semi_automated
    execution_mode: str = "research"

    @property
    def database_url(self) -> str:
        """Sync PostgreSQL connection URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def async_database_url(self) -> str:
        """Async PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Redis connection URL."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
