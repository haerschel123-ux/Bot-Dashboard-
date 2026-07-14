"""Bans & Whitelist über die Nitrado-Gameserver-Settings (wie im Web-Interface).

Nutzt die vorhandenen async-Helfer ``_read_banlist``/``_write_banlist`` bzw.
``_read_whitelist``/``_write_whitelist`` des Bots.
"""

from __future__ import annotations

from aiohttp import web

from ..context import ctx
from .common import body, err, ok


async def _read(kind: str):
    fn = ctx.g(f"_read_{kind}")
    if not callable(fn):
        return None
    return await fn()  # (names, category, key)


async def _write(kind: str, names, category, key):
    fn = ctx.g(f"_write_{kind}")
    if not callable(fn):
        return False, "Funktion nicht verfügbar."
    return await fn(names, category, key)


def _make_get(kind: str):
    async def handler(request: web.Request) -> web.Response:
        try:
            names, cat, key = await _read(kind)
        except Exception as e:  # noqa: BLE001
            return err(f"Nitrado nicht erreichbar: {e}", 502)
        return ok({"names": names, "category": cat, "key": key})
    return handler


def _make_add(kind: str):
    async def handler(request: web.Request) -> web.Response:
        data = await body(request)
        player = str(data.get("player", "")).strip()
        if not player:
            return err("Spielername fehlt.")
        try:
            names, cat, key = await _read(kind)
        except Exception as e:  # noqa: BLE001
            return err(f"Nitrado nicht erreichbar: {e}", 502)
        if player.lower() not in [n.lower() for n in names]:
            names.append(player)
            good, msg = await _write(kind, names, cat, key)
            if not good:
                return err(msg or "Speichern fehlgeschlagen.", 502)
        return ok({"names": names})
    return handler


def _make_remove(kind: str):
    async def handler(request: web.Request) -> web.Response:
        player = request.match_info["player"]
        try:
            names, cat, key = await _read(kind)
        except Exception as e:  # noqa: BLE001
            return err(f"Nitrado nicht erreichbar: {e}", 502)
        new = [n for n in names if n.lower() != player.lower()]
        if len(new) != len(names):
            good, msg = await _write(kind, new, cat, key)
            if not good:
                return err(msg or "Speichern fehlgeschlagen.", 502)
        return ok({"names": new})
    return handler


get_bans = _make_get("banlist")
add_ban = _make_add("banlist")
remove_ban = _make_remove("banlist")
get_whitelist = _make_get("whitelist")
add_whitelist = _make_add("whitelist")
remove_whitelist = _make_remove("whitelist")
