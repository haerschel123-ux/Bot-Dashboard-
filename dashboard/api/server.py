"""Server-Steuerung: Status, Neustart, Stopp (reuse NitradoAPI + A2S)."""

from __future__ import annotations

from aiohttp import web

from ..context import ctx
from .common import err, ok, require_nitrado


async def status(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    a2s = ctx.g("a2s_query")
    ip = cfg.config.get("server_ip") or ""
    port = int(cfg.config.get("query_port", 2302) or 2302)
    live = None
    if callable(a2s) and ip:
        try:
            live = await ctx.run(lambda: a2s(ip, port))
        except Exception:
            live = None
    nit_info = None
    nit = getattr(ctx.bot, "nitrado", None)
    if nit and str(getattr(nit, "service_id", "") or "").strip():
        try:
            info = await nit.get_info()
            if info:
                q = info.get("query") or {}
                nit_info = {
                    "state": info.get("status") or info.get("state"),
                    "players": q.get("player_current"),
                    "max_players": q.get("player_max"),
                    "map": q.get("map"),
                }
        except Exception:
            nit_info = None
    return ok({
        "online": bool(live),
        "a2s": live,
        "nitrado": nit_info,
        "map_name": cfg.config.get("map_name"),
        "server_ip": ip or None,
    })


async def restart(request: web.Request) -> web.Response:
    nit, e = require_nitrado()
    if e:
        return e
    okflag, msg = await nit.restart()
    return (ok({"message": msg}) if okflag else err(msg or "Neustart fehlgeschlagen.", 502))


async def stop(request: web.Request) -> web.Response:
    nit, e = require_nitrado()
    if e:
        return e
    okflag, msg = await nit.stop()
    return (ok({"message": msg}) if okflag else err(msg or "Stopp fehlgeschlagen.", 502))
