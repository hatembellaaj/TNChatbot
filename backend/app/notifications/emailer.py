import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Iterable

LOGGER = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    pass


def _smtp_settings() -> dict:
    return {
        "host": os.getenv("SMTP_HOST"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER"),
        "password": os.getenv("SMTP_PASSWORD"),
        "from_address": os.getenv("SMTP_FROM", "no-reply@tnchatbot.local"),
        "to_address": os.getenv("LEADS_EMAIL_TO", "leads@tnchatbot.local"),
        "environment": os.getenv("APP_ENV", "development"),
    }


def send_email(subject: str, body: str, to_addrs: Iterable[str] | None = None) -> str:
    settings = _smtp_settings()
    to_addresses = list(to_addrs or [settings["to_address"]])
    environment = settings["environment"].lower()

    if not settings["host"] or environment != "production":
        LOGGER.info(
            "Email delivery mocked: subject=%s to=%s env=%s",
            subject,
            to_addresses,
            environment,
        )
        return "mocked"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["from_address"]
    message["To"] = ", ".join(to_addresses)
    message.set_content(body)

    try:
        with smtplib.SMTP(settings["host"], settings["port"]) as smtp:
            smtp.starttls()
            if settings["user"]:
                smtp.login(settings["user"], settings["password"])
            smtp.send_message(message)
    except smtplib.SMTPException as exc:
        LOGGER.exception("Email delivery failed")
        raise EmailDeliveryError("Email delivery failed") from exc

    return "sent"
