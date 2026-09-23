"""
Module: experiment.py
Description: Permanent research lineage — `reports/upgrade statergy.txt`
    PHASE 8 (every strategy carries ids), PHASE 24 (research database) and
    PHASE 29 (reproducibility), raised as **P1.1** in
    docs/INSTITUTIONAL_AUDIT.md.

    THE GAP THIS CLOSES. `grep -rln "experiment_id\\|mlflow\\|run_id"` across
    `engines/` and `core/` returned nothing. The project has scored 98,546
    candidates, run three synthetic-null campaigns and promoted two strategies
    to live trading, and not one of those results records the code or the data
    that produced it. PHASE 29 asks that a historical backtest be reproducible
    from its experiment ID; nothing here could be.

    NOT A SECOND CATALOG. `core/catalog.py` already versions datasets — source,
    row count, date range, SHA-256 checksum, and a version counter that
    increments on every re-fetch. `data_version()` reads from it rather than
    re-checksumming, so an experiment's data provenance and the platform's own
    dataset history can never disagree.

    THE DIRTY-TREE FLAG IS THE POINT. A git SHA alone implies reproducibility
    it does not deliver: this repository currently has 269 modified files
    against `992f8f6`, so "run at 992f8f6" would be actively misleading for
    anything run today. `code_version()` records the SHA, whether the tree was
    dirty, and how many files differed — and `ExperimentRecord.reproducible`
    is False whenever it was dirty. An experiment that cannot be reproduced
    should say so in its own record rather than leave the reader to discover it.

    APPEND-ONLY, NEVER OVERWRITTEN. Non-negotiables 8, 9 and 15 forbid hiding
    failed research, deleting negative results, and silently changing
    historical ones. Records go to an append-only JSONL and `record()` REFUSES
    a duplicate experiment_id rather than replacing it — the same discipline as
    the forward-test log, for the same reason.

    A CONCLUSION IS REQUIRED. PHASE 24 lists `conclusion` alongside the
    metrics, and it is the field that makes the log worth keeping: a bare
    metrics dump is what the sweep reports already are. `record()` rejects an
    empty conclusion, which also means a failed experiment gets written up as a
    failure instead of quietly not being recorded at all.

    WHAT IS NOT BACKFILLED. The 98,546 already-scored candidates are NOT
    retroactively given experiment records. Their code and data versions are
    genuinely unknown, and inventing plausible ones would manufacture exactly
    the provenance this module exists to establish. They stay as they are, and
    `docs/INSTITUTIONAL_AUDIT.md` says so.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = _ROOT / "data" / "models" / "e24_strategy_research" / "experiments.jsonl"

# Experiment kinds this project actually runs. Not an enum: an unrecognised
# kind is recorded with a warning rather than refused, because losing a real
# experiment to a vocabulary mismatch is worse than an untidy `kind` field.
KNOWN_KINDS = (
    "sweep",            # a parameter grid over one instrument/timeframe
    "null_campaign",    # a synthetic no-edge null calibration
    "score",            # scoring/leaderboard build over existing candidates
    "forward_test",     # a forward-test evaluation
    "ablation",         # concept/feature removal study
    "robustness",       # perturbation / stress study
    "deployment",       # a change to whether a strategy drives live signals
)


class ExperimentIntegrityError(RuntimeError):
    """A record was rejected because writing it would corrupt the lineage."""


@dataclass
class ExperimentRecord:
    experiment_id: str
    created_at: str
    kind: str
    title: str
    conclusion: str
    code_version: dict = field(default_factory=dict)
    data_version: dict = field(default_factory=dict)
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    strategy: Optional[str] = None
    params: dict = field(default_factory=dict)
    periods: dict = field(default_factory=dict)
    execution_assumptions: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    artifacts: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def reproducible(self) -> bool:
        """True only when the tree was clean AND a data version was captured.

        Both halves are required: a clean SHA with unknown input data does not
        let anyone re-run this, and neither does known data at an unknown
        revision.
        """
        return bool(
            self.code_version.get("git_sha")
            and self.code_version.get("dirty") is False
            and self.data_version.get("checksum")
        )

    def why_not_reproducible(self) -> list[str]:
        """Specific reasons, so the record states its own limits."""
        out = []
        if not self.code_version.get("git_sha"):
            out.append("no git revision was recorded")
        elif self.code_version.get("dirty"):
            n = self.code_version.get("dirty_file_count")
            out.append(
                f"the working tree was dirty ({n} file(s) differed from "
                f"{self.code_version.get('git_sha')}), so the revision alone does not "
                f"reconstruct the code that ran"
            )
        if not self.data_version.get("checksum"):
            out.append("no dataset checksum was recorded, so the exact input is unidentified")
        return out


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def code_version(root: Path | None = None) -> dict:
    """Current git revision plus an honest dirtiness flag.

    Returns `{}` when git is unavailable rather than inventing a version — an
    absent provenance field is a fact; a fabricated one is a lie that survives
    in the record forever.
    """
    r = Path(root) if root else _ROOT
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(r),
            capture_output=True, text=True, timeout=10,
        )
        if sha.returncode != 0:
            return {}
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(r),
            capture_output=True, text=True, timeout=30,
        )
        changed = [l for l in status.stdout.splitlines() if l.strip()] if status.returncode == 0 else []
        return {
            "git_sha": sha.stdout.strip(),
            "dirty": bool(changed),
            "dirty_file_count": len(changed),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("experiment: could not read git revision (%s)", e)
        return {}


def data_version(symbol: str, timeframe: str) -> dict:
    """Dataset provenance for this instrument, read from `core.catalog`.

    Deliberately delegates: the catalog already records source, rows, date
    range, SHA-256 checksum and a version counter on every fetch. Re-deriving
    any of that here would let an experiment's provenance drift from the
    platform's own dataset history.
    """
    try:
        from project_titan_x.core.catalog import get_catalog
        catalog = get_catalog()
        entry = catalog.get_dataset(symbol, timeframe)
        if not entry:
            # The catalog is keyed by YAHOO symbol ("ETH-USD") while sweep
            # reports and overrides use the registry symbol ("ETHUSD"). Without
            # resolving both spellings, half the callers silently record no
            # data provenance at all -- and an absent checksum then makes every
            # such experiment report itself as not reproducible for the wrong
            # reason. Measured: data_version("ETHUSD", "1d") returned {} while
            # data_version("ETH-USD", "1d") returned a full record.
            from project_titan_x.core.config import list_assets
            for a in list_assets():
                if symbol in (a.symbol, a.yahoo_symbol):
                    entry = catalog.get_dataset(a.yahoo_symbol, timeframe) or \
                            catalog.get_dataset(a.symbol, timeframe)
                    break
    except Exception as e:  # noqa: BLE001
        logger.warning("experiment: catalog unavailable for %s %s (%s)", symbol, timeframe, e)
        return {}
    if not entry:
        return {}
    return {
        "dataset_id": entry.get("dataset_id"),
        "source": entry.get("source"),
        "rows": entry.get("rows"),
        "date_range": entry.get("date_range"),
        "checksum": entry.get("checksum"),
        "catalog_version": entry.get("version"),
        "fetched_at": entry.get("fetched_at"),
    }


def new_experiment_id(kind: str, now: Optional[datetime] = None) -> str:
    """Sortable, human-readable, collision-resistant: `kind-YYYYmmddTHHMMSS-xxxxxx`."""
    stamp = (now or _utcnow()).strftime("%Y%m%dT%H%M%S")
    return f"{kind}-{stamp}-{uuid.uuid4().hex[:6]}"


def load(log_path: Path | None = None) -> list[ExperimentRecord]:
    """Every recorded experiment, oldest first."""
    p = Path(log_path) if log_path else DEFAULT_LOG_PATH
    if not p.exists():
        return []
    fields = set(ExperimentRecord.__dataclass_fields__)
    out: list[ExperimentRecord] = []
    with p.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
                out.append(ExperimentRecord(**{k: v for k, v in doc.items() if k in fields}))
            except (json.JSONDecodeError, TypeError) as e:
                # One malformed line must not cost the whole research history.
                logger.warning("experiment: skipping unreadable line %d of %s (%s)", lineno, p, e)
    return out


def get(experiment_id: str, log_path: Path | None = None) -> Optional[ExperimentRecord]:
    """One experiment by id — PHASE 29's 'reproducible from its experiment ID'."""
    for rec in load(log_path):
        if rec.experiment_id == experiment_id:
            return rec
    return None


