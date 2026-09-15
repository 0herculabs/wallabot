from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from wallabot import cashconverters, cex, milanuncios, notifications, results, wallapop
from wallabot.config import settings
from wallabot.searches import Search, get_search, matches_criteria, record_scan_result

logger = logging.getLogger(__name__)

MAX_RECHECKS_PER_SCAN = 20

# Un único candado global: como mucho una búsqueda habla con una tienda a la
# vez, venga del scheduler, de "Escanear ahora" o de "Escanear todo". Evita
# que varias búsquedas disparen peticiones concurrentes y aumenten el riesgo
# de que la tienda bloquee o limite las peticiones.
_scan_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def scan_search(search_id: int, notify: bool = True) -> list[results.Result]:
    """Escanea una búsqueda en todas las tiendas que tenga activadas, filtra,
    deduplica y revalida vendidos.

    `notify=False` se usa en el escaneo manual (el usuario lo ve al momento en
    la web, no hace falta email); el scheduler automático deja `notify=True`.

    Serializado con `_scan_lock`: si otra búsqueda se está escaneando ahora
    mismo, esta llamada espera a que termine antes de empezar.

    Devuelve la lista de resultados nuevos detectados en este escaneo.
    """
    with _scan_lock:
        return _scan_search_locked(search_id, notify)


def _scan_search_locked(search_id: int, notify: bool) -> list[results.Result]:
    search = get_search(search_id)
    if search is None:
        raise ValueError(f"Búsqueda {search_id} no encontrada")

    new_results: list[results.Result] = []
    price_drops: list[results.Result] = []
    errors: list[str] = []

    if search.search_wallapop:
        try:
            wp_new, wp_drops = _scan_wallapop(search)
            new_results += wp_new
            price_drops += wp_drops
        except wallapop.WallapopError as exc:
            logger.warning("Escaneo Wallapop de búsqueda %s falló: %s", search_id, exc)
            errors.append(f"Wallapop: {exc}")

    if search.search_cashconverters:
        try:
            cc_new, cc_drops = _scan_cashconverters(search)
            new_results += cc_new
            price_drops += cc_drops
        except cashconverters.CashConvertersError as exc:
            logger.warning("Escaneo CashConverters de búsqueda %s falló: %s", search_id, exc)
            errors.append(f"CashConverters: {exc}")

    if search.search_cex:
        try:
            cex_new, cex_drops = _scan_cex(search)
            new_results += cex_new
            price_drops += cex_drops
        except cex.CexError as exc:
            logger.warning("Escaneo CeX de búsqueda %s falló: %s", search_id, exc)
            errors.append(f"CeX: {exc}")

    if search.search_milanuncios:
        try:
            ma_new, ma_drops = _scan_milanuncios(search)
            new_results += ma_new
            price_drops += ma_drops
        except milanuncios.MilanunciosError as exc:
            logger.warning("Escaneo Milanuncios de búsqueda %s falló: %s", search_id, exc)
            errors.append(f"Milanuncios: {exc}")

    enabled_count = sum([
        search.search_wallapop, search.search_cashconverters, search.search_cex, search.search_milanuncios,
    ])
    if errors and len(errors) == enabled_count:
        record_scan_result(search_id, status="error", error="; ".join(errors), timestamp=_now())
    else:
        record_scan_result(
            search_id, status="ok", error="; ".join(errors) if errors else None, timestamp=_now()
        )

    if notify:
        notifications.notify_new_results(search, new_results, price_drops)
    return new_results


