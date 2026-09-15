"""Copias de seguridad periódicas de la base de datos SQLite.

Se ejecutan dentro del propio proceso (ver `scheduler.py`), sin depender de
cron ni systemd timers externos, siguiendo el mismo criterio de simplicidad
que el resto de la app: un único proceso Python se encarga de todo.
"""

from __future__ import annotations

import gzip
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wallabot.config import settings

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
RETENTION_DAYS = 30
FILENAME_FORMAT = "wallabot-%Y%m%d-%H%M%S.db.gz"


def backup_database() -> Path:
    """Crea una copia consistente de la BD y la comprime; purga backups de +30 días.

    Usa el API de backup online de SQLite (no una simple copia de fichero), que
    produce una copia consistente incluso si hay escrituras en curso.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    filename = datetime.now(timezone.utc).strftime(FILENAME_FORMAT)
    dest_path = BACKUP_DIR / filename
    raw_path = dest_path.with_suffix("")  # mismo nombre sin el .gz final

    source = sqlite3.connect(settings.db_path)
    try:
        target = sqlite3.connect(raw_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    with open(raw_path, "rb") as f_in, gzip.open(dest_path, "wb") as f_out:
        f_out.writelines(f_in)
    raw_path.unlink()

    logger.info("Backup de BD creado: %s", dest_path.name)
    _prune_old_backups()
    return dest_path


def _prune_old_backups() -> None:
    if not BACKUP_DIR.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    for path in BACKUP_DIR.glob("wallabot-*.db.gz"):
        try:
            file_date = datetime.strptime(path.name, FILENAME_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if file_date < cutoff:
            path.unlink()
            logger.info("Backup antiguo eliminado (>%d días): %s", RETENTION_DAYS, path.name)
