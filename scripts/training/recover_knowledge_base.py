"""
Module: recover_knowledge_base.py
Description: One-time recovery from a real chromadb 1.5.9 bug found
    2026-07-23: the Rust-backed collection.count()/.get()/.query() calls
    crash this process outright (Windows access violation, confirmed via
    `python -X faulthandler`) once this project's real corpus grew past
    ~1.7M chunks -- a known chroma-core issue on Windows at scale (see
    chroma-core/chroma #5909, #3058), not memory exhaustion (a larger
    page file did not help) and not data corruption (Chroma's own SQLite
    metadata/document tables read back cleanly and fast via raw SQL; only
    the separate proprietary HNSW vector-segment binary format is
    affected, and the older Python SegmentAPI backend cannot read data
    written by the Rust backend either -- confirmed incompatible on-disk
    formats, not a simple version-skew).

    Recovery: every chunk's full text and metadata is still completely
    intact and readable via raw SQL against Chroma's own chroma.sqlite3
    (see extract_chunks() below) -- only the vector index is affected.
    Since sentence-transformer embeddings are a deterministic function of
    text for a fixed model, re-embedding from the recovered text is exact
    reconstruction, not approximation -- zero information loss.

    Parallel + resumable (added after the first single-process attempt
    measured ~475min ETA -- too slow): splits the corpus into N_WORKERS
    contiguous slices, each embedded by its own OS process (CPU-bound
    model inference parallelizes across processes; each worker's own
    small model copy is cheap, ~90MB). Each worker appends raw float32
    vector bytes to its own dedicated file as it completes each batch --
    a restart re-extracts chunks (cheap, ~250s) and checks each worker's
    output file SIZE to know how many vectors are already done, skipping
    that many texts and resuming -- so a session restart (this project's
    single biggest source of lost work all week) costs at most one
    partial batch per worker, never hours of re-computation.

    Writes a fresh DocumentStore rehydrate cache at the end so every
    future process start loads instantly from it and never needs to call
    Chroma's broken read path again. document_store.py's
    _safe_collection_count() (raw SQL) and hybrid_search()/
    similar_chunks() (routed onto faiss_search() instead of
    vector_search()) complete the fix so nothing in this codebase calls
    the crashing Rust read paths anymore. Chroma's own .upsert() (writes)
    is untouched and confirmed NOT affected -- only reads crash -- so
    ingestion keeps persisting new chunks into the same Chroma store
    exactly as before.
Author: Shantanu Waykar
Version: 2.0.0
"""

import multiprocessing
import pickle
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

import numpy as np  # noqa: E402

from project_titan_x.engines.e01_knowledge.models import Chunk, DocumentType, KnowledgeCategory  # noqa: E402

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
PERSIST_DIR = DATA_ROOT / "knowledge" / "chroma_db"
DB_PATH = PERSIST_DIR / "chroma.sqlite3"
WORK_DIR = DATA_ROOT / "knowledge" / "_recovery_work"

N_WORKERS = 4
EMBED_BATCH = 2048
VECTOR_DIM = 384
BYTES_PER_VECTOR = VECTOR_DIM * 4  # float32


def _build_chunk(chunk_id, meta):
    text = meta.get("chroma:document", "") or ""
    topics_str = meta.get("topics", "") or ""
    topics = [KnowledgeCategory(t) for t in topics_str.split(",") if t]
    page = meta.get("page")
    return Chunk(
        chunk_id=chunk_id,
        doc_id=meta.get("doc_id", "") or "",
        text=text,
        title=meta.get("title", "") or "",
        author=meta.get("author", "") or "",
        source=meta.get("source", "") or "",
        document_type=DocumentType(meta.get("document_type") or DocumentType.TXT.value),
        page=page if page is not None and page != -1 else None,
        chapter=meta.get("chapter") or None,
        topics=topics,
        confidence=float(meta.get("confidence") or 0.0),
        contains_table=bool(meta.get("contains_table") or False),
        contains_formula=bool(meta.get("contains_formula") or False),
    )


