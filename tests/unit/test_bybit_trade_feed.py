"""
Module: test_bybit_trade_feed.py
Description: Unit tests for core/data_providers/bybit_trade_feed.py --
    message parsing and tick-to-bar aggregation, all against synthetic,
    hand-constructed messages (no live network needed; the real live
    connection is verified separately, see CLAUDE.md for that run's
    results, not something to depend on for a deterministic test suite).
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timezone

from project_titan_x.core.data_providers.bybit_trade_feed import (
    Tick,
    TickAggregator,
    parse_trade_message,
)


def test_parse_trade_message_extracts_real_field_names():
    msg = {
        "topic": "publicTrade.BTCUSDT",
        "type": "snapshot",
        "ts": 1700000000000,
        "data": [
            {"T": 1700000000123, "s": "BTCUSDT", "S": "Buy", "v": "0.015", "p": "43250.5", "i": "abc123"},
            {"T": 1700000000456, "s": "BTCUSDT", "S": "Sell", "v": "0.02", "p": "43248.0", "i": "def456"},
        ],
    }
    ticks = parse_trade_message(msg)
    assert len(ticks) == 2
    assert ticks[0].symbol == "BTCUSD"  # mapped from Bybit's BTCUSDT back to platform canonical
    assert ticks[0].side == "buy"
    assert ticks[0].price == 43250.5
    assert ticks[0].size == 0.015
    assert ticks[0].timestamp == datetime.fromtimestamp(1700000000.123, tz=timezone.utc)
    assert ticks[1].side == "sell"


def test_parse_trade_message_ignores_non_trade_messages():
    assert parse_trade_message({"success": True, "ret_msg": "pong", "op": "ping"}) == []
    assert parse_trade_message({"op": "subscribe", "success": True}) == []
    assert parse_trade_message({"topic": "orderbook.1.BTCUSDT", "data": {}}) == []


def test_parse_trade_message_skips_malformed_entry_without_raising():
    msg = {
        "topic": "publicTrade.ETHUSDT",
        "data": [
            {"T": 1700000000000, "s": "ETHUSDT", "S": "Buy", "v": "1.0", "p": "2500.0", "i": "1"},
            {"T": "not-a-number", "s": "ETHUSDT", "S": "Buy", "v": "1.0", "p": "2500.0", "i": "2"},
        ],
    }
    ticks = parse_trade_message(msg)
    assert len(ticks) == 1  # malformed second entry skipped, first still parsed
    assert ticks[0].symbol == "ETHUSD"


def _tick(ts_epoch: float, symbol: str, price: float, size: float, side: str) -> Tick:
    return Tick(
        timestamp=datetime.fromtimestamp(ts_epoch, tz=timezone.utc),
        symbol=symbol, price=price, size=size, side=side, trade_id="x",
    )


def test_tick_aggregator_builds_ohlc_and_true_delta_within_one_bucket():
    agg = TickAggregator(bar_seconds=60)
    base = 1700000000.0  # arbitrary bucket-aligned-ish start
    agg.add_tick(_tick(base + 1, "BTCUSD", 100.0, 1.0, "buy"))
    agg.add_tick(_tick(base + 10, "BTCUSD", 105.0, 2.0, "buy"))
    flushed = agg.add_tick(_tick(base + 20, "BTCUSD", 98.0, 0.5, "sell"))
    assert flushed is None  # still within the same 60s bucket

    open_bar = agg._open_bars["BTCUSD"]
    assert open_bar.open == 100.0
    assert open_bar.high == 105.0
    assert open_bar.low == 98.0
    assert open_bar.close == 98.0
    assert open_bar.buy_volume == 3.0
    assert open_bar.sell_volume == 0.5
    assert open_bar.delta == 2.5  # TRUE delta -- real buy minus real sell, no CLV approximation
    assert open_bar.trade_count == 3


def test_tick_aggregator_flushes_bar_on_new_bucket():
    agg = TickAggregator(bar_seconds=60)
    base = agg._bucket_start(datetime.fromtimestamp(1700000000.0, tz=timezone.utc)).timestamp()
    agg.add_tick(_tick(base + 1, "BTCUSD", 100.0, 1.0, "buy"))
    flushed = agg.add_tick(_tick(base + 61, "BTCUSD", 101.0, 1.0, "sell"))  # next bucket
    assert flushed is not None
    assert flushed.close == 100.0  # the completed (first) bar
    assert "BTCUSD" in agg.completed_bars
    assert len(agg.completed_bars["BTCUSD"]) == 1


def test_tick_aggregator_flush_all_captures_partial_open_bars():
    agg = TickAggregator(bar_seconds=60)
    agg.add_tick(_tick(1700000000.0, "BTCUSD", 100.0, 1.0, "buy"))
    agg.add_tick(_tick(1700000010.0, "ETHUSD", 2000.0, 2.0, "sell"))
    assert agg.completed_bars == {}  # nothing flushed yet, both bars still open

    flushed = agg.flush_all()
    assert len(flushed) == 2
    assert len(agg.completed_bars["BTCUSD"]) == 1
    assert len(agg.completed_bars["ETHUSD"]) == 1
    assert agg._open_bars == {}  # cleared after flush


def test_tick_aggregator_keeps_symbols_independent():
    agg = TickAggregator(bar_seconds=60)
    base = 1700000000.0
    agg.add_tick(_tick(base, "BTCUSD", 100.0, 1.0, "buy"))
    agg.add_tick(_tick(base, "ETHUSD", 2000.0, 5.0, "sell"))
    btc = agg._open_bars["BTCUSD"]
    eth = agg._open_bars["ETHUSD"]
    assert btc.buy_volume == 1.0 and btc.sell_volume == 0.0
    assert eth.buy_volume == 0.0 and eth.sell_volume == 5.0
