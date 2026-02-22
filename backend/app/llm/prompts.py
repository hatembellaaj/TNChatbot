import logging
import os
import re
import json
from typing import Any, Dict, List

SYSTEM_PROMPT = (
    """
Tu réponds au nom de Tunisie Numérique (annonceurs).

Règles obligatoires :
- Réponds uniquement en français.
- Utilise exclusivement les informations présentes dans le contexte RAG.
- N'invente jamais d'information (aucun chiffre ni détail absent du contexte).
- Les données présentes dans le contexte RAG (y compris clés JSON et valeurs numériques) font foi.
- Si une valeur numérique ou un champ est présent dans le contexte, tu dois l'utiliser pour répondre.
- Tu peux reformuler les données du contexte en phrase naturelle.
- Si une information demandée n’est réellement pas présente dans le contexte, indique clairement que l'information n'est pas disponible dans le kit média.
- Ne réponds jamais de manière générique si le contexte contient l'information.
- Réponds en texte simple (pas de JSON, pas de balises).
- Tu ne produis jamais de structure JSON.
""".strip()
)

LOGGER = logging.getLogger(__name__)

DEFAULT_PROMPT_MAX_TOKENS = 250

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
        form_schema=_compact_json(form_schema, 80),
        config=_compact_json(config, 50),
        rag_context="",
        rag_empty_factual="oui" if rag_empty_factual else "non",
    )

    base_tokens = (
        _estimate_tokens(SYSTEM_PROMPT)
        + _estimate_tokens(base_prompt)
        + _estimate_tokens(user_message)
    )
    available = max(max_tokens - base_tokens, 0)
    rag_token_count = _estimate_tokens(rag_context)
    LOGGER.info(
        "rag_context_trim_check max_tokens=%s base_tokens=%s available=%s rag_tokens=%s",
        max_tokens,
        base_tokens,
        available,
        rag_token_count,
    )
    if not rag_context or available <= 0:
        if rag_context:
            LOGGER.warning("rag_context_trimmed_to_empty reason=no_available_tokens")
        return ""
    rag_tokens = re.findall(r"\S+", rag_context)
    if len(rag_tokens) <= available:
        return rag_context
    trimmed = " ".join(rag_tokens[:available])
    LOGGER.warning(
        "rag_context_trimmed_to_fit original_tokens=%s trimmed_tokens=%s",
        len(rag_tokens),
        available,
    )
    return trimmed


def _trim_developer_prompt(
    developer_prompt: str,
    *,
    user_message: str,
) -> str:
    max_tokens = int(os.getenv("PROMPT_MAX_TOKENS", DEFAULT_PROMPT_MAX_TOKENS))
    reserved_tokens = _estimate_tokens(SYSTEM_PROMPT) + _estimate_tokens(user_message)
    available = max(max_tokens - reserved_tokens, 0)
    return _trim_text_to_tokens(developer_prompt, available)

def _compact_json(obj: Dict[str, Any], max_tokens: int) -> str:
    """
    Compacte un dict JSON en une seule ligne et limite sa taille en 'tokens' (approx mots).
    """
    try:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""
    tokens = re.findall(r"\S+", text)
    if len(tokens) <= max_tokens:
        return text
    return " ".join(tokens[:max_tokens])


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
        form_schema=_compact_json(form_schema, 80),
        config=_compact_json(config, 50),
        rag_context=rag_context,
        rag_empty_factual="oui" if rag_empty_factual else "non",
    )

    developer_prompt = _trim_developer_prompt(
        developer_prompt,
        user_message=user_message,
    )
    LOGGER.info(
        "developer_prompt_tokens=%s rag_context_included=%s",
        _estimate_tokens(developer_prompt),
        bool(rag_context and rag_context in developer_prompt),
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "developer", "content": developer_prompt},
        {"role": "user", "content": user_message},
    ]
