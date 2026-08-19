from datetime import datetime, timezone

import pytest

from app.ingestion import KnowledgeChunk
from app.rag.index import FaissKnowledgeIndex


class DeterministicEmbedder:
    def __init__(self, model: str = "test-embedding") -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def _embed(self, text: str) -> list[float]:
        normalized = text.casefold()
        return [
            float(normalized.count("bank") + normalized.count("statement")),
            float(normalized.count("mandate")),
            1.0,
        ]

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)


def chunk(chunk_id: str, content: str, source_type: str = "SYNTHETIC_INTERNAL") -> KnowledgeChunk:
    return KnowledgeChunk(
        document_id="DOC-1",
        source_type=source_type,
        source_title="Demo Guidance",
        source_url="https://example.com/guidance" if source_type == "PUBLIC_NBFC" else None,
        ingested_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        chunk_id=chunk_id,
        content=content,
    )


def test_faiss_build_load_and_retrieve_preserves_provenance(tmp_path) -> None:
    embedder = DeterministicEmbedder()
    chunks = [
        chunk("CHUNK-BANK", "Bank statement upload and income review"),
        chunk("CHUNK-MANDATE", "Mandate setup instructions", "PUBLIC_NBFC"),
    ]
    index = FaissKnowledgeIndex(tmp_path, embedder)

    metadata = index.build(chunks)
    loaded = FaissKnowledgeIndex(tmp_path, embedder)
    loaded.load()
    results = loaded.retrieve("bank statement question", top_k=2)

    assert len(metadata.chunks) == 2
    assert len(metadata.corpus_checksum) == 64
    assert results[0].evidence_id == "CHUNK-BANK"
    assert results[0].source_type == "INTERNAL_RAG"
    assert {result.evidence_id for result in results} == {"CHUNK-BANK", "CHUNK-MANDATE"}
    public = next(result for result in results if result.evidence_id == "CHUNK-MANDATE")
    assert public.source_type == "PUBLIC_RAG"
    assert public.source_url == "https://example.com/guidance"


def test_faiss_rejects_embedding_model_mismatch(tmp_path) -> None:
    FaissKnowledgeIndex(tmp_path, DeterministicEmbedder("model-a")).build(
        [chunk("CHUNK-1", "bank statement")]
    )

    with pytest.raises(ValueError, match="embedding model"):
        FaissKnowledgeIndex(tmp_path, DeterministicEmbedder("model-b")).load()


def test_faiss_rejects_duplicate_chunk_ids(tmp_path) -> None:
    duplicate = chunk("CHUNK-1", "bank statement")
    with pytest.raises(ValueError, match="duplicate"):
        FaissKnowledgeIndex(tmp_path, DeterministicEmbedder()).build([duplicate, duplicate])
