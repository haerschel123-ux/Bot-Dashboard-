"""Wiederkehrende Ankündigungen verwalten (announcements.json).

Schema je Eintrag: ``{day, time, message, channel_id, repeat, last_sent}``.
``day`` = monday…sunday, ``time`` = HH:MM, ``repeat`` = weekly|biweekly|triweekly|monthly.
"""

from __future__ import annotations

import re

from aiohttp import web

from ..context import ctx
from .common import body, err, ok

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_REPEATS = ("weekly", "biweekly", "triweekly", "monthly")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _data() -> dict:
    d = ctx.g("ann_data")
    if not isinstance(d, dict):
        return {"announcements": []}
    d.setdefault("announcements", [])
    return d


async def list_announcements(request: web.Request) -> web.Response:
    d = _data()
    return ok({"announcements": [
        {"index": i, **a} for i, a in enumerate(d["announcements"])]})


async def create_announcement(request: web.Request) -> web.Response:
    d = _data()
    data = await body(request)
    day = str(data.get("day", "")).strip().lower()
    time_ = str(data.get("time", "")).strip()
    message = str(data.get("message", "")).strip()
    repeat = str(data.get("repeat", "weekly")).strip().lower()
    channel_id = data.get("channel_id")

    if day not in _DAYS:
        return err("day muss einer von monday…sunday sein.")
    if not _TIME_RE.match(time_):
        return err("time muss HH:MM sein.")
    if not message:
        return err("Nachricht fehlt.")
    if repeat not in _REPEATS:
        return err("repeat muss weekly, biweekly, triweekly oder monthly sein.")
    if not channel_id:
        return err("channel_id fehlt.")

    ann = {"day": day, "time": time_, "message": message,
           "channel_id": int(channel_id), "repeat": repeat, "last_sent": None}
    d["announcements"].append(ann)
    save = ctx.g("save_announcements")
    if callable(save):
        save()
    return ok({"index": len(d["announcements"]) - 1, **ann})


async def delete_announcement(request: web.Request) -> web.Response:
    d = _data()
    try:
        idx = int(request.match_info["index"])
    except ValueError:
        return err("Ungültiger Index.")
    if not 0 <= idx < len(d["announcements"]):
        return err("Ankündigung nicht gefunden.", 404)
    removed = d["announcements"].pop(idx)
    save = ctx.g("save_announcements")
    if callable(save):
        save()
    return ok({"removed": removed})
