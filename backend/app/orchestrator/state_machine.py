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
    WELCOME_SCOPE = "WELCOME_SCOPE"
    MAIN_MENU = "MAIN_MENU"
    AUDIENCE = "AUDIENCE"
    SOLUTIONS_MENU = "SOLUTIONS_MENU"
    SOLUTION_DISPLAY = "SOLUTION_DISPLAY"
    SOLUTION_CONTENT = "SOLUTION_CONTENT"
    SOLUTION_VIDEO = "SOLUTION_VIDEO"
    SOLUTION_AUDIO_NEWSLETTER = "SOLUTION_AUDIO_NEWSLETTER"
    SOLUTION_INNOVATION = "SOLUTION_INNOVATION"
    SOLUTION_MAG = "SOLUTION_MAG"
    BUDGET_CLIENT_TYPE = "BUDGET_CLIENT_TYPE"
    BUDGET_OBJECTIVE = "BUDGET_OBJECTIVE"
    BUDGET_RANGE = "BUDGET_RANGE"
    FORM_STANDARD_FIRST_NAME = "FORM_STANDARD_FIRST_NAME"
    FORM_STANDARD_LAST_NAME = "FORM_STANDARD_LAST_NAME"
    FORM_STANDARD_COMPANY = "FORM_STANDARD_COMPANY"
    FORM_STANDARD_EMAIL = "FORM_STANDARD_EMAIL"
    FORM_STANDARD_PHONE = "FORM_STANDARD_PHONE"
    FORM_STANDARD_JOB_TITLE = "FORM_STANDARD_JOB_TITLE"
    FORM_STANDARD_SECTOR = "FORM_STANDARD_SECTOR"
    FORM_STANDARD_MESSAGE = "FORM_STANDARD_MESSAGE"
    FORM_STANDARD_DONE = "FORM_STANDARD_DONE"
    FORM_IMMONEUF_PROJECT_CITIES = "FORM_IMMONEUF_PROJECT_CITIES"
    FORM_IMMONEUF_PROJECT_TYPES = "FORM_IMMONEUF_PROJECT_TYPES"
    FORM_IMMONEUF_PROJECTS_COUNT = "FORM_IMMONEUF_PROJECTS_COUNT"
    FORM_IMMONEUF_MARKETING_PERIOD = "FORM_IMMONEUF_MARKETING_PERIOD"
    FORM_PREMIUM_ESTIMATED_USERS = "FORM_PREMIUM_ESTIMATED_USERS"
    FORM_PARTNERSHIP_PRIORITY = "FORM_PARTNERSHIP_PRIORITY"
    OUT_OF_SCOPE_READER = "OUT_OF_SCOPE_READER"


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

WELCOME_SCOPE_MESSAGE = (
    "Ce chatbot est réservé aux annonceurs, agences, entreprises et institutions. "
    "Si vous êtes lecteur et souhaitez parler d'un article ou d'un commentaire, "
    "merci d'utiliser le formulaire de contact général."
)

MAIN_MENU_MESSAGE = "Que souhaitez-vous faire ?"

AUDIENCE_MESSAGE = (
    "Tunisie Numérique rassemble une audience professionnelle (décideurs, cadres, "
    "lecteurs business/tech) adaptée aux campagnes de notoriété et de génération de leads."
)

SOLUTIONS_MENU_MESSAGE = "Quelle solution souhaitez-vous découvrir ?"

SOLUTION_PITCHES = {
    ConversationStep.SOLUTION_DISPLAY: (
        "Les formats display offrent une visibilité rapide et multi-formats pour vos campagnes "
        "de notoriété et de lancement."
    ),
    ConversationStep.SOLUTION_CONTENT: (
        "Les contenus sponsorisés (articles, dossiers partenaires) valorisent vos messages "
        "avec un format éditorial détaillé."
    ),
    ConversationStep.SOLUTION_VIDEO: (
        "La vidéo apporte un impact fort pour le branding et les lancements, avec des formats "
        "adaptés aux dispositifs médias complets."
    ),
    ConversationStep.SOLUTION_AUDIO_NEWSLETTER: (
        "Les solutions audio et newsletter ciblent une audience engagée et régulière pour vos "
        "opérations de fidélisation."
    ),
    ConversationStep.SOLUTION_INNOVATION: (
        "Les formats innovation permettent des opérations spéciales, dispositifs sur-mesure "
        "et contenus différenciants."
    ),
    ConversationStep.SOLUTION_MAG: (
        "Le magazine met en avant vos prises de parole via des dossiers dédiés et des formats "
        "longs à forte valeur éditoriale."
    ),
}

OUT_OF_SCOPE_MESSAGE = (
    "Les demandes des lecteurs concernant les articles, commentaires ou contenus éditoriaux "
    "ne sont pas prises en charge ici. Merci d'utiliser le formulaire de contact général."
)

