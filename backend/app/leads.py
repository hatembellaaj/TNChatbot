import json
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Literal, Union

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, EmailStr, Field, validator

from app.db import get_connection
from app.notifications.emailer import build_lead_body, build_lead_subject, EmailDeliveryError, send_email

router = APIRouter()

SECTOR_OPTIONS = {
    "Banque",
    "Télécom",
    "Immobilier",
    "Retail",
    "Industrie",
    "Services",
    "Institution",
    "Autre",
}


class LeadBase(BaseModel):
    lead_type: str
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1)
    email: EmailStr
    phone: str = Field(..., min_length=1)
    job_title: str | None = None
    sector: str | None = None
    need_type: str | None = None
    budget_range: str | None = None
    entry_path: str | None = None
    message: str | None = None

    @validator("first_name", "last_name", "company", "phone")
    def normalize_required(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("This field is required.")
        return trimmed

    @validator("sector")
    def validate_sector(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if trimmed not in SECTOR_OPTIONS:
            raise ValueError("Invalid sector value.")
        return trimmed


class StandardLead(LeadBase):
    lead_type: Literal["standard"] = "standard"


class ImmoneufLead(LeadBase):
    lead_type: Literal["immoneuf"] = "immoneuf"
    project_cities: str | None = None
    project_types: str | None = None
    projects_count: int | None = Field(default=None, ge=1)
    marketing_period: str | None = None


class PremiumLead(LeadBase):
    lead_type: Literal["premium"] = "premium"
    estimated_users: int = Field(..., ge=1)


class PartnershipLead(LeadBase):
    lead_type: Literal["partnership"] = "partnership"
    partnership_priority: str = Field(..., min_length=1)


class CallbackLead(LeadBase):
    lead_type: Literal["callback"] = "callback"


LeadCreate = Annotated[
    Union[StandardLead, ImmoneufLead, PremiumLead, PartnershipLead, CallbackLead],
    Body(discriminator="lead_type"),
]


class LeadCreateResponse(BaseModel):
    lead_id: str
    email_status: str
    export_log_id: str


def _build_full_name(payload: LeadBase) -> str:
    return f"{payload.first_name} {payload.last_name}".strip()


def _build_extra_json(payload: LeadBase) -> Dict[str, Any]:
    base_fields = {
        "lead_type",
        "first_name",
        "last_name",
        "company",
        "email",
        "phone",
        "job_title",
        "sector",
        "need_type",
        "budget_range",
        "entry_path",
        "message",
    }
    raw = payload.dict(exclude_none=True)
    return {key: value for key, value in raw.items() if key not in base_fields}


def _build_email_fields(payload: LeadBase, extra_json: Dict[str, Any]) -> Dict[str, Any]:
    fields = {
        "Type": payload.lead_type,
        "Prénom": payload.first_name,
        "Nom": payload.last_name,
        "Société": payload.company,
        "Email": payload.email,
        "Téléphone": payload.phone,
        "Poste": payload.job_title or "",
        "Secteur": payload.sector or "",
        "Besoin": payload.need_type or "",
        "Budget": payload.budget_range or "",
        "Message": payload.message or "",
    }
    if extra_json:
        fields["Champs spécifiques"] = json.dumps(extra_json, ensure_ascii=False)
    return fields


@router.post("/api/leads", response_model=LeadCreateResponse)
def create_lead(payload: LeadCreate) -> LeadCreateResponse:
    extra_json = _build_extra_json(payload)
    timestamp = datetime.now(timezone.utc).isoformat()
    subject = build_lead_subject(payload.company)
    body = build_lead_body(
        _build_email_fields(payload, extra_json),
        payload.entry_path,
        timestamp,
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
                    _build_full_name(payload),
                    payload.company,
                    payload.email,
                    payload.phone,
                    payload.entry_path,
                    payload.lead_type,
                    json.dumps(
                        {
                            "job_title": payload.job_title,
                            "sector": payload.sector,
                            "need_type": payload.need_type,
                            "budget_range": payload.budget_range,
                            "message": payload.message,
                            **extra_json,
                        }
                    ),
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
    first_name = slots.get("first_name", "").strip()
    last_name = slots.get("last_name", "").strip()
    company = slots.get("company", "").strip()
    email = slots.get("email", "").strip()
    phone = slots.get("phone", "").strip()
    if not all([first_name, last_name, company, email, phone]):
        raise ValueError("Missing required wizard lead fields.")

    lead_type = slots.get("lead_type", "standard")
    entry_path = slots.get("entry_path")

    extra_json = {
        "client_type": slots.get("client_type"),
        "objective": slots.get("objective"),
        "budget_range": slots.get("budget_range"),
        "job_title": slots.get("job_title"),
        "sector": slots.get("sector"),
        "need_type": slots.get("need_type"),
        "message": slots.get("message"),
        "project_cities": slots.get("project_cities"),
        "project_types": slots.get("project_types"),
        "projects_count": slots.get("projects_count"),
        "marketing_period": slots.get("marketing_period"),
        "estimated_users": slots.get("estimated_users"),
        "partnership_priority": slots.get("partnership_priority"),
    }
    timestamp = datetime.now(timezone.utc).isoformat()
    subject = build_lead_subject(company)
    body = build_lead_body(
        {
            "Type": lead_type,
            "Prénom": first_name,
            "Nom": last_name,
            "Société": company,
            "Email": email,
            "Téléphone": phone,
            "Poste": slots.get("job_title", ""),
            "Secteur": slots.get("sector", ""),
            "Besoin": slots.get("need_type", ""),
            "Budget": slots.get("budget_range", ""),
            "Message": slots.get("message", ""),
            "Champs spécifiques": json.dumps(extra_json, ensure_ascii=False),
        },
        entry_path,
        timestamp,
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
                    f"{first_name} {last_name}".strip(),
                    company,
                    email,
                    phone,
                    entry_path,
                    lead_type,
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
                    json.dumps({"lead_id": str(lead_id), "lead_type": lead_type}),
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
