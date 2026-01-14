import os
import uuid
from typing import Any, Dict, List

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

app = FastAPI(title="TNChatbot API")


class ChatSessionCreateResponse(BaseModel):
    session_id: str


class ChatState(BaseModel):
    step: str


class ChatContext(BaseModel):
    page: str | None = None


class ChatMessageRequest(BaseModel):
    session_id: str
    user_message: str
    state: ChatState
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatButton(BaseModel):
    id: str
    label: str


class ChatMessageResponse(BaseModel):
    assistant_message: str
    state: ChatState
    buttons: List[ChatButton]


def get_connection() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


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


@app.on_event("startup")
def on_startup() -> None:
    initialize_db()


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
    next_step = "MAIN_MENU"
    with get_connection() as conn:
        result = conn.execute(
            "UPDATE chat_sessions SET step = %s WHERE session_id = %s",
            (next_step, payload.session_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Session not found")

    response = ChatMessageResponse(
        assistant_message=(
            "Bonjour ! Voici ce que je peux vous proposer pour commencer."
        ),
        state=ChatState(step=next_step),
        buttons=[
            ChatButton(id="M_AUDIENCE", label="📊 Découvrir notre audience"),
        ],
    )
    return response
