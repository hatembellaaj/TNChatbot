import os
import re
from typing import Any, Dict, List

SYSTEM_PROMPT = """
Tu es un assistant de service client.
Contraintes obligatoires :
- Réponds uniquement en français.
- Utilise exclusivement le contexte RAG.
- N'invente jamais d'information.
- Si le contexte est insuffisant, dis-le poliment.
- Réponds uniquement avec un JSON valide conforme EXACTEMENT au schéma :

{
  "assistant_message": string,
  "buttons": [ { "id": string, "label": string } ],
  "suggested_next_step": string,
  "slot_updates": object,
  "handoff": object,
  "safety": object
}

Aucun texte hors JSON. Aucun champ supplémentaire.
""".strip()


DEFAULT_PROMPT_MAX_TOKENS = 400

DEVELOPER_PROMPT_TEMPLATE = """
Étape courante: {step}

Boutons autorisés (ids): {allowed_buttons}

Schéma de formulaire:
{form_schema}

Configuration:
{config}

Contexte RAG:
{rag_context}

RAG vide et question factuelle: {rag_empty_factual}
""".strip()


def _estimate_tokens(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _trim_text_to_tokens(text: str, max_tokens: int) -> str:
    tokens = re.findall(r"\S+", text)
    if len(tokens) <= max_tokens:
        return text
    if max_tokens <= 0:
        return ""
    return " ".join(tokens[:max_tokens])


def _trim_rag_context(
    *,
    step: str,
    allowed_buttons: List[str],
    form_schema: Dict[str, Any],
    config: Dict[str, Any],
    rag_context: str,
    rag_empty_factual: bool,
    user_message: str,
) -> str:
    max_tokens = int(os.getenv("PROMPT_MAX_TOKENS", DEFAULT_PROMPT_MAX_TOKENS))
    base_prompt = DEVELOPER_PROMPT_TEMPLATE.format(
        step=step,
        allowed_buttons=", ".join(allowed_buttons),
        form_schema=form_schema,
        config=config,
        rag_context="",
        rag_empty_factual="oui" if rag_empty_factual else "non",
    )
    base_tokens = (
        _estimate_tokens(SYSTEM_PROMPT)
        + _estimate_tokens(base_prompt)
        + _estimate_tokens(user_message)
    )
    available = max(max_tokens - base_tokens, 0)
    if not rag_context or available <= 0:
        return ""
    rag_tokens = re.findall(r"\S+", rag_context)
    if len(rag_tokens) <= available:
        return rag_context
    return " ".join(rag_tokens[:available])


def _trim_developer_prompt(
    developer_prompt: str,
    *,
    user_message: str,
) -> str:
    max_tokens = int(os.getenv("PROMPT_MAX_TOKENS", DEFAULT_PROMPT_MAX_TOKENS))
    reserved_tokens = _estimate_tokens(SYSTEM_PROMPT) + _estimate_tokens(user_message)
    available = max(max_tokens - reserved_tokens, 0)
    return _trim_text_to_tokens(developer_prompt, available)


def build_messages(
    *,
    step: str,
    allowed_buttons: List[str],
    form_schema: Dict[str, Any],
    config: Dict[str, Any],
    rag_context: str,
    rag_empty_factual: bool,
    user_message: str,
) -> List[Dict[str, str]]:
    rag_context = _trim_rag_context(
        step=step,
        allowed_buttons=allowed_buttons,
        form_schema=form_schema,
        config=config,
        rag_context=rag_context,
        rag_empty_factual=rag_empty_factual,
        user_message=user_message,
    )
    developer_prompt = DEVELOPER_PROMPT_TEMPLATE.format(
        step=step,
        allowed_buttons=", ".join(allowed_buttons),
        form_schema=form_schema,
        config=config,
        rag_context=rag_context,
        rag_empty_factual="oui" if rag_empty_factual else "non",
    )
    developer_prompt = _trim_developer_prompt(
        developer_prompt,
        user_message=user_message,
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "developer", "content": developer_prompt},
        {"role": "user", "content": user_message},
    ]
