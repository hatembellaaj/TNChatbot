import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Dict, List

DEFAULT_LLM_URL = "http://localhost:11434/v1/chat/completions"
DEFAULT_MODEL = "llama3.2:3b"
DEFAULT_TIMEOUT_SECONDS = 60
LOGGER = logging.getLogger(__name__)


class LLMClientError(RuntimeError):
    """Raised when the LLM call fails."""


def call_llm(messages: List[Dict[str, str]]) -> str:
    llm_url = os.getenv("LLM_URL", DEFAULT_LLM_URL)
    model = os.getenv("LLM_MODEL", DEFAULT_MODEL)
    timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    start = time.monotonic()

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
        LOGGER.info(
            "llm_request_start url=%s model=%s messages=%s timeout_s=%s",
            llm_url,
            model,
            len(messages),
            timeout_seconds,
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
        LOGGER.info(
            "llm_request_success url=%s model=%s latency_ms=%s bytes=%s",
            llm_url,
            model,
            int((time.monotonic() - start) * 1000),
            len(body),
        )
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8") if exc.fp else ""
        message = f"LLM request failed ({exc.code})"
        if error_body:
            message = f"{message}: {error_body}"
        LOGGER.error(
            "llm_request_http_error url=%s model=%s status=%s body=%s",
            llm_url,
            model,
            exc.code,
            error_body,
        )
        raise LLMClientError(message) from exc
    except urllib.error.URLError as exc:
        LOGGER.error(
            "llm_request_url_error url=%s model=%s error=%s",
            llm_url,
            model,
            exc,
        )
        raise LLMClientError("LLM request failed") from exc

    try:
        payload = json.loads(body)
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        LOGGER.error(
            "llm_response_parse_error url=%s model=%s error=%s body=%s",
            llm_url,
            model,
            exc,
            body,
        )
        raise LLMClientError("Unexpected LLM response format") from exc
