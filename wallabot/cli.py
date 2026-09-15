"""Comandos de administración: `python -m wallabot.cli <comando>`."""

from __future__ import annotations

import argparse
import sys

from wallabot import wallapop
from wallabot.config import settings


def cmd_test_search(args: argparse.Namespace) -> None:
    criteria = wallapop.SearchCriteria(
        keywords=args.keywords,
        min_price=args.min_price,
        max_price=args.max_price,
        latitude=args.latitude if args.latitude is not None else settings.default_latitude,
        longitude=args.longitude if args.longitude is not None else settings.default_longitude,
        radius_km=args.radius_km,
        max_pages=args.pages,
    )
    print(f"Buscando '{criteria.keywords}' (min={criteria.min_price}, max={criteria.max_price})...")
    items = wallapop.search(criteria)
    print(f"\n{len(items)} anuncios encontrados:\n")
    for item in items:
        estado = " [RESERVADO]" if item.reserved else ""
        print(f"- [{item.item_id}] {item.title} — {item.price} {item.currency}{estado}")
        print(f"  {item.url}")

    if not items:
        print("(sin resultados; revisa palabras clave, precios o conectividad)")
        return

    print("\nComprobando is_alive() con el primer resultado y con un id inventado...")
    real_alive = wallapop.is_alive(items[0].item_id)
    fake_alive = wallapop.is_alive("00000000-0000-0000-0000-000000000000")
    print(f"  {items[0].item_id} (real) -> alive={real_alive}")
    print(f"  id inventado -> alive={fake_alive}")
    if real_alive and not fake_alive:
        print("OK: is_alive() distingue anuncios reales de inexistentes.")
    else:
        print("AVISO: resultado inesperado, revisar wallapop.is_alive().")


def cmd_test_email(args: argparse.Namespace) -> None:
    from wallabot import notifications

    print(f"Enviando email de prueba a {args.to_address} vía {settings.smtp_host}:{settings.smtp_port}...")
    notifications.send_test_email(args.to_address)
    print("Enviado. Revisa la bandeja de entrada (y spam) de", args.to_address)


def cmd_test_telegram(args: argparse.Namespace) -> None:
    from wallabot import notifications

    print(f"Enviando mensaje de prueba de Telegram al chat {args.chat_id}...")
    notifications.send_test_telegram(args.chat_id)
    print("Enviado. Revisa el chat con el bot en Telegram.")


def cmd_backup_db(args: argparse.Namespace) -> None:
    from wallabot import backup

    path = backup.backup_database()
    print(f"Backup creado: {path}")


def cmd_create_admin(args: argparse.Namespace) -> None:
    from wallabot import db, users

    db.init_db()
    user = users.create_user(
        username=args.username,
        password=args.password,
        email=args.email,
        is_admin=True,
    )
    print(f"Admin '{user.username}' creado (id={user.id}).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wallabot.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_test = subparsers.add_parser("test-search", help="Prueba el cliente de Wallapop contra la API real")
    p_test.add_argument("keywords")
    p_test.add_argument("--min-price", type=float, default=None)
    p_test.add_argument("--max-price", type=float, default=None)
    p_test.add_argument("--latitude", type=float, default=None)
    p_test.add_argument("--longitude", type=float, default=None)
    p_test.add_argument("--radius-km", type=float, default=None)
    p_test.add_argument("--pages", type=int, default=1)
    p_test.set_defaults(func=cmd_test_search)

    p_email = subparsers.add_parser("test-email", help="Envía un email de prueba con la configuración SMTP de .env")
    p_email.add_argument("to_address")
    p_email.set_defaults(func=cmd_test_email)

    p_telegram = subparsers.add_parser(
        "test-telegram", help="Envía un mensaje de prueba con el TELEGRAM_BOT_TOKEN de .env"
    )
    p_telegram.add_argument("chat_id")
    p_telegram.set_defaults(func=cmd_test_telegram)

    p_backup = subparsers.add_parser("backup-db", help="Crea una copia de seguridad de la BD ahora mismo")
    p_backup.set_defaults(func=cmd_backup_db)

    p_admin = subparsers.add_parser("create-admin", help="Crea el primer usuario administrador")
    p_admin.add_argument("username")
    p_admin.add_argument("password")
    p_admin.add_argument("--email", default=None)
    p_admin.set_defaults(func=cmd_create_admin)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
