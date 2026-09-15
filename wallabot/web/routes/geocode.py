from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from wallabot import geocode as geocode_module
from wallabot.users import User
from wallabot.web.deps import get_current_user

router = APIRouter()


@router.get("/geocode/suggest")
def geocode_suggest(q: str = Query(..., min_length=2), user: User = Depends(get_current_user)):
    results = geocode_module.search(q, limit=8)
    return [
        {"lat": r.latitude, "lon": r.longitude, "display_name": r.display_name}
        for r in results
    ]
