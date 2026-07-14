"""Economy: Guthaben ansehen & anpassen (nutzt economy.db + EconomyDB)."""

from __future__ import annotations

import sqlite3

from aiohttp import web

from ..context import ctx
from .common import body, err, ok


def _db_path() -> str:
    return str(ctx.cfg.config.get("economy_db_path", "economy.db"))


def _read_balances(guild_id: int, limit: int = 200):
    import os
    if not os.path.exists(_db_path()):
        return []
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        # Existiert die Tabelle noch nicht (Bot hat die Economy noch nie berührt),
        # liefern wir eine leere Liste statt eines Fehlers.
        have = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='balances'").fetchone()
        if not have:
            return []
        rows = con.execute(
            """SELECT b.user_id, b.wallet, b.bank,
                      (SELECT ingame_name FROM links l
                       WHERE l.guild_id=b.guild_id AND l.user_id=b.user_id) AS ingame
               FROM balances b WHERE b.guild_id=?
               ORDER BY (b.wallet + b.bank) DESC LIMIT ?""",
            (guild_id, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


async def balances(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    try:
        gid = int(request.query.get("guild_id") or (cfg.config.get("guild_ids") or [0])[0])
    except (TypeError, ValueError, IndexError):
        return err("Keine Guild angegeben.")
    try:
        rows = await ctx.run(_read_balances, gid)
    except Exception as e:  # noqa: BLE001
        return err(f"economy.db nicht lesbar: {e}", 500)
    return ok({
        "guild_id": str(gid),
        "balances": [{"user_id": str(r["user_id"]), "ingame": r["ingame"],
                      "wallet": r["wallet"], "bank": r["bank"]} for r in rows],
        "currency": cfg.config.get("currency_name", "Rubles"),
        "symbol": cfg.config.get("currency_symbol", "₽"),
    })


async def money(request: web.Request) -> web.Response:
    db = ctx.db
    data = await body(request)
    try:
        gid = int(data["guild_id"]); uid = int(data["user_id"])
        amount = int(data["amount"])
    except (KeyError, TypeError, ValueError):
        return err("guild_id, user_id und amount (Zahl) erforderlich.")
    op = str(data.get("op", "add"))
    try:
        if op == "add":
            wallet, bank = await ctx.run(db.add_wallet, gid, uid, amount)
        elif op == "remove":
            wallet, bank = await ctx.run(db.add_wallet, gid, uid, -amount)
        elif op == "set":
            wallet, bank = await ctx.run(db.set_wallet, gid, uid, amount)
        else:
            return err("op muss add, remove oder set sein.")
    except Exception as e:  # noqa: BLE001
        return err(f"Fehler: {e}", 500)
    return ok({"user_id": str(uid), "wallet": wallet, "bank": bank})


async def get_config(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    return ok({
        "currency_name": cfg.config.get("currency_name"),
        "currency_symbol": cfg.config.get("currency_symbol"),
        "starting_balance": cfg.config.get("starting_balance"),
        "economy": cfg.config.get("economy"),
        "kill_reward": cfg.config.get("kill_reward"),
    })


async def set_config(request: web.Request) -> web.Response:
    cfg = ctx.cfg
    data = await body(request)
    for key in ("currency_name", "currency_symbol"):
        if key in data:
            cfg.config[key] = str(data[key])
    for key in ("starting_balance", "kill_reward"):
        if key in data:
            try:
                cfg.config[key] = int(data[key])
            except (TypeError, ValueError):
                return err(f"{key} muss eine Zahl sein.")
    cfg.save_config()
    return ok()
