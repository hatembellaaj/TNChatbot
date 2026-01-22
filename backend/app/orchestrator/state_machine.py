from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import re
import unicodedata
from typing import Dict, Iterable, List, Optional

from app.leads import create_wizard_lead
from app.llm.client import LLMClientError, call_llm
from app.llm.prompts import build_messages
from app.llm.validator import normalize_llm_text
from app.rag.retrieve import is_factual_question, retrieve_rag_context


class ConversationStep(str, Enum):
    WELCOME = "WELCOME"
    MAIN_MENU = "MAIN_MENU"
    AUDIENCE = "AUDIENCE"
    SOLUTIONS_MENU = "SOLUTIONS_MENU"
    BUDGET_CLIENT_TYPE = "BUDGET_CLIENT_TYPE"
    FORM_IMMONEUF = "FORM_IMMONEUF"
    FORM_PREMIUM = "FORM_PREMIUM"
    FORM_PARTNERSHIP = "FORM_PARTNERSHIP"
    FORM_CALLBACK = "FORM_CALLBACK"
    SOLUTION_IMMONEUF = "SOLUTION_IMMONEUF"
    SOLUTION_PREMIUM = "SOLUTION_PREMIUM"
    SOLUTION_PARTNERSHIP = "SOLUTION_PARTNERSHIP"
    OUT_OF_SCOPE_READER = "OUT_OF_SCOPE_READER"
    QUAL_CLIENT_TYPE = "QUAL_CLIENT_TYPE"
    QUAL_OBJECTIVE = "QUAL_OBJECTIVE"
    QUAL_BUDGET = "QUAL_BUDGET"
    QUAL_LEAD_FIRST_NAME = "QUAL_LEAD_FIRST_NAME"
    QUAL_LEAD_LAST_NAME = "QUAL_LEAD_LAST_NAME"
    QUAL_LEAD_EMAIL = "QUAL_LEAD_EMAIL"
    QUAL_LEAD_PHONE = "QUAL_LEAD_PHONE"
    QUAL_LEAD_COMPANY = "QUAL_LEAD_COMPANY"
    QUAL_DONE = "QUAL_DONE"


class GlobalIntent(str, Enum):
    READER = "reader"
    CALLBACK = "callback"


@dataclass(frozen=True)
class ButtonSpec:
    id: str
    label: str
    next_step: ConversationStep


HANDOFF_CONTACT_URL = "https://tangram-noe.com/contact"
LOGGER = logging.getLogger(__name__)


WELCOME_BUTTONS = (
    ButtonSpec(
        id="M_START",
        label="✅ Commencer",
        next_step=ConversationStep.MAIN_MENU,
    ),
)

MAIN_MENU_BUTTONS = (
    ButtonSpec(
        id="M_AUDIENCE",
        label="📊 Découvrir notre audience",
        next_step=ConversationStep.AUDIENCE,
    ),
    ButtonSpec(
        id="M_SOLUTIONS",
        label="🧩 Découvrir nos solutions",
        next_step=ConversationStep.SOLUTIONS_MENU,
    ),
    ButtonSpec(
        id="M_BUDGET",
        label="💶 Parler budget",
        next_step=ConversationStep.QUAL_CLIENT_TYPE,
    ),
    ButtonSpec(
        id="M_IMMONEUF",
        label="🏗️ Projet immobilier neuf",
        next_step=ConversationStep.FORM_IMMONEUF,
    ),
    ButtonSpec(
        id="M_PREMIUM",
        label="✨ Offre premium",
        next_step=ConversationStep.FORM_PREMIUM,
    ),
    ButtonSpec(
        id="M_PARTNERSHIP",
        label="🤝 Devenir partenaire",
        next_step=ConversationStep.FORM_PARTNERSHIP,
    ),
    ButtonSpec(
        id="M_CALLBACK",
        label="📞 Être rappelé",
        next_step=ConversationStep.FORM_CALLBACK,
    ),
)

SOLUTIONS_MENU_BUTTONS = (
    ButtonSpec(
        id="S_IMMONEUF",
        label="🏗️ Immobilier neuf",
        next_step=ConversationStep.SOLUTION_IMMONEUF,
    ),
    ButtonSpec(
        id="S_PREMIUM",
        label="✨ Offre premium",
        next_step=ConversationStep.SOLUTION_PREMIUM,
    ),
    ButtonSpec(
        id="S_PARTNERSHIP",
        label="🤝 Partenariats",
        next_step=ConversationStep.SOLUTION_PARTNERSHIP,
    ),
)

