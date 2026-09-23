"""
Module: test_market_data_engine.py
Description: Unit tests for Engine 02 (Market Data) -- data quality wiring,
    dataset catalog wiring, and the crypto/COT/sentiment data methods added
    for the institutional Market Data Acquisition Platform spec.
Author: Shantanu Waykar
Version: 1.0.0
"""

from pathlib import Path

import pandas as pd
import pytest

from project_titan_x.core.catalog import DatasetCatalog
from project_titan_x.engines.e02_market_data.engine import (
    MarketDataEngine,
    _ccxt_perpetual_market_symbol,
)
from project_titan_x.engines.e40_data_quality.engine import DataQualityEngine


@pytest.fixture
def engine(tmp_path) -> MarketDataEngine:
    e = MarketDataEngine(data_dir=tmp_path)
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


# ---- OHLCV caching (added 2026-08-21, see MarketDataEngine.fetch_ohlcv's
# own docstring for the real, measured scan-performance reasoning) ----

def test_ohlcv_cache_key_distinguishes_every_parameter(engine):
    """A cache key collision here would mean fetch_ohlcv could silently
    return data for the wrong symbol/timeframe/range -- a real
    correctness risk, not just a cache-efficiency one, so every distinct
    combination must produce a distinct key."""
    from datetime import datetime, timezone
    base = engine._ohlcv_cache_key("GOLD", "1d", None, None, 2)
    variants = [
        engine._ohlcv_cache_key("SILVER", "1d", None, None, 2),
        engine._ohlcv_cache_key("GOLD", "1h", None, None, 2),
        engine._ohlcv_cache_key("GOLD", "1d", None, None, 5),
        engine._ohlcv_cache_key("GOLD", "1d", datetime(2026, 1, 1, tzinfo=timezone.utc), None, 2),
        engine._ohlcv_cache_key("GOLD", "1d", None, datetime(2026, 1, 1, tzinfo=timezone.utc), 2),
    ]
    assert len({base, *variants}) == len(variants) + 1  # all distinct, no collisions


def test_ohlcv_serialize_deserialize_round_trip_preserves_tz_aware_timestamps(engine):
    """The exact bug class this format was chosen to avoid: a tz-aware
    datetime column must survive the round trip with its dtype/tz
    intact, not silently become tz-naive or a different tz."""
    from project_titan_x.engines.base import EngineResult

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-15 12:00:00", "2026-01-16 12:00:00"], utc=True),
        "open": [100.0, 101.0], "high": [102.0, 103.0], "low": [99.0, 100.0], "close": [101.0, 102.0],
        "volume": [1000, 1200],
    })
    original = EngineResult(success=True, data=df, message="fetched", metadata={"source": "yahoo_finance"})

    raw = engine._serialize_ohlcv_result(original)
    restored = engine._deserialize_ohlcv_result(raw)

    assert restored.success
    pd.testing.assert_frame_equal(restored.data, df)
    assert restored.metadata == {"source": "yahoo_finance"}
    assert "(cached)" in restored.message


def test_fetch_ohlcv_skips_real_fetch_on_cache_hit(engine, monkeypatch):
    """Core correctness/performance claim of this whole feature: a second
    call with identical parameters must return the cached result WITHOUT
    calling the real (network-hitting) _fetch_ohlcv_uncached again."""
    import project_titan_x.engines.e02_market_data.engine as md_module
    from project_titan_x.engines.base import EngineResult

    fake_store: dict[str, bytes] = {}
    monkeypatch.setattr(md_module, "cache_get_bytes", lambda key: fake_store.get(key))
    monkeypatch.setattr(md_module, "cache_set_bytes", lambda key, value, ttl: fake_store.__setitem__(key, value))

    call_count = {"n": 0}
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-15 12:00:00"], utc=True),
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5], "volume": [500],
    })

    def _fake_uncached(self, symbol, timeframe="1d", start=None, end=None, years=10):
        call_count["n"] += 1
        return EngineResult(success=True, data=df.copy(), message="real fetch")

    monkeypatch.setattr(md_module.MarketDataEngine, "_fetch_ohlcv_uncached", _fake_uncached)

    result1 = engine.fetch_ohlcv("GOLD", "1d", years=2, allow_cache=True)
    result2 = engine.fetch_ohlcv("GOLD", "1d", years=2, allow_cache=True)

    assert call_count["n"] == 1  # second call served entirely from cache
    assert result1.success and result2.success
    pd.testing.assert_frame_equal(result1.data, result2.data)
    assert "(cached)" in result2.message
    assert "(cached)" not in result1.message


