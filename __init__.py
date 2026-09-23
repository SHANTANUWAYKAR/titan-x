"""PROJECT TITAN-X — Institutional-Grade Trading Intelligence Platform."""

__version__ = "1.0.0"
__author__ = "Shantanu Waykar"

# ---------------------------------------------------------------------------
# Opt in to pandas' future downcasting behaviour, once, at import.
#
# WHY. A single sweep emitted 2,214 FutureWarnings ("Downcasting object dtype
# arrays on .fillna ... is deprecated and WILL CHANGE in a future version"),
# from 351 `.fillna(False)` sites across 77 strategy files. Two costs: the flood
# buries real errors in every sweep log, and the behaviour silently changes the
# day pandas 3 lands.
#
# WHY NOT FIX THE CALL SITES. Measured, not assumed -- each candidate fix was
# tested against an object-dtype series containing NaN:
#
#   .fillna(False).astype(bool)          still warns (fires INSIDE fillna)
#   .fillna(False).infer_objects(...)    still warns -- and this is the fix
#                                        pandas' own message recommends
#   .astype(bool).fillna(False)          NaN becomes True: WRONG VALUES
#   this option                          no warning, values correct
#
# So editing 351 sites would have been churn at best and a correctness bug at
# worst. Opting in is the only thing that actually works, and it surfaces any
# breakage in today's test run rather than after a pandas upgrade.
#
# The trade: fillna on object dtype now RETURNS object dtype instead of
# silently downcasting. Boolean ops still work; where a bool dtype is wanted,
# call .astype(bool) explicitly.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - a pandas without this option must not break import
    import pandas as _pd

    _pd.set_option("future.no_silent_downcasting", True)
except Exception:  # noqa: BLE001
    pass
