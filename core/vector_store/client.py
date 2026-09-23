"""
Module: client.py
Description: Vector store client for knowledge intelligence -- Qdrant
             primary (when a server is reachable), local FAISS fallback
             otherwise, both backed by real sentence-transformers
             embeddings instead of a hash-based placeholder.
Author: Shantanu Waykar
Version: 2.0.0
Last Modified: 2026-07-14
"""

import hashlib
import logging
import uuid
from functools import lru_cache
from typing import Any, Optional

import numpy as np

from project_titan_x.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logger.warning("qdrant-client not installed; Qdrant backend disabled")

try:
    import faiss

    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("faiss-cpu not installed; local fallback vector index disabled")

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache
def _get_embedding_model() -> Any:
    """Process-wide cached embedding model. Both the import AND the load
    are deferred to first actual use (not module import time): importing
    sentence-transformers pulls in transformers + torch, which alone
    measured ~23s of a ~33s server cold start -- 70% of total startup
    time paid on every launch whether or not semantic search was ever
    used that session. Loading the model itself is also a one-time cost
    (first run also downloads ~90MB from the HuggingFace Hub) -- must not
    be paid per VectorStoreClient instance, hence the process-wide cache.

    Prefers local_files_only once the model is cached: without it,
    sentence-transformers/huggingface_hub issues a HEAD request per
    encode() call to check for updates, which on a flaky/offline network
    silently degrades every embedding to the meaningless hash fallback
    below instead of failing loudly.
    """
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
    except Exception:
        return SentenceTransformer(EMBEDDING_MODEL_NAME)


