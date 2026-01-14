from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional


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


class GlobalIntent(str, Enum):
    READER = "reader"
    CALLBACK = "callback"


@dataclass(frozen=True)
class ButtonSpec:
    id: str
    label: str
    next_step: ConversationStep


HANDOFF_CONTACT_URL = "https://tangram-noe.com/contact"


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
        next_step=ConversationStep.BUDGET_CLIENT_TYPE,
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

BUTTONS_BY_STEP: Dict[ConversationStep, tuple[ButtonSpec, ...]] = {
    ConversationStep.WELCOME: WELCOME_BUTTONS,
    ConversationStep.MAIN_MENU: MAIN_MENU_BUTTONS,
    ConversationStep.SOLUTIONS_MENU: SOLUTIONS_MENU_BUTTONS,
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