FORM_MESSAGES = {
    ConversationStep.FORM_STANDARD_FIRST_NAME: "Merci de renseigner vos coordonnées professionnelles. Quel est votre prénom ?",
    ConversationStep.FORM_STANDARD_LAST_NAME: "Quel est votre nom ?",
    ConversationStep.FORM_STANDARD_COMPANY: "Quelle est votre société ?",
    ConversationStep.FORM_STANDARD_EMAIL: "Quel est votre email professionnel ?",
    ConversationStep.FORM_STANDARD_PHONE: "Quel est votre numéro de téléphone ?",
    ConversationStep.FORM_STANDARD_JOB_TITLE: "Quel est votre poste ? (optionnel, vous pouvez répondre 'passer')",
    ConversationStep.FORM_STANDARD_SECTOR: "Quel est votre secteur d'activité ?",
    ConversationStep.FORM_STANDARD_MESSAGE: (
        "Souhaitez-vous ajouter un message complémentaire ? (optionnel)\n\n"
        "Mention RGPD : vos données sont utilisées uniquement pour traiter votre demande."
    ),
    ConversationStep.FORM_STANDARD_DONE: (
        "Merci, votre demande a bien été transmise. Notre équipe reviendra vers vous rapidement."
    ),
    ConversationStep.FORM_IMMONEUF_PROJECT_CITIES: "Dans quelles villes se situent vos projets immobiliers neufs ?",
    ConversationStep.FORM_IMMONEUF_PROJECT_TYPES: "Quels types de projets proposez-vous (résidentiel, commercial, mixte, etc.) ?",
    ConversationStep.FORM_IMMONEUF_PROJECTS_COUNT: "Combien de projets immobiliers souhaitez-vous promouvoir ?",
    ConversationStep.FORM_IMMONEUF_MARKETING_PERIOD: "Quelle est la période marketing souhaitée ?",
    ConversationStep.FORM_PREMIUM_ESTIMATED_USERS: "Combien d'utilisateurs estimez-vous pour l'abonnement Premium entreprise ?",
    ConversationStep.FORM_PARTNERSHIP_PRIORITY: "Quelle priorité souhaitez-vous pour le partenariat (display, contenu, vidéo, innovation, etc.) ?",
}

BUDGET_PROMPTS = {
    ConversationStep.BUDGET_CLIENT_TYPE: "Quel type d'annonceur représentez-vous ?",
    ConversationStep.BUDGET_OBJECTIVE: "Quel est votre objectif principal ?",
    ConversationStep.BUDGET_RANGE: "Quel budget souhaitez-vous allouer ?",
}

BUDGET_RECOMMENDATIONS = {
    "B_LT_1000": "article/communiqué + petit display",
    "B_1000_3000": "mini-pack : bannières + article + relais RS",
    "B_3000_10000": "pack complet : display multi-format + contenu + audio/newsletter possible",
    "B_GT_10000": "plan média / partenariat + innovation/vidéo possible",
    "B_UNKNOWN": "accompagnement personnalisé",
}

NAV_MAIN_MENU_BUTTON = ButtonSpec(
    id="NAV_MAIN_MENU",
    label="Menu principal",
    next_step=ConversationStep.MAIN_MENU,
)

OPEN_CONTACT_READER_BUTTON = ButtonSpec(
    id="OPEN_CONTACT_FORM_READER",
    label="Formulaire de contact",
    next_step=ConversationStep.OUT_OF_SCOPE_READER,
)

MAIN_MENU_BUTTONS = (
    ButtonSpec(
        id="M_AUDIENCE",
        label="📊 Découvrir notre audience",
        next_step=ConversationStep.AUDIENCE,
    ),
    ButtonSpec(
        id="M_SOLUTIONS",
        label="🧩 Voir nos solutions pub…",
        next_step=ConversationStep.SOLUTIONS_MENU,
    ),
    ButtonSpec(
        id="M_BUDGET_HELP",
        label="💰 M’aider à choisir…",
        next_step=ConversationStep.BUDGET_CLIENT_TYPE,
    ),
    ButtonSpec(
        id="M_IMMONEUF",
        label="🏢 Immobilier neuf / Pack Immoneuf",
        next_step=ConversationStep.FORM_IMMONEUF_PROJECT_CITIES,
    ),
    ButtonSpec(
        id="M_PREMIUM",
        label="📰 Abonnement Premium entreprise",
        next_step=ConversationStep.FORM_PREMIUM_ESTIMATED_USERS,
    ),
    ButtonSpec(
        id="M_PARTNERSHIP",
        label="🤝 Parler d’un partenariat annuel",
        next_step=ConversationStep.FORM_PARTNERSHIP_PRIORITY,
    ),
    ButtonSpec(
        id="M_CALLBACK",
        label="📞 Être rappelé",
        next_step=ConversationStep.FORM_STANDARD_FIRST_NAME,
    ),
)

