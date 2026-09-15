from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from wallabot.config import settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _migrate(conn: sqlite3.Connection) -> None:
    """Ajustes de esquema para bases de datos creadas antes de un cambio de campos.

    `CREATE TABLE IF NOT EXISTS` no añade ni renombra columnas en tablas ya
    existentes, así que los ajustes se hacen aquí a mano.
    """
    if _column_exists(conn, "searches", "keywords") and not _column_exists(conn, "searches", "title_keywords"):
        conn.execute("ALTER TABLE searches RENAME COLUMN keywords TO title_keywords")
    _add_column_if_missing(conn, "searches", "content_keywords", "content_keywords TEXT")

    _add_column_if_missing(conn, "results", "latitude", "latitude REAL")
    _add_column_if_missing(conn, "results", "longitude", "longitude REAL")
    _add_column_if_missing(conn, "results", "is_reserved", "is_reserved INTEGER NOT NULL DEFAULT 0")

    _add_column_if_missing(conn, "searches", "search_wallapop", "search_wallapop INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(
        conn, "searches", "search_cashconverters", "search_cashconverters INTEGER NOT NULL DEFAULT 0"
    )
    _add_column_if_missing(conn, "results", "platform", "platform TEXT NOT NULL DEFAULT 'wallapop'")
    _add_column_if_missing(conn, "results", "previous_price", "previous_price REAL")

    _add_column_if_missing(conn, "searches", "search_cex", "search_cex INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(
        conn, "searches", "search_milanuncios", "search_milanuncios INTEGER NOT NULL DEFAULT 0"
    )

    _add_column_if_missing(
        conn, "searches", "category_id", "category_id INTEGER REFERENCES search_categories(id) ON DELETE SET NULL"
    )

    if _column_exists(conn, "searches", "notify_email") and not _column_exists(conn, "searches", "notify_enabled"):
        conn.execute("ALTER TABLE searches RENAME COLUMN notify_email TO notify_enabled")
    _add_column_if_missing(conn, "searches", "notify_enabled", "notify_enabled INTEGER NOT NULL DEFAULT 1")

    telegram_col_existed = _column_exists(conn, "users", "notify_telegram")
    _add_column_if_missing(conn, "users", "notify_telegram", "notify_telegram INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "users", "telegram_chat_id", "telegram_chat_id TEXT")
    if not telegram_col_existed:
        # Antes de esto, `notify_new_results` enviaba email con solo comprobar el
        # email de la búsqueda/usuario, ignorando `users.notify_email`. Al pasar a
        # exigirlo, lo activamos una vez para quien ya tenía email guardado, para
        # no cortarle los avisos que ya recibía sin que lo pidiera.
        conn.execute("UPDATE users SET notify_email = 1 WHERE email IS NOT NULL AND email != ''")


def init_db(db_path: Path | str | None = None) -> None:
    path = db_path or settings.db_path
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_connection(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or settings.db_path
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
