"""Ringpuffer der zuletzt passierten Server-Events für Karte & Event-Liste.

Der Bot verwirft geparste Events bisher nach dem Posten in die Discord-Feeds.
Für die Dashboard-Karte ("was ist zuletzt passiert") halten wir sie hier in
einem gedeckelten :class:`collections.deque` vor und reichern – wo möglich –
Koordinaten aus den zuletzt bekannten Spielerpositionen an.

Reines Standard-Bibliotheks-Modul: keine Bot-Imports, keine Drittpakete. Wird
von ``bot.py`` (Recorder, in ``DayZBot._dispatch``) und von den API-Handlern
(Leser) gemeinsam genutzt – beide sehen dieselbe deque, da das Modul nur einmal
in ``sys.modules`` existiert.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

MAX_EVENTS = 1000
PERSIST_FILE = "events_recent.json"
_SAVE_EVERY = 25          # nach so vielen neuen Events wird persistiert
_SAVE_MIN_INTERVAL = 15   # aber höchstens alle N Sekunden

# ── Metadaten je Event-Typ: Label, Emoji, Farbe, Filter-Standard ──────
#   Diese Liste speist auch das linke Filter-Panel der Karte.
EVENT_META: Dict[str, Dict[str, Any]] = {
    "connect":      {"label": "Verbindet",        "emoji": "🟢", "color": "#2ecc71", "default": True},
    "disconnect":   {"label": "Trennt",           "emoji": "🔴", "color": "#e74c3c", "default": True},
    "connecting":   {"label": "Verbindungsversuch","emoji": "🔌", "color": "#95a5a6", "default": False},
    "kill_pvp":     {"label": "PvP-Kill",          "emoji": "☠️", "color": "#c0392b", "default": True},
    "suicide":      {"label": "Selbstmord",        "emoji": "💀", "color": "#8e44ad", "default": True},
    "kill_env":     {"label": "Umwelt-Tod",        "emoji": "🧟", "color": "#7f8c8d", "default": True},
    "damage":       {"label": "Treffer / Hit",     "emoji": "🩸", "color": "#e67e22", "default": True},
    "basebuild":    {"label": "Bau-Event",         "emoji": "🏗️", "color": "#f1c40f", "default": True},
    "vehicle":      {"label": "Fahrzeug/Crash",    "emoji": "🚗", "color": "#16a085", "default": True},
    "heli_crash":   {"label": "Helikopter-Absturz","emoji": "🚁", "color": "#2980b9", "default": True},
    "train_crash":  {"label": "Zug-Unfall",        "emoji": "🚆", "color": "#34495e", "default": True},
    "chat":         {"label": "Chat",              "emoji": "💬", "color": "#3498db", "default": False},
    "admin_action": {"label": "Admin-Aktion",      "emoji": "🛡️", "color": "#9b59b6", "default": False},
    "loot":         {"label": "Loot",              "emoji": "🎒", "color": "#27ae60", "default": False},
}

# Welcher Spielername in einem Event trägt die (Karten-)Position?
_PRIMARY_PLAYER_KEYS = {
    "kill_pvp":     "victim",
    "damage":       "victim",
    "suicide":      "player",
    "kill_env":     "player",
    "connect":      "player",
    "disconnect":   "player",
    "connecting":   "player",
    "chat":         "player",
    "admin_action": "admin",
    "basebuild":    "player",
}

_lock = threading.Lock()
_buf: Deque[Dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_next_id = 1
_since_save = 0
_last_save = 0.0

_POS_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _parse_pos(pos_str: Optional[str]):
    """Erste zwei Zahlen aus 'X, Y, Z' → (x=Ost, z=Nord) oder None."""
    if not pos_str:
        return None
    nums = _POS_RE.findall(str(pos_str))
    if len(nums) >= 2:
        try:
            return round(float(nums[0]), 1), round(float(nums[1]), 1)
        except ValueError:
            return None
    return None


def _classify(ev: Dict[str, Any]) -> str:
    """Feinere Klassifizierung – trennt Heli/Zug aus dem generischen vehicle-Event."""
    t = ev.get("type", "")
    if t == "vehicle":
        raw = str(ev.get("raw", "")).lower()
        if "heli" in raw or "helicopter" in raw or "uh1" in raw or "mi8" in raw:
            return "heli_crash"
        if "train" in raw or "zug" in raw or "wagon" in raw or "locomotive" in raw:
            return "train_crash"
    return t


def _summary(ev: Dict[str, Any], etype: str) -> str:
    """Kurzer, menschenlesbarer Text für die Event-Liste."""
    g = ev.get
    if etype == "kill_pvp":
        w = f" mit {g('weapon')}" if g("weapon") else ""
        d = f" ({g('distance')} m)" if g("distance") else ""
        return f"{g('killer','?')} → {g('victim','?')}{w}{d}"
    if etype == "damage":
        w = f" ({g('weapon')})" if g("weapon") else ""
        return f"{g('attacker','?')} trifft {g('victim','?')}{w}"
    if etype in ("suicide",):
        return f"{g('player','?')} hat sich selbst getötet"
    if etype == "kill_env":
        return f"{g('player','?')} gestorben ({g('cause','Umwelt')})"
    if etype in ("connect", "disconnect", "connecting"):
        verb = {"connect": "verbindet", "disconnect": "trennt", "connecting": "verbindet sich"}[etype]
        return f"{g('player','?')} {verb}"
    if etype == "chat":
        return f"{g('player','?')}: {g('message','')}"[:180]
    if etype == "admin_action":
        return f"{g('admin','?')}: {g('command','')}"[:180]
    if etype == "basebuild":
        return f"{g('player','?')} · {g('item','Bau')}"
    if etype in ("vehicle", "heli_crash", "train_crash"):
        return str(g("raw", "Fahrzeug-Ereignis"))[:180]
    if etype == "loot":
        return str(g("raw", "Loot"))[:180]
    return str(g("raw", etype))[:180]


def record(ev: Dict[str, Any], player_positions: Optional[Dict[str, Any]] = None) -> None:
    """Ein geparstes Event in den Ringpuffer aufnehmen (aus ``_dispatch``)."""
    global _next_id, _since_save, _last_save
    try:
        etype = _classify(ev)
        # Position bestimmen: bevorzugt aus dem Event, sonst letzte bekannte Spielerposition
        xz = _parse_pos(ev.get("pos") or ev.get("position"))
        if xz is None and player_positions:
            pkey = _PRIMARY_PLAYER_KEYS.get(ev.get("type", ""))
            pname = ev.get(pkey) if pkey else None
            if pname:
                entry = player_positions.get(pname) or player_positions.get(str(pname))
                if isinstance(entry, dict):
                    xz = _parse_pos(entry.get("position"))
        rec = {
            "type": etype,
            "log_type": ev.get("type"),
            "time": ev.get("timestamp"),
            "summary": _summary(ev, etype),
            "player": ev.get("victim") or ev.get("player") or ev.get("killer") or ev.get("admin"),
            "raw": str(ev.get("raw", ""))[:400],
        }
        if xz:
            rec["x"], rec["z"] = xz[0], xz[1]
        with _lock:
            rec["id"] = _next_id
            rec["ts"] = time.time()
            _next_id += 1
            _buf.append(rec)
            _since_save += 1
            due = _since_save >= _SAVE_EVERY and (time.time() - _last_save) >= _SAVE_MIN_INTERVAL
        if due:
            _persist()
    except Exception:
        # Ein Fehler hier darf niemals den Log-Dispatch des Bots stören.
        pass


def snapshot(since_id: int = 0, types: Optional[List[str]] = None,
             limit: int = 500) -> Dict[str, Any]:
    """Aktuelle Events (optional nur neuere / bestimmte Typen) für die API."""
    tset = set(types) if types else None
    with _lock:
        items = [e for e in _buf
                 if e["id"] > since_id and (tset is None or e["type"] in tset)]
        last = _next_id - 1
    if len(items) > limit:
        items = items[-limit:]
    return {"events": items, "last_id": last}


def types_meta() -> List[Dict[str, Any]]:
    """Filter-Metadaten für das linke Panel."""
    return [{"type": k, **v} for k, v in EVENT_META.items()]


# ── Persistenz (überlebt einen Bot-Neustart mit etwas History) ────────
def _persist() -> None:
    global _since_save, _last_save
    try:
        with _lock:
            data = {"next_id": _next_id, "events": list(_buf)}
        tmp = PERSIST_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, PERSIST_FILE)
        _since_save = 0
        _last_save = time.time()
    except Exception:
        pass


def load() -> None:
    """Beim Start vorhandene History laden (best effort)."""
    global _next_id
    try:
        if not os.path.exists(PERSIST_FILE):
            return
        with open(PERSIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _lock:
            for e in data.get("events", [])[-MAX_EVENTS:]:
                _buf.append(e)
            _next_id = max(int(data.get("next_id", 1)),
                           (_buf[-1]["id"] + 1) if _buf else 1)
    except Exception:
        pass
