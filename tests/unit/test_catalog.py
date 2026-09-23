"""
Module: test_catalog.py
Description: Unit tests for DatasetCatalog (audit log, registry, versioning, checksums).
Author: Shantanu Waykar
Version: 1.0.0
"""

import hashlib
import json

from project_titan_x.core.catalog import DatasetCatalog


def _make_file(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_checksum_file_matches_real_sha256(tmp_path):
    path = _make_file(tmp_path, "a.txt", "hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert DatasetCatalog.checksum_file(path) == expected


def test_record_creates_registry_and_audit_log(tmp_path):
    catalog = DatasetCatalog(catalog_dir=tmp_path / "catalog")
    data_file = _make_file(tmp_path, "data.parquet", "content-v1")

    entry = catalog.record(
        symbol="BTC-USD", timeframe="1d", source="yahoo_finance", rows=100,
        date_range=("2020-01-01", "2026-01-01"), file_path=data_file, quality_score=95.0,
    )
    assert entry.version == 1
    assert entry.dataset_id == "BTC-USD_1d"
    assert entry.checksum == DatasetCatalog.checksum_file(data_file)

    latest = catalog.get_dataset("BTC-USD", "1d")
    assert latest is not None
    assert latest["rows"] == 100
    assert latest["quality_score"] == 95.0


def test_record_increments_version_on_re_fetch(tmp_path):
    catalog = DatasetCatalog(catalog_dir=tmp_path / "catalog")
    data_file = _make_file(tmp_path, "data.parquet", "content-v1")

    catalog.record(symbol="BTC-USD", timeframe="1d", source="yahoo_finance", rows=100,
                    date_range=("2020-01-01", "2026-01-01"), file_path=data_file)

    data_file.write_text("content-v2", encoding="utf-8")
    entry2 = catalog.record(symbol="BTC-USD", timeframe="1d", source="yahoo_finance", rows=105,
                             date_range=("2020-01-01", "2026-01-02"), file_path=data_file)

    assert entry2.version == 2
    latest = catalog.get_dataset("BTC-USD", "1d")
    assert latest["version"] == 2
    assert latest["rows"] == 105


def test_record_detects_content_change_via_checksum(tmp_path):
    catalog = DatasetCatalog(catalog_dir=tmp_path / "catalog")
    data_file = _make_file(tmp_path, "data.parquet", "content-v1")
    entry1 = catalog.record(symbol="X", timeframe="1d", source="s", rows=1,
                             date_range=("a", "b"), file_path=data_file)
    data_file.write_text("different-content", encoding="utf-8")
    entry2 = catalog.record(symbol="X", timeframe="1d", source="s", rows=1,
                             date_range=("a", "b"), file_path=data_file)
    assert entry1.checksum != entry2.checksum


def test_different_datasets_have_independent_versions(tmp_path):
    catalog = DatasetCatalog(catalog_dir=tmp_path / "catalog")
    f1 = _make_file(tmp_path, "btc.parquet", "btc-data")
    f2 = _make_file(tmp_path, "eth.parquet", "eth-data")

    catalog.record(symbol="BTC-USD", timeframe="1d", source="s", rows=1, date_range=("a", "b"), file_path=f1)
    entry = catalog.record(symbol="ETH-USD", timeframe="1d", source="s", rows=1, date_range=("a", "b"), file_path=f2)

    assert entry.version == 1  # independent from BTC-USD's version counter
    assert len(catalog.list_datasets()) == 2


def test_get_dataset_returns_none_for_unknown_dataset(tmp_path):
    catalog = DatasetCatalog(catalog_dir=tmp_path / "catalog")
    assert catalog.get_dataset("NOPE", "1d") is None


def test_get_audit_log_newest_first_and_respects_limit(tmp_path):
    catalog = DatasetCatalog(catalog_dir=tmp_path / "catalog")
    data_file = _make_file(tmp_path, "data.parquet", "content")
    for i in range(5):
        catalog.record(symbol="X", timeframe="1d", source="s", rows=i,
                        date_range=("a", "b"), file_path=data_file)

    log = catalog.get_audit_log(limit=3)
    assert len(log) == 3
    # Newest first: last-recorded entry (rows=4) comes first.
    assert log[0]["rows"] == 4
    assert log[1]["rows"] == 3
    assert log[2]["rows"] == 2


def test_record_handles_missing_file_gracefully(tmp_path):
    catalog = DatasetCatalog(catalog_dir=tmp_path / "catalog")
    missing = tmp_path / "does_not_exist.parquet"
    entry = catalog.record(symbol="X", timeframe="1d", source="s", rows=0,
                            date_range=("a", "b"), file_path=missing)
    assert entry.checksum == ""


def test_record_thread_safe_under_concurrent_writes(tmp_path):
    """Real bug found and fixed 2026-07-20: record() does a read-modify-
    write on registry.json with no lock -- harmless while
    e51_signals.scan_all_assets called MarketDataEngine (and its ONE
    shared DatasetCatalog) sequentially, but the moment that scan was
    parallelized, concurrent record() calls for different assets started
    racing on this same file. Symptoms seen live: a "Failed to load
    dataset registry: Expecting value: line 1 column 1 (char 0)" (a
    reader catching write_text mid-truncate) and, more quietly, lost
    updates (two threads reading the same snapshot, the later writer's
    entry silently overwriting the earlier one's). This test uses REAL
    threads and REAL file I/O against the actual registry.json path --
    not mocked -- since a lock bug is exactly the kind of thing a
    sequential/stubbed test can never catch."""
    import threading

    catalog = DatasetCatalog(catalog_dir=tmp_path / "catalog")
    data_file = _make_file(tmp_path, "data.parquet", "content")

    n_threads = 30
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            catalog.record(
                symbol=f"SYM{i}", timeframe="1d", source="test", rows=100,
                date_range=("2024-01-01", "2024-12-31"), file_path=data_file,
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    registry = catalog._load_registry()
    assert len(registry) == n_threads
    for i in range(n_threads):
        assert f"SYM{i}_1d" in registry, f"lost update: SYM{i}_1d missing from registry after concurrent writes"

    # The audit log (append-only) must also have exactly one line per
    # thread -- a torn/interleaved write there would show up as a line
    # count mismatch or a JSON-decode failure on any line.
    lines = catalog._audit_log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == n_threads
    for line in lines:
        json.loads(line)  # must not raise
