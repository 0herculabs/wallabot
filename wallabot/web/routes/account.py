from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request

from wallabot import notifications
from wallabot.users import User, authenticate, set_email, set_notify_email, set_password, set_telegram
from wallabot.web.deps import get_current_user
from wallabot.web.templating import templates

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/account")
def account_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request, "account.html", {"user": user, "message": None, "error": None})


@router.post("/account")
def update_account(
    request: Request,
    user: User = Depends(get_current_user),
    email: str = Form(""),
    notify_email: bool = Form(False),
):
    email = email.strip() or None
    set_email(user.id, email)
    set_notify_email(user.id, notify_email)
    updated = User(**{**user.__dict__, "email": email, "notify_email": notify_email})
    return templates.TemplateResponse(
        request, "account.html", {"user": updated, "message": "Preferencias guardadas.", "error": None}
    )


@router.post("/account/email/test")
def test_account_email(request: Request, user: User = Depends(get_current_user)):
    if not user.email:
        return templates.TemplateResponse(
            request,
            "account.html",
            {"user": user, "message": None, "error": "Guarda antes un email."},
            status_code=400,
        )
    try:
        notifications.send_test_email(user.email)
        message = "Email de prueba enviado. Revisa tu bandeja de entrada (y spam)."
        error = None
    except Exception as exc:
        logger.exception("Fallo enviando email de prueba para el usuario %s", user.id)
        message = None
        error = f"No se ha podido enviar el email de prueba: {exc}"
    return templates.TemplateResponse(
        request, "account.html", {"user": user, "message": message, "error": error}
    )


@router.post("/account/telegram")
def update_account_telegram(
    request: Request,
    user: User = Depends(get_current_user),
    telegram_chat_id: str = Form(""),
    notify_telegram: bool = Form(False),
):
    telegram_chat_id = telegram_chat_id.strip() or None
    set_telegram(user.id, telegram_chat_id, notify_telegram)
    updated = User(**{**user.__dict__, "telegram_chat_id": telegram_chat_id, "notify_telegram": notify_telegram})
    return templates.TemplateResponse(
        request, "account.html", {"user": updated, "message": "Preferencias guardadas.", "error": None}
    )


@router.post("/account/telegram/test")
def test_account_telegram(request: Request, user: User = Depends(get_current_user)):
    if not user.telegram_chat_id:
        return templates.TemplateResponse(
            request,
            "account.html",
            {"user": user, "message": None, "error": "Guarda antes un chat_id de Telegram."},
            status_code=400,
        )
    try:
        notifications.send_test_telegram(user.telegram_chat_id)
        message = "Mensaje de prueba enviado. Revisa tu chat de Telegram."
        error = None
    except Exception as exc:
        logger.exception("Fallo enviando Telegram de prueba para el usuario %s", user.id)
        message = None
        error = f"No se ha podido enviar el mensaje de prueba: {exc}"
    return templates.TemplateResponse(
        request, "account.html", {"user": user, "message": message, "error": error}
    )


@router.post("/account/password")
def update_account_password(
    request: Request,
    user: User = Depends(get_current_user),
    current_password: str = Form(...),
    new_password: str = Form(...),
):
    if authenticate(user.username, current_password) is None:
        return templates.TemplateResponse(
            request,
            "account.html",
            {"user": user, "message": None, "error": "La contraseña actual no es correcta."},
            status_code=400,
        )
    set_password(user.id, new_password)
    return templates.TemplateResponse(
        request, "account.html", {"user": user, "message": "Contraseña actualizada.", "error": None}
    )