def test_fetch_ohlcv_default_never_touches_cache(engine, monkeypatch):
    """Regression test for a real bug caught by 2 pre-existing tests
    failing (test_fetch_ohlcv_twice_increments_catalog_version,
    test_get_catalog_summary_reflects_fetched_datasets): an early
    version of this cache wrapped every fetch_ohlcv call unconditionally,
    silently breaking this engine's own documented "audit/versioning
    catalog on every fetch" guarantee (catalog.record() and the audit
    log only run inside _fetch_ohlcv_uncached, so a cache hit skipped
    them too). allow_cache now defaults to False specifically so every
    existing caller's guarantee is untouched -- this asserts
    cache_get_bytes/cache_set_bytes are never even called without an
    explicit opt-in."""
    import project_titan_x.engines.e02_market_data.engine as md_module
    from project_titan_x.engines.base import EngineResult

    calls = {"get": 0, "set": 0}
    monkeypatch.setattr(md_module, "cache_get_bytes", lambda key: calls.__setitem__("get", calls["get"] + 1))
    monkeypatch.setattr(md_module, "cache_set_bytes", lambda key, value, ttl: calls.__setitem__("set", calls["set"] + 1))

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-15 12:00:00"], utc=True),
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5], "volume": [500],
    })
    monkeypatch.setattr(
        md_module.MarketDataEngine, "_fetch_ohlcv_uncached",
        lambda self, symbol, timeframe="1d", start=None, end=None, years=10: EngineResult(success=True, data=df, message="real fetch"),
    )

    engine.fetch_ohlcv("GOLD", "1d", years=2)  # no allow_cache -- must default False
    engine.fetch_ohlcv("GOLD", "1d", years=2)  # again -- still must never touch the cache

    assert calls == {"get": 0, "set": 0}


def test_fetch_ohlcv_falls_back_to_real_fetch_when_cache_unavailable(engine, monkeypatch):
    """Best-effort convention: a Redis failure (simulated here as
    cache_get_bytes/cache_set_bytes raising) must never prevent a real
    fetch from succeeding -- degrades to uncached behavior silently."""
    import project_titan_x.engines.e02_market_data.engine as md_module
    from project_titan_x.engines.base import EngineResult

    def _raise(*a, **kw):
        raise ConnectionError("redis down")

    monkeypatch.setattr(md_module, "cache_get_bytes", _raise)
    monkeypatch.setattr(md_module, "cache_set_bytes", _raise)

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-15 12:00:00"], utc=True),
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5], "volume": [500],
    })
    monkeypatch.setattr(
        md_module.MarketDataEngine, "_fetch_ohlcv_uncached",
        lambda self, symbol, timeframe="1d", start=None, end=None, years=10: EngineResult(success=True, data=df, message="real fetch"),
    )

    result = engine.fetch_ohlcv("GOLD", "1d", years=2, allow_cache=True)
    assert result.success
    assert result.message == "real fetch"  # not "(cached)" -- genuinely fell through


# ---- _ccxt_perpetual_market_symbol (pure function, no network) ----


def test_ccxt_perpetual_market_symbol_maps_usd_to_usdt_perpetual():
    assert _ccxt_perpetual_market_symbol("BTC-USD") == "BTC/USDT:USDT"
    assert _ccxt_perpetual_market_symbol("ETH-USD") == "ETH/USDT:USDT"


def test_ccxt_perpetual_market_symbol_none_for_non_crypto():
    assert _ccxt_perpetual_market_symbol("EURUSD=X") is None
    assert _ccxt_perpetual_market_symbol("GC=F") is None


# ---- fetch_ohlcv `years` bounding (real regression test) ----
# Real bug found and fixed 2026-07-19: for every daily+ timeframe,
# YFINANCE_PERIOD["1d"/"1wk"/"1mo"] == "max", and the old code always
# called yfinance with period=... when `end` wasn't given -- `years` was
# computed into `start` but that value was never actually passed to
# yfinance, so every daily-timeframe fetch_ohlcv call across the WHOLE
# codebase (E24/E27/E28/E51's own edge-gate, etc.) silently ignored
# `years` and always returned maximum available history. Never caught
# because no test asserted the returned range was actually bounded.


