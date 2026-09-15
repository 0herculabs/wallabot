from __future__ import annotations

from fastapi import APIRouter, Depends

from wallabot import results
from wallabot.users import User
from wallabot.web.deps import get_current_user

router = APIRouter()


@router.get("/notifications")
def get_notifications(user: User = Depends(get_current_user)):
    count = results.count_unseen_for_user(user.id)
    rows = results.list_unseen_for_user(user.id, limit=20)
    items = [
        {
            "search_id": row["search_id"],
            "search_name": row["search_name"],
            "result_id": row["id"],
            "platform": row["platform"],
            "title": row["title"],
            "price": row["price"],
            "currency": row["currency"],
            "image_url": row["image_url"],
            "first_seen_at": row["first_seen_at"],
        }
        for row in rows
    ]
    return {"count": count, "items": items}
