import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_QDRANT_COLLECTION = "tnchatbot_kb"
DEFAULT_EMBEDDING_URL = "http://localhost:8001/v1/embeddings"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_RAG_TOP_K = 6
DEFAULT_RAG_SCORE_THRESHOLD = 0.2
DEFAULT_KB_SOURCES_DIR = "kb_sources"
DEFAULT_RAG_CHUNK_SIZE = 400
DEFAULT_RAG_CHUNK_OVERLAP = 80

LOGGER = logging.getLogger(__name__)

INTENT_SCORE_THRESHOLD_FALLBACKS = {
    "audience": 0.0,
    "overview": 0.0,
    "solutions": 0.0,
}

INTENTS_TRIGGERING_RAG = {
    "audience",
    "offres",
    "formats",
    "display",
    "content",
    "video",
    "newsletter_audio",
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
    ("welcome_scope", {"bonjour", "bonsoir", "salut", "hello", "hey", "coucou"}),
    ("audience", {"audience", "lecteurs", "lectorat"}),
    ("solutions", {"offre", "offres", "produit", "produits", "solution", "solutions"}),
    ("display", {"display", "banniere", "bannières", "banner", "banners"}),
    ("content", {"contenu", "contenus", "sponsorisé", "sponsorise", "article"}),
    ("video", {"format video", "vidéo", "video"}),
    ("newsletter_audio", {"newsletter", "audio", "emailing"}),
    ("innovation", {"innovation", "innovant", "innovante", "operation speciale"}),
    ("mag", {"mag", "magazine"}),
    ("formats", {"format", "formats"}),
    ("immoneuf", {"immoneuf", "immobilier neuf", "neuf"}),
    ("premium", {"premium"}),
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
    point_id: str | int | None = None


@dataclass(frozen=True)
class RagSelection:
    context: str
    selected_chunks: List[dict]


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
        point_id = item.get("id")
        if score_threshold is not None and score < score_threshold:
            continue
        chunks.append(
            RetrievedChunk(
                content=payload.get("content", ""),
                score=score,
                payload=payload,
                point_id=point_id,
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
    return True


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


def normalize_source_name(source_name: str | None) -> str | None:
    if not source_name:
        return None
    stem = Path(source_name).stem.strip().lower()
    stem = re.sub(r"[\s\-]+", "_", stem)
    return stem or None


def source_matches_intent(payload: dict, intent: str) -> bool:
    source_name = normalize_source_name(payload.get("source_uri"))
    title_name = normalize_source_name(payload.get("title"))
    if source_name and (source_name == intent or source_name.startswith(f"{intent}_")):
        return True
    if title_name and (title_name == intent or intent in title_name):
        return True
    return False


def load_intent_chunks(intent: str) -> List[RetrievedChunk]:
    sources_dir = Path(os.getenv("KB_SOURCES_DIR", DEFAULT_KB_SOURCES_DIR)).resolve()
    if not sources_dir.exists():
        LOGGER.warning("rag_intent_sources_missing path=%s", sources_dir)
        return []
    max_tokens = int(os.getenv("RAG_CHUNK_SIZE", str(DEFAULT_RAG_CHUNK_SIZE)))
    overlap = int(os.getenv("RAG_CHUNK_OVERLAP", str(DEFAULT_RAG_CHUNK_OVERLAP)))
    for path in sorted(sources_dir.iterdir()):
        if path.is_dir() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        normalized_name = normalize_source_name(path.stem)
        if not normalized_name:
            continue
        if normalized_name != intent and not normalized_name.startswith(f"{intent}_"):
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        chunks = chunk_text(text, max_tokens, overlap)
        return [
            RetrievedChunk(
                content=chunk,
                score=1.0,
                payload={
                    "content": chunk,
                    "intent": intent,
                    "source_uri": str(path.relative_to(sources_dir)),
                    "title": path.stem,
                },
                point_id=f"file:{path.stem}:{index}",
            )
            for index, chunk in enumerate(chunks, start=1)
        ]
    return []


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
    collection = os.getenv("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION)
    score_threshold_env = os.getenv("RAG_SCORE_THRESHOLD")
    score_threshold = (
        float(score_threshold_env)
        if score_threshold_env is not None
        else DEFAULT_RAG_SCORE_THRESHOLD
    )
    normalized_intent = normalize_intent(intent)
    LOGGER.warning(
        "rag_query_received query=%s collection=%s top_k=%s score_threshold=%s",
        query,
        collection,
        resolved_top_k,
        score_threshold,
    )
    LOGGER.warning(
        "rag_search_start intent=%s top_k=%s score_threshold=%s",
        normalized_intent or "none",
        resolved_top_k,
        score_threshold,
    )
    chunks = search_qdrant(vector, resolved_top_k, score_threshold, normalized_intent)
    semantic_chunks = list(chunks)
    LOGGER.warning(
        "rag_search_results count=%s doc_ids=%s",
        len(chunks),
        [chunk.point_id for chunk in chunks],
    )
    if not chunks:
        fallback_threshold = INTENT_SCORE_THRESHOLD_FALLBACKS.get(normalized_intent or "")
        if fallback_threshold is not None and fallback_threshold != score_threshold:
            LOGGER.warning(
                "rag_search_threshold_fallback intent=%s score_threshold=%s",
                normalized_intent or "none",
                fallback_threshold,
            )
            chunks = search_qdrant(
                vector,
                resolved_top_k,
                fallback_threshold,
                normalized_intent,
            )
            LOGGER.warning(
                "rag_search_threshold_results count=%s doc_ids=%s",
                len(chunks),
                [chunk.point_id for chunk in chunks],
            )
        if not chunks:
            LOGGER.warning(
                "rag_search_empty_retry intent=%s score_threshold=None",
                normalized_intent or "none",
            )
            chunks = search_qdrant(vector, resolved_top_k, None, normalized_intent)
            LOGGER.warning(
                "rag_search_retry_results count=%s doc_ids=%s",
                len(chunks),
                [chunk.point_id for chunk in chunks],
            )
    if normalized_intent:
        filtered_chunks = [
            chunk
            for chunk in chunks
            if source_matches_intent(chunk.payload, normalized_intent)
        ]
        LOGGER.warning(
            "rag_search_results_filtered count=%s intent=%s",
            len(filtered_chunks),
            normalized_intent,
        )
        if not filtered_chunks and semantic_chunks:
            LOGGER.warning(
                "rag_intent_filter_empty_keep_semantic count=%s intent=%s",
                len(semantic_chunks),
                normalized_intent,
            )
            chunks = semantic_chunks
        elif not filtered_chunks:
            LOGGER.warning("rag_intent_empty_fallback intent=%s", normalized_intent)
            LOGGER.warning("rag_intent_source_fallback intent=%s", normalized_intent)
            chunks = search_qdrant(vector, resolved_top_k, score_threshold)
            LOGGER.warning(
                "rag_search_fallback_results count=%s doc_ids=%s",
                len(chunks),
                [chunk.point_id for chunk in chunks],
            )
            if not chunks:
                LOGGER.warning(
                    "rag_search_fallback_empty_retry intent=%s score_threshold=None",
                    normalized_intent,
                )
                chunks = search_qdrant(vector, resolved_top_k, None)
                LOGGER.warning(
                    "rag_search_fallback_retry_results count=%s doc_ids=%s",
                    len(chunks),
                    [chunk.point_id for chunk in chunks],
                )
            filtered_chunks = [
                chunk
                for chunk in chunks
                if source_matches_intent(chunk.payload, normalized_intent)
            ]
            LOGGER.warning(
                "rag_search_fallback_filtered count=%s intent=%s",
                len(filtered_chunks),
                normalized_intent,
            )
            if not filtered_chunks:
                LOGGER.warning("rag_intent_file_fallback intent=%s", normalized_intent)
                filtered_chunks = load_intent_chunks(normalized_intent)[:1]
                LOGGER.warning(
                    "rag_intent_file_fallback_results count=%s intent=%s",
                    len(filtered_chunks),
                    normalized_intent,
                )
        if filtered_chunks:
            chunks = filtered_chunks
    best_chunks = chunks[:2]
    if best_chunks:
        for index, chunk in enumerate(best_chunks, start=1):
            LOGGER.warning(
                "rag_chunk_selected index=%s score=%.4f source=%s",
                index,
                chunk.score,
                chunk.payload.get("source_uri", "unknown"),
            )
            LOGGER.warning("rag_context_sent_to_llm index=%s content=%s", index, chunk.content)
    else:
        LOGGER.warning("rag_no_chunk_selected")
    return build_rag_context(best_chunks)


def retrieve_rag_selection(
    query: str,
    top_k: int | None = None,
    intent: str | None = None,
) -> RagSelection:
    context = retrieve_rag_context(query, top_k=top_k, intent=intent)
    selected_chunks: List[dict] = []
    if context:
        for chunk in context.split("\n\n"):
            selected_chunks.append({"content": chunk})
    return RagSelection(context=context, selected_chunks=selected_chunks)