@pytest.mark.network
def test_fetch_ohlcv_years_actually_bounds_daily_history(engine):
    result_2y = engine.fetch_ohlcv("GC=F", "1d", years=2)
    result_8y = engine.fetch_ohlcv("GC=F", "1d", years=8)
    assert result_2y.success and result_8y.success
    span_2y_days = (result_2y.data["timestamp"].max() - result_2y.data["timestamp"].min()).days
    span_8y_days = (result_8y.data["timestamp"].max() - result_8y.data["timestamp"].min()).days
    # Not asserting an exact day count (weekends/holidays/yfinance's own
    # slight rounding) -- just that a smaller `years` genuinely returns a
    # smaller window, and neither silently returns the full ~26-year
    # history GOLD (GC=F) actually has on Yahoo.
    assert span_2y_days < 900  # well under 3 years
    assert span_8y_days < 3200  # well under 9 years
    assert span_2y_days < span_8y_days
    assert len(result_2y.data) < len(result_8y.data)


@pytest.mark.network
def test_fetch_ohlcv_records_quality_score_and_catalog_entry(engine, tmp_path):
    result = engine.fetch_ohlcv("BTC-USD", timeframe="1d", years=1)
    assert result.success
    assert result.metadata["quality_score"] is not None
    assert 0.0 <= result.metadata["quality_score"] <= 100.0

    catalog_entry = engine._catalog.get_dataset("BTC-USD", "1d")
    assert catalog_entry is not None
    assert catalog_entry["rows"] == len(result.data)
    assert catalog_entry["source"] == "yahoo_finance"
    assert catalog_entry["checksum"]
    assert catalog_entry["version"] == 1


@pytest.mark.network
def test_fetch_ohlcv_twice_increments_catalog_version(engine):
    engine.fetch_ohlcv("BTC-USD", timeframe="1d", years=1)
    engine.fetch_ohlcv("BTC-USD", timeframe="1d", years=1)
    entry = engine._catalog.get_dataset("BTC-USD", "1d")
    assert entry["version"] == 2

    audit_log = engine.get_audit_log().data
    assert len(audit_log) == 2


@pytest.mark.network
def test_fetch_ohlcv_merges_with_existing_cache_instead_of_overwriting(engine):
    """Real regression test: a live fetch must MERGE with whatever's
    already cached on disk, never blind-overwrite it. Caught live: a
    narrow-window fetch (e.g. 1-minute data, where yfinance's free tier
    caps history at ~60 days regardless of `years` requested) would
    otherwise silently destroy deeper imported/cached history sitting
    outside that window -- this happened to a real 22-year, 6.79M-row
    imported GOLD 1-minute dataset before this fix."""
    first = engine.fetch_ohlcv("BTC-USD", timeframe="1d", years=2)
    assert first.success

    # Simulate deep imported history sitting in the cache well outside
    # what any bounded live fetch below would ever request.
    parquet_path = engine.processed_dir / "BTC-USD_1d.parquet"
    cached = pd.read_parquet(parquet_path)
    old_row = cached.iloc[[0]].copy()
    old_row["timestamp"] = old_row["timestamp"] - pd.Timedelta(days=3650)
    augmented = pd.concat([old_row, cached], ignore_index=True)
    augmented.to_parquet(parquet_path, index=False)

    # A narrower, more recent live fetch must not wipe the 10-years-older row.
    second = engine.fetch_ohlcv("BTC-USD", timeframe="1d", years=1)
    assert second.success

    final_cache = pd.read_parquet(parquet_path)
    # Note: use .tolist(), not .values -- Series.values on a tz-aware
    # datetime column silently drops tz info (documented pandas
    # behavior), which breaks direct comparison against a tz-aware
    # Timestamp.
    assert old_row["timestamp"].iloc[0] in final_cache["timestamp"].tolist()
    # The narrow fetch's own returned data must stay narrow (callers get
    # what they asked for, not the whole merged cache file).
    assert second.data["timestamp"].min() > old_row["timestamp"].iloc[0]


