"""Shop-Katalog: Items & Bundles anlegen/bearbeiten, Autofill der Classnames.

Nutzt den vorhandenen ``ShopCatalog`` (``catalog``). Ein "Bundle" ist ein Item
mit mehreren ``classnames``; ein Einzelitem hat ``classname``. Persistiert wie
der Bot über ``catalog.save()`` – bei Quelle ``config.json`` wird zusätzlich
``config["shop_items"]`` gespiegelt, damit auch Hinzufügen/Löschen dauerhaft ist.
"""

from __future__ import annotations

import re
from typing import List

from aiohttp import web

from ..context import ctx
from .common import body, err, ok


def _classnames(it: dict) -> List[str]:
    fn = ctx.g("_item_classnames")
    if callable(fn):
        return fn(it)
    cls = it.get("classnames")
    if isinstance(cls, list) and cls:
        return [str(c) for c in cls]
    return [str(it["classname"])] if it.get("classname") else []


def _persist() -> bool:
    """catalog.save() + bei config.json-Quelle die Liste spiegeln."""
    catalog = ctx.catalog
    if getattr(catalog, "source", "") == "config.json":
        ctx.cfg.config["shop_items"] = catalog.items
    return bool(catalog.save())


def _item_view(it: dict) -> dict:
    cls = _classnames(it)
    return {
        "name": str(it.get("name") or (cls[0] if cls else "?")),
        "classnames": cls,
        "is_bundle": len(cls) > 1,
        "price": int(it.get("price", 0)),
        "category": str(it.get("category", "Misc")),
        "enabled": bool(it.get("enabled", True)),
        "max_amount_per_buy": int(it.get("max_amount_per_buy", 1)),
        "custom": bool(it.get("custom", False)),
    }


async def list_items(request: web.Request) -> web.Response:
    catalog = ctx.catalog
    q = request.query.get("q", "").strip().lower()
    category = request.query.get("category", "").strip()
    try:
        page = max(1, int(request.query.get("page", 1)))
        page_size = min(200, max(1, int(request.query.get("page_size", 50))))
    except ValueError:
        page, page_size = 1, 50

    items = catalog.items
    if category:
        items = [it for it in items if str(it.get("category", "Misc")) == category]
    if q:
        def match(it):
            hay = " ".join([str(it.get("name", "")).lower()] +
                           [c.lower() for c in _classnames(it)])
            return q in hay
        items = [it for it in items if match(it)]

    total = len(items)
    start = (page - 1) * page_size
    view = [_item_view(it) for it in items[start:start + page_size]]
    return ok({"items": view, "total": total, "page": page, "page_size": page_size,
               "source": getattr(catalog, "source", "?")})


async def categories(request: web.Request) -> web.Response:
    catalog = ctx.catalog
    cfg = ctx.cfg
    counts = {k: len(v) for k, v in getattr(catalog, "by_category", {}).items()}
    names = set(counts)
    names.update((cfg.config.get("shop_category_prices") or {}).keys())
    names.update(cfg.config.get("shop_categories_custom", []) or [])
    cats = [{"name": n, "count": counts.get(n, 0),
             "default_price": (cfg.config.get("shop_category_prices") or {}).get(n)}
            for n in sorted(names, key=str.lower)]
    return ok({"categories": cats,
               "default_price": int(cfg.config.get("shop_default_price", 100))})


async def classnames(request: web.Request) -> web.Response:
    """Autofill: Classnames (Einzelitems) per Substring-Suche."""
    catalog = ctx.catalog
    q = request.query.get("q", "").strip().lower()
    limit = min(50, max(1, int(request.query.get("limit", 25) or 25)))
    out = []
    seen = set()
    for it in catalog.items:
        cls = _classnames(it)
        if len(cls) != 1:
            continue  # Bundles nicht als Classname vorschlagen
        cn = cls[0]
        key = cn.lower()
        if key in seen:
            continue
        name = str(it.get("name") or cn)
        if not q or q in key or q in name.lower():
            seen.add(key)
            out.append({"classname": cn, "name": name,
                        "category": str(it.get("category", "Misc"))})
            if len(out) >= limit:
                break
    return ok({"classnames": out})


def _split_classnames(raw) -> List[str]:
    if isinstance(raw, list):
        toks = [str(t) for t in raw]
    else:
        toks = re.split(r"[,;\s]+", str(raw or "").strip())
    parts, seen = [], set()
    for tok in toks:
        tok = tok.strip()
        if tok and tok.lower() not in seen:
            seen.add(tok.lower())
            parts.append(tok)
    return parts