def record(
    *,
    kind: str,
    title: str,
    conclusion: str,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    strategy: Optional[str] = None,
    params: Optional[dict] = None,
    periods: Optional[dict] = None,
    execution_assumptions: Optional[dict] = None,
    metrics: Optional[dict] = None,
    artifacts: Optional[list] = None,
    notes: Optional[list] = None,
    experiment_id: Optional[str] = None,
    log_path: Path | None = None,
    now: Optional[datetime] = None,
    capture_versions: bool = True,
) -> ExperimentRecord:
    """Append one experiment to the permanent research log.

    Raises ExperimentIntegrityError on an empty conclusion or a duplicate
    experiment_id. Both raise rather than return a status: a silently dropped
    experiment is indistinguishable from one that was never run, which is the
    failure this module exists to prevent.
    """
    if not (conclusion or "").strip():
        raise ExperimentIntegrityError(
            "An experiment needs a conclusion. PHASE 24 requires one, and without it this "
            "log is only a second copy of the metrics the sweep reports already hold. If the "
            "experiment failed, that IS the conclusion -- record it (non-negotiables 8 and 9 "
            "forbid hiding failed research)."
        )

    p = Path(log_path) if log_path else DEFAULT_LOG_PATH
    at = now or _utcnow()
    eid = experiment_id or new_experiment_id(kind, at)

    if kind not in KNOWN_KINDS:
        logger.warning("experiment: unrecognised kind %r (recording anyway); known: %s",
                       kind, list(KNOWN_KINDS))

    for existing in load(p):
        if existing.experiment_id == eid:
            raise ExperimentIntegrityError(
                f"experiment_id {eid!r} already exists. Research lineage is append-only -- "
                f"overwriting a recorded experiment would silently change a historical "
                f"result (non-negotiable 15). Record a new experiment instead."
            )

    rec = ExperimentRecord(
        experiment_id=eid,
        created_at=at.isoformat(),
        kind=kind,
        title=title,
        conclusion=conclusion.strip(),
        code_version=code_version() if capture_versions else {},
        data_version=(data_version(symbol, timeframe)
                      if capture_versions and symbol and timeframe else {}),
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy,
        params=dict(params or {}),
        periods=dict(periods or {}),
        execution_assumptions=dict(execution_assumptions or {}),
        metrics=dict(metrics or {}),
        artifacts=list(artifacts or []),
        notes=list(notes or []),
    )

    # The record states its own reproducibility limits, so a future reader does
    # not have to infer them from a bare SHA.
    for reason in rec.why_not_reproducible():
        rec.notes.append(f"NOT REPRODUCIBLE: {reason}")

    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(rec), default=str) + "\n")

    logger.info("experiment: recorded %s (%s) -- reproducible=%s",
                eid, title, rec.reproducible)
    return rec


