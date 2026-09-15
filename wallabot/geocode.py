"""Autocompletado de ciudad/localidad a coordenadas vía Photon (komoot.io, datos OSM).

Se llama bajo demanda desde el autocompletado del formulario de búsqueda,
nunca en el ciclo de escaneo. Se usa Photon en vez de Nominatim porque este
último no soporta bien búsquedas por prefijo ("Madr" no encuentra Madrid;
solo funciona con el nombre completo), lo que lo hace inútil para escribir
y ver sugerencias en vivo. Photon está pensado justo para eso.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

PHOTON_URL = "https://photon.komoot.io/api/"
USER_AGENT = "wallabot/1.0 (uso personal, autoalojado)"

# Bounding box amplio que cubre península, Baleares y Canarias. Photon lo usa
# como filtro dentro de la caja; el filtro por country=España de abajo excluye
# el resto de países que caen dentro de este rectángulo tan grande.
SPAIN_BBOX = "-18.5,27.5,4.5,43.9"
SPAIN_COUNTRY_NAMES = {"España", "Spain"}


@dataclass
class GeocodeResult:
    latitude: float
    longitude: float
    display_name: str


def _format_display_name(props: dict) -> str:
    parts = [props.get("name")]
    for key in ("state", "country"):
        value = props.get(key)
        if value and value not in parts:
            parts.append(value)
    return ", ".join(p for p in parts if p)


def search(query: str, limit: int = 8) -> list[GeocodeResult]:
    query = query.strip()
    if not query:
        return []
    try:
        response = httpx.get(
            PHOTON_URL,
            params={
                "q": query,
                "limit": limit * 2,
                "bbox": SPAIN_BBOX,
                "osm_tag": "place",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Fallo geocodificando '%s': %s", query, exc)
        return []

    results: list[GeocodeResult] = []
    seen: set[tuple[str, str | None]] = set()
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if props.get("country") not in SPAIN_COUNTRY_NAMES:
            continue
        name = props.get("name")
        if not name:
            continue
        dedup_key = (name, props.get("state"))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        try:
            lon, lat = feature["geometry"]["coordinates"]
        except (KeyError, ValueError, TypeError):
            continue

        results.append(
            GeocodeResult(
                latitude=float(lat),
                longitude=float(lon),
                display_name=_format_display_name(props),
            )
        )
        if len(results) >= limit:
            break

    return results
