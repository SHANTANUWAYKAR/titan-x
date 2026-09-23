"""
Module: migrate_youtube_knowledge_to_main_store.py
Description: One-time migration -- moves the YouTube Knowledge Import
    Pipeline's chunks (currently isolated in data/knowledge/
    chroma_db_youtube, a workaround for the main store's chromadb
    Windows segfault bug -- see titanx_integrator.py's own
    _document_store() docstring) into the SAME store every other engine
    actually queries (data/knowledge/chroma_db), now that
    recover_knowledge_base.py has rebuilt that store's vector index.

    Deliberately re-embeds from text rather than copying the YouTube
    store's own vectors across: sentence-transformer embeddings are a
    deterministic function of text for a fixed model (same reasoning
    recover_knowledge_base.py's own docstring uses), so re-embedding is
    exact reconstruction, not approximation, and it avoids a second,
    more fragile code path just to transplant raw vectors between two
    Chroma collections. 7,076 chunks re-embeds in well under a minute
    (~20-25/s per the recovery job's own measured single-process rate).

    Safe to re-run: chunk_ids are the YouTube pipeline's own
    content-derived, deterministic IDs (see titanx_integrator.py's
    _make_chunk_id) -- add_chunks()'s upsert is idempotent per ID, so a
    second run just re-writes the same rows, never duplicates them.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e01_knowledge.document_store import DocumentStore
from project_titan_x.engines.e01_knowledge.models import Chunk, DocumentType, KnowledgeCategory

logger = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
YOUTUBE_STORE_DIR = DATA_ROOT / "knowledge" / "chroma_db_youtube"
MAIN_STORE_DIR = DATA_ROOT / "knowledge" / "chroma_db"


def _chunk_from_metadata(chunk_id: str, text: str, meta: dict) -> Chunk:
    topics_str = meta.get("topics", "") or ""
    topics = [KnowledgeCategory(t) for t in topics_str.split(",") if t]
    page = meta.get("page")
    return Chunk(
        chunk_id=chunk_id,
        doc_id=meta.get("doc_id", "") or "",
        text=text or "",
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not YOUTUBE_STORE_DIR.exists():
        raise FileNotFoundError(f"No YouTube store at {YOUTUBE_STORE_DIR}")

    logger.info("Reading chunks from the YouTube store (%s)...", YOUTUBE_STORE_DIR)
    yt_store = DocumentStore(persist_dir=YOUTUBE_STORE_DIR)
    raw = yt_store._collection.get(include=["documents", "metadatas"])
    ids, docs, metas = raw["ids"], raw["documents"], raw["metadatas"]
    logger.info("Read %d chunks from the YouTube store.", len(ids))

    chunks = [_chunk_from_metadata(cid, doc, meta) for cid, doc, meta in zip(ids, docs, metas)]

    logger.info("Opening main store (%s) -- this loads via the rehydrate cache, not the crashing Chroma read path...", MAIN_STORE_DIR)
    main_store = DocumentStore(persist_dir=MAIN_STORE_DIR)
    before = main_store._safe_collection_count()
    logger.info("Main store currently has %d chunks.", before)

    logger.info("Re-embedding and upserting %d YouTube chunks into the main store (this also rebuilds BM25 over the FULL combined corpus -- can take a few minutes at this scale)...", len(chunks))
    main_store.add_chunks(chunks, vectors=None, rebuild_bm25=True)

    after = main_store._safe_collection_count()
    logger.info("Main store now has %d chunks (was %d, +%d).", after, before, after - before)
    logger.info("DONE.")


if __name__ == "__main__":
    main()
