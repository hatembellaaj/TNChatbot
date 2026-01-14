import json
import os
import urllib.error
import urllib.request
from typing import Dict, List

DEFAULT_LLM_URL = "http://localhost:8001/v1/chat/completions"
DEFAULT_MODEL = "llama-3.2-3b-instruct"


class LLMClientError(RuntimeError):
    """Raised when the LLM call fails."""


def call_llm(messages: List[Dict[str, str]]) -> str:
    llm_url = os.getenv("LLM_URL", DEFAULT_LLM_URL)
    model = os.getenv("LLM_MODEL", DEFAULT_MODEL)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        llm_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise LLMClientError("LLM request failed") from exc

    try:
        payload = json.loads(body)
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise LLMClientError("Unexpected LLM response format") from exc