def extract_chunks() -> list:
    from project_titan_x.engines.e01_knowledge.document_store import COLLECTION_NAME

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT e.id, e.embedding_id, em.key, em.string_value, em.int_value, em.float_value, em.bool_value
            FROM embeddings e
            JOIN embedding_metadata em ON em.id = e.id
            JOIN segments s ON e.segment_id = s.id
            JOIN collections c ON s.collection = c.id
            WHERE c.name = ?
            ORDER BY e.id
            """,
            (COLLECTION_NAME,),
        )

        chunks = []
        current_id = None
        current_chunk_id = None
        current_meta: dict = {}
        t0 = time.time()
        for row_id, embedding_id, key, sval, ival, fval, bval in cur:
            if row_id != current_id:
                if current_id is not None:
                    chunks.append(_build_chunk(current_chunk_id, current_meta))
                    if len(chunks) % 200_000 == 0:
                        print(f"  extracted {len(chunks)} chunks ({time.time() - t0:.0f}s elapsed)", flush=True)
                current_id = row_id
                current_chunk_id = embedding_id
                current_meta = {}
            if sval is not None:
                value = sval
            elif ival is not None:
                value = ival
            elif fval is not None:
                value = fval
            else:
                value = bval
            current_meta[key] = value
        if current_id is not None:
            chunks.append(_build_chunk(current_chunk_id, current_meta))
        return chunks
    finally:
        conn.close()


def _worker_embed_slice(worker_id: int, texts: list, out_path: str) -> None:
    """Runs in its own process. Resumable: checks out_path's current size
    to know how many vectors are already written, skips that many texts,
    and appends (never overwrites) from there -- a kill/restart mid-run
    loses at most the in-flight batch, not this worker's whole slice.

    Real bug found 2026-07-23: the first version of this function let
    torch/BLAS pick its own thread count per worker (its default is "use
    every logical core"), so N_WORKERS processes each tried to use all 12
    cores simultaneously -- pure oversubscription, not parallelism. Measured
    throughput barely beat the single-process baseline (16/s/worker * 4
    workers ~= 64/s, vs ~50-60/s single-process). Setting these env vars
    BEFORE numpy/torch get imported anywhere in this process (must happen
    first thing in a freshly spawned worker, before the _get_embedding_model
    import below pulls torch in transitively) caps each worker to its fair
    share of cores, so N_WORKERS processes actually add up to ~N_WORKERS x
    the single-process rate instead of fighting each other for the same
    cores."""
    import os

    threads_per_worker = max(1, multiprocessing.cpu_count() // N_WORKERS)
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[var] = str(threads_per_worker)

    from project_titan_x.core.vector_store.client import _get_embedding_model

    import torch

    torch.set_num_threads(threads_per_worker)

    out_file = Path(out_path)
    already_done = out_file.stat().st_size // BYTES_PER_VECTOR if out_file.exists() else 0
    if already_done >= len(texts):
        print(f"[worker {worker_id}] already complete ({already_done} vectors), skipping", flush=True)
        return

    model = _get_embedding_model()
    t0 = time.time()
    with open(out_file, "ab") as f:
        i = already_done
        while i < len(texts):
            batch = texts[i : i + EMBED_BATCH]
            vecs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
            f.write(np.asarray(vecs, dtype="float32").tobytes())
            f.flush()
            i += len(batch)
            elapsed = time.time() - t0
            rate = (i - already_done) / elapsed if elapsed > 0 else 0
            print(f"[worker {worker_id}] {i}/{len(texts)} ({rate:.0f}/s)", flush=True)
    print(f"[worker {worker_id}] DONE", flush=True)


def main() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print("Extracting chunks via raw SQL (Chroma's Rust query path is never touched)...", flush=True)
    chunks = extract_chunks()
    print(f"Extracted {len(chunks)} chunks in {time.time() - t0:.1f}s", flush=True)

    n = len(chunks)
    slice_size = (n + N_WORKERS - 1) // N_WORKERS
    slices = [(i, min(i + slice_size, n)) for i in range(0, n, slice_size)]

    print(f"Embedding {n} chunks across {len(slices)} parallel workers (resumable)...", flush=True)
    t0 = time.time()
    procs = []
    for worker_id, (start, end) in enumerate(slices):
        texts = [c.text for c in chunks[start:end]]
        out_path = str(WORK_DIR / f"vectors_worker_{worker_id}.bin")
        p = multiprocessing.Process(target=_worker_embed_slice, args=(worker_id, texts, out_path))
        p.start()
        procs.append(p)
    for p in procs:
        p.join()
    print(f"All workers finished in {time.time() - t0:.1f}s", flush=True)

    print("Reassembling vectors in original order...", flush=True)
    vec_parts = []
    for worker_id, (start, end) in enumerate(slices):
        out_path = WORK_DIR / f"vectors_worker_{worker_id}.bin"
        expected = end - start
        arr = np.fromfile(out_path, dtype="float32").reshape(-1, VECTOR_DIM)
        if len(arr) != expected:
            raise RuntimeError(f"worker {worker_id} incomplete: got {len(arr)} vectors, expected {expected}")
        vec_parts.append(arr)
    vectors = np.concatenate(vec_parts, axis=0)
    print(f"Reassembled {len(vectors)} vectors", flush=True)

    import faiss
    from rank_bm25 import BM25Okapi

    from project_titan_x.engines.e01_knowledge.document_store import VECTOR_SIZE, _tokenize

    print("Building fresh FAISS index...", flush=True)
    t0 = time.time()
    faiss_index = faiss.IndexFlatIP(VECTOR_SIZE)
    faiss_index.add(vectors)
    faiss_ids = [c.chunk_id for c in chunks]
    print(f"FAISS index built in {time.time() - t0:.1f}s ({faiss_index.ntotal} vectors)", flush=True)

    print("Building fresh BM25 index...", flush=True)
    t0 = time.time()
    tokenized = [_tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(tokenized)
    print(f"BM25 index built in {time.time() - t0:.1f}s", flush=True)

    chunks_dict = {c.chunk_id: c for c in chunks}

    print("Writing rehydrate cache (future process starts load from this, not Chroma's broken read path)...", flush=True)
    faiss.write_index(faiss_index, str(PERSIST_DIR / "_rehydrate_cache_faiss.index"))
    with open(PERSIST_DIR / "_rehydrate_cache_meta.pkl", "wb") as f:
        pickle.dump(
            {"count": len(chunks), "chunks": chunks_dict, "faiss_ids": faiss_ids, "bm25_ids": faiss_ids, "bm25": bm25},
            f,
        )
    print(f"DONE. Recovered {len(chunks)} chunks.", flush=True)

    for worker_id in range(len(slices)):
        (WORK_DIR / f"vectors_worker_{worker_id}.bin").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
