import json
import logging
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_QDRANT_COLLECTION = "tnchatbot_kb"
DEFAULT_EMBEDDING_URL = "http://localhost:8001/v1/embeddings"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

LOGGER = logging.getLogger(__name__)

INTENTS_TRIGGERING_RAG = {
    "audience",
    "offres",
    "formats",
    "immoneuf",
    "premium",
    "mag",
    "innovation",
}

KEYWORD_FALLBACKS = {
    "audience",
    "offre",
    "offres",
    "format",
    "formats",
    "immoneuf",
    "premium",
    "mag",
    "innovation",
}

FACTUAL_TOKENS = {
    "quel",
    "quelle",
    "quels",
    "quelles",
    "combien",
    "liste",
    "exemple",
    "exemples",
    "prix",
    "tarif",
    "formats",
}

DEFAULT_AUDIENCE_ADMIN_CONFIG = {
    "audience_admin": {
        "note": "Renseigner les chiffres audience côté admin.",
    }
}


def request_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")
    if not body:
        return {}
    return json.loads(body)


def embed_query(query: str) -> List[float]:
    embedding_url = os.getenv("EMBEDDING_URL", DEFAULT_EMBEDDING_URL)
    embedding_model = os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    payload = {
        "model": embedding_model,
        "input": [query],
    }
    try:
        response = request_json("POST", embedding_url, payload)
    except (HTTPError, URLError) as exc:
        raise RuntimeError("Embedding request failed") from exc
    data = response.get("data", [])
    if not data:
        raise RuntimeError("Embedding response empty")
    return data[0].get("embedding", [])


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    score: float
    payload: dict


def search_qdrant(vector: List[float], top_k: int) -> List[RetrievedChunk]:
    qdrant_url = os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL).rstrip("/")
    collection = os.getenv("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION)
    url = f"{qdrant_url}/collections/{collection}/points/search"
    payload = {
        "vector": vector,
        "limit": top_k,
        "with_payload": True,
    }
    response = request_json("POST", url, payload)
    result = response.get("result", [])
    chunks: List[RetrievedChunk] = []
    for item in result:
        payload = item.get("payload", {})
        chunks.append(
            RetrievedChunk(
                content=payload.get("content", ""),
                score=item.get("score", 0.0),
                payload=payload,
            )
        )
    return chunks


def build_rag_context(chunks: Iterable[RetrievedChunk]) -> str:
    lines: List[str] = []
    for index, chunk in enumerate(chunks, start=1):
        content = chunk.content.strip()
        if not content:
            continue
        lines.append(f"[{index}] {content}")
    return "\n\n".join(lines)


def should_trigger_rag(intent: Optional[str], user_message: str) -> bool:
    normalized_intent = (intent or "").strip().lower()
    if normalized_intent in INTENTS_TRIGGERING_RAG:
        return True
    lowered = user_message.lower()
    return any(keyword in lowered for keyword in KEYWORD_FALLBACKS)


def is_factual_question(user_message: str) -> bool:
    lowered = user_message.lower()
    if "?" in lowered:
        return True
    return any(token in lowered for token in FACTUAL_TOKENS)


def build_config(base_config: dict | None) -> dict:
    config = dict(base_config or {})
    if "audience_admin" not in config:
        env_config = os.getenv("AUDIENCE_ADMIN_CONFIG")
        if env_config:
            try:
                config["audience_admin"] = json.loads(env_config)
            except json.JSONDecodeError:
                LOGGER.warning("AUDIENCE_ADMIN_CONFIG is not valid JSON")
        else:
            config.update(DEFAULT_AUDIENCE_ADMIN_CONFIG)
    return config


def retrieve_rag_context(query: str, top_k: int = 4) -> str:
    vector = embed_query(query)
    chunks = search_qdrant(vector, top_k)
    return build_rag_context(chunks)