class VectorStoreClient:
    """Vector store for semantic knowledge search.

    Backend priority: Qdrant (if a server is reachable) -> local in-memory
    FAISS index (zero infra required) -> disabled (search returns empty).
    The FAISS fallback is intentionally non-persistent -- it exists so
    semantic search still works during local research/dev when the Qdrant
    container isn't running, not as a production substitute for Qdrant.

    Embeddings: real sentence-transformers vectors when the library is
    installed and loads successfully, degrading to a deterministic
    hash-based pseudo-embedding otherwise -- which has NO actual semantic
    meaning, only kept so upsert/search don't crash outright when the
    embedding model isn't available.
    """

    VECTOR_SIZE = 384  # all-MiniLM-L6-v2's output dimension

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._collection = settings.qdrant_collection
        self.backend = "none"
        self._faiss_index = None
        self._faiss_payloads: dict[int, dict[str, Any]] = {}
        self._faiss_next_id = 0

    @property
    def is_available(self) -> bool:
        return self.backend != "none"

    def connect(self) -> bool:
        """
        Connect to Qdrant; fall back to a local FAISS index if no Qdrant
        server is reachable.

        Returns:
            True if EITHER backend is usable (upsert/search will work).
        """
        if QDRANT_AVAILABLE and self._connect_qdrant():
            self.backend = "qdrant"
            return True

        if FAISS_AVAILABLE:
            self._faiss_index = faiss.IndexFlatIP(self.VECTOR_SIZE)
            self._faiss_payloads = {}
            self._faiss_next_id = 0
            self.backend = "faiss_local"
            logger.info("Qdrant unavailable -- using local FAISS fallback (in-memory, non-persistent)")
            return True

        self.backend = "none"
        return False

    def _connect_qdrant(self) -> bool:
        try:
            self._client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
            collections = [c.name for c in self._client.get_collections().collections]
            if self._collection not in collections:
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(size=self.VECTOR_SIZE, distance=Distance.COSINE),
                )
            logger.info("Connected to Qdrant at %s:%s", settings.qdrant_host, settings.qdrant_port)
            return True
        except Exception as e:
            logger.warning("Qdrant connection failed (%s) -- trying FAISS fallback", e)
            self._client = None
            return False

    def upsert(
        self,
        text: str,
        metadata: dict[str, Any],
        vector: Optional[list[float]] = None,
        point_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Store a knowledge document with vector embedding.

        Args:
            text: Document text content.
            metadata: Associated metadata.
            vector: Pre-computed embedding vector.
            point_id: Optional existing point ID.

        Returns:
            Point ID if successful, None otherwise.
        """
        # Not `vector or ...`: a caller-supplied vector that happens to be
        # falsy (e.g. []) must still be used as-is, not silently replaced.
        vec = vector if vector is not None else self._embed(text)

        if self.backend == "qdrant" and self._client:
            try:
                pid = point_id or str(uuid.uuid4())
                self._client.upsert(
                    collection_name=self._collection,
                    points=[
                        PointStruct(id=pid, vector=vec, payload={"text": text, **metadata}),
                    ],
                )
                return pid
            except Exception as e:
                logger.error("Qdrant upsert failed: %s", e)
                return None

        if self.backend == "faiss_local" and self._faiss_index is not None:
            pid = point_id or str(uuid.uuid4())
            arr = self._normalize(np.asarray(vec, dtype="float32").reshape(1, -1))
            faiss_id = self._faiss_next_id
            self._faiss_next_id += 1
            self._faiss_index.add(arr)
            self._faiss_payloads[faiss_id] = {"point_id": pid, "text": text, **metadata}
            return pid

        return None

    def search(
        self,
        query: str,
        limit: int = 10,
        filter_metadata: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic search across knowledge base.

        Args:
            query: Search query text.
            limit: Maximum results to return.
            filter_metadata: Optional metadata filters (Qdrant backend only).

        Returns:
            List of matching documents with scores.
        """
        query_vector = self._embed(query)

        if self.backend == "qdrant" and self._client:
            try:
                # .search() was removed from qdrant-client (this project pins
                # 1.18.0) in favor of .query_points() -- same scored-point
                # shape (.id/.score/.payload), just wrapped in a
                # QueryResponse's .points list instead of returned bare.
                response = self._client.query_points(
                    collection_name=self._collection,
                    query=query_vector,
                    limit=limit,
                )
                return [
                    {"id": str(r.id), "score": r.score, "payload": r.payload}
                    for r in response.points
                ]
            except Exception as e:
                logger.error("Qdrant search failed: %s", e)
                return []

        if self.backend == "faiss_local" and self._faiss_index is not None and self._faiss_index.ntotal > 0:
            arr = self._normalize(np.asarray(query_vector, dtype="float32").reshape(1, -1))
            k = min(limit, self._faiss_index.ntotal)
            scores, indices = self._faiss_index.search(arr, k)
            out = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0:
                    continue
                payload = self._faiss_payloads.get(int(idx), {})
                out.append({
                    "id": payload.get("point_id", str(idx)),
                    "score": float(score),
                    "payload": payload,
                })
            return out

        return []

    def _embed(self, text: str) -> list[float]:
        """Real sentence-transformers embedding when available (imported
        and loaded lazily on first call, see _get_embedding_model);
        degrades to a hash-based pseudo-embedding (no semantic meaning)
        if the library isn't installed or loading fails for any reason."""
        try:
            model = _get_embedding_model()
            vector = model.encode(text, normalize_embeddings=True)
            return vector.tolist()
        except Exception as e:
            logger.warning(
                "sentence-transformers embedding failed (%s) -- using hash-based pseudo-embedding", e
            )
        return self._simple_hash_vector(text)

    @staticmethod
    def _normalize(arr: np.ndarray) -> np.ndarray:
        """L2-normalize so FAISS's inner-product index computes cosine
        similarity, matching Qdrant's COSINE distance metric above."""
        norm = np.linalg.norm(arr)
        return arr / norm if norm > 0 else arr

    @staticmethod
    def _simple_hash_vector(text: str, size: int = 384) -> list[float]:
        """
        Deterministic pseudo-embedding fallback -- has NO actual semantic
        meaning (two related sentences get unrelated vectors). Only used
        when sentence-transformers isn't installed or fails to load, so
        upsert/search keep functioning rather than crashing outright.
        """
        h = hashlib.sha256(text.encode()).digest()
        return [(h[i % len(h)] / 127.5) - 1.0 for i in range(size)]
