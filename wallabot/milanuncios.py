"""Cliente del buscador público de Milanuncios.

Milanuncios renderiza la búsqueda en servidor y embebe el listado completo en
`window.__INITIAL_PROPS__` como un `JSON.parse("...")`: un JSON escapado dos
veces (primero como literal de string JS, luego como JSON de verdad). No hace
falta ninguna API separada, cabecera especial ni manejo de anti-bot.

A diferencia de Wallapop, la ficha de un anuncio no responde 404 cuando
desaparece: Milanuncios la redirige (301) a la página de la categoría. Esa
redirección es la señal que usamos para revalidar anuncios guardados que ya
no aparecen en el listado, así que `check_status()` recibe la URL completa
del anuncio en vez de solo su id.

El propio listado de búsqueda incluye un campo `isReserved`, pero en la
práctica los anuncios reservados dejan de aparecer en la búsqueda (no salen
con una marca, como sí hace Wallapop); por eso la detección real de
"en venta -> reservado" se hace en `check_status()`, consultando la ficha de
los anuncios que dejan de salir en el listado.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.milanuncios.com/anuncios/"
BASE_URL = "https://www.milanuncios.com"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-ES,es;q=0.9",
}

RESULTS_PER_PAGE = 41
MAX_PAGES = 5
PAGE_DELAY_SECONDS = 1.0
MAX_RETRIES = 3
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}

_PROPS_RE = re.compile(r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\("(.*?)"\);</script>', re.DOTALL)


class MilanunciosError(RuntimeError):
    """Error de comunicación con Milanuncios tras agotar reintentos."""


@dataclass
class SearchCriteria:
    keywords: str
    min_price: float | None = None
    max_price: float | None = None
    max_pages: int = MAX_PAGES


@dataclass
class Item:
    item_id: str
    title: str
    description: str
    price: float
    currency: str
    url: str
    image_url: str | None
    reserved: bool


def _request_with_retries(client: httpx.Client, url: str, params: dict[str, Any]) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            last_exc = exc
            response = None

        if response is not None:
            if response.is_redirect:
                # Una ficha de anuncio que ya no existe se redirige (301) a su
                # categoría en vez de dar 404; se devuelve tal cual para que
                # is_alive() lo interprete, no es un error de comunicación.
                return response
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()
                return response
            last_exc = httpx.HTTPStatusError(
                f"status {response.status_code}", request=response.request, response=response
            )

        if attempt < MAX_RETRIES:
            time.sleep((2**attempt) + (0.1 * attempt))

    assert last_exc is not None
    raise MilanunciosError(f"Fallo tras {MAX_RETRIES} intentos contra {url}: {last_exc}") from last_exc


def _parse_initial_props(html: str) -> dict[str, Any] | None:
    match = _PROPS_RE.search(html)
    if match is None:
        return None
    # El bloque es JSON.parse("<json escapado como literal de string JS>"):
    # se decodifica primero como string (quita el escapado JS) y el resultado
    # ya es JSON válido.
    js_string = json.loads('"' + match.group(1) + '"')
    return json.loads(js_string)


def _parse_ad(raw: dict[str, Any]) -> Item | None:
    item_id = raw.get("id")
    url_path = raw.get("url")
    price = ((raw.get("price") or {}).get("cashPrice") or {}).get("value")
    if not item_id or not url_path or price is None:
        return None

    images = raw.get("images") or []
    # El CDN de imágenes exige el parámetro `rule` (tamaño/calidad); sin él
    # responde 404. `hw396_70` es el que usa la propia web para las miniaturas
    # del listado de búsqueda.
    image_url = f"https://{images[0]}?rule=hw396_70" if images else None

    reserved_flag = raw.get("isReserved")
    reserved = bool(reserved_flag) and reserved_flag != "RELEASED"

    return Item(
        item_id=str(item_id),
        title=raw.get("title") or "(sin título)",
        description=raw.get("description") or "",
        price=float(price),
        currency="EUR",
        url=BASE_URL + url_path,
        image_url=image_url,
        reserved=reserved,
    )


def search(criteria: SearchCriteria, client: httpx.Client | None = None) -> list[Item]:
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, timeout=15.0)

    try:
        items: list[Item] = []
        params: dict[str, Any] = {"s": criteria.keywords}
        if criteria.min_price is not None:
            params["desde"] = int(criteria.min_price)
        if criteria.max_price is not None:
            params["hasta"] = int(criteria.max_price)

        for page in range(1, criteria.max_pages + 1):
            page_params = {**params, "pagina": page}
            response = _request_with_retries(client, SEARCH_URL, page_params)

            props = _parse_initial_props(response.text)
            if props is None:
                logger.warning("No se encontró __INITIAL_PROPS__ en la respuesta de Milanuncios")
                break

            ad_list = (props.get("adListPagination") or {}).get("adList") or {}
            ads = ad_list.get("ads") or []
            if not ads:
                break

            for raw in ads:
                item = _parse_ad(raw)
                if item is not None:
                    items.append(item)
                else:
                    logger.warning("Anuncio de Milanuncios no parseable (id=%s)", raw.get("id"))

            pagination = (props.get("adListPagination") or {}).get("pagination") or {}
            if page >= pagination.get("totalPages", page):
                break
            time.sleep(PAGE_DELAY_SECONDS)

        return items
    finally:
        if own_client:
            client.close()


AdStatus = Literal["active", "reserved", "gone"]


def check_status(url: str, client: httpx.Client | None = None) -> AdStatus:
    """Consulta el estado actual de un anuncio ya guardado, a partir de su ficha.

    - "gone": Milanuncios redirige (301) la ficha a la categoría — el anuncio
      ha caducado, se ha retirado o se ha vendido y desaparecido del catálogo.
    - "reserved": la ficha sigue viva pero el vendedor la ha marcado como
      reservada (`ad.isReserved`). A diferencia de Wallapop, los anuncios
      reservados de Milanuncios ya NO aparecen en el listado de búsqueda (no
      salen con una marca, directamente desaparecen), así que esta es la
      única forma de detectar la transición "en venta -> reservado" para
      anuncios que dejan de salir en un escaneo.
    - "active": sigue en venta normal.

    De vez en cuando, en vez de la ficha real o su redirección, Milanuncios
    sirve una página de verificación anti-bot ("Pardon Our Interruption") con
    200 pero sin el JSON de la ficha. Para no marcar por error un anuncio como
    vendido en ese caso, se lanza MilanunciosError (se reintenta en el
    siguiente escaneo) en vez de devolver un estado a ciegas.
    """
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, timeout=15.0)

    try:
        response = _request_with_retries(client, url, {})
        if response.is_redirect:
            return "gone"
        if response.status_code == 200:
            props = _parse_initial_props(response.text)
            ad = (props or {}).get("ad") or {}
            if "id" in ad:
                return "reserved" if ad.get("isReserved") else "active"
        raise MilanunciosError(f"Respuesta inesperada revalidando {url} (status {response.status_code})")
    finally:
        if own_client:
            client.close()
