import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from app.rag.sources import PublicSourceFetcher, read_local_source


class KnowledgeDocument(BaseModel):
    document_id: str = Field(min_length=1)
    source_type: Literal["PUBLIC_NBFC", "SYNTHETIC_INTERNAL"]
    source_title: str = Field(min_length=1)
    path: str = Field(min_length=1)
    source_url: str | None = None

    @model_validator(mode="after")
    def require_public_url(self) -> "KnowledgeDocument":
        if self.source_type == "PUBLIC_NBFC" and not self.source_url:
            raise ValueError("PUBLIC_NBFC documents require source_url provenance")
        if self.source_url:
            parsed_url = urlparse(self.source_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                raise ValueError("source_url must be an absolute HTTPS URL")
        return self


class KnowledgeManifest(BaseModel):
    version: int = Field(ge=1)
    documents: list[KnowledgeDocument] = Field(min_length=1)

    @model_validator(mode="after")
    def ensure_unique_document_ids(self) -> "KnowledgeManifest":
        document_ids = [document.document_id for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("knowledge manifest contains duplicate document_id values")
        return self


class KnowledgeChunk(BaseModel):
    document_id: str
    source_type: Literal["PUBLIC_NBFC", "SYNTHETIC_INTERNAL"]
    source_title: str
    source_url: str | None
    ingested_at: datetime
    chunk_id: str
    content: str


def load_manifest(data_root: Path) -> KnowledgeManifest:
    manifest_path = data_root / "knowledge" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return KnowledgeManifest.model_validate(payload)


def resolve_document_path(data_root: Path, relative_path: str) -> Path:
    resolved_root = data_root.resolve()
    resolved_path = (data_root / relative_path).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"knowledge path escapes data root: {relative_path}")
    if not resolved_path.is_file():
        raise FileNotFoundError(f"knowledge document does not exist: {relative_path}")
    return resolved_path


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
    normalized = text.strip()
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized):
            paragraph_break = normalized.rfind("\n\n", start, end)
            if paragraph_break > start:
                end = paragraph_break
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        next_start = end - overlap
        start = next_start if next_start > start else end
    return chunks


def build_chunks(
    data_root: Path,
    *,
    chunk_size: int = 800,
    overlap: int = 150,
    ingested_at: datetime | None = None,
    public_fetcher: PublicSourceFetcher | None = None,
) -> list[KnowledgeChunk]:
    manifest = load_manifest(data_root)
    timestamp = ingested_at or datetime.now(timezone.utc)
    chunks: list[KnowledgeChunk] = []
    for document in manifest.documents:
        path = resolve_document_path(data_root, document.path)
        if document.source_type == "PUBLIC_NBFC" and public_fetcher is not None:
            assert document.source_url is not None
            content = public_fetcher.fetch(document.source_url)
        else:
            content = read_local_source(path)
        for index, chunk_content in enumerate(split_text(content, chunk_size, overlap), start=1):
            chunks.append(
                KnowledgeChunk(
                    document_id=document.document_id,
                    source_type=document.source_type,
                    source_title=document.source_title,
                    source_url=document.source_url,
                    ingested_at=timestamp,
                    chunk_id=f"{document.document_id}-CHUNK-{index:04d}",
                    content=chunk_content,
                )
            )
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and chunk the local knowledge corpus")
    parser.add_argument("--data-root", type=Path, default=Path(os.getenv("DATA_ROOT", "data")))
    parser.add_argument("--chunk-size", type=int, default=int(os.getenv("RAG_CHUNK_SIZE", "800")))
    parser.add_argument("--overlap", type=int, default=int(os.getenv("RAG_CHUNK_OVERLAP", "150")))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    chunks = build_chunks(args.data_root, chunk_size=args.chunk_size, overlap=args.overlap)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps([chunk.model_dump(mode="json") for chunk in chunks], indent=2),
            encoding="utf-8",
        )
    source_counts: dict[str, int] = {}
    for chunk in chunks:
        source_counts[chunk.source_type] = source_counts.get(chunk.source_type, 0) + 1
    print(json.dumps({"documents": len(load_manifest(args.data_root).documents), "chunks": len(chunks), "source_counts": source_counts}))


if __name__ == "__main__":
    main()
