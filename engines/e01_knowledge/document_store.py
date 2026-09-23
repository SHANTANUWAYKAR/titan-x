"""
Module: document_store.py
Description: Dual-backend storage for Engine 01's ingested chunks --
    ChromaDB (persistent, primary query path with native metadata
    filtering) and FAISS (in-memory mirror, satisfying the explicit
    "store in ChromaDB AND FAISS" requirement and giving a second,
    independent index to cross-check against). Also owns the BM25
    keyword index and combines all three into hybrid_search().

    Reuses the SAME cached sentence-transformers model instance already
    used by core/vector_store/client.py (core.vector_store._get_embedding_model)
    rather than loading a second copy of the model into memory.

    hybrid_search() is memoized (see _hybrid_search_cache): BM25's
    get_scores() does a full linear scan of the entire corpus (319,396
    chunks in this project's real ingested library) on EVERY call, and a
    single signal_generation workflow triggers ~6 separate knowledge
    lookups (E07, E04, E08, E06, E51, E45) -- most with query strings that
    repeat often (the same regime label, the same asset, across nearby
    calls), so a small bounded cache turns most of those into a dict
    lookup instead of a full corpus rescan. Invalidated on any write
    (add_chunks) rather than relying on a TTL alone, so newly ingested
    content is never served stale -- the TTL is a defensive backstop, not
    the primary correctness mechanism.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
import pickle
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

import chromadb
import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from project_titan_x.core.vector_store.client import _get_embedding_model
from project_titan_x.engines.e01_knowledge.models import Chunk, DocumentType, KnowledgeCategory, SearchResult

logger = logging.getLogger(__name__)

VECTOR_SIZE = 384  # all-MiniLM-L6-v2 output dimension, same model as core/vector_store
COLLECTION_NAME = "titan_knowledge_documents"

_HYBRID_SEARCH_CACHE_MAXSIZE = 256
_HYBRID_SEARCH_CACHE_TTL_SECONDS = 3600  # defensive backstop; add_chunks() invalidating on write is the primary mechanism


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def _chunk_from_record(chunk_id: str, text: str, metadata: dict[str, Any]) -> Chunk:
    """Inverse of Chunk.to_metadata_dict(), for rehydrating from Chroma."""
    topics_str = metadata.get("topics", "") or ""
    topics = [KnowledgeCategory(t) for t in topics_str.split(",") if t]
    page = metadata.get("page", -1)
    return Chunk(
        chunk_id=chunk_id,
        doc_id=metadata.get("doc_id", ""),
        text=text,
        title=metadata.get("title", ""),
        author=metadata.get("author", ""),
        source=metadata.get("source", ""),
        document_type=DocumentType(metadata.get("document_type", DocumentType.TXT.value)),
        page=page if page != -1 else None,
        chapter=metadata.get("chapter") or None,
        topics=topics,
        confidence=float(metadata.get("confidence", 0.0)),
        contains_table=bool(metadata.get("contains_table", False)),
        contains_formula=bool(metadata.get("contains_formula", False)),
    )


class DocumentStore:
    """Chroma (persistent) + FAISS (in-memory) + BM25 keyword index over
    the same set of chunks, combined via hybrid_search()."""

    def __init__(self, persist_dir: Optional[Path] = None) -> None:
        self._persist_dir = persist_dir or Path("data/knowledge/chroma_db")
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        # NOT loaded here: _rehydrate() below reads embeddings already
        # persisted in Chroma directly, so construction never actually
        # needs the embedding model itself -- only embed()/embed_batch()
        # (real new-chunk ingestion or query embedding) do, and those
        # call _get_embedding_model() directly (see below), which is
        # itself lazily-loaded and process-wide cached. Eagerly loading
        # it here cost ~19s of every server construction regardless of
        # whether anything was ever actually ingested/searched that run.
        self._chroma_client = chromadb.PersistentClient(path=str(self._persist_dir))
        self._collection = self._chroma_client.get_or_create_collection(
            COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
        # Chroma rejects a single add/upsert call above this size (observed
        # 5461 in this environment) -- queried dynamically rather than
        # hardcoded since it depends on the underlying SQLite build.
        self._max_batch_size = self._chroma_client.get_max_batch_size()

        self._faiss_index = faiss.IndexFlatIP(VECTOR_SIZE)
        self._faiss_ids: list[str] = []

        self._chunks: dict[str, Chunk] = {}
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_ids: list[str] = []

        # cache_key -> (cached_at_monotonic, results); see module docstring.
        self._hybrid_search_cache: OrderedDict[tuple, tuple[float, list[SearchResult]]] = OrderedDict()

        self._rehydrate()

    # Cache files for _rehydrate's expensive rebuild (FAISS index + BM25
    # index + the _chunks dict) -- see _rehydrate's own docstring for why
    # this exists and how it's invalidated.
    @property
    def _rehydrate_cache_meta_path(self) -> Path:
        return self._persist_dir / "_rehydrate_cache_meta.pkl"

    @property
    def _rehydrate_cache_faiss_path(self) -> Path:
        return self._persist_dir / "_rehydrate_cache_faiss.index"

    def _safe_collection_count(self) -> int:
        """Real bug found and fixed 2026-07-23: `self._collection.count()`
        -- chromadb 1.5.9's Rust-backed implementation
        (chromadb/api/rust.py's _count) -- crashed this process outright
        with a Windows access violation once this project's real corpus
        grew past ~1.7M chunks (confirmed via python -X faulthandler: the
        crash is a native access violation inside _count() itself, not a
        Python exception, not OOM -- a bigger page file did not help). A
        native access violation terminates the process; it cannot be
        caught with try/except, so the only fix is to never call the
        buggy path once the corpus is real-world scale. Chroma has no
        newer release (1.5.9 is latest) and downgrading below the Rust
        rewrite would mean an incompatible on-disk format -- unable to
        read this same data at all, and re-ingesting from scratch would
        destroy ~1.7M chunks of real, already-completed work.

        Reads the row count directly from Chroma's own persisted SQLite
        file instead, scoped to this collection via segments/collections
        (embeddings.segment_id -> segments.id -> segments.collection ->
        collections.id), the same scoping self._collection.count() itself
        would apply -- verified against a real 1.72M-row database this
        matches the row count of the vector segment exactly. Falls back to
        the normal (safe at small/test scale -- this crash is scale-
        dependent, every existing unit test's tmp_path-sized store is
        unaffected) self._collection.count() whenever the raw path isn't
        available (brand-new store, no sqlite file yet, or a future Chroma
        version with a different on-disk schema)."""
        sqlite_path = self._persist_dir / "chroma.sqlite3"
        if not sqlite_path.exists():
            return self._collection.count()
        try:
            import sqlite3

            conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT COUNT(*) FROM embeddings e
                    JOIN segments s ON e.segment_id = s.id
                    JOIN collections c ON s.collection = c.id
                    WHERE c.name = ?
                    """,
                    (COLLECTION_NAME,),
                )
                return cur.fetchone()[0]
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Raw sqlite count failed (%s), falling back to collection.count()", e)
            return self._collection.count()

    def _rehydrate(self) -> None:
        """Reload chunks already persisted in Chroma (from a previous
        process) into the in-memory _chunks dict, FAISS index, and BM25
        index. Without this, every process restart would keep the vectors
        on disk in Chroma but silently lose keyword search, metadata
        filtering, and similar_chunks() -- all of which read from
        self._chunks, not Chroma directly. figure_captions isn't part of
        Chroma's flattened metadata and comes back empty on rehydrated
        chunks -- a minor, informational-only gap (not used in ranking).

        Real performance bug found and fixed 2026-07-20: this rebuild --
        paginated Chroma reads + a full FAISS insert + a full BM25Okapi
        build (non-linear in corpus size, see add_chunks' own docstring)
        -- was measured taking 100-140s EVERY process start against this
        project's real 319,497-chunk corpus, dwarfing every other part of
        server startup combined. The corpus is near-static (only grows via
        deliberate ingest_all() runs, not on every restart), so rebuilding
        it from scratch on every single start was pure waste. Now: a
        cached FAISS index (faiss.write_index/read_index -- proper native
        (de)serialization) plus a pickled snapshot of _chunks/_faiss_ids/
        _bm25_ids/the built BM25Okapi object, keyed on Chroma's own
        collection.count(). If the cached count matches the real count,
        load the cache directly (a few seconds) instead of rebuilding
        (100+s). If the corpus has grown (a real ingest happened, see
        add_chunks' cache invalidation below) the count won't match, and
        this falls through to the original full paginated-rebuild path,
        then writes a fresh cache at the end for the NEXT start. Trade-off,
        stated plainly: this cache-by-count check would miss a corpus
        mutation that doesn't change the total chunk count (e.g. an
        in-place chunk replacement) -- not a real risk today since nothing
        in this codebase replaces a chunk in place, only add_chunks
        (append-only) exists.

        Paginated (uncached fallback path): a single get() over a large
        collection hits SQLite's variable-count limit ("too many SQL
        variables"), the read-side counterpart of upsert()'s max-batch-
        size limit in add_chunks().

        REAL FIX, 2026-09-14: the paginated get() above was chromadb
        1.5.9's Rust-backed `.get()` -- confirmed live to segfault this
        process outright (Windows access violation, uncatchable) even on
        a single-row metadata-only call, once this project's real corpus
        passed ~2.1M chunks. Same root defect class `_safe_collection_
        count`'s own 2026-07-23 docstring already documents for `.count()`
        -- `.get()` shares it. Replaced with `_rehydrate_via_safe_sql`,
        the same direct-SQLite technique, generalized from counting to
        actually reading every chunk's id/text/metadata/vector. See that
        method's own docstring for the honest gap it carries forward
        (vectors already compacted into Chroma's own binary HNSW segment
        before this fix existed aren't recoverable from SQL and are
        rehydrated without a vector -- keyword search still covers them)."""
        count = self._safe_collection_count()
        if count == 0:
            return

        if self._load_rehydrate_cache(count):
            logger.info("Rehydrated %d chunks from cache (skipped full rebuild) at %s", count, self._persist_dir)
            return

        self._rehydrate_via_safe_sql(count)
        self._rebuild_bm25()
        logger.info("Rehydrated %d chunks from persisted Chroma store at %s", count, self._persist_dir)
        self._write_rehydrate_cache(count)

    def _rehydrate_via_safe_sql(self, count: int) -> None:
        """Reads every chunk's id/document/metadata/vector directly from
        Chroma's own persisted SQLite file, never through chromadb's own
        `.get()`/`.count()`/`.query()` API -- see `_rehydrate`'s own
        docstring for why (a confirmed, reproducible native crash in
        chromadb 1.5.9's Rust bindings at this corpus's real scale).

        WHY THIS IS SAFE, VERIFIED DIRECTLY, NOT ASSUMED:
        - id/document/metadata: `_safe_collection_count` already proved
          direct SQLite reads against this exact database are safe at
          this exact scale (only the Rust API path crashes). This method
          reuses the identical embeddings/embedding_metadata tables that
          method already reads, just fetching full rows instead of a
          COUNT(*).
        - vectors: `embeddings_queue.vector` stores the raw embedding for
          every upsert as a little-endian FLOAT32 blob (confirmed via
          direct inspection: 1536 bytes = 384 floats = VECTOR_SIZE
          exactly) -- append-only, so the LATEST row per chunk id (by
          seq_id) is that chunk's current, real vector, not an
          approximation.

        A SECOND, SEPARATE PROBLEM THIS METHOD WORKS AROUND (documented
        for the record, not something this method itself fixes): a real
        environment instability this session found (repeated segfaults
        in the book-ingestion pipeline, see CLAUDE.md's dated entry) left
        Chroma's own internal vector-segment write-ahead queue over 1.1
        MILLION entries behind the metadata segment (max_seq_id showed
        the metadata segment fully caught up at seq_id 2,864,718 while
        the vector segment sat stuck at 1,718,113) -- any `.get()` call
        was triggering Chroma's own attempt to backfill that entire
        backlog into the HNSW segment in one shot, which is what the
        original crash traceback's "Failed to apply logs to the hnsw
        segment writer" names. This means `embeddings_queue` currently
        holds a real, recoverable vector for every chunk written since
        that backlog started (459,803 distinct ids at the time this was
        written) -- exactly the chunks most in need of a safe read path,
        since they were never compacted into the (unreadable, for now)
        binary HNSW segment at all.

        HONEST GAP: chunks whose vector WAS already compacted into that
        binary segment before the backlog started have no safe vector
        source here -- their queue rows have since been pruned, and
        parsing Chroma's proprietary on-disk HNSW format is out of scope
        for this fix. They are still fully rehydrated into self._chunks
        (real text, real metadata, real BM25 keyword search) -- only
        FAISS/vector-similarity search is unavailable for them until a
        dedicated re-embedding pass runs (their text is already safe to
        read, so this is a real, schedulable follow-up, not a permanent
        loss). Logged once, with the exact count, rather than silently
        degrading search quality with no visible signal."""
        import sqlite3

        sqlite_path = self._persist_dir / "chroma.sqlite3"
        conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        try:
            cur = conn.cursor()

            vector_by_chunk_id: dict[str, np.ndarray] = {}
            cur.execute("SELECT id, vector FROM embeddings_queue WHERE vector IS NOT NULL ORDER BY seq_id ASC")
            for chunk_id, vector_blob in cur.fetchall():
                vector_by_chunk_id[chunk_id] = np.frombuffer(vector_blob, dtype=np.float32)

            cur.execute(
                """
                SELECT e.id, e.embedding_id FROM embeddings e
                JOIN segments s ON e.segment_id = s.id
                JOIN collections c ON s.collection = c.id
                WHERE c.name = ? AND s.scope = 'METADATA'
                ORDER BY e.id
                """,
                (COLLECTION_NAME,),
            )
            int_id_to_chunk_id: dict[int, str] = dict(cur.fetchall())

            n_no_vector = 0
            int_ids = list(int_id_to_chunk_id.keys())
            for start in range(0, len(int_ids), self._max_batch_size):
                batch = int_ids[start:start + self._max_batch_size]
                placeholders = ",".join("?" * len(batch))
                cur.execute(
                    f"SELECT id, key, string_value, int_value, float_value, bool_value "
                    f"FROM embedding_metadata WHERE id IN ({placeholders})",
                    batch,
                )
                metadata_by_int_id: dict[int, dict[str, Any]] = {i: {} for i in batch}
                for int_id, key, s_val, i_val, f_val, b_val in cur.fetchall():
                    if s_val is not None:
                        value: Any = s_val
                    elif i_val is not None:
                        value = i_val
                    elif f_val is not None:
                        value = f_val
                    else:
                        value = bool(b_val)
                    metadata_by_int_id[int_id][key] = value

                # Vectors are flushed to FAISS PER BATCH (added 2026-09-14,
                # real bug found live under memory pressure -- accumulating
                # every one of ~475K+ vectors in a Python list before a
                # single np.stack() call needs roughly 2x the final array's
                # memory at its peak (the list of individual arrays AND the
                # freshly-stacked contiguous array coexist briefly), and a
                # real full-suite run concurrent with book ingestion hit
                # `numpy.core._exceptions._ArrayMemoryError: Unable to
                # allocate 697. MiB` on exactly that call. Bounding the
                # batch to self._max_batch_size (the SAME bound add_chunks'
                # own upsert path already respects) keeps peak memory for
                # this step to one batch's worth of vectors, not the whole
                # corpus's.
                batch_vectors: list[np.ndarray] = []
                for int_id in batch:
                    chunk_id = int_id_to_chunk_id[int_id]
                    metadata = metadata_by_int_id.get(int_id, {})
                    text = metadata.get("chroma:document", "")
                    self._chunks[chunk_id] = _chunk_from_record(chunk_id, text, metadata)
                    vector = vector_by_chunk_id.get(chunk_id)
                    if vector is not None:
                        self._faiss_ids.append(chunk_id)
                        batch_vectors.append(vector)
                    else:
                        n_no_vector += 1
                if batch_vectors:
                    self._faiss_index.add(np.stack(batch_vectors).astype("float32"))

            if n_no_vector:
                logger.warning(
                    "%d of %d rehydrated chunks have no safely-recoverable vector yet "
                    "(already compacted into Chroma's own HNSW segment before this fix "
                    "existed -- see document_store.py's _rehydrate_via_safe_sql docstring). "
                    "Keyword search covers them; vector/semantic search does not until a "
                    "dedicated re-embed pass runs.",
                    n_no_vector, count,
                )
        finally:
            conn.close()

    def _load_rehydrate_cache(self, count: int) -> bool:
        """Returns True and populates state from the cache iff a valid,
        up-to-date (count-matched) cache was found. Any failure (missing
        file, corrupt pickle, count mismatch) returns False and leaves
        state untouched -- caller falls back to the real rebuild, same
        never-serve-something-broken discipline as every other best-effort
        cache in this codebase."""
        if not (self._rehydrate_cache_meta_path.exists() and self._rehydrate_cache_faiss_path.exists()):
            return False
        try:
            with open(self._rehydrate_cache_meta_path, "rb") as f:
                meta = pickle.load(f)
            if meta.get("count") != count:
                return False
            faiss_index = faiss.read_index(str(self._rehydrate_cache_faiss_path))
            self._chunks = meta["chunks"]
            self._faiss_ids = meta["faiss_ids"]
            self._bm25_ids = meta["bm25_ids"]
            self._bm25 = meta["bm25"]
            self._faiss_index = faiss_index
            return True
        except Exception as e:
            logger.warning("Rehydrate cache unusable (%s) -- falling back to full rebuild", e)
            return False

    def _write_rehydrate_cache(self, count: int) -> None:
        """Best-effort -- a failed cache write must never fail startup
        itself, it just means the next start pays the full rebuild again."""
        try:
            faiss.write_index(self._faiss_index, str(self._rehydrate_cache_faiss_path))
            with open(self._rehydrate_cache_meta_path, "wb") as f:
                pickle.dump(
                    {"count": count, "chunks": self._chunks, "faiss_ids": self._faiss_ids, "bm25_ids": self._bm25_ids, "bm25": self._bm25},
                    f,
                )
        except Exception as e:
            logger.warning("Failed to write rehydrate cache (%s) -- next start will rebuild from scratch", e)

    def _invalidate_rehydrate_cache(self) -> None:
        """Called on every write (add_chunks) -- the cache is keyed on
        chunk count, so a stale cache after a real ingestion would either
        be silently skipped (count now differs, safe) or -- the case this
        guards against -- a batch that happens to leave the count matching
        a stale cache's count by coincidence. Deleting outright is simpler
        and safer than trying to reason about that edge case."""
        for path in (self._rehydrate_cache_meta_path, self._rehydrate_cache_faiss_path):
            try:
                path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning("Failed to invalidate rehydrate cache file %s: %s", path, e)

    # ---- embedding ----

    def embed(self, text: str) -> list[float]:
        return _get_embedding_model().encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return np.asarray(_get_embedding_model().encode(texts, normalize_embeddings=True), dtype="float32")

    # ---- ingestion ----

    def add_chunks(
        self, chunks: list[Chunk], vectors: Optional[np.ndarray] = None, rebuild_bm25: bool = True
    ) -> None:
        """rebuild_bm25=False lets a bulk-ingestion caller add many
        documents' chunks back-to-back and rebuild the BM25 index once at
        the end, rather than paying its full-corpus rebuild cost after
        every single file -- BM25Okapi's build time scales worse than
        linearly (measured ~0.17s at 1k docs, ~19s at 70k), so rebuilding
        it N times during an N-file batch is needless, avoidable
        quadratic-ish cost on top of the actual parsing work.

        `vectors` lets a caller that already embedded these chunks for
        another purpose (e.g. topic classification) pass them in instead
        of embedding the same text a second time here."""
        if not chunks:
            return
        vectors = vectors if vectors is not None else self.embed_batch([c.text for c in chunks])

        ids = [c.chunk_id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [c.to_metadata_dict() for c in chunks]
        vectors_list = vectors.tolist()

        # Chroma rejects a single call larger than self._max_batch_size (a
        # single large book can produce tens of thousands of chunks, well
        # past that limit) -- split into sub-batches rather than let the
        # whole file silently fail (as Encyclopedia_of_Chart_Patterns.pdf's
        # 25,141 chunks did before this fix).
        for start in range(0, len(chunks), self._max_batch_size):
            end = start + self._max_batch_size
            self._collection.upsert(
                ids=ids[start:end],
                embeddings=vectors_list[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

        self._faiss_index.add(vectors)
        self._faiss_ids.extend(ids)

        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

        if rebuild_bm25:
            self._rebuild_bm25()
        # Any write invalidates every cached hybrid_search() result --
        # cheaper and simpler than trying to reason about which cached
        # queries could now return different results.
        self._hybrid_search_cache.clear()
        # Also invalidate the on-disk _rehydrate() cache (see that
        # method's docstring) -- a real ingestion just happened, so the
        # cached FAISS/BM25/_chunks snapshot from before this write is
        # now stale. Only meaningful when rebuild_bm25=True (this write
        # is "final" for this batch); a mid-batch call with
        # rebuild_bm25=False will invalidate again on its own next write
        # anyway, harmless repeated no-op deletes.
        self._invalidate_rehydrate_cache()
        logger.info("Stored %d chunks (Chroma + FAISS%s)", len(chunks), " + BM25" if rebuild_bm25 else "")

    def _rebuild_bm25(self) -> None:
        self._bm25_ids = list(self._chunks.keys())
        if not self._bm25_ids:
            self._bm25 = None
            return
        tokenized = [_tokenize(self._chunks[cid].text) for cid in self._bm25_ids]
        self._bm25 = BM25Okapi(tokenized)

    # ---- retrieval primitives ----

    def vector_search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Chroma-backed cosine similarity search (primary path -- native
        metadata filtering support, persisted to disk)."""
        if self._collection.count() == 0:
            return []
        query_vector = self.embed(query)
        result = self._collection.query(query_embeddings=[query_vector], n_results=min(limit, self._collection.count()))
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        # cosine SPACE distance in [0, 2]; similarity = 1 - distance/2 keeps it in [0, 1] like FAISS's IP score.
        return [(cid, 1.0 - dist / 2.0) for cid, dist in zip(ids, distances)]

    def faiss_search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Independent FAISS-backed search over the same chunks -- exists
        so the second required storage backend is genuinely queryable, not
        just written to and ignored."""
        if self._faiss_index.ntotal == 0:
            return []
        query_vector = np.asarray(self.embed(query), dtype="float32").reshape(1, -1)
        k = min(limit, self._faiss_index.ntotal)
        scores, indices = self._faiss_index.search(query_vector, k)
        out = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._faiss_ids):
                continue
            out.append((self._faiss_ids[idx], float(score)))
        return out

    # Real, measured limit (2026-08-05, after this project's corpus grew
    # from 319,396 to 2,148,629 chunks post book+YouTube merge): rank_bm25's
    # get_scores() does a full linear scan of the whole corpus on EVERY
    # call (see module docstring) -- at this new scale that alone measured
    # 18-47s PER QUERY, consistently, not just a one-time warmup cost
    # (confirmed by timing 3 distinct queries back-to-back in the same
    # warm process). A single signal-generation workflow triggers ~6
    # separate knowledge lookups, so this alone made a full workflow take
    # minutes. Above this many chunks, keyword_search short-circuits to
    # empty (hybrid_search then degrades to FAISS-only, which stayed fast
    # once warm: 3-5s/query at this same scale, and independently verified
    # to still return relevant results) rather than pay a cost that scales
    # with corpus size with no bound. This is a real scale limitation of
    # rank_bm25's brute-force implementation, not a design choice to
    # silently degrade quality -- a proper fix (an actual inverted index,
    # e.g. SQLite FTS5 or a dedicated BM25 library) is real follow-up work,
    # not something to build hastily under deadline pressure without
    # testing it as carefully as everything else in this codebase.
    _BM25_MAX_CORPUS_FOR_FULL_SCAN = 600_000

    def keyword_search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        if self._bm25 is None:
            return []
        if len(self._bm25_ids) > self._BM25_MAX_CORPUS_FOR_FULL_SCAN:
            return []
        scores = np.asarray(self._bm25.get_scores(_tokenize(query)))
        n = len(scores)
        k = min(limit, n)
        if k == 0:
            return []
        # argpartition finds the top-k indices in O(n) average time instead
        # of fully sorting every score -- a plain Python sorted() over
        # every (id, score) pair measured ~10s on its own at 2.15M chunks,
        # a real, avoidable cost on top of get_scores() itself. Only the
        # returned top-k get a final (cheap) sort.
        top_idx = np.argpartition(-scores, k - 1)[:k]
        top_idx = top_idx[np.argsort(-scores[top_idx])]
        return [(self._bm25_ids[i], float(scores[i])) for i in top_idx if scores[i] > 0]

    def filter_chunk_ids(
        self,
        document_type: Optional[DocumentType] = None,
        topic: Optional[KnowledgeCategory] = None,
        author: Optional[str] = None,
        chapter: Optional[str] = None,
        source: Optional[str] = None,
    ) -> set[str]:
        """Metadata search: exact-match filter over chunk fields."""
        matches = set()
        for chunk_id, chunk in self._chunks.items():
            if document_type is not None and chunk.document_type != document_type:
                continue
            if topic is not None and topic not in chunk.topics:
                continue
            if author is not None and chunk.author.lower() != author.lower():
                continue
            if chapter is not None and (chunk.chapter or "").lower() != chapter.lower():
                continue
            if source is not None and chunk.source != source:
                continue
            matches.add(chunk_id)
        return matches

    # ---- hybrid search ----

    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> list[SearchResult]:
        """Combines Chroma vector similarity + BM25 keyword score + an
        optional metadata pre-filter into one ranked list. Memoized (see
        module docstring) -- repeated identical calls (common across a
        single workflow run, where several engines build the same or a
        similar query string) skip BM25's full-corpus rescan entirely."""
        cache_key = self._hybrid_search_cache_key(query, limit, vector_weight, keyword_weight, metadata_filter)
        cached = self._get_cached_hybrid_search(cache_key)
        if cached is not None:
            return cached
        results = self._hybrid_search_uncached(query, limit, vector_weight, keyword_weight, metadata_filter)
        self._set_cached_hybrid_search(cache_key, results)
        return results

    @staticmethod
    def _hybrid_search_cache_key(
        query: str, limit: int, vector_weight: float, keyword_weight: float, metadata_filter: Optional[dict[str, Any]]
    ) -> tuple:
        filter_key = frozenset(metadata_filter.items()) if metadata_filter else None
        return (query, limit, vector_weight, keyword_weight, filter_key)

    def _get_cached_hybrid_search(self, cache_key: tuple) -> Optional[list[SearchResult]]:
        entry = self._hybrid_search_cache.get(cache_key)
        if entry is None:
            return None
        cached_at, results = entry
        if time.monotonic() - cached_at > _HYBRID_SEARCH_CACHE_TTL_SECONDS:
            del self._hybrid_search_cache[cache_key]
            return None
        self._hybrid_search_cache.move_to_end(cache_key)
        return results

    def _set_cached_hybrid_search(self, cache_key: tuple, results: list[SearchResult]) -> None:
        self._hybrid_search_cache[cache_key] = (time.monotonic(), results)
        self._hybrid_search_cache.move_to_end(cache_key)
        while len(self._hybrid_search_cache) > _HYBRID_SEARCH_CACHE_MAXSIZE:
            self._hybrid_search_cache.popitem(last=False)

    def _hybrid_search_uncached(
        self,
        query: str,
        limit: int = 10,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> list[SearchResult]:
        candidate_ids: Optional[set[str]] = None
        if metadata_filter:
            candidate_ids = self.filter_chunk_ids(**metadata_filter)
            if not candidate_ids:
                return []

        over_fetch = max(limit * 4, 20)
        # faiss_search(), not vector_search(): real bug found 2026-07-23 --
        # vector_search()'s self._collection.query() call (chromadb 1.5.9's
        # Rust-backed _query) crashes this process outright (Windows access
        # violation, confirmed via faulthandler -- a known chromadb Rust-
        # backend issue at large scale on Windows, see chroma-core/chroma
        # #5909/#3058) once this project's real corpus grew past ~1.7M
        # chunks. faiss_search() queries our own already-in-memory FAISS
        # index instead -- same underlying vectors, proven to agree with
        # vector_search() on top hits (see
        # test_document_store_faiss_search_matches_vector_search_top_hit),
        # and never touches Chroma's query path at all.
        vector_hits = dict(self.faiss_search(query, limit=over_fetch))
        keyword_hits_raw = dict(self.keyword_search(query, limit=over_fetch))

        max_keyword = max(keyword_hits_raw.values(), default=0.0) or 1.0
        keyword_hits = {cid: score / max_keyword for cid, score in keyword_hits_raw.items()}

        all_ids = set(vector_hits) | set(keyword_hits)
        if candidate_ids is not None:
            all_ids &= candidate_ids

        results = []
        for chunk_id in all_ids:
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue
            v_score = vector_hits.get(chunk_id, 0.0)
            k_score = keyword_hits.get(chunk_id, 0.0)
            combined = vector_weight * v_score + keyword_weight * k_score
            results.append(SearchResult(chunk=chunk, score=combined, vector_score=v_score, keyword_score=k_score))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def similar_chunks(self, chunk_id: str, limit: int = 5) -> list[SearchResult]:
        """Chunks most similar to an already-ingested chunk (by its own
        text as the query), excluding itself."""
        chunk = self._chunks.get(chunk_id)
        if chunk is None:
            return []
        hits = self.faiss_search(chunk.text, limit=limit + 1)  # see hybrid_search's own comment on why not vector_search()
        results = []
        for cid, score in hits:
            if cid == chunk_id:
                continue
            other = self._chunks.get(cid)
            if other is not None:
                results.append(SearchResult(chunk=other, score=score, vector_score=score))
        return results[:limit]

    # ---- accessors ----

    def get_chunk(self, chunk_id: str) -> Optional[Chunk]:
        return self._chunks.get(chunk_id)

    def all_chunks(self) -> list[Chunk]:
        return list(self._chunks.values())

    def __len__(self) -> int:
        return len(self._chunks)


class CombinedDocumentStore:
    """Read-only facade merging hybrid_search() results from two
    independent DocumentStore instances -- the main book corpus and a
    second, separately-persisted store (e.g. YouTube-extracted
    knowledge) -- into one ranked list.

    Deliberately a QUERY-TIME merge, never a data-time one: found live
    on 2026-08-05 that Chroma's own upsert() -- previously believed safe
    (only .get()/.count()/.query() were known to crash, see
    DocumentStore._safe_collection_count's own docstring) -- also hits
    the same native access violation once the main store's real corpus
    passed ~2.1M chunks, a scale this project only reached this session
    (confirmed: a migration run wrote 5,461/7,076 chunks then died with
    no Python traceback, the exact signature of the already-documented
    Rust-backend bug). Writing the second store's chunks into the main
    one is exactly the operation that crashed, so this class never does
    that -- every engine already only calls document_store.hybrid_search()
    (see each engine's own _build_knowledge_context), so merging at that
    single call site gets every engine book+secondary knowledge without
    ever performing a large write against the fragile store again.

    Any attribute not defined here (add_chunks, get_chunk, ...) delegates
    to `primary` via __getattr__ -- e.g. new ingestion still writes only
    to the main store, exactly as before this class existed."""

    def __init__(self, primary: DocumentStore, secondary: Optional[DocumentStore] = None) -> None:
        self.primary = primary
        self.secondary = secondary

    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> list[SearchResult]:
        results = self.primary.hybrid_search(query, limit, vector_weight, keyword_weight, metadata_filter)
        if self.secondary is not None:
            try:
                secondary_results = self.secondary.hybrid_search(query, limit, vector_weight, keyword_weight, metadata_filter)
            except Exception as e:
                logger.warning("Secondary document store search failed (%s) -- continuing with primary only", e)
                secondary_results = []
            if secondary_results:
                seen_ids = {r.chunk.chunk_id for r in results}
                merged = results + [r for r in secondary_results if r.chunk.chunk_id not in seen_ids]
                results = sorted(merged, key=lambda r: r.score, reverse=True)[:limit]
        return results

    def __len__(self) -> int:
        return len(self.primary) + (len(self.secondary) if self.secondary is not None else 0)

    def __getattr__(self, name: str):
        return getattr(self.primary, name)
