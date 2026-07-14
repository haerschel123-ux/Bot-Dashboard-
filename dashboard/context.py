"""Zugriff auf die laufenden Bot-Globals ohne ``import bot``.

Beim Start via ``python bot.py`` ist das Bot-Modul ``__main__``. Ein
``import bot`` würde die Datei ein zweites Mal als Modul ``bot`` ausführen und
damit doppelte, voneinander getrennte Globals (``cfg``, ``db`` …) erzeugen.
Deshalb merken wir uns beim Dashboard-Start das *tatsächlich laufende* Modul
über ``sys.modules[type(bot).__module__]`` und lesen alle Bot-Objekte von dort.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Callable, Optional


class _Context:
    """Hält Referenzen auf die laufende Bot-Instanz und deren Modul."""

    def __init__(self) -> None:
        self.bot: Any = None          # DayZBot-Instanz
        self.mod: Any = None          # das Modul, in dem die Bot-Globals leben
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Einrichtung ────────────────────────────────────────────
    def bind(self, bot: Any) -> None:
        self.bot = bot
        self.mod = sys.modules[type(bot).__module__]
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None

    @property
    def ready(self) -> bool:
        return self.bot is not None and self.mod is not None

    # ── Bequeme Zugriffe auf häufig genutzte Globals ───────────
    @property
    def cfg(self) -> Any:
        return self.mod.cfg

    @property
    def db(self) -> Any:
        return self.mod.db

    @property
    def catalog(self) -> Any:
        return self.mod.catalog

    def g(self, name: str, default: Any = None) -> Any:
        """Beliebiges Bot-Global/-Funktion holen (z. B. ``ctx.g('LOG_TYPES')``)."""
        return getattr(self.mod, name, default)

    # ── Blockierende Bot-Funktionen (SQLite/FTP) im Executor ──
    async def run(self, func: Callable, *args) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)


# Modulweit geteilte Singleton-Instanz
ctx = _Context()
