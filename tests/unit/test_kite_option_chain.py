"""
Module: test_kite_option_chain.py
Description: Unit tests for core/data_providers/kite_option_chain.py --
    see that module's docstring for provenance and its honest live-
    untested-HTTP-layer caveat. These tests cover everything that IS
    fully verifiable without a live Kite Connect account: underlying-
    symbol mapping (the exact gap both audited reference repos left
    unfilled for NIFTY/BANKNIFTY), instrument-dump filtering, and option-
    chain assembly including real IV/Greeks computation from synthetic
    quote data.
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from project_titan_x.core.data_providers.kite_option_chain import (
    KiteConnectClient,
    KiteNotConfigured,
    OptionChainRow,
    assemble_option_chain,
    classify_moneyness,
    filter_option_instruments,
    find_atm_strike,
    list_available_expiries,
    max_pain_strike,
    put_call_ratio,
    underlying_quote_symbol,
)
from project_titan_x.engines.e13_derivatives.black_scholes import price_and_greeks


def test_underlying_quote_symbol_maps_nifty_and_banknifty():
    """The exact gap both audited repos (express-option-chain,
    kite-option-chain) left unfilled -- neither resolves a real Kite
    quote symbol for NIFTY/BANKNIFTY at all."""
    assert underlying_quote_symbol("NIFTY50") == "NSE:NIFTY 50"
    assert underlying_quote_symbol("NIFTY") == "NSE:NIFTY 50"
    assert underlying_quote_symbol("BANKNIFTY") == "NSE:NIFTY BANK"
    assert underlying_quote_symbol("nifty50") == "NSE:NIFTY 50"  # case-insensitive


def test_underlying_quote_symbol_none_for_unsupported():
    assert underlying_quote_symbol("RELIANCE") is None


def _synthetic_nfo_instruments() -> pd.DataFrame:
    return pd.DataFrame([
        {"tradingsymbol": "NIFTY24AUG18000CE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY24AUG18000PE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "PE"},
        {"tradingsymbol": "NIFTY24AUG18100CE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18100.0, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY24SEP18000CE", "name": "NIFTY", "expiry": "2026-09-24", "strike": 18000.0, "instrument_type": "CE"},  # different expiry -- must be excluded
        {"tradingsymbol": "NIFTY24AUG18000FUT", "name": "NIFTY", "expiry": "2026-08-27", "strike": 0.0, "instrument_type": "FUT"},  # future, not an option -- must be excluded
        {"tradingsymbol": "BANKNIFTY24AUG40000CE", "name": "BANKNIFTY", "expiry": "2026-08-27", "strike": 40000.0, "instrument_type": "CE"},  # different underlying -- must be excluded
    ])


def test_filter_option_instruments_keeps_only_matching_underlying_expiry_and_option_type():
    instruments = _synthetic_nfo_instruments()
    result = filter_option_instruments(instruments, "NIFTY50", date(2026, 8, 27))
    assert set(result["tradingsymbol"]) == {"NIFTY24AUG18000CE", "NIFTY24AUG18000PE", "NIFTY24AUG18100CE"}


def test_filter_option_instruments_empty_for_unsupported_underlying():
    instruments = _synthetic_nfo_instruments()
    result = filter_option_instruments(instruments, "RELIANCE", date(2026, 8, 27))
    assert result.empty


def test_assemble_option_chain_computes_real_iv_and_greeks_from_synthetic_ltp():
    """Build a chain from a single strike whose CE leg's quoted LTP is
    generated FROM a known Black-Scholes price at a known vol -- the
    assembled row's ce_iv must recover that known vol, proving the
    IV-inversion -> Greeks pipeline is wired correctly end to end. This
    is the exact capability (IV + Greeks on an Indian index option) that
    neither audited reference repo had any coverage of at all."""
    expiry = date(2026, 8, 27)
    as_of = datetime(2026, 8, 20, tzinfo=timezone.utc)
    time_to_expiry_years = (datetime.combine(expiry, datetime.min.time(), tzinfo=timezone.utc) - as_of).total_seconds() / (365.0 * 86400.0)
    spot = 18050.0
    known_vol = 0.14
    theo = price_and_greeks(spot=spot, strike=18000.0, time_to_expiry_years=time_to_expiry_years, volatility=known_vol, option_type="call", risk_free_rate=0.065)

    instruments = pd.DataFrame([
        {"tradingsymbol": "NIFTY24AUG18000CE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY24AUG18000PE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "PE"},
    ])
    quotes = {
        "NFO:NIFTY24AUG18000CE": {"last_price": theo.price, "oi": 125000},
        "NFO:NIFTY24AUG18000PE": {"last_price": 0.0, "oi": 0},  # no quote/zero LTP -- must not crash, must produce no IV
    }

    snapshot = assemble_option_chain(
        option_instruments=instruments, quotes=quotes, underlying_symbol="NIFTY50",
        expiry=expiry, spot_price=spot, risk_free_rate=0.065, as_of=as_of,
    )

    assert len(snapshot.rows) == 1
    row = snapshot.rows[0]
    assert row.strike == 18000.0
    assert row.ce_ltp == theo.price
    assert row.ce_oi == 125000
    assert row.ce_iv is not None
    assert abs(row.ce_iv - known_vol) < 1e-3
    assert row.ce_greeks is not None
    assert abs(row.ce_greeks["delta"] - theo.delta) < 1e-3
    assert row.pe_ltp == 0.0
    assert row.pe_iv is None  # zero LTP -- correctly no fabricated IV
    assert row.pe_greeks is None


def test_assemble_option_chain_sets_volume_and_moneyness():
    """docs/UPGRADE_BRIEF.md Phase 10: volume and ATM/ITM/OTM
    classification, both confirmed absent before this pass. Spot=18050
    with strikes 18000/18100 -- 18000 is closer, so it's ATM; 18100 is
    OTM for the call (spot < strike) and ITM for the put (spot < strike)."""
    expiry = date(2026, 8, 27)
    as_of = datetime(2026, 8, 20, tzinfo=timezone.utc)
    instruments = pd.DataFrame([
        {"tradingsymbol": "NIFTY24AUG18000CE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY24AUG18000PE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "PE"},
        {"tradingsymbol": "NIFTY24AUG18100CE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18100.0, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY24AUG18100PE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18100.0, "instrument_type": "PE"},
    ])
    quotes = {
        "NFO:NIFTY24AUG18000CE": {"last_price": 120.0, "oi": 1000, "volume": 5000},
        "NFO:NIFTY24AUG18000PE": {"last_price": 80.0, "oi": 800, "volume": 4000},
        "NFO:NIFTY24AUG18100CE": {"last_price": 60.0, "oi": 600, "volume": 3000},
        "NFO:NIFTY24AUG18100PE": {"last_price": 140.0, "oi": 1200, "volume": 6000},
    }
    snapshot = assemble_option_chain(
        option_instruments=instruments, quotes=quotes, underlying_symbol="NIFTY50",
        expiry=expiry, spot_price=18050.0, risk_free_rate=0.065, as_of=as_of,
    )
    row_18000 = next(r for r in snapshot.rows if r.strike == 18000.0)
    row_18100 = next(r for r in snapshot.rows if r.strike == 18100.0)
    assert row_18000.ce_volume == 5000
    assert row_18000.pe_volume == 4000
    assert row_18000.ce_moneyness == "ATM"
    assert row_18000.pe_moneyness == "ATM"
    assert row_18100.ce_moneyness == "OTM"  # spot 18050 < strike 18100 -- a call is OTM
    assert row_18100.pe_moneyness == "ITM"  # spot 18050 < strike 18100 -- a put is ITM


def test_assemble_option_chain_attaches_chain_level_aggregates():
    """atm_strike/pcr_oi/pcr_volume/max_pain must be computed and attached
    to the snapshot itself, not left for every caller to re-derive."""
    expiry = date(2026, 8, 27)
    as_of = datetime(2026, 8, 20, tzinfo=timezone.utc)
    instruments = pd.DataFrame([
        {"tradingsymbol": "NIFTY24AUG18000CE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY24AUG18000PE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "PE"},
    ])
    quotes = {
        "NFO:NIFTY24AUG18000CE": {"last_price": 120.0, "oi": 1000, "volume": 5000},
        "NFO:NIFTY24AUG18000PE": {"last_price": 80.0, "oi": 2000, "volume": 3000},
    }
    snapshot = assemble_option_chain(
        option_instruments=instruments, quotes=quotes, underlying_symbol="NIFTY50",
        expiry=expiry, spot_price=18010.0, risk_free_rate=0.065, as_of=as_of,
    )
    assert snapshot.atm_strike == 18000.0
    assert snapshot.pcr_oi == pytest.approx(2.0)
    assert snapshot.pcr_volume == pytest.approx(3000 / 5000)
    assert snapshot.max_pain == 18000.0  # the only strike with any OI at all


def test_find_atm_strike_picks_the_closest_listed_strike():
    rows = [OptionChainRow(strike=k) for k in (17900.0, 18000.0, 18100.0, 18200.0)]
    assert find_atm_strike(rows, 18050.0) == 18000.0
    assert find_atm_strike(rows, 18060.0) == 18100.0
    assert find_atm_strike([], 18050.0) is None


def test_classify_moneyness_call_and_put_are_mirror_images():
    assert classify_moneyness(18000.0, 18050.0, atm_strike=17000.0, option_type="CE") == "ITM"  # spot above strike
    assert classify_moneyness(18000.0, 17950.0, atm_strike=17000.0, option_type="CE") == "OTM"
    assert classify_moneyness(18000.0, 18050.0, atm_strike=17000.0, option_type="PE") == "OTM"
    assert classify_moneyness(18000.0, 17950.0, atm_strike=17000.0, option_type="PE") == "ITM"
    assert classify_moneyness(18000.0, 18050.0, atm_strike=18000.0, option_type="CE") == "ATM"


def test_put_call_ratio_matches_hand_computed_value():
    rows = [
        OptionChainRow(strike=18000.0, ce_oi=1000, pe_oi=800, ce_volume=5000, pe_volume=4000),
        OptionChainRow(strike=18100.0, ce_oi=600, pe_oi=1200, ce_volume=3000, pe_volume=6000),
    ]
    assert put_call_ratio(rows, by="oi") == pytest.approx((800 + 1200) / (1000 + 600))
    assert put_call_ratio(rows, by="volume") == pytest.approx((4000 + 6000) / (5000 + 3000))


def test_put_call_ratio_none_when_no_call_oi():
    rows = [OptionChainRow(strike=18000.0, ce_oi=None, pe_oi=800)]
    assert put_call_ratio(rows, by="oi") is None


def test_max_pain_strike_is_the_strike_minimizing_writer_payout():
    """Constructed so the answer is unambiguous: almost all OI sits at
    18000 on both legs, so settling AT 18000 (zero intrinsic value paid
    on the dominant OI) must minimize total payout versus settling
    anywhere else."""
    rows = [
        OptionChainRow(strike=17900.0, ce_oi=10, pe_oi=10),
        OptionChainRow(strike=18000.0, ce_oi=100_000, pe_oi=100_000),
        OptionChainRow(strike=18100.0, ce_oi=10, pe_oi=10),
    ]
    assert max_pain_strike(rows) == 18000.0


def test_max_pain_strike_none_without_any_oi():
    rows = [OptionChainRow(strike=18000.0), OptionChainRow(strike=18100.0)]
    assert max_pain_strike(rows) is None


def test_assemble_option_chain_missing_quote_leg_gets_none_fields_not_a_crash():
    instruments = pd.DataFrame([
        {"tradingsymbol": "NIFTY24AUG18000CE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "CE"},
    ])
    snapshot = assemble_option_chain(
        option_instruments=instruments, quotes={},  # no quote data at all for this leg
        underlying_symbol="NIFTY50", expiry=date(2026, 8, 27), spot_price=18050.0, risk_free_rate=0.065,
        as_of=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    assert len(snapshot.rows) == 1
    assert snapshot.rows[0].ce_ltp is None
    assert snapshot.rows[0].ce_iv is None


def test_assemble_option_chain_expired_expiry_produces_no_iv_and_a_note():
    instruments = pd.DataFrame([
        {"tradingsymbol": "NIFTY24AUG18000CE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "CE"},
    ])
    snapshot = assemble_option_chain(
        option_instruments=instruments, quotes={"NFO:NIFTY24AUG18000CE": {"last_price": 50.0, "oi": 100}},
        underlying_symbol="NIFTY50", expiry=date(2026, 8, 27), spot_price=18050.0, risk_free_rate=0.065,
        as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),  # after the expiry date
    )
    assert snapshot.rows[0].ce_iv is None
    assert any("already passed" in n for n in snapshot.notes)


def test_list_available_expiries_sorted_nearest_first_and_excludes_past():
    instruments = pd.DataFrame([
        {"tradingsymbol": "NIFTY24SEP18000CE", "name": "NIFTY", "expiry": "2026-09-24", "strike": 18000.0, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY24AUG18000CE", "name": "NIFTY", "expiry": "2026-08-27", "strike": 18000.0, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY24JUL18000CE", "name": "NIFTY", "expiry": "2026-07-30", "strike": 18000.0, "instrument_type": "CE"},  # already expired relative to as_of
    ])
    result = list_available_expiries(instruments, "NIFTY50", as_of=date(2026, 8, 20))
    assert result == [date(2026, 8, 27), date(2026, 9, 24)]


def test_list_available_expiries_empty_for_unsupported_underlying():
    instruments = _synthetic_nfo_instruments()
    assert list_available_expiries(instruments, "RELIANCE", as_of=date(2026, 8, 20)) == []


def test_client_raises_not_configured_without_credentials():
    client = KiteConnectClient(api_key=None, access_token=None)
    assert client.is_configured is False
    with pytest.raises(KiteNotConfigured):
        client._headers()
