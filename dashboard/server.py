"""aiohttp-Web-Server des Dashboards – läuft im Event-Loop des Bots."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from aiohttp import web

from . import auth, events as devents
from .context import ctx
from .api import (announcements, autotasks, bans, economy, feeds, mapview,
                  server as srv, session, shop, zones)

log = logging.getLogger("dashboard")

_STATIC = os.path.join(os.path.dirname(__file__), "static")
_runner: Optional[web.AppRunner] = None


async def _index(request: web.Request) -> web.Response:
    path = os.path.join(_STATIC, "index.html")
    if not os.path.exists(path):
        return web.Response(text="Dashboard-Frontend fehlt (index.html).", status=500)
    return web.FileResponse(path)


async def _health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "ready": ctx.ready})


async def _maps(request: web.Request) -> web.Response:
    """Optionale Kartenbilder aus static/maps/<Name>.jpg ausliefern (404 wenn keins)."""
    name = os.path.basename(request.match_info["name"])
    path = os.path.join(_STATIC, "maps", name)
    if os.path.exists(path):
        return web.FileResponse(path)
    return web.Response(status=404)


def build_app() -> web.Application:
    app = web.Application(middlewares=[auth.auth_middleware])
    r = app.router

    # ── Seite & Statisches ──
    r.add_get("/", _index)
    r.add_get("/index.html", _index)
    r.add_get("/api/health", _health)
    r.add_get("/maps/{name}", _maps)
    if os.path.isdir(_STATIC):
        r.add_static("/static/", _STATIC, show_index=False)
        vendor = os.path.join(_STATIC, "vendor")
        if os.path.isdir(vendor):
            r.add_static("/vendor/", vendor, show_index=False)

    # ── Auth / Session ──
    r.add_post("/api/auth/token", session.post_token)
    r.add_post("/api/auth/select-server", session.post_select_server)
    r.add_post("/api/auth/logout", session.post_logout)
    r.add_get("/api/session", session.get_session)

    # ── Feeds ──
    r.add_get("/api/feeds", feeds.get_feeds)
    r.add_post("/api/feeds/{guild_id}/{log_type}", feeds.set_feed)

    # ── Zones ──
    r.add_get("/api/zones", zones.list_zones)
    r.add_post("/api/zones", zones.create_zone)
    r.add_put("/api/zones/{name}", zones.update_zone)
    r.add_delete("/api/zones/{name}", zones.delete_zone)
    r.add_get("/api/zones/{name}/allowlist", zones.get_allowlist)
    r.add_post("/api/zones/{name}/allowlist", zones.add_allowlist)
    r.add_delete("/api/zones/{name}/allowlist/{player}", zones.remove_allowlist)
    r.add_get("/api/guild/{guild_id}/roles", zones.guild_roles)
    r.add_get("/api/guild/{guild_id}/channels", zones.guild_channels)

    # ── Auto-Aufgaben ──
    r.add_get("/api/auto-restart", autotasks.get_auto_restart)
    r.add_post("/api/auto-restart", autotasks.set_auto_restart)

    # ── Shop ──
    r.add_get("/api/shop/items", shop.list_items)
    r.add_get("/api/shop/categories", shop.categories)
    r.add_get("/api/shop/classnames", shop.classnames)
    r.add_post("/api/shop/items", shop.create_item)
    r.add_put("/api/shop/items/{name}", shop.update_item)
    r.add_delete("/api/shop/items/{name}", shop.delete_item)
    r.add_post("/api/shop/categories", shop.add_category)

    # ── Karte / Events ──
    r.add_get("/api/map/meta", mapview.map_meta)
    r.add_get("/api/map/players", mapview.players)
    r.add_get("/api/events", mapview.events)
    r.add_get("/api/events/types", mapview.event_types)

    # ── Extras: Bans/Whitelist ──
    r.add_get("/api/bans", bans.get_bans)
    r.add_post("/api/bans", bans.add_ban)
    r.add_delete("/api/bans/{player}", bans.remove_ban)
    r.add_get("/api/whitelist", bans.get_whitelist)
    r.add_post("/api/whitelist", bans.add_whitelist)
    r.add_delete("/api/whitelist/{player}", bans.remove_whitelist)

    # ── Extras: Economy ──
    r.add_get("/api/economy/balances", economy.balances)
    r.add_post("/api/economy/money", economy.money)
    r.add_get("/api/economy/config", economy.get_config)
    r.add_post("/api/economy/config", economy.set_config)

    # ── Extras: Ankündigungen ──
    r.add_get("/api/announcements", announcements.list_announcements)
    r.add_post("/api/announcements", announcements.create_announcement)
    r.add_delete("/api/announcements/{index}", announcements.delete_announcement)

    # ── Extras: Server-Steuerung ──
    r.add_get("/api/server/status", srv.status)
    r.add_post("/api/server/restart", srv.restart)
    r.add_post("/api/server/stop", srv.stop)

    return app


def _resolve_port() -> int:
    try:
        cfg_port = ctx.cfg.config.get("dashboard_port")
    except Exception:
        cfg_port = None
    for cand in (os.environ.get("SERVER_PORT"), os.environ.get("PORT"), cfg_port):
        if cand:
            try:
                return int(cand)
            except (TypeError, ValueError):
                continue
    return 8080


async def start_dashboard(bot: Any) -> None:
    """Bindet den Bot ans Dashboard und startet den Web-Server (idempotent)."""
    global _runner
    if _runner is not None:
        return
    ctx.bind(bot)
    devents.load()

    if not ctx.cfg.config.get("dashboard_enabled", True):
        log.info("[DASHBOARD] deaktiviert (dashboard_enabled=false).")
        return

    port = _resolve_port()
    # Bind-Host: den konfigurierten Host zuerst versuchen, aber IMMER auf
    # 0.0.0.0 zurückfallen. Eine öffentliche IP (z. B. die Panel-Adresse) lässt
    # sich im Container in der Regel NICHT direkt binden
    # ("cannot assign requested address"); 0.0.0.0 bindet alle Interfaces und
    # wird vom Host (PebbleHost/Pterodactyl) nach außen weitergereicht.
    cfg_host = str(ctx.cfg.config.get("dashboard_host", "0.0.0.0") or "0.0.0.0").strip()
    hosts = []
    for hc in (cfg_host, "0.0.0.0"):
        if hc and hc not in hosts:
            hosts.append(hc)

    app = build_app()
    _runner = web.AppRunner(app, access_log=None)
    await _runner.setup()

    bound, last_err = None, None
    for host in hosts:
        try:
            site = web.TCPSite(_runner, host, port)
            await site.start()
            bound = host
            break
        except OSError as e:
            last_err = e
            hint = " Versuche 0.0.0.0 …" if host != "0.0.0.0" else ""
            log.warning(f"[DASHBOARD] Bind auf {host}:{port} fehlgeschlagen ({e}).{hint}")

    if bound is None:
        await _runner.cleanup()
        _runner = None
        log.error(f"[DASHBOARD] Konnte auf Port {port} nicht binden: {last_err}. "
                  f"Dashboard ist AUS. Ist der Port vom Host freigegeben (SERVER_PORT) "
                  f"und nicht belegt?")
        return

    log.info(f"[DASHBOARD] ✅ gebunden an {bound}:{port}")
    log.info(f"[DASHBOARD] 🌐 Im Browser über die ÖFFENTLICHE Server-Adresse öffnen: "
             f"http://<DEINE-SERVER-IP>:{port}  — NICHT 0.0.0.0 oder 127.0.0.1!")


async def stop_dashboard() -> None:
    global _runner
    if _runner is not None:
        await _runner.cleanup()
        _runner = None
