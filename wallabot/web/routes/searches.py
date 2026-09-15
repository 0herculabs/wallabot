from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from wallabot import results, scanner, scheduler
from wallabot.categories import get_category_for_user, list_categories_for_user
from wallabot.config import settings
from wallabot.results import VALID_PLATFORMS, VALID_SORT_MODES, SortMode
from wallabot.searches import (
    Search,
    create_search,
    delete_search,
    get_search_for_user,
    list_searches_for_user,
    set_active,
    update_search,
)
from wallabot.users import User
from wallabot.web.deps import get_current_user
from wallabot.web.templating import templates

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_owned_search_or_404(search_id: int, user: User) -> Search:
    search = get_search_for_user(search_id, user.id)
    if search is None:
        raise HTTPException(status_code=404, detail="Búsqueda no encontrada")
    return search


def _sort_param(sort: str) -> SortMode:
    return sort if sort in VALID_SORT_MODES else "newest"


def _platforms_param(platforms: str) -> set[str]:
    requested = {p.strip() for p in platforms.split(",") if p.strip()}
    valid = requested & VALID_PLATFORMS
    return valid if valid else set(VALID_PLATFORMS)


def _search_origin(search: Search) -> tuple[float, float]:
    lat = search.latitude if search.latitude is not None else settings.default_latitude
    lon = search.longitude if search.longitude is not None else settings.default_longitude
    return (lat, lon)


def _selected_category_param(category: str, category_list: list) -> int | None | str:
    if category == "none":
        return None
    if category == "all":
        return "all"
    try:
        category_id = int(category)
    except ValueError:
        return "all"
    return category_id if any(c.id == category_id for c in category_list) else "all"


@router.get("/")
def index(request: Request, category: str = "all", user: User = Depends(get_current_user)):
    search_list = list_searches_for_user(user.id)
    unseen_counts = {s.id: results.count_unseen(s.id, search=s) for s in search_list}
    category_list = list_categories_for_user(user.id)

    grouped_searches: dict[int | None, list[Search]] = {None: []}
    for cat in category_list:
        grouped_searches[cat.id] = []
    for search in search_list:
        grouped_searches.setdefault(search.category_id, []).append(search)

    selected = _selected_category_param(category, category_list)

    sections = [{"id": None, "param": "none", "name": "Sin categoría", "searches": grouped_searches[None]}]
    sections += [
        {"id": cat.id, "param": str(cat.id), "name": cat.name, "searches": grouped_searches.get(cat.id, [])}
        for cat in category_list
    ]
    if selected != "all":
        sections = [s for s in sections if s["id"] == selected]

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user, "searches": search_list, "unseen_counts": unseen_counts,
            "categories": category_list, "grouped_searches": grouped_searches,
            "sections": sections, "selected": selected,
        },
    )


@router.post("/searches/scan-all")
def manual_scan_all(request: Request, user: User = Depends(get_current_user)):
    for search in list_searches_for_user(user.id):
        if not search.is_active:
            continue
        try:
            scanner.scan_search(search.id, notify=False)
        except Exception:
            logger.exception("Fallo escaneando la búsqueda %s en el escaneo global", search.id)
    return RedirectResponse(url="/", status_code=303)


@router.get("/searches/new")
def new_search_form(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request, "search_form.html", {"user": user, "search": None, "error": None})


@router.post("/searches")
def create_search_submit(
    request: Request,
    user: User = Depends(get_current_user),
    name: str = Form(...),
    title_keywords: str = Form(...),
    content_keywords: str = Form(""),
    min_price: str = Form(""),
    max_price: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    radius_km: str = Form(""),
    excluded_words: str = Form(""),
    shipping_filter: str = Form("any"),
    search_wallapop: bool = Form(False),
    search_cashconverters: bool = Form(False),
    search_cex: bool = Form(False),
    search_milanuncios: bool = Form(False),
    scan_interval_minutes: int = Form(60),
    notify_enabled: bool = Form(False),
):
    if not search_wallapop and not search_cashconverters and not search_cex and not search_milanuncios:
        return templates.TemplateResponse(
            request,
            "search_form.html",
            {"user": user, "search": None, "error": "Activa al menos una tienda."},
            status_code=400,
        )
    search = create_search(
        user_id=user.id,
        name=name,
        title_keywords=title_keywords,
        content_keywords=content_keywords or None,
        min_price=float(min_price) if min_price else None,
        max_price=float(max_price) if max_price else None,
        latitude=float(latitude) if latitude else None,
        longitude=float(longitude) if longitude else None,
        radius_km=float(radius_km) if radius_km else None,
        excluded_words=excluded_words or None,
        shipping_filter=shipping_filter,
        search_wallapop=search_wallapop,
        search_cashconverters=search_cashconverters,
        search_cex=search_cex,
        search_milanuncios=search_milanuncios,
        scan_interval_minutes=scan_interval_minutes,
        notify_enabled=notify_enabled,
    )
    scheduler.schedule_search(search)
    return RedirectResponse(url=f"/searches/{search.id}", status_code=303)


