from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.ingestion import KnowledgeDocument, build_chunks, load_manifest, resolve_document_path, split_text


DATA_ROOT = Path("data")


def test_manifest_and_synthetic_corpus_build_chunks() -> None:
    manifest = load_manifest(DATA_ROOT)
    chunks = build_chunks(
        DATA_ROOT,
        chunk_size=800,
        overlap=150,
        ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert len(manifest.documents) == 3
    assert chunks
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert {chunk.source_type for chunk in chunks} == {"SYNTHETIC_INTERNAL"}
    assert all(chunk.document_id.startswith("SYN-LOS-") for chunk in chunks)


def test_chunking_validates_bounds() -> None:
    assert split_text("abcdefghij", chunk_size=6, overlap=2) == ["abcdef", "efghij"]
    with pytest.raises(ValueError, match="smaller than chunk_size"):
        split_text("text", chunk_size=10, overlap=10)


def test_document_path_cannot_escape_data_root() -> None:
    with pytest.raises(ValueError, match="escapes data root"):
        resolve_document_path(DATA_ROOT, "../README.md")


def test_public_document_requires_absolute_https_provenance() -> None:
    with pytest.raises(ValueError, match="absolute HTTPS URL"):
        KnowledgeDocument(
            document_id="PUBLIC-001",
            source_type="PUBLIC_NBFC",
            source_title="Example public source",
            path="knowledge/public/example.md",
            source_url="http://example.com/policy",
        )
