import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

from app.llm.prompts import build_messages


def test_build_messages_extracts_launch_year_from_since_field():
    rag_context = '''
    [3] { "knowledge_base": { "brand_overview": { "since": "2010-12" } } }
    Tunisie Numérique a été lancé en décembre 2010.
    '''

    messages = build_messages(
        step="MAIN_MENU",
        allowed_buttons=["M_SOLUTIONS"],
        form_schema={},
        config={},
        rag_context=rag_context,
        rag_empty_factual=False,
        user_message="En quelle année Tunisie Numérique a-t-il été lancé ?",
    )

    developer_prompt = messages[1]["content"]
    assert "Année de lancement (champ since): 2010" in developer_prompt


def test_build_messages_sanitizes_noisy_rag_markers():
    rag_context = '🎬 { ! "since": "2010-12" ! 🎬 }'

    messages = build_messages(
        step="MAIN_MENU",
        allowed_buttons=[],
        form_schema={},
        config={},
        rag_context=rag_context,
        rag_empty_factual=False,
        user_message="Quelle est la date de création ?",
    )

    developer_prompt = messages[1]["content"]
    assert "🎬" not in developer_prompt
    assert "!" not in developer_prompt


def test_system_prompt_mentions_flexible_matching_for_rag_wording():
    messages = build_messages(
        step="MAIN_MENU",
        allowed_buttons=[],
        form_schema={},
        config={},
        rag_context="Photo coverage coûte 1000 DT HT.",
        rag_empty_factual=False,
        user_message="combien coute une photo coverage",
    )

    system_prompt = messages[0]["content"]
    assert "variations mineures de formulation" in system_prompt
    assert "formulation légèrement différente" in system_prompt


def test_build_messages_extracts_relevant_pricing_fact_for_user_question():
    rag_context = """
    Une publication vidéo sur Facebook coûte 600 DT HT.
    Photo coverage coûte 1000 DT HT.
    Video report branded tn coûte 3500 DT HT.
    """

    messages = build_messages(
        step="MAIN_MENU",
        allowed_buttons=[],
        form_schema={},
        config={},
        rag_context=rag_context,
        rag_empty_factual=False,
        user_message="combien coute une photo coverage",
    )

    developer_prompt = messages[1]["content"]
    assert "Tarif pertinent trouvé: Photo coverage coûte 1000 DT HT." in developer_prompt