QUAL_CLIENT_TYPE_BUTTONS = (
    ButtonSpec(
        id="CT_AGENCE",
        label="Agence",
        next_step=ConversationStep.QUAL_OBJECTIVE,
    ),
    ButtonSpec(
        id="CT_MARQUE",
        label="Marque",
        next_step=ConversationStep.QUAL_OBJECTIVE,
    ),
    ButtonSpec(
        id="CT_BANQUE",
        label="Banque",
        next_step=ConversationStep.QUAL_OBJECTIVE,
    ),
    ButtonSpec(
        id="CT_PROMOTEUR",
        label="Promoteur",
        next_step=ConversationStep.QUAL_OBJECTIVE,
    ),
    ButtonSpec(
        id="CT_ONG",
        label="ONG",
        next_step=ConversationStep.QUAL_OBJECTIVE,
    ),
)

QUAL_OBJECTIVE_BUTTONS = (
    ButtonSpec(
        id="OBJ_NOTORIETE",
        label="Notoriété",
        next_step=ConversationStep.QUAL_BUDGET,
    ),
    ButtonSpec(
        id="OBJ_LANCEMENT",
        label="Lancement produit",
        next_step=ConversationStep.QUAL_BUDGET,
    ),
    ButtonSpec(
        id="OBJ_LEADS",
        label="Leads",
        next_step=ConversationStep.QUAL_BUDGET,
    ),
    ButtonSpec(
        id="OBJ_CONVENTION",
        label="Convention",
        next_step=ConversationStep.QUAL_BUDGET,
    ),
)

NAV_BUTTONS = (
    ButtonSpec(
        id="NAV_MAIN_MENU",
        label="Menu principal",
        next_step=ConversationStep.MAIN_MENU,
    ),
    ButtonSpec(
        id="NAV_CALLBACK",
        label="Être rappelé",
        next_step=ConversationStep.FORM_CALLBACK,
    ),
)

BUTTONS_BY_STEP: Dict[ConversationStep, tuple[ButtonSpec, ...]] = {
    ConversationStep.WELCOME: WELCOME_BUTTONS,
    ConversationStep.MAIN_MENU: MAIN_MENU_BUTTONS,
    ConversationStep.SOLUTIONS_MENU: SOLUTIONS_MENU_BUTTONS,
    ConversationStep.QUAL_CLIENT_TYPE: QUAL_CLIENT_TYPE_BUTTONS,
    ConversationStep.QUAL_OBJECTIVE: QUAL_OBJECTIVE_BUTTONS,
}

TRANSITIONS: Dict[ConversationStep, Dict[str, ConversationStep]] = {
    step: {button.id: button.next_step for button in buttons}
    for step, buttons in BUTTONS_BY_STEP.items()
}

OUT_OF_SCOPE_MESSAGE = (
    "Je suis spécialisé sur l'offre Tangram Noir et ses solutions. "
    "Pour toute autre demande, notre équipe peut vous aider via notre formulaire de "
    "contact."
)

QUAL_PROMPTS: Dict[ConversationStep, str] = {
    ConversationStep.QUAL_CLIENT_TYPE: (
        "Pour commencer, quel type d'annonceur représentez-vous ?"
    ),
    ConversationStep.QUAL_OBJECTIVE: "Quel est votre objectif principal ?",
    ConversationStep.QUAL_BUDGET: "Quel budget souhaitez-vous allouer ?",
    ConversationStep.QUAL_LEAD_FIRST_NAME: "Quel est votre prénom ?",
    ConversationStep.QUAL_LEAD_LAST_NAME: "Quel est votre nom ?",
    ConversationStep.QUAL_LEAD_EMAIL: "Quel est votre email professionnel ?",
    ConversationStep.QUAL_LEAD_PHONE: "Quel est votre numéro de téléphone ?",
    ConversationStep.QUAL_LEAD_COMPANY: "Quelle est votre société ?",
    ConversationStep.QUAL_DONE: (
        "Merci, un membre de notre équipe commerciale va vous contacter rapidement."
    ),
}

