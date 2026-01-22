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
DEFAULT_RAG_TOP_K = 6
DEFAULT_RAG_SCORE_THRESHOLD = 0.2

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

INTENT_KEYWORDS = [
    ("welcome", {"bonjour", "bonsoir", "salut", "hello", "hey", "coucou"}),
    ("audience", {"audience", "lecteurs", "lectorat"}),
    ("solutions", {"offre", "offres", "produit", "produits", "solution", "solutions"}),
    ("formats", {"format", "formats", "video", "vidéo"}),
    ("immoneuf", {"immoneuf", "immobilier neuf", "neuf"}),
    ("premium", {"premium"}),
    ("mag", {"mag", "magazine"}),
    ("innovation", {"innovation", "innovant", "innovante"}),
]

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

DEFAULT_ADMIN_CONFIG = {
    "audience_metrics": {
        "note": "Renseigner les chiffres audience côté admin.",
    },
    "offers_copy": {},
    "email_config": {},
    "sectors": [],
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


def search_qdrant(
    vector: List[float],
    top_k: int,
    score_threshold: float | None = None,
    intent: str | None = None,
) -> List[RetrievedChunk]:
    qdrant_url = os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL).rstrip("/")
    collection = os.getenv("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION)
    url = f"{qdrant_url}/collections/{collection}/points/search"
    payload = {
        "vector": vector,
        "limit": top_k,
        "with_payload": True,
    }
    if score_threshold is not None:
        payload["score_threshold"] = score_threshold
    if intent:
        payload["filter"] = {
            "must": [
                {
                    "key": "intent",
                    "match": {"value": intent},
                }
            ]
        }
    response = request_json("POST", url, payload)
    result = response.get("result", [])
    chunks: List[RetrievedChunk] = []
    for item in result:
        payload = item.get("payload", {})
        score = item.get("score", 0.0)
        if score_threshold is not None and score < score_threshold:
            continue
        chunks.append(
            RetrievedChunk(
                content=payload.get("content", ""),
                score=score,
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
        title = chunk.payload.get("title")
        source_uri = chunk.payload.get("source_uri")
        source_label = ""
        if title and source_uri:
            source_label = f" (source: {title} — {source_uri})"
        elif title:
            source_label = f" (source: {title})"
        elif source_uri:
            source_label = f" (source: {source_uri})"
        lines.append(f"[{index}]{source_label} {content}")
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
    if "audience_metrics" not in config:
        env_config = os.getenv("AUDIENCE_METRICS_CONFIG")
        if env_config:
            try:
                config["audience_metrics"] = json.loads(env_config)
            except json.JSONDecodeError:
                LOGGER.warning("AUDIENCE_METRICS_CONFIG is not valid JSON")
        else:
            config["audience_metrics"] = DEFAULT_ADMIN_CONFIG["audience_metrics"]
    for key, default_value in DEFAULT_ADMIN_CONFIG.items():
        config.setdefault(key, default_value)
    return config


def normalize_intent(intent: str | None) -> str | None:
    if not intent:
        return None
    normalized = intent.strip().lower()
    return normalized or None


def classify_intent(user_message: str) -> str | None:
    lowered = user_message.lower()
    for intent, keywords in INTENT_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            LOGGER.info("intent_classifier_hit intent=%s", intent)
            return intent
    LOGGER.info("intent_classifier_miss")
    return None


def retrieve_rag_context(
    query: str,
    top_k: int | None = None,
    intent: str | None = None,
) -> str:
    vector = embed_query(query)
    resolved_top_k = top_k or int(os.getenv("RAG_TOP_K", DEFAULT_RAG_TOP_K))
    score_threshold_env = os.getenv("RAG_SCORE_THRESHOLD")
    score_threshold = (
        float(score_threshold_env)
        if score_threshold_env is not None
        else DEFAULT_RAG_SCORE_THRESHOLD
    )
    normalized_intent = normalize_intent(intent)
    LOGGER.info("rag_query_received query=%s", query)
    LOGGER.info(
        "rag_search_start intent=%s top_k=%s score_threshold=%s",
        normalized_intent or "none",
        resolved_top_k,
        score_threshold,
    )
    chunks = search_qdrant(vector, resolved_top_k, score_threshold, normalized_intent)
    LOGGER.info("rag_search_results count=%s", len(chunks))
    if not chunks and normalized_intent:
        LOGGER.info("rag_intent_empty_fallback intent=%s", normalized_intent)
        chunks = search_qdrant(vector, resolved_top_k, score_threshold)
        LOGGER.info("rag_search_fallback_results count=%s", len(chunks))
    best_chunk = chunks[:1]
    if best_chunk:
        LOGGER.info(
            "rag_best_chunk_selected score=%.4f source=%s",
            best_chunk[0].score,
            best_chunk[0].payload.get("source_uri", "unknown"),
        )
        LOGGER.info("rag_context_sent_to_llm content=%s", best_chunk[0].content)
    else:
        LOGGER.info("rag_no_chunk_selected")
    return build_rag_context(best_chunk)
