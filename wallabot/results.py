from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, TYPE_CHECKING

from wallabot import db

if TYPE_CHECKING:
    from wallabot.searches import Search

SortMode = Literal["newest", "oldest", "price_asc", "price_desc", "distance"]
VALID_SORT_MODES = {"newest", "oldest", "price_asc", "price_desc", "distance"}
VALID_PLATFORMS = {"wallapop", "cashconverters", "cex", "milanuncios"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def format_price(value: float | None) -> str:
    """Muestra decimales solo cuando aportan información (19.99 -> "19.99", 20.0 -> "20")."""
    if value is None:
        return "?"
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _sort_results(
    rows: list["Result"], sort: SortMode, origin: tuple[float, float] | None
) -> list["Result"]:
    if sort == "oldest":
        return sorted(rows, key=lambda r: r.first_seen_at)
    if sort == "price_asc":
        return sorted(rows, key=lambda r: (r.price is None, r.price))
    if sort == "price_desc":
        return sorted(rows, key=lambda r: (r.price is None, -r.price if r.price is not None else 0))
    if sort == "distance" and origin is not None:
        olat, olon = origin

        def distance_key(r: "Result") -> tuple[bool, float]:
            if r.latitude is None or r.longitude is None:
                return (True, 0.0)
            return (False, _haversine_km(olat, olon, r.latitude, r.longitude))

        return sorted(rows, key=distance_key)
    # "newest" (por defecto) ya viene de la consulta SQL ordenado por first_seen_at DESC.
    return rows


@dataclass
class Result:
    id: int
    search_id: int
    platform: str
    item_id: str
    title: str
    description: str | None
    price: float | None
    previous_price: float | None
    currency: str | None
    url: str
    image_url: str | None
    location: str | None
    latitude: float | None
    longitude: float | None
    shipping_allowed: bool
    published_at: str | None
    first_seen_at: str
    last_seen_at: str
    last_checked_at: str | None
    is_unseen: bool
    is_sold: bool
    is_reserved: bool
    discarded: bool
    discarded_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Result":
        return cls(
            id=row["id"],
            search_id=row["search_id"],
            platform=row["platform"],
            item_id=row["item_id"],
            title=row["title"],
            description=row["description"],
            price=row["price"],
            previous_price=row["previous_price"],
            currency=row["currency"],
            url=row["url"],
            image_url=row["image_url"],
            location=row["location"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            shipping_allowed=bool(row["shipping_allowed"]),
            published_at=row["published_at"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            last_checked_at=row["last_checked_at"],
            is_unseen=bool(row["is_unseen"]),
            is_sold=bool(row["is_sold"]),
            is_reserved=bool(row["is_reserved"]),
            discarded=bool(row["discarded"]),
            discarded_at=row["discarded_at"],
        )


@dataclass
class UpsertOutcome:
    is_new: bool
    result_id: int
    price_dropped: bool = False
    old_price: float | None = None
    new_price: float | None = None


def upsert_result(
    search_id: int,
    platform: str,
    item_id: str,
    title: str,
    description: str | None,
    price: float | None,
    currency: str | None,
    url: str,
    image_url: str | None,
    location: str | None,
    shipping_allowed: bool,
    published_at: str | None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> UpsertOutcome:
    """Inserta el anuncio si es nuevo para esta búsqueda; si ya existía, actualiza
    last_seen_at y detecta cambios de precio (subida o bajada, se guardan ambos
    para poder mostrar "antes/ahora"; solo las bajadas se marcan como novedad)."""
    now = _now()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO results (
                search_id, platform, item_id, title, description, price, currency, url,
                image_url, location, latitude, longitude, shipping_allowed, published_at,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                search_id, platform, item_id, title, description, price, currency, url,
                image_url, location, latitude, longitude, int(shipping_allowed), published_at, now, now,
            ),
        )
        if cursor.rowcount == 0:
            row = conn.execute(
                "SELECT id, price FROM results WHERE search_id = ? AND item_id = ?",
                (search_id, item_id),
            ).fetchone()
            old_price = row["price"]
            price_changed = price is not None and old_price is not None and price != old_price
            price_dropped = price_changed and price < old_price

            if price_changed:
                conn.execute(
                    """
                    UPDATE results
                    SET last_seen_at = ?, is_reserved = 0, previous_price = ?, price = ?, image_url = ?,
                        is_unseen = CASE WHEN ? THEN 1 ELSE is_unseen END
                    WHERE search_id = ? AND item_id = ?
                    """,
                    (now, old_price, price, image_url, price_dropped, search_id, item_id),
                )
            else:
                # Si estaba marcado como reservado y ahora vuelve a aparecer disponible
                # (Wallapop lo devuelve sin reserved.flag), se desmarca automáticamente.
                # `image_url` también se refresca aquí: la URL de un anuncio puede caducar
                # o cambiar de formato (p. ej. un cambio en las reglas de tamaño del CDN)
                # sin que cambie el precio.
                conn.execute(
                    "UPDATE results SET last_seen_at = ?, is_reserved = 0, image_url = ? WHERE search_id = ? AND item_id = ?",
                    (now, image_url, search_id, item_id),
                )
            return UpsertOutcome(
                is_new=False, result_id=row["id"], price_dropped=price_dropped,
                old_price=old_price, new_price=price,
            )
        return UpsertOutcome(is_new=True, result_id=cursor.lastrowid)


def _platform_clause(platforms: set[str] | None) -> tuple[str, list[str]]:
    if not platforms or platforms >= VALID_PLATFORMS:
        return "", []
    placeholders = ", ".join("?" for _ in platforms)
    return f" AND platform IN ({placeholders})", list(platforms)


def list_active_results(
    search_id: int,
    sort: SortMode = "newest",
    origin: tuple[float, float] | None = None,
    platforms: set[str] | None = None,
    search: "Search | None" = None,
) -> list[Result]:
    """Resultados activos (no descartados por el usuario, ni vendidos/reservados).

    Si se pasa `search`, además se reevalúan en vivo sus criterios actuales
    (precio, título, contenido, palabras excluidas, envío) contra cada
    resultado guardado: uno que dejó de encajar simplemente deja de listarse
    aquí, y en cuanto se amplíen los criterios de nuevo vuelve a aparecer
    solo, sin haber tenido que "eliminarlo"/"restaurarlo" a mano.
    """
    clause, extra_params = _platform_clause(platforms)
    with db.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM results
            WHERE search_id = ? AND discarded = 0 AND is_sold = 0 AND is_reserved = 0{clause}
            ORDER BY first_seen_at DESC
            """,
            (search_id, *extra_params),
        ).fetchall()
        result_list = [Result.from_row(row) for row in rows]

    if search is not None:
        from wallabot.searches import matches_criteria

        result_list = [
            r for r in result_list
            if matches_criteria(
                search, title=r.title, description=r.description or "", price=r.price,
                shippable=(r.shipping_allowed if r.platform == "wallapop" else None),
            )
        ]

    return _sort_results(result_list, sort, origin)


def list_discarded_results(
    search_id: int,
    sort: SortMode = "newest",
    origin: tuple[float, float] | None = None,
    platforms: set[str] | None = None,
) -> list[Result]:
    clause, extra_params = _platform_clause(platforms)
    with db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM results WHERE search_id = ? AND discarded = 1{clause} ORDER BY discarded_at DESC",
            (search_id, *extra_params),
        ).fetchall()
        return _sort_results([Result.from_row(row) for row in rows], sort, origin)


def list_unseen_for_user(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    with db.get_connection() as conn:
        return conn.execute(
            """
            SELECT r.*, s.name AS search_name
            FROM results r
            JOIN searches s ON s.id = r.search_id
            WHERE s.user_id = ? AND r.discarded = 0 AND r.is_sold = 0 AND r.is_reserved = 0 AND r.is_unseen = 1
            ORDER BY r.first_seen_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()


def count_unseen_for_user(user_id: int) -> int:
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM results r
            JOIN searches s ON s.id = r.search_id
            WHERE s.user_id = ? AND r.discarded = 0 AND r.is_sold = 0 AND r.is_reserved = 0 AND r.is_unseen = 1
            """,
            (user_id,),
        ).fetchone()
        return row["n"]


def count_unseen(search_id: int, search: "Search | None" = None) -> int:
    if search is not None:
        return sum(1 for r in list_active_results(search_id, search=search) if r.is_unseen)
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM results
            WHERE search_id = ? AND discarded = 0 AND is_sold = 0 AND is_reserved = 0 AND is_unseen = 1
            """,
            (search_id,),
        ).fetchone()
        return row["n"]


def mark_seen(search_id: int) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE results SET is_unseen = 0 WHERE search_id = ? AND is_unseen = 1", (search_id,)
        )


def get_result_for_search(result_id: int, search_id: int) -> Result | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM results WHERE id = ? AND search_id = ?", (result_id, search_id)
        ).fetchone()
        return Result.from_row(row) if row else None


