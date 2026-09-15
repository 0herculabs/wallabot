from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from wallabot import db
from wallabot.auth import hash_password, verify_password


class UsernameTakenError(RuntimeError):
    pass


@dataclass
class User:
    id: int
    username: str
    email: str | None
    password_hash: str
    is_admin: bool
    is_active: bool
    notify_email: bool
    notify_telegram: bool
    telegram_chat_id: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "User":
        return cls(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            password_hash=row["password_hash"],
            is_admin=bool(row["is_admin"]),
            is_active=bool(row["is_active"]),
            notify_email=bool(row["notify_email"]),
            notify_telegram=bool(row["notify_telegram"]),
            telegram_chat_id=row["telegram_chat_id"],
            created_at=row["created_at"],
        )


def create_user(username: str, password: str, email: str | None = None, is_admin: bool = False) -> User:
    with db.get_connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, email, password_hash, is_admin) VALUES (?, ?, ?, ?)",
                (username, email, hash_password(password), int(is_admin)),
            )
        except sqlite3.IntegrityError as exc:
            raise UsernameTakenError(f"El usuario '{username}' ya existe") from exc
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return User.from_row(row)


def get_user_by_id(user_id: int) -> User | None:
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return User.from_row(row) if row else None


def get_user_by_username(username: str) -> User | None:
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return User.from_row(row) if row else None


def list_users() -> list[User]:
    with db.get_connection() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [User.from_row(row) for row in rows]


def authenticate(username: str, password: str) -> User | None:
    user = get_user_by_username(username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def set_password(user_id: int, new_password: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )


def set_active(user_id: int, is_active: bool) -> None:
    with db.get_connection() as conn:
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id))


def set_email(user_id: int, email: str | None) -> None:
    with db.get_connection() as conn:
        conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, user_id))


def set_notify_email(user_id: int, notify_email: bool) -> None:
    with db.get_connection() as conn:
        conn.execute("UPDATE users SET notify_email = ? WHERE id = ?", (int(notify_email), user_id))


def set_telegram(user_id: int, chat_id: str | None, notify_telegram: bool) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE users SET telegram_chat_id = ?, notify_telegram = ? WHERE id = ?",
            (chat_id, int(notify_telegram), user_id),
        )


def delete_user(user_id: int) -> None:
    with db.get_connection() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
