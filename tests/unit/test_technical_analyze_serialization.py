"""Unit tests for the Phase 12 market-structure/ICT-SMC serialization
helpers added to GET /api/v1/technical/analyze (api/main.py).

These fields (order blocks, FVGs, liquidity sweeps, Wyckoff, harmonics,
RSI divergence) were already computed by TechnicalSnapshot before this
change -- this only tests that the new dict-builders serialize each real
dataclass type correctly (numpy scalar -> native type, Enum -> .value)."""

import numpy as np

from project_titan_x.api.main import (
    _fvg_dict,
    _harmonic_pattern_dict,
    _liquidity_sweep_dict,
    _order_block_dict,
    _rsi_divergence_dict,
    _structure_event_dict,
    _trading_range_dict,
    _volume_profile_dict,
    _wyckoff_event_dict,
)
from project_titan_x.engines.e07_technical.divergence import DivergenceKind, RSIDivergence
from project_titan_x.engines.e07_technical.harmonics import HarmonicPattern
from project_titan_x.engines.e07_technical.smart_money import (
    FairValueGap,
    LiquiditySweep,
    OrderBlock,
    StructureEvent,
    StructureEventKind,
)
from project_titan_x.engines.e07_technical.volume_profile import VolumeProfile
from project_titan_x.engines.e07_technical.wyckoff import TradingRange, WyckoffEvent


def test_structure_event_dict_converts_numpy_and_enum():
    e = StructureEvent(index=np.int64(5), kind=StructureEventKind.BOS_BULLISH, broken_level=np.float64(1.2345))
    d = _structure_event_dict(e)
    assert d == {"index": 5, "kind": "bos_bullish", "broken_level": 1.2345}
    assert isinstance(d["index"], int) and isinstance(d["broken_level"], float)


def test_liquidity_sweep_dict():
    s = LiquiditySweep(index=3, direction="bullish", swept_level=100.0, wick_price=99.5)
    assert _liquidity_sweep_dict(s) == {"index": 3, "direction": "bullish", "swept_level": 100.0, "wick_price": 99.5}


def test_order_block_dict_handles_none_mitigated_index():
    b = OrderBlock(index=1, direction="bearish", open=10, high=11, low=9, close=9.5)
    d = _order_block_dict(b)
    assert d["breaker"] is False
    assert d["mitigated_index"] is None


def test_order_block_dict_with_mitigation():
    b = OrderBlock(index=1, direction="bearish", open=10, high=11, low=9, close=9.5, breaker=True, mitigated_index=7)
    d = _order_block_dict(b)
    assert d["breaker"] is True
    assert d["mitigated_index"] == 7


def test_fvg_dict():
    g = FairValueGap(index=2, direction="bullish", gap_top=105.0, gap_bottom=103.0, filled=False)
    assert _fvg_dict(g) == {"index": 2, "direction": "bullish", "gap_top": 105.0, "gap_bottom": 103.0, "filled": False}


def test_volume_profile_dict_none_passthrough():
    assert _volume_profile_dict(None) is None


def test_volume_profile_dict_real_values():
    v = VolumeProfile(
        poc_price=100.0, value_area_high=105.0, value_area_low=95.0, value_area_volume_pct=68.5,
        high_volume_nodes=[100.0, 101.0], low_volume_nodes=[98.0], bin_prices=[], bin_volumes=[],
    )
    d = _volume_profile_dict(v)
    assert d["poc_price"] == 100.0
    assert d["high_volume_nodes"] == [100.0, 101.0]
    assert "bin_prices" not in d  # charting/debug-only field, not surfaced via the API


def test_trading_range_dict_none_passthrough():
    assert _trading_range_dict(None) is None


def test_trading_range_dict_real_values():
    r = TradingRange(support=90.0, resistance=110.0, start_index=0, end_index=50)
    assert _trading_range_dict(r) == {"support": 90.0, "resistance": 110.0, "start_index": 0, "end_index": 50}


def test_wyckoff_event_dict():
    e = WyckoffEvent(index=4, kind="spring", level=90.0, wick_price=88.5)
    assert _wyckoff_event_dict(e) == {"index": 4, "kind": "spring", "level": 90.0, "wick_price": 88.5}


def test_harmonic_pattern_dict():
    p = HarmonicPattern(
        name="Gartley", direction="bullish", x_index=0, a_index=1, b_index=2, c_index=3, d_index=4,
        x_price=1, a_price=2, b_price=3, c_price=4, d_price=5,
        ab_xa_ratio=0.618, bc_ab_ratio=0.5, cd_bc_ratio=1.27, ad_xa_ratio=0.786,
    )
    d = _harmonic_pattern_dict(p)
    assert d["name"] == "Gartley"
    assert d["ab_xa_ratio"] == 0.618


def test_rsi_divergence_dict_converts_enum():
    d_obj = RSIDivergence(
        first_index=1, second_index=5, kind=DivergenceKind.REGULAR_BULLISH,
        price_first=100.0, price_second=95.0, rsi_first=25.0, rsi_second=30.0,
    )
    d = _rsi_divergence_dict(d_obj)
    assert d["kind"] == "regular_bullish"
    assert d["price_first"] == 100.0