def find_by_item_id(search_id: int, platform: str, item_id: str) -> Result | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM results WHERE search_id = ? AND platform = ? AND item_id = ?",
            (search_id, platform, item_id),
        ).fetchone()
        return Result.from_row(row) if row else None


def mark_reserved(result_id: int) -> None:
    with db.get_connection() as conn:
        conn.execute("UPDATE results SET is_reserved = 1, last_checked_at = ? WHERE id = ?", (_now(), result_id))


def discard_result(result_id: int) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE results SET discarded = 1, discarded_at = ? WHERE id = ?", (_now(), result_id)
        )


def restore_result(result_id: int) -> None:
    with db.get_connection() as conn:
        conn.execute("UPDATE results SET discarded = 0, discarded_at = NULL WHERE id = ?", (result_id,))


def results_needing_recheck(search_id: int, platform: str, seen_item_ids: set[str], limit: int) -> list[Result]:
    """Resultados activos (de una plataforma dada) que no aparecieron en el escaneo
    actual y llevan más tiempo sin revalidar."""
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM results
            WHERE search_id = ? AND platform = ? AND discarded = 0 AND is_sold = 0 AND is_reserved = 0
            ORDER BY COALESCE(last_checked_at, '') ASC
            """,
            (search_id, platform),
        ).fetchall()
    candidates = [Result.from_row(row) for row in rows if row["item_id"] not in seen_item_ids]
    return candidates[:limit]


def mark_checked(result_id: int, still_alive: bool) -> None:
    now = _now()
    with db.get_connection() as conn:
        if still_alive:
            conn.execute("UPDATE results SET last_checked_at = ? WHERE id = ?", (now, result_id))
        else:
            conn.execute(
                "UPDATE results SET last_checked_at = ?, is_sold = 1 WHERE id = ?", (now, result_id)
            )