def test_fetch_ohlcv_merge_collapses_duplicate_calendar_days_on_daily_timeframe(engine):
    """Real regression test for a real, previously-documented bug: the
    exact-timestamp dedup alone (subset="timestamp") does NOT catch two
    rows for the SAME calendar day stamped at different times of day
    (e.g. 00:00 vs 04:00 UTC) -- measured live across this project's own
    cached data: 67,036 such duplicate-day rows across 13 files before
    this fix. Simulates exactly that shape (a correctly-normalized
    midnight row plus a stale non-midnight row for the SAME date) and
    confirms the merge collapses them to one, keeping the midnight one."""
    first = engine.fetch_ohlcv("BTC-USD", timeframe="1d", years=1)
    assert first.success

    parquet_path = engine.processed_dir / "BTC-USD_1d.parquet"
    cached = pd.read_parquet(parquet_path)
    real_row = cached.iloc[[0]].copy()
    real_date = real_row["timestamp"].iloc[0]
    assert real_date.hour == 0, "sanity: this project's own daily rows are midnight-UTC"

    # A stale duplicate for the SAME calendar day, stamped 4 hours later --
    # the exact shape found in this project's own real corrupted files.
    stale_dup = real_row.copy()
    stale_dup["timestamp"] = real_date + pd.Timedelta(hours=4)
    stale_dup["close"] = stale_dup["close"] * 1.0001  # near-identical, not byte-identical

    augmented = pd.concat([cached, stale_dup], ignore_index=True)
    augmented.to_parquet(parquet_path, index=False)
    before_count = len(pd.read_parquet(parquet_path))

    second = engine.fetch_ohlcv("BTC-USD", timeframe="1d", years=1)
    assert second.success

    final_cache = pd.read_parquet(parquet_path)
    final_cache["date"] = final_cache["timestamp"].dt.date
    assert before_count == len(cached) + 1                      # confirms the dup was really added
    assert not final_cache.duplicated("date", keep=False).any()  # and really collapsed
    same_date_rows = final_cache[final_cache["date"] == real_date.date()]
    assert len(same_date_rows) == 1
    assert same_date_rows["timestamp"].iloc[0].hour == 0        # kept the normalized-convention row


@pytest.mark.network
def test_fetch_ohlcv_uses_real_data_quality_engine_not_a_stub(tmp_path):
    """Confirms the injected DataQualityEngine is REALLY invoked (not just
    accepted and ignored) -- verify by checking the quality score is a
    real, non-default float computed from the actual fetched data, using
    a fresh, uninstrumented DataQualityEngine instance."""
    quality_engine = DataQualityEngine()
    quality_engine.initialize()
    engine = MarketDataEngine(data_dir=tmp_path, data_quality_engine=quality_engine)
    engine.initialize()
    result = engine.fetch_ohlcv("BTC-USD", timeframe="1d", years=1)
    assert result.success
    df = result.data
    direct_validation = quality_engine.validate(df)
    # The score attached to the fetch result must match a fresh validate()
    # call on the SAME final (possibly repaired) data -- proves the real
    # validate() path executed, not a bypassed/mocked one.
    assert result.metadata["quality_score"] == pytest.approx(direct_validation.data.quality_score)


def test_data_quality_defaults_to_real_instance_when_not_injected(tmp_path):
    engine = MarketDataEngine(data_dir=tmp_path)
    assert isinstance(engine._data_quality_engine, DataQualityEngine)


def test_catalog_defaults_to_real_instance_when_not_injected(tmp_path):
    engine = MarketDataEngine(data_dir=tmp_path)
    assert isinstance(engine._catalog, DatasetCatalog)


# ---- funding rate / open interest (real Binance public API) ----


@pytest.mark.network
def test_fetch_funding_rate_btc_returns_real_data(engine):
    result = engine.fetch_funding_rate("BTCUSD")
    assert result.success
    assert result.data is not None
    assert result.data["market"] == "BTC/USDT:USDT"
    assert isinstance(result.data["funding_rate"], float)


@pytest.mark.network
def test_fetch_open_interest_btc_returns_real_data(engine):
    result = engine.fetch_open_interest("BTCUSD")
    assert result.success
    assert result.data is not None
    assert result.data["open_interest"] > 0


