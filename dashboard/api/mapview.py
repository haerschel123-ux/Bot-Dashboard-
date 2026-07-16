"""Karte & Events: Kartendaten, Live-Spielerpositionen, letzte Events."""

from __future__ import annotations

import json
import os
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

# Kanonischer Map-Name → Ordner der öffentlichen Kachelquelle (xam.nu).
# Die Kacheln lädt der Browser direkt – unabhängig von der Host-Netzpolicy.
_XAM_FOLDER = {
    "ChernarusPlus": "chernarusplus",
    "Livonia": "livonia",
    "Sakhal": "sakhal",
}
_XAM_TEMPLATE = "https://static.xam.nu/dayz/maps/{folder}/1.27/topographic/{{z}}/{{x}}/{{y}}.webp"
TILE_MAX_NATIVE_ZOOM = 7

_POS_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _world_size(map_name: str) -> int:
    sizes = dict(DEFAULT_MAP_SIZES)
    sizes.update(ctx.cfg.config.get("dashboard_map_sizes", {}) or {})
    return int(sizes.get(map_name, 15360))


def _tile_url(map_name: str) -> str:
    """Kachel-URL je Karte: config-Override → xam.nu-Default → '' (dann Fallback)."""
    override = (ctx.cfg.config.get("dashboard_map_tiles") or {}).get(map_name)
    if override:
        return str(override)
    folder = _XAM_FOLDER.get(map_name)
    return _XAM_TEMPLATE.format(folder=folder) if folder else ""


# Gebündelte, exakte Ortslisten (dashboard/static/locations/<Karte>.json),
# generiert aus den Kartendaten von dayz.xam.nu – einmal geladen, dann gecacht.
_LOCATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "static", "locations")
_locations_cache: dict = {}


def _locations(map_name: str):
    if map_name in _locations_cache:
        return _locations_cache[map_name]
    out = []
    path = os.path.join(_LOCATIONS_DIR, f"{map_name}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = [{"name": l["name"], "x": l["x"], "z": l["z"], "t": l.get("t", "local")}
               for l in data.get("locations", [])
               if l.get("name") and isinstance(l.get("x"), (int, float))]
    except Exception:
        out = []
    if not out:
        # Fallback: grobe Ortsliste aus dem Bot (_MAP_LOCATIONS)
        locs = ctx.g("_MAP_LOCATIONS", {}) or {}
        data = locs.get(map_name) or locs.get("ChernarusPlus") or []
        out = [{"name": n, "x": x, "z": z, "t": "city"} for (n, x, z) in data]
    _locations_cache[map_name] = out
    return out


async def map_meta(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    map_name = cfg.config.get("map_name", "ChernarusPlus")
    return ok({
        "map_name": map_name,
        "world_size": _world_size(map_name),
        "tile_url": _tile_url(map_name),      # XYZ-Template ({z}/{x}/{y}), Browser lädt es
        "tile_max_native_zoom": TILE_MAX_NATIVE_ZOOM,
        "image": f"/maps/{map_name}.jpg",     # optionales eigenes Bild (ImageOverlay), falls vorhanden
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
