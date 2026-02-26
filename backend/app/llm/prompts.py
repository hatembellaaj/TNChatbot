import logging
import os
import re
import json
from typing import Any, Dict, List
import unicodedata

SYSTEM_PROMPT = (
    """
Tu réponds au nom de Tunisie Numérique (annonceurs).

Règles obligatoires :
- Réponds uniquement en français.
- Utilise exclusivement les informations présentes dans le contexte RAG.
- N'invente jamais d'information (aucun chiffre ni détail absent du contexte).
- Les données présentes dans le contexte RAG (y compris clés JSON et valeurs numériques) font foi.
- Si une valeur numérique ou un champ est présent dans le contexte, tu dois l'utiliser pour répondre.
- Accepte les variations mineures de formulation entre la question et le contexte (accents, singulier/pluriel, anglais/français, orthographe proche) et fais la correspondance la plus probable.
- Si une ligne du contexte correspond clairement à la demande (même avec une formulation légèrement différente), réponds avec cette valeur au lieu de dire que l'information est introuvable.
- Tu peux reformuler les données du contexte en phrase naturelle.
- Si une information demandée n’est réellement pas présente dans le contexte, indique clairement que l'information n'est pas disponible dans le kit média.
- Ne réponds jamais de manière générique si le contexte contient l'information.
- Réponds en texte simple (pas de JSON, pas de balises).
- Tu ne produis jamais de structure JSON.
""".strip()
)

LOGGER = logging.getLogger(__name__)

DEFAULT_PROMPT_MAX_TOKENS = 1400

DEVELOPER_PROMPT_TEMPLATE = """
Étape courante: {step}

Boutons autorisés (ids): {allowed_buttons}

Schéma de formulaire:
{form_schema}

Configuration:
{config}

Faits prioritaires extraits du contexte:
{priority_facts}

Contexte RAG:
{rag_context}

RAG vide et question factuelle: {rag_empty_factual}

Historique récent:
{recent_history}
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




def _sanitize_rag_context(rag_context: str) -> str:
    """Nettoie les marqueurs parasites afin de préserver les valeurs factuelles."""
    cleaned = rag_context.replace("🎬", " ").replace("!", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _extract_priority_facts(rag_context: str, user_message: str) -> str:
    """Extrait des faits courts (notamment dates/chiffres) pour les questions factuelles."""
    if not rag_context:
        return ""

    facts: List[str] = []
    normalized_question = user_message.lower()

    since_match = re.search(r'"since"\s*:\s*"(\d{4})(?:-\d{2})?"', rag_context)
    if since_match and any(keyword in normalized_question for keyword in ("année", "lanc", "création", "depuis")):
        facts.append(f"Année de lancement (champ since): {since_match.group(1)}")

    sentence_match = re.search(
        r"(?:lanc[eé]|cr[ée]e?|depuis)[^.\n]{0,60}(\d{4})",
        rag_context,
        flags=re.IGNORECASE,
    )
    if sentence_match and not any(sentence_match.group(1) in fact for fact in facts):
        facts.append(f"Année mentionnée dans le contexte: {sentence_match.group(1)}")

    pricing_fact = _extract_pricing_fact(rag_context, user_message)
    if pricing_fact:
        facts.append(pricing_fact)

    return "\n".join(f"- {fact}" for fact in facts[:3])


def _normalize_for_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    no_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9\s]", " ", no_accents)


def _extract_pricing_fact(rag_context: str, user_message: str) -> str:
    question = _normalize_for_match(user_message)
    question_tokens = {
        token
        for token in question.split()
        if len(token) > 2 and token not in {"combien", "coute", "cout", "prix", "tarif", "une", "pour"}
    }
    if not question_tokens:
        return ""

    best_line = ""
    best_overlap = 0
    candidates = re.split(r"(?<=[.!?])\s+", rag_context)
    for candidate in candidates:
        line = candidate.strip()
        if len(line) < 5:
            continue
        if not re.search(r"\b\d+[\d\s]*(?:dt|dinar|tnd|€|eur)\b", _normalize_for_match(line)):
            continue
        normalized_line = _normalize_for_match(line)
        overlap = sum(1 for token in question_tokens if token in normalized_line)
        if overlap > best_overlap:
            best_overlap = overlap
            best_line = line

    if best_overlap == 0 or not best_line:
        return ""
    return f"Tarif pertinent trouvé: {best_line}"
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
        priority_facts="",
        rag_context="",
        rag_empty_factual="oui" if rag_empty_factual else "non",
        recent_history="- Aucun historique récent",
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


def _format_recent_history(conversation_history: List[Dict[str, str]]) -> str:
    if not conversation_history:
        return "- Aucun historique récent"

    lines: List[str] = []
    for message in conversation_history:
        role = message.get("role", "")
        content = message.get("content", "")
        if role not in {"user", "assistant"} or not content:
            continue
        label = "Utilisateur" if role == "user" else "Assistant"
        lines.append(f"- {label}: {content}")

    return "\n".join(lines) if lines else "- Aucun historique récent"


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
    conversation_history: List[Dict[str, str]] | None = None,
) -> List[Dict[str, str]]:
    rag_context = _sanitize_rag_context(rag_context)
    priority_facts = _extract_priority_facts(rag_context, user_message)

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
        priority_facts=priority_facts or "- Aucun fait prioritaire extrait",
        rag_context=rag_context,
        rag_empty_factual="oui" if rag_empty_factual else "non",
        recent_history=_format_recent_history(conversation_history or []),
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

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "developer", "content": developer_prompt},
    ]

    history = list(conversation_history or [])
    if history and history[-1].get("role") == "user" and history[-1].get("content") == user_message:
        history = history[:-1]

    for message in history:
        role = message.get("role", "")
        content = message.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})
    return messages
