"""Feeds: Feed-Typ → Discord-Channel zuordnen (wie ``/setup feeds``)."""

from __future__ import annotations

from aiohttp import web

from ..context import ctx
from .common import body, err, ok


def _guild_payload(gid: int) -> dict:
    bot = ctx.bot
    cfg = ctx.cfg
    g = bot.get_guild(int(gid)) if bot else None
    channels = []
    if g is not None:
        for ch in getattr(g, "text_channels", []):
            channels.append({"id": str(ch.id), "name": ch.name,
                             "category": getattr(ch.category, "name", None)})
        channels.sort(key=lambda c: (c["category"] or "", c["name"].lower()))
    feeds = {k: str(v) for k, v in (cfg.guilds.get(str(gid), {}) or {}).items()
             if isinstance(v, int) or (isinstance(v, str) and str(v).isdigit())}
    return {
        "id": str(gid),
        "name": (g.name if g is not None else f"Guild {gid}"),
        "available": g is not None,
        "channels": channels,
        "feeds": feeds,
    }


async def get_feeds(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    log_types = ctx.g("LOG_TYPES", {})
    guild_ids = list(cfg.config.get("guild_ids", []) or [])
    for gid in cfg.guilds.keys():
        try:
            if int(gid) not in [int(x) for x in guild_ids]:
                guild_ids.append(int(gid))
        except (TypeError, ValueError):
            continue
    return ok({
        "log_types": [{"key": k, "label": v} for k, v in log_types.items()],
        "guilds": [_guild_payload(int(gid)) for gid in guild_ids],
    })


async def set_feed(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    log_types = ctx.g("LOG_TYPES", {})
    gid = request.match_info["guild_id"]
    log_type = request.match_info["log_type"]
    if log_type not in log_types:
        return err(f"Unbekannter Feed-Typ: {log_type}")
    data = await body(request)
    channel_id = data.get("channel_id")
    guilds = cfg.guilds.setdefault(str(gid), {})
    if channel_id in (None, "", "0"):
        guilds.pop(log_type, None)
        cfg.save_guilds()
        return ok({"cleared": True})
    try:
        cfg.set_channel(int(gid), log_type, int(channel_id))
    except (TypeError, ValueError):
        return err("Ungültige Channel-ID.")
    return ok({"log_type": log_type, "channel_id": str(channel_id)})
