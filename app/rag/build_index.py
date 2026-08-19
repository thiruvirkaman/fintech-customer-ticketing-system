import argparse
import os
from pathlib import Path

from app.ai.config import AISettings
from app.ingestion import build_chunks
from app.rag.index import FaissKnowledgeIndex, OpenAIEmbeddingProvider
from app.rag.sources import PublicSourceFetcher


def build_persistent_index(
    *,
    data_root: Path,
    index_path: Path,
    refresh_public: bool = False,
) -> int:
    settings = AISettings.from_env()
    embedder = OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
        timeout=settings.llm_timeout_seconds,
    )
    public_fetcher = None
    if refresh_public:
        allowed_hosts = {
            host.strip() for host in os.getenv("PUBLIC_SOURCE_ALLOWLIST", "").split(",") if host.strip()
        }
        public_fetcher = PublicSourceFetcher(
            allowed_hosts=allowed_hosts,
            timeout=settings.external_http_timeout_seconds,
        )
    chunks = build_chunks(data_root, public_fetcher=public_fetcher)
    metadata = FaissKnowledgeIndex(index_path, embedder).build(chunks)
    return len(metadata.chunks)


def main() -> None:
    settings = AISettings.from_env()
    parser = argparse.ArgumentParser(description="Build the persistent FAISS knowledge index")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--index-path", type=Path, default=Path(settings.rag_index_path))
    parser.add_argument(
        "--refresh-public",
        action="store_true",
        help="Fetch PUBLIC_NBFC manifest entries from their allowlisted HTTPS URLs",
    )
    args = parser.parse_args()
    count = build_persistent_index(
        data_root=args.data_root,
        index_path=args.index_path,
        refresh_public=args.refresh_public,
    )
    print(f"indexed {count} chunks into {args.index_path}")


if __name__ == "__main__":
    main()
