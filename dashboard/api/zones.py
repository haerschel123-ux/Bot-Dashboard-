"""Zonen verwalten (wie ``/zone create|edit|remove|list`` + Allowlist).

Zonen liegen in ``config.json["zones"]``. Schema:
``{name, x, z, radius, role_id?, channel_id?, guild_id, allowlist?}`` –
x = Ost (iZurvive), z = Nord.
"""

from __future__ import annotations

from aiohttp import web

from ..context import ctx
from .common import body, err, ok


def _zones() -> list:
    z = ctx.cfg.config.setdefault("zones", [])
    if not isinstance(z, list):
        z = []
        ctx.cfg.config["zones"] = z
    return z


def _find(name: str):
    n = (name or "").strip().lower()
    for z in _zones():
        if isinstance(z, dict) and str(z.get("name", "")).lower() == n:
            return z
    return None


def _default_guild() -> int:
    gids = ctx.cfg.config.get("guild_ids", []) or []
    return int(gids[0]) if gids else 0


async def list_zones(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    zones = [z for z in _zones() if isinstance(z, dict) and z.get("name")]
    return ok({"zones": zones, "map_name": cfg.config.get("map_name", "ChernarusPlus")})


async def create_zone(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    data = await body(request)
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 60:
        return err("Zonen-Name fehlt oder ist länger als 60 Zeichen.")
    if _find(name):
        return err(f"Zone '{name}' existiert bereits.")
    try:
        x = float(data["x"]); z = float(data["z"]); radius = float(data["radius"])
    except (KeyError, TypeError, ValueError):
        return err("x, z und radius müssen Zahlen sein.")

    validate = ctx.g("_validate_zone_geometry")
    if validate:
        geo_err = validate(x, z, radius)
        if geo_err:
            return err(geo_err.replace("❌", "").strip())

    zone = {
        "name": name,
        "x": round(x, 1), "z": round(z, 1), "radius": round(radius, 1),
        "role_id": int(data["role_id"]) if data.get("role_id") else None,
        "channel_id": int(data["channel_id"]) if data.get("channel_id") else None,
        "guild_id": int(data.get("guild_id") or _default_guild()),
    }
    _zones().append(zone)
    cfg.save_config()
    return ok(zone)


async def update_zone(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    zone = _find(request.match_info["name"])
    if not zone:
        return err("Zone nicht gefunden.", 404)
    data = await body(request)

    new_name = str(data.get("name", zone["name"])).strip() or zone["name"]
    if new_name.lower() != str(zone["name"]).lower() and _find(new_name):
        return err(f"Zone '{new_name}' existiert bereits.")
    try:
        x = float(data.get("x", zone["x"]))
        z = float(data.get("z", zone["z"]))
        radius = float(data.get("radius", zone["radius"]))
    except (TypeError, ValueError):
        return err("x, z und radius müssen Zahlen sein.")

    validate = ctx.g("_validate_zone_geometry")
    if validate:
        geo_err = validate(x, z, radius)
        if geo_err:
            return err(geo_err.replace("❌", "").strip())

    zone["name"] = new_name
    zone["x"], zone["z"], zone["radius"] = round(x, 1), round(z, 1), round(radius, 1)
    if "role_id" in data:
        zone["role_id"] = int(data["role_id"]) if data.get("role_id") else None
    if "channel_id" in data:
        zone["channel_id"] = int(data["channel_id"]) if data.get("channel_id") else None
    cfg.save_config()
    return ok(zone)


async def delete_zone(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    zone = _find(request.match_info["name"])
    if not zone:
        return err("Zone nicht gefunden.", 404)
    name = str(zone["name"])
    _zones().remove(zone)
    cfg.save_config()
    # Ping-Cooldown-Status im Bot zurücksetzen (wie /zone remove), falls vorhanden
    reset = ctx.g("_reset_zone_state")
    if callable(reset):
        try:
            reset(name)
        except Exception:
            pass
    return ok({"removed": name})


# ── Allowlist ─────────────────────────────────────────────────
async def get_allowlist(request: web.Request) -> web.Response:
    zone = _find(request.match_info["name"])
    if not zone:
        return err("Zone nicht gefunden.", 404)
    return ok({"allowlist": zone.get("allowlist", [])})


async def add_allowlist(request: web.Request) -> web.Response:
    zone = _find(request.match_info["name"])
    if not zone:
        return err("Zone nicht gefunden.", 404)
    data = await body(request)
    player = str(data.get("player", "")).strip()
    if not player:
        return err("Spielername fehlt.")
    al = zone.setdefault("allowlist", [])
    if player.lower() not in [str(p).lower() for p in al]:
        al.append(player)
        ctx.cfg.save_config()
    return ok({"allowlist": al})


async def remove_allowlist(request: web.Request) -> web.Response:
    zone = _find(request.match_info["name"])
    if not zone:
        return err("Zone nicht gefunden.", 404)
    player = request.match_info["player"]
    al = zone.get("allowlist", [])
    zone["allowlist"] = [p for p in al if str(p).lower() != player.lower()]
    ctx.cfg.save_config()
    return ok({"allowlist": zone["allowlist"]})


# ── Rollen/Channels für Picker ────────────────────────────────
async def guild_roles(request: web.Request) -> web.Response:
    bot = ctx.bot
    g = bot.get_guild(int(request.match_info["guild_id"])) if bot else None
    if g is None:
        return ok({"roles": []})
    roles = [{"id": str(r.id), "name": r.name}
             for r in g.roles if not r.is_default()]
    return ok({"roles": roles})


async def guild_channels(request: web.Request) -> web.Response:
    bot = ctx.bot
    g = bot.get_guild(int(request.match_info["guild_id"])) if bot else None
    if g is None:
        return ok({"channels": []})
    channels = [{"id": str(c.id), "name": c.name} for c in g.text_channels]
    return ok({"channels": channels})