WIZARD_STEPS = {
    ConversationStep.QUAL_CLIENT_TYPE,
    ConversationStep.QUAL_OBJECTIVE,
    ConversationStep.QUAL_BUDGET,
    ConversationStep.QUAL_LEAD_FIRST_NAME,
    ConversationStep.QUAL_LEAD_LAST_NAME,
    ConversationStep.QUAL_LEAD_EMAIL,
    ConversationStep.QUAL_LEAD_PHONE,
    ConversationStep.QUAL_LEAD_COMPANY,
    ConversationStep.QUAL_DONE,
}

WIZARD_SLOTS = {
    ConversationStep.QUAL_CLIENT_TYPE: "qual_client_type",
    ConversationStep.QUAL_OBJECTIVE: "qual_objective",
    ConversationStep.QUAL_BUDGET: "qual_budget",
    ConversationStep.QUAL_LEAD_FIRST_NAME: "lead_first_name",
    ConversationStep.QUAL_LEAD_LAST_NAME: "lead_last_name",
    ConversationStep.QUAL_LEAD_EMAIL: "lead_email",
    ConversationStep.QUAL_LEAD_PHONE: "lead_phone",
    ConversationStep.QUAL_LEAD_COMPANY: "lead_company",
}

WIZARD_NEXT_STEP = {
    ConversationStep.QUAL_CLIENT_TYPE: ConversationStep.QUAL_OBJECTIVE,
    ConversationStep.QUAL_OBJECTIVE: ConversationStep.QUAL_BUDGET,
    ConversationStep.QUAL_BUDGET: ConversationStep.QUAL_LEAD_FIRST_NAME,
    ConversationStep.QUAL_LEAD_FIRST_NAME: ConversationStep.QUAL_LEAD_LAST_NAME,
    ConversationStep.QUAL_LEAD_LAST_NAME: ConversationStep.QUAL_LEAD_EMAIL,
    ConversationStep.QUAL_LEAD_EMAIL: ConversationStep.QUAL_LEAD_PHONE,
    ConversationStep.QUAL_LEAD_PHONE: ConversationStep.QUAL_LEAD_COMPANY,
}

WIZARD_BUTTON_VALUES = {
    "CT_AGENCE": "Agence",
    "CT_MARQUE": "Marque",
    "CT_BANQUE": "Banque",
    "CT_PROMOTEUR": "Promoteur",
    "CT_ONG": "ONG",
    "OBJ_NOTORIETE": "Notoriété",
    "OBJ_LANCEMENT": "Lancement produit",
    "OBJ_LEADS": "Leads",
    "OBJ_CONVENTION": "Convention",
}

WIZARD_TEXT_MATCHERS = {
    ConversationStep.QUAL_CLIENT_TYPE: {
        "Agence": {"agence", "agences"},
        "Marque": {"marque", "brand"},
        "Banque": {"banque", "banques"},
        "Promoteur": {"promoteur", "promoteurs"},
        "ONG": {"ong", "association"},
    },
    ConversationStep.QUAL_OBJECTIVE: {
        "Notoriété": {"notoriete", "notoriété", "visibilite", "visibilité"},
        "Lancement produit": {"lancement", "produit", "lancement produit"},
        "Leads": {"lead", "leads", "prospects", "acquisition"},
        "Convention": {"convention", "event", "événement", "evenement"},
    },
}

QUESTION_KEYWORDS = {
    "produits",
    "solutions",
    "audience",
    "prix",
    "tarif",
    "formats",
    "newsletter",
    "vidéo",
    "video",
}


def apply_global_interruptions(intent: Optional[str]) -> Optional[ConversationStep]:
    if intent == GlobalIntent.READER.value:
        return ConversationStep.OUT_OF_SCOPE_READER
    if intent == GlobalIntent.CALLBACK.value:
        return ConversationStep.FORM_CALLBACK
    return None


def get_buttons_for_step(step: ConversationStep) -> List[ButtonSpec]:
    return list(BUTTONS_BY_STEP.get(step, ()))


def get_transition(step: ConversationStep, button_id: Optional[str]) -> ConversationStep:
    if not button_id:
        return step
    return TRANSITIONS.get(step, {}).get(button_id, step)


