"""
Module: test_black_scholes.py
Description: Unit tests for engines/e13_derivatives/black_scholes.py. No
    dedicated test file existed before -- added 2026-08-21 alongside the
    new implied_volatility() inversion (needed by the new Kite Connect
    option-chain provider, which only has a real traded PRICE, not a
    broker-published IV like Deribit's mark_iv). Covers implied_volatility
    thoroughly (new code); price_and_greeks gets a light round-trip
    sanity check via the inversion tests rather than a full retroactive
    suite, since it's pre-existing and already exercised indirectly by
    e13_derivatives' own real Deribit greeks cross-check.
Author: Shantanu Waykar
Version: 1.0.0
"""

from project_titan_x.engines.e13_derivatives.black_scholes import implied_volatility, price_and_greeks


def test_implied_volatility_round_trips_a_known_price():
    """Price a call at a known vol, then invert that same price back to
    volatility -- must recover the original vol to within a tight
    tolerance (Brent's method on a smooth, monotonic function)."""
    known_vol = 0.35
    priced = price_and_greeks(spot=100.0, strike=100.0, time_to_expiry_years=0.25, volatility=known_vol, option_type="call")
    recovered = implied_volatility(
        market_price=priced.price, spot=100.0, strike=100.0, time_to_expiry_years=0.25, option_type="call",
    )
    assert recovered is not None
    assert abs(recovered - known_vol) < 1e-4


def test_implied_volatility_round_trips_a_put_with_nonzero_rate():
    known_vol = 0.22
    priced = price_and_greeks(
        spot=18500.0, strike=18000.0, time_to_expiry_years=7 / 365, volatility=known_vol,
        option_type="put", risk_free_rate=0.065,
    )
    recovered = implied_volatility(
        market_price=priced.price, spot=18500.0, strike=18000.0, time_to_expiry_years=7 / 365,
        option_type="put", risk_free_rate=0.065,
    )
    assert recovered is not None
    assert abs(recovered - known_vol) < 1e-4


def test_implied_volatility_returns_none_for_price_below_intrinsic_no_root_possible():
    """A market price below the option's own intrinsic value can't be
    matched by ANY volatility (price is monotonically increasing in vol,
    bounded below by intrinsic value as vol->0) -- must return None, not
    an out-of-range or fabricated number."""
    result = implied_volatility(
        market_price=0.01, spot=100.0, strike=50.0, time_to_expiry_years=0.5, option_type="call",
    )
    assert result is None


def test_implied_volatility_returns_none_for_non_positive_inputs():
    assert implied_volatility(market_price=5.0, spot=0.0, strike=100.0, time_to_expiry_years=0.5, option_type="call") is None
    assert implied_volatility(market_price=5.0, spot=100.0, strike=100.0, time_to_expiry_years=0.0, option_type="call") is None
    assert implied_volatility(market_price=0.0, spot=100.0, strike=100.0, time_to_expiry_years=0.5, option_type="call") is None


def test_implied_volatility_rejects_invalid_option_type():
    import pytest

    with pytest.raises(ValueError):
        implied_volatility(market_price=5.0, spot=100.0, strike=100.0, time_to_expiry_years=0.5, option_type="straddle")
