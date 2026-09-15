"""Categorías de búsquedas: agrupación puramente organizativa por usuario, sin
ningún efecto sobre el escaneo ni sobre los criterios de una búsqueda.

Toda búsqueda sin categoría asignada (`searches.category_id IS NULL`) vive en
"Sin categoría": no es una fila real de `search_categories`, es simplemente
el estado por defecto, así que no se puede renombrar ni borrar.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from wallabot import db


@dataclass
class Category:
    id: int
    user_id: int
    name: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Category":
        return cls(id=row["id"], user_id=row["user_id"], name=row["name"], created_at=row["created_at"])


def create_category(user_id: int, name: str) -> Category:
    name = name.strip()
    if not name:
        raise ValueError("El nombre de la categoría no puede estar vacío")
    with db.get_connection() as conn:
        cursor = conn.execute("INSERT INTO search_categories (user_id, name) VALUES (?, ?)", (user_id, name))
        row = conn.execute("SELECT * FROM search_categories WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return Category.from_row(row)


def list_categories_for_user(user_id: int) -> list[Category]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM search_categories WHERE user_id = ? ORDER BY created_at ASC", (user_id,)
        ).fetchall()
        return [Category.from_row(row) for row in rows]


def get_category_for_user(category_id: int, user_id: int) -> Category | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM search_categories WHERE id = ? AND user_id = ?", (category_id, user_id)
        ).fetchone()
        return Category.from_row(row) if row else None


def delete_category(category_id: int) -> None:
    """Borra la categoría; las búsquedas que apuntaban a ella vuelven a
    Sin categoría (ON DELETE SET NULL), no se borran."""
    with db.get_connection() as conn:
        conn.execute("DELETE FROM search_categories WHERE id = ?", (category_id,))
