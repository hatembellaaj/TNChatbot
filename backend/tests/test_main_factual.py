import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

from app.main import (
    _build_direct_factual_answer,
    _extract_pricing_sentence_from_context,
    _extract_total_socionautes_from_context,
    _extract_launch_year_from_context,
    _extract_visits_total_2024_from_context,
    _extract_article_reads_2024_from_context,
)


def test_extract_launch_year_from_context_reads_since_field():
    rag_context = '[3] {"knowledge_base":{"brand_overview":{"since":"2010-12"}}}'
    year = _extract_launch_year_from_context(
        "En quelle année Tunisie Numérique a-t-il été lancé ?",
        rag_context,
    )
    assert year == "2010"


def test_build_direct_factual_answer_returns_grounded_response():
    rag_context = 'Tunisie Numérique a été lancé en décembre 2010.'
    answer = _build_direct_factual_answer(
        "Quelle est la date de création de Tunisie Numérique ?",
        rag_context,
    )
    assert answer == "Tunisie Numérique a été lancé en 2010."


def test_extract_visits_total_2024_from_context_reads_json_value():
    rag_context = '[3] {"audience_2024":{"high_level":{"visits_total":46000000}}}'
    visits = _extract_visits_total_2024_from_context(
        "Combien de visites totales TN a-t-il enregistrées en 2024 ?",
        rag_context,
    )
    assert visits == 46000000


def test_build_direct_factual_answer_returns_visits_total_2024():
    rag_context = '[4] En 2024, Tunisie Numérique a enregistré 46 000 000 visites.'
    answer = _build_direct_factual_answer(
        "Combien de visites totales TN a-t-il enregistrées en 2024 ?",
        rag_context,
    )
    assert answer == "En 2024, Tunisie Numérique a enregistré 46 000 000 visites au total."


def test_extract_article_reads_2024_from_context_reads_json_value():
    rag_context = '[5] {"audience_2024":{"high_level":{"article_reads_total":62400000}}}'
    reads = _extract_article_reads_2024_from_context(
        "Combien de lectures d’articles en 2024 ?",
        rag_context,
    )
    assert reads == 62400000


def test_build_direct_factual_answer_returns_article_reads_2024():
    rag_context = '[5] Le site a généré 62 400 000 lectures d’articles en 2024.'
    answer = _build_direct_factual_answer(
        "Combien de lectures d’articles en 2024 ?",
        rag_context,
    )
    assert answer == "En 2024, Tunisie Numérique a généré 62 400 000 lectures d’articles."


def test_extract_total_socionautes_from_context_reads_sentence_value():
    rag_context = "Le kit média indique un total de +1 175 000 socionautes (septembre 2025)."
    total = _extract_total_socionautes_from_context(
        "Combien y a-t-il de socionautes au total ?",
        rag_context,
    )
    assert total == 1175000


def test_build_direct_factual_answer_returns_socionautes_total():
    rag_context = "Le kit média indique un total de +1 175 000 socionautes (septembre 2025)."
    answer = _build_direct_factual_answer(
        "Combien y a-t-il de socionautes au total ?",
        rag_context,
    )
    assert answer == "Le total de socionautes est de 1 175 000."


def test_extract_pricing_sentence_from_context_matches_photo_coverage():
    rag_context = """
    Un communiqué de presse coûte 600 DT HT.
    Photo coverage coûte 1000 DT HT.
    Video report branded tn coûte 3500 DT HT.
    """
    pricing_sentence = _extract_pricing_sentence_from_context(
        "combien coute une photo coverage pour un évènement",
        rag_context,
    )
    assert pricing_sentence == "Photo coverage coûte 1000 DT HT."


def test_build_direct_factual_answer_returns_pricing_sentence_when_present():
    rag_context = """
    Un communiqué de presse coûte 600 DT HT.
    Photo coverage coûte 1000 DT HT.
    """
    answer = _build_direct_factual_answer(
        "combien coute une photo coverage pour un évènement",
        rag_context,
    )
    assert answer == "Photo coverage coûte 1000 DT HT."


def test_build_direct_factual_answer_strips_chunk_source_prefix_for_pricing():
    rag_context = """
    [2] (source: tn_kit_media_2025_RAG_ULTRA_EXHAUSTIVE_LOCKED — admin/upload/tn_kit_media_2025_RAG_ULTRA_EXHAUSTIVE_LOCKED.json) Photo coverage coûte 1000 DT HT.
    """
    answer = _build_direct_factual_answer(
        "combien coute une photo coverage pour un évènement",
        rag_context,
    )
    assert answer == "Photo coverage coûte 1000 DT HT."
