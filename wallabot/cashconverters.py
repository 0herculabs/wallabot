"""Cliente del buscador público de CashConverters España (Salesforce Commerce Cloud).

A diferencia de Wallapop, aquí no hace falta ninguna cabecera especial ni
manejo de anti-bot: el HTML de resultados es de servidor y trae todos los
datos de cada producto embebidos en el atributo `data-product-datalayer`.

CashConverters es una tienda real, no un mercado entre particulares: un
anuncio que aparece en la búsqueda está en stock. En cuanto se vende,
desaparece del catálogo (no hay concepto de "reservado" a medio plazo como
en Wallapop). Por eso no existe una revalidación tipo `is_alive()` aquí: no
hay un endpoint de detalle por producto que confirme su desaparición, así
que un resultado que deja de aparecer en el buscador simplemente se queda
como estaba hasta que el usuario lo descarte a mano.
"""

from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.cashconverters.es/on/demandware.store/Sites-CashConvertersSpain-Site/es/Search-Show"
BASE_URL = "https://www.cashconverters.es"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-ES,es;q=0.9",
}

PAGE_SIZE = 24
MAX_PAGES = 5
PAGE_DELAY_SECONDS = 1.0
MAX_RETRIES = 3
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}

_TILE_RE = re.compile(
    r'<div class="product-tile[^"]*" data-pid="(?P<pid>[^"]+)" data-product-datalayer="(?P<datalayer>[^"]*)">'
    r"(?P<body>.*?)</div>\s*</div>\s*</div>",
    re.DOTALL,
)
_IMAGE_RE = re.compile(r'class="tile-image"[^>]*\bsrc="([^"]+)"')
_LINK_RE = re.compile(r'class="pdp-link">\s*<a[^>]*href="([^"]+)"')
_PRICE_RE = re.compile(r'class="principal" data-price=([0-9.]+)')
_CONDITION_RE = re.compile(r'class="status">\s*([^<\n]+?)\s*</div>', re.DOTALL)


class CashConvertersError(RuntimeError):
    """Error de comunicación con CashConverters tras agotar reintentos."""


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
    condition: str | None


def _request_with_retries(client: httpx.Client, url: str, params: dict[str, Any]) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            last_exc = exc
            response = None

        if response is not None:
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()
                return response
            last_exc = httpx.HTTPStatusError(
                f"status {response.status_code}", request=response.request, response=response
            )

        if attempt < MAX_RETRIES:
            time.sleep((2**attempt) + (0.1 * attempt))

    assert last_exc is not None
    raise CashConvertersError(f"Fallo tras {MAX_RETRIES} intentos contra {url}: {last_exc}") from last_exc


def _unescape(value: str) -> str:
    return html.unescape(value).strip()


def _parse_tile(match: re.Match) -> Item | None:
    pid = match.group("pid")
    body = match.group("body")

    price_match = _PRICE_RE.search(body)
    if price_match is None:
        return None
    price = float(price_match.group(1))

    link_match = _LINK_RE.search(body)
    if link_match is None:
        return None
    url = BASE_URL + _unescape(link_match.group(1)).split("?")[0]

    image_match = _IMAGE_RE.search(body)
    image_url = _unescape(image_match.group(1)) if image_match else None

    condition_match = _CONDITION_RE.search(body)
    condition = _unescape(condition_match.group(1)) if condition_match else None

    # El título "bonito" viene en el propio enlace pdp-link (texto entre <a>...</a>);
    # lo sacamos del bloque completo del tile en vez del datalayer (que lo trae en minúsculas).
    title_match = re.search(r'class="link"[^>]*>([^<]+)</a>', body)
    title = _unescape(title_match.group(1)) if title_match else pid

    return Item(
        item_id=pid,
        title=title,
        description=condition or "",
        price=price,
        currency="EUR",
        url=url,
        image_url=image_url,
        condition=condition,
    )


def search(criteria: SearchCriteria, client: httpx.Client | None = None) -> list[Item]:
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, timeout=15.0, follow_redirects=True)

    try:
        items: list[Item] = []
        params: dict[str, Any] = {"q": criteria.keywords, "sz": PAGE_SIZE}
        if criteria.min_price is not None:
            params["pmin"] = int(criteria.min_price)
        if criteria.max_price is not None:
            params["pmax"] = int(criteria.max_price)

        for page in range(criteria.max_pages):
            page_params = {**params, "start": page * PAGE_SIZE}
            response = _request_with_retries(client, SEARCH_URL, page_params)

            matches = list(_TILE_RE.finditer(response.text))
            if not matches:
                break

            for match in matches:
                item = _parse_tile(match)
                if item is not None:
                    items.append(item)
                else:
                    logger.warning("Tile de CashConverters no parseable (pid=%s)", match.group("pid"))

            if len(matches) < PAGE_SIZE:
                break
            time.sleep(PAGE_DELAY_SECONDS)

        return items
    finally:
        if own_client:
            client.close()