def resolve_next_step(
    step: ConversationStep,
    button_id: Optional[str] = None,
    intent: Optional[str] = None,
) -> ConversationStep:
    interrupted = apply_global_interruptions(intent)
    if interrupted is not None:
        return interrupted
    return get_transition(step, button_id)


def serialize_buttons(buttons: Iterable[ButtonSpec]) -> List[Dict[str, str]]:
    return [{"id": button.id, "label": button.label} for button in buttons]


def get_out_of_scope_payload() -> Dict[str, str]:
    return {
        "assistant_message": OUT_OF_SCOPE_MESSAGE,
        "handoff_url": HANDOFF_CONTACT_URL,
    }


def is_wizard_step(step: ConversationStep) -> bool:
    return step in WIZARD_STEPS


def build_response(
    step: ConversationStep,
    assistant_message: str,
    buttons: Iterable[ButtonSpec],
    suggested_next_step: ConversationStep,
    slot_updates: Dict[str, str],
    handoff: Dict[str, object] | None = None,
    safety: Dict[str, object] | None = None,
) -> Dict[str, object]:
    return {
        "assistant_message": assistant_message,
        "buttons": serialize_buttons(buttons),
        "suggested_next_step": suggested_next_step.value,
        "slot_updates": slot_updates,
        "handoff": handoff or {"requested": False},
        "safety": safety or {"rag_used": False},
    }


def normalize_step(step: str) -> ConversationStep | None:
    try:
        return ConversationStep(step)
    except ValueError:
        return None


def normalize_text(text: str) -> str:
    lowered = text.strip().lower()
    if not lowered:
        return ""
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join([char for char in normalized if not unicodedata.combining(char)])


def looks_like_info_question(user_message: str) -> bool:
    normalized = normalize_text(user_message)
    if not normalized:
        return False
    if "?" in user_message:
        return True
    if normalized.startswith(("quoi", "quel", "quels", "quelle", "quelles", "comment", "combien")):
        return True
    return any(keyword in normalized for keyword in QUESTION_KEYWORDS)


def match_button_id(step: ConversationStep, user_message: str) -> Optional[str]:
    normalized = normalize_text(user_message)
    if not normalized:
        return None
    for button in get_buttons_for_step(step):
        if normalize_text(button.label) == normalized:
            return button.id
    return None


def _match_text_value(step: ConversationStep, user_message: str) -> Optional[str]:
    if step not in WIZARD_TEXT_MATCHERS:
        return None
    normalized = normalize_text(user_message)
    if not normalized:
        return None
    for value, tokens in WIZARD_TEXT_MATCHERS[step].items():
        if normalize_text(value) == normalized:
            return value
        if any(token in normalized for token in tokens):
            return value
    return None


