import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

from app.main import (
    _build_direct_factual_answer,
    _extract_launch_year_from_context,
    _extract_visits_total_2024_from_context,
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
