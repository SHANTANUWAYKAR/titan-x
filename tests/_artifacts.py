"""Skip guards for tests that need artifacts the repository deliberately omits.

WHY THIS EXISTS. `data/` ships empty: ~1.8 GB of market data, model artefacts
and calibration files, regenerable by the fetch/sweep scripts, some of it not
ours to redistribute, and four files over GitHub's 100 MB limit. A number of
tests assert *calibrated* behaviour -- a real HMM winner for GOLD, a real
per-asset volatility multiplier, real springs and upthrusts in real bars -- and
that behaviour is only reachable when the artefact is present.

Without a guard those tests fail on any fresh clone, so a new contributor's
first `pytest` run reports 21 failures that have nothing to do with their
change. Skipping with a reason that names the missing file is the honest
outcome: it says "not verified here" rather than either fabricating a pass or
crying wolf.

This mirrors the existing `network` marker, which excludes tests that hit live
rate-limited endpoints for the same reason -- unrelated to the change under
review.

The guards are deliberately `skipif`, NOT `xfail`. With the artefact present --
in the maintainer's working copy, or after `scripts/fetch_all_data.py` -- these
tests run and must pass. An `xfail` would hide a real regression there.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# tests/_artifacts.py -> tests/ -> repository root
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data"


def data_path(*parts: str) -> Path:
    """Absolute path to an artefact under `data/`."""
    return DATA_ROOT.joinpath(*parts)


def requires_data(*relative: str):
    """Skip unless every named path under `data/` exists.

    Paths are given relative to `data/`, e.g.
    `requires_data("processed/AAPL_1d.parquet")`.
    """
    missing = [rel for rel in relative if not data_path(*rel.split("/")).exists()]
    return pytest.mark.skipif(
        bool(missing),
        reason=(
            "needs data/ artefact(s) not shipped in this repository: "
            + ", ".join(missing)
            + " -- regenerate with scripts/fetch_all_data.py"
        ),
    )


def requires_data_glob(pattern: str, *, under: str = ""):
    """Skip unless at least one file matches `pattern` under `data/<under>`.

    For tests that need *some* calibration artefact rather than one named file.
    """
    base = data_path(*under.split("/")) if under else DATA_ROOT
    found = bool(list(base.glob(pattern))) if base.is_dir() else False
    return pytest.mark.skipif(
        not found,
        reason=(
            f"needs a data/{under + '/' if under else ''}{pattern} artefact, "
            "none present in this repository -- regenerate with the sweep scripts"
        ),
    )


def _postgres_reachable() -> bool:
    """True if the project's Postgres is actually accepting connections.

    Probed with a plain socket rather than by importing the DB layer: this runs
    at collection time, and a failed import here would error the whole module
    instead of skipping one test.
    """
    import socket

    for host, port in (("127.0.0.1", 5433), ("localhost", 5433)):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            continue
    return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason=(
        "needs the project Postgres on 127.0.0.1:5433 -- start it with "
        "deployment/docker-compose.yml"
    ),
)
