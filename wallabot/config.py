from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    _secret_key: str
    db_path: Path
    host: str
    port: int
    default_latitude: float
    default_longitude: float
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_from: str | None
    telegram_bot_token: str | None
    public_base_url: str | None
    timezone: str

    @property
    def secret_key(self) -> str:
        """Solo se exige al arrancar la web/auth, no para el cliente de Wallapop o la CLI."""
        if not self._secret_key or self._secret_key == "changeme":
            raise RuntimeError(
                "SECRET_KEY no configurada (o sigue en 'changeme'). "
                "Copia .env.example a .env y genera una clave con "
                "`python -c \"import secrets; print(secrets.token_hex(32))\"`."
            )
        return self._secret_key


def load_settings() -> Settings:
    db_path = Path(os.environ.get("DB_PATH", "wallabot.db"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    return Settings(
        _secret_key=os.environ.get("SECRET_KEY", ""),
        db_path=db_path,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "12185")),
        default_latitude=float(os.environ.get("DEFAULT_LATITUDE", "40.4168")),
        default_longitude=float(os.environ.get("DEFAULT_LONGITUDE", "-3.7038")),
        smtp_host=os.environ.get("SMTP_HOST") or None,
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER") or None,
        smtp_password=os.environ.get("SMTP_PASSWORD") or None,
        smtp_from=os.environ.get("SMTP_FROM") or None,
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
        public_base_url=(os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/") or None,
        timezone=os.environ.get("TIMEZONE", "Europe/Madrid"),
    )


settings = load_settings()
