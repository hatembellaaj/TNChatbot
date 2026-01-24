import csv
import io
import json
import os
from typing import Any, Dict, Iterable, List

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.db import get_connection

ADMIN_CONFIG_KEYS = ("audience_metrics", "offers_copy", "email_config", "sectors")


def _get_admin_password() -> str:
    expected = os.getenv("ADMIN_PASSWORD")
    if not expected:
        raise HTTPException(status_code=500, detail="ADMIN_PASSWORD not configured")
    return expected


def _ensure_admin_password(password: str | None) -> None:
    expected = _get_admin_password()
    if not password or password != expected:
        raise HTTPException(status_code=401, detail="Invalid admin password")


def require_admin_password(
    x_admin_password: str | None = Header(None),
) -> None:
    _ensure_admin_password(x_admin_password)


auth_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_admin_password)])


@auth_router.post("/api/admin/login")
def login_admin(payload: Dict[str, str] = Body(...)) -> Dict[str, bool]:
    _ensure_admin_password(payload.get("password"))
    return {"ok": True}


def load_admin_config(keys: Iterable[str] = ADMIN_CONFIG_KEYS) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    keys_list = list(keys)
    if not keys_list:
        return config
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT key, value FROM admin_config WHERE key = ANY(%s)",
                (keys_list,),
            )
            for key, value in cur.fetchall():
                config[key] = value
    return config


def _upsert_config(key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_config (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (key, json.dumps(payload)),
            )
    return payload


def _get_config(key: str) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM admin_config WHERE key = %s", (key,))
            row = cur.fetchone()
            if not row:
                return {}
            return row[0]


@router.get("/api/admin/audience-metrics")
def get_audience_metrics() -> Dict[str, Any]:
    return {"key": "audience_metrics", "value": _get_config("audience_metrics")}


@router.put("/api/admin/audience-metrics")
def put_audience_metrics(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return {"key": "audience_metrics", "value": _upsert_config("audience_metrics", payload)}


@router.get("/api/admin/offers-copy")
def get_offers_copy() -> Dict[str, Any]:
    return {"key": "offers_copy", "value": _get_config("offers_copy")}


@router.put("/api/admin/offers-copy")
def put_offers_copy(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return {"key": "offers_copy", "value": _upsert_config("offers_copy", payload)}


@router.get("/api/admin/email-config")
def get_email_config() -> Dict[str, Any]:
    return {"key": "email_config", "value": _get_config("email_config")}


@router.put("/api/admin/email-config")
def put_email_config(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return {"key": "email_config", "value": _upsert_config("email_config", payload)}


@router.get("/api/admin/sectors")
def get_sectors() -> Dict[str, Any]:
    return {"key": "sectors", "value": _get_config("sectors")}


@router.put("/api/admin/sectors")
def put_sectors(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return {"key": "sectors", "value": _upsert_config("sectors", payload)}


@router.get("/api/admin/leads")
def get_leads(format: str | None = Query(default=None)) -> Any:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, full_name, company, email, phone, entry_path, lead_type,
                       extra_json, created_at
                FROM leads
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()

    leads: List[Dict[str, Any]] = []
    for row in rows:
        (
            lead_id,
            full_name,
            company,
            email,
            phone,
            entry_path,
            lead_type,
            extra_json,
            created_at,
        ) = row
        leads.append(
            {
                "id": str(lead_id),
                "full_name": full_name,
                "company": company,
                "email": email,
                "phone": phone,
                "entry_path": entry_path,
                "lead_type": lead_type,
                "extra_json": extra_json or {},
                "created_at": created_at.isoformat() if created_at else None,
            }
        )

    if format and format.lower() == "csv":
        buffer = io.StringIO()
        fieldnames = [
            "id",
            "full_name",
            "company",
            "email",
            "phone",
            "entry_path",
            "lead_type",
            "extra_json",
            "created_at",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for lead in leads:
            row = dict(lead)
            row["extra_json"] = json.dumps(row["extra_json"], ensure_ascii=False)
            writer.writerow(row)
        buffer.seek(0)
        headers = {"Content-Disposition": "attachment; filename=leads.csv"}
        return StreamingResponse(buffer, media_type="text/csv", headers=headers)

    return {"count": len(leads), "items": leads}


@router.get("/api/admin/overview")
def get_overview() -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chat_sessions")
            sessions_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM chat_messages")
            messages_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM leads")
            leads_count = cur.fetchone()[0]

    return {
        "sessions": sessions_count,
        "messages": messages_count,
        "leads": leads_count,
    }


@router.get("/api/admin/conversations")
def get_conversations(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chat_sessions")
            total = cur.fetchone()[0]
            cur.execute(
                """
                SELECT session_id, step, created_at
                FROM chat_sessions
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            sessions = cur.fetchall()

            session_ids = [row[0] for row in sessions]
            messages_by_session: Dict[str, List[Dict[str, Any]]] = {
                str(session_id): [] for session_id in session_ids
            }
            if session_ids:
                cur.execute(
                    """
                    SELECT session_id, role, content, step, created_at
                    FROM chat_messages
                    WHERE session_id = ANY(%s)
                    ORDER BY created_at ASC
                    """,
                    (session_ids,),
                )
                for session_id, role, content, step, created_at in cur.fetchall():
                    messages_by_session[str(session_id)].append(
                        {
                            "role": role,
                            "content": content,
                            "step": step,
                            "created_at": created_at.isoformat()
                            if created_at
                            else None,
                        }
                    )

    items = [
        {
            "session_id": str(session_id),
            "step": step,
            "created_at": created_at.isoformat() if created_at else None,
            "messages": messages_by_session.get(str(session_id), []),
        }
        for session_id, step, created_at in sessions
    ]
    return {"total": total, "count": len(items), "items": items}
