from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from wallabot.config import settings
from wallabot.results import format_price

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_LOCAL_TZ = ZoneInfo(settings.timezone)


def friendly_datetime(value: str | None) -> str:
    """Convierte un timestamp ISO en UTC (como se guardan en BD) a hora local legible."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(_LOCAL_TZ).strftime("%d/%m/%Y %H:%M")


templates.env.filters["friendly_datetime"] = friendly_datetime
templates.env.filters["price"] = format_price
