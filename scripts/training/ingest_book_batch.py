"""
Module: ingest_book_batch.py
Description: Batch runner for data/books/NOT READED BOOKS -> Engine 01's
    real ingestion pipeline -> data/books/READ BOOKS (only files that
    actually ingest without error are moved; zero-byte/corrupt files are
    left in place and reported, never silently skipped or fabricated as
    successes).

    WRITES TO data/knowledge/chroma_db_overflow, NOT the main
    data/knowledge/chroma_db (changed 2026-09-14, see main()'s own
    comment at the persist_dir/overflow_dir assignment for the full
    reproduction). The main collection's writes are confirmed broken at
    this project's real scale (2,212,628 embeddings, same root defect
    class as the already-documented .get()/.count()/.query() native
    crashes -- see document_store.py's CombinedDocumentStore docstring,
    2026-08-05). New books land in a second, small, separately-persisted
    store instead, merged into search results at query time by
    engine.py's CombinedDocumentStore wiring -- exactly the pattern
    already established there for YouTube-extracted knowledge. A book
    ingested here is visible to the live knowledge base on the next
    server start, same as before; it's just reading from a second store
    now, transparently to every caller.

    Parallel parse, sequential write: PDF loading (PyMuPDF text extraction +
    pdfplumber's table-extraction pass, see loaders.load_pdf) and chunking
    are pure CPU-bound work with no shared state, so they run in a
    ProcessPoolExecutor across multiple books at once. Embedding + the
    actual Chroma/FAISS/BM25 writes stay strictly sequential in the main
    process -- Chroma's persistent store is SQLite-backed and does not
    support safe concurrent multi-process writes, so parallelizing that
    part would risk corrupting the shared production knowledge base. This
    still captures nearly all the real wall-clock win: the table-scan pass
    is the dominant per-book cost, and it never touches the store.

    Processes files in fixed-size waves (--wave-size) rather than the whole
    corpus in one shot, per explicit instruction to batch (~150 at a time)
    rather than process everything in a single run. Resumable: skips any
    file whose doc_id (sha256 of its resolved path, same formula
    IngestionPipeline.ingest_file uses internally) already has chunks in
    the store, so re-running after an interruption is cheap and safe, and
    a folder that grows between runs (more books added) is picked up
    automatically -- SRC_DIR is rescanned fresh on every invocation.
Author: Shantanu Waykar
Version: 2.0.0
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

# Deliberately ONLY the lightweight ingestion modules at top level (models.py
# has zero third-party deps; chunking.py depends only on models.py; loaders.py
# needs pymupdf/pdfplumber/docx/ebooklib/bs4/trafilatura). IngestionPipeline
# (-> DocumentStore -> chromadb/faiss/sentence-transformers/torch) is
# deliberately imported LOCALLY inside main(), not here -- on Windows,
# ProcessPoolExecutor's spawn re-executes this module's ENTIRE top level in
# every worker process to reconstruct __main__, so anything imported here
# gets paid for in every worker even though _load_and_chunk() never touches
# the store. Keeping the heavy chain out of module scope means workers only
# pay for what they actually use.
from project_titan_x.engines.e01_knowledge.chunking import chunk_document  # noqa: E402
from project_titan_x.engines.e01_knowledge.loaders import load_document, _openable_path  # noqa: E402
from project_titan_x.engines.e01_knowledge.models import Chunk, DocumentMetadata, DocumentType  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# Mirrors ingestion.py's _SUFFIX_TO_DOC_TYPE exactly -- duplicated (rather
# than imported from ingestion.py) specifically to keep that module's heavy
# transitive imports out of worker processes. Small, stable mapping; low
# drift risk.
_SUFFIX_TO_DOC_TYPE = {
    "pdf": DocumentType.PDF,
    "epub": DocumentType.EPUB,
    "docx": DocumentType.DOCX,
    "txt": DocumentType.TXT,
    "html": DocumentType.HTML,
    "htm": DocumentType.HTML,
    "md": DocumentType.MARKDOWN,
    "markdown": DocumentType.MARKDOWN,
}

# Files per wave and worker processes per wave. Originally set to 10/10
# (matching this machine's 12 logical cores), but a real run hit repeated
# "DLL load failed... the paging file is too small" failures -- this
# machine has only ~15.3GB RAM, and 10 concurrent PyMuPDF+pdfplumber
# workers parsing large economics textbooks (some 100s of MB, with
# image/table-heavy pages) collectively committed ~40GB of virtual memory,
# well past what the system could actually back. Dropped to WORKERS=3 at
# the time (reliability over raw speed per the explicit "read all books
# proper, without any mistake" instruction). Bumped to 5 on 2026-07-23
# after the page file was moved from auto-managed to a fixed 16-48GB --
# real extra headroom, not just a hope, so a moderate increase over 3 is
# reasonable; staying well under the original 10 that actually crashed
# rather than assuming the page file alone makes any worker count safe.
WAVE_SIZE = 1
# Dropped from 5 to 1 on 2026-07-30 after a real structural finding: within
# one wave, a single persistent worker process (WORKERS=1) handles all
# WAVE_SIZE books' parse calls sequentially without releasing memory back to
# the OS between them (confirmed directly -- isolated testing showed a
# second file's baseline memory started from where the first file's ended,
# not from a clean baseline). A "fresh ProcessPoolExecutor per wave" only
# resets memory BETWEEN waves, so a larger WAVE_SIZE meant more accumulation
# before that reset. WAVE_SIZE=1 forces the reset after every single book --
# the tightest possible memory-reset cadence, directly targeting the
# multi-hour repeating stalls this caused.
# Dropped back to 3 on 2026-07-29 after a real near-crash: at WORKERS=5, two
# workers processing unusually large/image-heavy PDFs simultaneously ballooned
# to 2.5-2.9GB each, and system-wide free memory measured (via
# Win32_OperatingSystem.FreePhysicalMemory) dropped to 382MB out of 16GB --
# real danger of the whole system becoming unstable, not a hypothetical. The
# fixed 16-48GB page file (see the 2026-07-23 note below) provides swap
# headroom but doesn't prevent a burst of several large-PDF workers landing in
# the same wave from spiking real physical memory this hard. 3 concurrent
# workers bounds the worst case to a smaller multiple of any one pathological
# PDF's footprint.
# Tried bumping both WORKERS and WAVE_SIZE to 3 on 2026-07-30, on the
# hypothesis that MAX_SAFE_SIZE_BYTES (below) already excludes every file
# that ever tripped the memory guard, so the old "several large PDFs land
# in one wave together" failure mode couldn't recur even at WORKERS=3.
# Free memory measured healthy (6.3GB/15.6GB) immediately before the
# change. Tested it live rather than trusting the hypothesis: the very
# FIRST WORKERS=3 wave (3 unremarkable sub-20MB books, nothing like the
# excluded cluster) drove free memory from 6.3GB to 1.9GB in under 90
# seconds, tripping the watchdog's guard on its first run. That's real,
# measured evidence the hypothesis was wrong -- something about 3
# concurrent PyMuPDF/pdfplumber/embedding workers costs far more than 3x
# a single worker's footprint on this machine, size-filtering alone
# doesn't fix it. Reverted back to 1/1 the same session, per the standing
# "reliability over raw speed" instruction -- do not re-attempt this bump
# without a real per-worker memory measurement first (isolated, like the
# WAVE_SIZE cross-book test above), not just a queue-size argument.
WORKERS = 1
MAX_SAFE_SIZE_BYTES = 50_000_000  # 50MB -- observed real cluster of 65-100MB
# image/chart-heavy trading books (Encyclopedia of Chart Patterns-style) that
# individually exceeded safe memory headroom. This is a real, measured
# threshold, not a guess: every file that tripped the memory guard was
# 65MB+; every book processed successfully so far (at the time this
# threshold was set) was well under this.
#
# No longer a permanent defer, as of 2026-09-14: 6 real books hit this gate
# and sat in NOT READED BOOKS forever, every single ingestion run, since
# nothing else in this script ever revisits them (confirmed live: "35.
# Easy Trading Book...", "51 Trading Strategies...", "62. Mastering the
# Stock Market...", plus 3 large academic textbooks, all logged as
# deferred on every single wave for hours). Measuring WHY each is large
# (size_bytes / page_count) showed two real, different cases: the 3
# textbooks (897-1264 pages) are large from page COUNT at ordinary
# 52-93KB/page density -- exactly what MAX_SAFE_PAGES's slicing already
# handles safely elsewhere in this file. The trading books are large from
# PER-PAGE IMAGE DENSITY (174KB-2.1MB/page) at moderate-to-low page counts
# -- MAX_SAFE_PAGES's flat 225-page slice size would still pull tens of
# MB of images into one pass for these. TARGET_SLICE_BYTES below adapts
# the slice size to the file's own measured density instead of assuming
# one flat page count is safe for every book -- see
# _adaptive_pages_per_slice.
TARGET_SLICE_BYTES = 15_000_000  # 15MB/slice -- well under the 147-553MB
# peak RSS already directly measured safe for a 225-page/moderate-density
# slice (see MAX_SAFE_PAGES's own comment history), leaving real headroom
# for the fact that these oversized files are, by definition, denser per
# page than the books that measurement was taken from.

# Real finding 2026-07-30: file size on disk does NOT reliably predict
# parsing cost. "Making Economic Sense" [Rothbard 2006] is only 5.6MB --
# comfortably under MAX_SAFE_SIZE_BYTES -- but has 381 pages, and measuring
# it directly (isolated _load_and_chunk call) showed it actually costs
# 1.7GB RSS and 60s to parse+chunk (pdfplumber's table-extraction pass
# scales with page count, not file size). This ONE file sat at the front
# of the queue and silently ate every single-book wave for 45+ minutes
# before anyone noticed it wasn't just ambient system contention.
# Tightened from 350 to 200 on 2026-07-31 after a real, now 4-for-4
# pattern: every single book directly measured in the 200-380 page range
# that night turned out to be a landmine (Rothbard 381pg/1.7GB/60s,
# "A Modern Migration Theory" 258pg/1.4GB/47s, "Monetary Regimes and
# Inflation" 225pg/1.7GB/61s, "Pioneers of Industrial Organization"
# 342pg/2.2GB/53s) -- all dense academic-press economics texts, all
# individually confirmed via isolated _load_and_chunk measurement, not
# guessed.
# Raised 200 -> 220 on 2026-08-01 after the deferred-queue's remaining
# candidates were surveyed (all 78 books left in NOT READED BOOKS were
# above this cutoff) and the 200-220 band was directly re-measured, now
# with the machine otherwise idle: 203pg/848MB/179s, 208pg/795MB/73s,
# 210pg/916MB/82s, 210pg/816MB/80s -- all real, moderate costs (comparable
# to other already-ingested "moderately expensive" books), clearly below
# the 225pg+ landmine tier above (1.4-2.2GB).
# Raised 220 -> 225 the same day after measuring the next band up: two
# real 225pg books both landed at 650-717MB peak heap, consistent with
# the 200-220 tier. But 235pg/238pg/245pg books measured RIGHT AFTER them
# all jumped to 1057-1224MB peak heap -- a clear, real step change, not
# noise (3-for-3, all comfortably above the ~600MB main-process baseline
# this laptop already carries, meaning a 235pg+ book risks ~1.6-1.8GB
# total process memory against a 1GB free-memory guard). 225 is the
# precise line this data supports; do not extend to 235+ without new
# evidence that specifically contradicts this 3-for-3 result.
MAX_SAFE_PAGES = 225

# Generous headroom above the 1239.8s observed for this corpus's slowest
# real file so far -- bounds worst-case stall from a pathological PDF to
# one wave's timeout instead of an indefinite hang. A fresh ProcessPoolExecutor
# per wave (not shared across waves): a timed-out task's OS process is
# abandoned (can't cleanly cancel in-flight work), and reusing the same pool
# across waves would leave that slot permanently unavailable for every
# subsequent wave.
WAVE_TIMEOUT_SECONDS = 1800

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
SRC_DIR = DATA_ROOT / "books" / "NOT READED BOOKS"
DST_DIR = DATA_ROOT / "books" / "READ BOOKS"
SKIP_DIR = DATA_ROOT / "books" / "SKIPPED (not relevant or duplicate)"
REPORT_DIR = DATA_ROOT / "knowledge" / "ingestion_batch_reports"

# Added 2026-07-30 per explicit instruction: before spending a full
# parse+embed+store pass on a book, check its title + index/table-of-
# contents first and leave (skip, don't ingest) anything that clearly
# isn't going to be useful. Deliberately broad and generous -- this
# platform's scope isn't just the 20 currently-implemented engines, it's
# the full MASTER_PROMPT.md 1-50 roster including engines not yet built
# (Alternative Data, Feature Engineering, Forecasting, Scenario Analysis,
# Capital Allocation, Model Risk Management, Governance, Execution
# Intelligence -- see CLAUDE.md's roster table). A book only gets skipped
# if NONE of these terms appear anywhere in its title or first 20 pages --
# when in doubt, this list is written to keep the book, not skip it, since
# a wrongly-skipped valuable book is a worse failure than an occasional
# irrelevant book getting fully processed anyway.
_RELEVANT_KEYWORDS = [
    # markets / trading / instruments
    "trading", "trader", "market", "stock", "equity", "equities", "bond", "forex", "currency",
    "commodity", "commodities", "futures", "option", "derivative", "crypto", "bitcoin",
    "hedge fund", "portfolio", "asset allocation", "capital market", "wall street",
    "exchange", "broker", "security", "securities",
    # economics / macro
    "economic", "economics", "economy", "macroeconomic", "microeconomic", "monetary",
    "fiscal", "inflation", "gdp", "interest rate", "central bank", "recession", "business cycle",
    # finance / valuation / accounting
    "finance", "financial", "valuation", "balance sheet", "income statement", "cash flow",
    "accounting", "corporate finance", "investment", "investing", "investor", "wealth",
    # quant / statistics / data science / ML (covers not-yet-built engines too:
    # Feature Engineering, Forecasting, Alpha Research Factory, Learning Engine,
    # Meta-Learning, Model Risk Management, Adversarial Testing)
    "quantitative", "statistics", "statistical", "probability", "regression", "econometrics",
    "machine learning", "deep learning", "neural network", "artificial intelligence",
    "data science", "algorithm", "backtest", "time series", "forecasting", "forecast", "prediction",
    "reinforcement learning", "feature engineering", "model risk", "adversarial",
    "risk management", "value at risk", "volatility", "sharpe", "kelly criterion",
    "portfolio optimization", "factor model", "alpha", "beta", "capital allocation",
    # market structure / behavior / psychology
    "technical analysis", "fundamental analysis", "chart pattern", "candlestick",
    "market microstructure", "order book", "liquidity", "sentiment", "behavioral finance",
    "psychology of trading", "trading psychology", "cognitive bias", "decision making",
    "game theory", "negotiation",
    # broader/future-engine scope: alt data, scenario analysis, governance,
    # execution, credit/fixed income, crypto, commodities
    "alternative data", "scenario analysis", "stress test", "credit risk", "sovereign",
    "fixed income", "yield curve", "monetary policy", "central banking", "banking",
    "regulation", "compliance", "governance", "chief risk officer", "chief investment officer",
    "execution", "market making", "algorithmic trading", "high frequency", "strategy",
]


def _normalize_title_key(name: str) -> str:
    """Strips the ingestion hash tag and edition/author bracket noise down
    to a comparable core title -- e.g. "Macroeconomics (9th ed.) [Mankiw
    2016] {ABC12345}.pdf" and a re-downloaded copy of the same book with a
    different hash or edition note both normalize to "macroeconomics",
    letting the duplicate check recognize them as the same underlying
    book."""
    key = Path(name).stem
    key = re.sub(r"\{[0-9A-Fa-f]+\}", "", key)  # ingestion hash tag, e.g. {DD7BF291}
    key = re.sub(r"\([^)]*\)", "", key)  # (9th ed.)
    key = re.sub(r"\[[^\]]*\]", "", key)  # [Mankiw 2016]
    key = re.sub(r"[^a-z0-9]+", " ", key.lower()).strip()
    return key


def _safe_is_file(p: Path) -> bool:
    """p.is_file() silently returns False -- not an exception, just a
    wrong answer -- for a path Windows' legacy (non-long-path) stat API
    can't resolve (>260 chars without a \\\\?\\ prefix). Real bug found
    2026-09-14: this is what made a genuine 619-page book (263-char path)
    vanish from `all_files`/`candidates` entirely -- before _page_count,
    _index_check, or any per-file logic ever got a chance to run or log
    anything about it. See loaders.py's _openable_path docstring for the
    full chain (pymupdf.open() has the identical failure one layer
    deeper, fixed separately there). Tries the fast/common path first;
    only pays the long-path-prefixed fallback when the plain call says
    False, since this is the rare case, not the common one."""
    if p.is_file():
        return True
    try:
        return os.path.isfile(_openable_path(p))
    except OSError:
        return False


def _safe_size(p: Path) -> int:
    """p.stat().st_size, long-path-safe -- see _safe_is_file's docstring.
    Every size_bytes read in this script's main() goes through this
    instead of the bare .stat() call, so a long-path book doesn't crash
    the whole wave with an uncaught OSError the moment its size is
    needed, now that _safe_is_file lets it past the candidate filter."""
    try:
        return p.stat().st_size
    except OSError:
        return os.stat(_openable_path(p)).st_size


def _safe_move(src: Path, dst: Path) -> None:
    """shutil.move(), long-path-safe -- directly confirmed (isolated test,
    a real 286-char dummy path) that plain shutil.move() fails with the
    identical WinError 3 as every other unprefixed call on a >260-char
    path, and that prefixing BOTH the source and destination string with
    \\\\?\\ makes it succeed. Without this, a long-path book would parse
    and embed successfully (loaders.py/_page_count/_safe_is_file above
    all fixed) and then fail at the very last step, forever left in
    place instead of moved to READ BOOKS -- a partial fix that still
    looks broken from the outside. Tries the plain move first (the
    common, fast case); only pays the prefixed fallback for the rare
    long-path book."""
    try:
        shutil.move(str(src), str(dst))
    except OSError:
        shutil.move(_openable_path(src), _openable_path(dst))


def _page_count(path: Path) -> int:
    """Cheap page-count check via PyMuPDF -- reads only the document's own
    metadata, not page content, so it's fast even for a large file. A
    second, independent memory-cost signal alongside MAX_SAFE_SIZE_BYTES
    (see that constant's 2026-07-30 comment): file size on disk doesn't
    reliably predict parsing cost, page count does better for the specific
    pdfplumber table-extraction bottleneck.

    Real bug found and fixed 2026-09-14: the bare `except Exception: return
    0` here is exactly what made a real, existing 619-page book invisible
    for 65+ ingestion iterations across two overnight runs -- its path
    exceeded Windows' 260-char MAX_PATH, pymupdf.open() raised
    FileNotFoundError on a file that demonstrably exists, and this catch
    silently turned that into "0 pages", which then sailed through every
    downstream check as if it were a tiny book, never logged, never
    errored, never processed. _openable_path (loaders.py) fixes the actual
    open failure; kept as a real safety net for genuinely corrupt files,
    not as the mechanism that hides a class of real bugs."""
    import pymupdf

    try:
        doc = pymupdf.open(_openable_path(path))
        try:
            return doc.page_count
        finally:
            doc.close()
    except Exception:
        return 0


def _extract_front_matter_text(path: Path, max_pages: int = 20) -> str:
    """Cheap pre-check, NOT the real parse: opens with PyMuPDF only (no
    pdfplumber table pass, no chunking) and reads just the first max_pages,
    where a book's title page and table of contents/index almost always
    live. A small fraction of _load_and_chunk()'s real cost, so it's safe
    to run on every new candidate before committing a worker slot to the
    full pipeline."""
    import pymupdf

    try:
        doc = pymupdf.open(_openable_path(path))
        try:
            n = min(max_pages, doc.page_count)
            return "\n".join(doc[i].get_text() for i in range(n))
        finally:
            doc.close()
    except Exception:
        return ""


def _index_check(path: Path, existing_titles: dict[str, str]) -> tuple[bool, str]:
    """Returns (keep, reason). keep=False means "leave that book" -- move
    it to SKIP_DIR instead of running the full pipeline, per explicit
    instruction to check the index/title first and skip whatever isn't
    actually needed (off-topic for this platform's current AND future
    scope, or a duplicate of a book already ingested)."""
    key = _normalize_title_key(path.name)
    if key in existing_titles:
        return False, f"duplicate of already-read '{existing_titles[key]}'"

    haystack = (path.stem + "\n" + _extract_front_matter_text(path)).lower()
    if any(kw in haystack for kw in _RELEVANT_KEYWORDS):
        return True, ""
    return False, "no finance/trading/economics/quant keywords found in title or first 20 pages"


def _doc_id_for(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]


class WorkItem(NamedTuple):
    """One unit of parse+embed+store work submitted to a wave. For a book
    at or under MAX_SAFE_PAGES this is the whole document (start_page=0,
    end_page=None). For a book over that limit, added 2026-08-01: instead
    of deferring the whole book forever, it's split into consecutive
    MAX_SAFE_PAGES-sized slices (see _book_slices), each processed as its
    own WorkItem with its own doc_id across separate waves -- the physical
    file only gets moved to READ BOOKS once every slice has a chunk in the
    store (see the move logic in main())."""
    path: Path
    doc_id: str
    start_page: int
    end_page: int | None  # None = whole document, unsliced
    slice_label: str  # "" for a whole-book item, else "slice i/N (pages A-B)" for logging/report clarity


def _book_slices(total_pages: int, pages_per_slice: int = MAX_SAFE_PAGES) -> list[tuple[int, int]]:
    """Splits a book into consecutive [start, end) page ranges, each
    <= pages_per_slice pages, covering the whole book with no gaps or
    overlaps. Real per-slice cost was directly measured on a 510-page book
    (see MAX_SAFE_PAGES's comment history): three MAX_SAFE_PAGES-sized
    slices cost 147-553MB peak each, the same moderate-cost profile as a
    small whole book -- comfortably safe, versus loading all 510 pages in
    one pass which is exactly the kind of landmine this threshold exists
    to avoid.

    pages_per_slice defaults to MAX_SAFE_PAGES (every existing caller's
    behavior, unchanged) but is overridable -- see
    _adaptive_pages_per_slice, added 2026-09-14 for oversized-by-bytes
    books where a flat page count isn't the right budget (a handful of
    image-dense pages can cost as much as MAX_SAFE_PAGES ordinary ones)."""
    return [(s, min(s + pages_per_slice, total_pages)) for s in range(0, total_pages, pages_per_slice)]


def _adaptive_pages_per_slice(size_bytes: int, total_pages: int) -> int:
    """Slice size (in pages) for a book that exceeded MAX_SAFE_SIZE_BYTES,
    added 2026-09-14 -- see MAX_SAFE_SIZE_BYTES's own comment for why a
    permanent defer wasn't acceptable. Targets a roughly constant memory
    footprint per slice (TARGET_SLICE_BYTES of raw PDF) by dividing it by
    this SPECIFIC book's own measured average bytes/page, rather than
    assuming every book's pages cost the same to parse -- the same
    per-book measurement (size_bytes / page_count) that revealed these
    files fall into two different real cases (see MAX_SAFE_SIZE_BYTES's
    comment) drives the slice size here too. Capped at MAX_SAFE_PAGES so a
    large but sparse (low bytes/page) oversized book never gets a BIGGER
    slice than the flat threshold already proven safe for ordinary books."""
    avg_bytes_per_page = size_bytes / max(total_pages, 1)
    return max(1, min(MAX_SAFE_PAGES, int(TARGET_SLICE_BYTES / max(avg_bytes_per_page, 1))))


def _slice_doc_id_for(path: Path, start: int, end: int) -> str:
    """Distinct store identity per page-range slice of the same physical
    file, so known_doc_ids / the resumability logic tracks each slice's
    completion independently -- a book can be interrupted partway through
    its slices (segfault, memory guard, restart) and resume exactly where
    it left off, same as the existing whole-book resumability."""
    return hashlib.sha256(f"{path.resolve()}::pages[{start}:{end})".encode()).hexdigest()[:16]


def _known_doc_ids_via_sql(persist_dir: Path) -> set[str]:
    """Real bug found 2026-07-24: constructing a full DocumentStore (even
    with the KnowledgeGraph rebuild already skipped) still pays its
    _rehydrate() cost -- deserializing the entire FAISS index + BM25
    corpus for 1.7M+ chunks into memory, ~30-45s, just to answer "which
    doc_ids already exist" for the skip-duplicate check. This environment
    has been killing every restart's process within that window regardless
    of launch method (plain background, detached Start-Process, even a
    fully independent Task Scheduler task with no relation to this
    session's process tree) -- so the fix is making the vulnerable window
    itself as short as possible, not launching it more cleverly. Reading
    doc_ids straight from Chroma's own SQLite file (same query
    document_store.py's own _safe_collection_count workaround uses)
    answers the ONE thing this script actually needs before it can start
    on new books, in about a second, without touching FAISS/BM25 at all."""
    if not persist_dir.exists() or not (persist_dir / "chroma.sqlite3").exists():
        return set()
    import sqlite3

    conn = sqlite3.connect(f"file:{persist_dir / 'chroma.sqlite3'}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT string_value FROM embedding_metadata WHERE key='doc_id'")
        return {r[0] for r in cur.fetchall() if r[0]}
    finally:
        conn.close()


def _load_and_chunk(path_str: str, doc_id: str, start_page: int, end_page: int | None) -> tuple[str, list[Chunk] | None, str | None]:
    """Runs in a worker process -- pure CPU-bound (PyMuPDF + pdfplumber +
    chunking), touches no shared state, so it's safe to run many of these
    concurrently. Mirrors IngestionPipeline.ingest_file's load+chunk half
    exactly (same DocumentMetadata construction) so behavior is identical
    to running it through ingest_file() directly -- only the
    embed+classify+store half moves to the main process.

    doc_id/start_page/end_page are supplied by the caller (added
    2026-08-01) rather than computed here from path alone -- the main
    process decides identity and page range for every submission, whether
    it's a whole small book (start_page=0, end_page=None) or one slice of
    a larger one, so this worker function stays identity-agnostic."""
    path = Path(path_str)
    try:
        suffix = path.suffix.lower().lstrip(".")
        document_type = _SUFFIX_TO_DOC_TYPE[suffix]
        loaded = load_document(path, start_page=start_page, end_page=end_page)
        doc_meta = DocumentMetadata(
            doc_id=doc_id,
            title=loaded.title,
            author=loaded.author,
            source=str(path.resolve()),
            document_type=document_type,
            total_pages=loaded.total_pages,
        )
        chunks = chunk_document(loaded.elements, doc_meta)
        return (path_str, chunks, None)
    except Exception as e:
        return (path_str, None, str(e))


def main() -> None:
    # Local import (not module-level): see the top-of-file comment -- keeps
    # chromadb/faiss/sentence-transformers/torch out of every spawned
    # worker's re-executed module scope. main() only ever runs in the
    # parent process, never a worker.
    #
    # Real bug found 2026-07-24, round 2: skipping the KnowledgeGraph
    # rebuild (see git history / _known_doc_ids_via_sql's own docstring)
    # was a genuine improvement but NOT the actual fix -- restarts kept
    # dying at the exact same "Loading knowledge store" line even after
    # that change, including under a Task Scheduler-launched process with
    # zero relation to this session's process tree. That rules out
    # "launched wrong" as the cause -- this environment kills python
    # processes on some cadence this script doesn't control, so the only
    # real lever left is making the vulnerable startup window as short as
    # possible. DocumentStore(persist_dir=...) alone -- even without
    # IngestionPipeline's graph -- still deserializes the FULL FAISS index
    # + BM25 corpus for 1.7M+ chunks (~30-45s measured in isolation,
    # apparently long enough to keep losing this race for real). This
    # script only ever needed ONE thing from that: the existing doc_ids,
    # for the skip-duplicate check. Chroma writes (.upsert(), used below)
    # are separately confirmed NOT to trip the chromadb Rust-backend crash
    # that .count()/.get()/.query() do at this scale (see
    # document_store.py's own _safe_collection_count docstring) -- only
    # reads are affected, and this script never reads the vector index at
    # all, so talking to Chroma directly here (bypassing DocumentStore
    # entirely) is safe. FAISS/BM25 freshness for OTHER consumers (the
    # live server) is deliberately deferred to a separate
    # recover_knowledge_base.py-style rebuild run once after a full batch
    # of books completes, not maintained incrementally here.
    import numpy as np
    import chromadb

    from project_titan_x.core.vector_store.client import _get_embedding_model
    from project_titan_x.engines.e01_knowledge.classification import TopicClassifier
    from project_titan_x.engines.e01_knowledge.document_store import COLLECTION_NAME

    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=150, help="Stop once this many NEW books have been successfully ingested+moved (not counting already-done/zero-byte).")
    parser.add_argument("--only", nargs="*", default=None, help="Process exactly these filenames (timing smoke test); ignores --target.")
    args = parser.parse_args()

    # persist_dir kept ONLY for the known_doc_ids duplicate-detection read
    # (see below) -- writes now go to OVERFLOW_DIR instead. Real bug found
    # and fixed 2026-09-14: the comment that used to sit here claimed
    # ".upsert() is separately confirmed NOT to trip the chromadb
    # Rust-backend crash ... only reads are affected" -- that claim was
    # simply wrong, and CombinedDocumentStore's own docstring in
    # document_store.py already recorded the correction back on 2026-08-05
    # ("Chroma's own upsert() -- previously believed safe -- ALSO hits the
    # same native access violation once the main store's real corpus
    # passed ~2.1M chunks"). This script never got updated to match. Live
    # reproduction tonight (58 books still queued, main collection at
    # 2,212,628 embeddings + a 1.2M-row unapplied compaction backlog from
    # this session's earlier crash cycles): every single upsert attempt
    # against the main collection failed or crashed the whole process
    # trying to apply/rebuild the HNSW segment, REGARDLESS of which book,
    # confirmed even from a from-scratch process with no other load
    # (minimal_compaction_test.py, 6GB free, zero other work: still
    # "Error in compaction: Failed to apply logs to the hnsw segment
    # writer" after 63s). Same root defect class as .get()/.count()/
    # .query(), now confirmed for .upsert() too, at real-world scale, on
    # this platform. FIX: apply the exact same pattern this codebase
    # already established for YouTube knowledge (a second, small,
    # separately-persisted DocumentStore, merged at query time via
    # CombinedDocumentStore -- see engine.py) instead of writing into the
    # main store at all. OVERFLOW_DIR starts empty, so its own HNSW
    # segment has no backlog and no scale problem for a very long time
    # (58 books is a tiny fraction of what got the main store into this
    # state). known_doc_ids is still read from BOTH stores (see below) so
    # duplicate detection isn't blind to the ~2.2M chunks/586 doc_ids
    # already in the main store.
    persist_dir = DATA_ROOT / "knowledge" / "chroma_db"
    overflow_dir = DATA_ROOT / "knowledge" / "chroma_db_overflow"
    logger.info("Connecting to knowledge store (lightweight -- no full rehydrate)...")
    t0 = time.monotonic()
    chroma_client = chromadb.PersistentClient(path=str(overflow_dir))
    collection = chroma_client.get_or_create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    max_batch_size = chroma_client.get_max_batch_size()

    model = _get_embedding_model()

    def embed_fn(text: str) -> list[float]:
        return model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(texts: list[str]) -> np.ndarray:
        return np.asarray(model.encode(texts, normalize_embeddings=True), dtype="float32")

    classifier = TopicClassifier(embed_fn=embed_fn)
    # Union of both stores -- duplicate detection must see the ~2.2M
    # chunks/586 doc_ids already in the (now write-frozen) main store, not
    # just whatever's accumulated in the new overflow store so far.
    known_doc_ids = _known_doc_ids_via_sql(persist_dir) | _known_doc_ids_via_sql(overflow_dir)
    logger.info("Store ready in %.1fs (%d known doc_ids)", time.monotonic() - t0, len(known_doc_ids))

    # Normalized-title index of already-ingested books, for the duplicate
    # half of the index/title pre-check (see _index_check). Grown as this
    # run itself moves new books into DST_DIR, so two copies of the same
    # book both sitting in NOT READED BOOKS get caught too, not just
    # duplicates of something from a previous run.
    existing_titles: dict[str, str] = {}
    if DST_DIR.exists():
        for p in DST_DIR.iterdir():
            if _safe_is_file(p):
                existing_titles[_normalize_title_key(p.name)] = p.name
    logger.info("%d existing titles indexed for duplicate detection", len(existing_titles))

    results: list[dict] = []
    n_ok = n_skipped_zero = n_already = n_error = n_empty_text = n_skipped_index = n_slices_completed = 0
    total_chunks = 0
    seen_large: set[str] = set()  # names already warned-about this run, avoids duplicate log spam across waves
    run_t0 = time.monotonic()

    # Persists across waves (workers spawned once, reused for every
    # .submit() after) rather than recreated per wave -- avoids paying
    # Python-interpreter-plus-import startup cost (pymupdf/pdfplumber/etc.)
    # for all 10 workers on every single wave. Only replaced (see below)
    # after a timeout, since a pool containing an abandoned stuck worker
    # can't be safely reused -- shutdown(cancel_futures=True) tears the
    # whole pool down, and submit() after shutdown() raises.
    executor = ProcessPoolExecutor(max_workers=WORKERS)

    while True:
        all_files = sorted(p for p in SRC_DIR.iterdir() if _safe_is_file(p) and p.suffix.lower() == ".pdf")

        if args.only:
            wanted = set(args.only)
            candidates = [p for p in all_files if p.name in wanted]
        else:
            candidates = all_files

        # Filter out already-done/zero-byte BEFORE spending a worker slot on them.
        # Real issue found 2026-07-29: a cluster of ~65-100MB image/chart-heavy
        # PDFs (technical-analysis books, mostly) drove free system memory from
        # healthy to under 500MB within ~90s even at WORKERS=1 -- not a
        # concurrency problem, a single-file memory footprint problem on this
        # machine.
        #
        # Oversized-by-bytes files are no longer permanently deferred here
        # (fixed 2026-09-14, see MAX_SAFE_SIZE_BYTES's own comment) -- they
        # fall through to the SAME slicing path as oversized-by-pages files
        # below, using pages_per_slice computed from this specific file's
        # own measured density (_adaptive_pages_per_slice) instead of the
        # flat MAX_SAFE_PAGES, so a genuinely image-dense book still gets
        # small, safe slices rather than one huge pass.
        to_parse: list[WorkItem] = []
        for p in candidates:
            size_bytes = _safe_size(p)
            if size_bytes == 0:
                continue

            # Page count needed either way now (to decide slice size for an
            # oversized-by-bytes file, or to check the ordinary
            # oversized-by-pages gate) -- computed once and reused below,
            # not a second pymupdf.open() per branch.
            pages = _page_count(p)
            if size_bytes > MAX_SAFE_SIZE_BYTES:
                pages_per_slice = _adaptive_pages_per_slice(size_bytes, pages)
                if p.name not in seen_large:
                    seen_large.add(p.name)
                    logger.info(
                        "%s -> %.1fMB, %d pages (%.0fKB/page) exceeds the flat safe-size threshold -- "
                        "adaptive slicing at %d pages/slice instead of deferring",
                        p.name, size_bytes / 1e6, pages, size_bytes / max(pages, 1) / 1024, pages_per_slice,
                    )
            else:
                # Second, independent memory-cost gate (added 2026-07-30 --
                # see MAX_SAFE_PAGES's own comment for the real
                # 5.6MB/381-page book that slipped through the byte-size
                # filter and stalled the whole queue for 45+ minutes). File
                # size alone isn't enough; page count catches what it
                # misses.
                pages_per_slice = MAX_SAFE_PAGES

            if pages <= pages_per_slice:
                whole_doc_id = _doc_id_for(p)
                if whole_doc_id in known_doc_ids:
                    continue
                # Index/title pre-check (added 2026-07-30, explicit
                # instruction): before spending a worker slot on the full
                # parse+embed+store pipeline, check the title + first 20
                # pages first. "Leave" (skip -> SKIP_DIR, never processed)
                # anything that's a duplicate of an already-read book or
                # that carries none of this platform's current-or-future
                # finance/trading/economics/quant keywords -- everything
                # else still gets fully read, same as before.
                keep, reason = _index_check(p, existing_titles)
                if keep:
                    to_parse.append(WorkItem(path=p, doc_id=whole_doc_id, start_page=0, end_page=None, slice_label=""))
                else:
                    try:
                        SKIP_DIR.mkdir(parents=True, exist_ok=True)
                        _safe_move(p, SKIP_DIR / p.name)
                        results.append({"file": p.name, "size_bytes": size_bytes, "outcome": "skipped_index_check", "reason": reason})
                        n_skipped_index += 1
                        logger.info("%s -> LEFT (index check): %s", p.name, reason)
                    except Exception as e:
                        results.append({"file": p.name, "size_bytes": size_bytes, "outcome": "skip_move_failed", "error": str(e)})
                        logger.warning("%s -> index check said skip but failed to move: %s", p.name, e)
            else:
                # Added 2026-08-01: a book over MAX_SAFE_PAGES no longer
                # gets deferred forever -- it's split into consecutive
                # pages_per_slice-sized slices (see _book_slices), each
                # tracked as its own store entry via _slice_doc_id_for.
                # Directly measured safe on a real 510pg book (three
                # MAX_SAFE_PAGES-sized slices, 147-553MB peak each) -- see
                # WorkItem's docstring. pages_per_slice is MAX_SAFE_PAGES
                # for this ordinary path, or the smaller, density-adapted
                # value from _adaptive_pages_per_slice for a file that got
                # here via the oversized-by-bytes branch above.
                slices = _book_slices(pages, pages_per_slice)
                slice_ids = [_slice_doc_id_for(p, s, e) for s, e in slices]
                if all(sid in known_doc_ids for sid in slice_ids):
                    # Every slice already landed in the store in a
                    # previous run -- this book is done, just needs its
                    # physical file moved (handled by the orphan-
                    # reconciliation pass below, same as a whole book).
                    continue
                # Index/title check runs once per book, before its FIRST
                # slice is queued -- an off-topic 800pg book shouldn't get
                # 225 pages parsed before being recognized as skippable.
                keep, reason = _index_check(p, existing_titles)
                if not keep:
                    try:
                        SKIP_DIR.mkdir(parents=True, exist_ok=True)
                        _safe_move(p, SKIP_DIR / p.name)
                        results.append({"file": p.name, "size_bytes": size_bytes, "outcome": "skipped_index_check", "reason": reason})
                        n_skipped_index += 1
                        logger.info("%s -> LEFT (index check): %s", p.name, reason)
                    except Exception as e:
                        results.append({"file": p.name, "size_bytes": size_bytes, "outcome": "skip_move_failed", "error": str(e)})
                        logger.warning("%s -> index check said skip but failed to move: %s", p.name, e)
                else:
                    # Queue only the earliest not-yet-done slice -- one
                    # slice per wave (same WAVE_SIZE=1 cadence as whole
                    # books), so one huge book can't monopolize multiple
                    # wave slots and starve everything queued behind it.
                    for i, ((s, e), sid) in enumerate(zip(slices, slice_ids)):
                        if sid not in known_doc_ids:
                            label = f"slice {i + 1}/{len(slices)} (pages {s + 1}-{e})"
                            to_parse.append(WorkItem(path=p, doc_id=sid, start_page=s, end_page=e, slice_label=label))
                            break
            if len(to_parse) >= WAVE_SIZE:
                break

        # Report every zero-byte/already-done file encountered this pass
        # (only once -- track via results to avoid duplicate log spam across
        # waves since SRC_DIR is rescanned fresh each iteration).
        seen_files = {r["file"] for r in results}
        for p in candidates:
            if p.name in seen_files:
                continue
            size_bytes_check = _safe_size(p)
            if size_bytes_check == 0:
                results.append({"file": p.name, "size_bytes": 0, "outcome": "zero_byte_unreadable"})
                n_skipped_zero += 1
                logger.warning("%s -> 0 bytes, cannot read, leaving in place", p.name)
                continue

            # Real bug found and fixed 2026-09-14, same day oversized-by-
            # bytes files stopped being permanently deferred above: this
            # pass used to unconditionally `continue` past anything over
            # MAX_SAFE_SIZE_BYTES, meaning a fully-ingested-and-slice-
            # complete oversized book would NEVER be detected as done and
            # moved to READ BOOKS -- it would sit here forever, re-scanned
            # every single run, all its slices correctly recognized as
            # already-done by the candidate loop above (so never
            # re-queued either) but never physically moved. Must use the
            # SAME pages_per_slice this file was actually ingested with
            # (the density-adapted value, not the flat MAX_SAFE_PAGES) or
            # _book_slices here would compute different boundaries than
            # what's really in the store and never match.
            pages_check = _page_count(p)
            pages_per_slice_check = (
                _adaptive_pages_per_slice(size_bytes_check, pages_check)
                if size_bytes_check > MAX_SAFE_SIZE_BYTES
                else MAX_SAFE_PAGES
            )
            if pages_check <= pages_per_slice_check:
                all_done = _doc_id_for(p) in known_doc_ids
            else:
                # Added 2026-08-01: a sliced book's whole-file doc_id is
                # never itself written to the store -- only its slices are
                # -- so "done" means every slice landed.
                all_done = all(
                    _slice_doc_id_for(p, s, e) in known_doc_ids
                    for s, e in _book_slices(pages_check, pages_per_slice_check)
                )
            if not all_done:
                continue

            # Real bug found 2026-07-24: a book whose chunks got
            # embedded+upserted successfully but whose move() never ran
            # (this environment killing the process between those two
            # steps, mid-wave) used to just sit here forever -- every
            # future restart's known_doc_ids check correctly recognized
            # it as "already done" and silently left it in place, never
            # actually moving it. Over hours of repeated restarts this
            # quietly accumulated real, completed work that never
            # reflected in the file-count progress anyone could see.
            # Moving it here, the instant this case is detected, makes
            # the file system self-heal on every restart instead of
            # needing a manual reconciliation pass. Applies identically
            # to a fully-sliced large book -- all_done above already
            # confirms every slice is in, so it's just as "orphaned" as a
            # whole small book whose move() never ran.
            size_bytes = _safe_size(p)  # captured BEFORE move() -- p no longer exists at this path afterward
            try:
                DST_DIR.mkdir(parents=True, exist_ok=True)
                _safe_move(p, DST_DIR / p.name)
                existing_titles[_normalize_title_key(p.name)] = p.name
                results.append({"file": p.name, "size_bytes": size_bytes, "outcome": "already_ingested_moved_now"})
                logger.info("%s -> already ingested in a previous run, moving now (was orphaned)", p.name)
            except Exception as e:
                results.append({"file": p.name, "size_bytes": size_bytes, "outcome": "already_ingested_move_failed", "error": str(e)})
                logger.warning("%s -> already ingested but failed to move: %s", p.name, e)
            n_already += 1

        if not to_parse:
            logger.info("Nothing left to parse (target reached or pool exhausted).")
            break
        if not args.only and n_ok >= args.target:
            logger.info("Target of %d newly-ingested books reached.", args.target)
            break

        wave_t0 = time.monotonic()
        logger.info("Wave: parsing %d books in parallel (%d workers)...", len(to_parse), WORKERS)
        futures = {executor.submit(_load_and_chunk, str(item.path), item.doc_id, item.start_page, item.end_page): item for item in to_parse}
        done, not_done = wait(futures.keys(), timeout=WAVE_TIMEOUT_SECONDS)

        if not_done:
            for future in not_done:
                item = futures[future]
                p = item.path
                results.append({"file": p.name, "size_bytes": _safe_size(p), "outcome": "timeout", "slice": item.slice_label})
                n_error += 1
                logger.error("%s%s -> TIMED OUT after wave budget (left in place, worker abandoned)", p.name,
                             f" [{item.slice_label}]" if item.slice_label else "")
            # The pool now has an abandoned worker stuck on the timed-out
            # task -- tear the whole pool down and start a fresh one for
            # the next wave (see comment where `executor` is first created).
            executor.shutdown(wait=False, cancel_futures=True)
            executor = ProcessPoolExecutor(max_workers=WORKERS)

        for future in done:
            item = futures[future]
            p = item.path
            slice_tag = f" [{item.slice_label}]" if item.slice_label else ""
            path_str, chunks, error = future.result()
            rec: dict = {"file": p.name, "size_bytes": _safe_size(p), "slice": item.slice_label}
            if error is not None:
                rec["outcome"] = "error"
                rec["error"] = error
                n_error += 1
                logger.error("%s%s -> FAILED to parse: %s (left in place)", p.name, slice_tag, error)
                results.append(rec)
                continue

            t_embed = time.monotonic()
            try:
                if chunks:
                    vectors = embed_batch([c.text for c in chunks])
                    for chunk, vector in zip(chunks, vectors):
                        topics, confidence = classifier.classify_vector(vector)
                        chunk.topics = topics
                        chunk.confidence = confidence
                    # Direct Chroma upsert -- mirrors DocumentStore.add_chunks'
                    # own logic (same sub-batching for Chroma's max-batch-size
                    # limit) without constructing a DocumentStore. Chroma
                    # writes are confirmed NOT affected by the Rust-backend
                    # read crash (see this function's top comment) -- FAISS/
                    # BM25/KnowledgeGraph freshness for other consumers is
                    # deliberately deferred to a separate rebuild run, not
                    # maintained incrementally here.
                    ids = [c.chunk_id for c in chunks]
                    documents = [c.text for c in chunks]
                    metadatas = [c.to_metadata_dict() for c in chunks]
                    vectors_list = vectors.tolist()
                    for start in range(0, len(chunks), max_batch_size):
                        end = start + max_batch_size
                        collection.upsert(
                            ids=ids[start:end],
                            embeddings=vectors_list[start:end],
                            documents=documents[start:end],
                            metadatas=metadatas[start:end],
                        )

                rec["n_chunks"] = len(chunks)
                rec["elapsed_s"] = round(time.monotonic() - t_embed, 1)
                total_chunks += len(chunks)
                if len(chunks) == 0:
                    n_empty_text += 1
                    rec["outcome"] = "ingested_no_extractable_text"
                    logger.warning("%s%s -> parsed fine but 0 chunks (likely scanned/image-only)", p.name, slice_tag)
                else:
                    rec["outcome"] = "ingested"
                    logger.info("%s%s -> %d chunks (embed+store %.1fs)", p.name, slice_tag, len(chunks), rec["elapsed_s"])

                # Keep the in-memory set current for THIS run -- needed so
                # a book split across several slices (added 2026-08-01) is
                # correctly recognized as "slice N done, queue slice N+1"
                # on the very next while-True pass, not just after a fresh
                # process restart re-reads known_doc_ids from the store.
                known_doc_ids.add(item.doc_id)

                if item.end_page is None:
                    # Whole-book item (not sliced) -- move immediately,
                    # same behavior as before slicing existed. n_ok counts
                    # actual moved-to-READ-BOOKS completions, matching its
                    # docstring ("newly-ingested books") and the final
                    # summary's "ingested+moved" wording.
                    DST_DIR.mkdir(parents=True, exist_ok=True)
                    _safe_move(p, DST_DIR / p.name)
                    existing_titles[_normalize_title_key(p.name)] = p.name
                    n_ok += 1
                else:
                    # One slice of a larger book landed -- only move the
                    # physical file (and only then count it toward n_ok)
                    # once EVERY slice is in (known_doc_ids was just
                    # updated above with this one). p still exists at this
                    # path (not moved yet) so its true page count is
                    # available for recomputing the full slice set.
                    n_slices_completed += 1
                    total_pages_now = _page_count(p)
                    size_bytes_now = _safe_size(p)
                    # Same adaptive-vs-flat pages_per_slice this book was
                    # actually ingested with (see the reconciliation pass's
                    # own comment on this exact class of bug) -- otherwise
                    # an oversized-by-bytes book's recomputed slice
                    # boundaries never match what's really in the store and
                    # it never gets recognized as complete.
                    pages_per_slice_now = (
                        _adaptive_pages_per_slice(size_bytes_now, total_pages_now)
                        if size_bytes_now > MAX_SAFE_SIZE_BYTES
                        else MAX_SAFE_PAGES
                    )
                    all_slice_ids = [_slice_doc_id_for(p, s, e) for s, e in _book_slices(total_pages_now, pages_per_slice_now)]
                    if all(sid in known_doc_ids for sid in all_slice_ids):
                        DST_DIR.mkdir(parents=True, exist_ok=True)
                        _safe_move(p, DST_DIR / p.name)
                        existing_titles[_normalize_title_key(p.name)] = p.name
                        logger.info("%s -> all %d slices ingested, moving now", p.name, len(all_slice_ids))
                        n_ok += 1
            except Exception as e:
                rec["outcome"] = "error"
                rec["error"] = str(e)
                n_error += 1
                logger.error("%s%s -> FAILED to embed/store: %s (left in place)", p.name, slice_tag, e)

            results.append(rec)

        logger.info("Wave done in %.1fs (%d/%d parsed successfully).", time.monotonic() - wave_t0, len(done), len(to_parse))

        # No rehydrate-cache checkpoint and no FAISS/BM25 rebuild here --
        # this lightweight version never loads them in the first place (see
        # this function's top comment). Chroma itself (the durable,
        # authoritative store) is updated immediately by every wave's
        # collection.upsert() calls above -- run
        # scripts/training/recover_knowledge_base.py once after a batch of
        # books completes to bring the FAISS/BM25 search indexes (used by
        # hybrid_search(), not by this script) up to date with everything
        # ingested since the last rebuild.

    executor.shutdown(wait=False, cancel_futures=True)

    elapsed_total = time.monotonic() - run_t0
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": args.target,
        "n_ingested_ok": n_ok,
        "n_ingested_no_text": n_empty_text,
        "n_already_ingested": n_already,
        "n_zero_byte_skipped": n_skipped_zero,
        "n_skipped_index_check": n_skipped_index,
        "n_slices_completed": n_slices_completed,
        "n_errors": n_error,
        "total_new_chunks": total_chunks,
        "elapsed_seconds": round(elapsed_total, 1),
        "files": results,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"run_{int(time.time())}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    logger.info(
        "DONE. %d ingested+moved (%d with no extractable text), %d already done, %d zero-byte skipped, "
        "%d left via index-check (not relevant/duplicate), %d large-book slices completed (not yet fully moved), "
        "%d errors. +%d chunks in %.1f min. Report: %s",
        n_ok, n_empty_text, n_already, n_skipped_zero, n_skipped_index, n_slices_completed, n_error, total_chunks, elapsed_total / 60, out_path,
    )


if __name__ == "__main__":
    main()