def _scan_wallapop(search: Search) -> tuple[list[results.Result], list[results.Result]]:
    criteria = wallapop.SearchCriteria(
        keywords=search.title_keywords,
        min_price=search.min_price,
        max_price=search.max_price,
        latitude=search.latitude if search.latitude is not None else settings.default_latitude,
        longitude=search.longitude if search.longitude is not None else settings.default_longitude,
        radius_km=search.radius_km,
    )
    items = wallapop.search(criteria)

    seen_item_ids: set[str] = set()
    new_results: list[results.Result] = []
    price_drops: list[results.Result] = []

    for item in items:
        if item.reserved:
            # El detalle del anuncio (usado en la revalidación) no expone si está
            # reservado, solo si existe o no; por eso hay que capturarlo aquí, con
            # el propio resultado de búsqueda, que sí trae ese dato.
            existing = results.find_by_item_id(search.id, "wallapop", item.item_id)
            if existing is not None and not existing.discarded and not existing.is_sold and not existing.is_reserved:
                results.mark_reserved(existing.id)
                logger.info("Resultado %s marcado como reservado (búsqueda %s)", existing.id, search.id)
            seen_item_ids.add(item.item_id)
            continue

        if not matches_criteria(
            search, title=item.title, description=item.description, price=item.price,
            shippable=item.shippable,
        ):
            continue

        seen_item_ids.add(item.item_id)
        outcome = results.upsert_result(
            search_id=search.id,
            platform="wallapop",
            item_id=item.item_id,
            title=item.title,
            description=item.description,
            price=item.price,
            currency=item.currency,
            url=item.url,
            image_url=item.image_url,
            location=item.location,
            shipping_allowed=item.shippable,
            published_at=str(item.published_at_ms) if item.published_at_ms else None,
            latitude=item.item_latitude,
            longitude=item.item_longitude,
        )
        if outcome.is_new:
            result_row = results.get_result_for_search(outcome.result_id, search.id)
            if result_row is not None:
                new_results.append(result_row)
        elif outcome.price_dropped:
            result_row = results.get_result_for_search(outcome.result_id, search.id)
            if result_row is not None:
                price_drops.append(result_row)

    _revalidate_missing_wallapop(search.id, seen_item_ids)
    return new_results, price_drops


def _scan_cashconverters(search: Search) -> tuple[list[results.Result], list[results.Result]]:
    criteria = cashconverters.SearchCriteria(
        keywords=search.title_keywords,
        min_price=search.min_price,
        max_price=search.max_price,
    )
    items = cashconverters.search(criteria)

    new_results: list[results.Result] = []
    price_drops: list[results.Result] = []

    for item in items:
        if not matches_criteria(
            search, title=item.title, description=item.description, price=item.price,
            shippable=None,
        ):
            continue

        outcome = results.upsert_result(
            search_id=search.id,
            platform="cashconverters",
            item_id=item.item_id,
            title=item.title,
            description=item.description,
            price=item.price,
            currency=item.currency,
            url=item.url,
            image_url=item.image_url,
            location=None,
            shipping_allowed=True,
            published_at=None,
        )
        if outcome.is_new:
            result_row = results.get_result_for_search(outcome.result_id, search.id)
            if result_row is not None:
                new_results.append(result_row)
        elif outcome.price_dropped:
            result_row = results.get_result_for_search(outcome.result_id, search.id)
            if result_row is not None:
                price_drops.append(result_row)

    # CashConverters no tiene un endpoint de detalle para revalidar un item
    # concreto: es una tienda real (no un mercado P2P), así que en cuanto se
    # vende desaparece del catálogo. No hay forma fiable de distinguir "ya no
    # sale en estas páginas" de "se vendió", así que no se marca nada como
    # vendido aquí: el usuario lo descarta a mano si ve que ya no está.
    return new_results, price_drops


def _scan_cex(search: Search) -> tuple[list[results.Result], list[results.Result]]:
    criteria = cex.SearchCriteria(
        keywords=search.title_keywords,
        min_price=search.min_price,
        max_price=search.max_price,
    )
    items = cex.search(criteria)

    seen_item_ids: set[str] = set()
    new_results: list[results.Result] = []
    price_drops: list[results.Result] = []

    for item in items:
        if not matches_criteria(
            search, title=item.title, description=item.description, price=item.price,
            shippable=None,
        ):
            continue

        seen_item_ids.add(item.item_id)
        outcome = results.upsert_result(
            search_id=search.id,
            platform="cex",
            item_id=item.item_id,
            title=item.title,
            description=item.description,
            price=item.price,
            currency=item.currency,
            url=item.url,
            image_url=item.image_url,
            location=None,
            shipping_allowed=True,
            published_at=None,
        )
        if outcome.is_new:
            result_row = results.get_result_for_search(outcome.result_id, search.id)
            if result_row is not None:
                new_results.append(result_row)
        elif outcome.price_dropped:
            result_row = results.get_result_for_search(outcome.result_id, search.id)
            if result_row is not None:
                price_drops.append(result_row)

    _revalidate_missing(search.id, "cex", seen_item_ids, lambda c: cex.is_alive(c.item_id), cex.CexError)
    return new_results, price_drops