SOLUTIONS_MENU_BUTTONS = (
    ButtonSpec(
        id="S_DISPLAY",
        label="Display",
        next_step=ConversationStep.SOLUTION_DISPLAY,
    ),
    ButtonSpec(
        id="S_CONTENT",
        label="Contenus sponsorisés",
        next_step=ConversationStep.SOLUTION_CONTENT,
    ),
    ButtonSpec(
        id="S_VIDEO",
        label="Vidéo",
        next_step=ConversationStep.SOLUTION_VIDEO,
    ),
    ButtonSpec(
        id="S_AUDIO_NEWSLETTER",
        label="Audio / Newsletter",
        next_step=ConversationStep.SOLUTION_AUDIO_NEWSLETTER,
    ),
    ButtonSpec(
        id="S_INNOVATION",
        label="Innovation",
        next_step=ConversationStep.SOLUTION_INNOVATION,
    ),
    ButtonSpec(
        id="S_MAG",
        label="Magazine",
        next_step=ConversationStep.SOLUTION_MAG,
    ),
)

SOLUTION_CTA_BUTTONS = (
    ButtonSpec(
        id="M_BUDGET_HELP",
        label="💰 M’aider à choisir…",
        next_step=ConversationStep.BUDGET_CLIENT_TYPE,
    ),
    ButtonSpec(
        id="M_CALLBACK",
        label="📞 Être rappelé",
        next_step=ConversationStep.FORM_STANDARD_FIRST_NAME,
    ),
)

BUDGET_CLIENT_TYPE_BUTTONS = (
    ButtonSpec(
        id="CT_AGENCY",
        label="Agence média / communication",
        next_step=ConversationStep.BUDGET_OBJECTIVE,
    ),
    ButtonSpec(
        id="CT_BRAND",
        label="Entreprise / marque",
        next_step=ConversationStep.BUDGET_OBJECTIVE,
    ),
    ButtonSpec(
        id="CT_FINANCE",
        label="Banque / assurance / institution financière",
        next_step=ConversationStep.BUDGET_OBJECTIVE,
    ),
    ButtonSpec(
        id="CT_INSTITUTION",
        label="Institution / ONG / organisation",
        next_step=ConversationStep.BUDGET_OBJECTIVE,
    ),
    ButtonSpec(
        id="CT_REALESTATE",
        label="Promoteur immobilier",
        next_step=ConversationStep.BUDGET_OBJECTIVE,
    ),
    ButtonSpec(
        id="CT_OTHER",
        label="Autre",
        next_step=ConversationStep.BUDGET_OBJECTIVE,
    ),
)

BUDGET_OBJECTIVE_BUTTONS = (
    ButtonSpec(
        id="OBJ_AWARENESS",
        label="Notoriété / image",
        next_step=ConversationStep.BUDGET_RANGE,
    ),
    ButtonSpec(
        id="OBJ_LAUNCH",
        label="Lancement produit / service",
        next_step=ConversationStep.BUDGET_RANGE,
    ),
    ButtonSpec(
        id="OBJ_LEADS",
        label="Générer des leads",
        next_step=ConversationStep.BUDGET_RANGE,
    ),
    ButtonSpec(
        id="OBJ_REALESTATE",
        label="Campagne immobilière",
        next_step=ConversationStep.BUDGET_RANGE,
    ),
    ButtonSpec(
        id="OBJ_PREMIUM",
        label="Abonnement Premium entreprise",
        next_step=ConversationStep.BUDGET_RANGE,
    ),
    ButtonSpec(
        id="OBJ_PARTNERSHIP",
        label="Partenariat annuel / convention",
        next_step=ConversationStep.BUDGET_RANGE,
    ),
)

BUDGET_RANGE_BUTTONS = (
    ButtonSpec(
        id="B_LT_1000",
        label="< 1000 TND",
        next_step=ConversationStep.FORM_STANDARD_FIRST_NAME,
    ),
    ButtonSpec(
        id="B_1000_3000",
        label="1000–3000",
        next_step=ConversationStep.FORM_STANDARD_FIRST_NAME,
    ),
    ButtonSpec(
        id="B_3000_10000",
        label="3000–10000",
        next_step=ConversationStep.FORM_STANDARD_FIRST_NAME,
    ),
    ButtonSpec(
        id="B_GT_10000",
        label="> 10000",
        next_step=ConversationStep.FORM_STANDARD_FIRST_NAME,
    ),
    ButtonSpec(
        id="B_UNKNOWN",
        label="Je ne sais pas encore",
        next_step=ConversationStep.FORM_STANDARD_FIRST_NAME,
    ),
)

FORM_SECTOR_BUTTONS = (
    ButtonSpec(
        id="SECTOR_BANK",
        label="Banque",
        next_step=ConversationStep.FORM_STANDARD_MESSAGE,
    ),
    ButtonSpec(
        id="SECTOR_TELCO",
        label="Télécom",
        next_step=ConversationStep.FORM_STANDARD_MESSAGE,
    ),
    ButtonSpec(
        id="SECTOR_REAL_ESTATE",
        label="Immobilier",
        next_step=ConversationStep.FORM_STANDARD_MESSAGE,
    ),
    ButtonSpec(
        id="SECTOR_RETAIL",
        label="Retail",
        next_step=ConversationStep.FORM_STANDARD_MESSAGE,
    ),
    ButtonSpec(
        id="SECTOR_INDUSTRY",
        label="Industrie",
        next_step=ConversationStep.FORM_STANDARD_MESSAGE,
    ),
    ButtonSpec(
        id="SECTOR_SERVICES",
        label="Services",
        next_step=ConversationStep.FORM_STANDARD_MESSAGE,
    ),
    ButtonSpec(
        id="SECTOR_INSTITUTION",
        label="Institution",
        next_step=ConversationStep.FORM_STANDARD_MESSAGE,
    ),
    ButtonSpec(
        id="SECTOR_OTHER",
        label="Autre",
        next_step=ConversationStep.FORM_STANDARD_MESSAGE,
    ),
)