def record_deployment_change(
    *,
    symbol: str,
    timeframe: str,
    strategy: str,
    previous_status: Optional[str],
    new_status: str,
    reason: str,
    evidence: Optional[dict] = None,
    log_path: Path | None = None,
) -> Optional[ExperimentRecord]:
    """Record a change to whether a strategy drives LIVE signals.

    This is PHASE 26's "audit logging" in the form that matters for this
    platform. A `stage0.status` tag is the single thing standing between a
    search result and real money, and until now flipping one was an
    unrecorded file write: nothing could answer "when did this go live, and on
    what evidence", which is exactly the question worth asking after a loss.

    Deliberately reuses the experiment log rather than opening a third
    append-only store. A deployment IS an event in a strategy's research
    lineage -- the one where the research stopped being hypothetical -- and
    splitting it into its own file would mean reconstructing a strategy's
    history from two places.

    Returns None (never raises) when the status has not actually changed, so
    callers can invoke it unconditionally on every tagging run without padding
    the log with no-ops.
    """
    if previous_status == new_status:
        return None
    went_live = new_status == "VALIDATED"
    try:
        return record(
            kind="deployment",
            title=f"{symbol} {timeframe} {strategy}: {previous_status or 'untagged'} -> {new_status}",
            symbol=symbol,
            timeframe=timeframe,
            strategy=strategy,
            metrics=dict(evidence or {}),
            conclusion=(
                f"{'PROMOTED TO LIVE' if went_live else 'WITHDRAWN FROM LIVE'}: {reason}"
            ),
            notes=[
                "A deployment change is reversible: the tag is data, not code.",
                ("This strategy now drives real signals."
                 if went_live else
                 "This strategy no longer drives signals; the baseline composite rule applies."),
            ],
            log_path=log_path,
        )
    except Exception as e:  # noqa: BLE001 - auditing must never block the change
        # itself; a missing audit line is bad, a tagging run that dies halfway
        # leaving some overrides tagged and others not is worse.
        logger.warning("experiment: could not audit deployment change for %s %s (%s)",
                       symbol, timeframe, e)
        return None


def deployment_history(
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    log_path: Path | None = None,
) -> list[ExperimentRecord]:
    """Every recorded change to live status, oldest first, optionally filtered."""
    return [
        r for r in load(log_path)
        if r.kind == "deployment"
        and (symbol is None or r.symbol == symbol)
        and (timeframe is None or r.timeframe == timeframe)
    ]


def summarise(log_path: Path | None = None) -> dict:
    """Counts by kind and reproducibility, for reporting."""
    recs = load(log_path)
    by_kind: dict[str, int] = {}
    for r in recs:
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
    reproducible = sum(1 for r in recs if r.reproducible)
    return {
        "total": len(recs),
        "by_kind": by_kind,
        "reproducible": reproducible,
        "not_reproducible": len(recs) - reproducible,
        "first": recs[0].created_at if recs else None,
        "last": recs[-1].created_at if recs else None,
    }
