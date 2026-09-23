"""
Tests for the shared Yahoo wrapper (docs/PROJECT_AUDIT.md weakness W1).

Six engines used to call `yf.Ticker(...).history(...)` directly, bypassing
E02's fallback chain, so a Yahoo outage degraded each of them silently and
DIFFERENTLY. These tests pin the two properties that fix is worth anything
for: it retries, and it never raises.

No network. yfinance is monkeypatched, so these run in the deterministic
suite rather than depending on a third party being up.
"""

import logging

import pandas as pd
import pytest

from project_titan_x.core.data_providers import yahoo


class _FakeTicker:
    """Scripted stand-in for yf.Ticker."""

    def __init__(self, behaviours):
        self._behaviours = list(behaviours)
        self.calls = 0

    def __call__(self, symbol):
        return self

    def history(self, **kwargs):
        self.calls += 1
        b = self._behaviours.pop(0) if self._behaviours else pd.DataFrame()
        if isinstance(b, Exception):
            raise b
        return b

    @property
    def info(self):
        self.calls += 1
        b = self._behaviours.pop(0) if self._behaviours else {}
        if isinstance(b, Exception):
            raise b
        return b


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Backoff is real in production; waiting for it in tests is not."""
    monkeypatch.setattr(yahoo.time, "sleep", lambda *_: None)


def _frame():
    return pd.DataFrame({"Close": [1.0, 2.0]})


def _install(monkeypatch, behaviours):
    fake = _FakeTicker(behaviours)
    monkeypatch.setattr(yahoo.yf, "Ticker", fake)
    return fake


# --------------------------------------------------------------------------
# It never raises -- the contract every existing caller depends on
# --------------------------------------------------------------------------

def test_history_returns_empty_frame_instead_of_raising(monkeypatch):
    _install(monkeypatch, [RuntimeError("boom")] * yahoo.MAX_ATTEMPTS)
    out = yahoo.ticker_history("ANY", "5d")
    assert isinstance(out, pd.DataFrame) and out.empty


def test_info_returns_empty_dict_instead_of_raising(monkeypatch):
    _install(monkeypatch, [RuntimeError("boom")] * yahoo.MAX_ATTEMPTS)
    assert yahoo.ticker_info("ANY") == {}


@pytest.mark.parametrize("boom", [RuntimeError("x"), ValueError("y"), KeyError("z"),
                                  TimeoutError("t"), ConnectionError("c")])
def test_any_provider_exception_degrades_the_same_way(monkeypatch, boom):
    """The point of the wrapper: one failure shape, whatever the provider
    throws. Previously each engine's own try/except decided this."""
    _install(monkeypatch, [boom] * yahoo.MAX_ATTEMPTS)
    assert yahoo.ticker_history("ANY", "5d").empty


# --------------------------------------------------------------------------
# It retries
# --------------------------------------------------------------------------

def test_history_retries_then_succeeds(monkeypatch):
    fake = _install(monkeypatch, [RuntimeError("transient"), _frame()])
    out = yahoo.ticker_history("ANY", "5d")
    assert not out.empty
    assert fake.calls == 2, "should have retried exactly once before succeeding"


def test_history_gives_up_after_max_attempts(monkeypatch):
    fake = _install(monkeypatch, [RuntimeError("down")] * 10)
    yahoo.ticker_history("ANY", "5d")
    assert fake.calls == yahoo.MAX_ATTEMPTS


def test_empty_response_is_also_retried(monkeypatch):
    """An empty frame can be a transient blip or a genuinely dead ticker.
    Retrying distinguishes them without making a bad ticker cost three
    slow calls forever."""
    fake = _install(monkeypatch, [pd.DataFrame(), _frame()])
    out = yahoo.ticker_history("ANY", "5d")
    assert not out.empty
    assert fake.calls == 2


def test_info_retries_then_succeeds(monkeypatch):
    fake = _install(monkeypatch, [RuntimeError("transient"), {"marketCap": 1}])
    assert yahoo.ticker_info("ANY") == {"marketCap": 1}
    assert fake.calls == 2


def test_first_attempt_success_does_not_retry(monkeypatch):
    fake = _install(monkeypatch, [_frame()])
    yahoo.ticker_history("ANY", "5d")
    assert fake.calls == 1


# --------------------------------------------------------------------------
# The failure is VISIBLE -- the actual defect being fixed
# --------------------------------------------------------------------------

def test_total_failure_is_logged_with_the_symbol(monkeypatch, caplog):
    """A Yahoo outage previously surfaced as 'insufficient history', which
    is indistinguishable from a real finding. It must name the symbol."""
    _install(monkeypatch, [RuntimeError("down")] * yahoo.MAX_ATTEMPTS)
    with caplog.at_level(logging.WARNING, logger=yahoo.logger.name):
        yahoo.ticker_history("^TNX", "5d", context="e06.yield_10y")
    text = caplog.text
    assert "^TNX" in text
    assert "e06.yield_10y" in text, "context must identify which engine asked"


def test_interval_is_forwarded_when_given(monkeypatch):
    seen = {}

    class T:
        def __call__(self, s): return self
        def history(self, **kw):
            seen.update(kw)
            return _frame()

    monkeypatch.setattr(yahoo.yf, "Ticker", T())
    yahoo.ticker_history("ANY", "60d", interval="1d")
    assert seen.get("interval") == "1d"
    seen.clear()
    yahoo.ticker_history("ANY", "5d")
    assert "interval" not in seen, "must not pass interval=None to yfinance"


# --------------------------------------------------------------------------
# No engine reaches past the wrapper any more
# --------------------------------------------------------------------------

def test_no_engine_outside_e02_calls_yfinance_directly():
    """The regression guard. E02 legitimately owns the raw provider calls
    because it implements the fallback chain; nobody else may."""
    import pathlib
    import re

    root = pathlib.Path(yahoo.__file__).resolve().parents[2] / "engines"
    offenders = []
    for f in root.rglob("engine.py"):
        if "e02_market_data" in str(f):
            continue
        src = f.read_text(encoding="utf-8", errors="replace")
        if re.search(r"yf\.Ticker\(|yf\.download\(", src):
            offenders.append(f.parent.name)
    assert not offenders, f"engines bypassing the wrapper: {offenders}"
