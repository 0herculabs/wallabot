"""Cliente de la API interna de Wallapop.

Toda la particularidad de la API (endpoint, cabeceras, paginación, nombres de
campos) vive en este fichero. Si Wallapop cambia su API, solo hay que tocar
este módulo: el resto de la aplicación consume `search()` e `is_alive()`.

Detalles vigentes (sep-2026), ver plan de implementación:
- Endpoint: GET https://api.wallapop.com/api/v3/search (paginación por cursor
  `meta.next_page`, no offset/limit). `/api/v3/general/search` está
  deprecado (403 de CDN).
- `source=search_box` es obligatorio (sin él, 400).
- Sin lat/lon la API devuelve secciones vacías (geolocaliza por IP).
- No hace falta X-Signature, cookies ni token: basta cabeceras de navegador.
- No existe flag "vendido": un anuncio vendido desaparece del índice. La
  única forma fiable de confirmarlo es pedir /api/v3/items/{id} y ver 404.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.wallapop.com/api/v3/search"
ITEM_URL = "https://api.wallapop.com/api/v3/items/{item_id}"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Origin": "https://es.wallapop.com",
    "Referer": "https://es.wallapop.com/",
    "X-DeviceOS": "0",
}

MAX_PAGES = 5
PAGE_DELAY_SECONDS = 1.0
MAX_RETRIES = 3
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}

ShippingFilter = Literal["any", "shipping", "inperson"]


class WallapopError(RuntimeError):
    """Error de comunicación con la API de Wallapop tras agotar reintentos."""


@dataclass
class SearchCriteria:
    keywords: str
    min_price: float | None = None
    max_price: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float | None = None
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
    location: str | None
    item_latitude: float | None
    item_longitude: float | None
    shippable: bool
    published_at_ms: int | None
    reserved: bool


def _device_id() -> str:
    return str(uuid.uuid4())


def _request_with_retries(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            last_exc = exc
            response = None

        if response is not None:
            if response.status_code == 404:
                return response
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()
                return response
            last_exc = httpx.HTTPStatusError(
                f"status {response.status_code}", request=response.request, response=response
            )

        if attempt < MAX_RETRIES:
            backoff = (2 ** attempt) + (0.1 * attempt)
            time.sleep(backoff)

    assert last_exc is not None
    raise WallapopError(f"Fallo tras {MAX_RETRIES} intentos contra {url}: {last_exc}") from last_exc


def _get(field: dict[str, Any], *path: str, default: Any = None) -> Any:
    """Navega un dict anidado con fallback, sin reventar si Wallapop reordena campos."""
    current: Any = field
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current if current is not None else default


def _parse_item(raw: dict[str, Any]) -> Item | None:
    item_id = raw.get("id")
    if not item_id:
        logger.warning("Ítem de Wallapop sin 'id', se descarta: %r", raw)
        return None

    web_slug = raw.get("web_slug") or item_id
    price = _get(raw, "price", "amount", default=_get(raw, "price", default=None))
    if isinstance(raw.get("price"), (int, float)):
        price = raw["price"]
    currency = _get(raw, "price", "currency", default="EUR")

    images = raw.get("images") or []
    image_url = None
    if images:
        image_url = _get(images[0], "urls", "medium") or _get(images[0], "urls", "small")

    reserved = bool(_get(raw, "reserved", "flag", default=False))
    shippable = bool(
        _get(raw, "shipping", "item_is_shippable", default=False)
        or _get(raw, "shipping", "user_allows_shipping", default=False)
    )

    return Item(
        item_id=str(item_id),
        title=raw.get("title") or "(sin título)",
        description=raw.get("description") or "",
        price=float(price) if price is not None else 0.0,
        currency=str(currency),
        url=f"https://es.wallapop.com/item/{web_slug}",
        image_url=image_url,
        location=_get(raw, "location", "city"),
        item_latitude=_get(raw, "location", "latitude"),
        item_longitude=_get(raw, "location", "longitude"),
        shippable=shippable,
        published_at_ms=raw.get("created_at") or raw.get("modified_at"),
        reserved=reserved,
    )


def search(criteria: SearchCriteria, client: httpx.Client | None = None) -> list[Item]:
    """Busca anuncios en Wallapop según los criterios dados, paginando por cursor."""
    own_client = client is None
    if own_client:
        client = httpx.Client(headers={**DEFAULT_HEADERS, "x-deviceid": _device_id()}, timeout=15.0)

    try:
        items: list[Item] = []
        params: dict[str, Any] = {
            "keywords": criteria.keywords,
            "source": "search_box",
            "order_by": "most_relevance",
        }
        if criteria.min_price is not None:
            params["min_sale_price"] = int(criteria.min_price)
        if criteria.max_price is not None:
            params["max_sale_price"] = int(criteria.max_price)
        if criteria.latitude is not None:
            params["latitude"] = criteria.latitude
        if criteria.longitude is not None:
            params["longitude"] = criteria.longitude
        if criteria.radius_km is not None:
            params["distance_in_km"] = criteria.radius_km

        next_page: str | None = None
        for page in range(criteria.max_pages):
            page_params = dict(params)
            if next_page:
                page_params["next_page"] = next_page

            response = _request_with_retries(client, SEARCH_URL, page_params)
            data = response.json()

            payload = _get(data, "data", "section", "payload", default=None)
            if payload is not None:
                raw_items = payload.get("items", [])
            else:
                raw_items = _get(data, "data", "section", "items", default=[])

            if not raw_items:
                break

            for raw in raw_items:
                parsed = _parse_item(raw)
                if parsed is not None:
                    items.append(parsed)

            next_page = _get(data, "meta", "next_page", default=None)
            if not next_page:
                break

            time.sleep(PAGE_DELAY_SECONDS)

        return items
    finally:
        if own_client:
            client.close()


def is_alive(item_id: str, client: httpx.Client | None = None) -> bool:
    """True si el anuncio sigue existiendo (200); False si Wallapop responde 404."""
    own_client = client is None
    if own_client:
        client = httpx.Client(headers={**DEFAULT_HEADERS, "x-deviceid": _device_id()}, timeout=15.0)

    try:
        response = _request_with_retries(client, ITEM_URL.format(item_id=item_id))
        return response.status_code != 404
    finally:
        if own_client:
            client.close()


AdStatus = Literal["active", "reserved", "gone"]


def check_status(item_id: str, client: httpx.Client | None = None) -> AdStatus:
    """Consulta el estado actual de un anuncio ya guardado, a partir de su ficha.

    - "gone": el detalle da 404 (se ha borrado o vendido y retirado).
    - "reserved": el detalle sigue existiendo (200) pero con `reserved.flag`.
      Un anuncio reservado no siempre se vuelve a ver en el listado de
      búsqueda con la marca puesta (a veces Wallapop lo omite directamente
      del listado, igual que si se hubiera vendido), así que hay que
      comprobarlo también aquí al revalidar los que dejan de aparecer en un
      escaneo, no solo al verlos en la propia búsqueda.
    - "active": sigue en venta, no reservado.
    """
    own_client = client is None
    if own_client:
        client = httpx.Client(headers={**DEFAULT_HEADERS, "x-deviceid": _device_id()}, timeout=15.0)

    try:
        response = _request_with_retries(client, ITEM_URL.format(item_id=item_id))
        if response.status_code == 404:
            return "gone"
        data = response.json()
        return "reserved" if bool(_get(data, "reserved", "flag", default=False)) else "active"
    finally:
        if own_client:
            client.close()
