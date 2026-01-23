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
from psycopg import errors

from app.admin import load_admin_config, router as admin_router
from app.db import get_connection
from app.leads import router as leads_router
from app.llm.client import LLMClientError, call_llm
from app.llm.prompts import build_messages
from app.llm.validator import (
    build_fallback_response_with_step,
    normalize_llm_text,
    validate_or_fallback,
)
from app.orchestrator.state_machine import (
    ConversationStep,
    build_response,
    build_static_response,
    build_transition_slot_updates,
    build_wizard_prompt,
    get_buttons_for_step,
    handle_step,
    is_wizard_step,
    is_static_step,
    looks_like_reader_request,
    match_button_id,
    normalize_step,
    resolve_next_step,
    serialize_buttons,
)
from app.rag.retrieve import (
    build_config,
    classify_intent,
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
            CREATE TABLE IF NOT EXISTS chat_messages (
                id BIGSERIAL PRIMARY KEY,
                session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                step TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            """
            ALTER TABLE chat_messages
            ADD COLUMN IF NOT EXISTS step TEXT
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
            (session_id, ConversationStep.WELCOME_SCOPE.value),
        )
    return ChatSessionCreateResponse(session_id=str(session_id))


def record_chat_message(
    session_id: str,
    role: str,
    content: str,
    step: str | None,
) -> None:
    with get_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, step)
                VALUES (%s, %s, %s, %s)
                """,
                (session_id, role, content, step),
            )
        except errors.ForeignKeyViolation as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc


@app.post("/api/chat/message", response_model=ChatMessageResponse)
def chat_message(payload: ChatMessageRequest) -> ChatMessageResponse:
    allowed_buttons = payload.context.get("allowed_buttons") or []
    form_schema = payload.context.get("form_schema", {})
    admin_config = load_admin_config()
    context_config = payload.context.get("config") or {}
    config = build_config({**admin_config, **context_config})
    rag_context = payload.context.get("rag_context", "")
    raw_step = payload.state.get("step", "UNKNOWN")
    resolved_step = normalize_step(raw_step) or ConversationStep.MAIN_MENU
    step = resolved_step.value
    raw_intent = payload.state.get("intent") or payload.context.get("intent")
    inferred_intent = None if raw_intent else classify_intent(payload.user_message)
    intent = raw_intent or inferred_intent
    source = "payload" if raw_intent else ("inferred" if inferred_intent else "none")
    LOGGER.warning("intent_selected intent=%s source=%s", intent or "unknown", source)
    record_chat_message(payload.session_id, "user", payload.user_message, step)

    slots = payload.state.get("slots")
    if not isinstance(slots, dict):
        slots = {}

    button_id = payload.state.get("button_id")
    if not isinstance(button_id, str):
        button_id = match_button_id(resolved_step, payload.user_message)

    next_step = resolve_next_step(resolved_step, button_id, intent)

    if looks_like_reader_request(payload.user_message):
        reader_payload = build_static_response(
            source_step=resolved_step,
            step=ConversationStep.OUT_OF_SCOPE_READER,
            button_id=button_id,
            slots=slots,
        )
        with get_connection() as conn:
            result = conn.execute(
                "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
                (reader_payload["suggested_next_step"], payload.session_id),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Session not found")
        record_chat_message(
            payload.session_id,
            "assistant",
            reader_payload["assistant_message"],
            reader_payload["suggested_next_step"],
        )
        return ChatMessageResponse(
            assistant_message=reader_payload["assistant_message"],
            buttons=[ChatButton(**button) for button in reader_payload["buttons"]],
            suggested_next_step=reader_payload["suggested_next_step"],
            slot_updates=reader_payload["slot_updates"],
            handoff=reader_payload["handoff"],
            safety=reader_payload["safety"],
        )

    if is_wizard_step(resolved_step) or resolved_step == ConversationStep.BUDGET_CLIENT_TYPE:
        wizard_payload = handle_step(
            resolved_step,
            payload.user_message,
            button_id,
            slots,
        )
        with get_connection() as conn:
            result = conn.execute(
                "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
                (wizard_payload["suggested_next_step"], payload.session_id),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Session not found")
        record_chat_message(
            payload.session_id,
            "assistant",
            wizard_payload["assistant_message"],
            wizard_payload["suggested_next_step"],
        )
        return ChatMessageResponse(
            assistant_message=wizard_payload["assistant_message"],
            buttons=[ChatButton(**button) for button in wizard_payload["buttons"]],
            suggested_next_step=wizard_payload["suggested_next_step"],
            slot_updates=wizard_payload["slot_updates"],
            handoff=wizard_payload["handoff"],
            safety=wizard_payload["safety"],
        )

    if is_wizard_step(next_step):
        slot_updates = build_transition_slot_updates(
            step=resolved_step,
            button_id=button_id,
            slots=slots,
        )
        wizard_payload = build_response(
            resolved_step,
            build_wizard_prompt(next_step),
            get_buttons_for_step(next_step),
            next_step,
            slot_updates,
            handoff={"requested": False},
            safety={"rag_used": False},
        )
        with get_connection() as conn:
            result = conn.execute(
                "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
                (wizard_payload["suggested_next_step"], payload.session_id),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Session not found")
        record_chat_message(
            payload.session_id,
            "assistant",
            wizard_payload["assistant_message"],
            wizard_payload["suggested_next_step"],
        )
        return ChatMessageResponse(
            assistant_message=wizard_payload["assistant_message"],
            buttons=[ChatButton(**button) for button in wizard_payload["buttons"]],
            suggested_next_step=wizard_payload["suggested_next_step"],
            slot_updates=wizard_payload["slot_updates"],
            handoff=wizard_payload["handoff"],
            safety=wizard_payload["safety"],
        )

    if resolved_step == ConversationStep.WELCOME_SCOPE or (
        button_id and is_static_step(next_step)
    ):
        static_payload = build_static_response(
            source_step=resolved_step,
            step=next_step if resolved_step != ConversationStep.WELCOME_SCOPE else resolved_step,
            button_id=button_id,
            slots=slots,
        )
        with get_connection() as conn:
            result = conn.execute(
                "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
                (static_payload["suggested_next_step"], payload.session_id),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Session not found")
        record_chat_message(
            payload.session_id,
            "assistant",
            static_payload["assistant_message"],
            static_payload["suggested_next_step"],
        )
        return ChatMessageResponse(
            assistant_message=static_payload["assistant_message"],
            buttons=[ChatButton(**button) for button in static_payload["buttons"]],
            suggested_next_step=static_payload["suggested_next_step"],
            slot_updates=static_payload["slot_updates"],
            handoff=static_payload["handoff"],
            safety=static_payload["safety"],
        )

    rag_triggered = should_trigger_rag(intent, payload.user_message)
    LOGGER.warning(
        "rag_trigger_decision intent=%s triggered=%s",
        intent or "unknown",
        rag_triggered,
    )
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
    else:
        LOGGER.warning("rag_skipped reason=not_triggered intent=%s", intent or "unknown")

    if rag_context:
        allowed_buttons = []
        LOGGER.info("rag_buttons_disabled reason=rag_context_present")

    rag_empty_factual = (
        rag_triggered and not rag_context and is_factual_question(payload.user_message)
    )
    LOGGER.info(
        "rag_context_status empty=%s length=%s",
        not bool(rag_context),
        len(rag_context),
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

    default_next_step = next_step.value

    try:
        llm_response = call_llm(messages)
    
        LOGGER.warning(
            "llm_raw_response session_id=%s response=%s",
            payload.session_id,
            llm_response,
        )

        validated = validate_or_fallback(
            llm_response,
            allowed_buttons,
            default_next_step,
            text_only=True,
        )

    except LLMClientError as exc:
        LOGGER.error(
            "llm_call_failed session_id=%s error=%s",
            payload.session_id,
            exc,
        )
        validated = build_fallback_response_with_step(default_next_step)


    next_step = default_next_step
    buttons = get_buttons_for_step(resolved_step)
    if button_id:
        buttons = get_buttons_for_step(ConversationStep(next_step))
    slot_updates = (
        build_transition_slot_updates(
            step=resolved_step,
            button_id=button_id,
            slots=slots,
        )
        if button_id
        else {}
    )
    with get_connection() as conn:
        result = conn.execute(
            "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
            (next_step, payload.session_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Session not found")

    assistant_message = normalize_llm_text(validated["assistant_message"])
    record_chat_message(payload.session_id, "assistant", assistant_message, next_step)

    return ChatMessageResponse(
        assistant_message=assistant_message,
        buttons=[ChatButton(**button) for button in serialize_buttons(buttons)],
        suggested_next_step=next_step,
        slot_updates=slot_updates,
        handoff={"requested": False},
        safety={"rag_used": bool(rag_context)},
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
    raw_step = payload.state.get("step", "UNKNOWN")
    resolved_step = normalize_step(raw_step) or ConversationStep.MAIN_MENU
    step = resolved_step.value
    raw_intent = payload.state.get("intent") or payload.context.get("intent")
    inferred_intent = None if raw_intent else classify_intent(payload.user_message)
    intent = raw_intent or inferred_intent
    source = "payload" if raw_intent else ("inferred" if inferred_intent else "none")
    LOGGER.warning("intent_selected intent=%s source=%s", intent or "unknown", source)
    record_chat_message(payload.session_id, "user", payload.user_message, step)

    slots = payload.state.get("slots")
    if not isinstance(slots, dict):
        slots = {}

    button_id = payload.state.get("button_id")
    if not isinstance(button_id, str):
        button_id = match_button_id(resolved_step, payload.user_message)

    next_step = resolve_next_step(resolved_step, button_id, intent)

    if looks_like_reader_request(payload.user_message):
        reader_payload = build_static_response(
            source_step=resolved_step,
            step=ConversationStep.OUT_OF_SCOPE_READER,
            button_id=button_id,
            slots=slots,
        )

        async def reader_event_stream() -> Any:
            with get_connection() as conn:
                result = conn.execute(
                    "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
                    (reader_payload["suggested_next_step"], payload.session_id),
                )
                if result.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Session not found")
            record_chat_message(
                payload.session_id,
                "assistant",
                reader_payload["assistant_message"],
                reader_payload["suggested_next_step"],
            )
            state_payload = {
                "step": reader_payload["suggested_next_step"],
                "slot_updates": reader_payload["slot_updates"],
                "handoff": reader_payload["handoff"],
                "safety": reader_payload["safety"],
                "suggested_next_step": reader_payload["suggested_next_step"],
                "latency_ms": 0,
            }
            yield _format_sse(
                "final",
                ChatStreamFinal(
                    assistant_message=reader_payload["assistant_message"],
                    state=state_payload,
                    buttons=[ChatButton(**button) for button in reader_payload["buttons"]],
                ).model_dump(),
            )

        return StreamingResponse(reader_event_stream(), media_type="text/event-stream")

    if is_wizard_step(resolved_step) or resolved_step == ConversationStep.BUDGET_CLIENT_TYPE:
        wizard_payload = handle_step(
            resolved_step,
            payload.user_message,
            button_id,
            slots,
        )

        async def wizard_event_stream() -> Any:
            with get_connection() as conn:
                result = conn.execute(
                    "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
                    (wizard_payload["suggested_next_step"], payload.session_id),
                )
                if result.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Session not found")
            record_chat_message(
                payload.session_id,
                "assistant",
                wizard_payload["assistant_message"],
                wizard_payload["suggested_next_step"],
            )
            state_payload = {
                "step": wizard_payload["suggested_next_step"],
                "slot_updates": wizard_payload["slot_updates"],
                "handoff": wizard_payload["handoff"],
                "safety": wizard_payload["safety"],
                "suggested_next_step": wizard_payload["suggested_next_step"],
                "latency_ms": 0,
            }
            yield _format_sse(
                "final",
                ChatStreamFinal(
                    assistant_message=wizard_payload["assistant_message"],
                    state=state_payload,
                    buttons=[ChatButton(**button) for button in wizard_payload["buttons"]],
                ).model_dump(),
            )

        return StreamingResponse(wizard_event_stream(), media_type="text/event-stream")

    if is_wizard_step(next_step):
        slot_updates = build_transition_slot_updates(
            step=resolved_step,
            button_id=button_id,
            slots=slots,
        )
        wizard_payload = build_response(
            resolved_step,
            build_wizard_prompt(next_step),
            get_buttons_for_step(next_step),
            next_step,
            slot_updates,
            handoff={"requested": False},
            safety={"rag_used": False},
        )

        async def wizard_start_stream() -> Any:
            with get_connection() as conn:
                result = conn.execute(
                    "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
                    (wizard_payload["suggested_next_step"], payload.session_id),
                )
                if result.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Session not found")
            record_chat_message(
                payload.session_id,
                "assistant",
                wizard_payload["assistant_message"],
                wizard_payload["suggested_next_step"],
            )
            state_payload = {
                "step": wizard_payload["suggested_next_step"],
                "slot_updates": wizard_payload["slot_updates"],
                "handoff": wizard_payload["handoff"],
                "safety": wizard_payload["safety"],
                "suggested_next_step": wizard_payload["suggested_next_step"],
                "latency_ms": 0,
            }
            yield _format_sse(
                "final",
                ChatStreamFinal(
                    assistant_message=wizard_payload["assistant_message"],
                    state=state_payload,
                    buttons=[ChatButton(**button) for button in wizard_payload["buttons"]],
                ).model_dump(),
            )

        return StreamingResponse(wizard_start_stream(), media_type="text/event-stream")

    if resolved_step == ConversationStep.WELCOME_SCOPE or (
        button_id and is_static_step(next_step)
    ):
        static_payload = build_static_response(
            source_step=resolved_step,
            step=next_step if resolved_step != ConversationStep.WELCOME_SCOPE else resolved_step,
            button_id=button_id,
            slots=slots,
        )

        async def static_event_stream() -> Any:
            with get_connection() as conn:
                result = conn.execute(
                    "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
                    (static_payload["suggested_next_step"], payload.session_id),
                )
                if result.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Session not found")
            record_chat_message(
                payload.session_id,
                "assistant",
                static_payload["assistant_message"],
                static_payload["suggested_next_step"],
            )
            state_payload = {
                "step": static_payload["suggested_next_step"],
                "slot_updates": static_payload["slot_updates"],
                "handoff": static_payload["handoff"],
                "safety": static_payload["safety"],
                "suggested_next_step": static_payload["suggested_next_step"],
                "latency_ms": 0,
            }
            yield _format_sse(
                "final",
                ChatStreamFinal(
                    assistant_message=static_payload["assistant_message"],
                    state=state_payload,
                    buttons=[ChatButton(**button) for button in static_payload["buttons"]],
                ).model_dump(),
            )

        return StreamingResponse(static_event_stream(), media_type="text/event-stream")

    rag_triggered = should_trigger_rag(intent, payload.user_message)
    LOGGER.warning(
        "rag_trigger_decision intent=%s triggered=%s",
        intent or "unknown",
        rag_triggered,
    )
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
    else:
        LOGGER.warning("rag_skipped reason=not_triggered intent=%s", intent or "unknown")

    if rag_context:
        allowed_buttons = []
        LOGGER.info("rag_buttons_disabled reason=rag_context_present")

    rag_empty_factual = (
        rag_triggered and not rag_context and is_factual_question(payload.user_message)
    )
    LOGGER.info(
        "rag_context_status empty=%s length=%s",
        not bool(rag_context),
        len(rag_context),
    )

    default_next_step = next_step.value

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
            validated = validate_or_fallback(
                llm_response,
                allowed_buttons,
                default_next_step,
                text_only=True,
            )
        except (LLMClientError, TimeoutError) as exc:
            llm_error = str(exc)
            validated = build_fallback_response_with_step(default_next_step)
            LOGGER.warning(
                "chat_stream_llm_error session_id=%s error=%s",
                payload.session_id,
                llm_error,
            )

        if llm_error:
            yield _format_sse("error", {"message": llm_error})

        next_step = default_next_step
        buttons = get_buttons_for_step(resolved_step)
        if button_id:
            buttons = get_buttons_for_step(ConversationStep(next_step))
        slot_updates = (
            build_transition_slot_updates(
                step=resolved_step,
                button_id=button_id,
                slots=slots,
            )
            if button_id
            else {}
        )
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

        assistant_message = normalize_llm_text(validated["assistant_message"])
        record_chat_message(payload.session_id, "assistant", assistant_message, next_step)
        for token in _tokenize_message(assistant_message):
            yield _format_sse("token", {"value": token})

        state_payload = {
            "step": next_step,
            "slot_updates": slot_updates,
            "handoff": {"requested": False},
            "safety": {"rag_used": bool(rag_context)},
            "suggested_next_step": next_step,
            "latency_ms": int((time.monotonic() - llm_start) * 1000),
        }
        yield _format_sse(
            "final",
            ChatStreamFinal(
                assistant_message=assistant_message,
                state=state_payload,
                buttons=[ChatButton(**button) for button in serialize_buttons(buttons)],
            ).model_dump(),
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
