from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from wallabot.users import authenticate
from wallabot.web.deps import get_optional_user
from wallabot.web.templating import templates

router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    if get_optional_user(request) is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = authenticate(username, password)
    if user is None:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Usuario o contraseña incorrectos"}, status_code=401
        )
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
