"""Gemeinsame Helfer für die API-Handler."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..context import ctx


def ok(data: Any = None, **extra) -> web.Response:
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return web.json_response(payload)


def err(message: str, status: int = 400, **extra) -> web.Response:
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return web.json_response(payload, status=status)


async def body(request: web.Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def require_nitrado():
    """Gibt (nitrado, None) zurück oder (None, Fehlerantwort), wenn nicht eingerichtet."""
    bot = ctx.bot
    nit = getattr(bot, "nitrado", None) if bot else None
    if not nit or not str(getattr(nit, "service_id", "") or "").strip():
        return None, err("Nitrado-Server ist noch nicht eingerichtet.", 409)
    return nit, None
