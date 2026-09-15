"""Cliente de búsqueda de CeX España, vía el backend Algolia que usa su propia web.

CeX delega su buscador en Algolia a través de un proxy propio
(`search.webuy.io`, no `algolia.net` directamente). Las credenciales de
abajo son una App ID y una API key de **solo búsqueda** ("search-only"):
de solo lectura, pensadas para usarse desde el navegador del cliente — es
exactamente como la propia web de CeX las expone, no ningún bypass. Si
CeX las rota alguna vez y el escaneo empieza a fallar con 401/403, hay que
capturar las nuevas desde las herramientas de red del navegador (pestaña
Network, filtrar por "algolia" al buscar algo en es.webuy.com) y
actualizarlas aquí.

A diferencia de CashConverters, el propio índice ya expone señales de
stock (`inStockOnline`, `discontinued`, `showOnWeb`) y permite consultar un
producto suelto por id, así que sí se puede revalidar de forma fiable si
un anuncio ya guardado se ha quedado sin stock (equivalente al
`is_alive()` de Wallapop).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

APPLICATION_ID = "LNNFEEWZVA"
API_KEY = "bf79f2b6699e60a18ae330a1248b452c"
INDEX_NAME = "prod_cex_es"

SEARCH_URL = f"https://search.webuy.io/1/indexes/{INDEX_NAME}/query"
OBJECT_URL = f"https://search.webuy.io/1/indexes/{INDEX_NAME}/" + "{object_id}"
BASE_URL = "https://es.webuy.com"

DEFAULT_HEADERS = {
    "X-Algolia-Application-Id": APPLICATION_ID,
    "X-Algolia-API-Key": API_KEY,
    "Content-Type": "application/json",
}

# Solo productos visibles, no descatalogados y con stock online real.
AVAILABILITY_FILTER = "inStockOnline=1 AND discontinued=0 AND showOnWeb=1"

HITS_PER_PAGE = 40
MAX_PAGES = 5
PAGE_DELAY_SECONDS = 1.0
MAX_RETRIES = 3
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}


class CexError(RuntimeError):
    """Error de comunicación con el buscador de CeX tras agotar reintentos."""


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


def _request_with_retries(
    client: httpx.Client, url: str, method: str = "GET", json_body: dict[str, Any] | None = None
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.post(url, json=json_body) if method == "POST" else client.get(url)
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
            time.sleep((2**attempt) + (0.1 * attempt))

    assert last_exc is not None
    raise CexError(f"Fallo tras {MAX_RETRIES} intentos contra {url}: {last_exc}") from last_exc


def _parse_hit(hit: dict[str, Any]) -> Item | None:
    box_id = hit.get("boxId") or hit.get("objectID")
    price = hit.get("sellPrice")
    if not box_id or price is None:
        return None

    images = hit.get("imageUrls") or {}
    image_url = images.get("medium") or images.get("large") or images.get("small")

    box_name = hit.get("boxName") or str(box_id)
    # CeX no mete la plataforma en el nombre libre del producto (p. ej. un
    # juego se llama solo "F1 25", nunca "F1 25 PS5"): va aparte, en la
    # categoría ("PS5 Juegos", "Xbox Series Juegos"...). La añadimos al
    # título para que búsquedas como "F1 25 PS5" puedan encontrarlo.
    category = hit.get("categoryFriendlyName") or hit.get("categoryName")
    title = f"{box_name} - {category}" if category else box_name

    return Item(
        item_id=str(box_id),
        title=title,
        description=" / ".join(hit.get("productLineName") or []),
        price=float(price),
        currency="EUR",
        url=f"{BASE_URL}/product-detail/?id={box_id}",
        image_url=image_url,
    )


def search(criteria: SearchCriteria, client: httpx.Client | None = None) -> list[Item]:
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, timeout=15.0)

    try:
        items: list[Item] = []
        numeric_filters = []
        if criteria.min_price is not None:
            numeric_filters.append(f"sellPrice>={int(criteria.min_price)}")
        if criteria.max_price is not None:
            numeric_filters.append(f"sellPrice<={int(criteria.max_price)}")

        for page in range(criteria.max_pages):
            body: dict[str, Any] = {
                "query": criteria.keywords,
                "hitsPerPage": HITS_PER_PAGE,
                "page": page,
                "filters": AVAILABILITY_FILTER,
            }
            if numeric_filters:
                body["numericFilters"] = numeric_filters

            response = _request_with_retries(client, SEARCH_URL, method="POST", json_body=body)
            data = response.json()
            hits = data.get("hits", [])
            if not hits:
                break

            for hit in hits:
                item = _parse_hit(hit)
                if item is not None:
                    items.append(item)
                else:
                    logger.warning("Hit de CeX no parseable: %r", hit.get("boxId") or hit.get("objectID"))

            if page + 1 >= data.get("nbPages", 1):
                break
            time.sleep(PAGE_DELAY_SECONDS)

        return items
    finally:
        if own_client:
            client.close()


def is_alive(item_id: str, client: httpx.Client | None = None) -> bool:
    """True si el producto sigue existiendo y con stock online real (no solo si el objeto existe)."""
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, timeout=15.0)

    try:
        response = _request_with_retries(client, OBJECT_URL.format(object_id=item_id))
        if response.status_code == 404:
            return False
        data = response.json()
        return bool(data.get("inStockOnline")) and not data.get("discontinued") and bool(data.get("showOnWeb"))
    finally:
        if own_client:
            client.close()
