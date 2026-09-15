from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from wallabot import db

VALID_SHIPPING_FILTERS = {"any", "shipping", "inperson"}
MIN_SCAN_INTERVAL_MINUTES = 5


@dataclass
class Search:
    id: int
    user_id: int
    name: str
    category_id: int | None
    title_keywords: str
    content_keywords: str | None
    min_price: float | None
    max_price: float | None
    latitude: float | None
    longitude: float | None
    radius_km: float | None
    excluded_words: str | None
    shipping_filter: str
    search_wallapop: bool
    search_cashconverters: bool
    search_cex: bool
    search_milanuncios: bool
    scan_interval_minutes: int
    is_active: bool
    notify_enabled: bool
    last_scan_at: str | None
    last_scan_status: str | None
    last_scan_error: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Search":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            category_id=row["category_id"],
            title_keywords=row["title_keywords"],
            content_keywords=row["content_keywords"],
            min_price=row["min_price"],
            max_price=row["max_price"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            radius_km=row["radius_km"],
            excluded_words=row["excluded_words"],
            shipping_filter=row["shipping_filter"],
            search_wallapop=bool(row["search_wallapop"]),
            search_cashconverters=bool(row["search_cashconverters"]),
            search_cex=bool(row["search_cex"]),
            search_milanuncios=bool(row["search_milanuncios"]),
            scan_interval_minutes=row["scan_interval_minutes"],
            is_active=bool(row["is_active"]),
            notify_enabled=bool(row["notify_enabled"]),
            last_scan_at=row["last_scan_at"],
            last_scan_status=row["last_scan_status"],
            last_scan_error=row["last_scan_error"],
            created_at=row["created_at"],
        )

    @property
    def excluded_words_list(self) -> list[str]:
        if not self.excluded_words:
            return []
        return [w.strip().lower() for w in self.excluded_words.split(",") if w.strip()]

    @property
    def title_keywords_list(self) -> list[str]:
        return [w.strip().lower() for w in self.title_keywords.split() if w.strip()]

    @property
    def content_keywords_list(self) -> list[str]:
        if not self.content_keywords:
            return []
        return [w.strip().lower() for w in self.content_keywords.split() if w.strip()]


def matches_criteria(
    search: Search, *, title: str, description: str, price: float | None, shippable: bool | None
) -> bool:
    """Filtros de una búsqueda que se pueden evaluar sin llamar a ninguna tienda.

    Se usa tanto al escanear (contra un ítem recién llegado) como al listar
    resultados ya guardados (para que dejen de verse en cuanto se editan los
    criterios, y vuelvan a verse solos si se vuelven a ampliar — sin tener
    que "des-eliminar" nada a mano). `shippable=None` cuando el concepto de
    envío no aplica a la plataforma (tiendas con catálogo propio, no un
    mercado entre particulares).
    """
    title_lower = title.lower()
    description_lower = (description or "").lower()

    # Wallapop hace matching por relevancia contra título Y descripción, así que
    # un anuncio puede "colar" solo porque su descripción menciona palabras
    # ajenas al producto (para tener más alcance). Exigimos aquí, en local, que
    # las palabras del título estén realmente en el título del anuncio.
    title_words = search.title_keywords_list
    if title_words and not all(word in title_lower for word in title_words):
        return False

    content_words = search.content_keywords_list
    if content_words and not all(word in description_lower for word in content_words):
        return False

    excluded = search.excluded_words_list
    if excluded and (
        any(word in title_lower for word in excluded)
        or any(word in description_lower for word in excluded)
    ):
        return False

    if search.min_price is not None and (price is None or price < search.min_price):
        return False
    if search.max_price is not None and (price is None or price > search.max_price):
        return False

    if shippable is not None:
        if search.shipping_filter == "shipping" and not shippable:
            return False
        if search.shipping_filter == "inperson" and shippable:
            return False

    return True


def create_search(
    user_id: int,
    name: str,
    title_keywords: str,
    category_id: int | None = None,
    content_keywords: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    excluded_words: str | None = None,
    shipping_filter: str = "any",
    search_wallapop: bool = True,
    search_cashconverters: bool = False,
    search_cex: bool = False,
    search_milanuncios: bool = False,
    scan_interval_minutes: int = 60,
    notify_enabled: bool = True,
) -> Search:
    if shipping_filter not in VALID_SHIPPING_FILTERS:
        raise ValueError(f"shipping_filter inválido: {shipping_filter}")
    if not search_wallapop and not search_cashconverters and not search_cex and not search_milanuncios:
        raise ValueError("La búsqueda debe activar al menos una tienda")
    scan_interval_minutes = max(scan_interval_minutes, MIN_SCAN_INTERVAL_MINUTES)

    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO searches (
                user_id, name, category_id, title_keywords, content_keywords, min_price, max_price,
                latitude, longitude, radius_km, excluded_words,
                shipping_filter, search_wallapop, search_cashconverters, search_cex, search_milanuncios,
                scan_interval_minutes, notify_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, name, category_id, title_keywords, content_keywords, min_price, max_price,
                latitude, longitude, radius_km, excluded_words,
                shipping_filter, int(search_wallapop), int(search_cashconverters), int(search_cex),
                int(search_milanuncios), scan_interval_minutes, int(notify_enabled),
            ),
        )
        row = conn.execute("SELECT * FROM searches WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return Search.from_row(row)


def update_search(search_id: int, **fields) -> None:
    if not fields:
        return
    if "shipping_filter" in fields and fields["shipping_filter"] not in VALID_SHIPPING_FILTERS:
        raise ValueError(f"shipping_filter inválido: {fields['shipping_filter']}")
    if "scan_interval_minutes" in fields:
        fields["scan_interval_minutes"] = max(fields["scan_interval_minutes"], MIN_SCAN_INTERVAL_MINUTES)

    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [search_id]
    with db.get_connection() as conn:
        conn.execute(f"UPDATE searches SET {columns} WHERE id = ?", values)


def get_search(search_id: int) -> Search | None:
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
        return Search.from_row(row) if row else None


def get_search_for_user(search_id: int, user_id: int) -> Search | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM searches WHERE id = ? AND user_id = ?", (search_id, user_id)
        ).fetchone()
        return Search.from_row(row) if row else None


def list_searches_for_user(user_id: int) -> list[Search]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM searches WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
        return [Search.from_row(row) for row in rows]


def list_active_searches() -> list[Search]:
    with db.get_connection() as conn:
        rows = conn.execute("SELECT * FROM searches WHERE is_active = 1").fetchall()
        return [Search.from_row(row) for row in rows]


def set_active(search_id: int, is_active: bool) -> None:
    with db.get_connection() as conn:
        conn.execute("UPDATE searches SET is_active = ? WHERE id = ?", (int(is_active), search_id))


def delete_search(search_id: int) -> None:
    with db.get_connection() as conn:
        conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))


def record_scan_result(search_id: int, status: str, error: str | None, timestamp: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE searches SET last_scan_at = ?, last_scan_status = ?, last_scan_error = ? WHERE id = ?",
            (timestamp, status, error, search_id),
        )
