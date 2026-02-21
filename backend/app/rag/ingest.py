import json
import logging
import os
import re
import time
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
DEFAULT_EMBEDDING_TIMEOUT_SECONDS = 30
DEFAULT_EMBEDDING_MAX_RETRIES = 2

LOGGER = logging.getLogger(__name__)


def get_connection() -> psycopg.Connection:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    return psycopg.connect(database_url)


def request_json(
    method: str,
    url: str,
    payload: dict | None = None,
    timeout_seconds: float = DEFAULT_EMBEDDING_TIMEOUT_SECONDS,
) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=timeout_seconds) as response:
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
    timeout_seconds = float(
        os.getenv("EMBEDDING_TIMEOUT_SECONDS", str(DEFAULT_EMBEDDING_TIMEOUT_SECONDS))
    )
    max_retries = int(os.getenv("EMBEDDING_MAX_RETRIES", str(DEFAULT_EMBEDDING_MAX_RETRIES)))
    payload = {
        "model": embedding_model,
        "input": texts,
    }
    response: dict | None = None
    last_error: Exception | None = None
    error_history: list[str] = []
    attempts = max_retries + 1
    input_characters = sum(len(text) for text in texts)
    LOGGER.info(
        "Starting embedding request: model=%s url=%s texts=%s chars=%s timeout=%.1fs max_retries=%s",
        embedding_model,
        embedding_url,
        len(texts),
        input_characters,
        timeout_seconds,
        max_retries,
    )
    for attempt in range(1, attempts + 1):
        request_started_at = time.perf_counter()
        LOGGER.info("Embedding attempt %s/%s started", attempt, attempts)
        try:
            response = request_json("POST", embedding_url, payload, timeout_seconds=timeout_seconds)
            elapsed = time.perf_counter() - request_started_at
            data_count = len(response.get("data", [])) if isinstance(response, dict) else 0
            LOGGER.info(
                "Embedding attempt %s/%s succeeded in %.2fs (items=%s)",
                attempt,
                attempts,
                elapsed,
                data_count,
            )
            break
        except HTTPError as exc:
            elapsed = time.perf_counter() - request_started_at
            retryable = exc.code == 429 or 500 <= exc.code < 600
            error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            error_history.append(
                f"attempt {attempt}/{attempts}: HTTP {exc.code} in {elapsed:.2f}s"
                + (f" body={error_body[:300]!r}" if error_body else "")
            )
            LOGGER.error(
                "Embedding attempt %s/%s failed with HTTP %s in %.2fs (retryable=%s): %s",
                attempt,
                attempts,
                exc.code,
                elapsed,
                retryable,
                error_body[:300] if error_body else exc,
            )
            if not retryable or attempt == attempts:
                detail = (
                    f"Embedding request failed ({exc.code})"
                    f" for model '{embedding_model}' via '{embedding_url}'"
                )
                if error_body:
                    detail = f"{detail}: {error_body}"
                if attempts > 1:
                    detail = f"{detail} after {attempt} attempt(s)"
                if error_history:
                    detail = f"{detail}. Attempts: {' | '.join(error_history)}"
                raise RuntimeError(detail) from exc
            last_error = exc
        except (URLError, TimeoutError) as exc:
            elapsed = time.perf_counter() - request_started_at
            error_history.append(f"attempt {attempt}/{attempts}: {type(exc).__name__} in {elapsed:.2f}s: {exc}")
            LOGGER.error(
                "Embedding attempt %s/%s failed with %s in %.2fs: %s",
                attempt,
                attempts,
                type(exc).__name__,
                elapsed,
                exc,
            )
            if attempt == attempts:
                detail = (
                    f"Embedding request failed for model '{embedding_model}' via '{embedding_url}': {exc}"
                )
                if attempts > 1:
                    detail = f"{detail} after {attempt} attempt(s)"
                if error_history:
                    detail = f"{detail}. Attempts: {' | '.join(error_history)}"
                raise RuntimeError(detail) from exc
            last_error = exc

        wait_seconds = min(0.5 * attempt, 2.0)
        LOGGER.warning(
            "Embedding request attempt %s/%s failed: %s; retrying in %.1fs",
            attempt,
            attempts,
            last_error,
            wait_seconds,
        )
        time.sleep(wait_seconds)

    if response is None:
        raise RuntimeError("Embedding request failed before receiving a response")

    data = response.get("data", [])
    embeddings: List[List[float]] = []
    for item in data:
        embeddings.append(item.get("embedding", []))
    if len(embeddings) != len(texts):
        raise RuntimeError("Embedding response size mismatch")
    LOGGER.info(
        "Embedding completed successfully: vectors=%s dimension=%s",
        len(embeddings),
        len(embeddings[0]) if embeddings else 0,
    )
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


def derive_intent_from_path(path: Path) -> str:
    stem = path.stem.strip().lower()
    stem = re.sub(r"[\s\-]+", "_", stem)
    return stem


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
            intent = derive_intent_from_path(path)

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
                            "intent": intent,
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