def _validate_email(value: str) -> bool:
    return bool(re.match(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", value.strip()))


def _validate_phone(value: str) -> bool:
    digits = re.sub(r"\\D", "", value)
    return len(digits) >= 6


def _build_validation_message(step: ConversationStep) -> str:
    prompt = QUAL_PROMPTS.get(step, "Pouvez-vous préciser ?")
    return f"Je n'ai pas bien compris. {prompt}"


def build_wizard_prompt(step: ConversationStep) -> str:
    return QUAL_PROMPTS.get(step, "Merci pour ces précisions.")


def _answer_rag_question(user_message: str) -> str:
    try:
        rag_context = retrieve_rag_context(user_message)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("wizard_rag_retrieval_failed", exc_info=exc)
        rag_context = ""

    messages = build_messages(
        step="RAG_WIZARD",
        allowed_buttons=[],
        form_schema={},
        config={},
        rag_context=rag_context,
        rag_empty_factual=bool(is_factual_question(user_message) and not rag_context),
        user_message=user_message,
    )
    try:
        raw_response = call_llm(messages)
        return normalize_llm_text(raw_response)
    except LLMClientError as exc:
        LOGGER.warning("wizard_rag_llm_failed", exc_info=exc)
        if rag_context:
            return "Voici les informations disponibles dans notre base."
        return "Je n'ai pas trouvé d'information disponible pour le moment."


def handle_step(
    step: ConversationStep,
    user_message: str,
    button_id: Optional[str],
    slots: Dict[str, str],
) -> Dict[str, object]:
    if step == ConversationStep.BUDGET_CLIENT_TYPE:
        step = ConversationStep.QUAL_CLIENT_TYPE

    if step == ConversationStep.QUAL_DONE:
        return build_response(
            step,
            QUAL_PROMPTS[ConversationStep.QUAL_DONE],
            [],
            ConversationStep.QUAL_DONE,
            {},
            handoff={"requested": True, "type": "LEAD_CREATED"},
            safety={"rag_used": False},
        )

    slot_key = WIZARD_SLOTS.get(step)
    if slot_key is None:
        return build_response(
            step,
            _build_validation_message(step),
            get_buttons_for_step(step),
            step,
            {},
            safety={"rag_used": False},
        )

    selected_button_id = button_id or match_button_id(step, user_message)
    if selected_button_id and selected_button_id in WIZARD_BUTTON_VALUES:
        slot_value = WIZARD_BUTTON_VALUES[selected_button_id]
        slot_updates = {slot_key: slot_value}
        next_step = WIZARD_NEXT_STEP.get(step, step)
        return build_response(
            step,
            build_wizard_prompt(next_step),
            get_buttons_for_step(next_step),
            next_step,
            slot_updates,
            safety={"rag_used": False},
        )

    if step in WIZARD_TEXT_MATCHERS:
        matched = _match_text_value(step, user_message)
        if matched:
            slot_updates = {slot_key: matched}
            next_step = WIZARD_NEXT_STEP.get(step, step)
            return build_response(
                step,
                build_wizard_prompt(next_step),
                get_buttons_for_step(next_step),
                next_step,
                slot_updates,
                safety={"rag_used": False},
            )

    if step == ConversationStep.QUAL_LEAD_EMAIL and not _validate_email(user_message):
        if looks_like_info_question(user_message):
            rag_answer = _answer_rag_question(user_message)
            assistant_message = f"{rag_answer}\n\n{build_wizard_prompt(step)}"
            return build_response(
                step,
                assistant_message,
                get_buttons_for_step(step),
                step,
                {},
                safety={"rag_used": True},
            )
        return build_response(
            step,
            "Pouvez-vous indiquer un email valide ?",
            get_buttons_for_step(step),
            step,
            {},
            safety={"rag_used": False},
        )

    if step == ConversationStep.QUAL_LEAD_PHONE and not _validate_phone(user_message):
        if looks_like_info_question(user_message):
            rag_answer = _answer_rag_question(user_message)
            assistant_message = f"{rag_answer}\n\n{build_wizard_prompt(step)}"
            return build_response(
                step,
                assistant_message,
                get_buttons_for_step(step),
                step,
                {},
                safety={"rag_used": True},
            )
        return build_response(
            step,
            "Pouvez-vous indiquer un numéro de téléphone valide ?",
            get_buttons_for_step(step),
            step,
            {},
            safety={"rag_used": False},
        )

    cleaned = user_message.strip()
    if not cleaned:
        return build_response(
            step,
            _build_validation_message(step),
            get_buttons_for_step(step),
            step,
            {},
            safety={"rag_used": False},
        )

    if looks_like_info_question(user_message):
        rag_answer = _answer_rag_question(user_message)
        assistant_message = f"{rag_answer}\n\n{build_wizard_prompt(step)}"
        return build_response(
            step,
            assistant_message,
            get_buttons_for_step(step),
            step,
            {},
            safety={"rag_used": True},
        )

    slot_updates = {slot_key: cleaned}
    next_step = WIZARD_NEXT_STEP.get(step, step)

    if step == ConversationStep.QUAL_LEAD_COMPANY:
        updated_slots = {**slots, **slot_updates}
        try:
            create_wizard_lead(updated_slots)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("wizard_lead_create_failed", exc_info=exc)
            return build_response(
                step,
                "Une erreur est survenue lors de l'enregistrement. Pouvez-vous réessayer ?",
                get_buttons_for_step(step),
                step,
                {},
                safety={"rag_used": False},
            )
        return build_response(
            step,
            QUAL_PROMPTS[ConversationStep.QUAL_DONE],
            [],
            ConversationStep.QUAL_DONE,
            slot_updates,
            handoff={"requested": True, "type": "LEAD_CREATED"},
            safety={"rag_used": False},
        )

    return build_response(
        step,
        build_wizard_prompt(next_step),
        get_buttons_for_step(next_step),
        next_step,
        slot_updates,
        safety={"rag_used": False},
    )
