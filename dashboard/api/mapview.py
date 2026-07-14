"""Karte & Events: Kartendaten, Live-Spielerpositionen, letzte Events."""

from __future__ import annotations

import re

from aiohttp import web

from .. import events as devents
from ..context import ctx
from .common import ok

# Welt-Kantenlänge je Karte in Metern (für die Leaflet-CRS-Skalierung).
# Überschreibbar via config["dashboard_map_sizes"].
DEFAULT_MAP_SIZES = {
    "ChernarusPlus": 15360,
    "Livonia": 12800,
    "Sakhal": 15360,
}

_POS_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _world_size(map_name: str) -> int:
    sizes = dict(DEFAULT_MAP_SIZES)
    sizes.update(ctx.cfg.config.get("dashboard_map_sizes", {}) or {})
    return int(sizes.get(map_name, 15360))


def _locations(map_name: str):
    locs = ctx.g("_MAP_LOCATIONS", {}) or {}
    data = locs.get(map_name) or locs.get("ChernarusPlus") or []
    return [{"name": n, "x": x, "z": z} for (n, x, z) in data]


async def map_meta(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    map_name = cfg.config.get("map_name", "ChernarusPlus")
    tiles = (cfg.config.get("dashboard_map_tiles") or {}).get(map_name) or ""
    return ok({
        "map_name": map_name,
        "world_size": _world_size(map_name),
        "tile_url": tiles,          # optionales XYZ-Template ({z}/{x}/{y})
        "image": f"/maps/{map_name}.jpg",  # optionales Bild (ImageOverlay), falls vorhanden
        "locations": _locations(map_name),
        "izurvive": f"https://www.izurvive.com/?m={map_name}",
    })


async def players(request: web.Request) -> web.Response:
    bot = ctx.bot
    parser = getattr(bot, "parser", None) if bot else None
    positions = getattr(parser, "player_positions", {}) if parser else {}
    nearest_fn = ctx.g("_nearest_location")
    map_name = ctx.cfg.config.get("map_name", "ChernarusPlus")
    out = []
    for name, entry in list(positions.items()):
        if not isinstance(entry, dict):
            continue
        nums = _POS_RE.findall(str(entry.get("position", "")))
        if len(nums) < 2:
            continue
        try:
            x, z = round(float(nums[0]), 1), round(float(nums[1]), 1)
        except ValueError:
            continue
        near = None
        if callable(nearest_fn):
            try:
                near = nearest_fn(x, z, map_name)
            except Exception:
                near = None
        out.append({"name": name, "x": x, "z": z,
                    "last_seen": entry.get("last_seen"), "near": near})
    return ok({"players": out, "map_name": map_name})


async def events(request: web.Request) -> web.Response:
    try:
        since = int(request.query.get("since", 0))
    except ValueError:
        since = 0
    types = request.query.get("types")
    tlist = [t for t in types.split(",") if t] if types else None
    snap = devents.snapshot(since_id=since, types=tlist)
    return ok(snap)


async def event_types(request: web.Request) -> web.Response:
    return ok({"types": devents.types_meta()})
