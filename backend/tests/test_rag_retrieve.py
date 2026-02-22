import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

import app.rag.retrieve as retrieve  # noqa: E402


def test_retrieve_rag_selection_exposes_selected_chunks(monkeypatch):
    monkeypatch.setattr(
        retrieve,
        "retrieve_rag_context",
        lambda *_args, **_kwargs: "[1] chunk A\n\n[2] chunk B",
    )

    result = retrieve.retrieve_rag_selection("question")

    assert result.context == "[1] chunk A\n\n[2] chunk B"
    assert result.selected_chunks == [
        {"content": "[1] chunk A"},
        {"content": "[2] chunk B"},
    ]


def test_retrieve_rag_selection_handles_empty_context(monkeypatch):
    monkeypatch.setattr(retrieve, "retrieve_rag_context", lambda *_args, **_kwargs: "")

    result = retrieve.retrieve_rag_selection("question")

    assert result.context == ""
    assert result.selected_chunks == []


def test_retrieve_rag_context_keeps_semantic_results_when_intent_filter_is_empty(monkeypatch):
    monkeypatch.setattr(retrieve, "embed_query", lambda *_args, **_kwargs: [0.1, 0.2])

    calls = {"count": 0}

    def fake_search(_vector, _top_k, _score_threshold=None, intent=None):
        calls["count"] += 1
        if calls["count"] == 1:
            assert intent == "formats"
            return [
                retrieve.RetrievedChunk(
                    content="Box 300x250 : CPM 36 en global.",
                    score=0.89,
                    payload={
                        "content": "Box 300x250 : CPM 36 en global.",
                        "source_uri": "tn_kit_media_training_2025.json",
                        "title": "TN Kit Media 2025",
                    },
                    point_id="p1",
                )
            ]
        raise AssertionError("No fallback search expected when semantic result exists")

    monkeypatch.setattr(retrieve, "search_qdrant", fake_search)

    context = retrieve.retrieve_rag_context(
        "Quel est le CPM du format Box mobile global ?",
        top_k=6,
        intent="formats",
    )

    assert "CPM 36" in context


def test_rerank_chunks_lexical_prioritizes_price_match(monkeypatch):
    monkeypatch.setenv("RAG_LEXICAL_WEIGHT", "0.7")
    query = "Combien coûte un communiqué de presse prix de base"
    chunks = [
        retrieve.RetrievedChunk(
            content="Les contenus sponsorisés incluent les communiqués de presse.",
            score=0.95,
            payload={"source_uri": "CONTENT_ADS.txt", "title": "CONTENT_ADS"},
            point_id="generic",
        ),
        retrieve.RetrievedChunk(
            content="Communiqué de presse : prix de base 900 DT HT.",
            score=0.75,
            payload={"source_uri": "pricing.txt", "title": "Tarifs"},
            point_id="pricing",
        ),
    ]

    reranked = retrieve.rerank_chunks_lexical(query, chunks)

    assert reranked[0].point_id == "pricing"


def test_retrieve_rag_context_applies_rerank_before_selection(monkeypatch):
    monkeypatch.setattr(retrieve, "embed_query", lambda *_args, **_kwargs: [0.1, 0.2])
    monkeypatch.setenv("RAG_LEXICAL_WEIGHT", "0.7")

    def fake_search(_vector, top_k, _score_threshold=None, intent=None):
        assert top_k >= 6
        assert intent == "content"
        return [
            retrieve.RetrievedChunk(
                content="Les contenus sponsorisés incluent les communiqués de presse.",
                score=0.95,
                payload={
                    "content": "Les contenus sponsorisés incluent les communiqués de presse.",
                    "source_uri": "CONTENT_ADS.txt",
                    "title": "CONTENT_ADS",
                    "intent": "content",
                },
                point_id="generic",
            ),
            retrieve.RetrievedChunk(
                content="Communiqué de presse : prix de base 900 DT HT.",
                score=0.75,
                payload={
                    "content": "Communiqué de presse : prix de base 900 DT HT.",
                    "source_uri": "tn_kit_media_training_2025.json",
                    "title": "tn_kit_media_training_2025",
                    "intent": "content",
                },
                point_id="pricing",
            ),
        ]

    monkeypatch.setattr(retrieve, "search_qdrant", fake_search)

    context = retrieve.retrieve_rag_context(
        "Combien coûte un communiqué de presse (prix de base) ?",
        top_k=6,
        intent="content",
    )

    first_chunk = context.split("\n\n")[0]
    assert "prix de base" in first_chunk.lower()
