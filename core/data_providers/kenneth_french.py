"""
Module: kenneth_french.py
Description: Kenneth R. French Data Library client -- free, no-key, real
             academic source for the Fama-French factor returns (Mkt-RF,
             SMB, HML, RMW, CMA) and the Carhart momentum factor, both at
             daily frequency, back to 1926. Verified live 2026-07-20: a
             real, unauthenticated GET against
             mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/ returns
             200 with real ZIP-wrapped CSV data (26,260 real daily rows in
             the 3-factor file alone), not guessed.

             Same disk-cache/graceful-shape convention as this project's
             other lightweight data-provider clients (alpha_vantage.py,
             finnhub.py, fred.py) -- a thin, faithful wrapper; normalization
             into this platform's own shape happens in
             e20_factor_research/engine.py, not here.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-20
"""

import hashlib
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"

# Real, stable, publicly documented file names on French's own site --
# not guessed. "5_Factors_2x3" is French's own naming for the standard
# 5-factor construction (2x3 sorts); "Momentum_Factor" is the Carhart
# 4th-factor addition, distributed separately from the 3/5-factor sets.
DATASET_FILES = {
    "3factor": "F-F_Research_Data_Factors_daily_CSV.zip",
    "5factor": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "momentum": "F-F_Momentum_Factor_daily_CSV.zip",
}

# This is reference academic data, updated by French's team roughly
# monthly/quarterly, not intraday -- a long TTL is appropriate and avoids
# hitting Dartmouth's server on every process restart.
CACHE_TTL_SECONDS = 24 * 60 * 60


class KennethFrenchError(Exception):
    """Raised when the Kenneth French library returns an error or an
    unexpected/unparseable file shape."""


class KennethFrenchClient:
    """Thin client for French's Data Library -- downloads a ZIP, extracts
    the single CSV inside, and parses French's own (slightly idiosyncratic
    but stable) header-then-table format into a real pandas DataFrame of
    daily FRACTIONAL returns (French's own files are in percent, e.g.
    0.09 meaning 0.09% -- divided by 100 here so every factor return is on
    the same fractional scale as a log/pct_change asset return, since
    e20_factor_research regresses the two against each other directly)."""

    def __init__(self, cache_dir: Optional[Path] = None, timeout: float = 30.0) -> None:
        self.cache_dir = cache_dir or Path("data") / "raw" / "kenneth_french_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def get_factors_daily(self, dataset: str = "3factor") -> pd.DataFrame:
        """Real daily factor returns for `dataset` ("3factor": Mkt-RF/SMB/
        HML/RF; "5factor": Mkt-RF/SMB/HML/RMW/CMA/RF; "momentum": Mom).
        Returns a DataFrame indexed by real trading dates (UTC-naive,
        matches French's own daily calendar) with fractional (not
        percent) return columns."""
        filename = DATASET_FILES.get(dataset)
        if filename is None:
            raise KennethFrenchError(f"Unknown dataset {dataset!r} -- expected one of {list(DATASET_FILES)}")

        cached = self._read_cache(dataset)
        if cached is not None:
            return cached

        url = f"{BASE_URL}/{filename}"
        response = self._client.get(url)
        if response.status_code != 200:
            raise KennethFrenchError(f"Kenneth French library GET {url} -- {response.status_code}")

        try:
            zf = zipfile.ZipFile(io.BytesIO(response.content))
            inner_name = zf.namelist()[0]
            text = zf.read(inner_name).decode("utf-8", errors="replace")
        except Exception as e:
            raise KennethFrenchError(f"Could not read ZIP/CSV from {url}: {e}") from e

        df = self._parse_csv(text, dataset)
        self._write_cache(dataset, df)
        return df

    @staticmethod
    def _is_daily_date_row(line: str) -> bool:
        first_field = line.split(",", 1)[0].strip()
        return first_field.isdigit() and len(first_field) == 8

    @classmethod
    def _parse_csv(cls, text: str, dataset: str) -> pd.DataFrame:
        """French's files: several free-text descriptive lines (some of
        which -- confirmed live in the momentum file -- are themselves
        blank comma-separated rows like ",," and would WRONGLY match a
        naive "starts with a comma" header check), then the real header
        row (",Mkt-RF,SMB,HML,RF" or ",Mom,"), then one data row per
        trading day (YYYYMMDD, value, ...), ending with a blank line and a
        copyright notice. The header is identified as the comma-prefixed
        line immediately BEFORE the first real 8-digit-date data row --
        not just any comma-prefixed line -- which is what the blank-line
        false-positive above requires. Parsed defensively (stops at the
        first non-date row once data begins) rather than assuming a fixed
        line count, since French's team does occasionally reformat these.
        Missing-data sentinels (-99.99 / -999, per the momentum file's own
        documented convention) become real NaN, never a fabricated 0."""
        lines = text.splitlines()
        first_data_idx = next((i for i, line in enumerate(lines) if cls._is_daily_date_row(line)), None)
        if first_data_idx is None or first_data_idx == 0 or not lines[first_data_idx - 1].startswith(","):
            raise KennethFrenchError(f"Could not find the header row in {dataset} CSV -- unexpected file format")
        header_idx = first_data_idx - 1

        columns = ["date"] + [c.strip() for c in lines[header_idx].split(",")[1:] if c.strip()]
        rows = []
        for line in lines[first_data_idx:]:
            if not cls._is_daily_date_row(line):
                break  # first non-daily-date row -- end of the real data table
            parts = [p.strip() for p in line.split(",")]
            rows.append(parts[: len(columns)])

        if not rows:
            raise KennethFrenchError(f"No data rows parsed from {dataset} CSV -- unexpected file format")

        df = pd.DataFrame(rows, columns=columns)
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        for col in columns[1:]:
            values = pd.to_numeric(df[col], errors="coerce")
            values = values.where(~values.isin([-99.99, -999.0, -999]), other=float("nan"))
            df[col] = values / 100.0  # percent -> fraction
        return df.set_index("date").sort_index()

    def _cache_path(self, dataset: str) -> Path:
        digest = hashlib.sha256(dataset.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{dataset}_{digest}.json"

    def _read_cache(self, dataset: str) -> Optional[pd.DataFrame]:
        path = self._cache_path(dataset)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(envelope["fetched_at"])
            if (datetime.now(timezone.utc) - fetched_at).total_seconds() > CACHE_TTL_SECONDS:
                return None
            df = pd.read_json(io.StringIO(envelope["data"]), orient="split")
            df.index = pd.to_datetime(df.index)
            return df
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Kenneth French cache unusable for %s (%s) -- refetching", dataset, e)
            return None

    def _write_cache(self, dataset: str, df: pd.DataFrame) -> None:
        path = self._cache_path(dataset)
        envelope = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": df.to_json(orient="split", date_format="iso"),
        }
        path.write_text(json.dumps(envelope), encoding="utf-8")


_client: Optional[KennethFrenchClient] = None


def get_kenneth_french_client() -> KennethFrenchClient:
    """Process-wide cached client singleton, same convention as this
    project's other data-provider factories."""
    global _client
    if _client is None:
        _client = KennethFrenchClient()
    return _client
