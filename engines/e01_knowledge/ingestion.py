"""
Module: ingestion.py
Description: Orchestrates Engine 01's document pipeline: discover files in
    the allowed directories -> load -> chunk -> classify -> embed & store
    (Chroma + FAISS + BM25) -> update the knowledge graph.

    Directory scope enforcement: per the platform spec, the system may
    ONLY ingest documents under data/books, data/research,
    data/annual_reports, data/sec_filings, data/trading_journals,
    data/notes (relative to the project's own data/ directory -- not OS
    root paths, which wouldn't exist on this machine and would be an
    unreviewable place to read from). ingest_file() enforces this itself
    (not just discover_files()'s glob scope), so calling it directly with
    a path outside those directories fails loudly rather than silently
    reading from somewhere unintended.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

from project_titan_x.engines.e01_knowledge.chunking import chunk_document
from project_titan_x.engines.e01_knowledge.classification import TopicClassifier
from project_titan_x.engines.e01_knowledge.document_store import DocumentStore
from project_titan_x.engines.e01_knowledge.knowledge_graph import KnowledgeGraph
from project_titan_x.engines.e01_knowledge.loaders import LOADERS, load_document
from project_titan_x.engines.e01_knowledge.models import Chunk, DocumentMetadata, DocumentType

logger = logging.getLogger(__name__)

ALLOWED_SUBDIRS = ["books", "research", "annual_reports", "sec_filings", "trading_journals", "notes"]

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


class DocumentOutsideAllowedDirectoryError(PermissionError):
    """Raised when ingest_file() is asked to read a path outside the
    platform's approved document directories."""


class IngestionPipeline:
    def __init__(self, data_root: Optional[Path] = None, store: Optional[DocumentStore] = None) -> None:
        self.data_root = (data_root or Path("data")).resolve()
        # See engine.py's identical comment: DocumentStore defines __len__,
        # so `store or DocumentStore()` would discard an empty-but-real
        # passed-in store. Explicit None-check required.
        self.store = store if store is not None else DocumentStore()
        self.graph = KnowledgeGraph()
        self.classifier = TopicClassifier(embed_fn=self.store.embed)
        self._allowed_dirs = [(self.data_root / sub).resolve() for sub in ALLOWED_SUBDIRS]
        for directory in self._allowed_dirs:
            directory.mkdir(parents=True, exist_ok=True)

        # KnowledgeGraph is pure in-memory (never persisted, unlike
        # DocumentStore's Chroma-backed chunks) -- rebuild it from whatever
        # the store already rehydrated from disk, so related_topics()/
        # sources_for_topic() work immediately after a process restart too.
        for chunk in self.store.all_chunks():
            self.graph.add_chunk(chunk)

    def _validate_path(self, path: Path) -> Path:
        resolved = path.resolve()
        if not any(resolved.is_relative_to(allowed) for allowed in self._allowed_dirs):
            raise DocumentOutsideAllowedDirectoryError(
                f"{resolved} is outside the allowed document directories "
                f"({', '.join(str(d) for d in self._allowed_dirs)})"
            )
        return resolved

    def discover_files(self) -> list[Path]:
        files: list[Path] = []
        for directory in self._allowed_dirs:
            for ext in LOADERS:
                files.extend(sorted(directory.glob(f"*.{ext}")))
        return files

    def ingest_file(self, path: Path, rebuild_bm25: bool = True) -> list[Chunk]:
        resolved = self._validate_path(Path(path))
        suffix = resolved.suffix.lower().lstrip(".")
        document_type = _SUFFIX_TO_DOC_TYPE.get(suffix)
        if document_type is None:
            raise ValueError(f"Unsupported document format: {resolved.suffix}")

        loaded = load_document(resolved)
        doc_id = hashlib.sha256(str(resolved).encode()).hexdigest()[:16]
        doc_meta = DocumentMetadata(
            doc_id=doc_id,
            title=loaded.title,
            author=loaded.author,
            source=str(resolved),
            document_type=document_type,
            total_pages=loaded.total_pages,
        )

        chunks = chunk_document(loaded.elements, doc_meta)
        if chunks:
            # One batched embed call, reused for BOTH classification and
            # storage -- embedding every chunk's text individually (once
            # for classify(), again inside add_chunks()) measured ~5x
            # slower than a single batched call at ingestion scale.
            vectors = self.store.embed_batch([c.text for c in chunks])
            for chunk, vector in zip(chunks, vectors):
                topics, confidence = self.classifier.classify_vector(vector)
                chunk.topics = topics
                chunk.confidence = confidence
            self.store.add_chunks(chunks, vectors=vectors, rebuild_bm25=rebuild_bm25)
            for chunk in chunks:
                self.graph.add_chunk(chunk)

        logger.info("Ingested %s -> %d chunks", resolved.name, len(chunks))
        return chunks

    def ingest_all(self, skip_existing: bool = True) -> dict[str, Any]:
        """skip_existing=True (default) skips any file whose doc_id (a
        hash of its resolved path) already has chunks in the store --
        makes re-running after an interrupted batch (crash, a bug fix
        requiring a restart) resume cheaply instead of re-parsing and
        re-embedding files already done."""
        files = self.discover_files()
        known_doc_ids = {c.doc_id for c in self.store.all_chunks()} if skip_existing else set()
        results: dict[str, Any] = {}
        for i, path in enumerate(files, start=1):
            doc_id = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
            if skip_existing and doc_id in known_doc_ids:
                results[str(path)] = {"success": True, "n_chunks": 0, "skipped": True}
                logger.info("[%d/%d] %s -> already ingested, skipping", i, len(files), path.name)
                continue
            try:
                # BM25 rebuilt once at the end of the batch, not after
                # every file -- see add_chunks()'s docstring for why.
                chunks = self.ingest_file(path, rebuild_bm25=False)
                results[str(path)] = {"success": True, "n_chunks": len(chunks)}
                logger.info("[%d/%d] %s -> %d chunk(s)", i, len(files), path.name, len(chunks))
            except Exception as e:
                logger.error("[%d/%d] Ingestion failed for %s: %s", i, len(files), path, e)
                results[str(path)] = {"success": False, "error": str(e)}
        self.store._rebuild_bm25()
        return results
