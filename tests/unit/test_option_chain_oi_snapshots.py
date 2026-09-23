"""
Real-DB tests for docs/UPGRADE_ROADMAP.md P1 item 5 -- option-chain OI
change tracking (api.main._oi_changes_and_persist + the
OptionChainOISnapshot table).

Imports the function directly from api.main rather than booting the full
app/registry (same discipline as test_api_security.py's own docstring:
importing api.main costs ~14s and initialising all 55 engines would make
a focused test too slow -- this function needs only the DB, not the
registry).

Marked network since it needs a real Postgres connection, matching this
suite's own convention for tests that need a real external dependency
rather than a mock.
"""

from datetime import date

import pytest

from project_titan_x.api.main import _oi_changes_and_persist
from project_titan_x.core.data_providers.kite_option_chain import OptionChainRow
from project_titan_x.core.database import OptionChainOISnapshot, get_db_session

TEST_SYMBOL = "TEST_OI_SYMBOL"
TEST_EXPIRY = date(2099, 12, 31)  # far future, never collides with a real symbol/expiry


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with get_db_session() as session:
        session.query(OptionChainOISnapshot).filter(
            OptionChainOISnapshot.symbol == TEST_SYMBOL, OptionChainOISnapshot.expiry == TEST_EXPIRY,
        ).delete(synchronize_session=False)


@pytest.mark.network
def test_first_read_has_no_prior_to_diff_against():
    rows = [
        OptionChainRow(strike=100.0, ce_oi=500.0, pe_oi=300.0),
        OptionChainRow(strike=110.0, ce_oi=200.0, pe_oi=None),
    ]
    changes = _oi_changes_and_persist(TEST_SYMBOL, TEST_EXPIRY, rows)
    assert changes[(100.0, "CE")] is None
    assert changes[(100.0, "PE")] is None
    assert (110.0, "PE") not in changes  # oi=None -> skipped, never a fabricated 0
    assert changes[(110.0, "CE")] is None

    with get_db_session() as session:
        persisted = session.query(OptionChainOISnapshot).filter(
            OptionChainOISnapshot.symbol == TEST_SYMBOL, OptionChainOISnapshot.expiry == TEST_EXPIRY,
        ).all()
    # 2 legs at strike 100 (CE+PE) + 1 leg at strike 110 (CE only, PE was None) = 3
    assert len(persisted) == 3


@pytest.mark.network
def test_second_read_diffs_against_the_first():
    first_rows = [OptionChainRow(strike=100.0, ce_oi=500.0, pe_oi=300.0)]
    _oi_changes_and_persist(TEST_SYMBOL, TEST_EXPIRY, first_rows)

    second_rows = [OptionChainRow(strike=100.0, ce_oi=650.0, pe_oi=250.0)]
    changes = _oi_changes_and_persist(TEST_SYMBOL, TEST_EXPIRY, second_rows)
    assert changes[(100.0, "CE")] == pytest.approx(150.0)   # 650 - 500
    assert changes[(100.0, "PE")] == pytest.approx(-50.0)   # 250 - 300


@pytest.mark.network
def test_third_read_diffs_against_the_second_not_the_first():
    """The lookup is MAX(captured_at) -- the most recent prior batch, not
    the oldest -- so a chain of reads tracks the real running change."""
    _oi_changes_and_persist(TEST_SYMBOL, TEST_EXPIRY, [OptionChainRow(strike=100.0, ce_oi=500.0)])
    _oi_changes_and_persist(TEST_SYMBOL, TEST_EXPIRY, [OptionChainRow(strike=100.0, ce_oi=600.0)])
    changes = _oi_changes_and_persist(TEST_SYMBOL, TEST_EXPIRY, [OptionChainRow(strike=100.0, ce_oi=650.0)])
    assert changes[(100.0, "CE")] == pytest.approx(50.0)  # 650 - 600, not 650 - 500


@pytest.mark.network
def test_different_expiry_does_not_cross_contaminate():
    other_expiry = date(2098, 1, 1)
    _oi_changes_and_persist(TEST_SYMBOL, TEST_EXPIRY, [OptionChainRow(strike=100.0, ce_oi=999.0)])
    try:
        changes = _oi_changes_and_persist(TEST_SYMBOL, other_expiry, [OptionChainRow(strike=100.0, ce_oi=1.0)])
        assert changes[(100.0, "CE")] is None  # no prior for THIS expiry, despite one existing for TEST_EXPIRY
    finally:
        with get_db_session() as session:
            session.query(OptionChainOISnapshot).filter(
                OptionChainOISnapshot.symbol == TEST_SYMBOL, OptionChainOISnapshot.expiry == other_expiry,
            ).delete(synchronize_session=False)
