"""Session-/Zugangsschutz für das Dashboard.

Gemäß Nutzerwahl gibt es KEIN separates Passwort – das Gate ist ein gültiger
Nitrado-Token. Nach erfolgreicher Token-Prüfung (Nitrado liefert Gameserver)
wird eine Server-seitige Session angelegt; der Browser bekommt nur eine
zufällige Session-ID als Cookie, der Token selbst verlässt den Server nie.

Ein optionaler Passwort-Hook ist vorbereitet (``DASHBOARD_PASSWORD`` in der
config), bleibt hier aber standardmäßig deaktiviert.
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, Optional

from aiohttp import web

COOKIE = "dz_sess"
_TTL = 60 * 60 * 12  # 12 Stunden

# session_id → {token, service_id, gameservers, map_name, created, seen}
_SESSIONS: Dict[str, Dict[str, Any]] = {}

# Pfade, die ohne Session erreichbar sind
_PUBLIC_PREFIXES = ("/api/auth/", "/static/", "/vendor/", "/maps/")
_PUBLIC_EXACT = ("/", "/index.html", "/api/session", "/favicon.ico", "/api/health")


def _prune() -> None:
    now = time.time()
    for sid in [s for s, v in _SESSIONS.items() if now - v.get("seen", 0) > _TTL]:
        _SESSIONS.pop(sid, None)


def create_session(token: str, gameservers: list) -> str:
    _prune()
    sid = secrets.token_urlsafe(32)
    now = time.time()
    _SESSIONS[sid] = {
        "token": token,
        "gameservers": gameservers,
        "service_id": None,
        "map_name": None,
        "created": now,
        "seen": now,
    }
    return sid


def get_session(request: web.Request) -> Optional[Dict[str, Any]]:
    sid = request.cookies.get(COOKIE)
    if not sid:
        return None
    sess = _SESSIONS.get(sid)
    if not sess:
        return None
    if time.time() - sess.get("seen", 0) > _TTL:
        _SESSIONS.pop(sid, None)
        return None
    sess["seen"] = time.time()
    return sess


def destroy_session(request: web.Request) -> None:
    sid = request.cookies.get(COOKIE)
    if sid:
        _SESSIONS.pop(sid, None)


def attach_cookie(response: web.Response, sid: str) -> None:
    response.set_cookie(COOKIE, sid, httponly=True, samesite="Lax",
                        max_age=_TTL, path="/")


def is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Blockt geschützte /api/-Pfade ohne gültige Session mit 401."""
    path = request.path
    if path.startswith("/api/") and not is_public(path):
        sess = get_session(request)
        if not sess:
            return web.json_response(
                {"error": "unauthorized",
                 "message": "Bitte zuerst den Nitrado-Token eingeben."},
                status=401)
        request["session"] = sess
    return await handler(request)
