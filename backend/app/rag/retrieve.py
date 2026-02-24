import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg

DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_QDRANT_COLLECTION = "index_source"
DEFAULT_EMBEDDING_URL = "http://localhost:8001/v1/embeddings"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_RAG_TOP_K = 3
DEFAULT_RAG_SCORE_THRESHOLD = 0.45
DEFAULT_KB_SOURCES_DIR = "kb_sources"
DEFAULT_RAG_CHUNK_SIZE = 400
DEFAULT_RAG_CHUNK_OVERLAP = 80
DEFAULT_RAG_LEXICAL_RERANK_CANDIDATES = 12
DEFAULT_RAG_LEXICAL_WEIGHT = 0.35
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
DEFAULT_RAG_FALLBACK_TOP_K = 15
DEFAULT_RRF_K = 60
NOT_FOUND_PATTERNS = (
    "information not found",
    "i don't have information",
    "not available",
)

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

LEXICAL_STOPWORDS = {
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou", "en", "sur", "dans",
    "pour", "avec", "au", "aux", "est", "sont", "que", "qui", "quoi", "quel", "quelle", "quels", "quelles",
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


def get_connection() -> psycopg.Connection:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    return psycopg.connect(database_url)


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
        content = _compact_chunk_content(chunk.content)
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


def _compact_chunk_content(content: str, *, max_chars: int = 700, max_text_items: int = 12) -> str:
    """Réduit les fragments JSON volumineux pour garder les faits lisibles dans le prompt."""
    compact = content.strip()
    if not compact:
        return ""

    text_matches = re.findall(r'"text"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', compact)
    if text_matches:
        decoded_items: List[str] = []
        for item in text_matches:
            try:
                decoded = json.loads(f'"{item}"')
            except json.JSONDecodeError:
                decoded = item
            normalized = re.sub(r"\s+", " ", decoded).strip()
            if normalized:
                decoded_items.append(normalized)
        if decoded_items:
            return " | ".join(decoded_items[:max_text_items])[:max_chars].strip()

    compact = re.sub(r"\s+", " ", compact)
    return compact[:max_chars].strip()


def _focus_chunk_content_for_query(query: str, content: str, *, max_lines: int = 4) -> str:
    """Conserve en priorité les lignes pertinentes pour la requête (ex: tarifs demandés)."""
    compact = content.strip()
    if not compact:
        return ""

    candidates: List[str] = []
    text_matches = re.findall(r'"text"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', compact)
    if text_matches:
        for item in text_matches:
            try:
                decoded = json.loads(f'"{item}"')
            except json.JSONDecodeError:
                decoded = item
            normalized = re.sub(r"\s+", " ", decoded).strip()
            if normalized:
                candidates.append(normalized)

    if not candidates:
        return _compact_chunk_content(compact)

    query_tokens = {
        token
        for token in _tokenize_lexical(query)
        if len(token) > 2 and token not in {"combien", "coute", "prix", "tarif"}
    }

    scored: List[tuple[float, str]] = []
    for line in candidates:
        normalized_line = _tokenize_lexical(line)
        token_set = set(normalized_line)
        overlap = sum(1 for token in query_tokens if token in token_set)
        has_price = 1 if re.search(r"\b\d+[\d\s]*(dt|dinar|tnd|€|eur)\b", line.lower()) else 0
        startswith_focus = 1 if ("photo" in token_set and "coverage" in token_set) else 0
        score = startswith_focus * 10 + overlap * 3 + has_price
        if score > 0:
            scored.append((score, line))

    if not scored:
        return _compact_chunk_content(compact)

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [line for _, line in scored[:max_lines]]
    return " | ".join(selected)


def should_trigger_rag(intent: Optional[str], user_message: str) -> bool:
    return True


def _tokenize_lexical(text: str) -> List[str]:
    normalized = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    tokens = [token for token in normalized.split() if token and token not in LEXICAL_STOPWORDS]
    return tokens


def _lexical_overlap_score(query: str, content: str) -> float:
    query_tokens = _tokenize_lexical(query)
    if not query_tokens:
        return 0.0
    content_tokens = set(_tokenize_lexical(content))
    if not content_tokens:
        return 0.0
    overlap_count = sum(1 for token in query_tokens if token in content_tokens)
    return overlap_count / max(1, len(query_tokens))


def rerank_chunks_lexical(query: str, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    lexical_weight = float(os.getenv("RAG_LEXICAL_WEIGHT", str(DEFAULT_RAG_LEXICAL_WEIGHT)))
    lexical_weight = max(0.0, min(1.0, lexical_weight))
    semantic_weight = 1.0 - lexical_weight

    scored_chunks = []
    for chunk in chunks:
        lexical_score = _lexical_overlap_score(query, chunk.content)
        combined_score = semantic_weight * chunk.score + lexical_weight * lexical_score
        scored_chunks.append((combined_score, lexical_score, chunk))

    scored_chunks.sort(key=lambda item: (item[0], item[1], item[2].score), reverse=True)
    return [item[2] for item in scored_chunks]


def rewrite_query(query: str) -> str:
    lowered = query.lower()
    expansion_tokens: List[str] = []
    if "coûte" in lowered or "coute" in lowered:
        expansion_tokens.extend(["prix", "tarif"])
    if "communiqué" in lowered or "communique" in lowered:
        expansion_tokens.extend(["communiqué de presse", "CP", "diffusion presse"])
    if "live" in lowered:
        expansion_tokens.extend(["vidéo live", "couverture live", "Facebook", "YouTube"])
    rewritten = " ".join(dict.fromkeys([query.strip(), *expansion_tokens])).strip()
    return rewritten or query


def keyword_search_bm25(query: str, top_k: int, intent: str | None = None) -> List[RetrievedChunk]:
    query_terms = _tokenize_lexical(query)
    if not query_terms:
        return []
    where_sql = ""
    params: list[object] = []
    if intent:
        where_sql = "WHERE LOWER(COALESCE(d.source_uri, '')) LIKE %s"
        params.append(f"%{intent}%")
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT c.id, c.content, d.source_uri, d.title
            FROM kb_chunks c
            JOIN kb_documents d ON c.document_id = d.id
            {where_sql}
            ORDER BY c.created_at DESC
            LIMIT 3000
            """,
            params,
        ).fetchall()
    if not rows:
        return []
    docs_tokens: list[list[str]] = [_tokenize_lexical(row[1] or "") for row in rows]
    avgdl = sum(len(tokens) for tokens in docs_tokens) / max(1, len(docs_tokens))
    df: dict[str, int] = {}
    for tokens in docs_tokens:
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1

    k1 = 1.5
    b = 0.75
    scored: list[tuple[float, tuple]] = []
    for row, tokens in zip(rows, docs_tokens):
        term_freq: dict[str, int] = {}
        for token in tokens:
            term_freq[token] = term_freq.get(token, 0) + 1
        score = 0.0
        doc_len = max(1, len(tokens))
        for term in query_terms:
            freq = term_freq.get(term, 0)
            if freq == 0:
                continue
            n_qi = df.get(term, 0)
            idf = max(0.0, (len(rows) - n_qi + 0.5) / (n_qi + 0.5))
            denom = freq + k1 * (1 - b + b * doc_len / max(1.0, avgdl))
            score += (idf * (freq * (k1 + 1))) / max(1e-6, denom)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        RetrievedChunk(
            content=(row[1] or ""),
            score=float(score),
            payload={"source_uri": row[2], "title": row[3], "content": row[1]},
            point_id=str(row[0]),
        )
        for score, row in scored[:top_k]
    ]


def reciprocal_rank_fusion(
    vector_results: List[RetrievedChunk],
    keyword_results: List[RetrievedChunk],
    top_k: int,
) -> List[RetrievedChunk]:
    rrf_k = int(os.getenv("RAG_RRF_K", str(DEFAULT_RRF_K)))
    fused_scores: dict[str, float] = {}
    by_id: dict[str, RetrievedChunk] = {}
    for rank, chunk in enumerate(vector_results, start=1):
        chunk_id = str(chunk.point_id)
        by_id[chunk_id] = chunk
        fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    for rank, chunk in enumerate(keyword_results, start=1):
        chunk_id = str(chunk.point_id)
        by_id.setdefault(chunk_id, chunk)
        fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    ordered_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
    return [by_id[chunk_id] for chunk_id in ordered_ids[:top_k]]


def rerank_chunks_cross_encoder(query: str, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    if not chunks:
        return chunks
    cohere_api_key = os.getenv("COHERE_API_KEY")
    if not cohere_api_key:
        return rerank_chunks_lexical(query, chunks)
    endpoint = "https://api.cohere.com/v2/rerank"
    payload = {
        "model": os.getenv("COHERE_RERANK_MODEL", "rerank-v3.5"),
        "query": query,
        "documents": [chunk.content for chunk in chunks],
        "top_n": min(10, len(chunks)),
    }
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cohere_api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        LOGGER.warning("cohere_rerank_failed_fallback_to_lexical", exc_info=True)
        return rerank_chunks_lexical(query, chunks)
    results = body.get("results", [])
    if not results:
        return rerank_chunks_lexical(query, chunks)
    reranked = [chunks[item.get("index", 0)] for item in results if item.get("index") is not None]
    seen = {id(chunk) for chunk in reranked}
    reranked.extend([chunk for chunk in chunks if id(chunk) not in seen])
    return reranked


def response_indicates_not_found(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in NOT_FOUND_PATTERNS)


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
    payload_intent = normalize_intent(str(payload.get("intent") or ""))
    if payload_intent == intent:
        return True
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




def retrieve_debug(query: str, k: int = 10, intent: str | None = None) -> List[RetrievedChunk]:
    rewritten_query = rewrite_query(query)
    vector = embed_query(rewritten_query)
    normalized_intent = normalize_intent(intent)
    vector_results = search_qdrant(vector, k, None, normalized_intent)
    keyword_results = keyword_search_bm25(rewritten_query, k, normalized_intent)
    merged = reciprocal_rank_fusion(vector_results, keyword_results, k)
    return rerank_chunks_cross_encoder(rewritten_query, merged)[:k]
def retrieve_rag_context(
    query: str,
    top_k: int | None = None,
    intent: str | None = None,
) -> str:
    rewritten_query = rewrite_query(query)
    vector = embed_query(rewritten_query)
    resolved_top_k = top_k or int(os.getenv("RAG_TOP_K", DEFAULT_RAG_TOP_K))
    lexical_candidates = int(
        os.getenv("RAG_LEXICAL_RERANK_CANDIDATES", str(DEFAULT_RAG_LEXICAL_RERANK_CANDIDATES))
    )
    retrieval_limit = max(resolved_top_k, lexical_candidates)
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
    chunks = search_qdrant(vector, retrieval_limit, score_threshold, normalized_intent)
    keyword_chunks = keyword_search_bm25(rewritten_query, resolved_top_k, normalized_intent)
    chunks = reciprocal_rank_fusion(chunks, keyword_chunks, resolved_top_k)
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
                retrieval_limit,
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
            chunks = search_qdrant(vector, retrieval_limit, None, normalized_intent)
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
            chunks = search_qdrant(vector, retrieval_limit, score_threshold)
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
                chunks = search_qdrant(vector, retrieval_limit, None)
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
                filtered_chunks = load_intent_chunks(normalized_intent)[:resolved_top_k]
                LOGGER.warning(
                    "rag_intent_file_fallback_results count=%s intent=%s",
                    len(filtered_chunks),
                    normalized_intent,
                )
        if filtered_chunks:
            chunks = filtered_chunks
    reranked_chunks = rerank_chunks_cross_encoder(rewritten_query, chunks)
    LOGGER.warning(
        "rag_rerank_applied total=%s selected=%s",
        len(reranked_chunks),
        min(resolved_top_k, len(reranked_chunks)),
    )
    best_chunks = reranked_chunks[:resolved_top_k]
    if best_chunks:
        for chunk in best_chunks:
            chunk.content = _focus_chunk_content_for_query(rewritten_query, chunk.content)
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
