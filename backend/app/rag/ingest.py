import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_QDRANT_COLLECTION = "tnchatbot_kb"
DEFAULT_EMBEDDING_URL = "http://localhost:8001/v1/embeddings"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

LOGGER = logging.getLogger(__name__)


def get_connection() -> psycopg.Connection:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    return psycopg.connect(database_url)


def request_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    if not body:
        return {}
    return json.loads(body)


def ensure_qdrant_collection(vector_size: int) -> None:
    qdrant_url = os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL).rstrip("/")
    collection = os.getenv("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION)
    collection_url = f"{qdrant_url}/collections/{collection}"
    try:
        request_json("GET", collection_url)
        return
    except HTTPError as exc:
        if exc.code != 404:
            raise

    payload = {
        "vectors": {
            "size": vector_size,
            "distance": "Cosine",
        }
    }
    request_json("PUT", collection_url, payload)


@dataclass(frozen=True)
class Chunk:
    document_id: uuid.UUID
    chunk_index: int
    content: str
    token_count: int


def chunk_text(text: str, max_tokens: int, overlap: int) -> List[str]:
    words = [word for word in text.split() if word.strip()]
    if not words:
        return []
    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_tokens, len(words))
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))
        if end == len(words):
            break
        start = max(0, end - overlap)
    return chunks


def estimate_tokens(text: str) -> int:
    return len([word for word in text.split() if word.strip()])


def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    if not texts:
        return []
    embedding_url = os.getenv("EMBEDDING_URL", DEFAULT_EMBEDDING_URL)
    embedding_model = os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    payload = {
        "model": embedding_model,
        "input": texts,
    }
    try:
        response = request_json("POST", embedding_url, payload)
    except (HTTPError, URLError) as exc:
        raise RuntimeError("Embedding request failed") from exc

    data = response.get("data", [])
    embeddings: List[List[float]] = []
    for item in data:
        embeddings.append(item.get("embedding", []))
    if len(embeddings) != len(texts):
        raise RuntimeError("Embedding response size mismatch")
    return embeddings


def iter_source_files(source_dir: Path) -> Iterable[Path]:
    for path in sorted(source_dir.iterdir()):
        if path.name.startswith("."):
            continue
        if path.is_dir():
            continue
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        yield path


def upsert_qdrant_points(points: List[dict]) -> None:
    if not points:
        return
    qdrant_url = os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL).rstrip("/")
    collection = os.getenv("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION)
    url = f"{qdrant_url}/collections/{collection}/points?wait=true"
    request_json("PUT", url, {"points": points})


def ingest_sources(source_dir: Path | str | None = None) -> dict:
    chunk_size = int(os.getenv("RAG_CHUNK_SIZE", "200"))
    overlap = int(os.getenv("RAG_CHUNK_OVERLAP", "40"))
    source_root = Path(source_dir or "kb_sources").resolve()

    with get_connection() as conn:
        run_id = conn.execute(
            "INSERT INTO kb_ingestion_runs (status) VALUES ('running') RETURNING id"
        ).fetchone()[0]

        stats = {
            "documents": 0,
            "chunks": 0,
            "skipped": 0,
        }

        for path in iter_source_files(source_root):
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                stats["skipped"] += 1
                continue

            doc_id = conn.execute(
                """
                INSERT INTO kb_documents (ingestion_run_id, source_type, source_uri, title, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (run_id, "file", str(path.relative_to(source_root)), path.stem, "processing"),
            ).fetchone()[0]

            chunks = chunk_text(text, chunk_size, overlap)
            if not chunks:
                conn.execute(
                    "UPDATE kb_documents SET status = %s, updated_at = NOW() WHERE id = %s",
                    ("empty", doc_id),
                )
                stats["skipped"] += 1
                continue

            embeddings = embed_texts(chunks)
            ensure_qdrant_collection(len(embeddings[0]))
            points: List[dict] = []

            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_id = uuid.uuid4()
                token_count = estimate_tokens(chunk)
                conn.execute(
                    """
                    INSERT INTO kb_chunks (id, document_id, chunk_index, content, embedding, token_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        chunk_id,
                        doc_id,
                        index,
                        chunk,
                        json.dumps(embedding),
                        token_count,
                    ),
                )
                points.append(
                    {
                        "id": str(chunk_id),
                        "vector": embedding,
                        "payload": {
                            "document_id": str(doc_id),
                            "chunk_index": index,
                            "content": chunk,
                            "source_uri": str(path.relative_to(source_root)),
                            "title": path.stem,
                        },
                    }
                )

            upsert_qdrant_points(points)
            conn.execute(
                "UPDATE kb_documents SET status = %s, updated_at = NOW() WHERE id = %s",
                ("ready", doc_id),
            )

            stats["documents"] += 1
            stats["chunks"] += len(chunks)

        conn.execute(
            """
            UPDATE kb_ingestion_runs
            SET status = %s, finished_at = NOW(), stats = %s
            WHERE id = %s
            """,
            ("finished", json.dumps(stats), run_id),
        )

    LOGGER.info("kb ingestion finished", extra={"stats": stats})
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingest_sources()
