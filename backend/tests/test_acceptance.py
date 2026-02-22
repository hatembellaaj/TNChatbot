import sys

from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

import app.orchestrator.state_machine as sm  # noqa: E402


def test_budget_wizard_flow_creates_lead(monkeypatch):
    created = {}

    def _fake_create_lead(slots):
        created.update(slots)

    monkeypatch.setattr(sm, "create_wizard_lead", _fake_create_lead)

    slots = {}
    response = sm.handle_step(
        sm.ConversationStep.BUDGET_CLIENT_TYPE,
        "",
        "CT_AGENCY",
        slots,
    )
    slots.update(response["slot_updates"])
    assert response["suggested_next_step"] == sm.ConversationStep.BUDGET_OBJECTIVE.value

    response = sm.handle_step(
        sm.ConversationStep.BUDGET_OBJECTIVE,
        "",
        "OBJ_AWARENESS",
        slots,
    )
    slots.update(response["slot_updates"])
    assert response["suggested_next_step"] == sm.ConversationStep.BUDGET_RANGE.value

    response = sm.handle_step(
        sm.ConversationStep.BUDGET_RANGE,
        "",
        "B_1000_3000",
        slots,
    )
    slots.update(response["slot_updates"])
    assert "mini-pack" in response["assistant_message"].lower()
    assert response["suggested_next_step"] == sm.ConversationStep.FORM_STANDARD_FIRST_NAME.value

    response = sm.handle_step(
        sm.ConversationStep.FORM_STANDARD_FIRST_NAME,
        "Amina",
        None,
        slots,
    )
    slots.update(response["slot_updates"])
    response = sm.handle_step(
        sm.ConversationStep.FORM_STANDARD_LAST_NAME,
        "Ben Ali",
        None,
        slots,
    )
    slots.update(response["slot_updates"])
    response = sm.handle_step(
        sm.ConversationStep.FORM_STANDARD_COMPANY,
        "TN Media",
        None,
        slots,
    )
    slots.update(response["slot_updates"])
    response = sm.handle_step(
        sm.ConversationStep.FORM_STANDARD_EMAIL,
        "contact@tn.media",
        None,
        slots,
    )
    slots.update(response["slot_updates"])
    response = sm.handle_step(
        sm.ConversationStep.FORM_STANDARD_PHONE,
        "+216 70 000 000",
        None,
        slots,
    )
    slots.update(response["slot_updates"])
    response = sm.handle_step(
        sm.ConversationStep.FORM_STANDARD_JOB_TITLE,
        "Directrice marketing",
        None,
        slots,
    )
    slots.update(response["slot_updates"])
    response = sm.handle_step(
        sm.ConversationStep.FORM_STANDARD_SECTOR,
        "Banque",
        None,
        slots,
    )
    slots.update(response["slot_updates"])
    response = sm.handle_step(
        sm.ConversationStep.FORM_STANDARD_MESSAGE,
        "Nous souhaitons une campagne rapide.",
        None,
        slots,
    )

    assert response["handoff"]["requested"] is True
    assert created["first_name"] == "Amina"
    assert created["budget_range"] == "1000–3000"


def test_question_during_wizard_returns_rag(monkeypatch):
    monkeypatch.setattr(sm, "_answer_rag_question", lambda _: "Réponse RAG")

    response = sm.handle_step(
        sm.ConversationStep.BUDGET_OBJECTIVE,
        "Quels sont vos produits ?",
        None,
        {},
    )

    assert response["safety"]["rag_used"] is True
    assert "Réponse RAG" in response["assistant_message"]
    assert "Pour continuer" in response["assistant_message"]
    assert response["suggested_next_step"] == sm.ConversationStep.BUDGET_OBJECTIVE.value


def test_reader_out_of_scope_message():
    assert sm.looks_like_reader_request("Je veux commenter un article") is True
    response = sm.build_static_response(
        source_step=sm.ConversationStep.MAIN_MENU,
        step=sm.ConversationStep.OUT_OF_SCOPE_READER,
        button_id=None,
        slots={},
    )
    assert "lecteurs" in response["assistant_message"].lower()
    assert response["buttons"]


def test_solutions_menu_and_cta_buttons():
    response = sm.build_static_response(
        source_step=sm.ConversationStep.MAIN_MENU,
        step=sm.ConversationStep.SOLUTIONS_MENU,
        button_id="M_SOLUTIONS",
        slots={},
    )
    button_ids = {button["id"] for button in response["buttons"]}
    assert "S_DISPLAY" in button_ids
    assert "NAV_MAIN_MENU" in button_ids

    response = sm.build_static_response(
        source_step=sm.ConversationStep.SOLUTIONS_MENU,
        step=sm.ConversationStep.SOLUTION_DISPLAY,
        button_id="S_DISPLAY",
        slots={},
    )
    button_ids = {button["id"] for button in response["buttons"]}
    assert "M_BUDGET_HELP" in button_ids
    assert "M_CALLBACK" in button_ids
    assert "NAV_MAIN_MENU" in button_ids


def test_specific_form_flows_prompt_extra_fields():
    response = sm.handle_step(
        sm.ConversationStep.FORM_IMMONEUF_PROJECT_CITIES,
        "Tunis, Sfax",
        None,
        {},
    )
    assert response["suggested_next_step"] == sm.ConversationStep.FORM_IMMONEUF_PROJECT_TYPES.value

    response = sm.handle_step(
        sm.ConversationStep.FORM_PREMIUM_ESTIMATED_USERS,
        "50",
        None,
        {},
    )
    assert response["suggested_next_step"] == sm.ConversationStep.FORM_STANDARD_FIRST_NAME.value

    response = sm.handle_step(
        sm.ConversationStep.FORM_PARTNERSHIP_PRIORITY,
        "display",
        None,
        {},
    )
    assert response["suggested_next_step"] == sm.ConversationStep.FORM_STANDARD_FIRST_NAME.value


def test_launch_year_question_uses_rag_since_without_llm(monkeypatch):
    rag_context = "\n".join([
        '[1] (source: tn_kit_media_2025) {"knowledge_base":{"brand_overview":{"since":"2010-12"}}}',
        '[2] Tunisie Numérique a été lancé en décembre 2010.',
    ])

    monkeypatch.setattr(sm, "retrieve_rag_context", lambda *_args, **_kwargs: rag_context)

    def _fail_call_llm(_messages):
        raise AssertionError("LLM should not be called when factual answer is extracted from RAG")

    monkeypatch.setattr(sm, "call_llm", _fail_call_llm)

    response = sm.handle_step(
        sm.ConversationStep.BUDGET_OBJECTIVE,
        "En quelle année Tunisie Numérique a-t-il été lancé ?",
        None,
        {},
    )

    assert "2010" in response["assistant_message"]
    assert response["safety"]["rag_used"] is True
