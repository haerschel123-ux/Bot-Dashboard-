"""Onboarding: Nitrado-Token prüfen → Server wählen → Karte erkennen.

Spiegelt den Discord-Flow ``/setup token`` (bot.py ~3003) +
``_finish_token_setup`` (bot.py ~2879), nur über HTTP.
"""

from __future__ import annotations

from aiohttp import web

from .. import auth
from ..context import ctx
from .common import body, err, ok


def _server_view(svc: dict) -> dict:
    d = svc.get("details") or {}
    return {
        "id": str(svc.get("id")),
        "name": d.get("name") or d.get("game") or f"Service {svc.get('id')}",
        "game": d.get("game") or "",
        "address": d.get("address") or "",
        "status": str(svc.get("status", "")),
    }


async def post_token(request: web.Request) -> web.Response:
    data = await body(request)
    token = str(data.get("token", "")).strip()
    if not token:
        return err("Bitte einen Nitrado-Token eingeben.")

    NitradoAPI = ctx.g("NitradoAPI")
    base = ctx.cfg.config.get("nitrado_api_base", "https://api.nitrado.net")
    api = NitradoAPI(token=token, service_id="", base=base)
    try:
        services = await api.list_services()
    finally:
        await api.close()

    gameservers = [s for s in services
                   if str(s.get("type", "")).lower() == "gameserver"]
    if not gameservers:
        return err("Über diesen Token wurden keine Gameserver gefunden. "
                   "Prüfe, ob der Long-Life-Token korrekt kopiert wurde "
                   "(Nitrado → Benutzereinstellungen → API-Schlüssel).", 401)

    view = [_server_view(s) for s in gameservers[:25]]
    sid = auth.create_session(token, gameservers)
    resp = ok({"servers": view, "count": len(gameservers)})
    auth.attach_cookie(resp, sid)
    return resp


async def post_select_server(request: web.Request) -> web.Response:
    sess = auth.get_session(request)
    if not sess:
        return err("Session abgelaufen – bitte Token erneut eingeben.", 401)
    data = await body(request)
    service_id = str(data.get("service_id", "")).strip()
    if not service_id:
        return err("Bitte einen Server auswählen.")

    service = next((s for s in sess.get("gameservers", [])
                    if str(s.get("id")) == service_id), None)
    if not service:
        return err("Server nicht in dieser Session gefunden.", 404)

    token = sess["token"]
    cfg = ctx.cfg
    NitradoAPI = ctx.g("NitradoAPI")
    _apply = ctx.g("_apply_gameserver_info")

    # --- Kern von _finish_token_setup (ohne Discord-Embed) ---
    old_service = str(cfg.config.get("service_id") or "").strip()
    cfg.config["nitrado_token"] = token
    cfg.config["service_id"] = service_id
    if old_service and old_service != service_id:
        for k in ("ftp_log_dir", "ftp_ban_file", "ftp_profile_dir",
                  "ftp_mission_dir", "cfg_effect_area_path", "server_ip"):
            cfg.config[k] = ""
        cfg.log_state.pop("current", None)
        cfg.save_log_state()

    base = cfg.config.get("nitrado_api_base", "https://api.nitrado.net")
    api = NitradoAPI(token=token, service_id=service_id, base=base)
    warnings = []
    try:
        info = await api.get_info()
    finally:
        await api.close()
    if info and _apply:
        _apply(info)
    else:
        warnings.append("Gameserver-Infos konnten nicht geladen werden – "
                        "FTP/Karte evtl. nicht erkannt.")
    cfg.save_config()

    # Nitrado/FTP/Shop live neu initialisieren (inkl. FTP-Auto-Discovery)
    try:
        await ctx.bot.init_nitrado(force=True)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Init-Warnung: {e}")

    if not cfg.config.get("ftp_host"):
        warnings.append("Keine FTP-Zugangsdaten gefunden – Log-Feeds & "
                        "Shop-Lieferung funktionieren so nicht.")

    sess["service_id"] = service_id
    sess["map_name"] = cfg.config.get("map_name")
    return ok({
        "service_id": service_id,
        "map_name": cfg.config.get("map_name"),
        "ftp_host": cfg.config.get("ftp_host") or None,
        "log_dir": cfg.config.get("ftp_log_dir") or None,
        "server_ip": cfg.config.get("server_ip") or None,
        "name": _server_view(service)["name"],
        "warnings": warnings,
    })


async def get_session(request: web.Request) -> web.Response:
    sess = auth.get_session(request)
    cfg = ctx.cfg if ctx.ready else None
    configured = bool(cfg and str(cfg.config.get("service_id") or "").strip())
    if not sess:
        return ok({"authed": False, "configured": configured})
    return ok({
        "authed": True,
        "service_id": sess.get("service_id") or (cfg.config.get("service_id") if cfg else None),
        "map_name": sess.get("map_name") or (cfg.config.get("map_name") if cfg else None),
        "configured": configured,
        "servers": [_server_view(s) for s in sess.get("gameservers", [])[:25]],
    })


async def post_logout(request: web.Request) -> web.Response:
    auth.destroy_session(request)
    resp = ok()
    resp.del_cookie(auth.COOKIE, path="/")
    return resp
