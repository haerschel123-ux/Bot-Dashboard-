#!/usr/bin/env python3
"""Lokale Dashboard-Vorschau OHNE Discord-Verbindung – zum Entwickeln in VS Code.

Startet nur den aiohttp-Web-Server auf 127.0.0.1, ganz ohne den Bot bei Discord
einzuloggen. Damit kannst du das Dashboard lokal öffnen, anschauen und am
Frontend/Backend arbeiten, ohne einen echten Discord-Bot-Token zu brauchen.

Was funktioniert:
  • Onboarding, Zonen, Shop (Katalog/Bundles), Karte, Feeds-Konfiguration, Auto-Aufgaben.
  • Nitrado-Funktionen (Server-Status/Bans/Whitelist) werden aktiv, sobald du im
    Onboarding einen gültigen Nitrado-Token eingibst.
Was NICHT geht (weil der Bot nicht bei Discord eingeloggt ist):
  • Live-Channel-/Rollen-Listen (die brauchen die laufende Discord-Verbindung).
    Für den vollen Betrieb `python bot.py` mit gültigem bot_token nutzen.

Start:  python run_dashboard_local.py     (oder in VS Code: F5 → „Nur Dashboard (Vorschau)")
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot  # initialisiert cfg/catalog/db – ruft NICHT bot.run()

bot.cfg.load_all()
bot.catalog.load()

from aiohttp import web                       # noqa: E402
from dashboard import events as devents       # noqa: E402
from dashboard.context import ctx             # noqa: E402
from dashboard.server import build_app        # noqa: E402

HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT")
           or os.environ.get("SERVER_PORT")
           or bot.cfg.config.get("dashboard_port")
           or 8080)


async def main():
    ctx.bind(bot.bot)
    devents.load()
    runner = web.AppRunner(build_app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, HOST, PORT).start()
    print("\n" + "═" * 56)
    print(f"  🎮 Dashboard-Vorschau läuft:  http://{HOST}:{PORT}")
    print("  (ohne Discord-Verbindung · Strg+C zum Beenden)")
    print("═" * 56 + "\n")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBeendet.")
