import json
from typing import Any, Dict, List

DEFAULT_HANDOFF = {"requested": False}
DEFAULT_SAFETY = {"flagged": False}


class ValidationError(ValueError):
    """Raised when the LLM response is invalid."""


def parse_llm_json(raw_content: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValidationError("LLM response is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValidationError("LLM response must be a JSON object")

    return payload


def _normalize_buttons(
    buttons: Any,
    allowed_buttons: List[str],
) -> List[Dict[str, str]]:
    if not isinstance(buttons, list):
        return []

    normalized: List[Dict[str, str]] = []
    for button in buttons:
        if not isinstance(button, dict):
            continue
        button_id = button.get("id")
        label = button.get("label")
        if not isinstance(button_id, str) or not button_id.strip():
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        if allowed_buttons and button_id not in allowed_buttons:
            continue
        normalized.append({"id": button_id, "label": label})
    return normalized


def normalize_llm_payload(
    raw_content: str,
    allowed_buttons: List[str],
) -> Dict[str, Any]:
    payload = parse_llm_json(raw_content)

    assistant_message = payload.get("assistant_message")
    if not isinstance(assistant_message, str) or not assistant_message.strip():
        raise ValidationError("assistant_message must be a non-empty string")

    suggested_next_step = payload.get("suggested_next_step")
    if not isinstance(suggested_next_step, str) or not suggested_next_step.strip():
        suggested_next_step = "MAIN_MENU"

    slot_updates = payload.get("slot_updates")
    if not isinstance(slot_updates, dict):
        slot_updates = {}

    handoff = payload.get("handoff")
    if not isinstance(handoff, dict):
        handoff = DEFAULT_HANDOFF.copy()

    safety = payload.get("safety")
    if not isinstance(safety, dict):
        safety = DEFAULT_SAFETY.copy()

    buttons = _normalize_buttons(payload.get("buttons"), allowed_buttons)

    return {
        "assistant_message": assistant_message,
        "buttons": buttons,
        "suggested_next_step": suggested_next_step,
        "slot_updates": slot_updates,
        "handoff": handoff,
        "safety": safety,
    }


def build_fallback_response() -> Dict[str, Any]:
    return {
        "assistant_message": (
            "Je suis désolé, je n'ai pas pu traiter votre demande. "
            "Voici le menu principal pour continuer."
        ),
        "buttons": [
            {"id": "CALL_BACK", "label": "Être rappelé"},
        ],
        "suggested_next_step": "MAIN_MENU",
        "slot_updates": {},
        "handoff": {"requested": False},
        "safety": {"flagged": False},
    }


def validate_or_fallback(
    raw_content: str,
    allowed_buttons: List[str],
) -> Dict[str, Any]:
    try:
        return normalize_llm_payload(raw_content, allowed_buttons)
    except ValidationError:
        return build_fallback_response()