@pytest.mark.network
def test_fetch_open_interest_history_btc_returns_real_time_series(engine):
    result = engine.fetch_open_interest_history("BTCUSD", days=10)
    assert result.success
    assert result.data is not None
    assert not result.data.empty
    assert list(result.data.columns) == ["timestamp", "open_interest"]
    assert (result.data["open_interest"] > 0).all()
    assert result.data["timestamp"].is_monotonic_increasing


def test_fetch_open_interest_history_non_crypto_returns_honest_gap(engine):
    result = engine.fetch_open_interest_history("GOLD")
    assert result.success
    assert result.data is None


def test_fetch_funding_rate_non_crypto_returns_honest_gap(engine):
    result = engine.fetch_funding_rate("GOLD")
    assert result.success
    assert result.data is None


def test_fetch_open_interest_non_crypto_returns_honest_gap(engine):
    result = engine.fetch_open_interest("EURUSD")
    assert result.success
    assert result.data is None


# ---- COT reports (real CFTC API) ----


@pytest.mark.network
def test_fetch_cot_report_gold_returns_real_data(engine):
    result = engine.fetch_cot_report("GOLD", limit=5)
    assert result.success
    assert result.data is not None
    assert not result.data.empty


def test_fetch_cot_report_india_asset_returns_honest_gap(engine):
    result = engine.fetch_cot_report("NIFTY50")
    assert result.success
    assert result.data is None
    assert "not a us-listed futures" in result.message.lower()


# ---- Fear & Greed Index (real alternative.me API) ----


@pytest.mark.network
def test_fetch_fear_greed_index_returns_real_data(engine):
    result = engine.fetch_fear_greed_index(limit=5)
    assert result.success
    assert not result.data.empty
    assert 0 <= result.metadata["latest_value"] <= 100


# ---- catalog / audit log accessors ----


@pytest.mark.network
def test_get_catalog_summary_reflects_fetched_datasets(engine):
    engine.fetch_ohlcv("BTC-USD", timeframe="1d", years=1)
    summary = engine.get_catalog_summary()
    assert summary.success
    assert any(d["symbol"] == "BTC-USD" for d in summary.data)


def test_get_catalog_summary_empty_before_any_fetch(engine):
    summary = engine.get_catalog_summary()
    assert summary.success
    assert summary.data == []


def test_get_audit_log_empty_before_any_fetch(engine):
    log = engine.get_audit_log()
    assert log.success
    assert log.data == []


# ---- All-null column pruning (added 2026-09-15). Real defect: measured
# across all 241 processed parquets, ETH-USD_1d -- one of the two
# instruments trading live -- had accumulated `date`, `asset_name`,
# `asset_type` and `region`, all null in all 3,675 rows, while no other
# file carried them. Cache merging via concat is what widens a file like
# that, and it compounds because the next merge takes the widened file as
# its baseline. ----

def test_all_null_columns_are_dropped_before_save():
    from project_titan_x.engines.e02_market_data.engine import _prune_empty_columns

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
        "close": [1.0, 2.0],
        "date": [None, None],           # the dangerous one -- plausible name,
        "asset_name": [None, None],     # no data
    })
    out = _prune_empty_columns(df, "ETH-USD", "1d")
    assert list(out.columns) == ["timestamp", "close"]
    assert len(out) == 2


def test_sparse_columns_are_real_data_and_are_kept():
    """`dividends` is legitimately null on early rows for several symbols.
    Pruning it would destroy real corporate-action data."""
    from project_titan_x.engines.e02_market_data.engine import _prune_empty_columns

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
        "dividends": [None, 0.25],
    })
    out = _prune_empty_columns(df, "AAPL", "1d")
    assert "dividends" in out.columns


def test_pruning_never_loses_a_good_fetch_to_its_own_failure():
    """Cleanup must never cost the data it was cleaning."""
    from project_titan_x.engines.e02_market_data.engine import _prune_empty_columns

    class _Hostile(pd.DataFrame):
        @property
        def columns(self):
            raise RuntimeError("boom")

    df = _Hostile({"close": [1.0]})
    assert _prune_empty_columns(df, "X", "1d") is df


def test_a_frame_with_nothing_to_prune_is_returned_unchanged():
    from project_titan_x.engines.e02_market_data.engine import _prune_empty_columns

    df = pd.DataFrame({"timestamp": pd.to_datetime(["2026-01-01"], utc=True), "close": [1.0]})
    assert _prune_empty_columns(df, "X", "1d") is df