async def create_item(request: web.Request) -> web.Response:
    catalog = ctx.catalog
    data = await body(request)
    parts = _split_classnames(data.get("classnames") or data.get("classname"))
    if not parts:
        return err("Mindestens einen Classname angeben (z. B. M4A1 oder "
                   "M4A1, Mag_STANAG_60Rnd für ein Bundle).")
    is_bundle = len(parts) > 1
    display = str(data.get("name", "")).strip() or (
        f"{parts[0]} Bundle ({len(parts)} items)" if is_bundle else parts[0])
    if catalog.find(display):
        return err(f"'{display}' existiert bereits im Katalog. Anderen Namen wählen "
                   f"oder den Eintrag zuerst löschen.")

    try:
        price = int(data.get("price"))
    except (TypeError, ValueError):
        # Kategorie-Standardpreis als Fallback
        cat_prices = ctx.cfg.config.get("shop_category_prices") or {}
        price = int(cat_prices.get(str(data.get("category", "")).strip(),
                                   ctx.cfg.config.get("shop_default_price", 100)))
    if price < 0:
        return err("Preis darf nicht negativ sein.")

    cat = str(data.get("category", "")).strip() or ("Bundles" if is_bundle else "Custom")
    try:
        mx = int(data.get("max_amount_per_buy") or data.get("limit") or (1 if is_bundle else 5))
    except (TypeError, ValueError):
        mx = 1 if is_bundle else 5
    mx = max(1, mx)

    it = {
        "name": display[:100],
        "price": price,
        "category": cat,
        "enabled": bool(data.get("enabled", True)),
        "max_amount_per_buy": mx,
        "custom": True,
    }
    if is_bundle:
        it["classnames"] = parts
    else:
        it["classname"] = parts[0]

    # Unbekannte Classnames (Tippfehler-Hinweis, nicht blockierend)
    unknown = [c for c in parts if catalog.find(c) is None]

    catalog.items.append(it)
    saved = _persist()
    # neue Kategorie ggf. als custom merken
    if cat not in (getattr(catalog, "by_category", {}) or {}):
        _remember_category(cat)
    return ok({"item": _item_view(it), "saved": saved, "unknown_classnames": unknown})


async def update_item(request: web.Request) -> web.Response:
    catalog = ctx.catalog
    it = catalog.find(request.match_info["name"])
    if not it:
        return err("Item nicht gefunden.", 404)
    data = await body(request)

    if "name" in data:
        new_name = str(data["name"]).strip()
        if new_name and new_name.lower() != str(it.get("name", "")).lower():
            if catalog.find(new_name):
                return err(f"'{new_name}' existiert bereits.")
            it["name"] = new_name[:100]
    if "price" in data:
        try:
            it["price"] = max(0, int(data["price"]))
        except (TypeError, ValueError):
            return err("Preis muss eine Zahl sein.")
    if "category" in data and str(data["category"]).strip():
        it["category"] = str(data["category"]).strip()
        _remember_category(it["category"])
    if "enabled" in data:
        it["enabled"] = bool(data["enabled"])
    if "max_amount_per_buy" in data or "limit" in data:
        try:
            it["max_amount_per_buy"] = max(1, int(data.get("max_amount_per_buy") or data.get("limit")))
        except (TypeError, ValueError):
            return err("Limit muss eine Zahl ≥ 1 sein.")
    if "classnames" in data or "classname" in data:
        parts = _split_classnames(data.get("classnames") or data.get("classname"))
        if not parts:
            return err("Mindestens einen Classname angeben.")
        it.pop("classname", None)
        it.pop("classnames", None)
        if len(parts) > 1:
            it["classnames"] = parts
        else:
            it["classname"] = parts[0]

    saved = _persist()
    return ok({"item": _item_view(it), "saved": saved})


async def delete_item(request: web.Request) -> web.Response:
    catalog = ctx.catalog
    it = catalog.find(request.match_info["name"])
    if not it:
        return err("Item nicht gefunden.", 404)
    try:
        catalog.items.remove(it)
    except ValueError:
        pass
    saved = _persist()
    return ok({"removed": str(it.get("name")), "saved": saved})


def _remember_category(cat: str) -> None:
    cfg = ctx.cfg
    lst = cfg.config.setdefault("shop_categories_custom", [])
    if cat and cat not in lst:
        lst.append(cat)
        cfg.save_config()


async def add_category(request: web.Request) -> web.Response:
    data = await body(request)
    cat = str(data.get("name", "")).strip()
    if not cat:
        return err("Kategoriename fehlt.")
    if len(cat) > 60:
        return err("Kategoriename ist zu lang.")
    _remember_category(cat)
    return ok({"category": cat})
