from typing import Any, Dict, List

SYSTEM_PROMPT = """
Tu es un assistant conversationnel pour un service client. Tu dois respecter STRICTEMENT
les contraintes suivantes :
- Réponds UNIQUEMENT en français.
- Réponds UNIQUEMENT à partir du contexte RAG fourni.
- Ne fabrique aucune information absente du contexte RAG.
- Ta réponse DOIT être un JSON STRICT valide (sans texte avant/après).
- Le JSON doit respecter exactement le schéma suivant :
{
  "assistant_message": string,
  "buttons": [ { "id": string, "label": string } ],
  "suggested_next_step": string,
  "slot_updates": object,
  "handoff": object,
  "safety": object
}
- N'ajoute aucun champ supplémentaire.
- Si l'information manque dans le contexte RAG, indique poliment que tu ne sais pas.
""".strip()

DEVELOPER_PROMPT_TEMPLATE = """
Étape courante: {step}

Boutons autorisés (ids): {allowed_buttons}

Schéma de formulaire:
{form_schema}

Configuration:
{config}

Contexte RAG:
{rag_context}
""".strip()


def build_messages(
    *,
    step: str,
    allowed_buttons: List[str],
    form_schema: Dict[str, Any],
    config: Dict[str, Any],
    rag_context: str,
    user_message: str,
) -> List[Dict[str, str]]:
    developer_prompt = DEVELOPER_PROMPT_TEMPLATE.format(
        step=step,
        allowed_buttons=", ".join(allowed_buttons),
        form_schema=form_schema,
        config=config,
        rag_context=rag_context,
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "developer", "content": developer_prompt},
        {"role": "user", "content": user_message},
    ]
