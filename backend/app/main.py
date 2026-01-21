import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.admin import load_admin_config, router as admin_router
from app.db import get_connection
from app.leads import router as leads_router
from app.llm.client import LLMClientError, call_llm
from app.llm.prompts import build_messages
from app.llm.validator import build_fallback_response, validate_or_fallback
from app.rag.retrieve import (
    build_config,
    is_factual_question,
    retrieve_rag_context,
    should_trigger_rag,
)

app = FastAPI(title="TNChatbot API")
LOGGER = logging.getLogger(__name__)
PING_INTERVAL_SECONDS = 15

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatSessionCreateResponse(BaseModel):
    session_id: str


class ChatMessageRequest(BaseModel):
    session_id: str
    user_message: str
    state: Dict[str, Any]
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatButton(BaseModel):
    id: str
    label: str


class ChatMessageResponse(BaseModel):
    assistant_message: str
    buttons: List[ChatButton]
    suggested_next_step: str
    slot_updates: Dict[str, Any]
    handoff: Dict[str, Any]
    safety: Dict[str, Any]


class ChatStreamFinal(BaseModel):
    assistant_message: str
    state: Dict[str, Any]
    buttons: List[ChatButton]


def initialize_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id UUID PRIMARY KEY,
                step TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_config (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


@app.on_event("startup")
def on_startup() -> None:
    initialize_db()


app.include_router(leads_router)
app.include_router(admin_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {"message": "TNChatbot backend is running"}


@app.post("/api/chat/session", response_model=ChatSessionCreateResponse)
def create_chat_session() -> ChatSessionCreateResponse:
    session_id = uuid.uuid4()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (session_id, step) VALUES (%s, %s)",
            (session_id, "WELCOME"),
        )
    return ChatSessionCreateResponse(session_id=str(session_id))


@app.post("/api/chat/message", response_model=ChatMessageResponse)
def chat_message(payload: ChatMessageRequest) -> ChatMessageResponse:
    allowed_buttons = payload.context.get("allowed_buttons") or []
    form_schema = payload.context.get("form_schema", {})
    admin_config = load_admin_config()
    context_config = payload.context.get("config") or {}
    config = build_config({**admin_config, **context_config})
    rag_context = payload.context.get("rag_context", "")
    step = payload.state.get("step", "UNKNOWN")
    intent = payload.state.get("intent") or payload.context.get("intent")
    LOGGER.info("intent_selected intent=%s", intent or "unknown")

    rag_triggered = should_trigger_rag(intent, payload.user_message)
    if rag_triggered:
        try:
            retrieved_context = retrieve_rag_context(
                payload.user_message,
                intent=intent,
            )
            rag_context = "\n\n".join(
                [context for context in (rag_context, retrieved_context) if context]
            )
        except Exception as exc:  # noqa: BLE001 - log and continue with empty context
            LOGGER.warning("RAG retrieval failed", exc_info=exc)
        LOGGER.info("rag_used=true intent=%s", intent or "unknown")

    rag_empty_factual = (
        rag_triggered and not rag_context and is_factual_question(payload.user_message)
    )

    messages = build_messages(
        step=step,
        allowed_buttons=allowed_buttons,
        form_schema=form_schema,
        config=config,
        rag_context=rag_context,
        rag_empty_factual=rag_empty_factual,
        user_message=payload.user_message,
    )

    try:
        llm_response = call_llm(messages)
    
        LOGGER.warning(
            "llm_raw_response session_id=%s response=%s",
            payload.session_id,
            llm_response,
        )

        validated = validate_or_fallback(llm_response, allowed_buttons)

    except LLMClientError as exc:
        LOGGER.error(
            "llm_call_failed session_id=%s error=%s",
            payload.session_id,
            exc,
        )
        validated = build_fallback_response()


    next_step = validated.get("suggested_next_step", "MAIN_MENU")
    with get_connection() as conn:
        result = conn.execute(
            "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
            (next_step, payload.session_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Session not found")

    return ChatMessageResponse(
        assistant_message=validated["assistant_message"],
        buttons=[ChatButton(**button) for button in validated["buttons"]],
        suggested_next_step=validated["suggested_next_step"],
        slot_updates=validated["slot_updates"],
        handoff=validated["handoff"],
        safety=validated["safety"],
    )


def _format_sse(event: str, data: Dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _tokenize_message(message: str) -> List[str]:
    return re.findall(r"\S+\s*", message)


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatMessageRequest) -> StreamingResponse:
    allowed_buttons = payload.context.get("allowed_buttons") or []
    form_schema = payload.context.get("form_schema", {})
    admin_config = load_admin_config()
    context_config = payload.context.get("config") or {}
    config = build_config({**admin_config, **context_config})
    rag_context = payload.context.get("rag_context", "")
    step = payload.state.get("step", "UNKNOWN")
    intent = payload.state.get("intent") or payload.context.get("intent")
    LOGGER.info("intent_selected intent=%s", intent or "unknown")

    rag_triggered = should_trigger_rag(intent, payload.user_message)
    if rag_triggered:
        try:
            retrieved_context = retrieve_rag_context(
                payload.user_message,
                intent=intent,
            )
            rag_context = "\n\n".join(
                [context for context in (rag_context, retrieved_context) if context]
            )
        except Exception as exc:  # noqa: BLE001 - log and continue with empty context
            LOGGER.warning("RAG retrieval failed", exc_info=exc)
        LOGGER.info("rag_used=true intent=%s", intent or "unknown")

    rag_empty_factual = (
        rag_triggered and not rag_context and is_factual_question(payload.user_message)
    )

    messages = build_messages(
        step=step,
        allowed_buttons=allowed_buttons,
        form_schema=form_schema,
        config=config,
        rag_context=rag_context,
        rag_empty_factual=rag_empty_factual,
        user_message=payload.user_message,
    )

    async def event_stream() -> Any:
        LOGGER.info(
            "chat_stream_start session_id=%s step=%s rag_triggered=%s rag_empty_factual=%s",
            payload.session_id,
            step,
            rag_triggered,
            rag_empty_factual,
        )
        route = "rag" if rag_triggered else "direct"
        yield _format_sse(
            "meta",
            {
                "route": route,
                "rag_empty_factual": rag_empty_factual,
            },
        )

        llm_error = None
        llm_start = time.monotonic()
        llm_task = asyncio.create_task(asyncio.to_thread(call_llm, messages))

        while True:
            done, _ = await asyncio.wait({llm_task}, timeout=PING_INTERVAL_SECONDS)
            if llm_task in done:
                break
            yield _format_sse("ping", {"ts": time.time()})

        try:
            llm_response = await llm_task
            validated = validate_or_fallback(llm_response, allowed_buttons)
        except (LLMClientError, TimeoutError) as exc:
            llm_error = str(exc)
            validated = build_fallback_response()
            LOGGER.warning(
                "chat_stream_llm_error session_id=%s error=%s",
                payload.session_id,
                llm_error,
            )

        if llm_error:
            yield _format_sse("error", {"message": llm_error})

        next_step = validated.get("suggested_next_step", "MAIN_MENU")
        with get_connection() as conn:
            result = conn.execute(
                "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
                (next_step, payload.session_id),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Session not found")
        LOGGER.info(
            "chat_stream_state_update session_id=%s next_step=%s",
            payload.session_id,
            next_step,
        )

        assistant_message = validated["assistant_message"]
        for token in _tokenize_message(assistant_message):
            yield _format_sse("token", {"value": token})

        state_payload = {
            "step": next_step,
            "slot_updates": validated["slot_updates"],
            "handoff": validated["handoff"],
            "safety": validated["safety"],
            "suggested_next_step": validated["suggested_next_step"],
            "latency_ms": int((time.monotonic() - llm_start) * 1000),
        }
        yield _format_sse(
            "final",
            ChatStreamFinal(
                assistant_message=assistant_message,
                state=state_payload,
                buttons=[ChatButton(**button) for button in validated["buttons"]],
            ).model_dump(),
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
