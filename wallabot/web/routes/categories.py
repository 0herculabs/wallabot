from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from wallabot.categories import create_category, delete_category, get_category_for_user
from wallabot.users import User
from wallabot.web.deps import get_current_user

router = APIRouter()


@router.post("/categories")
def create_category_submit(request: Request, user: User = Depends(get_current_user), name: str = Form(...)):
    if name.strip():
        create_category(user.id, name)
    return RedirectResponse(url="/", status_code=303)


@router.post("/categories/{category_id}/delete")
def delete_category_submit(request: Request, category_id: int, user: User = Depends(get_current_user)):
    category = get_category_for_user(category_id, user.id)
    if category is None:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    delete_category(category_id)
    return RedirectResponse(url="/", status_code=303)
