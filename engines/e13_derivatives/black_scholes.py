"""
Module: black_scholes.py
Description: Black-Scholes-Merton European option pricing and Greeks --
    added 2026-08-02. This engine previously only ever READ greeks
    Deribit had already computed (real, but a hard dependency on Deribit
    publishing them for exactly the strike/expiry Deribit happens to
    list) -- there was no independent way to price a hypothetical
    strike/expiry/vol scenario, or to sanity-check Deribit's own published
    greeks against the standard closed-form model literally every options
    textbook in the corpus's 121K-chunk Options topic builds on.

    Standard closed-form formulas (Black & Scholes 1973, Merton 1973),
    not fitted/calibrated -- same "exact well-established result, not a
    parameter" category as e31_portfolio_construction's Markowitz/Black-
    Litterman formulas.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from scipy.optimize import brentq
from scipy.stats import norm


@dataclass
class BlackScholesGreeks:
    option_type: str  # "call" | "put"
    price: float
    delta: float
    gamma: float
    theta: float  # per calendar day
    vega: float  # per 1 vol point (1% change in IV)
    rho: float  # per 1 percentage point change in the risk-free rate


def price_and_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    option_type: str,
    risk_free_rate: float = 0.0,
) -> BlackScholesGreeks:
    """
    Black-Scholes-Merton price and Greeks for a European option.

    Args:
        spot: Current underlying price.
        strike: Option strike price.
        time_to_expiry_years: Time to expiry in years (e.g. 30/365 for 30 days).
        volatility: Annualized implied volatility as a decimal (e.g. 0.65 for 65%).
        option_type: "call" or "put".
        risk_free_rate: Annualized risk-free rate as a decimal. Defaults to 0.0 --
            a common simplification for crypto options (Deribit itself prices
            with a near-zero/zero rate convention), but callers pricing
            traditional-asset options should pass a real rate.

    Returns:
        BlackScholesGreeks with the theoretical price and all five Greeks.
    """
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if time_to_expiry_years <= 0:
        raise ValueError("time_to_expiry_years must be positive (option has already expired)")
    if volatility <= 0:
        raise ValueError("volatility must be positive")
    if option_type not in ("call", "put"):
        raise ValueError("option_type must be 'call' or 'put'")

    s, k, t, sigma, r = spot, strike, time_to_expiry_years, volatility, risk_free_rate
    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    pdf_d1 = norm.pdf(d1)
    discount = math.exp(-r * t)

    # Gamma and Vega are identical for calls and puts (put-call symmetry
    # of the second/vol derivatives); only price/delta/theta/rho differ
    # by sign/term between the two.
    gamma = pdf_d1 / (s * sigma * sqrt_t)
    vega = s * pdf_d1 * sqrt_t / 100.0  # per 1 vol point, not per unit (100%) of vol

    if option_type == "call":
        price = s * norm.cdf(d1) - k * discount * norm.cdf(d2)
        delta = norm.cdf(d1)
        theta = (-s * pdf_d1 * sigma / (2 * sqrt_t) - r * k * discount * norm.cdf(d2)) / 365.0
        rho = (k * t * discount * norm.cdf(d2)) / 100.0
    else:
        price = k * discount * norm.cdf(-d2) - s * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1.0
        theta = (-s * pdf_d1 * sigma / (2 * sqrt_t) + r * k * discount * norm.cdf(-d2)) / 365.0
        rho = (-k * t * discount * norm.cdf(-d2)) / 100.0

    return BlackScholesGreeks(
        option_type=option_type,
        price=round(price, 6),
        delta=round(delta, 6),
        gamma=round(gamma, 8),
        theta=round(theta, 6),
        vega=round(vega, 6),
        rho=round(rho, 6),
    )


def implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    option_type: str,
    risk_free_rate: float = 0.0,
) -> Optional[float]:
    """
    Inverts price_and_greeks() for volatility -- added 2026-08-21 for the
    new Kite Connect option-chain provider (core.data_providers.
    kite_option_chain), where the real market data available is a traded
    PRICE, not a broker-published IV (unlike Deribit's mark_iv, which
    this engine's existing crypto path reads directly, never needing
    this inversion).

    Root-finds via Brent's method (scipy.optimize.brentq -- already a
    scipy dependency via norm above) on volatility in [0.01%, 500%]
    annualized, wide enough to bracket any real market IV without
    silently clamping a genuine extreme reading (e.g. a deep-OTM option
    near expiry can legitimately imply IV well above 100%).

    Returns None -- never a fabricated guess -- if market_price can't be
    bracketed by any volatility in that range (e.g. a stale/crossed quote
    priced below intrinsic value) or if the inputs are otherwise
    non-priceable (non-positive spot/strike/price/time).
    """
    if spot <= 0 or strike <= 0 or time_to_expiry_years <= 0 or market_price <= 0:
        return None
    if option_type not in ("call", "put"):
        raise ValueError("option_type must be 'call' or 'put'")

    def _price_diff(vol: float) -> float:
        return price_and_greeks(spot, strike, time_to_expiry_years, vol, option_type, risk_free_rate).price - market_price

    lo, hi = 1e-4, 5.0
    try:
        if _price_diff(lo) * _price_diff(hi) > 0:
            return None
        return round(brentq(_price_diff, lo, hi, xtol=1e-6), 6)
    except (ValueError, RuntimeError):
        return None
