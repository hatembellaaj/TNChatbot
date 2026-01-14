import json
from typing import Any, Dict, List

REQUIRED_FIELDS = {
    "assistant_message",
    "buttons",
    "suggested_next_step",
    "slot_updates",
    "handoff",
    "safety",
}


class ValidationError(ValueError):
    """Raised when the LLM response is invalid."""


def parse_llm_json(raw_content: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValidationError("LLM response is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValidationError("LLM response must be a JSON object")

    missing = REQUIRED_FIELDS - payload.keys()
    if missing:
        raise ValidationError(f"Missing fields: {', '.join(sorted(missing))}")

    return payload


def validate_buttons(payload: Dict[str, Any], allowed_buttons: List[str]) -> None:
    buttons = payload.get("buttons")
    if not isinstance(buttons, list):
        raise ValidationError("buttons must be a list")

    for button in buttons:
        if not isinstance(button, dict):
            raise ValidationError("button entries must be objects")
        button_id = button.get("id")
        if not isinstance(button_id, str):
            raise ValidationError("button id must be a string")
        if button_id not in allowed_buttons:
            raise ValidationError(f"button id '{button_id}' not allowed")


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
        payload = parse_llm_json(raw_content)
        validate_buttons(payload, allowed_buttons)
        return payload
    except ValidationError:
        return build_fallback_response()
