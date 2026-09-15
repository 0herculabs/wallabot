from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from wallabot import results
from wallabot.searches import get_search_for_user
from wallabot.users import User
from wallabot.web.deps import get_current_user

router = APIRouter()


def _get_owned_result_or_404(result_id: int, search_id: int, user: User) -> results.Result:
    search = get_search_for_user(search_id, user.id)
    if search is None:
        raise HTTPException(status_code=404, detail="Búsqueda no encontrada")
    result = results.get_result_for_search(result_id, search_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Resultado no encontrado")
    return result


@router.post("/searches/{search_id}/results/{result_id}/discard")
def discard(request: Request, search_id: int, result_id: int, user: User = Depends(get_current_user)):
    result = _get_owned_result_or_404(result_id, search_id, user)
    results.discard_result(result.id)
    return RedirectResponse(url=f"/searches/{search_id}", status_code=303)


@router.post("/searches/{search_id}/results/{result_id}/restore")
def restore(request: Request, search_id: int, result_id: int, user: User = Depends(get_current_user)):
    result = _get_owned_result_or_404(result_id, search_id, user)
    results.restore_result(result.id)
    return RedirectResponse(url=f"/searches/{search_id}/discarded", status_code=303)