@router.get("/searches/{search_id}")
def search_detail(
    request: Request, search_id: int, sort: str = "newest", platforms: str = "",
    user: User = Depends(get_current_user),
):
    search = _get_owned_search_or_404(search_id, user)
    sort_mode = _sort_param(sort)
    platform_set = _platforms_param(platforms)
    active_results = results.list_active_results(
        search_id, sort=sort_mode, origin=_search_origin(search), platforms=platform_set, search=search
    )
    results.mark_seen(search_id)
    return templates.TemplateResponse(
        request,
        "search_detail.html",
        {
            "user": user, "search": search, "results": active_results,
            "sort": sort_mode, "active_platforms": platform_set,
        },
    )


@router.get("/searches/{search_id}/discarded")
def search_discarded(
    request: Request, search_id: int, sort: str = "newest", platforms: str = "",
    user: User = Depends(get_current_user),
):
    search = _get_owned_search_or_404(search_id, user)
    sort_mode = _sort_param(sort)
    platform_set = _platforms_param(platforms)
    discarded_results = results.list_discarded_results(
        search_id, sort=sort_mode, origin=_search_origin(search), platforms=platform_set
    )
    return templates.TemplateResponse(
        request,
        "search_discarded.html",
        {
            "user": user, "search": search, "results": discarded_results,
            "discarded": True, "sort": sort_mode, "active_platforms": platform_set,
        },
    )


@router.get("/searches/{search_id}/edit")
def edit_search_form(request: Request, search_id: int, user: User = Depends(get_current_user)):
    search = _get_owned_search_or_404(search_id, user)
    return templates.TemplateResponse(
        request, "search_form.html", {"user": user, "search": search, "error": None}
    )


@router.post("/searches/{search_id}/edit")
def edit_search_submit(
    request: Request,
    search_id: int,
    user: User = Depends(get_current_user),
    name: str = Form(...),
    title_keywords: str = Form(...),
    content_keywords: str = Form(""),
    min_price: str = Form(""),
    max_price: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    radius_km: str = Form(""),
    excluded_words: str = Form(""),
    shipping_filter: str = Form("any"),
    search_wallapop: bool = Form(False),
    search_cashconverters: bool = Form(False),
    search_cex: bool = Form(False),
    search_milanuncios: bool = Form(False),
    scan_interval_minutes: int = Form(60),
    notify_enabled: bool = Form(False),
):
    search = _get_owned_search_or_404(search_id, user)
    if not search_wallapop and not search_cashconverters and not search_cex and not search_milanuncios:
        return templates.TemplateResponse(
            request,
            "search_form.html",
            {"user": user, "search": search, "error": "Activa al menos una tienda."},
            status_code=400,
        )
    update_search(
        search.id,
        name=name,
        title_keywords=title_keywords,
        content_keywords=content_keywords or None,
        min_price=float(min_price) if min_price else None,
        max_price=float(max_price) if max_price else None,
        latitude=float(latitude) if latitude else None,
        longitude=float(longitude) if longitude else None,
        radius_km=float(radius_km) if radius_km else None,
        excluded_words=excluded_words or None,
        shipping_filter=shipping_filter,
        search_wallapop=search_wallapop,
        search_cashconverters=search_cashconverters,
        search_cex=search_cex,
        search_milanuncios=search_milanuncios,
        scan_interval_minutes=scan_interval_minutes,
        notify_enabled=notify_enabled,
    )
    updated = get_search_for_user(search_id, user.id)
    scheduler.reschedule_search(updated)
    return RedirectResponse(url=f"/searches/{search_id}", status_code=303)


@router.post("/searches/{search_id}/move")
def move_search_submit(
    request: Request, search_id: int, user: User = Depends(get_current_user), category_id: str = Form(""),
):
    _get_owned_search_or_404(search_id, user)
    target_id = int(category_id) if category_id else None
    if target_id is not None and get_category_for_user(target_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    update_search(search_id, category_id=target_id)
    return RedirectResponse(url="/", status_code=303)


@router.post("/searches/{search_id}/toggle")
def toggle_search(request: Request, search_id: int, user: User = Depends(get_current_user)):
    search = _get_owned_search_or_404(search_id, user)
    set_active(search_id, not search.is_active)
    updated = get_search_for_user(search_id, user.id)
    scheduler.reschedule_search(updated)
    return RedirectResponse(url="/", status_code=303)


@router.post("/searches/{search_id}/delete")
def delete_search_submit(request: Request, search_id: int, user: User = Depends(get_current_user)):
    _get_owned_search_or_404(search_id, user)
    scheduler.unschedule_search(search_id)
    delete_search(search_id)
    return RedirectResponse(url="/", status_code=303)


@router.post("/searches/{search_id}/scan")
def manual_scan(request: Request, search_id: int, user: User = Depends(get_current_user)):
    _get_owned_search_or_404(search_id, user)
    scanner.scan_search(search_id, notify=False)
    return RedirectResponse(url=f"/searches/{search_id}", status_code=303)
