import csv
import io
import json
import os
from typing import Any, Dict, Iterable, List

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.db import get_connection

ADMIN_CONFIG_KEYS = ("audience_metrics", "offers_copy", "email_config", "sectors")


def _extract_admin_token(
    authorization: str | None, x_admin_token: str | None
) -> str | None:
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    return x_admin_token


def require_admin_token(
    authorization: str | None = Header(None),
    x_admin_token: str | None = Header(None),
) -> None:
    expected = os.getenv("ADMIN_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=500, detail="ADMIN_API_TOKEN not configured")
    token = _extract_admin_token(authorization, x_admin_token)
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token")


router = APIRouter(dependencies=[Depends(require_admin_token)])


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
