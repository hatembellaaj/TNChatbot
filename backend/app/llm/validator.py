import json
from typing import Any, Dict, List

DEFAULT_HANDOFF = {"requested": False}
DEFAULT_SAFETY = {"flagged": False}


class ValidationError(ValueError):
    """Raised when the LLM response is invalid."""


def normalize_llm_text(raw_content: str) -> str:
    if not raw_content:
        return ""
    stripped = raw_content.strip()
    if not stripped:
        return ""
    if stripped.startswith("{"):
        payload = _parse_llm_payload(stripped)
        assistant_message = payload.get("assistant_message")
        if isinstance(assistant_message, str) and assistant_message.strip():
            return assistant_message.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _parse_llm_payload(raw_content: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return {}

    if not isinstance(payload, dict):
        return {}

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
    default_next_step: str,
) -> Dict[str, Any]:
    payload = _parse_llm_payload(raw_content)

    assistant_message = payload.get("assistant_message")
    if not isinstance(assistant_message, str) or not assistant_message.strip():
        assistant_message = raw_content.strip()
    if not assistant_message:
        raise ValidationError("assistant_message must be a non-empty string")

    suggested_next_step = payload.get("suggested_next_step")
    if not isinstance(suggested_next_step, str) or not suggested_next_step.strip():
        suggested_next_step = default_next_step

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
    return build_fallback_response_with_step("MAIN_MENU")


def build_fallback_response_with_step(default_next_step: str) -> Dict[str, Any]:
    return {
        "assistant_message": (
            "Je suis désolé, je n'ai pas pu traiter votre demande. "
            "Voici le menu principal pour continuer."
        ),
        "buttons": [],
        "suggested_next_step": default_next_step,
        "slot_updates": {},
        "handoff": {"requested": False},
        "safety": {"flagged": False},
    }


def validate_or_fallback(
    raw_content: str,
    allowed_buttons: List[str],
    default_next_step: str,
    *,
    text_only: bool = False,
) -> Dict[str, Any]:
    if text_only:
        assistant_message = normalize_llm_text(raw_content)
        if not assistant_message:
            return build_fallback_response_with_step(default_next_step)
        return {
            "assistant_message": assistant_message,
            "buttons": [],
            "suggested_next_step": default_next_step,
            "slot_updates": {},
            "handoff": {"requested": False},
            "safety": {"flagged": False},
        }
    try:
        return normalize_llm_payload(raw_content, allowed_buttons, default_next_step)
    except ValidationError:
        return build_fallback_response_with_step(default_next_step)
