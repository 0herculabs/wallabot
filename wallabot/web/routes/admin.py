from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from wallabot.users import (
    User,
    UsernameTakenError,
    create_user,
    delete_user,
    list_users,
    set_active,
    set_password,
)
from wallabot.web.deps import require_admin
from wallabot.web.templating import templates

router = APIRouter()


@router.get("/admin/users")
def list_users_page(request: Request, admin: User = Depends(require_admin)):
    return templates.TemplateResponse(
        request, "admin_users.html", {"user": admin, "users": list_users(), "error": None}
    )


@router.post("/admin/users")
def create_user_submit(
    request: Request,
    admin: User = Depends(require_admin),
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(""),
    is_admin: bool = Form(False),
):
    try:
        create_user(username=username, password=password, email=email or None, is_admin=is_admin)
    except UsernameTakenError as exc:
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            {"user": admin, "users": list_users(), "error": str(exc)},
            status_code=400,
        )
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{target_user_id}/toggle")
def toggle_user(request: Request, target_user_id: int, admin: User = Depends(require_admin)):
    users = {u.id: u for u in list_users()}
    target = users.get(target_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    set_active(target_user_id, not target.is_active)
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{target_user_id}/password")
def change_password(
    request: Request,
    target_user_id: int,
    admin: User = Depends(require_admin),
    new_password: str = Form(...),
):
    set_password(target_user_id, new_password)
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{target_user_id}/delete")
def delete_user_submit(request: Request, target_user_id: int, admin: User = Depends(require_admin)):
    if target_user_id == admin.id:
        return RedirectResponse(url="/admin/users", status_code=303)
    delete_user(target_user_id)
    return RedirectResponse(url="/admin/users", status_code=303)