def _scan_milanuncios(search: Search) -> tuple[list[results.Result], list[results.Result]]:
    criteria = milanuncios.SearchCriteria(
        keywords=search.title_keywords,
        min_price=search.min_price,
        max_price=search.max_price,
    )
    items = milanuncios.search(criteria)

    seen_item_ids: set[str] = set()
    new_results: list[results.Result] = []
    price_drops: list[results.Result] = []

    for item in items:
        if item.reserved:
            # Igual que en Wallapop, el detalle del anuncio no expone si está
            # reservado (solo si existe o no); ese dato solo viene en el propio
            # listado de búsqueda, así que hay que capturarlo aquí.
            existing = results.find_by_item_id(search.id, "milanuncios", item.item_id)
            if existing is not None and not existing.discarded and not existing.is_sold and not existing.is_reserved:
                results.mark_reserved(existing.id)
                logger.info("Resultado %s marcado como reservado (búsqueda %s)", existing.id, search.id)
            seen_item_ids.add(item.item_id)
            continue

        if not matches_criteria(
            search, title=item.title, description=item.description, price=item.price,
            shippable=None,
        ):
            continue

        seen_item_ids.add(item.item_id)
        outcome = results.upsert_result(
            search_id=search.id,
            platform="milanuncios",
            item_id=item.item_id,
            title=item.title,
            description=item.description,
            price=item.price,
            currency=item.currency,
            url=item.url,
            image_url=item.image_url,
            location=None,
            shipping_allowed=True,
            published_at=None,
        )
        if outcome.is_new:
            result_row = results.get_result_for_search(outcome.result_id, search.id)
            if result_row is not None:
                new_results.append(result_row)
        elif outcome.price_dropped:
            result_row = results.get_result_for_search(outcome.result_id, search.id)
            if result_row is not None:
                price_drops.append(result_row)

    _revalidate_missing_milanuncios(search.id, seen_item_ids)
    return new_results, price_drops


def _revalidate_missing_wallapop(search_id: int, seen_item_ids: set[str]) -> None:
    # Un anuncio reservado no siempre vuelve a salir en el listado de búsqueda
    # con la marca puesta (a veces Wallapop lo omite directamente, igual que si
    # se hubiera vendido), así que hay que confirmarlo en su ficha.
    _revalidate_three_state(
        search_id, "wallapop", seen_item_ids, lambda c: wallapop.check_status(c.item_id), wallapop.WallapopError
    )


def _revalidate_missing_milanuncios(search_id: int, seen_item_ids: set[str]) -> None:
    # Milanuncios directamente deja de mostrar en el listado los anuncios
    # reservados (sin marca, a diferencia de Wallapop), así que la transición
    # "en venta -> reservado" solo se puede detectar en su ficha.
    _revalidate_three_state(
        search_id, "milanuncios", seen_item_ids, lambda c: milanuncios.check_status(c.url), milanuncios.MilanunciosError
    )


def _revalidate_three_state(search_id: int, platform: str, seen_item_ids: set[str], check_status_fn, error_cls) -> None:
    """Revalidación de anuncios que no aparecieron en este escaneo, distinguiendo
    tres estados (activo / reservado / vendido-retirado) en vez del simple
    vivo/muerto de `_revalidate_missing`."""
    candidates = results.results_needing_recheck(search_id, platform, seen_item_ids, MAX_RECHECKS_PER_SCAN)
    for candidate in candidates:
        try:
            status = check_status_fn(candidate)
        except error_cls as exc:
            logger.warning("No se pudo revalidar %s (%s): %s", candidate.item_id, platform, exc)
            continue
        if status == "gone":
            results.mark_checked(candidate.id, still_alive=False)
        elif status == "reserved":
            results.mark_reserved(candidate.id)
            logger.info("Resultado %s marcado como reservado (búsqueda %s)", candidate.id, search_id)
        else:
            results.mark_checked(candidate.id, still_alive=True)


def _revalidate_missing(search_id: int, platform: str, seen_item_ids: set[str], is_alive_fn, error_cls) -> None:
    candidates = results.results_needing_recheck(search_id, platform, seen_item_ids, MAX_RECHECKS_PER_SCAN)
    if not candidates:
        return
    for candidate in candidates:
        try:
            alive = is_alive_fn(candidate)
        except error_cls as exc:
            logger.warning("No se pudo revalidar %s (%s): %s", candidate.item_id, platform, exc)
            continue
        results.mark_checked(candidate.id, still_alive=alive)