BUTTONS_BY_STEP: Dict[ConversationStep, tuple[ButtonSpec, ...]] = {
    ConversationStep.MAIN_MENU: MAIN_MENU_BUTTONS,
    ConversationStep.SOLUTIONS_MENU: SOLUTIONS_MENU_BUTTONS,
    ConversationStep.SOLUTION_DISPLAY: SOLUTION_CTA_BUTTONS,
    ConversationStep.SOLUTION_CONTENT: SOLUTION_CTA_BUTTONS,
    ConversationStep.SOLUTION_VIDEO: SOLUTION_CTA_BUTTONS,
    ConversationStep.SOLUTION_AUDIO_NEWSLETTER: SOLUTION_CTA_BUTTONS,
    ConversationStep.SOLUTION_INNOVATION: SOLUTION_CTA_BUTTONS,
    ConversationStep.SOLUTION_MAG: SOLUTION_CTA_BUTTONS,
    ConversationStep.BUDGET_CLIENT_TYPE: BUDGET_CLIENT_TYPE_BUTTONS,
    ConversationStep.BUDGET_OBJECTIVE: BUDGET_OBJECTIVE_BUTTONS,
    ConversationStep.BUDGET_RANGE: BUDGET_RANGE_BUTTONS,
    ConversationStep.FORM_STANDARD_SECTOR: FORM_SECTOR_BUTTONS,
    ConversationStep.OUT_OF_SCOPE_READER: (OPEN_CONTACT_READER_BUTTON,),
}

TRANSITIONS: Dict[ConversationStep, Dict[str, ConversationStep]] = {
    step: {button.id: button.next_step for button in buttons}
    for step, buttons in BUTTONS_BY_STEP.items()
}

FORM_OPTIONAL_TOKENS = {
    "passer",
    "aucun",
    "aucune",
    "non",
    "n/a",
    "na",
}

READER_KEYWORDS = {
    "article",
    "commentaire",
    "commentaires",
    "redaction",
    "rédaction",
    "avis lecteur",
    "avis lecteurs",
    "lecteur",
    "lecteurs",
    "contenu éditorial",
    "contenu editorial",
}

QUESTION_KEYWORDS = {
    "produits",
    "solutions",
    "audience",
    "prix",
    "tarif",
    "formats",
    "newsletter",
    "video",
    "vidéo",
    "offre",
    "offres",
}

WIZARD_STEPS = {
    ConversationStep.BUDGET_CLIENT_TYPE,
    ConversationStep.BUDGET_OBJECTIVE,
    ConversationStep.BUDGET_RANGE,
    ConversationStep.FORM_STANDARD_FIRST_NAME,
    ConversationStep.FORM_STANDARD_LAST_NAME,
    ConversationStep.FORM_STANDARD_COMPANY,
    ConversationStep.FORM_STANDARD_EMAIL,
    ConversationStep.FORM_STANDARD_PHONE,
    ConversationStep.FORM_STANDARD_JOB_TITLE,
    ConversationStep.FORM_STANDARD_SECTOR,
    ConversationStep.FORM_STANDARD_MESSAGE,
    ConversationStep.FORM_STANDARD_DONE,
    ConversationStep.FORM_IMMONEUF_PROJECT_CITIES,
    ConversationStep.FORM_IMMONEUF_PROJECT_TYPES,
    ConversationStep.FORM_IMMONEUF_PROJECTS_COUNT,
    ConversationStep.FORM_IMMONEUF_MARKETING_PERIOD,
    ConversationStep.FORM_PREMIUM_ESTIMATED_USERS,
    ConversationStep.FORM_PARTNERSHIP_PRIORITY,
}

WIZARD_SLOTS = {
    ConversationStep.BUDGET_CLIENT_TYPE: "client_type",
    ConversationStep.BUDGET_OBJECTIVE: "objective",
    ConversationStep.BUDGET_RANGE: "budget_range",
    ConversationStep.FORM_STANDARD_FIRST_NAME: "first_name",
    ConversationStep.FORM_STANDARD_LAST_NAME: "last_name",
    ConversationStep.FORM_STANDARD_COMPANY: "company",
    ConversationStep.FORM_STANDARD_EMAIL: "email",
    ConversationStep.FORM_STANDARD_PHONE: "phone",
    ConversationStep.FORM_STANDARD_JOB_TITLE: "job_title",
    ConversationStep.FORM_STANDARD_SECTOR: "sector",
    ConversationStep.FORM_STANDARD_MESSAGE: "message",
    ConversationStep.FORM_IMMONEUF_PROJECT_CITIES: "project_cities",
    ConversationStep.FORM_IMMONEUF_PROJECT_TYPES: "project_types",
    ConversationStep.FORM_IMMONEUF_PROJECTS_COUNT: "projects_count",
    ConversationStep.FORM_IMMONEUF_MARKETING_PERIOD: "marketing_period",
    ConversationStep.FORM_PREMIUM_ESTIMATED_USERS: "estimated_users",
    ConversationStep.FORM_PARTNERSHIP_PRIORITY: "partnership_priority",
}

