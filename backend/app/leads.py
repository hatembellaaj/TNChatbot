import json
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Literal, Union

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, EmailStr, Field, validator

from app.db import get_connection
from app.notifications.emailer import EmailDeliveryError, send_email

router = APIRouter()


class LeadBase(BaseModel):
    lead_type: str
    full_name: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1)
    email: EmailStr
    phone: str = Field(..., min_length=1)
    entry_path: str | None = None
    message: str | None = None

    @validator("full_name", "company", "phone")
    def normalize_required(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("This field is required.")
        return trimmed

    @validator("company")
    def require_b2b_mention(cls, value: str) -> str:
        if "b2b" not in value.lower():
            raise ValueError("Company must mention B2B.")
        return value


class StandardLead(LeadBase):
    lead_type: Literal["standard"] = "standard"


class ImmoneufLead(LeadBase):
    lead_type: Literal["immoneuf"] = "immoneuf"
    program_name: str | None = None
    project_city: str | None = None
    unit_count: int | None = Field(default=None, ge=1)
    delivery_window: str | None = None


class PremiumLead(LeadBase):
    lead_type: Literal["premium"] = "premium"
    user_count: int = Field(..., ge=1)


class PartnershipLead(LeadBase):
    lead_type: Literal["partenariat"] = "partenariat"
    priority: str = Field(..., min_length=1)


class CallbackLead(LeadBase):
    lead_type: Literal["callback"] = "callback"
    preferred_time: str | None = None


LeadCreate = Annotated[
    Union[StandardLead, ImmoneufLead, PremiumLead, PartnershipLead, CallbackLead],
    Body(discriminator="lead_type"),
]


class LeadCreateResponse(BaseModel):
    lead_id: str
    email_status: str
    export_log_id: str


def _build_extra_json(payload: LeadBase) -> Dict[str, Any]:
    base_fields = {
        "lead_type",
        "full_name",
        "company",
        "email",
        "phone",
        "entry_path",
        "message",
    }
    raw = payload.dict(exclude_none=True)
    return {key: value for key, value in raw.items() if key not in base_fields}


def _build_email_body(payload: LeadBase, extra_json: Dict[str, Any], timestamp: str) -> str:
    lines = [
        "Nouvelle demande lead.",
        f"Type: {payload.lead_type}",
        f"Nom complet: {payload.full_name}",
        f"Société: {payload.company}",
        f"Email: {payload.email}",
        f"Téléphone: {payload.phone}",
        "B2B: oui (mention dans société)",
    ]

    if payload.entry_path:
        lines.append(f"Entry path: {payload.entry_path}")
    if payload.message:
        lines.append(f"Message: {payload.message}")
    if extra_json:
        lines.append(f"Champs spécifiques: {json.dumps(extra_json, ensure_ascii=False)}")
    lines.append(f"Horodatage: {timestamp}")
    return "\n".join(lines)


def _build_wizard_email_body(
    *,
    full_name: str,
    company: str,
    email: str,
    phone: str,
    extra_json: Dict[str, Any],
    timestamp: str,
) -> str:
    lines = [
        "Nouveau lead issu du wizard.",
        f"Nom complet: {full_name}",
        f"Société: {company}",
        f"Email: {email}",
        f"Téléphone: {phone}",
    ]
    if extra_json:
        lines.append(f"Champs wizard: {json.dumps(extra_json, ensure_ascii=False)}")
    lines.append(f"Horodatage: {timestamp}")
    return "\n".join(lines)


@router.post("/api/leads", response_model=LeadCreateResponse)
def create_lead(payload: LeadCreate) -> LeadCreateResponse:
    extra_json = _build_extra_json(payload)
    timestamp = datetime.now(timezone.utc).isoformat()
    subject = f"[CHATBOT ANNONCEURS] Nouvelle demande – {payload.company}"
    body = _build_email_body(payload, extra_json, timestamp)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO leads (full_name, company, email, phone, entry_path, lead_type, extra_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    payload.full_name,
                    payload.company,
                    payload.email,
                    payload.phone,
                    payload.entry_path,
                    payload.lead_type,
                    json.dumps(extra_json),
                ),
            )
            lead_id = cur.fetchone()[0]

            try:
                email_status = send_email(subject, body)
            except EmailDeliveryError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            cur.execute(
                """
                INSERT INTO lead_events (lead_id, event_type, payload)
                VALUES (%s, %s, %s)
                """,
                (
                    lead_id,
                    "EMAIL_SENT",
                    json.dumps({"status": email_status, "subject": subject}),
                ),
            )

            cur.execute(
                """
                INSERT INTO export_logs (export_type, status, details)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    "leads",
                    "queued",
                    json.dumps({"lead_id": str(lead_id), "lead_type": payload.lead_type}),
                ),
            )
            export_log_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO lead_events (lead_id, event_type, payload)
                VALUES (%s, %s, %s)
                """,
                (
                    lead_id,
                    "EXPORTED",
                    json.dumps({"export_log_id": str(export_log_id), "status": "queued"}),
                ),
            )

    return LeadCreateResponse(
        lead_id=str(lead_id),
        email_status=email_status,
        export_log_id=str(export_log_id),
    )


def create_wizard_lead(slots: Dict[str, str]) -> None:
    first_name = slots.get("lead_first_name", "").strip()
    last_name = slots.get("lead_last_name", "").strip()
    company = slots.get("lead_company", "").strip()
    email = slots.get("lead_email", "").strip()
    phone = slots.get("lead_phone", "").strip()
    if not all([first_name, last_name, company, email, phone]):
        raise ValueError("Missing required wizard lead fields.")

    full_name = f"{first_name} {last_name}".strip()
    extra_json = {
        "client_type": slots.get("qual_client_type"),
        "objective": slots.get("qual_objective"),
        "budget": slots.get("qual_budget"),
    }
    timestamp = datetime.now(timezone.utc).isoformat()
    subject = f"[CHATBOT ANNONCEURS] Nouveau lead – {company}"
    body = _build_wizard_email_body(
        full_name=full_name,
        company=company,
        email=email,
        phone=phone,
        extra_json=extra_json,
        timestamp=timestamp,
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO leads (full_name, company, email, phone, entry_path, lead_type, extra_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    full_name,
                    company,
                    email,
                    phone,
                    "wizard",
                    "wizard",
                    json.dumps(extra_json),
                ),
            )
            lead_id = cur.fetchone()[0]

            email_status = send_email(subject, body)

            cur.execute(
                """
                INSERT INTO lead_events (lead_id, event_type, payload)
                VALUES (%s, %s, %s)
                """,
                (
                    lead_id,
                    "EMAIL_SENT",
                    json.dumps({"status": email_status, "subject": subject}),
                ),
            )

            cur.execute(
                """
                INSERT INTO export_logs (export_type, status, details)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    "leads",
                    "queued",
                    json.dumps({"lead_id": str(lead_id), "lead_type": "wizard"}),
                ),
            )
            export_log_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO lead_events (lead_id, event_type, payload)
                VALUES (%s, %s, %s)
                """,
                (
                    lead_id,
                    "EXPORTED",
                    json.dumps({"export_log_id": str(export_log_id), "status": "queued"}),
                ),
            )
