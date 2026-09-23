"""
Module: engine.py
Description: Engine 79 -- Portfolio Simulation. See MASTER_PROMPT.md's
    "PROMPT 5" section: the one genuinely new angle versus E26 Backtesting
    (historical replay) and E28 Stress Testing (historical crisis replay)
    is a FORWARD Monte Carlo from TODAY's actual real open positions --
    "before executing, simulate the portfolio 1 week/1 month/3 months/
    1 year forward."

    Real technique, not fabricated: historical-bootstrap Monte Carlo --
    for each real position, resample actual historical daily returns
    (with replacement) to build many random forward paths, exactly the
    same "describe the real spread of what has actually happened before"
    philosophy e23_forecasting's own module docstring already commits to
    (never a fabricated parametric distribution). Position sizing (risk
    amount per position) is caller-supplied real data (e.g. from
    e32_capital_allocation's own real allocation output), never invented.

    Rule 3: no calibration script -- real historical resampling, no
    fitted parameters (same "no" category as e26_backtesting's own
    monte_carlo() method, which this engine's per-position technique
    mirrors at the portfolio level).
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from project_titan_x.core.config import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

DEFAULT_N_SIMULATIONS = 1000
MIN_HISTORY_DAYS = 120


@dataclass
class PositionInput:
    symbol: str
    direction: str  # LONG | SHORT
    entry: float
    stop_loss: float
    allocated_capital: float


@dataclass
class PortfolioSimulationReport:
    generated_at: datetime
    horizon_days: int
    n_simulations: int
    n_positions: int
    total_capital: float
    percentile_outcomes: dict[str, float]  # {"p5": ..., "p50": ..., "p95": ...} final portfolio value
    prob_any_stop_breached_pct: float
    prob_portfolio_loss_pct: float
    data_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(), "horizon_days": self.horizon_days,
            "n_simulations": self.n_simulations, "n_positions": self.n_positions,
            "total_capital": round(self.total_capital, 2),
            "percentile_outcomes": {k: round(v, 2) for k, v in self.percentile_outcomes.items()},
            "prob_any_stop_breached_pct": round(self.prob_any_stop_breached_pct, 1),
            "prob_portfolio_loss_pct": round(self.prob_portfolio_loss_pct, 1),
            "data_gaps": self.data_gaps,
            "disclaimer": "Historical-bootstrap Monte Carlo (real resampled daily returns), not a deterministic forecast.",
        }


class PortfolioSimulationEngine(BaseEngine):
    """Portfolio Simulation Engine (#79) -- forward Monte Carlo from
    TODAY's real open positions, via historical-bootstrap resampling of
    each position's own real daily returns."""

    engine_id = "e79_portfolio_simulation"
    engine_name = "Portfolio Simulation Engine"
    version = "1.0.0"

    def __init__(self, market_data_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._market_data_engine = market_data_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Portfolio Simulation Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def simulate_forward(
        self, positions: list[PositionInput], horizon_days: int = 20,
        n_simulations: int = DEFAULT_N_SIMULATIONS, years: int = 10,
    ) -> EngineResult:
        if self._market_data_engine is None:
            return EngineResult(success=False, message="No market_data_engine injected")
        if not positions:
            return EngineResult(success=False, message="No positions supplied")
        try:
            self._set_status(EngineStatus.RUNNING)
            gaps: list[str] = []
            per_position_returns: list[tuple[PositionInput, np.ndarray]] = []
            for pos in positions:
                asset = get_asset(pos.symbol)
                yahoo_symbol = asset.yahoo_symbol if asset else pos.symbol
                fetch = self._market_data_engine.fetch_ohlcv(yahoo_symbol, "1d", years=years)
                if not fetch.success or fetch.data is None or len(fetch.data) < MIN_HISTORY_DAYS:
                    gaps.append(f"{pos.symbol}: insufficient real history, excluded from simulation")
                    continue
                returns = fetch.data["close"].pct_change().dropna().to_numpy()
                per_position_returns.append((pos, returns))

            if not per_position_returns:
                return EngineResult(success=False, message="No position had enough real history to simulate")

            total_capital = sum(p.allocated_capital for p, _ in per_position_returns)
            rng = np.random.default_rng()
            final_values = np.zeros(n_simulations)
            any_stop_breached = np.zeros(n_simulations, dtype=bool)

            for pos, returns in per_position_returns:
                sampled = rng.choice(returns, size=(n_simulations, horizon_days), replace=True)
                if pos.direction.upper() == "SHORT":
                    sampled = -sampled
                path_multiplier = np.cumprod(1.0 + sampled, axis=1)
                position_values = pos.allocated_capital * path_multiplier[:, -1]
                final_values += position_values

                risk_fraction = abs(pos.entry - pos.stop_loss) / pos.entry if pos.entry else 0.0
                min_multiplier_along_path = np.min(path_multiplier, axis=1)
                breached = min_multiplier_along_path <= (1.0 - risk_fraction)
                any_stop_breached |= breached

            percentiles = {f"p{p}": float(np.percentile(final_values, p)) for p in (5, 25, 50, 75, 95)}
            prob_stop = float(np.mean(any_stop_breached)) * 100.0
            prob_loss = float(np.mean(final_values < total_capital)) * 100.0

            report = PortfolioSimulationReport(
                generated_at=datetime.now(timezone.utc), horizon_days=horizon_days, n_simulations=n_simulations,
                n_positions=len(per_position_returns), total_capital=total_capital,
                percentile_outcomes=percentiles, prob_any_stop_breached_pct=prob_stop,
                prob_portfolio_loss_pct=prob_loss, data_gaps=gaps,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=f"Simulated {len(per_position_returns)} position(s) forward {horizon_days}d: median={percentiles['p50']:.2f}, P(loss)={prob_loss:.1f}%, P(any stop hit)={prob_stop:.1f}%",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("simulate_forward failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])
