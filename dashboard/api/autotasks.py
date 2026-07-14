"""Auto-Aufgaben: geplante Server-Neustarts (wie ``/auto restart|off|status``)."""

from __future__ import annotations

import re

from aiohttp import web

from ..context import ctx
from .common import body, ok, err

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _next_run():
    """Nächster geplanter Restart-Zeitpunkt. Die Funktion ist eine METHODE der
    Bot-Instanz (nicht des Moduls), daher am Bot-Objekt holen."""
    fn = getattr(ctx.bot, "_next_scheduled_restart", None)
    if callable(fn):
        try:
            return fn()
        except Exception:
            return None
    return None


async def get_auto_restart(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    sched = cfg.config.get("auto_restart_schedule",
                           {"enabled": False, "first_time": "04:00", "interval_hours": 4})
    nxt = _next_run()
    return ok({
        "schedule": sched,
        "next_run_ts": nxt,
        "after_purchase": bool(cfg.config.get("auto_restart_after_purchase", False)),
        "restart_cooldown_seconds": int(cfg.config.get("restart_cooldown_seconds", 300)),
    })


async def set_auto_restart(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    data = await body(request)
    sched = dict(cfg.config.get("auto_restart_schedule",
                                {"enabled": False, "first_time": "04:00", "interval_hours": 4}))

    if "enabled" in data:
        sched["enabled"] = bool(data["enabled"])
    if "first_time" in data:
        ft = str(data["first_time"]).strip()
        if not _TIME_RE.match(ft):
            return err("Startzeit muss im Format HH:MM (00:00–23:59) sein.")
        sched["first_time"] = ft
    if "interval_hours" in data:
        try:
            iv = int(data["interval_hours"])
        except (TypeError, ValueError):
            return err("Intervall muss eine Zahl sein.")
        if not 1 <= iv <= 24:
            return err("Intervall muss zwischen 1 und 24 Stunden liegen.")
        sched["interval_hours"] = iv

    cfg.config["auto_restart_schedule"] = sched

    if "after_purchase" in data:
        cfg.config["auto_restart_after_purchase"] = bool(data["after_purchase"])

    cfg.save_config()
    # Angekündigte Restarts zurücksetzen, damit die neue Zeit sauber greift
    try:
        ctx.bot._restart_announced.clear()
    except Exception:
        pass

    return ok({"schedule": sched, "next_run_ts": _next_run()})