WIZARD_NEXT_STEP = {
    ConversationStep.BUDGET_CLIENT_TYPE: ConversationStep.BUDGET_OBJECTIVE,
    ConversationStep.BUDGET_OBJECTIVE: ConversationStep.BUDGET_RANGE,
    ConversationStep.BUDGET_RANGE: ConversationStep.FORM_STANDARD_FIRST_NAME,
    ConversationStep.FORM_IMMONEUF_PROJECT_CITIES: ConversationStep.FORM_IMMONEUF_PROJECT_TYPES,
    ConversationStep.FORM_IMMONEUF_PROJECT_TYPES: ConversationStep.FORM_IMMONEUF_PROJECTS_COUNT,
    ConversationStep.FORM_IMMONEUF_PROJECTS_COUNT: ConversationStep.FORM_IMMONEUF_MARKETING_PERIOD,
    ConversationStep.FORM_IMMONEUF_MARKETING_PERIOD: ConversationStep.FORM_STANDARD_FIRST_NAME,
    ConversationStep.FORM_PREMIUM_ESTIMATED_USERS: ConversationStep.FORM_STANDARD_FIRST_NAME,
    ConversationStep.FORM_PARTNERSHIP_PRIORITY: ConversationStep.FORM_STANDARD_FIRST_NAME,
    ConversationStep.FORM_STANDARD_FIRST_NAME: ConversationStep.FORM_STANDARD_LAST_NAME,
    ConversationStep.FORM_STANDARD_LAST_NAME: ConversationStep.FORM_STANDARD_COMPANY,
    ConversationStep.FORM_STANDARD_COMPANY: ConversationStep.FORM_STANDARD_EMAIL,
    ConversationStep.FORM_STANDARD_EMAIL: ConversationStep.FORM_STANDARD_PHONE,
    ConversationStep.FORM_STANDARD_PHONE: ConversationStep.FORM_STANDARD_JOB_TITLE,
    ConversationStep.FORM_STANDARD_JOB_TITLE: ConversationStep.FORM_STANDARD_SECTOR,
    ConversationStep.FORM_STANDARD_SECTOR: ConversationStep.FORM_STANDARD_MESSAGE,
    ConversationStep.FORM_STANDARD_MESSAGE: ConversationStep.FORM_STANDARD_DONE,
}

WIZARD_BUTTON_VALUES = {
    "CT_AGENCY": "Agence média / communication",
    "CT_BRAND": "Entreprise / marque",
    "CT_FINANCE": "Banque / assurance / institution financière",
    "CT_INSTITUTION": "Institution / ONG / organisation",
    "CT_REALESTATE": "Promoteur immobilier",
    "CT_OTHER": "Autre",
    "OBJ_AWARENESS": "Notoriété / image",
    "OBJ_LAUNCH": "Lancement produit / service",
    "OBJ_LEADS": "Générer des leads",
    "OBJ_REALESTATE": "Campagne immobilière",
    "OBJ_PREMIUM": "Abonnement Premium entreprise",
    "OBJ_PARTNERSHIP": "Partenariat annuel / convention",
    "B_LT_1000": "< 1000 TND",
    "B_1000_3000": "1000–3000",
    "B_3000_10000": "3000–10000",
    "B_GT_10000": "> 10000",
    "B_UNKNOWN": "Je ne sais pas encore",
    "SECTOR_BANK": "Banque",
    "SECTOR_TELCO": "Télécom",
    "SECTOR_REAL_ESTATE": "Immobilier",
    "SECTOR_RETAIL": "Retail",
    "SECTOR_INDUSTRY": "Industrie",
    "SECTOR_SERVICES": "Services",
    "SECTOR_INSTITUTION": "Institution",
    "SECTOR_OTHER": "Autre",
}

SOLUTION_NEED_TYPES = {
    ConversationStep.SOLUTION_DISPLAY: "display",
    ConversationStep.SOLUTION_CONTENT: "content",
    ConversationStep.SOLUTION_VIDEO: "video",
    ConversationStep.SOLUTION_AUDIO_NEWSLETTER: "audio_newsletter",
    ConversationStep.SOLUTION_INNOVATION: "innovation",
    ConversationStep.SOLUTION_MAG: "mag",
}

