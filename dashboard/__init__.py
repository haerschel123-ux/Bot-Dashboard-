"""Web-Dashboard für den DayZ/Nitrado Discord-Bot.

Das Dashboard läuft im selben Prozess wie der Bot (aiohttp-Web-App im
Event-Loop des Bots) und greift über :mod:`dashboard.context` direkt auf die
bereits vorhandenen globalen Objekte des Bots zu (``cfg``, ``db``, ``catalog``,
die ``NitradoAPI`` usw.). Es wird bewusst KEIN ``import bot`` verwendet, damit
beim Start via ``python bot.py`` (Modul ``__main__``) keine zweite Kopie der
Bot-Globals entsteht.
"""

__all__ = ["events", "context", "server", "auth"]
