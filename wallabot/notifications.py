"""Notificaciones de novedades por email (SMTP) y/o Telegram.

`notify_new_results` es el único punto de entrada que usa el scanner. Solo
actúa si la propia búsqueda tiene `notify_enabled` activado; a partir de ahí
envía por cada canal que el usuario dueño tenga activado en su cuenta
(`notify_email`/`notify_telegram`) y que además esté configurado a nivel de
servidor (SMTP en `.env`, o `TELEGRAM_BOT_TOKEN` + chat_id del usuario).
`new_results` son siempre resultados recién insertados en este escaneo
(ver `results.upsert_result`), así que nunca se reenvían resultados ya
notificados en un escaneo anterior.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

import httpx

from wallabot.config import settings
from wallabot.results import Result, format_price
from wallabot.searches import Search
from wallabot.users import get_user_by_id
from wallabot.web.templating import templates

logger = logging.getLogger(__name__)

LOGO_PATH = Path(__file__).resolve().parent / "static" / "logo.png"

TELEGRAM_API_BASE = "https://api.telegram.org"


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def _telegram_configured() -> bool:
    return bool(settings.telegram_bot_token)


def _send_email(to_address: str, subject: str, plain_body: str, html_body: str | None = None) -> None:
    from_header = formataddr((settings.smtp_from or "Wallabot", settings.smtp_user))

    if html_body is None:
        msg = MIMEText(plain_body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = to_address
    else:
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = to_address

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(plain_body, "plain", "utf-8"))
        alt.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(alt)

        if LOGO_PATH.exists():
            logo = MIMEImage(LOGO_PATH.read_bytes(), _subtype="png")
            logo.add_header("Content-ID", "<logo>")
            logo.add_header("Content-Disposition", "inline", filename="logo.png")
            msg.attach(logo)

    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)


def send_test_email(to_address: str) -> None:
    """Envío de prueba para verificar la configuración SMTP (usado por la CLI)."""
    if not _smtp_configured():
        raise RuntimeError("SMTP no configurado: revisa SMTP_HOST/SMTP_USER/SMTP_PASSWORD en .env")
    _send_email(
        to_address,
        subject="Wallabot: email de prueba",
        plain_body="Si has recibido esto, la configuración SMTP de Wallabot funciona correctamente.",
    )


def _send_telegram(chat_id: str, text: str) -> None:
    response = httpx.post(
        f"{TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=15.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram devolvió un error: {payload.get('description')}")


def send_test_telegram(chat_id: str) -> None:
    """Envío de prueba para verificar el bot/chat_id de Telegram (CLI y botón de cuenta)."""
    if not _telegram_configured():
        raise RuntimeError("Telegram no configurado: revisa TELEGRAM_BOT_TOKEN en .env")
    _send_telegram(chat_id, "Si has recibido esto, la configuración de Telegram de Wallabot funciona correctamente.")


def _format_result_line(result: Result) -> str:
    price = f"{format_price(result.price)} {result.currency}" if result.price else "precio no disponible"
    return f"- {result.title} ({price})\n  {result.url}"


def _format_price_drop_line(result: Result) -> str:
    old = format_price(result.previous_price)
    new = f"{format_price(result.price)} {result.currency}" if result.price else "?"
    return f"- {result.title}: {old} -> {new}\n  {result.url}"



def notify_new_results(
    search: Search, new_results: list[Result], price_drops: list[Result] | None = None
) -> None:
    price_drops = price_drops or []
    if not new_results and not price_drops:
        return

    if not search.notify_enabled:
        return

    user = get_user_by_id(search.user_id)
    if user is None:
        return

    subject_parts = []
    if new_results:
        subject_parts.append(f"{len(new_results)} novedad(es)")
    if price_drops:
        subject_parts.append(f"{len(price_drops)} bajada(s) de precio")
    subject = f'Wallabot: {" y ".join(subject_parts)} en "{search.name}"'

    plain_lines = [f'Búsqueda "{search.name}":', ""]
    if new_results:
        plain_lines.append(f"{len(new_results)} resultado(s) nuevo(s):")
        plain_lines.extend(_format_result_line(r) for r in new_results)
        plain_lines.append("")
    if price_drops:
        plain_lines.append(f"{len(price_drops)} bajada(s) de precio:")
        plain_lines.extend(_format_price_drop_line(r) for r in price_drops)
        plain_lines.append("")
    plain_lines.append("— Wallabot")
    plain_body = "\n".join(plain_lines)

    if user.notify_email and user.email:
        if not _smtp_configured():
            logger.info(
                "Búsqueda %s ('%s'): %d nuevo(s), %d bajada(s) de precio [SMTP no configurado, sin email]",
                search.id, search.name, len(new_results), len(price_drops),
            )
        else:
            search_url = f"{settings.public_base_url}/searches/{search.id}" if settings.public_base_url else None
            html_body = templates.env.get_template("email/new_results.html").render(
                search=search, results=new_results, price_drops=price_drops, search_url=search_url,
            )
            try:
                _send_email(user.email, subject, plain_body, html_body)
                logger.info(
                    "Email enviado a %s (búsqueda %s): %d nuevo(s), %d bajada(s)",
                    user.email, search.id, len(new_results), len(price_drops),
                )
            except Exception:
                logger.exception("Fallo enviando email de novedades para la búsqueda %s", search.id)

    if user.notify_telegram and user.telegram_chat_id:
        if not _telegram_configured():
            logger.info(
                "Búsqueda %s ('%s'): %d nuevo(s), %d bajada(s) de precio [Telegram no configurado, sin aviso]",
                search.id, search.name, len(new_results), len(price_drops),
            )
        else:
            try:
                _send_telegram(user.telegram_chat_id, f"{subject}\n\n{plain_body}")
                logger.info(
                    "Telegram enviado a chat %s (búsqueda %s): %d nuevo(s), %d bajada(s)",
                    user.telegram_chat_id, search.id, len(new_results), len(price_drops),
                )
            except Exception:
                logger.exception("Fallo enviando Telegram de novedades para la búsqueda %s", search.id)