ENTRY_BUTTON_LEAD_TYPE = {
    "M_IMMONEUF": ("immoneuf", "immoneuf"),
    "M_PREMIUM": ("premium", "premium"),
    "M_PARTNERSHIP": ("partnership", "partnership"),
    "M_CALLBACK": ("callback", "callback"),
    "M_BUDGET_HELP": ("standard", "budget_help"),
}

STATIC_STEPS = {
    ConversationStep.WELCOME_SCOPE,
    ConversationStep.MAIN_MENU,
    ConversationStep.AUDIENCE,
    ConversationStep.SOLUTIONS_MENU,
    ConversationStep.SOLUTION_DISPLAY,
    ConversationStep.SOLUTION_CONTENT,
    ConversationStep.SOLUTION_VIDEO,
    ConversationStep.SOLUTION_AUDIO_NEWSLETTER,
    ConversationStep.SOLUTION_INNOVATION,
    ConversationStep.SOLUTION_MAG,
    ConversationStep.OUT_OF_SCOPE_READER,
}


def apply_global_interruptions(intent: Optional[str]) -> Optional[ConversationStep]:
    if intent == GlobalIntent.READER.value:
        return ConversationStep.OUT_OF_SCOPE_READER
    if intent == GlobalIntent.CALLBACK.value:
        return ConversationStep.FORM_STANDARD_FIRST_NAME
    return None


def get_buttons_for_step(step: ConversationStep) -> List[ButtonSpec]:
    buttons = list(BUTTONS_BY_STEP.get(step, ()))
    if step != ConversationStep.MAIN_MENU:
        if not any(button.id == NAV_MAIN_MENU_BUTTON.id for button in buttons):
            buttons.append(NAV_MAIN_MENU_BUTTON)
    return buttons


def get_transition(step: ConversationStep, button_id: Optional[str]) -> ConversationStep:
    if not button_id:
        return step
    if button_id == NAV_MAIN_MENU_BUTTON.id:
        return ConversationStep.MAIN_MENU
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


def is_wizard_step(step: ConversationStep) -> bool:
    return step in WIZARD_STEPS


def is_static_step(step: ConversationStep) -> bool:
    return step in STATIC_STEPS


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
    if step == "WELCOME":
        return ConversationStep.WELCOME_SCOPE
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


def looks_like_question(user_message: str) -> bool:
    normalized = normalize_text(user_message)
    if not normalized:
        return False
    if "?" in user_message:
        return True
    if normalized.startswith(
        ("quoi", "quel", "quels", "quelle", "quelles", "comment", "combien")
    ):
        return True
    return any(keyword in normalized for keyword in QUESTION_KEYWORDS)


def looks_like_reader_request(user_message: str) -> bool:
    normalized = normalize_text(user_message)
    if not normalized:
        return False
    return any(keyword in normalized for keyword in READER_KEYWORDS)


def match_button_id(step: ConversationStep, user_message: str) -> Optional[str]:
    normalized = normalize_text(user_message)
    if not normalized:
        return None
    for button in get_buttons_for_step(step):
        if normalize_text(button.label) == normalized:
            return button.id
    return None


def _match_text_value(step: ConversationStep, user_message: str) -> Optional[str]:
    if step not in WIZARD_SLOTS:
        return None
    normalized = normalize_text(user_message)
    if not normalized:
        return None
    if step == ConversationStep.BUDGET_RANGE:
        for button in BUDGET_RANGE_BUTTONS:
            if normalize_text(button.label) == normalized:
                return WIZARD_BUTTON_VALUES.get(button.id)
    if step == ConversationStep.BUDGET_OBJECTIVE:
        for button in BUDGET_OBJECTIVE_BUTTONS:
            if normalize_text(button.label) == normalized:
                return WIZARD_BUTTON_VALUES.get(button.id)
    if step == ConversationStep.BUDGET_CLIENT_TYPE:
        for button in BUDGET_CLIENT_TYPE_BUTTONS:
            if normalize_text(button.label) == normalized:
                return WIZARD_BUTTON_VALUES.get(button.id)
    if step == ConversationStep.FORM_STANDARD_SECTOR:
        for button in FORM_SECTOR_BUTTONS:
            if normalize_text(button.label) == normalized:
                return WIZARD_BUTTON_VALUES.get(button.id)
    return None


def _budget_recommendation_for_label(label: str) -> str:
    normalized = normalize_text(label)
    for button in BUDGET_RANGE_BUTTONS:
        if normalize_text(button.label) == normalized:
            return BUDGET_RECOMMENDATIONS.get(button.id, "")
    return ""


