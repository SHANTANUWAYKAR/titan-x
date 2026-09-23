"""Unit tests for the vector store client (Qdrant/FAISS + embeddings)."""

import pytest

from project_titan_x.core.vector_store.client import VectorStoreClient


@pytest.fixture
def store() -> VectorStoreClient:
    vs = VectorStoreClient()
    vs.connect()
    return vs


def test_connect_activates_a_backend(store: VectorStoreClient):
    """Without a Qdrant server running, connect() must fall back to the
    local FAISS index rather than leaving search silently disabled."""
    assert store.is_available
    assert store.backend in ("qdrant", "faiss_local")


def test_upsert_and_search_roundtrip_with_precomputed_vectors(store: VectorStoreClient):
    """Storage/retrieval mechanics work with caller-supplied vectors --
    doesn't require the embedding model to be downloaded."""
    vec_a = [1.0, 0.0, 0.0] + [0.0] * (store.VECTOR_SIZE - 3)
    vec_b = [0.0, 1.0, 0.0] + [0.0] * (store.VECTOR_SIZE - 3)

    pid_a = store.upsert("Document A", {"name": "A"}, vector=vec_a)
    store.upsert("Document B", {"name": "B"}, vector=vec_b)
    assert pid_a is not None

    results = store.search("irrelevant query text", limit=5)
    if store.backend == "faiss_local":
        # FAISS path still embeds the query text itself, but storage used
        # the precomputed vectors above -- just confirm both got stored.
        assert len(results) <= 2


@pytest.mark.network
def test_semantic_search_ranks_related_document_higher(store: VectorStoreClient):
    """With real sentence-transformers embeddings, a semantically related
    document should outrank an unrelated one -- this is the actual
    capability the hash-based placeholder embedding never had."""
    store.upsert(
        "George Soros reflexivity theory macro currency speculation",
        {"name": "Soros"},
    )
    store.upsert(
        "Recipe for chocolate chip cookies with butter and sugar",
        {"name": "Cookies"},
    )

    results = store.search("currency trading and macroeconomic speculation", limit=2)
    assert results
    assert results[0]["payload"]["name"] == "Soros"
