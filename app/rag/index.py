import json
import math
import os
from hashlib import sha256
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import faiss
import numpy as np
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator

from app.ai.contracts import EvidenceItem
from app.ingestion import KnowledgeChunk


class EmbeddingProvider(Protocol):
    @property
    def model(self) -> str: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        timeout: float = 20.0,
        client: OpenAI | None = None,
    ) -> None:
        if not api_key and client is None:
            raise RuntimeError("OPENAI_API_KEY is required to build or query the knowledge index")
        self._model = model
        self._client = client or OpenAI(api_key=api_key, timeout=timeout, max_retries=1)

    @property
    def model(self) -> str:
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(model=self._model, input=list(texts))
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("RAG query must not be empty")
        response = self._client.embeddings.create(model=self._model, input=[text])
        return list(response.data[0].embedding)


class IndexedChunk(BaseModel):
    document_id: str
    source_type: str
    source_title: str
    source_url: str | None
    ingested_at: datetime
    chunk_id: str
    content: str = Field(min_length=1)


class IndexMetadata(BaseModel):
    schema_version: int = 1
    embedding_model: str = Field(min_length=1)
    vector_dimension: int = Field(gt=0)
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    indexed_at: datetime
    chunks: list[IndexedChunk] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_chunks(self) -> "IndexMetadata":
        ids = [chunk.chunk_id for chunk in self.chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("FAISS metadata contains duplicate chunk IDs")
        return self


class FaissKnowledgeIndex:
    INDEX_FILENAME = "knowledge.index"
    METADATA_FILENAME = "metadata.json"

    def __init__(self, index_dir: Path, embedder: EmbeddingProvider) -> None:
        self._index_dir = index_dir
        self._embedder = embedder
        self._index: faiss.Index | None = None
        self._metadata: IndexMetadata | None = None

    def build(self, chunks: Sequence[KnowledgeChunk]) -> IndexMetadata:
        if not chunks:
            raise ValueError("cannot build a knowledge index without chunks")
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("cannot index duplicate chunk IDs")

        vectors = _as_normalized_matrix(self._embedder.embed_documents([chunk.content for chunk in chunks]))
        if vectors.shape[0] != len(chunks):
            raise ValueError("embedding provider returned the wrong number of vectors")
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        timestamp = datetime.now(timezone.utc)
        metadata = IndexMetadata(
            embedding_model=self._embedder.model,
            vector_dimension=vectors.shape[1],
            corpus_checksum=_corpus_checksum(chunks),
            indexed_at=timestamp,
            chunks=[IndexedChunk.model_validate(chunk.model_dump()) for chunk in chunks],
        )

        self._index_dir.mkdir(parents=True, exist_ok=True)
        index_path = self._index_dir / self.INDEX_FILENAME
        metadata_path = self._index_dir / self.METADATA_FILENAME
        temporary_index = index_path.with_suffix(".tmp")
        temporary_metadata = metadata_path.with_suffix(".tmp")
        faiss.write_index(index, str(temporary_index))
        temporary_metadata.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary_index, index_path)
        os.replace(temporary_metadata, metadata_path)
        self._index = index
        self._metadata = metadata
        return metadata

    def load(self) -> IndexMetadata:
        metadata_path = self._index_dir / self.METADATA_FILENAME
        index_path = self._index_dir / self.INDEX_FILENAME
        metadata = IndexMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        index = faiss.read_index(str(index_path))
        if index.ntotal != len(metadata.chunks) or index.d != metadata.vector_dimension:
            raise ValueError("FAISS index and metadata are inconsistent")
        if metadata.embedding_model != self._embedder.model:
            raise ValueError(
                f"index embedding model is {metadata.embedding_model}, configured model is {self._embedder.model}"
            )
        if metadata.corpus_checksum != _corpus_checksum(metadata.chunks):
            raise ValueError("FAISS metadata corpus checksum is invalid")
        self._index = index
        self._metadata = metadata
        return metadata

    def retrieve(self, query: str, *, top_k: int = 4) -> list[EvidenceItem]:
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if not query.strip():
            raise ValueError("RAG query must not be empty")
        if self._index is None or self._metadata is None:
            self.load()
        assert self._index is not None
        assert self._metadata is not None

        vector = _as_normalized_matrix([self._embedder.embed_query(query)])
        if vector.shape[1] != self._metadata.vector_dimension:
            raise ValueError("query embedding dimension does not match the FAISS index")
        count = min(top_k, self._index.ntotal)
        scores, positions = self._index.search(vector, count)
        evidence: list[EvidenceItem] = []
        for score, position in zip(scores[0], positions[0], strict=True):
            if position < 0:
                continue
            chunk = self._metadata.chunks[int(position)]
            evidence.append(
                EvidenceItem(
                    evidence_id=chunk.chunk_id,
                    source_type="PUBLIC_RAG" if chunk.source_type == "PUBLIC_NBFC" else "INTERNAL_RAG",
                    source=chunk.source_title,
                    source_url=chunk.source_url,
                    content=chunk.content,
                    relevance_score=max(-1.0, min(1.0, float(score))),
                )
            )
        return evidence


def _as_normalized_matrix(vectors: Sequence[Sequence[float]]) -> np.ndarray:
    if not vectors:
        raise ValueError("embedding provider returned no vectors")
    matrix = np.asarray(vectors, dtype="float32")
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise ValueError("embeddings must be a non-empty two-dimensional matrix")
    if not np.isfinite(matrix).all():
        raise ValueError("embeddings contain non-finite values")
    norms = np.linalg.norm(matrix, axis=1)
    if any(math.isclose(float(norm), 0.0) for norm in norms):
        raise ValueError("embeddings must not be zero vectors")
    faiss.normalize_L2(matrix)
    return matrix


def _corpus_checksum(chunks: Sequence[KnowledgeChunk | IndexedChunk]) -> str:
    payload = [chunk.model_dump(mode="json") for chunk in chunks]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()