def _validate_email(value: str) -> bool:
    return bool(re.match(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", value.strip()))


def _validate_phone(value: str) -> bool:
    digits = re.sub(r"\\D", "", value)
    return len(digits) >= 6


def _validate_integer(value: str) -> Optional[int]:
    try:
        number = int(re.sub(r"\D", "", value))
    except ValueError:
        return None
    return number if number > 0 else None


def _build_validation_message(step: ConversationStep) -> str:
    prompt = build_wizard_prompt(step)
    return f"Je n'ai pas compris. {prompt}"


def build_wizard_prompt(step: ConversationStep) -> str:
    if step in BUDGET_PROMPTS:
        return BUDGET_PROMPTS[step]
    return FORM_MESSAGES.get(step, "Merci pour ces précisions.")


def _extract_launch_year_from_rag(rag_context: str, user_message: str) -> Optional[str]:
    normalized = normalize_text(user_message)
    launch_keywords = ("annee", "lancement", "lance", "creation", "cree", "depuis")
    if not any(keyword in normalized for keyword in launch_keywords):
        return None

    since_match = re.search(r'"since"\s*:\s*"(\d{4})(?:-\d{2})?"', rag_context)
    if since_match:
        return since_match.group(1)

    sentence_match = re.search(
        r"tunisie numerique[^.\n]{0,120}(?:lanc[eé]e?|cr[ée]e?|depuis)[^.\n]{0,80}(\d{4})",
        normalize_text(rag_context),
    )
    if sentence_match:
        return sentence_match.group(1)
    return None


def _build_factual_rag_answer(rag_context: str, user_message: str) -> Optional[str]:
    launch_year = _extract_launch_year_from_rag(rag_context, user_message)
    if launch_year:
        return f"Tunisie Numérique a été lancé en {launch_year}."
    return None


def _answer_rag_question(user_message: str) -> str:
    try:
        rag_context = retrieve_rag_context(user_message, top_k=6)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("wizard_rag_retrieval_failed", exc_info=exc)
        rag_context = ""

    factual_answer = _build_factual_rag_answer(rag_context, user_message)
    if factual_answer:
        return factual_answer

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


def _build_entry_path_update(
    slots: Dict[str, str],
    step: ConversationStep,
    button_id: Optional[str],
) -> Dict[str, str]:
    if not button_id:
        return {}
    current = slots.get("entry_path")
    if not current:
        return {"entry_path": f"{step.value}>{button_id}"}
    if current.endswith(f">{button_id}"):
        return {}
    return {"entry_path": f"{current}>{button_id}"}


def build_transition_slot_updates(
    *,
    step: ConversationStep,
    button_id: Optional[str],
    slots: Dict[str, str],
) -> Dict[str, str]:
    updates = _build_entry_path_update(slots, step, button_id)
    if not button_id:
        return updates
    lead_type = ENTRY_BUTTON_LEAD_TYPE.get(button_id)
    if lead_type:
        updates["lead_type"] = lead_type[0]
        updates["need_type"] = lead_type[1]
    if step in SOLUTION_NEED_TYPES and button_id == "M_CALLBACK":
        updates["lead_type"] = "standard"
        updates["need_type"] = SOLUTION_NEED_TYPES[step]
    return updates


def build_static_response(
    *,
    source_step: ConversationStep,
    step: ConversationStep,
    button_id: Optional[str],
    slots: Dict[str, str],
) -> Dict[str, object]:
    slot_updates = build_transition_slot_updates(
        step=source_step,
        button_id=button_id,
        slots=slots,
    )
    if step == ConversationStep.WELCOME_SCOPE:
        return build_response(
            step,
            WELCOME_SCOPE_MESSAGE,
            MAIN_MENU_BUTTONS,
            ConversationStep.MAIN_MENU,
            slot_updates,
            safety={"rag_used": False},
        )
    if step == ConversationStep.MAIN_MENU:
        return build_response(
            step,
            MAIN_MENU_MESSAGE,
            MAIN_MENU_BUTTONS,
            ConversationStep.MAIN_MENU,
            slot_updates,
            safety={"rag_used": False},
        )
    if step == ConversationStep.AUDIENCE:
        return build_response(
            step,
            AUDIENCE_MESSAGE,
            get_buttons_for_step(step),
            ConversationStep.AUDIENCE,
            slot_updates,
            safety={"rag_used": False},
        )
    if step == ConversationStep.SOLUTIONS_MENU:
        return build_response(
            step,
            SOLUTIONS_MENU_MESSAGE,
            get_buttons_for_step(step),
            ConversationStep.SOLUTIONS_MENU,
            slot_updates,
            safety={"rag_used": False},
        )
    if step in SOLUTION_PITCHES:
        return build_response(
            step,
            SOLUTION_PITCHES[step],
            get_buttons_for_step(step),
            step,
            slot_updates,
            safety={"rag_used": False},
        )
    if step == ConversationStep.OUT_OF_SCOPE_READER:
        return build_response(
            step,
            OUT_OF_SCOPE_MESSAGE,
            get_buttons_for_step(step),
            ConversationStep.OUT_OF_SCOPE_READER,
            slot_updates,
            handoff={"requested": True, "type": "OUT_OF_SCOPE", "url": HANDOFF_CONTACT_URL},
            safety={"rag_used": False},
        )
    return build_response(
        step,
        MAIN_MENU_MESSAGE,
        MAIN_MENU_BUTTONS,
        ConversationStep.MAIN_MENU,
        slot_updates,
        safety={"rag_used": False},
    )


def handle_step(
    step: ConversationStep,
    user_message: str,
    button_id: Optional[str],
    slots: Dict[str, str],
) -> Dict[str, object]:
    if step == ConversationStep.FORM_STANDARD_DONE:
        return build_response(
            step,
            FORM_MESSAGES[ConversationStep.FORM_STANDARD_DONE],
            get_buttons_for_step(step),
            ConversationStep.FORM_STANDARD_DONE,
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
        if step == ConversationStep.BUDGET_RANGE:
            recommendation = BUDGET_RECOMMENDATIONS.get(selected_button_id, "")
            recommendation_line = (
                f"Recommandation : {recommendation}." if recommendation else ""
            )
            assistant_message = (
                f"{recommendation_line}\n\n"
                "Pour une reco sur mesure, j'ai besoin de vos coordonnées pro."
            ).strip()
            slot_updates.setdefault("need_type", slots.get("need_type") or "budget_help")
            slot_updates.setdefault("lead_type", slots.get("lead_type") or "standard")
            return build_response(
                step,
                assistant_message,
                get_buttons_for_step(ConversationStep.FORM_STANDARD_FIRST_NAME),
                ConversationStep.FORM_STANDARD_FIRST_NAME,
                slot_updates,
                safety={"rag_used": False},
            )
        next_step = WIZARD_NEXT_STEP.get(step, step)
        return build_response(
            step,
            build_wizard_prompt(next_step),
            get_buttons_for_step(next_step),
            next_step,
            slot_updates,
            safety={"rag_used": False},
        )

    matched = _match_text_value(step, user_message)
    if matched:
        slot_updates = {slot_key: matched}
        if step == ConversationStep.BUDGET_RANGE:
            recommendation = _budget_recommendation_for_label(matched)
            recommendation_line = (
                f"Recommandation : {recommendation}." if recommendation else ""
            )
            assistant_message = (
                f"{recommendation_line}\n\n"
                "Pour une reco sur mesure, j'ai besoin de vos coordonnées pro."
            ).strip()
            slot_updates.setdefault("need_type", slots.get("need_type") or "budget_help")
            slot_updates.setdefault("lead_type", slots.get("lead_type") or "standard")
            return build_response(
                step,
                assistant_message,
                get_buttons_for_step(ConversationStep.FORM_STANDARD_FIRST_NAME),
                ConversationStep.FORM_STANDARD_FIRST_NAME,
                slot_updates,
                safety={"rag_used": False},
            )
        next_step = WIZARD_NEXT_STEP.get(step, step)
        return build_response(
            step,
            build_wizard_prompt(next_step),
            get_buttons_for_step(next_step),
            next_step,
            slot_updates,
            safety={"rag_used": False},
        )

    if looks_like_question(user_message):
        rag_answer = _answer_rag_question(user_message)
        assistant_message = f"{rag_answer}\n\nPour continuer : {build_wizard_prompt(step)}"
        return build_response(
            step,
            assistant_message,
            get_buttons_for_step(step),
            step,
            {},
            safety={"rag_used": True},
        )

    if step in BUTTONS_BY_STEP:
        return build_response(
            step,
            "Je n'ai pas compris. Merci de choisir un bouton.",
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

    if step == ConversationStep.FORM_STANDARD_EMAIL and not _validate_email(cleaned):
        return build_response(
            step,
            "Pouvez-vous indiquer un email valide ?",
            get_buttons_for_step(step),
            step,
            {},
            safety={"rag_used": False},
        )

    if step == ConversationStep.FORM_STANDARD_PHONE and not _validate_phone(cleaned):
        return build_response(
            step,
            "Pouvez-vous indiquer un numéro de téléphone valide ?",
            get_buttons_for_step(step),
            step,
            {},
            safety={"rag_used": False},
        )

    if step in {
        ConversationStep.FORM_IMMONEUF_PROJECTS_COUNT,
        ConversationStep.FORM_PREMIUM_ESTIMATED_USERS,
    }:
        parsed = _validate_integer(cleaned)
        if parsed is None:
            return build_response(
                step,
                "Merci d'indiquer un nombre valide.",
                get_buttons_for_step(step),
                step,
                {},
                safety={"rag_used": False},
            )
        slot_updates = {slot_key: str(parsed)}
        next_step = WIZARD_NEXT_STEP.get(step, step)
        return build_response(
            step,
            build_wizard_prompt(next_step),
            get_buttons_for_step(next_step),
            next_step,
            slot_updates,
            safety={"rag_used": False},
        )

    if step in {ConversationStep.FORM_STANDARD_JOB_TITLE, ConversationStep.FORM_STANDARD_MESSAGE}:
        if normalize_text(cleaned) in FORM_OPTIONAL_TOKENS:
            cleaned = ""

    slot_updates = {slot_key: cleaned}
    next_step = WIZARD_NEXT_STEP.get(step, step)

    if step == ConversationStep.FORM_STANDARD_MESSAGE:
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
            FORM_MESSAGES[ConversationStep.FORM_STANDARD_DONE],
            get_buttons_for_step(ConversationStep.FORM_STANDARD_DONE),
            ConversationStep.FORM_STANDARD_DONE,
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
