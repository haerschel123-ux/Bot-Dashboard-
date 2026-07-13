#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║          DayZ Discord Bot – Vollständige Server-Verwaltung       ║
║  Nitrado Konsolen-Server | Multi-Guild | FTP-Auto-Discovery      ║
║  Starte mit: python dayz_bot.py                                  ║
╚══════════════════════════════════════════════════════════════════╝

Beim ersten Start werden automatisch erstellt:
  - config.json        (Hauptkonfiguration – nur bot_token und guild_ids
                        eintragen; den Nitrado-Token setzt du im Discord per
                        /setup token mit Server-Auswahl im Dropdown – FTP-Zugang
                        und aktive Karte werden dann automatisch erkannt)
  - guilds_config.json (Channel-Einstellungen pro Discord-Server)
  - banlist.json       (Lokale Ban-Datenbank)
  - log_state.json     (Log-Lese-Position)
  - requirements.txt   (Benötigte Pakete)
  - README.txt         (Kurzanleitung)
"""

import os
import sys
import json
import re
import asyncio
import ftplib
import io
import time
import logging
import platform
import sqlite3
import uuid
import random
import threading
import functools
import glob
from datetime import datetime, timezone, timedelta, date
from typing import Optional, Dict, List, Tuple, Any
from zoneinfo import ZoneInfo


# ══════════════════════════════════════════════════════════════
#  SCHRITT 1 – Automatische Abhängigkeits-Installation
# ══════════════════════════════════════════════════════════════
def _install_deps():
    required = {
        "discord": "discord.py>=2.3.0",
        "aiohttp":  "aiohttp>=3.9.0",
        "requests": "requests>=2.31.0",
    }
    missing = [pip for mod, pip in required.items() if not _can_import(mod)]
    if missing:
        print(f"\n[SETUP] Installiere fehlende Pakete: {', '.join(missing)}")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + missing)
        print("[SETUP] Fertig – starte Bot neu...\n")
        os.execv(sys.executable, [sys.executable] + sys.argv)

def _can_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False

_install_deps()

import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp


# ══════════════════════════════════════════════════════════════
#  SCHRITT 2 – Logging
# ══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    handlers=[
        logging.FileHandler("dayz_bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("DayZBot")


# ══════════════════════════════════════════════════════════════
#  SCHRITT 3 – Standard-Konfiguration (wird auto-erstellt)
# ══════════════════════════════════════════════════════════════
CONFIG_FILE    = "config.json"
GUILDS_FILE    = "guilds_config.json"
BANLIST_FILE   = "banlist.json"
LOG_STATE_FILE = "log_state.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "_anleitung": [
        "1) Nur DIESE 2 Angaben sind nötig – alles andere richtet der Bot selbst ein:",
        "2) bot_token: Discord Entwicklerportal → deine App → Bot → Token kopieren",
        "3) guild_ids: Discord → Einstellungen → Erweitert → Entwicklermodus aktivieren,",
        "   dann Rechtsklick auf deinen Server → ID kopieren. Mehrere IDs möglich!",
        "4) admin_role_name: Name der Rolle, die Bot-Befehle nutzen darf (z.B. 'DayZ Admin')",
        "5) Bot starten und im Discord /setup token <dein Nitrado-Token> ausführen:",
        "   Es öffnet sich ein Dropdown mit deinen Nitrado-Servern – Server auswählen,",
        "   bestätigen, fertig. FTP-Zugang und die aktuelle Karte erkennt der Bot",
        "   automatisch und speichert alles hier als Cache.",
        "   (Nitrado-Token: Nitrado → Benutzereinstellungen → API-Schlüssel,",
        "   Long-Life-Token. Er kann auch weiterhin direkt hier eingetragen werden.)"
    ],
    "bot_token":         "HIER_DEIN_DISCORD_BOT_TOKEN_EINTRAGEN",
    "nitrado_token":     "",
    "service_id":        "",
    "nitrado_api_base":  "https://api.nitrado.net",
    "ftp_host":          "",
    "ftp_port":          21,
    "ftp_user":          "",
    "ftp_password":      "",

    "ftp_log_dir":       "",
    "ftp_ban_file":      "",
    "ftp_profile_dir":   "",

    "_anleitung_banliste": [
        "Die Banliste läuft über die NITRADO-SERVEREINSTELLUNGEN (dasselbe Feld wie im",
        "Webinterface bei den allgemeinen Einstellungen, 1 Name pro Zeile) – nicht mehr",
        "über eine ban.txt. /ban, /ban_entfernen und /banlist nutzen die Nitrado-API.",
        "nitrado_ban_category/nitrado_ban_key: Nur setzen, falls die Auto-Erkennung",
        "  (Settings-Key 'bans') das falsche Feld findet – sonst leer lassen."
    ],
    "nitrado_ban_category": "",
    "nitrado_ban_key":      "",

    "guild_ids": [111111111111111111],

    "server_ip":   "",
    "query_port":  2302,
    "rcon_port":   2310,

    "admin_role_name":           "DayZ Admin",
    "log_poll_interval_seconds": 10,
    "max_embed_fields":          25,
    "map_name":                  "ChernarusPlus",

    "_anleitung_neue_features": [
        "─────────── FEED-SCHUTZ / BELOHNUNGEN / AUTO-RESTART ───────────",
        "max_backlog_minutes: War der Bot länger als X Minuten offline, werden alte",
        "  Log-Events NICHT nachgepostet (verhindert Embed-Fluten nach Ausfällen).",
        "max_events_per_cycle: Höchstens so viele Events pro Poll-Zyklus posten.",
        "ftp_fail_warn_cycles: Nach so vielen FTP-Fehlzyklen in Folge postet der Bot",
        "  eine Warnung in den Adminlog-Channel (/setup feeds adminlog).",
        "kill_reward: Betrag, den ein per /link verknüpfter Spieler pro PvP-Kill erhält.",
        "playtime_reward: amount pro interval_minutes Spielzeit (500 pro 30 Min = 1000/Std)",
        "  – wird nur verlinkten Spielern gutgeschrieben.",
        "status_update_interval_seconds: Aktualisierungs-Intervall des Auto-Status-Embeds",
        "  (/setup feeds status #channel).",
        "auto_restart_schedule: Wird über /auto restart im Discord gesetzt (Startzeit +",
        "  Intervall in Stunden). Ankündigungen 15/5/1 Min vorher im /setup feeds restart Channel.",
        "economy_backup_keep: So viele tägliche economy.db-Backups werden aufbewahrt.",
        "delivery_cleanup_delay_seconds: FALLBACK-Delay. Nach einem Server-Neustart wartet",
        "  der Bot, bis der Server wieder ONLINE ist (A2S-Antwort), und entfernt die",
        "  SHOP_-Einträge dann SOFORT aus der cfgEffectArea.json. Nur wenn der Online-",
        "  Status nicht prüfbar ist (server_ip/query_port fehlt oder A2S-Timeout),",
        "  wartet er stattdessen diesen festen Delay, bevor er sie entfernt.",
        "delivery_online_wait_max_seconds: Maximal so lange auf die A2S-Antwort warten;",
        "  danach (oder ohne server_ip/query_port) greift der feste Delay als Fallback.",
        "zones: Überwachte Zonen (/zone create|remove|list|edit|allowlist im Discord verwalten).",
        "  Pro Zone: name, x/z (iZurvive: x=Ost, z=Nord), radius (Meter), role_id",
        "  (optional, Ping-@), channel_id (optional, eigener Warn-Channel), allowlist",
        "  (ignorierte Spieler), guild_id. Ohne channel_id gehen Pings in den zone-Feed",
        "  (/setup feeds zone, Fallback adminlog) – wiederholt alle",
        "  zone_ping_cooldown_seconds, solange der Spieler in der Zone bleibt.",
        "zone_ping_cooldown_seconds: Wiederhol-Intervall zwischen zwei Pings für",
        "  denselben Spieler in derselben Zone (Default 300 = 5 Minuten)."
    ],
    "delivery_cleanup_delay_seconds": 600,
    "delivery_online_wait_max_seconds": 2700,
    "zones": [],
    "zone_ping_cooldown_seconds": 300,
    "max_backlog_minutes":            10,
    "max_events_per_cycle":           30,
    "ftp_fail_warn_cycles":           10,
    "kill_reward":                    100,
    "playtime_reward":                {"amount": 500, "interval_minutes": 30},
    "status_update_interval_seconds": 180,
    "auto_restart_schedule":          {"enabled": False, "first_time": "04:00", "interval_hours": 4},
    "economy_backup_keep":            7,

    "_anleitung_shop_economy": [
        "─────────── SHOP / ECONOMY / CASINO ───────────",
        "admin_role_ids: Liste von Discord-Rollen-IDs (Zahlen!), die ALLE Admin-Befehle nutzen",
        "  dürfen. Rechtsklick auf Rolle → ID kopieren (Entwicklermodus). admin_role_name bleibt",
        "  als Fallback aktiv, Discord-Administratoren dürfen immer.",
        "economy_admin_role_ids: Rollen-IDs, die NUR Geld verwalten dürfen (/addmoney,",
        "  /removemoney, /setbalance). Leer lassen = nur admin_role_ids.",
        "auto_restart_after_purchase: true = Server startet nach einem Kauf automatisch neu.",
        "  restart_cooldown_seconds = Wartezeit vor dem Auto-Restart, damit mehrere Käufe",
        "  gesammelt werden. false = Items spawnen erst beim nächsten regulären Neustart.",
        "delivery_grace_seconds: Käufe, die jünger sind, werden bei Neustart-Erkennung noch",
        "  NICHT als geliefert markiert (Server hatte die Datei evtl. noch nicht gelesen).",
        "default_pos_y: Standard-Höhe (Pos[1]) für Spawns, meist 0.0. default_radius: Radius.",
        "ftp_mission_dir / cfg_effect_area_path: werden per /ftp_scan automatisch gefunden,",
        "  können aber auch manuell gesetzt werden, z.B.",
        "  /dayzps/mpmissions/dayzOffline.chernarusplus/cfgEffectArea.json",
        "currency_name / currency_symbol / starting_balance: Währung & Startguthaben.",
        "economy: Beträge und Cooldowns für /work, /daily, /beg.",
        "bounty: min_amount/max_amount (Grenzen pro Kopfgeld) und cooldown_seconds pro Nutzer.",
        "hilfe_cooldown_seconds: Spam-Schutz für /hilfe (Sekunden pro Nutzer).",
        "casino: min_bet/max_bet, Auszahlungs-Multiplikatoren und Cooldowns pro Spiel.",
        "shop_items: Katalog. Pro Item: name (Anzeigename), classname (exakter DayZ-Type!),",
        "  price, category, enabled (true/false), max_amount_per_buy.",
        "shop_items_file: generierter Groß-Katalog. Wird beim Bot-Start automatisch aus",
        "  einer types.xml im Bot-Ordner erzeugt, falls die Datei noch fehlt. Existiert",
        "  sie, hat sie Vorrang vor shop_items. Preise pro Kategorie: shop_category_prices",
        "  (Datei löschen + Neustart = neu generieren) oder einzeln per /shop setprice",
        "  bzw. /edit shopitem. Items hinzufügen/ändern: /add shopitem, /edit shopitem.",
        "Nach Änderungen an dieser Datei: /economy_reload im Discord (kein Neustart nötig)."
    ],

    "admin_role_ids":              [],
    "economy_admin_role_ids":      [],

    "auto_restart_after_purchase": False,
    "restart_cooldown_seconds":    300,
    "delivery_grace_seconds":      90,
    "default_pos_y":               0.0,
    "default_radius":              1,
    "ftp_mission_dir":             "",
    "cfg_effect_area_path":        "",
    "economy_db_path":             "economy.db",

    "currency_name":    "Rubles",
    "currency_symbol":  "₽",
    "starting_balance": 5000,

    "economy": {
        "work":  {"min": 50, "max": 150, "cooldown_seconds": 3600},
        "daily": {"amount": 300, "cooldown_seconds": 86400},
        "beg":   {"min": 5, "max": 50, "fail_chance": 0.35, "cooldown_seconds": 300}
    },

    # Kopfgelder: Betragsgrenzen + Cooldown pro Nutzer (Spam-/Missbrauchsschutz)
    "bounty": {"min_amount": 100, "max_amount": 10000, "cooldown_seconds": 300},
    # /hilfe-Spam-Schutz (Sekunden pro Nutzer)
    "hilfe_cooldown_seconds": 30,

    "casino": {
        "blackjack": {"min_bet": 10, "max_bet": 1000, "blackjack_payout": 1.5, "cooldown_seconds": 30},
        "roulette":  {"min_bet": 10, "max_bet": 1000, "cooldown_seconds": 5,
                      "payout_number": 36.0, "payout_color": 2.0,
                      "payout_evenodd": 2.0, "payout_highlow": 2.0},
        "slots":     {"min_bet": 10, "max_bet": 500, "cooldown_seconds": 10,
                      "symbols":  ["🍒", "🍋", "🍉", "🔔", "💎", "7️⃣"],
                      "weights":  [30, 25, 20, 12, 8, 5],
                      "payout_three": {"🍒": 3, "🍋": 4, "🍉": 5, "🔔": 8, "💎": 15, "7️⃣": 30},
                      "payout_two": 1.5}
    },

    # Generierter Groß-Katalog: hat Vorrang vor shop_items (Fallback), wenn die Datei existiert
    "shop_items_file":    "shop_items.json",
    "shop_default_price": 100,
    "shop_category_prices": {
        "Armbands": 50, "Ammo": 150, "Attachments": 400, "Bags": 600,
        "Belts": 150, "Clothing": 100, "Clothing Improvised": 80, "Feet": 120,
        "Firearms": 2500, "Flags": 300, "Food": 60, "Gas Gear": 800,
        "Gas Masks": 700, "Ghillies": 1200, "Gloves": 100, "Hats": 80,
        "Helmets": 400, "Lights": 150, "Magazines": 300, "Masks": 150,
        "Medical Items": 200, "Melee Items": 250, "Misc Items": 100,
        "Nades & Traps": 900, "Navigation Items": 250, "Pelts": 150,
        "Plants": 40, "Optics": 600, "Seeds": 30, "Storage Items": 700,
        "Supplies": 120, "Suppressors": 800, "Tacticals": 500, "Tools": 300,
        "Vests": 800, "Vehicle Parts": 350, "Vehicles": 15000
    },

    "shop_items": [
        {"name": "CZ75",           "classname": "cz75",                    "price": 500,  "category": "Weapons", "enabled": True, "max_amount_per_buy": 5},
        {"name": "Mlock-91",       "classname": "Mlock91",                 "price": 600,  "category": "Weapons", "enabled": True, "max_amount_per_buy": 5},
        {"name": "M4-A1",          "classname": "M4A1",                    "price": 2500, "category": "Weapons", "enabled": True, "max_amount_per_buy": 2},
        {"name": "KA-M",           "classname": "AKM",                     "price": 2500, "category": "Weapons", "enabled": True, "max_amount_per_buy": 2},
        {"name": "Combat Knife",   "classname": "CombatKnife",             "price": 150,  "category": "Gear",    "enabled": True, "max_amount_per_buy": 10},
        {"name": "Field Backpack", "classname": "AliceBag_Camo",           "price": 800,  "category": "Gear",    "enabled": True, "max_amount_per_buy": 3},
        {"name": "Tetracycline",   "classname": "TetracyclineAntibiotics", "price": 200,  "category": "Medical", "enabled": True, "max_amount_per_buy": 10},
        {"name": "Saline Bag IV",  "classname": "SalineBagIV",             "price": 350,  "category": "Medical", "enabled": True, "max_amount_per_buy": 5},
        {"name": "Canned Bacon",   "classname": "CannedBacon",             "price": 60,   "category": "Food",    "enabled": True, "max_amount_per_buy": 20}
    ]
}

# ══════════════════════════════════════════════════════════════
#  Log-Typen (Auswahl im /setup feeds Dropdown)
# ══════════════════════════════════════════════════════════════
LOG_TYPES: Dict[str, str] = {
    "killfeed":     "☠️  PvP-Kills zwischen Spielern",
    "damagefeed":   "🩸 Treffer / Damage an Spielern",
    "joinleave":    "🟢 Spieler betritt / verlässt den Server",
    "suicide":      "💀 Selbstmord / Freitod",
    "chat":         "💬 In-Game Chat-Nachrichten",
    "adminlog":     "🛡️  Admin-Aktionen & Befehle",
    "envdeath":     "☠️  Umwelttode (Zombies, Bleed, Hunger usw.)",
    "vehiclecrash": "🚗 Fahrzeug-Ereignisse & Crashes",
    "basebuild":    "🏗️  Basis-Bau Ereignisse",
    "loot":         "🎒 Loot-Spawn/-Despawn Ereignisse",
    "connecting":   "🔌 Verbindungsversuche (is connecting)",
    "shop_log":     "🛒 Shop-Käufe (wer hat was gekauft)",
    "economy_log":  "💰 Economy-Admin-Aktionen (add/remove money)",
    "status":       "📊 Auto-Status-Embed (online/offline, Spielerzahl)",
    "restart":      "🔄 Restart-Ankündigungen (geplante Neustarts)",
    "zone":         "🛡️ Zonen-Pings (Spieler in überwachten Zonen, /zone create)",
}


# ══════════════════════════════════════════════════════════════
#  Map-Name → Mission-Ordner unter mpmissions/
# ══════════════════════════════════════════════════════════════
MISSION_FOLDERS: Dict[str, str] = {
    "chernarusplus": "dayzOffline.chernarusplus",
    "livonia":       "dayzOffline.enoch",
    "enoch":         "dayzOffline.enoch",
    "sakhal":        "dayzOffline.sakhal",
}

def _mission_folder_for_map(map_name: str) -> str:
    """Ermittelt den mpmissions-Ordnernamen für die konfigurierte Map."""
    return MISSION_FOLDERS.get((map_name or "").strip().lower(), "dayzOffline.chernarusplus")

# Kanonische Map-Namen (Schlüssel von _MAP_LOCATIONS bzw. iZurvive-URL)
_CANONICAL_MAPS: Dict[str, str] = {
    "chernarusplus": "ChernarusPlus",
    "chernarus":     "ChernarusPlus",
    "enoch":         "Livonia",
    "livonia":       "Livonia",
    "sakhal":        "Sakhal",
}

def _canonical_map_name(raw: str) -> Optional[str]:
    """Normalisiert einen Map-Namen aus Nitrado-Daten (z.B. query.map oder
    Mission-Ordner 'dayzOffline.sakhal') auf den kanonischen Namen.
    None, wenn keine bekannte Karte erkannt wird."""
    s = (raw or "").strip().lower()
    if not s:
        return None
    for key, canon in _CANONICAL_MAPS.items():
        if key in s:
            return canon
    return None


# ══════════════════════════════════════════════════════════════
#  Hilfsdateien automatisch erstellen
# ══════════════════════════════════════════════════════════════
def _create_helper_files():
    req = "discord.py>=2.3.0\naiohttp>=3.9.0\nrequests>=2.31.0\n"
    if not os.path.exists("requirements.txt"):
        with open("requirements.txt", "w", encoding="utf-8") as f:
            f.write(req)
        print("[SETUP] requirements.txt erstellt.")

    readme = """╔══════════════════════════════════════════════════════════════╗
║              DayZ Bot – Kurzanleitung                        ║
╚══════════════════════════════════════════════════════════════╝

ERSTE SCHRITTE
──────────────
1. Öffne config.json und trage NUR diese 2 Angaben ein:
   bot_token und guild_ids.
2. Starte den Bot: python dayz_bot.py
3. Führe im Discord /setup token <dein-nitrado-token> aus:
   Es öffnet sich ein Dropdown mit deinen Nitrado-Servern –
   Server auswählen und bestätigen. FTP-Zugang, die aktive Karte
   und die Log-Verzeichnisse erkennt der Bot dann automatisch.
4. Benutze /setup feeds im Discord um Channels zuzuweisen.

BEFEHLE (alle nur für Admins mit der konfigurierten Rolle)
──────────────────────────────────────────────────────────
/setup token <token>            → Nitrado-Token setzen; danach Server im
                                   Dropdown auswählen & bestätigen (erkennt
                                   FTP-Zugang und aktive Karte automatisch)
/setup feeds <feed> #channel    → Feed-Channel setzen (Dropdown-Auswahl:
                                   killfeed, damagefeed, joinleave, suicide,
                                   chat, adminlog, envdeath, vehiclecrash,
                                   basebuild, loot, connecting, shop_log,
                                   economy_log, status, restart, zone)
/setup uebersicht               → Alle Einstellungen anzeigen

/neustart                       → Server neu starten
/stoppen                        → Server stoppen
/serverstatus                   → Aktuellen Status abrufen

/ban <spieler> [grund]          → Name(n) auf die Nitrado-Banliste setzen (Komma = mehrere)
/ban_entfernen <spieler>        → Name(n) von der Nitrado-Banliste entfernen
/banlist                        → Nitrado-Banliste anzeigen (Servereinstellungen)

/admin_position                 → Letzte bekannte Positionen aller Spieler
/spieler_suche <name>           → Spieler in den Logs suchen
/log_status                     → Log-Polling Status anzeigen
/ftp_scan                       → FTP-Verzeichnisse neu scannen
/hilfe                          → Diese Hilfe

SHOP & ECONOMY & CASINO
───────────────────────
Spieler-Befehle (kein Admin nötig):
/balance [@user]                → Wallet & Bank anzeigen
/deposit [menge]                → Wallet → Bank (ohne Menge = alles)
/withdraw [menge]               → Bank → Wallet (ohne Menge = alles)
/work  /daily  /beg             → Geld verdienen (Cooldowns in config.json)
/blackjack <einsatz>            → Blackjack mit Hit/Stand-Buttons
/roulette <einsatz> <wette>     → red/black/even/odd/low/high oder Zahl 0-36
/slots <einsatz>                → Slot-Maschine
/shop list [kategorie]          → Item-Katalog (ohne Kategorie: Übersicht)
/buy <item> <menge> <x> <z> [y] → Item kaufen & an Koordinate spawnen lassen
   x = iZurvive X (Ost, 1. Zahl) | z = iZurvive Y (Nord, 2. Zahl)
   y = Höhe (optional, Standard: default_pos_y aus config.json)

Economy-Admin-Befehle (admin_role_ids / economy_admin_role_ids):
/addmoney <@user> <betrag>      → Guthaben hinzufügen
/removemoney <@user> <betrag>   → Guthaben abziehen (nie unter 0)
/setbalance <@user> <betrag>    → Wallet exakt setzen
/shop pending                   → Offene (noch nicht gespawnte) Käufe
/shop check                     → Delivery-Diagnose: prüft cfgEffectArea.json und
   trägt fehlende Einträge offener Käufe automatisch wieder ein
/shop cleanup                   → Lieferungen abschließen + verwaiste SHOP_-Einträge entfernen
/shop setprice <item> <preis>   → Item-Preis ändern
/shop enable <item> <true/false>→ Item im Shop (de)aktivieren
/add shopitem <classnames> <preis> → Item/Bundle in den Katalog aufnehmen
   Anzeigename = Classname; mehrere Classnames (Komma getrennt) = Bundle,
   dann spawnen alle Items zusammen an der Kauf-Koordinate
/bundle add                     → Bundle per Formular anlegen: Kategorie im
   Dropdown wählen, dann Items zeilenweise als "2xClassname" (mit Menge),
   Name, Preis und Max-Kauf-Limit eingeben
/edit shopitem <item> [...]     → Classnames, Preis, Name, Kategorie oder
   Max-Menge eines vorhandenen Items/Bundles ändern
/shop removeitem <item>         → Item/Bundle aus dem Katalog löschen
/economy_reload                 → config.json + Katalog neu laden (ohne Bot-Neustart)

ITEM-KATALOG (shop_items.json)
──────────────────────────────
Der große Katalog wird beim Bot-Start AUTOMATISCH aus deiner types.xml
erzeugt, falls shop_items.json noch fehlt (types.xml einfach in den
Bot-Ordner legen – der Generator steckt im Bot selbst, keine 2. Datei).
Neu generieren: shop_items.json löschen und den Bot neu starten;
per /add shopitem angelegte Items bleiben dabei erhalten.
Preise pro Kategorie: shop_category_prices in config.json; einzeln per
/shop setprice oder /edit shopitem. Existiert shop_items.json, hat sie
Vorrang vor der kleinen shop_items-Liste in config.json.

ITEM-AUSLIEFERUNG (cfgEffectArea.json)
──────────────────────────────────────
Käufe werden als Einträge in mpmissions/<mission>/cfgEffectArea.json
geschrieben (Type = Item-Classname). Die Items spawnen beim NÄCHSTEN
Server-Neustart an der angegebenen Koordinate.
- auto_restart_after_purchase=true → der Bot startet den Server nach
  einem Kauf automatisch neu (gesammelt über restart_cooldown_seconds).
- Nach dem Neustart entfernt der Bot die Einträge automatisch wieder,
  sonst würden die Items bei JEDEM Neustart erneut spawnen.
- Vor jedem Schreiben wird ein Backup (cfgEffectArea.json.bak) angelegt.
- Guthaben liegt in economy.db (SQLite) – Datei sichern = Economy sichern.

MEHRERE DISCORD-SERVER (Guilds)
────────────────────────────────
Trage in config.json unter "guild_ids" mehrere IDs ein:
  "guild_ids": [111111111111111111, 222222222222222222]
Jeder Server hat seine eigene Channel-Konfiguration.

NITRADO KONSOLEN-SERVER – LOG-PFADE
────────────────────────────────────
Der Bot sucht beim Start automatisch in folgenden Pfaden:
  /games/<user>/noftp/dayz/config
  /games/<user>/noftp/dayz/profiles
  /dayz/config
  /dayz/profiles
  ...und weiteren typischen Nitrado-Pfaden.
"""
    # README neu schreiben, wenn sie fehlt oder noch eine alte Version ist
    needs_readme = True
    if os.path.exists("README.txt"):
        try:
            with open("README.txt", "r", encoding="utf-8") as f:
                needs_readme = "NUR diese 3 Angaben" not in f.read()
        except Exception:
            needs_readme = True
    if needs_readme:
        with open("README.txt", "w", encoding="utf-8") as f:
            f.write(readme)
        print("[SETUP] README.txt erstellt/aktualisiert.")


# ══════════════════════════════════════════════════════════════
#  Konfigurations-Manager
# ══════════════════════════════════════════════════════════════
class ConfigManager:
    def __init__(self):
        self.config:    Dict = {}
        self.guilds:    Dict = {}
        self.bans:      Dict = {}
        self.log_state: Dict = {}

    def load_all(self):
        _create_helper_files()
        self.config    = self._load_or_create(CONFIG_FILE,    DEFAULT_CONFIG)
        self.guilds    = self._load_or_create(GUILDS_FILE,    {})
        self.bans      = self._load_or_create(BANLIST_FILE,   {})
        self.log_state = self._load_or_create(LOG_STATE_FILE, {})
        # Fehlende neue Felder (Shop/Economy/Casino) in bestehende config.json ergänzen
        if self._merge_defaults(self.config, DEFAULT_CONFIG):
            self.save_config()
            log.info("[CONFIG] config.json um neue Standard-Felder ergänzt.")

    def _merge_defaults(self, target: Dict, defaults: Dict) -> bool:
        """Ergänzt fehlende Keys rekursiv, ohne vorhandene Werte zu überschreiben."""
        changed = False
        for key, val in defaults.items():
            if key not in target:
                target[key] = val
                changed = True
            elif isinstance(val, dict) and isinstance(target.get(key), dict):
                if self._merge_defaults(target[key], val):
                    changed = True
        return changed

    def reload_config(self) -> bool:
        """Lädt config.json zur Laufzeit neu (für /economy_reload)."""
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            if self._merge_defaults(self.config, DEFAULT_CONFIG):
                self.save_config()
            return True
        except Exception as e:
            log.error(f"[CONFIG] Reload fehlgeschlagen: {e}")
            return False

    def _load_or_create(self, path: str, default: Any) -> Any:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            log.info(f"[CONFIG] '{path}' wurde neu erstellt.")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, path: str, data: Any):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_config(self):   self.save(CONFIG_FILE,    self.config)
    def save_guilds(self):   self.save(GUILDS_FILE,    self.guilds)
    def save_bans(self):     self.save(BANLIST_FILE,   self.bans)
    def save_log_state(self):self.save(LOG_STATE_FILE, self.log_state)

    def get_channel(self, guild_id: int, log_type: str) -> Optional[int]:
        return self.guilds.get(str(guild_id), {}).get(log_type)

    def set_channel(self, guild_id: int, log_type: str, channel_id: int):
        gid = str(guild_id)
        self.guilds.setdefault(gid, {})[log_type] = channel_id
        self.save_guilds()

    def is_valid(self) -> Tuple[bool, List[str]]:
        # Nur der Discord-Bot-Token ist Pflicht. Der Nitrado-Token wird per
        # /setup token im Discord gesetzt (oder optional hier eingetragen);
        # service_id + FTP-Zugang erkennt der Bot dann automatisch.
        errors = []
        placeholders = ["HIER", "TOKEN", "EINTRAGEN", "1111111", "2222222"]
        for key in ["bot_token"]:
            val = str(self.config.get(key, ""))
            if not val or any(p in val for p in placeholders):
                errors.append(key)
        return len(errors) == 0, errors

    def has_nitrado_token(self) -> bool:
        """True, wenn ein echter Nitrado-Token gesetzt ist (kein Platzhalter)."""
        val = str(self.config.get("nitrado_token") or "").strip()
        return bool(val) and "HIER" not in val and "EINTRAGEN" not in val

cfg = ConfigManager()


# ══════════════════════════════════════════════════════════════
#  Nitrado API-Client
# ══════════════════════════════════════════════════════════════
class NitradoAPI:
    def __init__(self, token: str, service_id: str, base: str = "https://api.nitrado.net"):
        self.token      = token
        self.service_id = service_id
        self.base       = base.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    def _headers(self) -> Dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    async def _s(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers())
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _post(self, endpoint: str) -> Tuple[bool, str]:
        try:
            s = await self._s()
            url = f"{self.base}/services/{self.service_id}/gameservers{endpoint}"
            async with s.post(url) as r:
                data = await r.json()
                if r.status in (200, 201, 204):
                    return True, data.get("message", "Erfolgreich")
                return False, data.get("message", f"HTTP {r.status}")
        except Exception as e:
            return False, f"Verbindungsfehler: {e}"

    async def restart(self) -> Tuple[bool, str]:
        return await self._post("/restart")

    async def stop(self) -> Tuple[bool, str]:
        return await self._post("/stop")

    async def get_info(self) -> Optional[Dict]:
        try:
            s = await self._s()
            url = f"{self.base}/services/{self.service_id}/gameservers"
            async with s.get(url) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("data", {}).get("gameserver")
        except Exception as e:
            log.error(f"[NITRADO] get_info: {e}")
        return None

    async def get_settings(self) -> Optional[Dict]:
        """Gameserver-Settings (Nitrado-Webinterface 'Einstellungen') als Dict
        {kategorie: {key: value}}. None bei API-Fehler."""
        info = await self.get_info()
        if not info:
            return None
        settings = info.get("settings")
        return settings if isinstance(settings, dict) else None

    async def set_setting(self, category: str, key: str, value: str) -> Tuple[bool, str]:
        """Setzt ein einzelnes Gameserver-Setting (z. B. die Banliste) über
        POST /gameservers/settings."""
        try:
            s = await self._s()
            url = f"{self.base}/services/{self.service_id}/gameservers/settings"
            payload = {"category": category, "key": key, "value": value}
            async with s.post(url, json=payload) as r:
                try:
                    data = await r.json()
                except Exception:
                    data = {}
                if r.status in (200, 201, 204):
                    return True, data.get("message", "Erfolgreich")
                return False, data.get("message", f"HTTP {r.status}")
        except Exception as e:
            return False, f"Verbindungsfehler: {e}"

    async def download_file(self, path: str) -> Optional[bytes]:
        try:
            s = await self._s()
            url = f"{self.base}/services/{self.service_id}/gameservers/file_server/download"
            async with s.get(url, params={"file": path}) as r:
                if r.status == 200:
                    data = await r.json()
                    dl_url = data.get("data", {}).get("token", {}).get("url")
                    if dl_url:
                        async with s.get(dl_url) as dr:
                            return await dr.read()
        except Exception as e:
            log.error(f"[NITRADO] download_file: {e}")
        return None

    # ── Auto-Erkennung (Service-ID, FTP-Zugang, Karte) ────────────
    async def list_services(self) -> List[Dict]:
        """GET /services – alle Services des Tokens. Leere Liste bei Fehler."""
        try:
            s = await self._s()
            async with s.get(f"{self.base}/services") as r:
                if r.status == 200:
                    data = await r.json()
                    services = data.get("data", {}).get("services", [])
                    return services if isinstance(services, list) else []
                log.error(f"[NITRADO] list_services: HTTP {r.status}")
        except Exception as e:
            log.error(f"[NITRADO] list_services: {e}")
        return []

    async def detect_service(self) -> Optional[str]:
        """Sucht den DayZ-Gameserver unter allen Services des Tokens und setzt
        self.service_id. Bevorzugt Services mit 'dayz' im Spiel-/Detailnamen,
        bei mehreren Kandidaten den ersten aktiven. None, wenn nichts gefunden."""
        services = await self.list_services()
        gameservers = [s for s in services
                       if str(s.get("type", "")).lower() == "gameserver"]

        def _is_dayz(svc: Dict) -> bool:
            details = svc.get("details") or {}
            text = " ".join(str(v) for v in (details.get("game"),
                                             details.get("name"),
                                             details.get("folder_short"))
                            if v).lower()
            return "dayz" in text

        candidates = [s for s in gameservers if _is_dayz(s)] or gameservers
        if not candidates:
            log.error("[NITRADO] Kein Gameserver-Service unter diesem Token gefunden.")
            return None
        active = [s for s in candidates
                  if str(s.get("status", "")).lower() == "active"]
        chosen = (active or candidates)[0]
        if len(candidates) > 1:
            overview = ", ".join(
                f"{s.get('id')} ({(s.get('details') or {}).get('name') or (s.get('details') or {}).get('game') or '?'})"
                for s in candidates)
            log.warning(f"[NITRADO] Mehrere Gameserver gefunden: {overview} – "
                        f"nutze Service {chosen.get('id')}. Zum Überschreiben "
                        f"service_id in config.json setzen.")
        self.service_id = str(chosen.get("id"))
        log.info(f"[NITRADO] ✅ Service-ID automatisch erkannt: {self.service_id}")
        return self.service_id

    @staticmethod
    def extract_ftp_credentials(info: Dict) -> Optional[Dict[str, Any]]:
        """Liest die FTP-Zugangsdaten aus den Gameserver-Infos (credentials.ftp)."""
        ftp = ((info or {}).get("credentials") or {}).get("ftp") or {}
        host     = ftp.get("hostname") or ftp.get("host")
        user     = ftp.get("username") or ftp.get("user")
        password = ftp.get("password")
        if not (host and user and password):
            return None
        try:
            port = int(ftp.get("port") or 21)
        except (TypeError, ValueError):
            port = 21
        return {"host": str(host), "port": port,
                "user": str(user), "password": str(password)}

    @staticmethod
    def extract_map(info: Dict) -> Optional[str]:
        """Ermittelt die aktuell laufende Karte aus den Gameserver-Infos:
        zuerst query.map (Server online), sonst Mission/Map aus den Settings."""
        info = info or {}
        m = _canonical_map_name(str((info.get("query") or {}).get("map") or ""))
        if m:
            return m
        settings = info.get("settings")
        if isinstance(settings, dict):
            for cat in settings.values():
                if not isinstance(cat, dict):
                    continue
                for key in ("mission", "map", "current_map", "mapname"):
                    m = _canonical_map_name(str(cat.get(key) or ""))
                    if m:
                        return m
        return None


# ══════════════════════════════════════════════════════════════
#  A2S UDP-Ping (Valve Server Query – kein extra Paket nötig)
#  Liefert Echtzeit-Spielerzahl, Servername und Map direkt
#  vom Spielserver – unabhängig von der Nitrado-API.
# ══════════════════════════════════════════════════════════════
import socket
import struct

def a2s_query(ip: str, port: int, timeout: float = 3.0) -> Optional[Dict]:
    """
    Sendet eine A2S_INFO Anfrage an den DayZ-Server und gibt
    ein Dict mit Serverinfos zurück, oder None bei Fehler.
    Funktioniert nur wenn der Server online ist.
    """
    if not ip:
        return None
    try:
        # A2S_INFO Request Payload
        payload = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(timeout)
            sock.sendto(payload, (ip, int(port)))
            data, _ = sock.recvfrom(4096)
        finally:
            sock.close()   # Socket auch bei Timeout/Fehler schließen

        if len(data) < 6:
            return None

        # Challenge-Response Handling (neuere Server)
        if data[4:5] == b"\x41":
            challenge = data[5:9]
            payload2 = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00" + challenge
            sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock2.settimeout(timeout)
                sock2.sendto(payload2, (ip, int(port)))
                data, _ = sock2.recvfrom(4096)
            finally:
                sock2.close()

        # A2S_INFO Response parsen (0x49 = 'I')
        if data[4:5] != b"\x49":
            return None

        offset = 6  # Header (4) + Typ (1) + Protocol (1)

        def read_str(d: bytes, pos: int):
            end = d.index(b"\x00", pos)
            return d[pos:end].decode("utf-8", errors="replace"), end + 1

        name,    offset = read_str(data, offset)
        mapname, offset = read_str(data, offset)
        folder,  offset = read_str(data, offset)
        game,    offset = read_str(data, offset)
        offset += 2  # App-ID (short)

        players     = data[offset];     offset += 1
        max_players = data[offset];     offset += 1
        bots        = data[offset];     offset += 1
        server_type = chr(data[offset]); offset += 1
        environment = chr(data[offset]); offset += 1
        visibility  = data[offset];     offset += 1

        return {
            "name":        name,
            "map":         mapname,
            "players":     players,
            "max_players": max_players,
            "bots":        bots,
            "type":        server_type,
            "password":    visibility == 1,
            "game":        game,
        }
    except (socket.timeout, socket.gaierror):
        return None
    except Exception as e:
        log.debug(f"[A2S] Query Fehler ({ip}:{port}): {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  FTP-Manager  (sync, läuft in ThreadPoolExecutor)
# ══════════════════════════════════════════════════════════════
class FTPManager:
    # Typische Nitrado-Pfade für DayZ Konsolen-Server
    NITRADO_SEARCH_PATHS = [
        "/games/{user}/noftp/dayz/config",
        "/games/{user}/noftp/dayz/profiles",
        "/games/{user}/noftp/dayz",
        "/noftp/dayz/config",
        "/noftp/dayz/profiles",
        "/dayz/config",
        "/dayz/profiles",
        "/dayz",
        "/",
    ]

    # Typische Orte des mpmissions-Ordners (Konsole: dayzps = PS4/PS5, dayzxb = Xbox)
    MPMISSIONS_SEARCH_PATHS = [
        "/dayzps_missions",
        "/dayzxb_missions",
        "/games/{user}/noftp/dayz/mpmissions",
        "/noftp/dayz/mpmissions",
        "/dayzps/mpmissions",
        "/dayzxb/mpmissions",
        "/dayz/mpmissions",
        "/mpmissions",
    ]

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host     = host
        self.port     = int(port)
        self.user     = user
        self.password = password
        # Eine gehaltene FTP-Verbindung mit Reconnect-Fallback statt 2–3 neuer
        # Verbindungen pro Poll-Zyklus – schneller und schont den Nitrado-Server.
        self._ftp: Optional[ftplib.FTP] = None
        self._ftp_lock = threading.Lock()   # Methoden laufen in Executor-Threads
        self.consecutive_failures = 0       # Zähler für die Adminlog-Ausfall-Warnung
        self.last_error: str = ""

    def _connect(self) -> ftplib.FTP:
        ftp = ftplib.FTP()
        ftp.connect(self.host, self.port, timeout=30)
        ftp.login(self.user, self.password)
        ftp.encoding = "utf-8"
        return ftp

    def _drop_conn(self):
        if self._ftp is not None:
            try:
                self._ftp.close()
            except Exception:
                pass
            self._ftp = None

    def _with_conn(self, op):
        """Führt op(ftp) auf der gehaltenen Verbindung aus. Ist der Socket tot
        (Timeout, Server-Trennung), wird genau einmal neu verbunden und wiederholt.
        error_perm (Pfad/Rechte) gilt nicht als Verbindungsfehler."""
        with self._ftp_lock:
            for attempt in (1, 2):
                try:
                    if self._ftp is None:
                        self._ftp = self._connect()
                    else:
                        self._ftp.voidcmd("NOOP")   # lebt die Verbindung noch?
                    result = op(self._ftp)
                    self.consecutive_failures = 0
                    self.last_error = ""
                    return result
                except ftplib.error_perm:
                    # Server hat geantwortet → Verbindung ok, nur Pfad/Rechte-Problem
                    self.consecutive_failures = 0
                    raise
                except Exception as e:
                    self._drop_conn()
                    if attempt == 2:
                        self.consecutive_failures += 1
                        self.last_error = str(e)
                        raise

    def _effect_area_file_in(self, mission_dir: str) -> str:
        """Realer Pfad der cfgEffectArea.json im Mission-Ordner. Ein bereits
        vorhandenes File (beliebige Schreibweise) hat Vorrang – FTP kann
        case-sensitiv sein und der Server liest nur die Original-Datei."""
        for entry in self.list_dir(mission_dir):
            if entry.split("/")[-1].lower() == "cfgeffectarea.json":
                return entry
        return f"{mission_dir.rstrip('/')}/cfgEffectArea.json"

    @staticmethod
    def _full_path(directory: str, name: str) -> str:
        """Gibt den vollständigen Pfad zurück – egal ob NLST absolute oder relative Namen liefert."""
        if name.startswith("/"):
            return name
        return f"{directory.rstrip('/')}/{name}"

    def list_adm_files(self, directory: str) -> List[str]:
        def op(ftp):
            raw: List[str] = []
            ftp.cwd(directory)
            ftp.retrlines("NLST", raw.append)
            return raw
        try:
            raw = self._with_conn(op)
        except ftplib.error_perm:
            return []
        except Exception as e:
            log.debug(f"[FTP] list_adm_files({directory}): {e}")
            return []
        # NLST gibt nach cwd() oft nur Dateinamen ohne Pfad zurück →
        # immer den vollständigen Pfad zusammenbauen
        return sorted([
            self._full_path(directory, f)
            for f in raw
            if f.split("/")[-1].lower().endswith(".adm")
        ])

    def list_dir(self, directory: str) -> List[str]:
        def op(ftp):
            raw: List[str] = []
            ftp.cwd(directory)
            ftp.retrlines("NLST", raw.append)
            return raw
        try:
            raw = self._with_conn(op)
        except ftplib.error_perm:
            return []
        except Exception as e:
            log.debug(f"[FTP] list_dir({directory}): {e}")
            return []
        # Vollständige Pfade zurückgeben
        return [self._full_path(directory, e) for e in raw]

    def read_file(self, path: str) -> Optional[str]:
        def op(ftp):
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {path}", buf.write)
            return buf.getvalue()
        try:
            return self._with_conn(op).decode("utf-8", errors="replace")
        except Exception as e:
            log.debug(f"[FTP] read_file({path}): {e}")
            return None

    def read_file_ex(self, path: str) -> Tuple[Optional[str], str]:
        """Wie read_file, unterscheidet aber 'Datei fehlt' von echten Fehlern.
        Status: 'ok' (Inhalt gelesen), 'missing' (550 – Datei existiert nicht),
        'error' (Verbindung/Timeout/Rechte – Inhalt UNBEKANNT; die Datei darf
        dann NICHT als leer behandelt/überschrieben werden!)."""
        def op(ftp):
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {path}", buf.write)
            return buf.getvalue()
        try:
            return self._with_conn(op).decode("utf-8", errors="replace"), "ok"
        except ftplib.error_perm as e:
            if str(e).lstrip().startswith("550"):
                return None, "missing"
            log.warning(f"[FTP] read_file_ex({path}): {e}")
            return None, "error"
        except Exception as e:
            log.warning(f"[FTP] read_file_ex({path}): {e}")
            return None, "error"

    def read_from_offset(self, path: str, offset: int) -> Tuple[str, int]:
        def op(ftp):
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {path}", buf.write, rest=offset if offset > 0 else None)
            return buf.getvalue()
        try:
            raw = self._with_conn(op)
        except Exception as e:
            log.debug(f"[FTP] read_from_offset({path}): {e}")
            return "", offset
        # Der Server schreibt die ADM-Datei live – die letzte Zeile kann noch
        # unvollständig sein. Nur bis zum letzten Zeilenumbruch verarbeiten,
        # der Rest wird beim nächsten Poll (dann vollständig) gelesen.
        # Sonst ginge das Event der halben Zeile für immer verloren.
        if raw and not raw.endswith(b"\n"):
            cut = raw.rfind(b"\n")
            if cut == -1:
                return "", offset
            raw = raw[:cut + 1]
        return raw.decode("utf-8", errors="replace"), offset + len(raw)

    def write_file(self, path: str, content: str) -> bool:
        # Atomar: erst als .tmp hochladen, dann umbenennen – bricht die Verbindung
        # mitten im Upload ab, bleibt die Zieldatei unversehrt
        tmp = path + ".tmp"
        def op(ftp):
            buf = io.BytesIO(content.encode("utf-8"))
            ftp.storbinary(f"STOR {tmp}", buf)
            try:
                ftp.rename(tmp, path)
            except ftplib.error_perm:
                # RNTO überschreibt nicht auf jedem FTP-Server → Ziel löschen,
                # aber erst hier (Zieldatei so kurz wie möglich weg)
                ftp.delete(path)
                ftp.rename(tmp, path)
            return True
        try:
            return bool(self._with_conn(op))
        except Exception as e:
            log.error(f"[FTP] write_file({path}): {e}")
            return False

    def delete_file(self, path: str) -> bool:
        """Löscht eine Datei; False wenn nicht vorhanden/kein Zugriff."""
        def op(ftp):
            ftp.delete(path)
            return True
        try:
            return bool(self._with_conn(op))
        except ftplib.error_perm:
            return False      # Datei existiert nicht → nichts zu tun
        except Exception as e:
            log.debug(f"[FTP] delete_file({path}): {e}")
            return False

    def file_size(self, path: str) -> int:
        def op(ftp):
            return ftp.size(path)
        try:
            return int(self._with_conn(op) or 0)
        except Exception:
            return 0

    def discover_paths(self, map_name: str = "ChernarusPlus") -> Dict[str, str]:
        """Durchsucht alle bekannten Nitrado-Pfade und gibt gefundene Verzeichnisse zurück.
        Findet zusätzlich mpmissions/<mission>/cfgEffectArea.json für die Shop-Auslieferung."""
        found: Dict[str, str] = {}

        # FTP-Benutzernamen für Pfad-Templates extrahieren
        user_part = self.user.split("_")[0] if "_" in self.user else self.user

        search_paths = []
        for p in self.NITRADO_SEARCH_PATHS:
            search_paths.append(p.replace("{user}", user_part))

        for path in search_paths:
            adm = self.list_adm_files(path)
            if adm:
                log.info(f"[FTP] ✅ ADM-Logs gefunden: {path} ({len(adm)} Dateien)")
                found["log_dir"] = path
                # ban.txt suchen – list_dir gibt jetzt vollständige Pfade zurück
                entries = self.list_dir(path)
                ban_entries = [e for e in entries if "ban" in e.split("/")[-1].lower()]
                if ban_entries:
                    found["ban_file"] = ban_entries[0]
                else:
                    found["ban_file"] = f"{path.rstrip('/')}/ban.txt"
                break

        if "log_dir" not in found:
            log.warning("[FTP] ⚠️  Keine ADM-Log-Dateien gefunden. "
                        "Prüfe FTP-Zugangsdaten und Pfade in config.json.")

        # ── mpmissions/<mission>/cfgEffectArea.json suchen ────────
        mission_candidates: List[str] = []
        # Aus gefundenem Log-Verzeichnis ableiten (z.B. /dayzps/config → /dayzps/mpmissions)
        if "log_dir" in found:
            base = found["log_dir"].rstrip("/")
            for suffix in ("/config", "/profiles"):
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
                    break
            if base:
                mission_candidates.append(f"{base}/mpmissions")
        for p in self.MPMISSIONS_SEARCH_PATHS:
            cand = p.replace("{user}", user_part)
            if cand not in mission_candidates:
                mission_candidates.append(cand)

        wanted = _mission_folder_for_map(map_name).lower()
        for mp_dir in mission_candidates:
            entries = self.list_dir(mp_dir)
            missions = [e for e in entries if "dayzoffline" in e.split("/")[-1].lower()]
            if not missions:
                continue
            # Bevorzugt den Ordner der konfigurierten Map, sonst den ersten Treffer
            mission = next((m for m in missions
                            if m.split("/")[-1].lower() == wanted), missions[0])
            found["mission_dir"]     = mission
            found["cfg_effect_area"] = self._effect_area_file_in(mission)
            log.info(f"[FTP] ✅ Mission-Ordner gefunden: {mission}")
            break

        if "cfg_effect_area" not in found:
            # Fallback: begrenzte Breitensuche über den FTP-Baum (Idee aus Referenzbot)
            hit = self._find_mission_bfs()
            if hit:
                found["mission_dir"]     = hit
                found["cfg_effect_area"] = self._effect_area_file_in(hit)
                log.info(f"[FTP] ✅ Mission-Ordner per Breitensuche gefunden: {hit}")

        if "cfg_effect_area" not in found:
            log.warning("[FTP] ⚠️  Kein mpmissions-Ordner gefunden – für die Shop-Auslieferung "
                        "muss cfg_effect_area_path in config.json manuell gesetzt werden.")

        return found

    def _find_mission_bfs(self, max_depth: int = 4, max_dirs: int = 200) -> Optional[str]:
        """Begrenzte Breitensuche nach einem dayzOffline.*-Mission-Ordner –
        Fallback, wenn die festen Kandidatenpfade nichts liefern."""
        queue: List[Tuple[str, int]] = [("/", 0)]
        seen = 0
        while queue and seen < max_dirs:
            current, depth = queue.pop(0)
            seen += 1
            for e in self.list_dir(current):
                name = e.split("/")[-1].lower()
                if name.startswith("dayzoffline"):
                    return e
                # Nur vermutliche Verzeichnisse (ohne Punkt) weiterverfolgen
                if depth + 1 < max_depth and "." not in name:
                    queue.append((e, depth + 1))
        return None


# ══════════════════════════════════════════════════════════════
#  Standort-Datenbank & iZurvive-Hilfsfunktionen
#  Koordinaten: X=Ost, Y=Nord, Z=Höhe  (DayZ pos=<X,Y,Z>)
# ══════════════════════════════════════════════════════════════
_MAP_LOCATIONS: Dict[str, List[Tuple[str, float, float]]] = {
    "ChernarusPlus": [
        ("Chernogorsk",          2946, 7693),
        ("Elektrozavodsk",       4452, 9839),
        ("Novodmitrovsk",        6730, 14350),
        ("Severograd",           4455, 13900),
        ("Krasnostav",           8990, 12700),
        ("Svetlojarsk",          9870, 12200),
        ("Berezino",             8481, 9150),
        ("Solnichny",            7510, 12700),
        ("Zelenogorsk",          2730, 5110),
        ("Pavlovo",              2880, 3480),
        ("Vybor",                3960, 5980),
        ("Green Mountain",       2560, 5760),
        ("Kabanino",             4470, 6560),
        ("Stary Sobor",          5110, 7240),
        ("Novy Sobor",           5520, 7850),
        ("Grishino",             4050, 7890),
        ("Guglovo",              6900, 9300),
        ("Polana",               6600, 10600),
        ("Mogilevka",            5890, 8720),
        ("Pusta",                6100, 8100),
        ("Vavilovo",             7370, 8880),
        ("Nadezhdino",           2800, 9400),
        ("Kamyshovo",            6190, 11300),
        ("Kamenka",              1010, 6070),
        ("Balota",               1790, 6970),
        ("Komarovo",             1600, 8800),
        ("Prigorodki",           2760, 7860),
        ("Krasnoe",              2130, 11150),
        ("Sinystok",             2000, 12100),
        ("Novaya Petrovka",      3610, 13500),
        ("Tisy Military Base",   1050, 13800),
        ("Kumyrna",              3800, 11600),
        ("Lopatino",             3780, 9970),
        ("NWAF",                 4640, 10350),
        ("NE Airfield",          8180, 13200),
        ("Karer Krasnaya Zarya", 8658, 12823),
        ("Dubrovka",             6910, 9900),
        ("Vyshnoye",             7340, 10900),
        ("Gorka",                6610, 9640),
        ("Vysotovo",             5680, 9190),
        ("Rogovo",               3760, 6920),
    ],
    "Livonia": [
        ("Nadbor",       6000, 5000),
        ("Sitnik",       4000, 2500),
        ("Topolin",      1800, 1800),
        ("Radacz",       3200, 4200),
        ("Bialy Brzeg",  8000, 3000),
        ("Grabin",       9000, 7000),
        ("Flintstone",   11000, 6000),
        ("Lukow",        2000, 8000),
        ("Puszcza",      4500, 7000),
        ("Polana",       6500, 8500),
        ("Dabrowa",      8500, 9000),
        ("Losino",       10000, 9500),
        ("Tarnow",       5500, 11000),
    ],
    "Sakhal": [
        ("Klen",        5500, 5500),
        ("Kvoshnino",   3000, 7000),
        ("Tikhaya Bay", 8000, 6000),
        ("Rikhov",      6000, 9000),
        ("Sever",       7500, 10000),
        ("Tulga",       9000, 8000),
        ("Podgorsk",    4000, 10000),
        ("Volcanka",    2500, 4000),
    ],
}

def _nearest_location(x: float, y: float, map_name: str = "ChernarusPlus") -> Optional[str]:
    """Gibt den Namen des nächsten Orts zurück (max. 1500 m Radius)."""
    locs = _MAP_LOCATIONS.get(map_name, _MAP_LOCATIONS["ChernarusPlus"])
    if not locs:
        return None
    nearest = min(locs, key=lambda l: (l[1] - x) ** 2 + (l[2] - y) ** 2)
    dist = ((nearest[1] - x) ** 2 + (nearest[2] - y) ** 2) ** 0.5
    return nearest[0] if dist <= 1500 else None

def _izurvive_url(x: float, y: float, map_name: str = "ChernarusPlus") -> str:
    return f"https://www.izurvive.com/?m={map_name}#l={x:.1f};{y:.1f}"

def _location_field_value(pos_str: Optional[str]) -> Optional[str]:
    """
    Parst 'X, Y, Z' aus pos_str (DayZ pos=<X,Y,Z>: X=Ost, Y=Nord, Z=Hoehe)
    und gibt einen Discord-Markdown-String mit klickbarem iZurvive-Link zurueck.
    """
    if not pos_str:
        return None
    parts = [p.strip() for p in pos_str.split(",")]
    if len(parts) < 3:
        return None
    try:
        x = float(parts[0])
        y = float(parts[1])
        z = float(parts[2])
    except ValueError:
        return None
    map_name = cfg.config.get("map_name", "ChernarusPlus")
    url  = _izurvive_url(x, y, map_name)
    loc  = _nearest_location(x, y, map_name)
    near = f"\n*(Near {loc})*" if loc else ""
    return f"[{x:.1f}, {y:.1f}, {z:.1f}]({url}){near}"


# ══════════════════════════════════════════════════════════════
#  DayZ Log-Parser
#  Quelle: Nitrado DayZ Konsolen-Server .ADM Logs
# ══════════════════════════════════════════════════════════════

class DayZLogParser:
    # Spieler-Positionen in-memory halten
    player_positions: Dict[str, Dict] = {}

    # Spieler-Muster: Name + optionale Steam-ID.
    # Tolerant gegenüber dem echten Nitrado-Konsolen-ADM-Format:
    #   Player "Name" (DEAD) (id=ABC123 pos=<7500.0, 8500.0, 12.3>)[HP: 85.6]
    # - "(DEAD)" zwischen Name und id-Klammer
    # - kein oder mehrere Leerzeichen vor "(id=..."
    # - pos=<...> INNERHALB der id-Klammer (id wird ohne pos-Anteil erfasst)
    # - "[HP: ...]" direkt hinter der Klammer
    PLAYER = (r'Player\s*"([^"]+)"'
              r'(?:\s*\(DEAD\))?'
              r'(?:\s*\(id=([^)\s]+)[^)]*\))?'
              r'(?:\s*\[HP:[^\]]*\])?')

    # ── Regex-Muster ──────────────────────────────────────────
    P = {
        # Konsolen-Format: pos INNERHALB der id-Klammer, pro Spieler
        "position": re.compile(
            r'Player\s*"([^"]+)"(?:\s*\(DEAD\))?\s*\(id=([^)\s]+)\s+pos\s*=\s*<([\d., \-]+)>[^)]*\)',
            re.IGNORECASE
        ),
        # Altes PC-Format: pos irgendwo hinter dem Spieler
        "position_legacy": re.compile(
            r'Player "([^"]+)"(?:\s+\(id=([^)]+)\))?.*?(?:pos|position)=<([\d., \-]+)>',
            re.IGNORECASE
        ),
        # PvP-Kill – tolerant gegenüber fehlender ID oder Zusatztext
        "kill_pvp": re.compile(
            PLAYER + r'\s*(?:was\s+)?(?:killed|murdered)\s+by\s+' + PLAYER +
            r'(?:\s+with\s+(.+?))?(?:\s+from\s+([\d.,]+)\s*m(?:eters?)?)?(?:\s+at\s+pos=<([\d., \-]+)>)?\s*$',
            re.IGNORECASE
        ),
        # Umwelt-Tod (kein PvP) – verschiedene Formulierungen
        "kill_env": re.compile(
            PLAYER + r'\s*(?:died|was killed|has died|perished|bled out|starved|dehydrated|drowned|suffocated|froze to death)'
            r'[.!]?'
            r'(?:\s+by\s+(.+?))?(?:\s+at\s+pos=<([\d., \-]+)>)?(?:\s+due to\s+(.+?))?(?:[.!]|\s|$)',
            re.IGNORECASE
        ),
        # Suicide
        "suicide": re.compile(
            PLAYER + r'\s*(?:committed suicide|killed themselves|blew themselves up|ended their life)',
            re.IGNORECASE
        ),
        # Damage/Hit – tolerant bei Bodypart / Waffe / Munition / Distanz
        "damage": re.compile(
            PLAYER + r'\s*(?:was\s+)?hit by\s+' + PLAYER +
            r'(?:\s+into\s+(.+?))?'
            r'(?:\s+for\s+([\d.,]+)\s+damage)?'
            r'(?:\s*\([^)]*\))?'
            r'(?:\s+with\s+(.+?))?'
            r'(?:\s+from\s+([\d.,]+)\s*m(?:eters?)?)?'
            r'(?:\s+at\s+pos=<([\d., \-]+)>)?\s*$',
            re.IGNORECASE
        ),
        # Connect – Konsole schreibt "is connected"
        "connect": re.compile(
            PLAYER + r'\s+(?:is\s+)?connected\b(?:\s+from\s+.+?)?(?:\s+at\s+pos=<([\d., \-]+)>)?',
            re.IGNORECASE
        ),
        # Disconnect – Konsole schreibt "has been disconnected"
        "disconnect": re.compile(
            PLAYER + r'\s+(?:has\s+been\s+)?disconnected\b(?:\s+from\s+.+?)?(?:\s+at\s+pos=<([\d., \-]+)>)?',
            re.IGNORECASE
        ),
        # Is Connecting
        "connecting": re.compile(
            PLAYER + r'\s+is connecting(?:\s+from\s+.+?)?(?:\s+at\s+pos=<([\d., \-]+)>)?',
            re.IGNORECASE
        ),
        # Chat (Side / Direct / Vehicle / Megaphone / Radio)
        "chat": re.compile(
            r'\((Side|Direct|Vehicle|Megaphone|Radio|GlobalBanMessage|Unknown)\) ([^:]+): (.+)',
            re.IGNORECASE
        ),
        # Chat – Konsolen-Format: Chat("Name"(id=...)): Nachricht
        "chat_console": re.compile(
            r'Chat\s*\(\s*"([^"]+)"[^)]*\)\s*\)?\s*:\s*(.+)',
            re.IGNORECASE
        ),
        # Admin-Aktion
        "admin_action": re.compile(
            r'Admin "([^"]+)"(?:\s+\(id=([^)]+)\))?(?: issued command:? (.+))?',
            re.IGNORECASE
        ),
        # Basis-Bau
        "basebuild": re.compile(
            PLAYER + r'\s+(?:placed|built|constructed|dismantled|repaired|attached|removed|folded|packed|deployed|mounted|unmounted)\s+([^\n]+)',
            re.IGNORECASE
        ),
        # Fahrzeug
        "vehicle": re.compile(
            r'(Vehicle|Car|Truck|Heli|Helicopter|Boat|UH[\w-]+)\s+'
            r'(?:crashed|exploded|was damaged|was destroyed|burned|flipped)',
            re.IGNORECASE
        ),
        # Loot-Spawn
        "loot": re.compile(
            r'(Loot|Item)\s+"([^"]+)"\s+(spawned|despawned|created|deleted|moved)',
            re.IGNORECASE
        ),
    }

    # Event-Typ → Log-Typ (für Channel-Routing)
    EVENT_TO_LOG = {
        "kill_pvp":     "killfeed",
        "suicide":      "suicide",
        "kill_env":     "envdeath",
        "damage":       "damagefeed",
        "connect":      "joinleave",
        "disconnect":   "joinleave",
        "connecting":   "connecting",
        "chat":         "chat",
        "admin_action": "adminlog",
        "basebuild":    "basebuild",
        "vehicle":      "vehiclecrash",
        "loot":         "loot",
    }

    @classmethod
    def _players_found(cls, line: str) -> List[Dict[str, Optional[str]]]:
        return [{"name": name, "id": pid or None} for name, pid in re.findall(cls.PLAYER, line)]

    @classmethod
    def _set_position(cls, name: str, player_id: Optional[str], pos: str):
        cls.player_positions[name] = {
            "id": player_id,
            "position": pos.strip(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def _extract_ts(cls, line: str) -> str:
        ts_m = re.match(r'^(\d{2}:\d{2}:\d{2})\s*\|?\s*', line)
        return ts_m.group(1) if ts_m else ""

    @classmethod
    def _generic_kill_event(cls, line: str, ts: str) -> Optional[Dict]:
        players = cls._players_found(line)
        if len(players) < 2 or "killed by" not in line.lower():
            return None

        victim = players[0]
        killer = players[1]

        weapon = "Unbekannt"
        distance = "?"
        # Sehr tolerante Fallbacks für Zusatzinformationen
        m_weapon = re.search(r'\b(?:with|using)\s+(.+?)(?=\s+from\s+[\d.,]+\s*m|\s+at\s+pos=<|$)', line, re.IGNORECASE)
        if m_weapon:
            weapon = m_weapon.group(1).strip()
        m_dist = re.search(r'\bfrom\s+([\d.,]+)\s*m(?:eters?)?', line, re.IGNORECASE)
        if m_dist:
            distance = m_dist.group(1)

        pos_m = re.search(r'pos=<([\d., \-]+)>', line, re.IGNORECASE)
        if pos_m:
            cls._set_position(victim["name"], victim["id"], pos_m.group(1))

        return {
            "type": "kill_pvp",
            "timestamp": ts,
            "victim": victim["name"],
            "victim_id": victim["id"] or "Unbekannt",
            "killer": killer["name"],
            "killer_id": killer["id"] or "Unbekannt",
            "weapon": weapon,
            "distance": distance,
            "raw": line,
        }

    @classmethod
    def _generic_damage_event(cls, line: str, ts: str) -> Optional[Dict]:
        players = cls._players_found(line)
        if len(players) < 2 or "hit by" not in line.lower():
            return None

        victim = players[0]
        attacker = players[1]

        hit_zone = "Unbekannt"
        damage = "?"
        weapon = "Unbekannt"
        distance = "?"

        m_zone = re.search(r'\bhit by\b.*?\binto\s+(.+?)(?=\s+for\s+[\d.,]+\s+damage|\s+with\s+|$)', line, re.IGNORECASE)
        if m_zone:
            hit_zone = m_zone.group(1).strip()

        m_damage = re.search(r'\bfor\s+([\d.,]+)\s+damage\b', line, re.IGNORECASE)
        if m_damage:
            damage = m_damage.group(1)

        m_weapon = re.search(r'\bwith\s+(.+?)(?=\s+from\s+[\d.,]+\s*m|\s+at\s+pos=<|$)', line, re.IGNORECASE)
        if m_weapon:
            weapon = m_weapon.group(1).strip()

        m_dist = re.search(r'\bfrom\s+([\d.,]+)\s*m(?:eters?)?', line, re.IGNORECASE)
        if m_dist:
            distance = m_dist.group(1)

        pos_m = re.search(r'pos=<([\d., \-]+)>', line, re.IGNORECASE)
        if pos_m:
            cls._set_position(victim["name"], victim["id"], pos_m.group(1))

        return {
            "type": "damage",
            "timestamp": ts,
            "victim": victim["name"],
            "victim_id": victim["id"] or "Unbekannt",
            "attacker": attacker["name"],
            "attacker_id": attacker["id"] or "Unbekannt",
            "hit_zone": hit_zone,
            "damage": damage,
            "weapon": weapon,
            "distance": distance,
            "raw": line,
        }

    @classmethod
    def _generic_env_death_event(cls, line: str, ts: str) -> Optional[Dict]:
        """Tod ohne zweiten Spieler: Zombie, Explosion, Verbluten, Sturz usw."""
        players = cls._players_found(line)
        if not players:
            return None
        p = players[0]

        cause = "Umgebung"
        m = re.search(r'\b(?:killed\s+by|died\s+(?:by|from|of)|due\s+to)\s+(.+?)(?=\s+at\s+pos=<|\s+with\s+|\s*[.!]?\s*$)',
                      line, re.IGNORECASE)
        if m:
            cause = m.group(1).strip()
        else:
            for kw, txt in (("bled out", "Verblutet"), ("starved", "Verhungert"),
                            ("dehydrated", "Verdurstet"), ("drowned", "Ertrunken"),
                            ("suffocated", "Erstickt"), ("froze", "Erfroren"),
                            ("fall", "Sturzschaden")):
                if kw in line.lower():
                    cause = txt
                    break

        pos_m = re.search(r'pos\s*=\s*<([\d., \-]+)>', line, re.IGNORECASE)
        if pos_m:
            cls._set_position(p["name"], p["id"], pos_m.group(1))

        return {
            "type": "kill_env",
            "timestamp": ts,
            "player": p["name"],
            "player_id": p["id"] or "Unbekannt",
            "cause": cause,
            "raw": line,
        }

    @classmethod
    def _generic_env_damage_event(cls, line: str, ts: str) -> Optional[Dict]:
        """Treffer ohne zweiten Spieler: Zombie, FallDamage, Explosion, Tier usw."""
        players = cls._players_found(line)
        if not players or "hit by" not in line.lower():
            return None
        victim = players[0]

        attacker = "Umgebung"
        m_att = re.search(r'\bhit by\s+(.+?)(?=\s+into\s+|\s+for\s+[\d.,]+\s+damage|\s+with\s+|\s+from\s+[\d.,]+\s*m|\s+at\s+pos=<|\s*$)',
                          line, re.IGNORECASE)
        if m_att:
            attacker = m_att.group(1).strip()

        hit_zone = "Unbekannt"
        m_zone = re.search(r'\binto\s+(.+?)(?=\s+for\s+[\d.,]+\s+damage|\s+with\s+|\s*$)', line, re.IGNORECASE)
        if m_zone:
            hit_zone = m_zone.group(1).strip()

        damage = "?"
        m_damage = re.search(r'\bfor\s+([\d.,]+)\s+damage\b', line, re.IGNORECASE)
        if m_damage:
            damage = m_damage.group(1)

        weapon = "Unbekannt"
        m_weapon = re.search(r'\bwith\s+(.+?)(?=\s+from\s+[\d.,]+\s*m|\s+at\s+pos=<|\s*$)', line, re.IGNORECASE)
        if m_weapon:
            weapon = m_weapon.group(1).strip()

        pos_m = re.search(r'pos\s*=\s*<([\d., \-]+)>', line, re.IGNORECASE)
        if pos_m:
            cls._set_position(victim["name"], victim["id"], pos_m.group(1))

        return {
            "type": "damage",
            "timestamp": ts,
            "victim": victim["name"],
            "victim_id": victim["id"] or "Unbekannt",
            "attacker": attacker,
            "attacker_id": "Umgebung",
            "hit_zone": hit_zone,
            "damage": damage,
            "weapon": weapon,
            "distance": "?",
            "raw": line,
        }

    @classmethod
    def parse_line(cls, line: str):
        line = line.strip()
        if not line:
            return None

        ts = cls._extract_ts(line)

        # Positionen immer tracken – Konsolen-Format zuerst (pro Spieler in
        # der eigenen id-Klammer), sonst altes Format als Fallback
        tracked = False
        for pm in cls.P["position"].finditer(line):
            cls._set_position(pm.group(1), pm.group(2), pm.group(3))
            tracked = True
        if not tracked:
            pm = cls.P["position_legacy"].search(line)
            if pm:
                cls._set_position(pm.group(1), pm.group(2), pm.group(3))

        # Reihenfolge ist wichtig:
        # 1) Kill
        m = cls.P["kill_pvp"].search(line)
        if m:
            pos = m.group(7)
            if pos:
                cls._set_position(m.group(1), m.group(2), pos)
            return {
                "type": "kill_pvp",
                "timestamp": ts,
                "victim": m.group(1),
                "victim_id": m.group(2) or "Unbekannt",
                "killer": m.group(3),
                "killer_id": m.group(4) or "Unbekannt",
                "weapon": (m.group(5) or "Unbekannt").strip(),
                "distance": (m.group(6) or "?").strip(),
                "raw": line,
            }

        # 2) Suicide
        m = cls.P["suicide"].search(line)
        if m:
            return {
                "type": "suicide",
                "timestamp": ts,
                "player": m.group(1),
                "player_id": m.group(2) or "Unbekannt",
                "raw": line,
            }

        # 3) Environment death
        m = cls.P["kill_env"].search(line)
        if m and "killed by player" not in line.lower():
            # Gruppe 3 = "by <Ursache>", Gruppe 5 = "due to <Ursache>"
            cause = m.group(3) or m.group(5)
            if not cause:
                ev = cls._generic_env_death_event(line, ts)
                if ev:
                    return ev
                cause = "Unbekannte Ursache"
            return {
                "type": "kill_env",
                "timestamp": ts,
                "player": m.group(1),
                "player_id": m.group(2) or "Unbekannt",
                "cause": cause.strip() if isinstance(cause, str) else "Unbekannte Ursache",
                "raw": line,
            }

        # 4) Damage
        m = cls.P["damage"].search(line)
        if m:
            pos = m.group(9)
            if pos:
                cls._set_position(m.group(1), m.group(2), pos)
            return {
                "type": "damage",
                "timestamp": ts,
                "victim": m.group(1),
                "victim_id": m.group(2) or "Unbekannt",
                "attacker": m.group(3),
                "attacker_id": m.group(4) or "Unbekannt",
                "hit_zone": (m.group(5) or "Unbekannt").strip(),
                "damage": (m.group(6) or "?").strip(),
                "weapon": (m.group(7) or "Unbekannt").strip(),
                "distance": (m.group(8) or "?").strip(),
                "raw": line,
            }

        # 5) Verbindungen
        m = cls.P["connect"].search(line)
        if m:
            pos = m.group(3)
            if pos:
                cls._set_position(m.group(1), m.group(2), pos)
            return {
                "type": "connect",
                "timestamp": ts,
                "player": m.group(1),
                "player_id": m.group(2) or "Unbekannt",
                "position": pos.strip() if pos else None,
                "raw": line,
            }

        m = cls.P["disconnect"].search(line)
        if m:
            pos = m.group(3)
            if pos:
                cls._set_position(m.group(1), m.group(2), pos)
            return {
                "type": "disconnect",
                "timestamp": ts,
                "player": m.group(1),
                "player_id": m.group(2) or "Unbekannt",
                "position": pos.strip() if pos else None,
                "raw": line,
            }

        m = cls.P["connecting"].search(line)
        if m:
            pos = m.group(3)
            if pos:
                cls._set_position(m.group(1), m.group(2), pos)
            return {
                "type": "connecting",
                "timestamp": ts,
                "player": m.group(1),
                "player_id": m.group(2) or "Unbekannt",
                "position": pos.strip() if pos else None,
                "raw": line,
            }

        # 6) Chat
        m = cls.P["chat"].search(line)
        if m:
            return {
                "type": "chat",
                "timestamp": ts,
                "channel": m.group(1),
                "player": m.group(2).strip(),
                "message": m.group(3).strip(),
                "raw": line,
            }

        # 6b) Chat im Konsolen-Format: Chat("Name"(id=...)): Nachricht
        m = cls.P["chat_console"].search(line)
        if m:
            return {
                "type": "chat",
                "timestamp": ts,
                "channel": "Side",
                "player": m.group(1).strip(),
                "message": m.group(2).strip().strip('"'),
                "raw": line,
            }

        # 7) Admin-Aktion
        m = cls.P["admin_action"].search(line)
        if m:
            return {
                "type": "admin_action",
                "timestamp": ts,
                "admin": m.group(1),
                "admin_id": m.group(2) or "Unbekannt",
                "command": m.group(3) or "",
                "raw": line,
            }

        # 8) Basis-Bau
        m = cls.P["basebuild"].search(line)
        if m:
            return {
                "type": "basebuild",
                "timestamp": ts,
                "player": m.group(1),
                "player_id": m.group(2) or "Unbekannt",
                "item": m.group(3).strip(),
                "raw": line,
            }

        # 9) Fahrzeug
        m = cls.P["vehicle"].search(line)
        if m:
            return {
                "type": "vehicle",
                "timestamp": ts,
                "raw": line,
            }

        # 10) Loot
        m = cls.P["loot"].search(line)
        if m:
            return {
                "type": "loot",
                "timestamp": ts,
                "item": m.group(2),
                "action": m.group(3),
                "raw": line,
            }

        # 11) Fallbacks – garantieren, dass jedes Feed-Ereignis gepostet wird,
        #     auch wenn die Zeile vom erwarteten Muster abweicht
        low = line.lower()

        # Suizid (z.B. mit "(DEAD)" oder Zusatztext zwischen Name und Schlüsselwort)
        if any(kw in low for kw in ("committed suicide", "killed themselves",
                                    "blew themselves up", "ended their life", "suicide")):
            players = cls._players_found(line)
            if players:
                return {
                    "type": "suicide",
                    "timestamp": ts,
                    "player": players[0]["name"],
                    "player_id": players[0]["id"] or "Unbekannt",
                    "raw": line,
                }

        # Kill: erst PvP (2 Spieler), sonst Umwelttod (Zombie, Explosion, ...)
        if "killed by" in low:
            ev = cls._generic_kill_event(line, ts)
            if ev:
                return ev
            ev = cls._generic_env_death_event(line, ts)
            if ev:
                return ev

        # Treffer: erst PvP (2 Spieler), sonst Umwelt (Zombie, FallDamage, ...)
        if "hit by" in low:
            ev = cls._generic_damage_event(line, ts)
            if ev:
                return ev
            ev = cls._generic_env_damage_event(line, ts)
            if ev:
                return ev

        # Sonstige Todesarten ohne "killed by"
        if any(kw in low for kw in (" died", "bled out", "perished", "starved",
                                    "dehydrated", "drowned", "suffocated", "froze to death")):
            ev = cls._generic_env_death_event(line, ts)
            if ev:
                return ev

        # Join/Leave/Connecting – falls das Format erneut abweicht
        if "connect" in low:
            players = cls._players_found(line)
            if players:
                p = players[0]
                if "disconnect" in low:
                    ctype = "disconnect"
                elif "connecting" in low:
                    ctype = "connecting"
                elif "connected" in low:
                    ctype = "connect"
                else:
                    ctype = None
                if ctype:
                    pos_m = re.search(r'pos\s*=\s*<([\d., \-]+)>', line, re.IGNORECASE)
                    if pos_m:
                        cls._set_position(p["name"], p["id"], pos_m.group(1))
                    return {
                        "type": ctype,
                        "timestamp": ts,
                        "player": p["name"],
                        "player_id": p["id"] or "Unbekannt",
                        "position": pos_m.group(1).strip() if pos_m else None,
                        "raw": line,
                    }

        # Basis-Bau – falls Verb/Format abweicht
        m_build = re.search(r'\b(placed|built|constructed|dismantled|repaired|attached|removed|folded|packed|deployed|mounted|unmounted)\s+(.+)$',
                            line, re.IGNORECASE)
        if m_build:
            players = cls._players_found(line)
            if players:
                return {
                    "type": "basebuild",
                    "timestamp": ts,
                    "player": players[0]["name"],
                    "player_id": players[0]["id"] or "Unbekannt",
                    "item": m_build.group(2).strip(),
                    "raw": line,
                }

        return None

    @classmethod
    def parse_lines(cls, content: str) -> List[Dict]:
        events = []
        for line in content.splitlines():
            ev = cls.parse_line(line)
            if ev:
                events.append(ev)
        return events


# ══════════════════════════════════════════════════════════════
#  Discord Embed-Builder
# ══════════════════════════════════════════════════════════════
def _footer(ev: Dict) -> str:
    return f"🕐 {ev['timestamp']}" if ev.get("timestamp") else ""

def _dist(d: str) -> str:
    return f"{d} m" if d != "?" else "Nah­kampf"

def _add_location_field(e: discord.Embed, ev: Dict, player_key: str):
    """Fügt das '📍 • Player Location'-Feld hinzu (gleiches Aussehen wie bei
    Connect/Disconnect): Position aus dem Event selbst oder die zuletzt
    getrackte Position des Spielers, als klickbarer iZurvive-Link."""
    name = ev.get(player_key) or ""
    pos = ev.get("position") or DayZLogParser.player_positions.get(name, {}).get("position")
    loc_val = _location_field_value(pos)
    if loc_val:
        e.add_field(name="📍 • Player Location", value=loc_val, inline=False)


class EmbedBuilder:
    @staticmethod
    def build(ev: Dict) -> Optional[discord.Embed]:
        t = ev["type"]
        if t == "kill_pvp":
            e = discord.Embed(
                title="☠️ KILL",
                description=f"**{ev['killer']}** hat **{ev['victim']}** getötet",
                color=0xE74C3C
            )
            e.add_field(name="Waffe",       value=ev["weapon"],         inline=True)
            e.add_field(name="Distanz",     value=_dist(ev["distance"]),inline=True)
            _add_location_field(e, ev, "victim")
            e.add_field(name="Killer ID",   value=f"`{ev['killer_id']}`",  inline=False)
            e.add_field(name="Opfer ID",    value=f"`{ev['victim_id']}`",  inline=False)

        elif t == "suicide":
            e = discord.Embed(
                title="💀 SELBSTMORD",
                description=f"**{ev['player']}** hat sein Leben beendet",
                color=0x7F8C8D
            )
            _add_location_field(e, ev, "player")
            e.add_field(name="Steam-ID", value=f"`{ev['player_id']}`", inline=False)

        elif t == "kill_env":
            e = discord.Embed(
                title="☠️ TOD",
                description=f"**{ev['player']}** ist gestorben",
                color=0xE67E22
            )
            e.add_field(name="Ursache",  value=ev["cause"],              inline=True)
            _add_location_field(e, ev, "player")
            e.add_field(name="Steam-ID", value=f"`{ev['player_id']}`",   inline=False)

        elif t == "damage":
            e = discord.Embed(
                title="🩸 TREFFER",
                description=f"**{ev['attacker']}** trifft **{ev['victim']}**",
                color=0xFF6B35
            )
            e.add_field(name="Schaden",     value=f"{ev['damage']} HP",  inline=True)
            e.add_field(name="Körperteil",  value=ev["hit_zone"],         inline=True)
            e.add_field(name="Waffe",       value=ev["weapon"],           inline=True)
            e.add_field(name="Distanz",     value=_dist(ev["distance"]),  inline=True)
            _add_location_field(e, ev, "victim")

        elif t == "connect":
            e = discord.Embed(
                title=f"→ • Connect • {ev.get('timestamp', '')}",
                description=f"**{ev['player']}** connected to the game server.",
                color=0x5865F2
            )
            _add_location_field(e, ev, "player")
            e.add_field(name="Steam-ID", value=f"`{ev['player_id']}`", inline=False)

        elif t == "disconnect":
            e = discord.Embed(
                title=f"← • Disconnect • {ev.get('timestamp', '')}",
                description=f"**{ev['player']}** left the game server.",
                color=0xE74C3C
            )
            _add_location_field(e, ev, "player")
            e.add_field(name="Steam-ID", value=f"`{ev['player_id']}`", inline=False)

        elif t == "connecting":
            e = discord.Embed(
                title=f"↔ • Connecting • {ev.get('timestamp', '')}",
                description=f"**{ev['player']}** verbindet sich...",
                color=0x3498DB
            )
            _add_location_field(e, ev, "player")
            e.add_field(name="Steam-ID", value=f"`{ev['player_id']}`", inline=False)

        elif t == "chat":
            icons = {"side":"📢","direct":"💬","vehicle":"🚗","megaphone":"📣","radio":"📻"}
            icon = icons.get(ev["channel"].lower(), "💬")
            e = discord.Embed(
                title=f"{icon} CHAT [{ev['channel'].upper()}]",
                description=f"**{ev['player']}**: {ev['message']}",
                color=0x5865F2
            )

        elif t == "admin_action":
            e = discord.Embed(
                title="🛡️ ADMIN AKTION",
                description=f"**{ev['admin']}** hat einen Befehl ausgeführt",
                color=0xF1C40F
            )
            if ev.get("command"):
                e.add_field(name="Befehl", value=f"`{ev['command']}`", inline=False)
            e.add_field(name="Admin-ID", value=f"`{ev['admin_id']}`", inline=False)

        elif t == "basebuild":
            e = discord.Embed(
                title="🏗️ BASIS-BAU",
                description=f"**{ev['player']}** hat gebaut: **{ev['item']}**",
                color=0x8B4513
            )
            _add_location_field(e, ev, "player")
            e.add_field(name="Steam-ID", value=f"`{ev['player_id']}`", inline=False)

        elif t == "vehicle":
            e = discord.Embed(
                title="🚗 FAHRZEUG-EREIGNIS",
                description=ev["raw"],
                color=0xFF8C00
            )

        elif t == "loot":
            action_icons = {"spawned":"✅", "despawned":"❌", "created":"✅", "deleted":"❌"}
            icon = action_icons.get(ev.get("action","").lower(), "📦")
            e = discord.Embed(
                title=f"{icon} LOOT",
                description=f"**{ev.get('item','Unbekannt')}** → {ev.get('action','?')}",
                color=0x9B59B6
            )
        else:
            return None

        if t in ("connect", "disconnect", "connecting"):
            if ev.get("timestamp"):
                e.set_footer(text=f"Server Time: {ev['timestamp']}")
        elif _footer(ev):
            e.set_footer(text=_footer(ev))
        return e


# ══════════════════════════════════════════════════════════════
#  Bot-Klasse
# ══════════════════════════════════════════════════════════════
class DayZBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree    = app_commands.CommandTree(self)
        self.nitrado: Optional[NitradoAPI] = None
        self.ftp:     Optional[FTPManager]  = None
        self.parser   = DayZLogParser()
        self.shop:    Optional["ShopManager"] = None   # wird in on_ready initialisiert
        self._ftp_warned_ts   = 0.0    # Zeitpunkt der letzten FTP-Ausfall-Warnung
        self._ftp_warn_active = False  # Warnung aktiv → bei Erholung Entwarnung posten
        self._online_since: Optional[float] = None  # Server online seit (A2S, Bot-Sicht)
        self._restart_announced: set = set()  # (restart_ts, minuten) bereits angekündigt
        # Zonen-Pings (/zone create): wiederholte Pings im Cooldown-Intervall
        self._zone_last_ping: Dict[Tuple[str, str], float] = {}  # letzter Ping pro Zone+Spieler
        self._zone_pos_seen: Dict[str, str] = {}              # Spieler → bereits bewertetes last_seen
        self._discover_retry_ts = 0.0  # letzter Auto-Discovery-Retry (log_poll)

    async def setup_hook(self):
        guild_ids = cfg.config.get("guild_ids", [])
        if not guild_ids:
            log.warning("[BOT] Keine guild_ids konfiguriert – Befehle werden global registriert (24h Verzögerung).")
            await self.tree.sync()
        else:
            for gid in guild_ids:
                g = discord.Object(id=int(gid))
                self.tree.copy_global_to(guild=g)
                await self.tree.sync(guild=g)
                log.info(f"[BOT] Slash-Befehle für Guild {gid} registriert.")

    async def on_ready(self):
        log.info(f"[BOT] ✅ Eingeloggt als {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="DayZ Server Logs 🎮")
        )
        # on_ready feuert auch bei jedem Discord-Reconnect → nur einmal initialisieren
        # (sonst leakt die alte aiohttp-Session und FTP wird unnötig neu gescannt)
        if cfg.has_nitrado_token() and str(cfg.config.get("service_id") or "").strip():
            await self.init_nitrado()
        else:
            log.warning("[BOT] ⚠️ Noch kein Nitrado-Token/Server eingerichtet – "
                        "führe im Discord /setup token aus.")
        # Nahezu-Echtzeit: höchstens 10s zwischen den Polls, mindestens 5s
        # (schont den FTP-Server). Größere Werte aus alten Configs werden
        # automatisch begrenzt, damit Feeds sofort nach Erscheinen posten.
        interval = int(cfg.config.get("log_poll_interval_seconds", 10))
        if interval > 10:
            log.info(f"[POLL] log_poll_interval_seconds={interval} wird auf 10s begrenzt (Echtzeit-Feeds)")
            interval = 10
        interval = max(5, interval)
        self.log_poll.change_interval(seconds=interval)
        if not self.log_poll.is_running():
            self.log_poll.start()
        if not self.economy_backup.is_running():
            self.economy_backup.start()
        status_iv = max(60, int(cfg.config.get("status_update_interval_seconds", 180)))
        self.status_update.change_interval(seconds=status_iv)
        if not self.status_update.is_running():
            self.status_update.start()
        if not self.restart_scheduler.is_running():
            self.restart_scheduler.start()
        if not announcement_scheduler.is_running():
            announcement_scheduler.start()

    async def init_nitrado(self, force: bool = False):
        """Initialisiert NitradoAPI + FTPManager + ShopManager aus der Config.
        force=True (für /setup token) ersetzt bestehende Instanzen – die alte
        aiohttp-Session wird dabei sauber geschlossen."""
        if force and self.nitrado is not None:
            try:
                await self.nitrado.close()
            except Exception:
                pass
            self.nitrado = None
        if force:
            self.ftp = None

        if self.nitrado is None:
            self.nitrado = NitradoAPI(
                token=cfg.config["nitrado_token"],
                service_id=str(cfg.config.get("service_id") or ""),
                base=cfg.config.get("nitrado_api_base", "https://api.nitrado.net"),
            )
        if self.ftp is None and all(str(cfg.config.get(k) or "").strip()
                                    for k in ("ftp_host", "ftp_user", "ftp_password")):
            self.ftp = FTPManager(
                host=cfg.config["ftp_host"],
                port=cfg.config.get("ftp_port", 21),
                user=cfg.config["ftp_user"],
                password=cfg.config["ftp_password"],
            )
            try:
                await self._auto_discover()
            except Exception as e:
                # FTP gerade nicht erreichbar → Init nicht abbrechen;
                # Discovery kann später per /ftp_scan nachgeholt werden
                log.warning(f"[FTP] Auto-Discovery fehlgeschlagen: {e}")
        # Shop-/Delivery-Manager initialisieren (braucht FTP + Nitrado)
        if self.shop is None and self.ftp is not None:
            self.shop = ShopManager(self)

    async def _auto_discover(self):
        """Sucht automatisch nach DayZ-Log-Verzeichnissen via FTP."""
        log.info("[FTP] Starte Auto-Discovery der Log-Verzeichnisse...")
        loop = asyncio.get_running_loop()
        found = await loop.run_in_executor(
            None,
            functools.partial(self.ftp.discover_paths,
                              cfg.config.get("map_name", "ChernarusPlus"))
        )

        changed = False
        if "log_dir" in found and not cfg.config.get("ftp_log_dir"):
            cfg.config["ftp_log_dir"] = found["log_dir"]
            changed = True
        if "ban_file" in found and not cfg.config.get("ftp_ban_file"):
            cfg.config["ftp_ban_file"] = found["ban_file"]
            changed = True
        if "mission_dir" in found and not cfg.config.get("ftp_mission_dir"):
            cfg.config["ftp_mission_dir"] = found["mission_dir"]
            changed = True
        if "cfg_effect_area" in found and not cfg.config.get("cfg_effect_area_path"):
            cfg.config["cfg_effect_area_path"] = found["cfg_effect_area"]
            changed = True
        if changed:
            cfg.save_config()
            log.info(f"[FTP] 💾 config.json aktualisiert: log_dir={cfg.config.get('ftp_log_dir')}, "
                     f"ban_file={cfg.config.get('ftp_ban_file')}, "
                     f"cfgEffectArea={cfg.config.get('cfg_effect_area_path')}")

        # Selbstheilung: Der konfigurierte cfgEffectArea-Pfad zeigt auf einen Ordner,
        # den es auf dem FTP gar nicht gibt (z.B. Chernarus-Pfad, obwohl der Server
        # Sakhal läuft) → Shop-Käufe landen sonst in einer Datei, die der Server nie
        # liest, und spawnen nie. Auf den tatsächlich gefundenen Ordner korrigieren.
        configured   = str(cfg.config.get("cfg_effect_area_path") or "")
        found_effect = found.get("cfg_effect_area")
        if configured and found_effect and configured != found_effect:
            parent  = configured.rsplit("/", 1)[0] or "/"
            entries = await loop.run_in_executor(None, self.ftp.list_dir, parent)
            if not entries:
                log.warning(f"[FTP] ⚠️ Konfigurierter cfg_effect_area_path existiert nicht "
                            f"auf dem FTP ({configured}) – korrigiert auf {found_effect}")
                cfg.config["cfg_effect_area_path"] = found_effect
                if found.get("mission_dir"):
                    cfg.config["ftp_mission_dir"] = found["mission_dir"]
                cfg.save_config()

    @tasks.loop(seconds=10)
    async def log_poll(self):
        if not self.ftp:
            return
        log_dir = cfg.config.get("ftp_log_dir")
        if not log_dir:
            # Discovery beim Start fehlgeschlagen oder noch nicht gelaufen →
            # automatisch erneut versuchen (alle 120s), sonst würden nie
            # Kills/Builds/Damage gepostet, bis jemand /ftp_scan ausführt
            now = time.time()
            if now - self._discover_retry_ts < 120:
                return
            self._discover_retry_ts = now
            try:
                await self._auto_discover()
            except Exception as e:
                log.warning(f"[FTP] Auto-Discovery-Retry fehlgeschlagen: {e}")
            log_dir = cfg.config.get("ftp_log_dir")
            if not log_dir:
                return
        try:
            loop = asyncio.get_running_loop()
            adm_files = await loop.run_in_executor(None, self.ftp.list_adm_files, log_dir)
            if not adm_files:
                await self._check_ftp_health()
                return

            latest = adm_files[-1]
            state = cfg.log_state.get("current")
            if state is None:
                # Erststart ohne gespeicherten Offset: Alt-Events NICHT in die
                # Feeds nachposten, sondern ab dem aktuellen Dateiende weiterlesen
                size_now = await loop.run_in_executor(None, self.ftp.file_size, latest)
                cfg.log_state["current"] = {"file": latest, "offset": int(size_now or 0)}
                cfg.log_state["last_poll_ts"] = time.time()
                cfg.save_log_state()
                log.info(f"[POLL] Erststart – überspringe Alt-Events, Offset={int(size_now or 0)} ({latest})")
                return

            # Offline-Lücke erkennen: War der Bot (oder das FTP) länger weg als
            # max_backlog_minutes, die aufgelaufenen Alt-Events NICHT nachposten –
            # sonst flutet der Bot die Feeds mit stundenalten Embeds.
            # last_poll_ts fehlt bei Updates von älteren Versionen → Lücke unbekannt
            # → sicherheitshalber ebenfalls überspringen (verliert max. 1 Poll-Zyklus).
            now = time.time()
            last_poll = float(cfg.log_state.get("last_poll_ts") or 0)
            backlog_limit = max(1, int(cfg.config.get("max_backlog_minutes", 10))) * 60
            gap = (now - last_poll) if last_poll else -1.0
            skip_backlog = (not last_poll) or gap > backlog_limit

            events: List[Dict] = []

            restart_detected = False
            if state["file"] != latest:
                # Neue ADM-Datei = Server wurde neu gestartet.
                # Den ungelesenen Rest der ALTEN Datei noch auslesen, damit
                # zwischen letztem Poll und Rotation keine Events verloren gehen.
                restart_detected = bool(state.get("file"))
                old_file = state.get("file")
                if old_file and old_file in adm_files and not skip_backlog:
                    old_tail, _ = await loop.run_in_executor(
                        None, self.ftp.read_from_offset, old_file, state.get("offset", 0)
                    )
                    if old_tail:
                        events.extend(self.parser.parse_lines(old_tail))
                        log.info(f"[POLL] {len(events)} Events aus dem Rest der alten Datei {old_file}")
                state = {"file": latest, "offset": 0}

            current_size = await loop.run_in_executor(None, self.ftp.file_size, latest)
            if current_size and state.get("offset", 0) > current_size:
                # Gleiche Datei, aber geschrumpft: Server hat die ADM beim Neustart geleert
                log.info(f"[POLL] Offset {state.get('offset', 0)} > Dateigröße {current_size} – Neustart (Truncation) erkannt")
                restart_detected = True
                state = {"file": latest, "offset": 0}

            if self.shop and (restart_detected or self.shop.cleanup_retry_needed):
                # Offene Käufe ausliefern; nach FTP-Fehler automatisch erneut versuchen.
                # Bei frisch erkanntem Neustart bleiben die Einträge in der Datei,
                # bis der Server per A2S wieder online ist (Mission-Load fertig),
                # und werden dann sofort entfernt
                self.shop.spawn_cleanup(delayed=restart_detected)

            if restart_detected:
                # Server-Neustart wirft alle Spieler → offene Spielzeit-Sitzungen beenden
                await loop.run_in_executor(None, db.close_all_sessions)

            if skip_backlog:
                # Fast-Forward ans aktuelle Dateiende – nichts nachposten
                size_now = current_size or await loop.run_in_executor(None, self.ftp.file_size, latest)
                if not size_now:
                    # Größe nicht ermittelbar (FTP-Fehler?) → nächsten Zyklus abwarten,
                    # last_poll_ts NICHT aktualisieren, damit der Skip erneut greift
                    await self._check_ftp_health()
                    return
                state = {"file": latest, "offset": int(size_now)}
                cfg.log_state["current"] = state
                cfg.log_state["last_poll_ts"] = now
                cfg.save_log_state()
                await loop.run_in_executor(None, db.close_all_sessions)
                mins = int(gap // 60) if gap >= 0 else 0
                log.info(f"[POLL] Bot war {mins} Min offline – überspringe Alt-Events, Offset={state['offset']} ({latest})")
                if gap >= 0:
                    info = discord.Embed(
                        title="⏭️ Alte Log-Events übersprungen",
                        description=(f"Der Bot war ca. **{mins} Minuten** offline. Log-Events aus "
                                     f"dieser Zeit werden nicht nachgepostet, um die Feeds nicht zu "
                                     f"fluten (Grenze: `max_backlog_minutes` in config.json)."),
                        color=0x95A5A6)
                    await _post_feed(None, "adminlog", info)
                await self._check_ftp_health()
                return

            content, new_offset = await loop.run_in_executor(
                None, self.ftp.read_from_offset, latest, state["offset"]
            )
            if content:
                state["offset"] = new_offset
                events.extend(self.parser.parse_lines(content))

            # Zustand auch bei reiner Rotation (ohne neuen Inhalt) speichern
            cfg.log_state["current"] = state
            cfg.log_state["last_poll_ts"] = now
            cfg.save_log_state()

            if events:
                log.info(f"[POLL] {len(events)} neue Events aus {latest}")
                # Rate-Limit-Schutz: pro Zyklus höchstens N Events posten
                cap = max(1, int(cfg.config.get("max_events_per_cycle", 30)))
                if len(events) > cap:
                    log.warning(f"[POLL] {len(events)} Events in einem Zyklus – "
                                f"poste nur die neuesten {cap} (max_events_per_cycle)")
                    events = events[-cap:]
                for ev in events:
                    await self._dispatch(ev)

            # Zonen-Pings: frisch getrackte Positionen gegen /zone-Zonen prüfen
            await self._check_zones()
            # Spielzeit-Belohnung für offene Sitzungen gutschreiben
            await self._credit_playtime()
            await self._check_ftp_health()
        except Exception as e:
            log.error(f"[POLL] Fehler: {e}")
            await self._check_ftp_health()

    @log_poll.before_loop
    async def _before_poll(self):
        await self.wait_until_ready()

    @tasks.loop(hours=24)
    async def economy_backup(self):
        keep = max(1, int(cfg.config.get("economy_backup_keep", 7)))
        loop = asyncio.get_running_loop()
        dest = await loop.run_in_executor(None, db.backup, keep)
        if dest:
            log.info(f"[ECON] Tages-Backup erstellt: {dest}")

    @economy_backup.before_loop
    async def _before_backup(self):
        await self.wait_until_ready()

    # ── Auto-Status-Embed (eine Nachricht pro Guild, wird editiert) ──
    @tasks.loop(seconds=180)
    async def status_update(self):
        # tasks.loop stoppt bei unbehandelten Exceptions dauerhaft → alles fangen
        try:
            await self._status_update_once()
        except Exception as e:
            log.error(f"[STATUS] Fehler: {e}")

    async def _status_update_once(self):
        ip = str(cfg.config.get("server_ip") or "").split(":")[0].strip()
        qport = int(cfg.config.get("query_port", 0) or 0)
        if not ip or not qport:
            return
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, a2s_query, ip, qport)
        if info:
            if self._online_since is None:
                self._online_since = time.time()
        else:
            self._online_since = None
        embed = self._build_status_embed(info)
        for gid_str in list(cfg.guilds.keys()):
            ch_id = cfg.get_channel(int(gid_str), "status")
            if not ch_id:
                continue
            ch = await self._resolve_channel(int(ch_id))
            if not ch:
                continue
            msg = None
            msg_id = cfg.guilds.get(gid_str, {}).get("status_message_id")
            if msg_id:
                try:
                    msg = await ch.fetch_message(int(msg_id))
                except Exception:
                    msg = None   # Nachricht gelöscht → neu senden
            try:
                if msg:
                    await msg.edit(embed=embed)
                else:
                    msg = await ch.send(embed=embed)
                    cfg.guilds.setdefault(gid_str, {})["status_message_id"] = msg.id
                    cfg.save_guilds()
            except Exception as e:
                log.error(f"[STATUS] Guild {gid_str}: {e}")

    @status_update.before_loop
    async def _before_status(self):
        await self.wait_until_ready()

    def _build_status_embed(self, info: Optional[Dict]) -> discord.Embed:
        if info:
            e = discord.Embed(title="🟢 Server ONLINE", color=0x2ECC71)
            e.add_field(name="Server", value=str(info.get("name") or "?"), inline=False)
            e.add_field(name="👥 Spieler",
                        value=f"{info.get('players', '?')} / {info.get('max_players', '?')}",
                        inline=True)
            e.add_field(name="🗺️ Map", value=str(info.get("map") or "?"), inline=True)
            if self._online_since:
                h, m = divmod(int((time.time() - self._online_since) // 60), 60)
                e.add_field(name="⏱️ Online seit (Bot-Sicht)",
                            value=f"{h} Std {m} Min", inline=True)
        else:
            e = discord.Embed(
                title="🔴 Server OFFLINE",
                description=("Keine Antwort auf die A2S-Abfrage – Server ist aus, "
                             "startet gerade oder der Query-Port stimmt nicht."),
                color=0xE74C3C)
        nxt = self._next_scheduled_restart()
        if nxt:
            e.add_field(name="⏰ Nächster Auto-Restart", value=f"<t:{int(nxt)}:R>", inline=True)
        e.set_footer(text="Auto-Status · aktualisiert sich automatisch")
        e.timestamp = datetime.now(timezone.utc)
        return e

    # ── Zonen-Pings (/zone create): Spieler in der Zone ───────
    async def _check_zones(self):
        """Bewertet frisch getrackte Spieler-Positionen gegen die konfigurierten
        Zonen und pingt WIEDERHOLT (alle zone_ping_cooldown_seconds, Default 5 Min),
        solange sich ein Spieler in der Zone befindet – auch mehrfach für denselben
        Spieler. Allowlist-Spieler werden nie gemeldet.
        Wird pro Poll-Zyklus aufgerufen; fängt eigene Fehler selbst ab, damit
        der Poll-Zyklus (Spielzeit-Gutschrift etc.) nie daran scheitert."""
        try:
            zones = [z for z in (cfg.config.get("zones") or [])
                     if isinstance(z, dict) and z.get("name")]
            if not zones:
                return
            # Zustände entfernter Zonen entsorgen
            zone_keys = {str(z["name"]).strip().lower() for z in zones}
            self._zone_last_ping = {k: v for k, v in self._zone_last_ping.items()
                                    if k[0] in zone_keys}
            cooldown = max(0, int(cfg.config.get("zone_ping_cooldown_seconds", 300)))
            now = time.time()
            for pname, info in list(DayZLogParser.player_positions.items()):
                # Nur NEU eingetroffene Positions-Samples bewerten – alte Daten
                # dürfen nach Zonen-Änderungen keine nachträglichen Pings auslösen
                last_seen = str(info.get("last_seen") or "")
                if self._zone_pos_seen.get(pname) == last_seen:
                    continue
                self._zone_pos_seen[pname] = last_seen
                parts = [p.strip() for p in str(info.get("position") or "").split(",")]
                if len(parts) < 2:
                    continue
                try:
                    px, pz = float(parts[0]), float(parts[1])   # ADM pos = <Ost, Nord, Höhe>
                except ValueError:
                    continue
                for zone in zones:
                    try:
                        zx = float(zone.get("x", 0.0))
                        zz = float(zone.get("z", 0.0))
                        zr = float(zone.get("radius", 0.0))
                    except (TypeError, ValueError):
                        continue
                    zkey = (str(zone["name"]).strip().lower(), pname)
                    inside = (px - zx) ** 2 + (pz - zz) ** 2 <= zr * zr
                    if not inside:
                        continue
                    if _player_in_allowlist(zone, pname):
                        continue     # Allowlist: nie pingen
                    if now - self._zone_last_ping.get(zkey, 0.0) < cooldown:
                        continue     # Wiederhol-Intervall noch nicht abgelaufen
                    self._zone_last_ping[zkey] = now
                    await self._post_zone_ping(zone, pname, info)
        except Exception as e:
            log.error(f"[ZONE] Zonen-Prüfung fehlgeschlagen: {e}")

    async def _post_zone_ping(self, zone: Dict, player: str, info: Dict):
        e = discord.Embed(
            title="🛡️ • Ping On Detection",
            description=f"**{player}** was located within the zone **{zone['name']}**.",
            color=0x9B59B6)
        loc = _location_field_value(info.get("position"))
        if loc:
            e.add_field(name="📍 • Player Location", value=loc, inline=False)
        e.add_field(name="🎯 Zone",
                    value=f"`{zone.get('x')}, {zone.get('z')}` · Radius **{zone.get('radius')} m**",
                    inline=False)
        e.set_footer(text=f"Zone: {zone['name']}")
        e.timestamp = datetime.now(timezone.utc)
        role_id = zone.get("role_id")
        content = f"<@&{int(role_id)}>" if role_id else None
        gid = int(zone["guild_id"]) if zone.get("guild_id") else None
        zone_ch = zone.get("channel_id")
        if zone_ch:
            await _post_feed(gid, "zone", e, content=content, channel_id=int(zone_ch))
        elif gid is None or cfg.get_channel(gid, "zone"):
            await _post_feed(gid, "zone", e, content=content)
        else:
            await _post_feed(gid, "adminlog", e, content=content)

    # ── Geplante Neustarts (/auto restart) ────────────────────
    def _next_scheduled_restart(self) -> Optional[float]:
        """Nächster geplanter Restart-Zeitpunkt (lokale Serverzeit des Bots)."""
        sched = cfg.config.get("auto_restart_schedule") or {}
        if not sched.get("enabled"):
            return None
        try:
            hh, mm = str(sched.get("first_time", "04:00")).split(":")
            step = timedelta(hours=max(1, int(sched.get("interval_hours", 4))))
            anchor = datetime.now().replace(hour=int(hh), minute=int(mm),
                                            second=0, microsecond=0)
        except Exception:
            return None
        now = datetime.now()
        while anchor > now:
            anchor -= step
        while anchor <= now:
            anchor += step
        return anchor.timestamp()

    @tasks.loop(seconds=30)
    async def restart_scheduler(self):
        # tasks.loop stoppt bei unbehandelten Exceptions dauerhaft → alles fangen
        try:
            await self._restart_scheduler_once()
        except Exception as e:
            log.error(f"[AUTO-RESTART] Fehler: {e}")

    async def _restart_scheduler_once(self):
        nxt = self._next_scheduled_restart()
        if nxt is None:
            if self._restart_announced:
                self._restart_announced.clear()
            return
        remaining = nxt - time.time()
        # Ankündigungen 15/5/1 Minuten vorher (45s-Fenster > 30s-Loop-Takt)
        for mins in (15, 5, 1):
            key = (int(nxt), mins)
            if (mins * 60 - 45) < remaining <= mins * 60 and key not in self._restart_announced:
                self._restart_announced.add(key)
                e = discord.Embed(
                    title=f"🔄 Server-Neustart in {mins} Minute{'n' if mins != 1 else ''}!",
                    description=(f"Geplanter Neustart um <t:{int(nxt)}:t> Uhr – "
                                 f"bitte sichere Position und Loot."),
                    color=0xE67E22 if mins <= 5 else 0xF1C40F)
                await self._post_restart_feed(e)
        # Restart auslösen
        key0 = (int(nxt), 0)
        if remaining <= 30 and key0 not in self._restart_announced:
            self._restart_announced.add(key0)
            try:
                ok, msg = await self.nitrado.restart()
            except Exception as ex:
                ok, msg = False, str(ex)
            log.info(f"[AUTO-RESTART] Geplanter Neustart ausgelöst: ok={ok} – {msg}")
            e = discord.Embed(
                title="🔄 Server wird jetzt neu gestartet" if ok
                      else "❌ Geplanter Neustart fehlgeschlagen",
                description=("Der geplante Neustart wurde über die Nitrado-API ausgelöst."
                             if ok else f"Nitrado-API-Fehler: {msg}"),
                color=0x2ECC71 if ok else 0xE74C3C)
            await self._post_restart_feed(e)
        # Alte Ankündigungs-Marker aufräumen
        cutoff = time.time() - 3600
        self._restart_announced = {k for k in self._restart_announced if k[0] > cutoff}

    @restart_scheduler.before_loop
    async def _before_restart_scheduler(self):
        await self.wait_until_ready()

    async def _post_restart_feed(self, embed: discord.Embed):
        """Postet in den restart-Feed; ohne konfigurierten Channel → adminlog."""
        for gid_str in cfg.guilds:
            gid = int(gid_str)
            lt = "restart" if cfg.get_channel(gid, "restart") else "adminlog"
            await _post_feed(gid, lt, embed)

    async def _try_refresh_ftp_credentials(self) -> bool:
        """Selbstheilung bei FTP-Dauerausfall: Zugangsdaten frisch über den
        Nitrado-Token holen und den FTPManager ersetzen, falls Nitrado sie
        geändert hat (z.B. Passwort-Rotation). True = neue Daten übernommen."""
        if not self.nitrado:
            return False
        try:
            info = await self.nitrado.get_info()
        except Exception:
            return False
        if not info:
            return False
        creds = NitradoAPI.extract_ftp_credentials(info)
        if not creds:
            return False
        changed = (creds["host"] != cfg.config.get("ftp_host")
                   or creds["user"] != cfg.config.get("ftp_user")
                   or creds["password"] != cfg.config.get("ftp_password")
                   or int(creds["port"]) != int(cfg.config.get("ftp_port") or 21))
        if not changed:
            return False
        cfg.config["ftp_host"]     = creds["host"]
        cfg.config["ftp_port"]     = creds["port"]
        cfg.config["ftp_user"]     = creds["user"]
        cfg.config["ftp_password"] = creds["password"]
        cfg.save_config()
        self.ftp = FTPManager(host=creds["host"], port=creds["port"],
                              user=creds["user"], password=creds["password"])
        log.info("[NITRADO] 🔄 FTP-Zugangsdaten über die API erneuert – "
                 "Verbindung wird mit den neuen Daten aufgebaut.")
        return True

    async def _check_ftp_health(self):
        """Warnt im Adminlog-Feed, wenn das FTP-Polling dauerhaft fehlschlägt
        (Passwort geändert, Nitrado-Wartung), und meldet die Erholung.
        Versucht vorher, die FTP-Zugangsdaten über den Nitrado-Token zu erneuern."""
        if not self.ftp:
            return
        fails     = self.ftp.consecutive_failures
        threshold = max(1, int(cfg.config.get("ftp_fail_warn_cycles", 10)))
        now = time.time()
        if fails >= threshold:
            if now - self._ftp_warned_ts >= 1800:   # höchstens alle 30 Min erneut warnen
                self._ftp_warned_ts   = now
                if await self._try_refresh_ftp_credentials():
                    # Zugangsdaten waren veraltet → mit den neuen weitermachen,
                    # keine Ausfall-Warnung nötig
                    self._ftp_warn_active = False
                    embed = discord.Embed(
                        title="🔄 FTP-Zugang automatisch erneuert",
                        description=("Die FTP-Zugriffe schlugen wiederholt fehl – der Bot "
                                     "hat die Zugangsdaten über den Nitrado-Token neu "
                                     "geholt und die Verbindung neu aufgebaut."),
                        color=0x2ECC71)
                    await _post_feed(None, "adminlog", embed)
                    return
                self._ftp_warn_active = True
                embed = discord.Embed(
                    title="🚨 FTP-Verbindung gestört",
                    description=(f"**{fails} FTP-Zugriffe in Folge fehlgeschlagen** "
                                 f"(Host `{cfg.config.get('ftp_host')}`).\n"
                                 f"Log-Feeds und Shop-Lieferungen sind unterbrochen!\n"
                                 f"Mögliche Ursachen: FTP-Passwort geändert, Nitrado-Wartung.\n"
                                 f"Letzter Fehler: `{self.ftp.last_error or 'unbekannt'}`"),
                    color=0xE74C3C)
                await _post_feed(None, "adminlog", embed)
        elif fails == 0 and self._ftp_warn_active:
            self._ftp_warn_active = False
            self._ftp_warned_ts   = 0.0
            embed = discord.Embed(
                title="✅ FTP-Verbindung wiederhergestellt",
                description="Der FTP-Zugriff funktioniert wieder – die Feeds laufen normal weiter.",
                color=0x2ECC71)
            await _post_feed(None, "adminlog", embed)

    async def _resolve_channel(self, channel_id: int):
        ch = self.get_channel(channel_id)
        if ch is not None:
            return ch
        try:
            return await self.fetch_channel(channel_id)
        except Exception as e:
            log.debug(f"[DISPATCH] fetch_channel({channel_id}) fehlgeschlagen: {e}")
            return None

    async def _dispatch(self, ev: Dict):
        log_type = DayZLogParser.EVENT_TO_LOG.get(ev["type"])
        if not log_type:
            return
        # Kill-Statistik, Sessions, Kill-Belohnung & Bounties verarbeiten
        rewards = await self._process_event_rewards(ev)
        embed = EmbedBuilder.build(ev)
        if not embed:
            return
        for gid_str in cfg.guilds:
            ch_id = cfg.get_channel(int(gid_str), log_type)
            if not ch_id:
                continue
            send_embed = embed
            reward_line = rewards.get(int(gid_str))
            if reward_line:
                send_embed = embed.copy()
                send_embed.add_field(name="💰 Belohnung", value=reward_line, inline=False)
            ch = await self._resolve_channel(int(ch_id))
            if ch:
                try:
                    await ch.send(embed=send_embed)
                except discord.Forbidden:
                    log.warning(f"[DISPATCH] Keine Rechte in Channel {ch_id} (Guild {gid_str})")
                except Exception as e:
                    log.error(f"[DISPATCH] Fehler in Guild {gid_str}: {e}")
            else:
                log.warning(f"[DISPATCH] Channel {ch_id} in Guild {gid_str} nicht gefunden")

    async def _process_event_rewards(self, ev: Dict) -> Dict[int, str]:
        """Nebenwirkungen eines Log-Events: Kill-Statistik schreiben, Spielzeit-
        Sitzungen öffnen/schließen, Kill-Belohnung und Kopfgelder an verlinkte
        Spieler auszahlen. Gibt pro Guild eine Belohnungszeile fürs Embed zurück."""
        out: Dict[int, str] = {}
        loop = asyncio.get_running_loop()
        t = ev["type"]
        try:
            if t == "connect":
                pid = ev.get("player_id")
                pid = pid if pid and pid != "Unbekannt" else None
                await loop.run_in_executor(None, db.open_session, ev["player"], pid)
                if pid:
                    await loop.run_in_executor(None, db.update_link_id, ev["player"], pid)

            elif t == "disconnect":
                await loop.run_in_executor(None, db.close_session, ev["player"])

            elif t == "kill_pvp":
                killer = ev.get("killer") or ""
                victim = ev.get("victim") or ""
                await loop.run_in_executor(
                    None, db.record_kill, killer, ev.get("killer_id"),
                    victim, ev.get("victim_id"), ev.get("weapon"), ev.get("distance"))
                for nm, key in ((killer, "killer_id"), (victim, "victim_id")):
                    pid = ev.get(key)
                    if nm and pid and pid != "Unbekannt":
                        await loop.run_in_executor(None, db.update_link_id, nm, pid)
                if killer and victim and killer.lower() != victim.lower():
                    reward = max(0, int(cfg.config.get("kill_reward", 0)))
                    links = await loop.run_in_executor(None, db.links_for_name, killer)
                    for lk in links:
                        gid, uid = int(lk["guild_id"]), int(lk["user_id"])
                        parts: List[str] = []
                        total = 0
                        if reward > 0:
                            total += reward
                            parts.append(f"+{_fmt_money(reward)} Kill-Belohnung")
                        bounty = await loop.run_in_executor(
                            None, db.claim_bounties, gid, victim, uid)
                        if bounty > 0:
                            total += bounty
                            parts.append(f"+{_fmt_money(bounty)} Kopfgeld 🎯")
                        if total > 0:
                            await loop.run_in_executor(None, db.add_wallet, gid, uid, total)
                            out[gid] = f"{' · '.join(parts)} → <@{uid}>"
        except Exception as e:
            log.error(f"[REWARD] Event-Verarbeitung fehlgeschlagen: {e}")
        return out

    async def _credit_playtime(self):
        """Schreibt verlinkten Spielern volle Spielzeit-Blöcke gut
        (playtime_reward: amount pro interval_minutes, z.B. 500 pro 30 Min)."""
        conf = cfg.config.get("playtime_reward") or {}
        amount = max(0, int(conf.get("amount", 0)))
        if amount <= 0:
            return
        interval = max(1, int(conf.get("interval_minutes", 30))) * 60
        loop = asyncio.get_running_loop()
        try:
            # Verpasste Connect-Events abfangen: verlinkte Spieler, die laut Log
            # gerade aktiv sind, aber keine offene Sitzung haben → Sitzung öffnen
            positions = dict(DayZLogParser.player_positions)
            await loop.run_in_executor(None, db.sync_sessions_from_positions, positions, 300)
            due = await loop.run_in_executor(None, db.playtime_credits_due, interval)
            for entry in due:
                links = await loop.run_in_executor(None, db.links_for_name, entry["name"])
                for lk in links:
                    gid, uid = int(lk["guild_id"]), int(lk["user_id"])
                    credit = amount * int(entry["blocks"])
                    await loop.run_in_executor(None, db.add_wallet, gid, uid, credit)
                    log.info(f"[PLAYTIME] {entry['name']}: +{credit} für <@{uid}> (Guild {gid})")
        except Exception as e:
            log.error(f"[PLAYTIME] Gutschrift fehlgeschlagen: {e}")


bot = DayZBot()


# ══════════════════════════════════════════════════════════════
#  Berechtigungs-Prüfung
# ══════════════════════════════════════════════════════════════
def _member_has_role_ids(member: discord.Member, role_ids: List) -> bool:
    """Prüft ob ein Member mindestens eine der konfigurierten Rollen-IDs besitzt."""
    if not role_ids:
        return False
    try:
        wanted = {int(r) for r in role_ids}
    except (TypeError, ValueError):
        return False
    return any(r.id in wanted for r in member.roles)

def _is_admin(interaction: discord.Interaction) -> bool:
    """Admin = Rolle aus admin_role_ids ODER Discord-Administrator.
    admin_role_name bleibt als Fallback erhalten (Abwärtskompatibilität)."""
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    if _member_has_role_ids(interaction.user, cfg.config.get("admin_role_ids", [])):
        return True
    role_name = cfg.config.get("admin_role_name", "")
    if role_name and any(r.name == role_name for r in interaction.user.roles):
        return True
    return False

def _is_economy_admin(interaction: discord.Interaction) -> bool:
    """Economy-Admin = economy_admin_role_ids ODER voller Admin."""
    if _is_admin(interaction):
        return True
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    return _member_has_role_ids(interaction.user, cfg.config.get("economy_admin_role_ids", []))

async def _deny(interaction: discord.Interaction):
    msg = ("❌ No permission. You need one of the configured admin roles "
           "(`admin_role_ids` in config.json) or Administrator rights.")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


async def _require_nitrado(interaction: discord.Interaction,
                           need_ftp: bool = False) -> bool:
    """True, wenn die Nitrado-Anbindung (und optional FTP) einsatzbereit ist.
    Sonst ephemere Hinweis-Meldung → Befehl mit `return` abbrechen."""
    if bot.nitrado is not None and (not need_ftp or bot.ftp is not None):
        return True
    msg = ("❌ Nitrado ist noch nicht eingerichtet.\n"
           "Führe zuerst `/setup token <dein-nitrado-token>` aus und wähle "
           "deinen Server im Dropdown aus.")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)
    return False


# ══════════════════════════════════════════════════════════════
#  /setup – Alle Log-Channels konfigurieren
# ══════════════════════════════════════════════════════════════
setup_group = app_commands.Group(name="setup", description="⚙️ Log-Channels konfigurieren")

@setup_group.command(name="feeds", description="⚙️ Feed-Channel für einen Log-Typ festlegen")
@app_commands.describe(feed="Welcher Feed?", channel="Ziel-Channel für diesen Feed")
@app_commands.choices(feed=[
    app_commands.Choice(name=LOG_TYPES[k][:100], value=k) for k in LOG_TYPES
])
async def setup_feeds(interaction: discord.Interaction,
                      feed: app_commands.Choice[str],
                      channel: discord.TextChannel):
    if not _is_admin(interaction):
        return await _deny(interaction)
    cfg.set_channel(interaction.guild_id, feed.value, channel.id)
    await interaction.response.send_message(
        f"✅ **{LOG_TYPES[feed.value]}** → {channel.mention}", ephemeral=True)


@setup_group.command(name="uebersicht", description="📋 Zeigt alle konfigurierten Channels")
async def setup_overview(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    guild_cfg = cfg.guilds.get(str(interaction.guild_id), {})
    embed = discord.Embed(title="📋 Aktuelle Channel-Konfiguration", color=0x5865F2)
    for lt, desc in LOG_TYPES.items():
        ch_id = guild_cfg.get(lt)
        embed.add_field(
            name=desc,
            value=f"<#{ch_id}>" if ch_id else "❌ Nicht gesetzt",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

async def _finish_token_setup(token: str, service_id: str,
                              service: Dict) -> discord.Embed:
    """Wendet Token + Server-Auswahl aus /setup token an: speichert beides,
    erkennt FTP-Zugang & aktuelle Karte, initialisiert Nitrado/FTP/Shop neu
    und gibt ein Ergebnis-Embed zurück."""
    old_service = str(cfg.config.get("service_id") or "").strip()
    cfg.config["nitrado_token"] = token
    cfg.config["service_id"]    = service_id
    if old_service and old_service != service_id:
        # Server-Wechsel: per-Server-Caches leeren, sonst zeigen Pfade,
        # Server-IP und Log-Offset noch auf den alten Server
        for k in ("ftp_log_dir", "ftp_ban_file", "ftp_profile_dir",
                  "ftp_mission_dir", "cfg_effect_area_path", "server_ip"):
            cfg.config[k] = ""
        cfg.log_state.pop("current", None)
        cfg.save_log_state()
        log.info(f"[SETUP] Server-Wechsel {old_service} → {service_id}: "
                 f"FTP-Pfade und Log-Position zurückgesetzt.")

    api = NitradoAPI(token=token, service_id=service_id,
                     base=cfg.config.get("nitrado_api_base", "https://api.nitrado.net"))
    try:
        info = await api.get_info()
    finally:
        await api.close()

    warnings = []
    if info:
        _apply_gameserver_info(info)
    else:
        warnings.append("⚠️ Gameserver-Infos konnten nicht geladen werden "
                        "(Nitrado-API-Fehler) – FTP/Karte nicht erkannt.")
    cfg.save_config()

    # Nitrado/FTP/Shop mit den neuen Daten (neu) initialisieren –
    # inklusive FTP-Auto-Discovery der Log-Verzeichnisse
    await bot.init_nitrado(force=True)

    details  = service.get("details") or {}
    name     = details.get("name") or details.get("game") or f"Service {service_id}"
    ftp_host = cfg.config.get("ftp_host") or "❌ Nicht gefunden"
    log_dir  = cfg.config.get("ftp_log_dir") or "❌ Nicht gefunden"
    if not cfg.config.get("ftp_host"):
        warnings.append("⚠️ Keine FTP-Zugangsdaten gefunden – Log-Feeds und "
                        "Shop-Lieferung funktionieren so nicht.")

    embed = discord.Embed(
        title="✅ Nitrado-Server eingerichtet",
        description=f"Der Bot arbeitet jetzt mit **{name}**.",
        color=0x2ECC71 if not warnings else 0xE67E22)
    embed.add_field(name="Service-ID",      value=f"`{service_id}`", inline=True)
    embed.add_field(name="Aktive Karte",    value=cfg.config.get("map_name", "–"), inline=True)
    embed.add_field(name="FTP-Host",        value=f"`{ftp_host}`",   inline=False)
    embed.add_field(name="Log-Verzeichnis", value=f"`{log_dir}`",    inline=False)
    if warnings:
        embed.add_field(name="Hinweise", value="\n".join(warnings), inline=False)
    embed.set_footer(text="Alle Werte wurden in config.json gespeichert – "
                          "beim nächsten Start ist kein /setup token nötig.")
    return embed


class NitradoServerSelectView(discord.ui.View):
    """Server-Auswahl für /setup token: Dropdown der über den Token
    verfügbaren Nitrado-Server + Bestätigen-Button."""

    def __init__(self, interaction: discord.Interaction, token: str,
                 services: List[Dict]):
        super().__init__(timeout=180)
        self.author_id = interaction.user.id
        self.token     = token
        self.selected: Optional[str] = None
        self._services = {str(s.get("id")): s for s in services}
        options = []
        for s in services[:25]:   # Discord erlaubt max. 25 Optionen pro Dropdown
            details = s.get("details") or {}
            label = str(details.get("name") or details.get("game")
                        or f"Service {s.get('id')}")[:100]
            desc  = " · ".join(x for x in (str(details.get("game") or "")[:50],
                                           str(s.get("status") or ""),
                                           f"ID {s.get('id')}") if x)[:100]
            options.append(discord.SelectOption(label=label,
                                                value=str(s.get("id")),
                                                description=desc or None))
        self.sel_server.options = options

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.author_id:
            await itx.response.send_message(
                "❌ Nur wer den Befehl aufgerufen hat, kann hier auswählen.", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="🖥️ Nitrado-Server auswählen",
                       options=[discord.SelectOption(label="wird geladen…", value="0")])
    async def sel_server(self, itx: discord.Interaction, select: discord.ui.Select):
        self.selected = select.values[0]
        await itx.response.defer()

    @discord.ui.button(label="✅ Server bestätigen", style=discord.ButtonStyle.success)
    async def confirm(self, itx: discord.Interaction, button: discord.ui.Button):
        if self.selected is None:
            return await itx.response.send_message(
                "❌ Bitte zuerst einen Server im Dropdown auswählen.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await itx.response.edit_message(
            content="🔧 Richte den Server ein (FTP-Zugang, Karte, Log-Verzeichnisse)…",
            embed=None, view=self)
        try:
            embed = await _finish_token_setup(
                self.token, self.selected, self._services.get(self.selected) or {})
        except Exception as e:
            log.error(f"[SETUP] /setup token fehlgeschlagen: {e}")
            embed = discord.Embed(
                title="❌ Einrichtung fehlgeschlagen",
                description=f"Unerwarteter Fehler: `{e}`\nBitte erneut versuchen.",
                color=0xE74C3C)
        await itx.edit_original_response(content=None, embed=embed, view=self)
        self.stop()


@setup_group.command(name="token",
                     description="🔑 Nitrado-Token setzen & Server per Dropdown auswählen")
@app_commands.describe(token="Dein Nitrado Long-Life-Token (Nitrado → Benutzereinstellungen → API-Schlüssel)")
async def setup_token(interaction: discord.Interaction, token: str):
    if not _is_admin(interaction):
        return await _deny(interaction)
    await interaction.response.defer(ephemeral=True)

    token = token.strip()
    api = NitradoAPI(token=token, service_id="",
                     base=cfg.config.get("nitrado_api_base", "https://api.nitrado.net"))
    try:
        services = await api.list_services()
    finally:
        await api.close()

    gameservers = [s for s in services
                   if str(s.get("type", "")).lower() == "gameserver"]
    if not gameservers:
        return await interaction.followup.send(
            "❌ Über diesen Token wurden keine Gameserver gefunden.\n"
            "Prüfe, ob der Token korrekt kopiert wurde "
            "(Nitrado → Benutzereinstellungen → API-Schlüssel, Long-Life-Token "
            "mit Berechtigung für deine Services).", ephemeral=True)

    desc = (f"Token akzeptiert – **{len(gameservers)} Server** gefunden.\n"
            "Wähle im Dropdown den Server aus, mit dem der Bot arbeiten soll, "
            "und bestätige. FTP-Zugang und die aktive Karte werden dann "
            "automatisch erkannt.")
    if len(gameservers) > 25:
        desc += "\n⚠️ Es werden nur die ersten 25 Server angezeigt."
    embed = discord.Embed(title="🔑 Nitrado-Server auswählen",
                          description=desc, color=0x5865F2)
    await interaction.followup.send(
        embed=embed,
        view=NitradoServerSelectView(interaction, token, gameservers),
        ephemeral=True)


bot.tree.add_command(setup_group)


# ══════════════════════════════════════════════════════════════
#  /show_feeds – Alle Feed-Channels auf einen Blick
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="show_feeds", description="📡 Zeigt alle Feed-Channels und ihren Status")
async def cmd_show_feeds(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    guild_cfg  = cfg.guilds.get(str(interaction.guild_id), {})
    active     = {lt: ch for lt, ch in guild_cfg.items() if ch and lt in LOG_TYPES}
    inactive   = [lt for lt in LOG_TYPES if lt not in active]

    embed = discord.Embed(
        title="📡 Feed-Channel Übersicht",
        description=(
            f"**{len(active)}** Feed{'s' if len(active) != 1 else ''} aktiv  •  "
            f"**{len(inactive)}** nicht konfiguriert"
        ),
        color=0x2ECC71 if active else 0x95A5A6,
    )

    # ── Aktive Feeds ──────────────────────────────────────────
    if active:
        lines = []
        for lt, ch_id in active.items():
            desc = LOG_TYPES.get(lt, lt)
            ch   = interaction.guild.get_channel(int(ch_id)) if interaction.guild else None
            ch_mention = ch.mention if ch else f"<#{ch_id}> *(Channel nicht gefunden)*"
            lines.append(f"{desc}\n╰ {ch_mention}")
        embed.add_field(
            name="✅ Aktive Feeds",
            value="\n\n".join(lines),
            inline=False,
        )

    # ── Inaktive Feeds ────────────────────────────────────────
    if inactive:
        lines = [f"❌ {LOG_TYPES[lt]}" for lt in inactive]
        embed.add_field(
            name="⚪ Nicht konfiguriert",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(text="Nutze /edit_feeds um einzelne Feeds zu ändern")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /edit_feeds – Einzelnen Feed-Channel ändern
#  Wähle den Feed-Typ per Autocomplete, dann den neuen Channel
# ══════════════════════════════════════════════════════════════
@bot.tree.command(
    name="edit_feeds",
    description="✏️ Feed-Channel ändern oder deaktivieren"
)
@app_commands.describe(
    feed="Welcher Feed soll geändert werden? (Tippe um zu filtern)",
    channel="Neuer Channel – leer lassen zum Deaktivieren"
)
async def cmd_edit_feeds(
    interaction: discord.Interaction,
    feed: str,
    channel: Optional[discord.TextChannel] = None,
):
    if not _is_admin(interaction):
        return await _deny(interaction)

    # Ungültigen Feed-Key abfangen (falls jemand manuell eingibt)
    if feed not in LOG_TYPES:
        choices = ", ".join(f"`{k}`" for k in LOG_TYPES)
        return await interaction.response.send_message(
            f"❌ Unbekannter Feed `{feed}`.\nGültige Feeds: {choices}",
            ephemeral=True,
        )

    desc = LOG_TYPES[feed]

    if channel is None:
        # Feed deaktivieren
        gid = str(interaction.guild_id)
        if gid in cfg.guilds and feed in cfg.guilds[gid]:
            del cfg.guilds[gid][feed]
            cfg.save_guilds()
        embed = discord.Embed(
            title="⚪ Feed deaktiviert",
            description=f"**{desc}**\nwird nicht mehr gepostet.",
            color=0x95A5A6,
        )
    else:
        # Feed auf neuen Channel setzen
        cfg.set_channel(interaction.guild_id, feed, channel.id)
        embed = discord.Embed(
            title="✅ Feed geändert",
            description=f"**{desc}**\n╰ {channel.mention}",
            color=0x2ECC71,
        )

    embed.set_footer(text="Nutze /show_feeds für eine Gesamtübersicht")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@cmd_edit_feeds.autocomplete("feed")
async def _feed_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Autocomplete: zeigt alle passenden Feed-Typen mit ihrem aktuellen Channel."""
    guild_cfg = cfg.guilds.get(str(interaction.guild_id), {})
    results   = []
    for lt, desc in LOG_TYPES.items():
        if current.lower() in lt.lower() or current.lower() in desc.lower() or not current:
            ch_id  = guild_cfg.get(lt)
            status = "✅" if ch_id else "❌"
            # Channel-Name im Label anzeigen wenn möglich
            ch_name = ""
            if ch_id and interaction.guild:
                ch = interaction.guild.get_channel(int(ch_id))
                ch_name = f" → #{ch.name}" if ch else f" → <#{ch_id}>"
            label = f"{status} {desc.strip()}{ch_name}"[:100]
            results.append(app_commands.Choice(name=label, value=lt))
    return results[:25]


# ══════════════════════════════════════════════════════════════
#  /neustart – Server Neustart
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="neustart", description="🔄 Startet den DayZ Server neu")
async def cmd_neustart(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction):
        return
    await interaction.response.defer()
    ok, msg = await bot.nitrado.restart()
    embed = discord.Embed(
        title="🔄 Server Neustart",
        description=msg,
        color=0x2ECC71 if ok else 0xE74C3C
    )
    embed.set_footer(text=f"Ausgeführt von {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /stoppen – Server stoppen
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="stoppen", description="⏹️ Stoppt den DayZ Server")
async def cmd_stoppen(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction):
        return
    await interaction.response.defer()
    ok, msg = await bot.nitrado.stop()
    embed = discord.Embed(
        title="⏹️ Server gestoppt",
        description=msg,
        color=0xF39C12 if ok else 0xE74C3C
    )
    embed.set_footer(text=f"Ausgeführt von {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /serverstatus – Status abrufen (Nitrado API + direkter A2S-Ping)
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="serverstatus", description="📊 Zeigt den aktuellen Server-Status")
async def cmd_status(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction):
        return
    await interaction.response.defer()

    # ── 1. Nitrado API (parallel zum A2S-Ping) ────────────────
    loop       = asyncio.get_running_loop()
    nitrado_task = loop.run_in_executor(None, lambda: None)   # Placeholder
    info = await bot.nitrado.get_info()

    # ── 2. Direkter A2S UDP-Ping ─────────────────────────────
    srv_ip    = cfg.config.get("server_ip",  "")
    qport     = int(cfg.config.get("query_port",  2302))
    rcon_port = int(cfg.config.get("rcon_port",   2310))

    a2s: Optional[Dict] = None
    a2s_ping_ms = -1
    if srv_ip:
        import time as _t
        t0 = _t.monotonic()
        a2s = await loop.run_in_executor(None, a2s_query, srv_ip, qport)
        a2s_ping_ms = int((_t.monotonic() - t0) * 1000)

    # ── 3. Status aus den Quellen zusammenbauen ───────────────
    # Nitrado-Daten
    n_status = ""
    n_players, n_max = "?", "?"
    n_game, n_ip, n_port = "DayZ", srv_ip or "–", "–"
    if info:
        n_status  = info.get("status", "")
        q         = info.get("query", {})
        n_players = str(q.get("player_current", "?"))
        n_max     = str(q.get("player_max", "?"))
        n_game    = info.get("game_human", "DayZ")
        n_ip      = info.get("ip", srv_ip or "–")
        n_port    = str(info.get("port", "–"))

    # Echtzeit-Daten bevorzugen wenn A2S antwortet
    if a2s:
        players_str = f"{a2s['players']}/{a2s['max_players']}"
        is_up       = True
        ping_str    = f"{a2s_ping_ms} ms"
        mapname     = a2s.get("map", "–")
        srv_name    = a2s.get("name", "–")
    else:
        players_str = f"{n_players}/{n_max}"
        is_up       = "started" in n_status.lower() or "running" in n_status.lower()
        ping_str    = "Timeout (offline?)" if srv_ip else "Keine IP konfiguriert"
        mapname     = "–"
        srv_name    = "–"

    color   = 0x2ECC71 if is_up else 0xE74C3C
    st_icon = "🟢" if is_up else "🔴"
    n_st    = n_status.upper() if n_status else ("ONLINE" if is_up else "OFFLINE")

    embed = discord.Embed(title="📊 Server Status", color=color)

    # Zeile 1: Status, Spieler, Ping
    embed.add_field(name="Status",    value=f"{st_icon} {n_st}",  inline=True)
    embed.add_field(name="Spieler",   value=players_str,           inline=True)
    embed.add_field(name="Ping",      value=ping_str,              inline=True)

    # Zeile 2: IP/Port, Query-Port, RCON-Port
    display_ip = n_ip if n_ip not in ("–", "") else (srv_ip or "–")
    embed.add_field(name="Server-IP", value=f"`{display_ip}`",           inline=True)
    embed.add_field(name="Game-Port / Query",
                    value=f"`{n_port}` / `{qport}`",                     inline=True)
    embed.add_field(name="RCON-Port", value=f"`{rcon_port}`",            inline=True)

    # Zeile 3: Map + Servername (nur wenn A2S geantwortet hat)
    if a2s:
        embed.add_field(name="Map",          value=mapname,  inline=True)
        embed.add_field(name="Servername",   value=srv_name[:50], inline=True)
        lock = "🔒 Passwort" if a2s.get("password") else "🔓 Offen"
        embed.add_field(name="Zugang",       value=lock,     inline=True)

    src = []
    if info:   src.append("Nitrado API")
    if a2s:    src.append("Direkter Ping (A2S)")
    embed.set_footer(text=f"Quellen: {', '.join(src) or '–'} | Service ID: {cfg.config.get('service_id','–')}")
    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /auto – Geplante automatische Server-Neustarts
# ══════════════════════════════════════════════════════════════
auto_group = app_commands.Group(name="auto", description="⏰ Automatische Server-Neustarts planen")


class AutoRestartView(discord.ui.View):
    """Uhrzeit-Auswahl für /auto restart: Stunde (0–23) + Minute (:00/:30).
    Zwei Dropdowns, weil Discord max. 25 Optionen pro Select erlaubt."""

    def __init__(self, interaction: discord.Interaction, interval_hours: int):
        super().__init__(timeout=180)
        self.author_id      = interaction.user.id
        self.interval_hours = interval_hours
        self.hour:   Optional[int] = None
        self.minute: Optional[int] = None

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.author_id:
            await itx.response.send_message(
                "❌ Nur wer den Befehl aufgerufen hat, kann hier auswählen.", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="🕐 Stunde der ersten Ausführung (0–23 Uhr)",
                       options=[discord.SelectOption(label=f"{h:02d} Uhr", value=str(h))
                                for h in range(24)])
    async def sel_hour(self, itx: discord.Interaction, select: discord.ui.Select):
        self.hour = int(select.values[0])
        await itx.response.defer()

    @discord.ui.select(placeholder="⏱️ Minute (:00 oder :30)",
                       options=[discord.SelectOption(label=":00", value="0"),
                                discord.SelectOption(label=":30", value="30")])
    async def sel_minute(self, itx: discord.Interaction, select: discord.ui.Select):
        self.minute = int(select.values[0])
        await itx.response.defer()

    @discord.ui.button(label="✅ Aktivieren", style=discord.ButtonStyle.success)
    async def confirm(self, itx: discord.Interaction, button: discord.ui.Button):
        if self.hour is None or self.minute is None:
            return await itx.response.send_message(
                "❌ Bitte zuerst Stunde und Minute auswählen.", ephemeral=True)
        first = f"{self.hour:02d}:{self.minute:02d}"
        cfg.config["auto_restart_schedule"] = {
            "enabled": True, "first_time": first, "interval_hours": self.interval_hours}
        cfg.save_config()
        bot._restart_announced.clear()
        nxt = bot._next_scheduled_restart()
        for child in self.children:
            child.disabled = True
        e = discord.Embed(
            title="⏰ Auto-Restart aktiviert",
            description=(f"Erste Ausführung: **{first} Uhr** · "
                         f"Intervall: **alle {self.interval_hours} Stunde(n)**\n"
                         f"Nächster Neustart: <t:{int(nxt)}:F> (<t:{int(nxt)}:R>)\n"
                         f"Ankündigungen **15/5/1 Min** vorher im `restart`-Feed-Channel "
                         f"(`/setup feeds restart`, Fallback: Adminlog)."),
            color=0x2ECC71)
        await itx.response.edit_message(embed=e, view=self)
        self.stop()


@auto_group.command(name="restart",
                    description="⏰ Plant automatische Neustarts (Startzeit per Dropdown + Intervall)")
@app_commands.describe(intervall="Abstand in Stunden, z.B. 2 = alle 2 Stunden (1–24)")
async def auto_restart(interaction: discord.Interaction,
                       intervall: app_commands.Range[int, 1, 24]):
    if not _is_admin(interaction):
        return await _deny(interaction)
    view = AutoRestartView(interaction, int(intervall))
    e = discord.Embed(
        title="⏰ Auto-Restart einrichten",
        description=(f"Intervall: **alle {int(intervall)} Stunde(n)**\n\n"
                     f"Wähle unten die Uhrzeit der **ersten Ausführung** "
                     f"(danach immer im gewählten Intervall) und bestätige."),
        color=0x5865F2)
    await interaction.response.send_message(embed=e, view=view, ephemeral=True)


@auto_group.command(name="off", description="⏹️ Deaktiviert die geplanten Neustarts")
async def auto_off(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    sched = dict(cfg.config.get("auto_restart_schedule") or {})
    was_on = bool(sched.get("enabled"))
    sched["enabled"] = False
    cfg.config["auto_restart_schedule"] = sched
    cfg.save_config()
    bot._restart_announced.clear()
    await interaction.response.send_message(
        "⏹️ Geplante Neustarts deaktiviert." if was_on
        else "ℹ️ Es waren keine geplanten Neustarts aktiv.", ephemeral=True)


@auto_group.command(name="status", description="📋 Zeigt den aktuellen Restart-Zeitplan")
async def auto_status(interaction: discord.Interaction):
    sched = cfg.config.get("auto_restart_schedule") or {}
    if not sched.get("enabled"):
        return await interaction.response.send_message(
            "ℹ️ Keine geplanten Neustarts aktiv. Einrichten: `/auto restart`.", ephemeral=True)
    nxt = bot._next_scheduled_restart()
    e = discord.Embed(
        title="⏰ Auto-Restart Zeitplan",
        description=(f"Startzeit: **{sched.get('first_time', '?')} Uhr** · "
                     f"Intervall: **alle {sched.get('interval_hours', '?')} Stunde(n)**\n"
                     f"Nächster Neustart: <t:{int(nxt)}:F> (<t:{int(nxt)}:R>)"),
        color=0x5865F2)
    await interaction.response.send_message(embed=e, ephemeral=True)


bot.tree.add_command(auto_group)


# ══════════════════════════════════════════════════════════════
#  /zone – Überwachte Zonen: wiederholter Ping (alle 5 Min),
#  solange ein Spieler in der Zone steht (außer Allowlist)
#  (Positionen kommen aus den ADM-Logs, Prüfung in _check_zones)
# ══════════════════════════════════════════════════════════════
zone_group = app_commands.Group(name="zone",
                                description="🛡️ Zonen-Pings verwalten (Admin)")

def _zones() -> List[Dict]:
    zs = cfg.config.get("zones")
    if not isinstance(zs, list):
        zs = []
        cfg.config["zones"] = zs
    return zs

def _find_zone(name: str) -> Optional[Dict]:
    key = name.strip().lower()
    for z in _zones():
        if isinstance(z, dict) and str(z.get("name", "")).strip().lower() == key:
            return z
    return None

def _zone_allowlist(zone: Dict) -> List[str]:
    """Liefert die Ignorier-Liste einer Zone (legt sie bei Bedarf an)."""
    al = zone.get("allowlist")
    if not isinstance(al, list):
        al = []
        zone["allowlist"] = al
    return al

def _player_in_allowlist(zone: Dict, pname: str) -> bool:
    """True, wenn der Spieler in dieser Zone ignoriert werden soll (case-insensitiv)."""
    key = (pname or "").strip().lower()
    return any(str(n).strip().lower() == key for n in _zone_allowlist(zone))

def _reset_zone_state(zone_name: str):
    """Ping-Cooldowns einer Zone verwerfen (nach remove/edit),
    damit die nächste frische Position sauber neu bewertet wird."""
    zk = zone_name.strip().lower()
    bot._zone_last_ping = {k: v for k, v in bot._zone_last_ping.items() if k[0] != zk}

def _zone_summary(z: Dict) -> str:
    role = f" · Ping: <@&{int(z['role_id'])}>" if z.get("role_id") else ""
    chan = f" · Channel: <#{int(z['channel_id'])}>" if z.get("channel_id") else ""
    return (f"Zentrum `{z.get('x')}, {z.get('z')}` (x=Ost, z=Nord) · "
            f"Radius **{z.get('radius')} m**{role}{chan}")

async def _zone_name_autocomplete(interaction: discord.Interaction, current: str):
    cur = (current or "").lower()
    return [app_commands.Choice(name=str(z["name"]), value=str(z["name"]))
            for z in _zones()
            if isinstance(z, dict) and z.get("name") and cur in str(z["name"]).lower()][:25]

def _validate_zone_geometry(x: float, z: float, radius: float) -> Optional[str]:
    """Gibt eine Fehlermeldung zurück oder None, wenn alles ok ist."""
    if not (0.0 <= x <= 20000.0 and 0.0 <= z <= 20000.0):
        return ("❌ Koordinaten außerhalb der Map. Gib die beiden iZurvive-Zahlen "
                "als `x` (Ost) und `z` (Nord) an, z. B. `x: 4522` `z: 9638`.")
    if not (10.0 <= radius <= 10000.0):
        return "❌ Radius muss zwischen **10** und **10000** Metern liegen."
    return None


@zone_group.command(name="create",
                    description="🛡️ Zone anlegen – pingt alle 5 Min, solange ein Spieler darin steht (Admin)")
@app_commands.describe(
    x="X-Koordinate des Zentrums (iZurvive, Ost)",
    z="Z-Koordinate des Zentrums (iZurvive, Nord)",
    name="Name der Zone (frei wählbar, einmalig)",
    radius="Radius in Metern, in dem der Bot nach Spielern schaut",
    channel="Optional: Channel, in den die Warnungen dieser Zone gepostet werden",
    rolle="Optional: Rolle, die beim Ping mit @ markiert wird")
async def zone_create(interaction: discord.Interaction, x: float, z: float,
                      name: str, radius: float,
                      channel: Optional[discord.TextChannel] = None,
                      rolle: Optional[discord.Role] = None):
    if not _is_admin(interaction):
        return await _deny(interaction)
    name = name.strip()
    if not name or len(name) > 60:
        return await interaction.response.send_message(
            "❌ Zonen-Name fehlt oder ist länger als 60 Zeichen.", ephemeral=True)
    if _find_zone(name):
        return await interaction.response.send_message(
            f"❌ Zone **{name}** existiert bereits – `/zone edit` zum Ändern "
            f"oder `/zone remove` zum Löschen.", ephemeral=True)
    err = _validate_zone_geometry(x, z, radius)
    if err:
        return await interaction.response.send_message(err, ephemeral=True)
    zone = {
        "name":       name,
        "x":          round(float(x), 1),
        "z":          round(float(z), 1),
        "radius":     round(float(radius), 1),
        "role_id":    int(rolle.id) if rolle else None,
        "channel_id": int(channel.id) if channel else None,
        "guild_id":   int(interaction.guild_id),
    }
    _zones().append(zone)
    cfg.save_config()
    e = discord.Embed(title="🛡️ Zone angelegt",
                      description=f"**{name}**\n{_zone_summary(zone)}",
                      color=0x2ECC71)
    if not channel and not cfg.get_channel(interaction.guild_id, "zone"):
        e.add_field(name="ℹ️ Hinweis",
                    value="Kein Channel gesetzt – Pings gehen in den **adminlog**. "
                          "Gib bei `/zone create` das Feld `channel` an oder setze mit "
                          "`/setup feeds` den Feed **zone**.",
                    inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


@zone_group.command(name="remove",
                    description="🗑️ Zone entfernen – dort wird nicht mehr gesucht (Admin)")
@app_commands.describe(name="Name der Zone (Autocomplete)")
async def zone_remove(interaction: discord.Interaction, name: str):
    if not _is_admin(interaction):
        return await _deny(interaction)
    zone = _find_zone(name)
    if not zone:
        return await interaction.response.send_message(
            f"❌ Keine Zone namens **{name.strip()}** gefunden – `/zone list` zeigt alle.",
            ephemeral=True)
    _zones().remove(zone)
    cfg.save_config()
    _reset_zone_state(str(zone["name"]))
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🗑️ Zone entfernt",
            description=f"**{zone['name']}** wird nicht mehr überwacht.\n{_zone_summary(zone)}",
            color=0xE74C3C),
        ephemeral=True)

zone_remove.autocomplete("name")(_zone_name_autocomplete)


@zone_group.command(name="list", description="📋 Alle aktiven Zonen anzeigen (Admin)")
async def zone_list(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    zones = [z for z in _zones() if isinstance(z, dict) and z.get("name")]
    if not zones:
        return await interaction.response.send_message(
            "ℹ️ Keine Zonen angelegt. Mit `/zone create` eine Zone einrichten.",
            ephemeral=True)
    e = discord.Embed(title=f"🛡️ Aktive Zonen ({len(zones)})", color=0x3498DB)
    for z in zones[:25]:
        e.add_field(name=f"📍 {z['name']}", value=_zone_summary(z), inline=False)
    if len(zones) > 25:
        e.set_footer(text=f"… und {len(zones) - 25} weitere (Embed-Limit)")
    await interaction.response.send_message(embed=e, ephemeral=True)


@zone_group.command(name="edit",
                    description="✏️ Zone bearbeiten – nur die angegebenen Felder werden geändert (Admin)")
@app_commands.describe(
    name="Name der Zone, die bearbeitet werden soll (Autocomplete)",
    neuer_name="Optional: neuer Name der Zone",
    x="Optional: neue X-Koordinate (iZurvive, Ost)",
    z="Optional: neue Z-Koordinate (iZurvive, Nord)",
    radius="Optional: neuer Radius in Metern",
    channel="Optional: neuer Channel für die Warnungen dieser Zone",
    channel_entfernen="True = eigenen Zonen-Channel entfernen (Fallback: Feed zone/adminlog)",
    rolle="Optional: neue Rolle für den Ping",
    rolle_entfernen="True = Rollen-Ping ausschalten")
async def zone_edit(interaction: discord.Interaction, name: str,
                    neuer_name: Optional[str] = None,
                    x: Optional[float] = None, z: Optional[float] = None,
                    radius: Optional[float] = None,
                    channel: Optional[discord.TextChannel] = None,
                    channel_entfernen: bool = False,
                    rolle: Optional[discord.Role] = None,
                    rolle_entfernen: bool = False):
    if not _is_admin(interaction):
        return await _deny(interaction)
    zone = _find_zone(name)
    if not zone:
        return await interaction.response.send_message(
            f"❌ Keine Zone namens **{name.strip()}** gefunden – `/zone list` zeigt alle.",
            ephemeral=True)
    if (neuer_name is None and x is None and z is None and radius is None
            and rolle is None and not rolle_entfernen
            and channel is None and not channel_entfernen):
        return await interaction.response.send_message(
            "❌ Nichts zu ändern – mindestens ein Feld angeben "
            "(`neuer_name`, `x`, `z`, `radius`, `channel`, `channel_entfernen`, "
            "`rolle`, `rolle_entfernen`).",
            ephemeral=True)
    new_x = float(x)      if x      is not None else float(zone.get("x", 0.0))
    new_z = float(z)      if z      is not None else float(zone.get("z", 0.0))
    new_r = float(radius) if radius is not None else float(zone.get("radius", 0.0))
    err = _validate_zone_geometry(new_x, new_z, new_r)
    if err:
        return await interaction.response.send_message(err, ephemeral=True)
    if neuer_name is not None:
        neuer_name = neuer_name.strip()
        if not neuer_name or len(neuer_name) > 60:
            return await interaction.response.send_message(
                "❌ Neuer Name fehlt oder ist länger als 60 Zeichen.", ephemeral=True)
        existing = _find_zone(neuer_name)
        if existing is not None and existing is not zone:
            return await interaction.response.send_message(
                f"❌ Es gibt bereits eine Zone namens **{neuer_name}**.", ephemeral=True)
    old_name = str(zone["name"])
    if neuer_name is not None:
        zone["name"] = neuer_name
    zone["x"], zone["z"], zone["radius"] = round(new_x, 1), round(new_z, 1), round(new_r, 1)
    if rolle_entfernen:
        zone["role_id"] = None
    elif rolle is not None:
        zone["role_id"] = int(rolle.id)
    if channel_entfernen:
        zone["channel_id"] = None
    elif channel is not None:
        zone["channel_id"] = int(channel.id)
    cfg.save_config()
    # Alten UND neuen Zustand verwerfen: Geometrie/Name haben sich evtl. geändert,
    # die nächste frische Position bewertet die Zone komplett neu
    _reset_zone_state(old_name)
    _reset_zone_state(str(zone["name"]))
    await interaction.response.send_message(
        embed=discord.Embed(
            title="✏️ Zone aktualisiert",
            description=f"**{zone['name']}**\n{_zone_summary(zone)}",
            color=0x2ECC71),
        ephemeral=True)

zone_edit.autocomplete("name")(_zone_name_autocomplete)


# ── /zone allowlist – Spieler in einer Zone ignorieren (Admin) ──
allowlist_group = app_commands.Group(
    name="allowlist",
    description="🙈 Spieler in einer Zone ignorieren (Admin)",
    parent=zone_group)


@allowlist_group.command(
    name="add",
    description="🙈 Spieler zur Ignorier-Liste einer Zone hinzufügen (Admin)")
@app_commands.describe(
    zone="Name der Zone (Autocomplete)",
    spieler="PlayStation-/Ingame-Name, der nicht mehr gemeldet werden soll")
async def zone_allowlist_add(interaction: discord.Interaction, zone: str, spieler: str):
    if not _is_admin(interaction):
        return await _deny(interaction)
    z = _find_zone(zone)
    if not z:
        return await interaction.response.send_message(
            f"❌ Keine Zone namens **{zone.strip()}** gefunden – `/zone list` zeigt alle.",
            ephemeral=True)
    spieler = spieler.strip()
    if not spieler:
        return await interaction.response.send_message(
            "❌ Kein Spielername angegeben.", ephemeral=True)
    if _player_in_allowlist(z, spieler):
        return await interaction.response.send_message(
            f"ℹ️ **{spieler}** steht bereits auf der Ignorier-Liste von **{z['name']}**.",
            ephemeral=True)
    _zone_allowlist(z).append(spieler)
    cfg.save_config()
    await interaction.response.send_message(
        f"🙈 **{spieler}** wird in Zone **{z['name']}** ab sofort **nicht** mehr gemeldet.",
        ephemeral=True)

zone_allowlist_add.autocomplete("zone")(_zone_name_autocomplete)


@allowlist_group.command(
    name="remove",
    description="🔔 Spieler wieder melden – von der Ignorier-Liste entfernen (Admin)")
@app_commands.describe(
    zone="Name der Zone (Autocomplete)",
    spieler="Name, der wieder gemeldet werden soll")
async def zone_allowlist_remove(interaction: discord.Interaction, zone: str, spieler: str):
    if not _is_admin(interaction):
        return await _deny(interaction)
    z = _find_zone(zone)
    if not z:
        return await interaction.response.send_message(
            f"❌ Keine Zone namens **{zone.strip()}** gefunden – `/zone list` zeigt alle.",
            ephemeral=True)
    key = spieler.strip().lower()
    al = _zone_allowlist(z)
    matches = [n for n in al if str(n).strip().lower() == key]
    if not matches:
        return await interaction.response.send_message(
            f"ℹ️ **{spieler.strip()}** steht nicht auf der Ignorier-Liste von **{z['name']}**.",
            ephemeral=True)
    z["allowlist"] = [n for n in al if str(n).strip().lower() != key]
    cfg.save_config()
    await interaction.response.send_message(
        f"🔔 **{matches[0]}** wird in Zone **{z['name']}** wieder gemeldet.",
        ephemeral=True)

zone_allowlist_remove.autocomplete("zone")(_zone_name_autocomplete)


@allowlist_group.command(
    name="show",
    description="📋 Ignorierte Spieler einer Zone anzeigen (Admin)")
@app_commands.describe(zone="Name der Zone (Autocomplete)")
async def zone_allowlist_show(interaction: discord.Interaction, zone: str):
    if not _is_admin(interaction):
        return await _deny(interaction)
    z = _find_zone(zone)
    if not z:
        return await interaction.response.send_message(
            f"❌ Keine Zone namens **{zone.strip()}** gefunden – `/zone list` zeigt alle.",
            ephemeral=True)
    al = _zone_allowlist(z)
    if not al:
        return await interaction.response.send_message(
            f"ℹ️ Für Zone **{z['name']}** werden aktuell keine Spieler ignoriert.",
            ephemeral=True)
    listing = "\n".join(f"• {n}" for n in al[:50])
    if len(al) > 50:
        listing += f"\n… und {len(al) - 50} weitere"
    e = discord.Embed(
        title=f"🙈 Ignorierte Spieler – {z['name']} ({len(al)})",
        description=listing,
        color=0x95A5A6)
    await interaction.response.send_message(embed=e, ephemeral=True)

zone_allowlist_show.autocomplete("zone")(_zone_name_autocomplete)


bot.tree.add_command(zone_group)


# ══════════════════════════════════════════════════════════════
#  Ban-Hilfsfunktionen (Banliste in den Nitrado-Servereinstellungen –
#  dasselbe Settings-Feld wie im Webinterface, 1 Name pro Zeile)
# ══════════════════════════════════════════════════════════════
def _find_ban_setting(settings: Dict) -> Tuple[str, str, str]:
    """Sucht das Banlisten-Setting in den Nitrado-Settings.
    Reihenfolge: Config-Override (nitrado_ban_category/nitrado_ban_key) →
    Auto-Erkennung (Key 'bans', Kategorie egal) → Fallback ('general', 'bans').
    Gibt (category, key, aktueller_wert) zurück."""
    ov_cat = str(cfg.config.get("nitrado_ban_category") or "").strip()
    ov_key = str(cfg.config.get("nitrado_ban_key") or "").strip()
    if ov_cat and ov_key:
        val = ((settings.get(ov_cat) or {}).get(ov_key)
               if isinstance(settings.get(ov_cat), dict) else None)
        return ov_cat, ov_key, str(val or "")
    for category, keys in settings.items():
        if not isinstance(keys, dict):
            continue
        for key, val in keys.items():
            if str(key).lower() == "bans":
                return str(category), str(key), str(val or "")
    return "general", "bans", ""

async def _read_banlist() -> Tuple[List[str], str, str]:
    """Liest die Banliste aus den Nitrado-Servereinstellungen.
    Gibt (namen, category, key) zurück. Wirft RuntimeError bei API-Fehler –
    Aufrufer dürfen dann NICHT schreiben (sonst würde die Liste überschrieben)."""
    settings = await bot.nitrado.get_settings()
    if settings is None:
        raise RuntimeError("Nitrado-API nicht erreichbar (Settings konnten nicht gelesen werden)")
    category, key, raw = _find_ban_setting(settings)
    names = [l.strip() for l in raw.splitlines() if l.strip()]
    return names, category, key

async def _write_banlist(names: List[str], category: str, key: str) -> Tuple[bool, str]:
    """Schreibt die Banliste in die Nitrado-Servereinstellungen (1 Name pro Zeile)."""
    return await bot.nitrado.set_setting(category, key, "\r\n".join(names))

def _split_names(raw: str) -> List[str]:
    """Zerlegt die Eingabe in einzelne Namen (Komma-getrennt), Duplikate raus."""
    out: List[str] = []
    seen: set = set()
    for part in raw.split(","):
        name = part.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


# ══════════════════════════════════════════════════════════════
#  /ban – Spieler bannen
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ban",
                  description="🔨 Fügt Spieler zur Banliste in den Nitrado-Servereinstellungen hinzu")
@app_commands.describe(
    spieler="Name(n) – mehrere per Komma getrennt",
    grund="Grund für den Ban (optional)"
)
async def cmd_ban(interaction: discord.Interaction, spieler: str, grund: str = "Kein Grund angegeben"):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction):
        return
    await interaction.response.defer()

    names = _split_names(spieler)
    if not names:
        return await interaction.followup.send("❌ Keinen gültigen Namen angegeben.")

    # Erst lesen – bei API-Fehler NICHT schreiben, sonst würde die
    # bestehende Nitrado-Banliste überschrieben/geleert
    try:
        current, category, key = await _read_banlist()
    except Exception as e:
        return await interaction.followup.send(
            f"❌ Nitrado-Banliste konnte nicht gelesen werden – nichts geändert.\n`{e}`")

    existing_lower = {n.lower() for n in current}
    added   = [n for n in names if n.lower() not in existing_lower]
    already = [n for n in names if n.lower() in existing_lower]

    sv = "ℹ️ Alle Namen standen bereits auf der Banliste"
    if added:
        ok, msg = await _write_banlist(current + added, category, key)
        if not ok:
            return await interaction.followup.send(
                f"❌ Nitrado-Banliste konnte nicht gespeichert werden – nichts geändert.\n`{msg}`")
        sv = "✅ In der Nitrado-Banliste gespeichert"

    # Lokale Metadaten (nur für die Anzeige in /banlist)
    now = datetime.now(timezone.utc).isoformat()
    for n in added:
        cfg.bans[n] = {"name": n, "reason": grund,
                       "banned_by": str(interaction.user), "banned_at": now}
    if added:
        cfg.save_bans()

    embed = discord.Embed(title="🔨 Spieler gebannt", color=0xE74C3C)
    embed.add_field(name="Hinzugefügt",
                    value="\n".join(f"`{n}`" for n in added) or "–", inline=True)
    if already:
        embed.add_field(name="Bereits gebannt",
                        value="\n".join(f"`{n}`" for n in already), inline=True)
    embed.add_field(name="Grund",       value=grund,                 inline=True)
    embed.add_field(name="Gebannt von", value=str(interaction.user), inline=True)
    embed.add_field(name="Nitrado",     value=sv,                    inline=False)
    embed.set_footer(text="Änderung greift ggf. erst nach einem Server-Neustart.")
    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /ban_entfernen – Ban aufheben
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ban_entfernen",
                  description="✅ Entfernt Spieler von der Banliste in den Nitrado-Servereinstellungen")
@app_commands.describe(spieler="Name(n) – mehrere per Komma getrennt")
async def cmd_unban(interaction: discord.Interaction, spieler: str):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction):
        return
    await interaction.response.defer()

    names = _split_names(spieler)
    if not names:
        return await interaction.followup.send("❌ Keinen gültigen Namen angegeben.")

    try:
        current, category, key = await _read_banlist()
    except Exception as e:
        return await interaction.followup.send(
            f"❌ Nitrado-Banliste konnte nicht gelesen werden – nichts geändert.\n`{e}`")

    wanted_lower = {n.lower() for n in names}
    new_list  = [n for n in current if n.lower() not in wanted_lower]
    removed   = [n for n in current if n.lower() in wanted_lower]
    not_found = [n for n in names if n.lower() not in {r.lower() for r in removed}]

    sv = "ℹ️ Keiner der Namen stand auf der Banliste"
    if removed:
        ok, msg = await _write_banlist(new_list, category, key)
        if not ok:
            return await interaction.followup.send(
                f"❌ Nitrado-Banliste konnte nicht gespeichert werden – nichts geändert.\n`{msg}`")
        sv = "✅ Von der Nitrado-Banliste entfernt"
        # Lokale Metadaten aufräumen (case-insensitive)
        for local_key in [k for k in cfg.bans if k.lower() in wanted_lower]:
            cfg.bans.pop(local_key, None)
        cfg.save_bans()

    embed = discord.Embed(title="✅ Ban aufgehoben", color=0x2ECC71)
    embed.add_field(name="Entfernt",
                    value="\n".join(f"`{n}`" for n in removed) or "–", inline=True)
    if not_found:
        embed.add_field(name="Nicht auf der Liste",
                        value="\n".join(f"`{n}`" for n in not_found), inline=True)
    embed.add_field(name="Nitrado", value=sv, inline=False)
    embed.set_footer(text="Änderung greift ggf. erst nach einem Server-Neustart.")
    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /banlist – Alle gesperrten Spieler
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="banlist",
                  description="📋 Zeigt die Banliste aus den Nitrado-Servereinstellungen")
async def cmd_banlist(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction):
        return
    await interaction.response.defer(ephemeral=True)

    try:
        all_bans, _category, _key = await _read_banlist()
    except Exception as e:
        return await interaction.followup.send(
            f"❌ Nitrado-Banliste konnte nicht gelesen werden.\n`{e}`", ephemeral=True)

    if not all_bans:
        return await interaction.followup.send("✅ Keine gesperrten Spieler.", ephemeral=True)

    embed = discord.Embed(
        title=f"🚫 Banliste – {len(all_bans)} Spieler gesperrt",
        color=0xE74C3C
    )
    # Metadaten (Grund/Datum/von) kommen aus der lokalen banlist.json, falls
    # der Ban über /ban gesetzt wurde – Einträge direkt aus dem Nitrado-
    # Webinterface haben keine Metadaten (case-insensitives Matching)
    local = {k.lower(): v for k, v in cfg.bans.items()}
    lines = []
    for entry in sorted(all_bans, key=str.lower):
        info = local.get(entry.lower())
        if info:
            grund = info.get("reason", "–")
            datum = (info.get("banned_at", "")[:10]) if info.get("banned_at") else "–"
            von   = info.get("banned_by", "–")
            lines.append(f"• `{entry}` — {grund} | {datum} | von {von}")
        else:
            lines.append(f"• `{entry}`")

    # Aufteilen bei > 1000 Zeichen
    chunks, chunk = [], []
    for line in lines:
        if len("\n".join(chunk + [line])) > 1000:
            chunks.append("\n".join(chunk))
            chunk = [line]
        else:
            chunk.append(line)
    if chunk:
        chunks.append("\n".join(chunk))

    for i, c in enumerate(chunks[:25]):
        embed.add_field(name=f"Spieler {i+1}" if len(chunks) > 1 else "Spieler",
                        value=c, inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /admin_position – Letzte bekannte Spieler-Positionen
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="admin_position",
                  description="📍 Letzte bekannte Positionen aller Spieler aus den Logs")
async def cmd_positions(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)

    positions = DayZLogParser.player_positions
    if not positions:
        return await interaction.response.send_message(
            "⚠️ Noch keine Positions-Daten verfügbar.\n"
            "Positionen werden aus Kill/Death-Events automatisch gesammelt. "
            "Warte bis der erste Log-Zyklus gelaufen ist.",
            ephemeral=True
        )

    embed = discord.Embed(
        title=f"📍 Spieler-Positionen ({len(positions)} bekannt)",
        description="Letzte bekannte Koordinaten aus Server-Logs (nicht live)",
        color=0x3498DB
    )

    lines = []
    for name, data in sorted(positions.items()):
        ts = data.get("last_seen", "")
        ts_fmt = ts[:16].replace("T", " ") if ts else "?"
        lines.append(f"**{name}** → `{data['position']}` *(zuletzt: {ts_fmt} UTC)*")

    chunk, fc = [], 0
    for line in lines:
        if len("\n".join(chunk + [line])) > 1000:
            embed.add_field(name="Spieler", value="\n".join(chunk), inline=False)
            chunk = [line]
            fc += 1
            if fc >= 24:
                chunk.append(f"... und {len(lines)-fc*10} weitere")
                break
        else:
            chunk.append(line)
    if chunk:
        embed.add_field(name="Spieler", value="\n".join(chunk), inline=False)

    embed.set_footer(text="⚠️ Positionen stammen aus Log-Events – nicht live in Echtzeit")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /spieler_suche – Spieler in Logs suchen
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="spieler_suche", description="🔍 Sucht einen Spieler in den aktuellen Logs")
@app_commands.describe(name="Ingame-Name oder Steam64-ID")
async def cmd_search(interaction: discord.Interaction, name: str):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction, need_ftp=True):
        return
    await interaction.response.defer(ephemeral=True)

    log_dir = cfg.config.get("ftp_log_dir")
    if not log_dir:
        return await interaction.followup.send(
            "❌ Log-Verzeichnis nicht konfiguriert. Starte den Bot neu oder nutze `/ftp_scan`.",
            ephemeral=True
        )

    loop = asyncio.get_running_loop()
    adm_files = await loop.run_in_executor(None, bot.ftp.list_adm_files, log_dir)
    if not adm_files:
        return await interaction.followup.send("❌ Keine Log-Dateien gefunden.", ephemeral=True)

    content = await loop.run_in_executor(None, bot.ftp.read_file, adm_files[-1])
    if not content:
        return await interaction.followup.send("❌ Log-Datei konnte nicht gelesen werden.", ephemeral=True)

    hits = [l.strip() for l in content.splitlines() if name.lower() in l.lower()][:25]
    if not hits:
        return await interaction.followup.send(f"❌ Keine Einträge für **{name}** gefunden.", ephemeral=True)

    result = "\n".join(f"`{h[:120]}`" for h in hits)
    if len(result) > 3900:
        result = result[:3900] + "\n..."

    embed = discord.Embed(title=f"🔍 Suche: {name}", description=result, color=0x5865F2)
    embed.set_footer(text=f"Datei: {adm_files[-1]} | {len(hits)} Treffer (max. 25)")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /ftp_scan – FTP-Verzeichnisse neu scannen
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ftp_scan", description="🔎 Scannt FTP-Server erneut nach Log-Verzeichnissen")
async def cmd_ftp_scan(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction, need_ftp=True):
        return
    await interaction.response.defer(ephemeral=True)

    # Pfade zurücksetzen damit discover_paths nicht überspringt
    cfg.config["ftp_log_dir"]          = ""
    cfg.config["ftp_ban_file"]         = ""
    cfg.config["ftp_mission_dir"]      = ""
    cfg.config["cfg_effect_area_path"] = ""
    cfg.log_state = {}
    cfg.save_config()
    cfg.save_log_state()

    await bot._auto_discover()

    log_dir  = cfg.config.get("ftp_log_dir")          or "Nicht gefunden"
    ban_file = cfg.config.get("ftp_ban_file")         or "Nicht gefunden"
    mission  = cfg.config.get("ftp_mission_dir")      or "Nicht gefunden"
    effect   = cfg.config.get("cfg_effect_area_path") or "Nicht gefunden"

    embed = discord.Embed(title="🔎 FTP-Scan abgeschlossen", color=0x2ECC71)
    embed.add_field(name="Log-Verzeichnis", value=f"`{log_dir}`",  inline=False)
    embed.add_field(name="Ban-Datei",       value=f"`{ban_file}`", inline=False)
    embed.add_field(name="Mission-Ordner",  value=f"`{mission}`",  inline=False)
    embed.add_field(name="cfgEffectArea",   value=f"`{effect}`",   inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /raw_log – Letzte N Zeilen des ADM-Logs anzeigen (Debug)
#  Hilft herauszufinden warum manche Events (damage, loot)
#  nicht gepostet werden – zeigt das exakte Log-Format.
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="raw_log", description="🔍 Zeigt die letzten Zeilen des ADM-Logs (Debug)")
@app_commands.describe(zeilen="Anzahl der Zeilen (Standard: 20, max. 40)")
async def cmd_raw_log(interaction: discord.Interaction, zeilen: int = 20):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction, need_ftp=True):
        return
    await interaction.response.defer(ephemeral=True)

    log_dir = cfg.config.get("ftp_log_dir")
    if not log_dir:
        return await interaction.followup.send(
            "❌ Log-Verzeichnis nicht konfiguriert. Nutze `/ftp_scan`.", ephemeral=True
        )

    loop = asyncio.get_running_loop()
    adm_files = await loop.run_in_executor(None, bot.ftp.list_adm_files, log_dir)
    if not adm_files:
        return await interaction.followup.send("❌ Keine ADM-Dateien gefunden.", ephemeral=True)

    content = await loop.run_in_executor(None, bot.ftp.read_file, adm_files[-1])
    if not content:
        return await interaction.followup.send("❌ Log-Datei konnte nicht gelesen werden.", ephemeral=True)

    zeilen = max(5, min(zeilen, 40))
    lines  = [l for l in content.splitlines() if l.strip()][-zeilen:]
    result = "\n".join(f"`{l[:110]}`" for l in lines)
    if len(result) > 3900:
        result = result[:3900] + "\n..."

    embed = discord.Embed(
        title=f"🔍 Raw Log – letzte {len(lines)} Zeilen",
        description=result,
        color=0x7F8C8D
    )
    embed.set_footer(text=f"Datei: {adm_files[-1].split('/')[-1]}  •  "
                         f"Tipp: Damage/Loot erscheinen nur wenn der Server diese Events loggt")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /test – Letztes Log-Event pro Typ in die jeweiligen Channels
# ══════════════════════════════════════════════════════════════
@bot.tree.command(
    name="test",
    description="🧪 Postet das letzte Log-Event jedes Typs in die jeweiligen Channels"
)
@app_commands.describe(zeilen="Zu durchsuchende Log-Zeilen (Standard: 500, max: 2000)")
async def cmd_test(interaction: discord.Interaction, zeilen: int = 500):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_nitrado(interaction, need_ftp=True):
        return
    await interaction.response.defer(ephemeral=True)

    # ── 1. Log-Datei lesen ────────────────────────────────────
    log_dir = cfg.config.get("ftp_log_dir")
    if not log_dir:
        return await interaction.followup.send(
            "❌ Log-Verzeichnis nicht konfiguriert. Nutze `/ftp_scan`.", ephemeral=True
        )

    loop = asyncio.get_running_loop()
    adm_files = await loop.run_in_executor(None, bot.ftp.list_adm_files, log_dir)
    if not adm_files:
        return await interaction.followup.send("❌ Keine ADM-Dateien gefunden.", ephemeral=True)

    content = await loop.run_in_executor(None, bot.ftp.read_file, adm_files[-1])
    if not content:
        return await interaction.followup.send("❌ Log-Datei konnte nicht gelesen werden.", ephemeral=True)

    # ── 2. Letzten N Zeilen parsen ────────────────────────────
    zeilen = max(50, min(zeilen, 2000))
    recent_lines = "\n".join(content.splitlines()[-zeilen:])
    events = bot.parser.parse_lines(recent_lines)

    # ── 3. Pro Log-Typ das neueste Event merken ───────────────
    # Events kommen in Lesereihenfolge → letztes überschreibt → neuestes bleibt
    latest_by_logtype: Dict[str, Dict] = {}
    for ev in events:
        lt = DayZLogParser.EVENT_TO_LOG.get(ev["type"])
        if lt:
            latest_by_logtype[lt] = ev

    # ── 4. Pro Log-Typ in konfigurierten Channel posten ───────
    guild_cfg = cfg.guilds.get(str(interaction.guild_id), {})

    sent:     List[Tuple[str, str]] = []  # (log_type, channel_mention)
    no_event: List[str]             = []  # Log-Typ ohne Event im gescannten Bereich
    no_ch:    List[str]             = []  # Log-Typ mit Event aber ohne Channel
    errors:   List[Tuple[str, str]] = []  # (log_type, Fehlermeldung)

    for lt in LOG_TYPES:
        ev    = latest_by_logtype.get(lt)
        ch_id = guild_cfg.get(lt)

        if not ev:
            no_event.append(lt)
            continue
        if not ch_id:
            no_ch.append(lt)
            continue

        ch = bot.get_channel(int(ch_id))
        if not ch:
            errors.append((lt, "Channel nicht gefunden (ID veraltet?)"))
            continue

        embed = EmbedBuilder.build(ev)
        if not embed:
            errors.append((lt, "Embed konnte nicht erstellt werden"))
            continue

        # Test-Kennung in den Embed-Titel & Author einbauen
        embed.title = f"🧪 [TEST] {embed.title or lt}"
        embed.set_author(
            name=f"Testpost via /test · {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
        )

        try:
            await ch.send(embed=embed)
            sent.append((lt, ch.mention))
        except discord.Forbidden:
            errors.append((lt, f"Keine Schreibrechte in {ch.mention}"))
        except Exception as ex:
            errors.append((lt, str(ex)[:80]))

    # ── 5. Ergebnis-Embed senden ──────────────────────────────
    ok_count = len(sent)
    color = 0x2ECC71 if ok_count > 0 else 0xE74C3C

    summary = discord.Embed(
        title="🧪 Test-Ergebnis",
        description=(
            f"Gescannt: letzte **{zeilen}** Zeilen aus `{adm_files[-1].split('/')[-1]}`\n"
            f"Events gefunden: **{len(events)}** · Gepostet: **{ok_count}**"
        ),
        color=color,
    )

    if sent:
        lines = [f"✅ `{lt}` → {ch}" for lt, ch in sent]
        summary.add_field(
            name=f"✅ Erfolgreich gepostet ({len(sent)})",
            value="\n".join(lines),
            inline=False
        )
    if no_ch:
        lines = [f"⚪ `{lt}`" for lt in no_ch]
        summary.add_field(
            name=f"⚪ Kein Channel konfiguriert ({len(no_ch)})",
            value="  ".join(lines),
            inline=False
        )
    if no_event:
        lines = [f"🔍 `{lt}`" for lt in no_event]
        summary.add_field(
            name=f"🔍 Kein Event in den letzten {zeilen} Zeilen ({len(no_event)})",
            value="  ".join(lines),
            inline=False
        )
    if errors:
        lines = [f"❌ `{lt}` — {msg}" for lt, msg in errors]
        summary.add_field(
            name=f"❌ Fehler ({len(errors)})",
            value="\n".join(lines),
            inline=False
        )

    summary.set_footer(
        text="🔍-Typen = diese Events kommen in deinen Logs nicht vor "
             "(z.B. Damage/Loot brauchen Server-Mods). "
             "⚪-Typen → /setup feeds <typ> #channel"
    )
    await interaction.followup.send(embed=summary, ephemeral=True)


@bot.tree.command(name="ftp_status", description="🔌 Testet die FTP-Verbindung zum Nitrado-Server")
async def cmd_ftp_status(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    await interaction.response.defer(ephemeral=True)

    host     = cfg.config.get("ftp_host", "–")
    port     = cfg.config.get("ftp_port", 21)
    user     = cfg.config.get("ftp_user", "–")
    log_dir  = cfg.config.get("ftp_log_dir",  "Noch nicht gesetzt")

    loop = asyncio.get_running_loop()

    # ── 1. Login-Test ─────────────────────────────────────────
    connect_ok  = False
    connect_msg = ""
    t_connect   = 0.0
    try:
        import ftplib, time as _time
        def _test_login():
            t0  = _time.monotonic()
            ftp = ftplib.FTP()
            ftp.connect(host, int(port), timeout=15)
            ftp.login(user, cfg.config.get("ftp_password", ""))
            welcome = ftp.getwelcome()
            ftp.quit()
            return _time.monotonic() - t0, welcome
        t_connect, welcome = await loop.run_in_executor(None, _test_login)
        connect_ok  = True
        connect_msg = welcome[:80] if welcome else "Verbindung erfolgreich"
    except Exception as e:
        connect_msg = str(e)[:120]

    # ── 2. Log-Verzeichnis lesen ──────────────────────────────
    adm_count  = 0
    adm_latest = "–"
    if connect_ok and log_dir and log_dir != "Noch nicht gesetzt":
        try:
            adm_files = await loop.run_in_executor(None, bot.ftp.list_adm_files, log_dir)
            adm_count  = len(adm_files)
            adm_latest = adm_files[-1].split("/")[-1] if adm_files else "Keine gefunden"
        except Exception as e:
            adm_latest = f"Fehler: {e}"

    # ── 3. Nitrado-Banliste prüfen (Servereinstellungen, nicht FTP) ──
    try:
        ban_names, _bcat, _bkey = await _read_banlist()
        ban_msg = f"✅ {len(ban_names)} Einträge"
    except Exception as e:
        ban_msg = f"⚠️ {e}"

    # ── Embed zusammenbauen ───────────────────────────────────
    if connect_ok:
        color = 0x2ECC71
        title = "🟢 FTP-Verbindung erfolgreich"
    else:
        color = 0xE74C3C
        title = "🔴 FTP-Verbindung fehlgeschlagen"

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Host",
                    value=f"`{host}:{port}`",                              inline=True)
    embed.add_field(name="Benutzer",
                    value=f"`{user}`",                                     inline=True)
    embed.add_field(name="Ping / Antwortzeit",
                    value=f"`{t_connect*1000:.0f} ms`" if connect_ok else "–", inline=True)
    embed.add_field(name="Server-Antwort",
                    value=f"`{connect_msg}`" if connect_ok else f"❌ `{connect_msg}`",
                    inline=False)
    embed.add_field(name="Log-Verzeichnis",
                    value=f"`{log_dir}`",                                  inline=False)
    embed.add_field(name="ADM-Dateien gefunden",
                    value=f"`{adm_count}`  •  Neueste: `{adm_latest}`",   inline=False)
    embed.add_field(name="Nitrado-Banliste (Servereinstellungen)",
                    value=ban_msg,                                         inline=False)

    if not connect_ok:
        embed.set_footer(text="Tipp: Prüfe Host, Port, Benutzername und Passwort in config.json")

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /log_status – Polling-Status anzeigen
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="log_status", description="📄 Zeigt den aktuellen Log-Polling Status")
async def cmd_log_status(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)

    state = cfg.log_state.get("current", {})
    embed = discord.Embed(title="📄 Log-Polling Status", color=0x5865F2)
    embed.add_field(name="Aktuelle Log-Datei",
                    value=f"`{state.get('file', 'Keine')}`",         inline=False)
    embed.add_field(name="Gelesene Bytes",
                    value=f"{state.get('offset', 0):,}",             inline=True)
    embed.add_field(name="Poll-Intervall",
                    value=f"{cfg.config.get('log_poll_interval_seconds', 10)}s",inline=True)
    embed.add_field(name="Log-Verzeichnis",
                    value=f"`{cfg.config.get('ftp_log_dir', '–')}`", inline=False)
    embed.add_field(name="Banliste",
                    value="Nitrado-Servereinstellungen (via API)",     inline=False)
    embed.add_field(name="FTP-Host",
                    value=f"`{cfg.config.get('ftp_host', '–')}`",    inline=False)
    embed.add_field(name="Bekannte Spieler-Positionen",
                    value=str(len(DayZLogParser.player_positions)),   inline=True)
    embed.add_field(name="Lokale Bans",
                    value=str(len(cfg.bans)),                         inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /hilfe – Alle Befehle
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="hilfe", description="❓ Zeigt alle verfügbaren Bot-Befehle")
async def cmd_hilfe(interaction: discord.Interaction):
    # Spam-Schutz: pro Nutzer, guild-übergreifend per gid=0-Fallback (DMs)
    gid = interaction.guild_id or 0
    remaining = db.cooldown_remaining(gid, interaction.user.id, "hilfe")
    if remaining > 0:
        return await interaction.response.send_message(
            embed=_cooldown_embed("/hilfe", remaining), ephemeral=True)
    db.set_cooldown(gid, interaction.user.id, "hilfe",
                    int(cfg.config.get("hilfe_cooldown_seconds", 30)))
    embed = discord.Embed(
        title="🎮 DayZ Bot – Befehlsübersicht",
        description="Alle Befehle (Admin-Rolle erforderlich, außer /hilfe)",
        color=0x5865F2
    )
    embed.add_field(name="⚙️ Server-Verwaltung", value=(
        "`/neustart` — Server neu starten\n"
        "`/stoppen` — Server stoppen\n"
        "`/serverstatus` — Server-Status anzeigen\n"
        "`/auto restart <intervall>` — Geplante Neustarts (Uhrzeit per Dropdown)\n"
        "`/auto status` / `/auto off` — Zeitplan anzeigen / deaktivieren"
    ), inline=False)
    embed.add_field(name="🔨 Spieler-Verwaltung", value=(
        "`/ban <spieler> [grund]` — Auf die Nitrado-Banliste setzen (Komma = mehrere)\n"
        "`/ban_entfernen <spieler>` — Von der Nitrado-Banliste entfernen\n"
        "`/banlist` — Nitrado-Banliste anzeigen\n"
        "`/admin_position` — Letzte Positionen\n"
        "`/spieler_suche <name>` — Spieler in Logs suchen"
    ), inline=False)
    embed.add_field(name="📡 Feed-Verwaltung", value=(
        "`/show_feeds` — Alle Feeds & Channels anzeigen\n"
        "`/edit_feeds <feed> [#channel]` — Feed ändern oder deaktivieren"
    ), inline=False)
    embed.add_field(name="🛡️ Zonen-Pings", value=(
        "`/zone create <x> <z> <name> <radius> [channel] [rolle]` — Zone anlegen "
        "(pingt beim Betreten; Channel & Rolle optional)\n"
        "`/zone remove <name>` — Zone entfernen\n"
        "`/zone list` — Alle aktiven Zonen (Name, x/z, Radius, Channel)\n"
        "`/zone edit <name> […]` — Zone bearbeiten (auch Channel)\n"
        "`/zone allowlist add|remove|show <zone> <spieler>` — Spieler in einer Zone "
        "ignorieren / wieder melden / anzeigen"
    ), inline=False)
    embed.add_field(name="📢 Setup", value=(
        "`/setup token <token>` — Nitrado-Token setzen; Server im Dropdown "
        "auswählen & bestätigen (FTP-Zugang und aktive Karte werden "
        "automatisch erkannt)\n"
        "`/setup feeds <feed> #channel` — Feed-Channel per Dropdown setzen "
        "(killfeed, damagefeed, joinleave, suicide, chat, adminlog, envdeath, "
        "vehiclecrash, basebuild, loot, connecting, shop_log, economy_log, "
        "status, restart, zone)\n"
        "`/setup uebersicht` — Alle konfigurierten Channels anzeigen\n"
        "`/edit_feeds <feed> [#channel]` — Feed ändern oder deaktivieren"
    ), inline=False)
    embed.add_field(name="📊 Kill-Stats & Belohnungen", value=(
        "`/stats <spieler>` — Kills, Tode, K/D, Lieblingswaffe, weitester Kill\n"
        "`/leaderboard` — Top 10 PvP-Killer\n"
        "`/link <playstation-name>` / `/unlink` — Account verknüpfen (Kill- & Spielzeit-Geld)\n"
        "`/username list` — Eigene Verknüpfung anzeigen (Admins: alle, 🟢 = online)\n"
        "`/forcelink <name> <@user>` / `/forceunlink <@user>` *(Admin)*\n"
        "`/bounty <spieler> <betrag>` — Kopfgeld aussetzen · `/bounties` — aktive Kopfgelder"
    ), inline=False)
    embed.add_field(name="🔧 Diagnose", value=(
        "`/log_status` — Polling-Status\n"
        "`/ftp_scan` — FTP neu scannen\n"
        "`/ftp_status` — FTP-Verbindung testen\n"
        "`/raw_log [zeilen]` — Rohe Log-Zeilen anzeigen (Debug)\n"
        "`/test [zeilen]` — Letztes Event pro Typ in Channels posten"
    ), inline=False)
    embed.add_field(name="💰 Economy", value=(
        "`/balance [@user]` — Wallet & Bank\n"
        "`/deposit [amount]` / `/withdraw [amount]`\n"
        "`/pay <@user> <betrag>` — Geld an Mitspieler überweisen\n"
        "`/work` `/daily` `/beg` — Geld verdienen\n"
        "`/addmoney` `/removemoney` `/setbalance` *(Admin)*\n"
        "`/economy_reload` — config.json neu laden *(Admin)*"
    ), inline=False)
    embed.add_field(name="🎰 Casino", value=(
        "`/blackjack <bet>` — Blackjack mit Hit/Stand-Buttons\n"
        "`/roulette <bet> <wager>` — red/black/even/odd/low/high/0-36\n"
        "`/slots <bet>` — Slot-Maschine"
    ), inline=False)
    embed.add_field(name="🛒 Shop", value=(
        "`/shop list [category]` — Item-Katalog (leer = Kategorie-Übersicht)\n"
        "`/buy <item> <amount> <x> <z> [y]` — Item kaufen (spawnt nach Neustart)\n"
        "`/add shopitem <classnames> <price>` — Item/Bundle hinzufügen *(Admin)*\n"
        "`/bundle add` — Bundle per Formular anlegen (Menge je Item, Dropdown-Kategorie) *(Admin)*\n"
        "`/edit shopitem <item> […]` — Classnames/Preis/Name/Kategorie ändern *(Admin)*\n"
        "`/shop pending` `/shop check` `/shop cleanup` `/shop setprice` "
        "`/shop enable` `/shop removeitem` *(Admin)*\n"
        "`/setup feeds shop_log|economy_log #channel` — Feed-Channels"
    ), inline=False)
    embed.add_field(name="📢 Ankündigungen", value=(
        "`/erstellen` — Neue wiederkehrende Ankündigung anlegen (Tag/Uhrzeit/Wiederholung per Dropdown)\n"
        "`/liste` — Alle Ankündigungen mit nächstem Sendetermin & Countdown\n"
        "`/löschen <index>` — Ankündigung löschen\n"
        "`/edit ankuendigung <index>` — Nachricht/Bild einer Ankündigung ändern\n"
        "`/hackban <user_id> [grund]` — Discord-Nutzer per ID bannen"
    ), inline=False)
    admin_ids = cfg.config.get("admin_role_ids", [])
    footer = (f"Admin-Rollen-IDs: {', '.join(str(i) for i in admin_ids)}"
              if admin_ids else
              f"Admin-Rolle: {cfg.config.get('admin_role_name', 'DayZ Admin')} "
              f"(Tipp: admin_role_ids in config.json setzen)")
    embed.set_footer(text=footer)
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════
#  ANKÜNDIGUNGEN – Wiederkehrende geplante Nachrichten
#  (/erstellen, /liste, /löschen, /edit ankuendigung, /hackban)
# ══════════════════════════════════════════════════════════════
ANNOUNCEMENTS_FILE = "announcements.json"

try:
    with open(ANNOUNCEMENTS_FILE, "r", encoding="utf-8") as f:
        ann_data = json.load(f)
except FileNotFoundError:
    ann_data = {"announcements": []}
    with open(ANNOUNCEMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(ann_data, f, ensure_ascii=False, indent=4)


def save_announcements():
    with open(ANNOUNCEMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(ann_data, f, ensure_ascii=False, indent=4)


def should_send_today(ann: dict, today: date) -> bool:
    """
    Prüft ob eine Ankündigung heute gesendet werden soll,
    basierend auf dem repeat-Typ und dem letzten Sendedatum.
    """
    repeat = ann.get("repeat", "weekly")
    last_sent_str = ann.get("last_sent")

    # Intervall in Wochen bestimmen
    interval_map = {
        "weekly":    1,
        "biweekly":  2,
        "triweekly": 3,
        "monthly":   4,  # ~4 Wochen
    }
    interval_weeks = interval_map.get(repeat, 1)

    if not last_sent_str:
        # Noch nie gesendet → darf heute gesendet werden
        return True

    last_sent = date.fromisoformat(last_sent_str)
    next_send = last_sent + timedelta(weeks=interval_weeks)

    return today >= next_send


def get_next_send_datetime(ann: dict) -> datetime:
    """
    Berechnet den nächsten Sendezeitpunkt einer Ankündigung
    als datetime-Objekt (Europe/Berlin).
    """
    tz = ZoneInfo("Europe/Berlin")
    repeat = ann.get("repeat", "weekly")
    last_sent_str = ann.get("last_sent")
    time_str = ann.get("time", "00:00")
    hour, minute = map(int, time_str.split(":"))

    interval_map = {
        "weekly":    1,
        "biweekly":  2,
        "triweekly": 3,
        "monthly":   4,
    }
    interval_weeks = interval_map.get(repeat, 1)

    today = datetime.now(tz).date()

    if not last_sent_str:
        # Noch nie gesendet → nächster passender Wochentag
        day_map = {
            "monday": 0, "tuesday": 1, "wednesday": 2,
            "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
        }
        target_weekday = day_map.get(ann.get("day", "monday"), 0)
        days_ahead = (target_weekday - today.weekday()) % 7
        next_date = today + timedelta(days=days_ahead)
    else:
        last_sent = date.fromisoformat(last_sent_str)
        next_date = last_sent + timedelta(weeks=interval_weeks)

    return datetime(next_date.year, next_date.month, next_date.day, hour, minute, 0, tzinfo=tz)


def format_countdown(dt: datetime) -> str:
    """Gibt die verbleibende Zeit bis dt als lesbaren String zurück."""
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    diff = dt - now

    if diff.total_seconds() <= 0:
        return "Wird gleich gesendet"

    total_seconds = int(diff.total_seconds())
    days    = total_seconds // 86400
    hours   = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts = []
    if days:    parts.append(f"{days}T")
    if hours:   parts.append(f"{hours}Std")
    if minutes: parts.append(f"{minutes}Min")
    parts.append(f"{seconds}Sek")

    return " ".join(parts)


ann_already_sent = set()


async def check_announcements():
    now = datetime.now(ZoneInfo("Europe/Berlin"))

    day = now.strftime("%A").lower()
    time_str = now.strftime("%H:%M")
    today = now.date()

    for ann in ann_data["announcements"]:

        if ann["day"] == day and ann["time"] == time_str:

            key = f"{today.isoformat()}-{day}-{time_str}-{ann['channel_id']}"

            if key in ann_already_sent:
                continue

            # Repeat-Logik prüfen
            if not should_send_today(ann, today):
                continue

            channel = bot.get_channel(int(ann["channel_id"]))

            if channel:

                embed = discord.Embed(
                    description=ann["message"],
                    color=discord.Color.blue()
                )

                if ann.get("image"):
                    embed.set_image(url=ann["image"])

                try:
                    await channel.send(embed=embed)
                    ann_already_sent.add(key)

                    # Letztes Sendedatum speichern
                    ann["last_sent"] = today.isoformat()
                    save_announcements()

                except Exception as e:
                    log.error(f"[ANKÜNDIGUNG] Fehler beim Senden: {e}")


@tasks.loop(minutes=1)
async def announcement_scheduler():
    await check_announcements()


# ─── Ankündigungs-UI: Tag / Uhrzeit / Wiederholung ───

class TagSelect(discord.ui.Select):

    def __init__(self):

        options = [
            discord.SelectOption(label="Montag", value="monday"),
            discord.SelectOption(label="Dienstag", value="tuesday"),
            discord.SelectOption(label="Mittwoch", value="wednesday"),
            discord.SelectOption(label="Donnerstag", value="thursday"),
            discord.SelectOption(label="Freitag", value="friday"),
            discord.SelectOption(label="Samstag", value="saturday"),
            discord.SelectOption(label="Sonntag", value="sunday"),
        ]

        super().__init__(
            placeholder="Tag auswählen",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        self.view.selected_day = self.values[0]

        await interaction.response.defer()


class TimeSelect(discord.ui.Select):

    def __init__(self, page=0):

        all_times = []

        for h in range(24):

            all_times.append(f"{h:02d}:00")
            all_times.append(f"{h:02d}:30")

        per_page = 16

        start = page * per_page
        end = start + per_page

        times = all_times[start:end]

        options = [
            discord.SelectOption(label=t, value=t)
            for t in times
        ]

        super().__init__(
            placeholder=f"Uhrzeit (Seite {page+1}/3)",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        self.view.selected_time = self.values[0]

        await interaction.response.defer()


class RepeatSelect(discord.ui.Select):

    def __init__(self):

        options = [
            discord.SelectOption(label="Jede Woche", value="weekly"),
            discord.SelectOption(label="Alle 2 Wochen", value="biweekly"),
            discord.SelectOption(label="Alle 3 Wochen", value="triweekly"),
            discord.SelectOption(label="Jeden Monat", value="monthly"),
        ]

        super().__init__(
            placeholder="Wiederholung auswählen",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        self.view.selected_repeat = self.values[0]
        await interaction.response.defer()


class PageButton(discord.ui.Button):

    def __init__(self, label, page):

        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary
        )

        self.page = page

    async def callback(self, interaction: discord.Interaction):

        view = CreateAnnouncementView(page=self.page)

        view.selected_day = self.view.selected_day
        view.selected_time = self.view.selected_time
        view.selected_repeat = self.view.selected_repeat

        await interaction.response.edit_message(view=view)


class NextButton(discord.ui.Button):

    def __init__(self):

        super().__init__(
            label="Weiter",
            style=discord.ButtonStyle.success
        )

    async def callback(self, interaction: discord.Interaction):

        if not self.view.selected_day or not self.view.selected_time or not self.view.selected_repeat:

            await interaction.response.send_message(
                "Bitte Tag und Uhrzeit wählen.",
                ephemeral=True
            )

            return

        modal = AnnouncementModal(
            self.view.selected_day,
            self.view.selected_time,
            self.view.selected_repeat
        )

        await interaction.response.send_modal(modal)


class CreateAnnouncementView(discord.ui.View):

    def __init__(self, page=0):

        super().__init__(timeout=300)

        self.selected_day = None
        self.selected_time = None
        self.selected_repeat = None

        self.add_item(TagSelect())
        self.add_item(TimeSelect(page))
        self.add_item(RepeatSelect())

        if page > 0:
            self.add_item(PageButton("⬅", page - 1))

        if page < 2:
            self.add_item(PageButton("➡", page + 1))

        self.add_item(NextButton())


class AnnouncementModal(discord.ui.Modal):

    def __init__(self, day, time, repeat_type):

        super().__init__(title="Ankündigung")

        self.day = day
        self.time = time
        self.repeat_type = repeat_type

        self.msg = discord.ui.TextInput(
            label="Nachricht",
            style=discord.TextStyle.paragraph,
            max_length=2000
        )

        self.channel = discord.ui.TextInput(
            label="Channel-ID"
        )

        self.image = discord.ui.TextInput(
            label="Bild URL",
            required=False
        )

        self.add_item(self.msg)
        self.add_item(self.channel)
        self.add_item(self.image)

    async def on_submit(self, interaction: discord.Interaction):

        try:
            channel = bot.get_channel(int(self.channel.value))

        except Exception:

            return await interaction.response.send_message(
                "❌ Fehlerhafte Channel-ID",
                ephemeral=True
            )

        if not channel:

            return await interaction.response.send_message(
                "❌ Channel nicht gefunden",
                ephemeral=True
            )

        ann_data["announcements"].append({
            "message": self.msg.value,
            "channel_id": str(self.channel.value),
            "day": self.day,
            "time": self.time,
            "repeat": self.repeat_type,
            "image": self.image.value.strip() if self.image.value else None,
            "last_sent": None  # Wird nach dem ersten Senden gesetzt
        })

        save_announcements()

        await interaction.response.send_message(
            "✅ Ankündigung gespeichert",
            ephemeral=True
        )


class EditAnnouncementModal(discord.ui.Modal):

    def __init__(self, index):

        super().__init__(title="Ankündigung bearbeiten")

        self.index = index

        ann = ann_data["announcements"][index]

        self.message_input = discord.ui.TextInput(
            label="Neue Nachricht",
            style=discord.TextStyle.paragraph,
            default=ann["message"],
            max_length=2000
        )

        self.image_input = discord.ui.TextInput(
            label="Neue Bild URL",
            default=ann.get("image") or "",
            required=False
        )

        self.add_item(self.message_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):

        ann_data["announcements"][self.index]["message"] = self.message_input.value

        ann_data["announcements"][self.index]["image"] = (
            self.image_input.value.strip()
            if self.image_input.value
            else None
        )

        save_announcements()

        await interaction.response.send_message(
            "✅ Ankündigung bearbeitet",
            ephemeral=True
        )


@bot.tree.command(name="erstellen", description="📢 Neue wiederkehrende Ankündigung anlegen")
async def cmd_ann_erstellen(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)

    await interaction.response.send_message(
        "Setup starten:",
        view=CreateAnnouncementView(),
        ephemeral=True
    )


@bot.tree.command(name="liste", description="📋 Zeigt alle geplanten Ankündigungen")
async def cmd_ann_liste(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)

    embed = discord.Embed(
        title="📋 Ankündigungen",
        color=discord.Color.blue()
    )

    if not ann_data["announcements"]:

        embed.description = "Keine Ankündigungen gespeichert."

    else:

        repeat_label = {
            "weekly":    "Jede Woche",
            "biweekly":  "Alle 2 Wochen",
            "triweekly": "Alle 3 Wochen",
            "monthly":   "Jeden Monat",
        }

        day_label = {
            "monday": "Montag", "tuesday": "Dienstag", "wednesday": "Mittwoch",
            "thursday": "Donnerstag", "friday": "Freitag",
            "saturday": "Samstag", "sunday": "Sonntag"
        }

        for i, ann in enumerate(ann_data["announcements"]):

            last_sent_str = ann.get("last_sent")
            last_sent_display = (
                f"📅 Zuletzt gesendet: **{last_sent_str}** um **{ann['time']} Uhr**"
                if last_sent_str
                else "📅 Zuletzt gesendet: **Noch nie**"
            )

            next_dt = get_next_send_datetime(ann)
            next_display = (
                f"⏭️ Nächster Post: **{next_dt.strftime('%d.%m.%Y')}** um **{next_dt.strftime('%H:%M')} Uhr**\n"
                f"⏱️ In: **{format_countdown(next_dt)}**"
            )

            embed.add_field(
                name=f"#{i} • {day_label.get(ann['day'], ann['day'])} • {ann['time']} Uhr • {repeat_label.get(ann.get('repeat', 'weekly'), ann.get('repeat', ''))}",
                value=(
                    f"💬 {ann['message']}\n"
                    f"📢 Channel: <#{ann['channel_id']}>\n"
                    f"{last_sent_display}\n"
                    f"{next_display}"
                ),
                inline=False
            )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


@bot.tree.command(name="löschen", description="🗑️ Löscht eine Ankündigung")
@app_commands.describe(index="Nummer der Ankündigung (siehe /liste)")
async def cmd_ann_loeschen(
    interaction: discord.Interaction,
    index: int
):
    if not _is_admin(interaction):
        return await _deny(interaction)

    if index < 0 or index >= len(ann_data["announcements"]):

        return await interaction.response.send_message(
            "❌ Ungültiger Index",
            ephemeral=True
        )

    ann_data["announcements"].pop(index)

    save_announcements()

    await interaction.response.send_message(
        "✅ Gelöscht",
        ephemeral=True
    )


@bot.tree.command(name="hackban", description="🔨 Bannt einen Discord-Benutzer per ID.")
@app_commands.describe(
    user_id="Discord User-ID",
    grund="Grund für den Bann"
)
async def cmd_hackban(
    interaction: discord.Interaction,
    user_id: str,
    grund: str = "Kein Grund angegeben"
):
    if not _is_admin(interaction):
        return await _deny(interaction)

    try:

        user = await bot.fetch_user(int(user_id))

        await interaction.guild.ban(
            user,
            reason=grund,
            delete_message_days=0
        )

        await interaction.response.send_message(
            f"✅ Benutzer {user} wurde gebannt.\nGrund: {grund}"
        )

    except discord.NotFound:

        await interaction.response.send_message(
            "❌ Benutzer nicht gefunden.",
            ephemeral=True
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ Keine Rechte.",
            ephemeral=True
        )

    except ValueError:

        await interaction.response.send_message(
            "❌ Ungültige User-ID.",
            ephemeral=True
        )

    except Exception as e:

        await interaction.response.send_message(
            f"❌ Fehler: {e}",
            ephemeral=True
        )


# ══════════════════════════════════════════════════════════════
#  ECONOMY-DATENBANK (SQLite)
#  Geldsalden/Buchungen laufen bewusst über SQLite statt JSON,
#  damit parallele Buchungen die Salden nicht korrumpieren.
# ══════════════════════════════════════════════════════════════
ECON_DB_FILE = "economy.db"

class EconomyDB:
    """Persistenz für Salden (Wallet/Bank), Cooldowns, Käufe und Casino-Historie.
    Die Verbindung wird lazy beim ersten Zugriff geöffnet – erst dann ist
    config.json geladen und economy_db_path bekannt. Ein RLock schützt
    parallele Zugriffe; WAL reduziert fsync-Blocking auf dem Event-Loop."""

    def __init__(self, path: Optional[str] = None):
        self._lock = threading.RLock()
        self._path = path
        self._db: Optional[sqlite3.Connection] = None

    @property
    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            with self._lock:
                if self._db is None:
                    path = self._path or str(cfg.config.get("economy_db_path") or ECON_DB_FILE)
                    conn = sqlite3.connect(path, check_same_thread=False)
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA busy_timeout=5000")
                    self._create_tables(conn)
                    self._db = conn
                    log.info(f"[ECON] SQLite-Datenbank bereit: {path}")
        return self._db

    def _create_tables(self, c: sqlite3.Connection):
        with self._lock:
            c.execute("""CREATE TABLE IF NOT EXISTS balances (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                wallet   INTEGER NOT NULL DEFAULT 0,
                bank     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS cooldowns (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                action   TEXT    NOT NULL,
                ready_at REAL    NOT NULL,
                PRIMARY KEY (guild_id, user_id, action))""")
            c.execute("""CREATE TABLE IF NOT EXISTS purchases (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                user_name    TEXT,
                item_name    TEXT,
                classname    TEXT,
                amount       INTEGER,
                total_price  INTEGER,
                x REAL, y REAL, z REAL,
                area_names   TEXT,
                status       TEXT DEFAULT 'pending',
                created_at   REAL,
                delivered_at REAL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS casino_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER,
                user_id    INTEGER,
                game       TEXT,
                bet        INTEGER,
                payout     INTEGER,
                result     TEXT,
                created_at REAL)""")
            # PvP-Kills für /stats und /leaderboard (Server-weit, nicht pro Guild)
            c.execute("""CREATE TABLE IF NOT EXISTS kills (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  REAL,
                killer_name TEXT,
                killer_id   TEXT,
                victim_name TEXT,
                victim_id   TEXT,
                weapon      TEXT,
                distance    REAL)""")
            # Discord-User ↔ Ingame-Name (pro Guild, ein Name nur einmal)
            c.execute("""CREATE TABLE IF NOT EXISTS links (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                ingame_name TEXT    NOT NULL COLLATE NOCASE,
                ingame_id   TEXT,
                created_at  REAL,
                PRIMARY KEY (guild_id, user_id),
                UNIQUE (guild_id, ingame_name))""")
            # Kopfgelder (Betrag wurde beim Aussetzen bereits abgebucht)
            c.execute("""CREATE TABLE IF NOT EXISTS bounties (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                target_name TEXT    NOT NULL COLLATE NOCASE,
                amount      INTEGER NOT NULL,
                placed_by   INTEGER NOT NULL,
                created_at  REAL,
                status      TEXT DEFAULT 'open',
                claimed_by  INTEGER,
                claimed_at  REAL)""")
            # Offene Spielzeit-Sitzungen (connect → disconnect/Restart)
            c.execute("""CREATE TABLE IF NOT EXISTS sessions (
                ingame_name     TEXT PRIMARY KEY COLLATE NOCASE,
                ingame_id       TEXT,
                connect_ts      REAL NOT NULL,
                last_seen_ts    REAL NOT NULL,
                credited_blocks INTEGER NOT NULL DEFAULT 0)""")
            c.commit()

    # ── Salden ────────────────────────────────────────────────
    def ensure_user(self, guild_id: int, user_id: int):
        """Legt den User mit Startguthaben an, falls noch nicht vorhanden."""
        start = int(cfg.config.get("starting_balance", 0))
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO balances (guild_id, user_id, wallet, bank) VALUES (?,?,?,0)",
                (guild_id, user_id, start))
            self._conn.commit()

    def get_balance(self, guild_id: int, user_id: int) -> Tuple[int, int]:
        self.ensure_user(guild_id, user_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT wallet, bank FROM balances WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)).fetchone()
        return (int(row["wallet"]), int(row["bank"])) if row else (0, 0)

    def add_wallet(self, guild_id: int, user_id: int, delta: int) -> Tuple[int, int]:
        """Addiert delta (auch negativ) aufs Wallet – nie unter 0. Gibt (wallet, bank) zurück."""
        self.ensure_user(guild_id, user_id)
        with self._lock:
            self._conn.execute(
                "UPDATE balances SET wallet = MAX(0, wallet + ?) WHERE guild_id=? AND user_id=?",
                (int(delta), guild_id, user_id))
            self._conn.commit()
        return self.get_balance(guild_id, user_id)

    def set_wallet(self, guild_id: int, user_id: int, value: int) -> Tuple[int, int]:
        self.ensure_user(guild_id, user_id)
        with self._lock:
            self._conn.execute(
                "UPDATE balances SET wallet = MAX(0, ?) WHERE guild_id=? AND user_id=?",
                (int(value), guild_id, user_id))
            self._conn.commit()
        return self.get_balance(guild_id, user_id)

    def try_spend_wallet(self, guild_id: int, user_id: int, amount: int) -> bool:
        """Atomare Abbuchung: nur wenn genug Guthaben vorhanden ist (kein Race möglich)."""
        if amount < 0:
            return False
        if amount == 0:
            return True   # Gratis-Item (Preis 0): nichts abzubuchen, Kauf ist gültig
        self.ensure_user(guild_id, user_id)
        with self._lock:
            cur = self._conn.execute(
                "UPDATE balances SET wallet = wallet - ? "
                "WHERE guild_id=? AND user_id=? AND wallet >= ?",
                (amount, guild_id, user_id, amount))
            self._conn.commit()
            return cur.rowcount > 0

    def deposit(self, guild_id: int, user_id: int, amount: Optional[int]) -> Tuple[int, int, int]:
        """Wallet → Bank. amount=None → alles. Gibt (verschoben, wallet, bank) zurück."""
        self.ensure_user(guild_id, user_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT wallet, bank FROM balances WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)).fetchone()
            move = int(row["wallet"]) if amount is None else min(int(amount), int(row["wallet"]))
            if move <= 0:
                return 0, int(row["wallet"]), int(row["bank"])
            self._conn.execute(
                "UPDATE balances SET wallet = wallet - ?, bank = bank + ? "
                "WHERE guild_id=? AND user_id=?",
                (move, move, guild_id, user_id))
            self._conn.commit()
            return move, int(row["wallet"]) - move, int(row["bank"]) + move

    def withdraw(self, guild_id: int, user_id: int, amount: Optional[int]) -> Tuple[int, int, int]:
        """Bank → Wallet. amount=None → alles. Gibt (verschoben, wallet, bank) zurück."""
        self.ensure_user(guild_id, user_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT wallet, bank FROM balances WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)).fetchone()
            move = int(row["bank"]) if amount is None else min(int(amount), int(row["bank"]))
            if move <= 0:
                return 0, int(row["wallet"]), int(row["bank"])
            self._conn.execute(
                "UPDATE balances SET wallet = wallet + ?, bank = bank - ? "
                "WHERE guild_id=? AND user_id=?",
                (move, move, guild_id, user_id))
            self._conn.commit()
            return move, int(row["wallet"]) + move, int(row["bank"]) - move

    # ── Cooldowns ─────────────────────────────────────────────
    def cooldown_remaining(self, guild_id: int, user_id: int, action: str) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT ready_at FROM cooldowns WHERE guild_id=? AND user_id=? AND action=?",
                (guild_id, user_id, action)).fetchone()
        if not row:
            return 0.0
        return max(0.0, float(row["ready_at"]) - time.time())

    def set_cooldown(self, guild_id: int, user_id: int, action: str, seconds: float):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cooldowns (guild_id, user_id, action, ready_at) "
                "VALUES (?,?,?,?)",
                (guild_id, user_id, action, time.time() + max(0.0, seconds)))
            self._conn.commit()

    # ── Käufe / Delivery-Tracking ─────────────────────────────
    def create_purchase(self, guild_id: int, user_id: int, user_name: str,
                        item_name: str, classname: str, amount: int, total_price: int,
                        x: float, y: float, z: float, area_names: List[str]) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO purchases
                   (guild_id, user_id, user_name, item_name, classname, amount,
                    total_price, x, y, z, area_names, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending',?)""",
                (guild_id, user_id, user_name, item_name, classname, amount,
                 total_price, x, y, z, json.dumps(area_names), time.time()))
            self._conn.commit()
            return int(cur.lastrowid)

    def pending_purchases(self, created_before: Optional[float] = None) -> List[sqlite3.Row]:
        q = "SELECT * FROM purchases WHERE status='pending'"
        args: Tuple = ()
        if created_before is not None:
            q += " AND created_at <= ?"
            args = (created_before,)
        with self._lock:
            return list(self._conn.execute(q + " ORDER BY id", args).fetchall())

    def mark_delivered(self, ids: List[int]):
        if not ids:
            return
        now = time.time()
        with self._lock:
            self._conn.executemany(
                "UPDATE purchases SET status='delivered', delivered_at=? WHERE id=?",
                [(now, i) for i in ids])
            self._conn.commit()

    # ── Casino-Historie ───────────────────────────────────────
    def log_casino(self, guild_id: int, user_id: int, game: str,
                   bet: int, payout: int, result: str):
        with self._lock:
            self._conn.execute(
                "INSERT INTO casino_history (guild_id, user_id, game, bet, payout, result, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (guild_id, user_id, game, bet, payout, result, time.time()))
            self._conn.commit()

    # ── Kill-Statistiken ──────────────────────────────────────
    def record_kill(self, killer_name: str, killer_id: Optional[str],
                    victim_name: str, victim_id: Optional[str],
                    weapon: Optional[str], distance: Any):
        try:
            dist: Optional[float] = float(str(distance).replace(",", "."))
        except (TypeError, ValueError):
            dist = None
        with self._lock:
            self._conn.execute(
                "INSERT INTO kills (created_at, killer_name, killer_id, victim_name, "
                "victim_id, weapon, distance) VALUES (?,?,?,?,?,?,?)",
                (time.time(), killer_name, killer_id, victim_name, victim_id, weapon, dist))
            self._conn.commit()

    def player_stats(self, name: str) -> Optional[Dict]:
        """Kills, Tode (PvP), Lieblingswaffe und weitester Kill eines Spielers."""
        with self._lock:
            kills = int(self._conn.execute(
                "SELECT COUNT(*) AS n FROM kills WHERE killer_name=? COLLATE NOCASE",
                (name,)).fetchone()["n"])
            deaths = int(self._conn.execute(
                "SELECT COUNT(*) AS n FROM kills WHERE victim_name=? COLLATE NOCASE",
                (name,)).fetchone()["n"])
            if kills == 0 and deaths == 0:
                return None
            fav = self._conn.execute(
                "SELECT weapon, COUNT(*) AS n FROM kills "
                "WHERE killer_name=? COLLATE NOCASE AND weapon IS NOT NULL "
                "AND weapon NOT IN ('', 'Unbekannt') "
                "GROUP BY weapon ORDER BY n DESC LIMIT 1", (name,)).fetchone()
            longest = self._conn.execute(
                "SELECT MAX(distance) AS d FROM kills WHERE killer_name=? COLLATE NOCASE",
                (name,)).fetchone()["d"]
        return {
            "kills": kills, "deaths": deaths,
            "kd": (kills / deaths) if deaths else float(kills),
            "fav_weapon": fav["weapon"] if fav else None,
            "fav_weapon_kills": int(fav["n"]) if fav else 0,
            "longest": float(longest) if longest is not None else None,
        }

    def leaderboard(self, limit: int = 10) -> List[Dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT killer_name AS name, COUNT(*) AS kills, MAX(distance) AS best "
                "FROM kills GROUP BY killer_name COLLATE NOCASE "
                "ORDER BY kills DESC, best DESC LIMIT ?", (limit,)).fetchall()
            out: List[Dict] = []
            for r in rows:
                deaths = int(self._conn.execute(
                    "SELECT COUNT(*) AS n FROM kills WHERE victim_name=? COLLATE NOCASE",
                    (r["name"],)).fetchone()["n"])
                out.append({"name": r["name"], "kills": int(r["kills"]), "deaths": deaths,
                            "kd": (int(r["kills"]) / deaths) if deaths else float(r["kills"]),
                            "best": float(r["best"]) if r["best"] is not None else None})
        return out

    def known_player_names(self, prefix: str = "", limit: int = 25) -> List[str]:
        """Spielernamen aus Kills + Sitzungen (für Autocomplete)."""
        like = f"%{prefix}%" if prefix else "%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM ("
                "  SELECT killer_name AS name FROM kills"
                "  UNION SELECT victim_name FROM kills"
                "  UNION SELECT ingame_name FROM sessions) "
                "WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT ?",
                (like, limit)).fetchall()
        return [r["name"] for r in rows if r["name"]]

    # ── /link: Discord ↔ Ingame-Name ──────────────────────────
    def link_user(self, guild_id: int, user_id: int, ingame_name: str) -> Tuple[bool, str]:
        """Verknüpft einen Discord-User mit einem Ingame-Namen (pro Guild eindeutig)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id FROM links WHERE guild_id=? AND ingame_name=?",
                (guild_id, ingame_name)).fetchone()
            if row and int(row["user_id"]) != user_id:
                return False, "name_taken"
            self._conn.execute(
                "INSERT OR REPLACE INTO links (guild_id, user_id, ingame_name, ingame_id, created_at) "
                "VALUES (?,?,?,?,?)",
                (guild_id, user_id, ingame_name, None, time.time()))
            self._conn.commit()
        return True, "ok"

    def unlink_user(self, guild_id: int, user_id: int) -> Optional[str]:
        """Entfernt die Verknüpfung; gibt den bisherigen Ingame-Namen zurück."""
        with self._lock:
            row = self._conn.execute(
                "SELECT ingame_name FROM links WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)).fetchone()
            if not row:
                return None
            self._conn.execute("DELETE FROM links WHERE guild_id=? AND user_id=?",
                               (guild_id, user_id))
            self._conn.commit()
        return row["ingame_name"]

    def get_link_by_user(self, guild_id: int, user_id: int) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM links WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)).fetchone()

    def links_for_name(self, ingame_name: str) -> List[sqlite3.Row]:
        """Alle Guild-Verknüpfungen für einen Ingame-Namen (case-insensitive)."""
        with self._lock:
            return list(self._conn.execute(
                "SELECT * FROM links WHERE ingame_name=? COLLATE NOCASE",
                (ingame_name,)).fetchall())

    def update_link_id(self, ingame_name: str, ingame_id: str):
        """Trägt die im Log gesehene Ingame-ID zum verlinkten Namen nach."""
        if not ingame_id:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE links SET ingame_id=? WHERE ingame_name=? COLLATE NOCASE "
                "AND (ingame_id IS NULL OR ingame_id != ?)",
                (ingame_id, ingame_name, ingame_id))
            self._conn.commit()

    def list_links(self, guild_id: int) -> List[sqlite3.Row]:
        """Alle Verknüpfungen einer Guild, alphabetisch nach PSN-Name."""
        with self._lock:
            return list(self._conn.execute(
                "SELECT * FROM links WHERE guild_id=? ORDER BY ingame_name COLLATE NOCASE",
                (guild_id,)).fetchall())

    def has_session(self, ingame_name: str) -> bool:
        """True, wenn für den Spieler gerade eine Spielzeit-Sitzung offen ist."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE ingame_name=? COLLATE NOCASE",
                (ingame_name,)).fetchone()
        return row is not None

    def sync_sessions_from_positions(self, positions: Dict, max_age_seconds: int = 300) -> int:
        """Öffnet Sitzungen für VERLINKTE Spieler, die laut Log-Positions-Tracking
        gerade aktiv sind, aber keine offene Sitzung haben (verpasstes Connect-Event
        durch Bot-Downtime/Backlog-Skip oder /link während man schon online ist).
        Gibt die Anzahl neu geöffneter Sitzungen zurück."""
        now_utc = datetime.now(timezone.utc)
        with self._lock:
            linked = {str(r["ingame_name"]).lower()
                      for r in self._conn.execute(
                          "SELECT DISTINCT ingame_name FROM links").fetchall()}
        opened = 0
        for pname, info in list(positions.items()):
            if pname.lower() not in linked:
                continue
            try:
                seen = datetime.fromisoformat(str(info.get("last_seen", "")))
            except ValueError:
                continue
            if (now_utc - seen).total_seconds() > max_age_seconds:
                continue
            if self.has_session(pname):
                continue
            self.open_session(pname, info.get("id"))
            opened += 1
            log.info(f"[PLAYTIME] Sitzung für {pname} aus Log-Sichtung geöffnet (Connect-Event verpasst).")
        return opened

    # ── Bounties (Kopfgelder) ─────────────────────────────────
    def add_bounty(self, guild_id: int, target_name: str, amount: int, placed_by: int) -> int:
        """Setzt ein Kopfgeld aus (Betrag wurde bereits abgebucht).
        Gibt die neue Gesamtsumme auf das Ziel zurück."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO bounties (guild_id, target_name, amount, placed_by, created_at) "
                "VALUES (?,?,?,?,?)",
                (guild_id, target_name, amount, placed_by, time.time()))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS total FROM bounties "
                "WHERE guild_id=? AND target_name=? COLLATE NOCASE AND status='open'",
                (guild_id, target_name)).fetchone()
        return int(row["total"])

    def open_bounties(self, guild_id: int) -> List[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(
                "SELECT target_name, SUM(amount) AS total, COUNT(*) AS n "
                "FROM bounties WHERE guild_id=? AND status='open' "
                "GROUP BY target_name COLLATE NOCASE ORDER BY total DESC",
                (guild_id,)).fetchall())

    def claim_bounties(self, guild_id: int, target_name: str, claimed_by: int) -> int:
        """Zahlt alle offenen Kopfgelder auf target_name aus (markiert claimed).
        Gibt die Gesamtsumme zurück (0 = keine offenen Bounties)."""
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS total FROM bounties "
                "WHERE guild_id=? AND target_name=? COLLATE NOCASE AND status='open'",
                (guild_id, target_name)).fetchone()
            total = int(row["total"])
            if total > 0:
                self._conn.execute(
                    "UPDATE bounties SET status='claimed', claimed_by=?, claimed_at=? "
                    "WHERE guild_id=? AND target_name=? COLLATE NOCASE AND status='open'",
                    (claimed_by, now, guild_id, target_name))
                self._conn.commit()
        return total

    # ── Spielzeit-Sitzungen ───────────────────────────────────
    def open_session(self, ingame_name: str, ingame_id: Optional[str]):
        """Connect-Event: neue Sitzung (Reconnect setzt den Zähler zurück)."""
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions "
                "(ingame_name, ingame_id, connect_ts, last_seen_ts, credited_blocks) "
                "VALUES (?,?,?,?,0)",
                (ingame_name, ingame_id, now, now))
            self._conn.commit()

    def close_session(self, ingame_name: str):
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE ingame_name=? COLLATE NOCASE",
                               (ingame_name,))
            self._conn.commit()

    def close_all_sessions(self):
        with self._lock:
            self._conn.execute("DELETE FROM sessions")
            self._conn.commit()

    def playtime_credits_due(self, interval_seconds: int) -> List[Dict]:
        """Berechnet pro offener Sitzung neu fällige Spielzeit-Blöcke und
        schreibt credited_blocks fort. Gibt [{name, blocks}] zurück."""
        now = time.time()
        out: List[Dict] = []
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sessions").fetchall()
            for r in rows:
                total = int((now - float(r["connect_ts"])) // max(60, interval_seconds))
                due = total - int(r["credited_blocks"])
                if due > 0:
                    self._conn.execute(
                        "UPDATE sessions SET credited_blocks=?, last_seen_ts=? "
                        "WHERE ingame_name=?",
                        (total, now, r["ingame_name"]))
                    out.append({"name": r["ingame_name"], "blocks": due})
            if out:
                self._conn.commit()
        return out

    # ── Backup ────────────────────────────────────────────────
    def backup(self, keep: int = 7) -> Optional[str]:
        """Konsistente Kopie via SQLite-Backup-API (WAL-sicher):
        economy.db.bak-YYYY-MM-DD; behält die neuesten `keep` Stück."""
        path = self._path or str(cfg.config.get("economy_db_path") or ECON_DB_FILE)
        dest = f"{path}.bak-{datetime.now().strftime('%Y-%m-%d')}"
        try:
            with self._lock:
                dst = sqlite3.connect(dest)
                try:
                    self._conn.backup(dst)
                finally:
                    dst.close()
            for old in sorted(glob.glob(f"{path}.bak-*"))[:-max(1, keep)]:
                try:
                    os.remove(old)
                except OSError:
                    pass
            return dest
        except Exception as e:
            log.error(f"[ECON] Backup fehlgeschlagen: {e}")
            return None


db = EconomyDB()


# ══════════════════════════════════════════════════════════════
#  Economy-Hilfsfunktionen
# ══════════════════════════════════════════════════════════════
def _cur_symbol() -> str:
    return cfg.config.get("currency_symbol", "₽")

def _fmt_money(n: int) -> str:
    return f"{int(n):,} {_cur_symbol()}"

def _cooldown_embed(action_label: str, remaining: float) -> discord.Embed:
    """Embed mit Discord-Relativzeit, wann der Befehl wieder nutzbar ist."""
    ready = int(time.time() + remaining)
    return discord.Embed(
        title="⏳ Cooldown",
        description=f"You can use **{action_label}** again <t:{ready}:R>.",
        color=0x95A5A6)

def _insufficient_embed(needed: int, wallet: int) -> discord.Embed:
    return discord.Embed(
        title="❌ Insufficient funds",
        description=(f"You need **{_fmt_money(needed)}** but your wallet only has "
                     f"**{_fmt_money(wallet)}**.\nUse `/withdraw` to move money from your bank."),
        color=0xE74C3C)

def _validate_bet(bet: int, conf: Dict) -> Optional[str]:
    """Gibt eine Fehlermeldung zurück, wenn der Einsatz außerhalb min/max liegt."""
    mn = int(conf.get("min_bet", 1))
    mx = int(conf.get("max_bet", 10 ** 9))
    if bet < mn:
        return f"Minimum bet is **{_fmt_money(mn)}**."
    if bet > mx:
        return f"Maximum bet is **{_fmt_money(mx)}**."
    return None

async def _post_feed(guild_id: Optional[int], log_type: str, embed: discord.Embed,
                     content: Optional[str] = None, channel_id: Optional[int] = None):
    """Postet ein Embed in den konfigurierten Feed-Channel (eine Guild oder alle).
    content: optionaler Nachrichtentext vor dem Embed (z. B. Rollen-Ping bei Zonen).
    channel_id: optionaler Ziel-Channel, der die Feed-Konfiguration überschreibt
    (z. B. eigener Warn-Channel einer Zone)."""
    async def _send(ch_id: int, tag: str):
        ch = await bot._resolve_channel(int(ch_id))
        if not ch:
            return
        try:
            if content:
                await ch.send(content=content, embed=embed,
                              allowed_mentions=discord.AllowedMentions(roles=True))
            else:
                await ch.send(embed=embed)
        except Exception as e:
            log.error(f"[FEED] {tag}: {e}")

    if channel_id:
        await _send(channel_id, f"{log_type} → Channel {channel_id}")
        return
    gids = [str(guild_id)] if guild_id else list(cfg.guilds.keys())
    for gid in gids:
        ch_id = cfg.get_channel(int(gid), log_type)
        if not ch_id:
            continue
        await _send(ch_id, f"{log_type} → Guild {gid}")


async def _notify_link_change(guild_id: Optional[int], embed: discord.Embed):
    """Meldet /link- und /unlink-Aktionen an die Admins:
    bevorzugt im adminlog-Feed, sonst im economy_log-Feed."""
    if guild_id and cfg.get_channel(int(guild_id), "adminlog"):
        return await _post_feed(guild_id, "adminlog", embed)
    await _post_feed(guild_id, "economy_log", embed)


# ══════════════════════════════════════════════════════════════
#  SHOP-MANAGER – Auslieferung über cfgEffectArea.json
#  Ablauf: Kauf → Eintrag in cfgEffectArea.json (pending) →
#  Server-Neustart (Item spawnt) → Eintrag entfernen (delivered).
#  WICHTIG: Ohne Entfernen respawnt das Item bei JEDEM Neustart!
# ══════════════════════════════════════════════════════════════
class ShopManager:
    AREA_PREFIX = "SHOP_"

    def __init__(self, bot_ref: "DayZBot"):
        self.bot  = bot_ref
        self.lock = asyncio.Lock()   # serialisiert ALLE Schreibzugriffe auf die Datei
        self._restart_task: Optional[asyncio.Task] = None
        self._last_restart_ts = 0.0
        self._cleanup_task: Optional[asyncio.Task] = None
        self.cleanup_retry_needed = False   # FTP-Fehler beim Cleanup → Retry im Poll-Zyklus
        self._last_restart_at = 0.0         # Zeitpunkt des zuletzt ERKANNTEN Server-Neustarts

    # ── Cleanup als Task starten (Referenz halten, Fehler loggen) ─
    def spawn_cleanup(self, delayed: bool = False):
        """Startet on_restart_detected als Task – nie fire-and-forget.
        delayed=True bei frisch erkanntem Neustart: die SHOP_-Einträge bleiben
        in der Datei, bis der Server per A2S wieder online ist (= Boot fertig,
        cfgEffectArea.json sicher eingelesen), und werden dann sofort entfernt.
        Ist der Online-Status nicht prüfbar, greift stattdessen der feste
        delivery_cleanup_delay_seconds-Fallback."""
        if delayed:
            self._last_restart_at = time.time()
        if self._cleanup_task and not self._cleanup_task.done():
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_safe(delayed))

    async def _cleanup_safe(self, delayed: bool = False):
        try:
            await self.on_restart_detected(delayed)
        except Exception as e:
            log.error(f"[SHOP] Delivery-Cleanup fehlgeschlagen: {e}")
            self.cleanup_retry_needed = True

    # ── Pfad zur cfgEffectArea.json ──────────────────────────
    def effect_area_path(self) -> Optional[str]:
        path = cfg.config.get("cfg_effect_area_path")
        if path:
            return path
        mission = cfg.config.get("ftp_mission_dir")
        if mission:
            return f"{mission.rstrip('/')}/cfgEffectArea.json"
        return None

    # ── JSON parsen (Areas-Key dynamisch, leere Datei ok) ─────
    @staticmethod
    def _parse_effect_area(raw: Optional[str]) -> Tuple[Dict, str]:
        """Gibt (Daten, Areas-Key) zurück. Fehlende/leere Datei → Grundstruktur."""
        if not raw or not raw.strip():
            return {"Areas": [], "SafePositions": []}, "Areas"
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Wurzel-Element ist kein JSON-Objekt")
        # 1) Key 'Areas' (Groß-/Kleinschreibung egal)
        for key, val in data.items():
            if key.lower() == "areas" and isinstance(val, list):
                return data, key
        # 2) Fallback: irgendeine Liste, deren Einträge wie Areas aussehen
        for key, val in data.items():
            if isinstance(val, list) and val and isinstance(val[0], dict) and "AreaName" in val[0]:
                return data, key
        data.setdefault("Areas", [])
        return data, "Areas"

    async def _write_json(self, path: str, new_data: Dict) -> bool:
        """Schreibt die cfgEffectArea.json – OHNE Zusatzdateien im Mission-Ordner.
        Eine evtl. noch vorhandene .bak aus früheren Bot-Versionen wird entfernt."""
        loop = asyncio.get_running_loop()
        content = json.dumps(new_data, ensure_ascii=False, indent=2)
        ok = await loop.run_in_executor(None, self.bot.ftp.write_file, path, content)
        if ok:
            # Aufräumen (Best-Effort): keine .bak mehr im Mission-Ordner
            await loop.run_in_executor(None, self.bot.ftp.delete_file, path + ".bak")
        return ok

    # ── Kauf: Einträge anhängen ───────────────────────────────
    async def add_purchase_entries(self, classnames: List[str], amount: int,
                                   x: float, y: float, z: float) -> Tuple[bool, str, List[str]]:
        """Schreibt pro Stück und Classname einen Area-Eintrag (Pos=[X, Höhe, Nord]) –
        Bundles spawnen alle enthaltenen Items an derselben Koordinate.
        Gibt (ok, fehlermeldung, area_names) zurück. Erst NACH Erfolg Geld abbuchen!"""
        path = self.effect_area_path()
        if not path:
            return (False,
                    "cfgEffectArea.json path is not configured. "
                    "Run `/ftp_scan` or set `cfg_effect_area_path` in config.json.", [])
        async with self.lock:
            loop = asyncio.get_running_loop()
            raw, status = await loop.run_in_executor(None, self.bot.ftp.read_file_ex, path)
            if status == "error":
                # Inhalt unbekannt → NIE mit leerer Grundstruktur überschreiben,
                # sonst gehen Vanilla-Zonen + andere pending-Käufe verloren
                return (False,
                        "FTP read of `cfgEffectArea.json` failed – purchase cancelled, "
                        "nothing was charged. Please try again in a moment.", [])
            try:
                data, areas_key = self._parse_effect_area(raw)
            except Exception as e:
                return False, f"Could not parse cfgEffectArea.json: `{e}`", []
            try:
                radius = float(cfg.config.get("default_radius", 1))
            except (TypeError, ValueError):
                radius = 1.0
            if radius.is_integer():
                radius = int(radius)   # "Radius": 1 statt 1.0 – exakt wie das Referenz-Format
            names: List[str] = []
            for _ in range(amount):
                for cn in classnames:
                    name = f"{self.AREA_PREFIX}{uuid.uuid4().hex}"
                    names.append(name)
                    data[areas_key].append({
                        "AreaName": name,
                        "Type": cn,
                        "Data": {"Pos": [float(x), float(y), float(z)], "Radius": radius},
                    })
            ok = await self._write_json(path, data)
            if not ok:
                return False, "FTP write failed – purchase cancelled, nothing was charged.", []
            return True, "", names

    # ── Cleanup: Einträge nach Auslieferung entfernen ─────────
    async def remove_area_entries(self, area_names: List[str]) -> bool:
        """Entfernt Einträge aus cfgEffectArea.json (verhindert Respawn bei jedem Neustart)."""
        if not area_names:
            return True   # nichts zu entfernen → Erfolg (sonst hängen Käufe ewig auf pending)
        path = self.effect_area_path()
        if not path:
            return False
        wanted = set(area_names)
        async with self.lock:
            loop = asyncio.get_running_loop()
            raw, status = await loop.run_in_executor(None, self.bot.ftp.read_file_ex, path)
            if status == "error":
                # Lesefehler ≠ leere Datei: sonst würden Käufe als geliefert
                # markiert, obwohl die Einträge noch drinstehen (Dauer-Respawn)
                log.error("[SHOP] Cleanup: cfgEffectArea.json nicht lesbar (FTP) – Retry folgt.")
                return False
            try:
                data, areas_key = self._parse_effect_area(raw)
            except Exception as e:
                log.error(f"[SHOP] Cleanup: Parse-Fehler in cfgEffectArea.json: {e}")
                return False
            before = len(data[areas_key])
            data[areas_key] = [a for a in data[areas_key]
                               if a.get("AreaName") not in wanted]
            if len(data[areas_key]) == before:
                return True   # nichts (mehr) enthalten → trotzdem Erfolg
            return await self._write_json(path, data)

    # ── Verwaiste SHOP_-Einträge entfernen (Selbstheilung) ────
    async def sweep_orphans(self) -> int:
        """Entfernt alle SHOP_-Einträge, die zu KEINEM pending-Kauf gehören
        (entstehen z. B. durch fehlgeschlagenen Rollback). Gibt die Anzahl
        entfernter Einträge zurück, -1 bei FTP-/Parse-Fehler."""
        path = self.effect_area_path()
        if not path:
            return -1
        valid: set = set()
        for r in db.pending_purchases():
            try:
                valid.update(json.loads(r["area_names"] or "[]"))
            except Exception:
                pass
        async with self.lock:
            loop = asyncio.get_running_loop()
            raw, status = await loop.run_in_executor(None, self.bot.ftp.read_file_ex, path)
            if status == "error":
                log.error("[SHOP] Orphan-Sweep: cfgEffectArea.json nicht lesbar (FTP).")
                return -1
            try:
                data, areas_key = self._parse_effect_area(raw)
            except Exception as e:
                log.error(f"[SHOP] Orphan-Sweep: Parse-Fehler in cfgEffectArea.json: {e}")
                return -1
            keep: List[Dict] = []
            removed = 0
            for a in data[areas_key]:
                name = str(a.get("AreaName", ""))
                if name.startswith(self.AREA_PREFIX) and name not in valid:
                    removed += 1
                else:
                    keep.append(a)
            if removed == 0:
                return 0
            data[areas_key] = keep
            ok = await self._write_json(path, data)
            return removed if ok else -1

    # ── Diagnose + Self-Heal (Basis für /shop check) ──────────
    async def check_and_heal(self) -> Dict:
        """Prüft Pfad, Lesbarkeit und JSON-Struktur der cfgEffectArea.json und
        trägt fehlende Einträge offener Käufe wieder ein (Self-Heal, z. B.
        nachdem die Datei extern überschrieben wurde). Gibt einen Report zurück."""
        report: Dict = {"path": self.effect_area_path(),
                        "last_restart_at": self._last_restart_at}
        path = report["path"]
        if not path:
            report["status"] = "no_path"
            return report
        pending = db.pending_purchases()
        report["pending"] = len(pending)
        async with self.lock:
            loop = asyncio.get_running_loop()
            raw, status = await loop.run_in_executor(None, self.bot.ftp.read_file_ex, path)
            report["status"] = status
            if status == "error":
                return report
            try:
                data, areas_key = self._parse_effect_area(raw)
            except Exception as e:
                report["status"] = "parse_error"
                report["error"] = str(e)
                return report
            areas = data[areas_key]
            present = {str(a.get("AreaName", "")) for a in areas}
            shop_n = sum(1 for n in present if n.startswith(self.AREA_PREFIX))
            report["areas_total"]     = len(areas)
            report["shop_entries"]    = shop_n
            report["vanilla_entries"] = len(areas) - shop_n
            try:
                radius = float(cfg.config.get("default_radius", 1))
            except (TypeError, ValueError):
                radius = 1.0
            if radius.is_integer():
                radius = int(radius)
            healed_ids: List[int] = []
            healed_entries = 0
            for r in pending:
                try:
                    names = json.loads(r["area_names"] or "[]")
                except Exception:
                    continue
                cls_list = [c for c in str(r["classname"] or "").split("+") if c]
                if not cls_list or all(n in present for n in names):
                    continue
                # area_names wurden in der Reihenfolge Stück×Classname erzeugt →
                # Index-Mapping stellt den Classname jedes Eintrags wieder her
                for i, n in enumerate(names):
                    if n in present:
                        continue
                    areas.append({
                        "AreaName": n,
                        "Type": cls_list[i % len(cls_list)],
                        "Data": {"Pos": [float(r["x"]), float(r["y"]), float(r["z"])],
                                 "Radius": radius},
                    })
                    present.add(n)
                    healed_entries += 1
                healed_ids.append(int(r["id"]))
            report["healed_purchases"] = healed_ids
            report["healed_entries"]   = healed_entries
            if healed_entries:
                report["heal_written"] = await self._write_json(path, data)
        return report

    # ── Auto-Restart (entprellt) ──────────────────────────────
    def schedule_auto_restart(self):
        """Startet den Restart-Timer, falls noch keiner läuft.
        Käufe innerhalb restart_cooldown_seconds werden gesammelt."""
        if self._restart_task and not self._restart_task.done():
            return
        self._restart_task = asyncio.create_task(self._restart_worker())

    async def _restart_worker(self):
        delay = max(5, int(cfg.config.get("restart_cooldown_seconds", 300)))
        # Mindestabstand zum vorherigen Auto-Restart erzwingen (Server bootet evtl. noch)
        wait = max(delay, (self._last_restart_ts + delay) - time.time())
        log.info(f"[SHOP] Auto-Restart in {int(wait)}s geplant (Käufe werden gesammelt).")
        await asyncio.sleep(wait)
        self._last_restart_ts = time.time()
        try:
            ok, msg = await self.bot.nitrado.restart()
            log.info(f"[SHOP] Auto-Restart nach Kauf ausgelöst: ok={ok} – {msg}")
        except Exception as e:
            log.error(f"[SHOP] Auto-Restart fehlgeschlagen: {e}")

    # ── Warten bis der Server wieder online ist (A2S) ─────────
    async def _wait_for_server_online(self) -> bool:
        """Pollt den Spielserver per A2S, bis er antwortet (= wirklich online).
        True = online gesehen. False = server_ip/query_port fehlt oder Timeout
        (delivery_online_wait_max_seconds) – dann greift der feste Delay als
        Fallback, sonst würden Items bei falschem Query-Port ewig respawnen."""
        ip = str(cfg.config.get("server_ip") or "").split(":")[0].strip()
        qport = int(cfg.config.get("query_port", 0) or 0)
        if not ip or not qport:
            log.warning("[SHOP] server_ip/query_port nicht gesetzt – kann Server-online "
                        "nicht prüfen, nutze festen Delivery-Delay als Fallback.")
            return False
        max_wait = max(60, int(cfg.config.get("delivery_online_wait_max_seconds", 2700)))
        deadline = time.time() + max_wait
        loop = asyncio.get_running_loop()
        while time.time() < deadline:
            info = await loop.run_in_executor(None, a2s_query, ip, qport)
            if info:
                return True
            await asyncio.sleep(20)
        log.warning(f"[SHOP] Server nach {max_wait // 60} Min nicht per A2S erreichbar – "
                    "nutze festen Delivery-Delay als Fallback.")
        return False

    # ── Neustart erkannt (neue ADM-Datei) → ausliefern ────────
    async def on_restart_detected(self, delayed: bool = False):
        """Wird vom Log-Poller nach einem erkannten Server-Neustart aufgerufen.
        Wartet bei delayed, bis der Server per A2S wieder online ist – die neue ADM
        erscheint früh im Boot, der Server muss die cfgEffectArea.json aber erst
        vollständig einlesen (zu frühes Entfernen = Items spawnen nie). Antwortet
        der Server per A2S, ist die Mission geladen → sofort bereinigen. Nur wenn
        der Online-Status nicht prüfbar ist, greift delivery_cleanup_delay_seconds
        als fester Fallback-Delay. Danach werden hinreichend alte pending-Käufe
        geliefert und die Datei bereinigt."""
        self.cleanup_retry_needed = False
        grace = int(cfg.config.get("delivery_grace_seconds", 90))
        poll  = int(cfg.config.get("log_poll_interval_seconds", 10))
        # Grace muss über dem Poll-Intervall liegen, sonst könnte ein Kauf, der NACH
        # dem Restart einging, fälschlich als geliefert gelten (bezahlt, nie gespawnt)
        grace = max(grace, poll + 30)
        # Cutoff am ERKENNUNGS-Zeitpunkt festmachen: Käufe, die während der
        # Wartezeit oder eines Retrys eingehen, sind noch nicht gespawnt und
        # dürfen nicht als geliefert markiert werden
        restart_at = self._last_restart_at or time.time()
        cutoff = restart_at - grace
        rows = db.pending_purchases(created_before=cutoff)
        if not rows:
            return
        if delayed:
            delay = max(0, int(cfg.config.get("delivery_cleanup_delay_seconds", 600)))
            log.info(f"[SHOP] Server-Neustart erkannt – warte bis der Server wieder online "
                     f"ist, danach werden {len(rows)} Lieferung(en) sofort abgeschlossen.")
            while True:
                seen = self._last_restart_at   # Stand vor dem Warten
                online = await self._wait_for_server_online()
                if online:
                    # Server antwortet per A2S → Mission (inkl. cfgEffectArea.json)
                    # ist geladen, Items sind gespawnt → Einträge sofort entfernen
                    log.info("[SHOP] Server ist wieder online – SHOP_-Einträge werden "
                             "jetzt sofort entfernt.")
                elif delay:
                    # Online-Status nicht prüfbar (keine server_ip/query_port oder
                    # A2S-Timeout) → fester Delay als Sicherheits-Fallback, sonst
                    # könnten die Einträge entfernt werden, bevor der Server die
                    # Datei eingelesen hat (Item spawnt nie)
                    log.info(f"[SHOP] Server-online nicht prüfbar – Fallback: warte "
                             f"{delay // 60} Min festen Delay vor dem Entfernen.")
                    await asyncio.sleep(delay)
                # Neuer Restart während des Wartens erkannt? spawn_cleanup startet
                # keinen zweiten Task, solange dieser läuft → hier von vorn warten,
                # sonst würden die Einträge mitten im nächsten Boot entfernt.
                if self._last_restart_at <= seen:
                    break
                log.info("[SHOP] Erneuter Server-Neustart während der Wartezeit erkannt – "
                         "warte erneut auf Server-online.")
        ids:   List[int] = []
        names: List[str] = []
        for r in rows:
            ids.append(int(r["id"]))
            try:
                names.extend(json.loads(r["area_names"] or "[]"))
            except Exception:
                pass
        log.info(f"[SHOP] Liefere {len(ids)} Kauf/Käufe aus (Einträge werden entfernt).")
        ok = await self.remove_area_entries(names)
        if not ok:
            self.cleanup_retry_needed = True
            log.error("[SHOP] cfgEffectArea.json konnte nicht bereinigt werden – "
                      "automatischer neuer Versuch beim nächsten Poll-Zyklus.")
            for warn_gid in {int(r["guild_id"]) for r in rows}:
                warn = discord.Embed(
                    title="⚠️ Delivery cleanup failed",
                    description=("Could not remove delivered `SHOP_` entries from "
                                 "`cfgEffectArea.json` (FTP error). Items would respawn on "
                                 "every restart. The bot retries automatically – admins can "
                                 "also run `/shop cleanup`."),
                    color=0xE67E22)
                await _post_feed(warn_gid, "shop_log", warn)
            return
        db.mark_delivered(ids)
        for r in rows:
            embed = discord.Embed(
                title="📦 DELIVERED",
                description=(f"**{r['amount']}× {r['item_name']}** for <@{r['user_id']}> "
                             f"spawned after the server restart."),
                color=0x2ECC71)
            embed.set_footer(text=f"Purchase #{r['id']}")
            await _post_feed(int(r["guild_id"]), "shop_log", embed)


# ══════════════════════════════════════════════════════════════
#  ECONOMY-COMMANDS – /work /daily /beg
# ══════════════════════════════════════════════════════════════
WORK_FLAVOR = [
    "You fixed a stranger's car engine and earned {amount}.",
    "You chopped firewood for a trader camp – {amount} earned.",
    "You escorted a fresh spawn safely across the map and got {amount}.",
    "You sold hand-made fishing rods at the market for {amount}.",
    "You repaired the town water pump – the mayor paid you {amount}.",
    "You hunted deer and sold the pelts for {amount}.",
    "You cleared the zombies off a farm – the owner paid {amount}.",
    "You worked a night shift at the docks and earned {amount}.",
    "You guided a group through the military zone and were paid {amount}.",
    "You patched up bullet wounds as a field medic – {amount} earned.",
]

BEG_SUCCESS = [
    "A kind survivor tossed you {amount}.",
    "You found {amount} in an old jacket by the road.",
    "A trader felt sorry for you and gave you {amount}.",
    "Someone left {amount} in a rusty can – lucky you.",
]

BEG_FAIL = [
    "People just walked past you. Nothing earned.",
    "A zombie chased you away before anyone could help.",
    "You got laughed at. No money this time.",
    "Someone threw a rotten fruit at you instead of money.",
]

async def _require_guild(interaction: discord.Interaction) -> bool:
    """Economy/Shop funktionieren nur in einer Guild (Salden sind pro Guild)."""
    if interaction.guild_id:
        return True
    await interaction.response.send_message(
        "❌ This command only works inside a server.", ephemeral=True)
    return False


@bot.tree.command(name="work", description="💼 Work a job and earn some money")
async def cmd_work(interaction: discord.Interaction):
    if not await _require_guild(interaction):
        return
    conf = cfg.config.get("economy", {}).get("work", {})
    gid, uid = interaction.guild_id, interaction.user.id

    remaining = db.cooldown_remaining(gid, uid, "work")
    if remaining > 0:
        return await interaction.response.send_message(
            embed=_cooldown_embed("/work", remaining), ephemeral=True)

    lo, hi = int(conf.get("min", 50)), int(conf.get("max", 150))
    amount = random.randint(min(lo, hi), max(lo, hi))
    wallet, _bank = db.add_wallet(gid, uid, amount)
    db.set_cooldown(gid, uid, "work", int(conf.get("cooldown_seconds", 3600)))

    embed = discord.Embed(
        title="💼 Work complete",
        description=random.choice(WORK_FLAVOR).format(amount=f"**{_fmt_money(amount)}**"),
        color=0x2ECC71)
    embed.set_footer(text=f"Wallet: {_fmt_money(wallet)}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="daily", description="📅 Claim your daily bonus")
async def cmd_daily(interaction: discord.Interaction):
    if not await _require_guild(interaction):
        return
    conf = cfg.config.get("economy", {}).get("daily", {})
    gid, uid = interaction.guild_id, interaction.user.id

    remaining = db.cooldown_remaining(gid, uid, "daily")
    if remaining > 0:
        return await interaction.response.send_message(
            embed=_cooldown_embed("/daily", remaining), ephemeral=True)

    # amount fest ODER min/max-Bereich – beides erlaubt
    if "min" in conf and "max" in conf:
        lo, hi = int(conf["min"]), int(conf["max"])
        amount = random.randint(min(lo, hi), max(lo, hi))
    else:
        amount = int(conf.get("amount", 300))
    wallet, _bank = db.add_wallet(gid, uid, amount)
    db.set_cooldown(gid, uid, "daily", int(conf.get("cooldown_seconds", 86400)))

    embed = discord.Embed(
        title="📅 Daily bonus",
        description=f"You claimed your daily bonus of **{_fmt_money(amount)}**!",
        color=0x2ECC71)
    embed.set_footer(text=f"Wallet: {_fmt_money(wallet)}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="beg", description="🥺 Beg for a little money – might fail")
async def cmd_beg(interaction: discord.Interaction):
    if not await _require_guild(interaction):
        return
    conf = cfg.config.get("economy", {}).get("beg", {})
    gid, uid = interaction.guild_id, interaction.user.id

    remaining = db.cooldown_remaining(gid, uid, "beg")
    if remaining > 0:
        return await interaction.response.send_message(
            embed=_cooldown_embed("/beg", remaining), ephemeral=True)

    db.set_cooldown(gid, uid, "beg", int(conf.get("cooldown_seconds", 300)))

    if random.random() < float(conf.get("fail_chance", 0.35)):
        embed = discord.Embed(
            title="🥺 Begging failed",
            description=random.choice(BEG_FAIL),
            color=0xE74C3C)
        return await interaction.response.send_message(embed=embed)

    lo, hi = int(conf.get("min", 5)), int(conf.get("max", 50))
    amount = random.randint(min(lo, hi), max(lo, hi))
    wallet, _bank = db.add_wallet(gid, uid, amount)

    embed = discord.Embed(
        title="🥺 Begging paid off",
        description=random.choice(BEG_SUCCESS).format(amount=f"**{_fmt_money(amount)}**"),
        color=0x2ECC71)
    embed.set_footer(text=f"Wallet: {_fmt_money(wallet)}")
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════
#  BANK-COMMANDS – /balance /deposit /withdraw
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="balance", description="💳 Show wallet & bank balance")
@app_commands.describe(user="Another member (optional – leave empty for yourself)")
async def cmd_balance(interaction: discord.Interaction,
                      user: Optional[discord.Member] = None):
    if not await _require_guild(interaction):
        return
    target = user or interaction.user
    wallet, bank = db.get_balance(interaction.guild_id, target.id)

    embed = discord.Embed(
        title=f"💳 Balance – {target.display_name}",
        color=0x5865F2)
    embed.add_field(name="👛 Wallet", value=_fmt_money(wallet),        inline=True)
    embed.add_field(name="🏦 Bank",   value=_fmt_money(bank),          inline=True)
    embed.add_field(name="Σ Total",   value=_fmt_money(wallet + bank), inline=True)
    if target.display_avatar:
        embed.set_thumbnail(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="deposit", description="🏦 Move money from wallet to bank")
@app_commands.describe(amount="Amount to deposit (leave empty = everything)")
async def cmd_deposit(interaction: discord.Interaction,
                      amount: Optional[app_commands.Range[int, 1]] = None):
    if not await _require_guild(interaction):
        return
    moved, wallet, bank = db.deposit(interaction.guild_id, interaction.user.id, amount)
    if moved <= 0:
        return await interaction.response.send_message(
            "❌ Nothing to deposit – your wallet is empty.", ephemeral=True)
    embed = discord.Embed(
        title="🏦 Deposit successful",
        description=f"Moved **{_fmt_money(moved)}** into your bank.",
        color=0x2ECC71)
    embed.add_field(name="👛 Wallet", value=_fmt_money(wallet), inline=True)
    embed.add_field(name="🏦 Bank",   value=_fmt_money(bank),   inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="withdraw", description="👛 Move money from bank to wallet")
@app_commands.describe(amount="Amount to withdraw (leave empty = everything)")
async def cmd_withdraw(interaction: discord.Interaction,
                       amount: Optional[app_commands.Range[int, 1]] = None):
    if not await _require_guild(interaction):
        return
    moved, wallet, bank = db.withdraw(interaction.guild_id, interaction.user.id, amount)
    if moved <= 0:
        return await interaction.response.send_message(
            "❌ Nothing to withdraw – your bank is empty.", ephemeral=True)
    embed = discord.Embed(
        title="👛 Withdraw successful",
        description=f"Moved **{_fmt_money(moved)}** into your wallet.",
        color=0x2ECC71)
    embed.add_field(name="👛 Wallet", value=_fmt_money(wallet), inline=True)
    embed.add_field(name="🏦 Bank",   value=_fmt_money(bank),   inline=True)
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════
#  ECONOMY-ADMIN-COMMANDS – /addmoney /removemoney /setbalance
# ══════════════════════════════════════════════════════════════
async def _post_economy_admin_log(interaction: discord.Interaction, title: str,
                                  target: discord.Member, amount_text: str,
                                  wallet: int, color: int):
    """Jede Admin-Geldaktion in den economy_log-Feed posten."""
    embed = discord.Embed(
        title=title,
        description=(f"**{interaction.user.display_name}** → {target.mention}\n"
                     f"Amount: **{amount_text}**"),
        color=color)
    embed.set_footer(text=f"New wallet: {_fmt_money(wallet)}")
    await _post_feed(interaction.guild_id, "economy_log", embed)


@bot.tree.command(name="addmoney", description="💰 Add money to a member's wallet (admin)")
@app_commands.describe(user="Member who receives the money", amount="Amount to add")
async def cmd_addmoney(interaction: discord.Interaction,
                       user: discord.Member, amount: app_commands.Range[int, 1]):
    if not _is_economy_admin(interaction):
        return await _deny(interaction)
    wallet, _bank = db.add_wallet(interaction.guild_id, user.id, int(amount))
    embed = discord.Embed(
        title="💰 Money added",
        description=f"Added **{_fmt_money(amount)}** to {user.mention}'s wallet.",
        color=0x2ECC71)
    embed.set_footer(text=f"New wallet: {_fmt_money(wallet)}")
    await interaction.response.send_message(embed=embed)
    await _post_economy_admin_log(interaction, "💰 ADMIN: ADD MONEY",
                                  user, f"+{_fmt_money(amount)}", wallet, 0x2ECC71)


@bot.tree.command(name="removemoney", description="💸 Remove money from a member's wallet (admin)")
@app_commands.describe(user="Member to remove money from", amount="Amount to remove")
async def cmd_removemoney(interaction: discord.Interaction,
                          user: discord.Member, amount: app_commands.Range[int, 1]):
    if not _is_economy_admin(interaction):
        return await _deny(interaction)
    old_wallet, _ = db.get_balance(interaction.guild_id, user.id)
    wallet, _bank = db.add_wallet(interaction.guild_id, user.id, -int(amount))
    removed = old_wallet - wallet   # nie unter 0 → tatsächlich abgezogener Betrag
    embed = discord.Embed(
        title="💸 Money removed",
        description=f"Removed **{_fmt_money(removed)}** from {user.mention}'s wallet.",
        color=0xE67E22)
    embed.set_footer(text=f"New wallet: {_fmt_money(wallet)}")
    await interaction.response.send_message(embed=embed)
    await _post_economy_admin_log(interaction, "💸 ADMIN: REMOVE MONEY",
                                  user, f"-{_fmt_money(removed)}", wallet, 0xE67E22)


@bot.tree.command(name="setbalance", description="🎯 Set a member's wallet to an exact amount (admin)")
@app_commands.describe(user="Member", amount="New wallet amount")
async def cmd_setbalance(interaction: discord.Interaction,
                         user: discord.Member, amount: app_commands.Range[int, 0]):
    if not _is_economy_admin(interaction):
        return await _deny(interaction)
    wallet, _bank = db.set_wallet(interaction.guild_id, user.id, int(amount))
    embed = discord.Embed(
        title="🎯 Balance set",
        description=f"{user.mention}'s wallet is now **{_fmt_money(wallet)}**.",
        color=0x5865F2)
    await interaction.response.send_message(embed=embed)
    await _post_economy_admin_log(interaction, "🎯 ADMIN: SET BALANCE",
                                  user, _fmt_money(wallet), wallet, 0x5865F2)


@bot.tree.command(name="economy_reload",
                  description="🔄 Reload config.json (shop/economy/casino) without restarting the bot")
async def cmd_economy_reload(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    ok = cfg.reload_config()
    if ok:
        catalog.load()   # Katalog (shop_items.json bzw. config-Fallback) mit neu laden
        items = [i for i in catalog.items if i.get("enabled", True)]
        embed = discord.Embed(
            title="🔄 Config reloaded",
            description=(f"`config.json` was reloaded successfully.\n"
                         f"Catalog: **{len(items)}** active items from `{catalog.source}` · "
                         f"Currency: **{cfg.config.get('currency_name', '?')} ({_cur_symbol()})**"),
            color=0x2ECC71)
    else:
        embed = discord.Embed(
            title="❌ Reload failed",
            description="Could not parse `config.json` – check the bot log / JSON syntax.",
            color=0xE74C3C)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  KILL-STATS / LINK / BOUNTY / PAY
# ══════════════════════════════════════════════════════════════
async def _player_name_ac(interaction: discord.Interaction,
                          current: str) -> List[app_commands.Choice[str]]:
    """Autocomplete: bekannte Spielernamen aus Kills + Sitzungen."""
    loop = asyncio.get_running_loop()
    try:
        names = await loop.run_in_executor(None, db.known_player_names, current, 25)
    except Exception:
        names = []
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names[:25]]


@bot.tree.command(name="stats", description="📊 Kill-Statistiken eines Spielers (Kills, Tode, K/D, Waffe)")
@app_commands.describe(spieler="Ingame-/PlayStation-Name")
@app_commands.autocomplete(spieler=_player_name_ac)
async def cmd_stats(interaction: discord.Interaction, spieler: str):
    st = db.player_stats(spieler.strip())
    if not st:
        return await interaction.response.send_message(
            f"❌ Keine PvP-Daten für **{spieler}** gefunden. Statistiken werden "
            f"ab jetzt automatisch aus dem Killfeed aufgezeichnet.", ephemeral=True)
    e = discord.Embed(title=f"📊 Statistiken – {spieler}", color=0x5865F2)
    e.add_field(name="☠️ Kills", value=str(st["kills"]), inline=True)
    e.add_field(name="💀 Tode",  value=str(st["deaths"]), inline=True)
    e.add_field(name="⚖️ K/D",   value=f"{st['kd']:.2f}", inline=True)
    e.add_field(name="🔫 Lieblingswaffe",
                value=(f"{st['fav_weapon']} ({st['fav_weapon_kills']} Kills)"
                       if st["fav_weapon"] else "–"), inline=True)
    e.add_field(name="🎯 Weitester Kill",
                value=(f"{st['longest']:.0f} m" if st["longest"] else "–"), inline=True)
    if interaction.guild_id:
        links = [lk for lk in db.links_for_name(spieler.strip())
                 if int(lk["guild_id"]) == interaction.guild_id]
        if links:
            e.add_field(name="🔗 Verknüpft mit",
                        value=f"<@{int(links[0]['user_id'])}>", inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name="leaderboard", description="🏆 Top 10 PvP-Killer des Servers")
async def cmd_leaderboard(interaction: discord.Interaction):
    rows = db.leaderboard(10)
    if not rows:
        return await interaction.response.send_message(
            "❌ Noch keine PvP-Kills aufgezeichnet – das Leaderboard füllt sich "
            "automatisch aus dem Killfeed.", ephemeral=True)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, r in enumerate(rows):
        rank = medals[i] if i < 3 else f"`#{i + 1}`"
        best = f" · 🎯 {r['best']:.0f} m" if r["best"] else ""
        lines.append(f"{rank} **{r['name']}** – {r['kills']} Kills · "
                     f"{r['deaths']} Tode · K/D {r['kd']:.2f}{best}")
    e = discord.Embed(title="🏆 Kill-Leaderboard", description="\n".join(lines),
                      color=0xF1C40F)
    e.set_footer(text="Automatisch aus dem Killfeed · /stats <spieler> für Details")
    await interaction.response.send_message(embed=e)


def _seen_in_logs(name: str, max_age_seconds: int = 900) -> Optional[Dict]:
    """Prüft, ob der Spieler kürzlich in den ADM-Logs auftauchte (Positions-Tracking
    des Parsers). Gibt den Eintrag (mit 'id') zurück, sonst None."""
    target = name.lower()
    now = datetime.now(timezone.utc)
    for pname, info in list(DayZLogParser.player_positions.items()):
        if pname.lower() != target:
            continue
        try:
            seen = datetime.fromisoformat(str(info.get("last_seen", "")))
        except ValueError:
            return None
        return info if (now - seen).total_seconds() <= max_age_seconds else None
    return None


@bot.tree.command(name="link", description="🔗 Verknüpft deinen Discord-Account mit deinem PlayStation-Namen")
@app_commands.describe(playstation_name="Dein Ingame-Name, exakt wie im Spiel")
@app_commands.autocomplete(playstation_name=_player_name_ac)
async def cmd_link(interaction: discord.Interaction, playstation_name: str):
    if not await _require_guild(interaction):
        return
    name = playstation_name.strip()
    if not name or len(name) > 64:
        return await interaction.response.send_message(
            "❌ Ungültiger Name.", ephemeral=True)
    existing = db.get_link_by_user(interaction.guild_id, interaction.user.id)
    if existing:
        old_name = str(existing["ingame_name"])
        if old_name.lower() == name.lower():
            return await interaction.response.send_message(
                f"✅ Du bist bereits mit **{old_name}** verbunden.", ephemeral=True)
        return await interaction.response.send_message(
            f"❌ Du bist bereits mit **{old_name}** verbunden – nutze zuerst `/unlink`, "
            f"um den Namen zu wechseln.", ephemeral=True)
    ok, _why = db.link_user(interaction.guild_id, interaction.user.id, name)
    if not ok:
        return await interaction.response.send_message(
            f"❌ **{name}** ist bereits mit einem anderen Discord-Account verknüpft. "
            f"Ein Admin kann das mit `/forcelink` korrigieren.", ephemeral=True)
    # Logs nach dem PSN-Namen prüfen: Ist der Spieler gerade auf dem Server,
    # startet der Spielzeit-Zähler sofort (kein neues Connect-Event nötig)
    seen = _seen_in_logs(name)
    if seen:
        if seen.get("id"):
            db.update_link_id(name, str(seen["id"]))
        if not db.has_session(name):
            db.open_session(name, seen.get("id"))
        online_line = "\n🟢 Du bist gerade auf dem Server – der Spielzeit-Zähler läuft ab jetzt!"
    else:
        online_line = ("\nℹ️ Aktuell nicht in den Logs gesehen – der Spielzeit-Zähler "
                       "startet bei deinem nächsten Connect.")
    reward   = int(cfg.config.get("kill_reward", 0))
    pt       = cfg.config.get("playtime_reward") or {}
    pt_line  = (f"\n⏱️ Spielzeit: **{_fmt_money(int(pt.get('amount', 0)))}** pro "
                f"**{int(pt.get('interval_minutes', 30))} Min** auf dem Server"
                if int(pt.get("amount", 0)) > 0 else "")
    e = discord.Embed(
        title="🔗 Account verknüpft",
        description=(f"{interaction.user.mention} ↔ **{name}**\n"
                     f"☠️ Pro PvP-Kill: **{_fmt_money(reward)}**{pt_line}{online_line}"),
        color=0x2ECC71)
    await interaction.response.send_message(embed=e)
    note = discord.Embed(
        title="🔗 /link verwendet",
        description=f"{interaction.user.mention} (`{interaction.user}`) hat sich mit **{name}** verknüpft.",
        color=0x2ECC71)
    await _notify_link_change(interaction.guild_id, note)


@bot.tree.command(name="unlink", description="🔓 Entfernt deine eigene Ingame-Verknüpfung")
async def cmd_unlink(interaction: discord.Interaction):
    if not await _require_guild(interaction):
        return
    old = db.unlink_user(interaction.guild_id, interaction.user.id)
    if not old:
        return await interaction.response.send_message(
            "❌ Du bist mit keinem Ingame-Namen verknüpft.", ephemeral=True)
    await interaction.response.send_message(
        f"🔓 Verknüpfung mit **{old}** entfernt.", ephemeral=True)
    note = discord.Embed(
        title="🔓 /unlink verwendet",
        description=f"{interaction.user.mention} (`{interaction.user}`) hat die Verknüpfung mit **{old}** entfernt.",
        color=0xE67E22)
    await _notify_link_change(interaction.guild_id, note)


@bot.tree.command(name="forcelink", description="🔗 (Admin) Verknüpft einen Spieler mit einem Discord-Account")
@app_commands.describe(playstation_name="Ingame-Name des Spielers",
                       user="Discord-Mitglied")
@app_commands.autocomplete(playstation_name=_player_name_ac)
async def cmd_forcelink(interaction: discord.Interaction,
                        playstation_name: str, user: discord.Member):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_guild(interaction):
        return
    name = playstation_name.strip()
    # Bestehende Verknüpfung dieses Namens (anderer User) lösen
    for lk in db.links_for_name(name):
        if int(lk["guild_id"]) == interaction.guild_id and int(lk["user_id"]) != user.id:
            db.unlink_user(interaction.guild_id, int(lk["user_id"]))
    db.link_user(interaction.guild_id, user.id, name)
    await interaction.response.send_message(
        f"🔗 **{name}** ↔ {user.mention} verknüpft (Admin).", ephemeral=True)
    note = discord.Embed(
        title="🔗 /forcelink verwendet",
        description=(f"{interaction.user.mention} hat {user.mention} "
                     f"mit **{name}** verknüpft."),
        color=0x2ECC71)
    await _notify_link_change(interaction.guild_id, note)


@bot.tree.command(name="forceunlink", description="🔓 (Admin) Entfernt die Verknüpfung eines Discord-Accounts")
@app_commands.describe(user="Discord-Mitglied")
async def cmd_forceunlink(interaction: discord.Interaction, user: discord.Member):
    if not _is_admin(interaction):
        return await _deny(interaction)
    if not await _require_guild(interaction):
        return
    old = db.unlink_user(interaction.guild_id, user.id)
    if not old:
        return await interaction.response.send_message(
            f"❌ {user.mention} ist mit keinem Ingame-Namen verknüpft.", ephemeral=True)
    await interaction.response.send_message(
        f"🔓 Verknüpfung {user.mention} ↔ **{old}** entfernt (Admin).", ephemeral=True)
    note = discord.Embed(
        title="🔓 /forceunlink verwendet",
        description=(f"{interaction.user.mention} hat die Verknüpfung "
                     f"{user.mention} ↔ **{old}** entfernt."),
        color=0xE67E22)
    await _notify_link_change(interaction.guild_id, note)


username_group = app_commands.Group(name="username",
                                    description="🔗 Verknüpfte PSN-Namen verwalten")


@username_group.command(name="list", description="📋 Zeigt deine verknüpften PSN-Namen (Admins: alle)")
async def username_list(interaction: discord.Interaction):
    if not await _require_guild(interaction):
        return
    if not _is_admin(interaction):
        # Normale Nutzer sehen nur die eigene Verknüpfung
        own = db.get_link_by_user(interaction.guild_id, interaction.user.id)
        if not own:
            return await interaction.response.send_message(
                "ℹ️ Du bist mit keinem PSN-Namen verknüpft. Nutze `/link <psn-name>`.",
                ephemeral=True)
        name   = str(own["ingame_name"])
        online = "🟢 " if db.has_session(name) else "⚫ "
        e = discord.Embed(
            title="🔗 Deine Verknüpfung",
            description=f"{online}**{name}** ↔ {interaction.user.mention}",
            color=0x5865F2)
        e.set_footer(text="🟢 = gerade auf dem Server · Admins sehen die vollständige Liste")
        return await interaction.response.send_message(embed=e, ephemeral=True)
    rows = db.list_links(interaction.guild_id)
    if not rows:
        return await interaction.response.send_message(
            "ℹ️ Noch keine Verknüpfungen vorhanden. Spieler verbinden sich mit "
            "`/link <psn-name>`.", ephemeral=True)
    lines = []
    for r in rows[:50]:
        online = "🟢 " if db.has_session(str(r["ingame_name"])) else "⚫ "
        lines.append(f"{online}**{r['ingame_name']}** ↔ <@{int(r['user_id'])}>")
    e = discord.Embed(
        title=f"🔗 Verknüpfte PSN-Namen ({len(rows)})",
        description="\n".join(lines),
        color=0x5865F2)
    e.set_footer(text="🟢 = gerade auf dem Server (offene Spielzeit-Sitzung)"
                      + (f" · … und {len(rows) - 50} weitere" if len(rows) > 50 else ""))
    await interaction.response.send_message(embed=e, ephemeral=True)


bot.tree.add_command(username_group)


@bot.tree.command(name="bounty", description="🎯 Setzt ein Kopfgeld auf einen Spieler aus (sofort abgebucht)")
@app_commands.describe(spieler="Ingame-Name des Ziels", betrag="Kopfgeld aus deinem Wallet")
@app_commands.autocomplete(spieler=_player_name_ac)
async def cmd_bounty(interaction: discord.Interaction,
                     spieler: str, betrag: app_commands.Range[int, 1]):
    if not await _require_guild(interaction):
        return
    name = spieler.strip()
    own = db.get_link_by_user(interaction.guild_id, interaction.user.id)
    if own and str(own["ingame_name"]).lower() == name.lower():
        return await interaction.response.send_message(
            "❌ Auf deinen eigenen Kopf kannst du kein Kopfgeld aussetzen.", ephemeral=True)
    bconf   = cfg.config.get("bounty", {})
    min_amt = int(bconf.get("min_amount", 100))
    max_amt = int(bconf.get("max_amount", 10000))
    if not (min_amt <= int(betrag) <= max_amt):
        return await interaction.response.send_message(
            f"❌ Kopfgeld muss zwischen **{_fmt_money(min_amt)}** und "
            f"**{_fmt_money(max_amt)}** liegen (`bounty` in config.json).", ephemeral=True)
    remaining = db.cooldown_remaining(interaction.guild_id, interaction.user.id, "bounty")
    if remaining > 0:
        return await interaction.response.send_message(
            embed=_cooldown_embed("/bounty", remaining), ephemeral=True)
    if not db.try_spend_wallet(interaction.guild_id, interaction.user.id, int(betrag)):
        wallet, _ = db.get_balance(interaction.guild_id, interaction.user.id)
        return await interaction.response.send_message(
            embed=_insufficient_embed(int(betrag), wallet), ephemeral=True)
    total = db.add_bounty(interaction.guild_id, name, int(betrag), interaction.user.id)
    db.set_cooldown(interaction.guild_id, interaction.user.id, "bounty",
                    int(bconf.get("cooldown_seconds", 300)))
    e = discord.Embed(
        title="🎯 Kopfgeld ausgesetzt",
        description=(f"**{_fmt_money(betrag)}** auf den Kopf von **{name}**!\n"
                     f"Gesamtes Kopfgeld: **{_fmt_money(total)}**\n"
                     f"Auszahlung automatisch an den (per `/link` verknüpften) Killer."),
        color=0xE67E22)
    e.set_footer(text=f"Ausgesetzt von {interaction.user.display_name}")
    await interaction.response.send_message(embed=e)


@bot.tree.command(name="bounties", description="🎯 Zeigt alle aktiven Kopfgelder")
async def cmd_bounties(interaction: discord.Interaction):
    if not await _require_guild(interaction):
        return
    rows = db.open_bounties(interaction.guild_id)
    if not rows:
        return await interaction.response.send_message(
            "✅ Keine aktiven Kopfgelder.", ephemeral=True)
    lines = [f"🎯 **{r['target_name']}** – {_fmt_money(int(r['total']))} "
             f"({int(r['n'])} Kopfgeld{'er' if int(r['n']) != 1 else ''})"
             for r in rows[:20]]
    e = discord.Embed(title="🎯 Aktive Kopfgelder", description="\n".join(lines),
                      color=0xE67E22)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name="pay", description="💸 Überweist Geld aus deinem Wallet an ein anderes Mitglied")
@app_commands.describe(user="Empfänger", betrag="Betrag aus deinem Wallet")
async def cmd_pay(interaction: discord.Interaction,
                  user: discord.Member, betrag: app_commands.Range[int, 1]):
    if not await _require_guild(interaction):
        return
    if user.id == interaction.user.id:
        return await interaction.response.send_message(
            "❌ Du kannst dir nicht selbst Geld überweisen.", ephemeral=True)
    if user.bot:
        return await interaction.response.send_message(
            "❌ Bots brauchen kein Geld.", ephemeral=True)
    if not db.try_spend_wallet(interaction.guild_id, interaction.user.id, int(betrag)):
        wallet, _ = db.get_balance(interaction.guild_id, interaction.user.id)
        return await interaction.response.send_message(
            embed=_insufficient_embed(int(betrag), wallet), ephemeral=True)
    new_wallet, _ = db.add_wallet(interaction.guild_id, user.id, int(betrag))
    e = discord.Embed(
        title="💸 Überweisung",
        description=f"{interaction.user.mention} → {user.mention}: **{_fmt_money(betrag)}**",
        color=0x2ECC71)
    await interaction.response.send_message(embed=e)
    log_embed = discord.Embed(
        title="💸 PLAYER TRANSFER",
        description=(f"**{interaction.user.display_name}** → **{user.display_name}**\n"
                     f"Betrag: **{_fmt_money(betrag)}**"),
        color=0x3498DB)
    await _post_feed(interaction.guild_id, "economy_log", log_embed)


# ══════════════════════════════════════════════════════════════
#  CASINO – /slots
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="slots", description="🎰 Spin the slot machine")
@app_commands.describe(bet="Your bet (paid from wallet)")
async def cmd_slots(interaction: discord.Interaction, bet: app_commands.Range[int, 1]):
    if not await _require_guild(interaction):
        return
    conf = cfg.config.get("casino", {}).get("slots", {})
    gid, uid = interaction.guild_id, interaction.user.id
    bet = int(bet)

    err = _validate_bet(bet, conf)
    if err:
        return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
    remaining = db.cooldown_remaining(gid, uid, "slots")
    if remaining > 0:
        return await interaction.response.send_message(
            embed=_cooldown_embed("/slots", remaining), ephemeral=True)
    if not db.try_spend_wallet(gid, uid, bet):
        wallet, _ = db.get_balance(gid, uid)
        return await interaction.response.send_message(
            embed=_insufficient_embed(bet, wallet), ephemeral=True)
    db.set_cooldown(gid, uid, "slots", int(conf.get("cooldown_seconds", 10)))

    symbols = list(conf.get("symbols", ["🍒", "🍋", "🍉", "🔔", "💎", "7️⃣"]))
    weights = list(conf.get("weights", []))
    if len(weights) != len(symbols):
        weights = [1] * len(symbols)   # Gewichte passen nicht → gleichverteilt
    reels = random.choices(symbols, weights=weights, k=3)

    payout_three = conf.get("payout_three", {})
    payout_two   = float(conf.get("payout_two", 1.5))
    if reels[0] == reels[1] == reels[2]:
        mult = float(payout_three.get(reels[0], 5))
        result = "three_of_a_kind"
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        mult = payout_two
        result = "pair"
    else:
        mult = 0.0
        result = "lose"

    payout = int(round(bet * mult))
    if payout > 0:
        db.add_wallet(gid, uid, payout)
    db.log_casino(gid, uid, "slots", bet, payout, result)
    wallet, _bank = db.get_balance(gid, uid)

    net = payout - bet
    if net > 0:
        color, headline = 0x2ECC71, f"You won **{_fmt_money(payout)}**! (net **+{net:,}**)"
    elif net == 0:
        color, headline = 0x95A5A6, "Break-even – your bet came back."
    else:
        color, headline = 0xE74C3C, f"You lost **{_fmt_money(bet)}**."

    embed = discord.Embed(
        title="🎰 Slots",
        description=f"**| {reels[0]} | {reels[1]} | {reels[2]} |**\n\n{headline}",
        color=color)
    embed.set_footer(text=f"Bet: {_fmt_money(bet)} · Wallet: {_fmt_money(wallet)}")
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════
#  CASINO – /roulette
# ══════════════════════════════════════════════════════════════
_ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
_ROULETTE_NAMED = ("red", "black", "green", "even", "odd", "low", "high")

@bot.tree.command(name="roulette",
                  description="🎡 Bet on red/black/even/odd/low/high or a single number (0-36)")
@app_commands.describe(bet="Your bet (paid from wallet)",
                       wager="red, black, green, even, odd, low, high or a number 0-36")
async def cmd_roulette(interaction: discord.Interaction,
                       bet: app_commands.Range[int, 1], wager: str):
    if not await _require_guild(interaction):
        return
    conf = cfg.config.get("casino", {}).get("roulette", {})
    gid, uid = interaction.guild_id, interaction.user.id
    bet = int(bet)

    # Wette parsen
    w = wager.strip().lower()
    number: Optional[int] = None
    if w in _ROULETTE_NAMED:
        kind = w
    elif w.isdigit() and 0 <= int(w) <= 36:
        kind, number = "number", int(w)
    else:
        return await interaction.response.send_message(
            "❌ Invalid wager. Use `red`, `black`, `green`, `even`, `odd`, `low`, `high` "
            "or a number from `0` to `36`.", ephemeral=True)

    err = _validate_bet(bet, conf)
    if err:
        return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
    remaining = db.cooldown_remaining(gid, uid, "roulette")
    if remaining > 0:
        return await interaction.response.send_message(
            embed=_cooldown_embed("/roulette", remaining), ephemeral=True)
    if not db.try_spend_wallet(gid, uid, bet):
        wallet, _ = db.get_balance(gid, uid)
        return await interaction.response.send_message(
            embed=_insufficient_embed(bet, wallet), ephemeral=True)
    db.set_cooldown(gid, uid, "roulette", int(conf.get("cooldown_seconds", 5)))

    spin = random.randint(0, 36)
    if spin == 0:
        spin_disp = "🟢 **0** (green)"
    elif spin in _ROULETTE_RED:
        spin_disp = f"🔴 **{spin}** (red)"
    else:
        spin_disp = f"⚫ **{spin}** (black)"

    # Gewinn & Auszahlungs-Multiplikator (Multiplikator = Gesamt-Rückzahlung × Einsatz)
    p_num  = float(conf.get("payout_number", 36.0))
    p_col  = float(conf.get("payout_color", 2.0))
    p_eo   = float(conf.get("payout_evenodd", 2.0))
    p_hl   = float(conf.get("payout_highlow", 2.0))
    won, mult = False, 0.0
    if kind == "number":
        won, mult = (spin == number), p_num
    elif kind == "green":
        won, mult = (spin == 0), p_num
    elif kind == "red":
        won, mult = (spin != 0 and spin in _ROULETTE_RED), p_col
    elif kind == "black":
        won, mult = (spin != 0 and spin not in _ROULETTE_RED), p_col
    elif kind == "even":
        won, mult = (spin != 0 and spin % 2 == 0), p_eo
    elif kind == "odd":
        won, mult = (spin % 2 == 1), p_eo
    elif kind == "low":
        won, mult = (1 <= spin <= 18), p_hl
    elif kind == "high":
        won, mult = (19 <= spin <= 36), p_hl

    payout = int(round(bet * mult)) if won else 0
    if payout > 0:
        db.add_wallet(gid, uid, payout)
    wager_disp = f"number {number}" if kind == "number" else kind
    db.log_casino(gid, uid, "roulette", bet, payout, f"{wager_disp}|spin={spin}")
    wallet, _bank = db.get_balance(gid, uid)

    if won:
        color = 0x2ECC71
        headline = f"You won **{_fmt_money(payout)}**! (net **+{payout - bet:,}**)"
    else:
        color = 0xE74C3C
        headline = f"You lost **{_fmt_money(bet)}**."

    embed = discord.Embed(
        title="🎡 Roulette",
        description=f"The ball landed on {spin_disp}\nYour wager: **{wager_disp}**\n\n{headline}",
        color=color)
    embed.set_footer(text=f"Bet: {_fmt_money(bet)} · Wallet: {_fmt_money(wallet)}")
    await interaction.response.send_message(embed=embed)


@cmd_roulette.autocomplete("wager")
async def _roulette_wager_ac(interaction: discord.Interaction,
                             current: str) -> List[app_commands.Choice[str]]:
    cur = current.strip().lower()
    out = [app_commands.Choice(name=o, value=o)
           for o in _ROULETTE_NAMED if (not cur) or cur in o]
    if cur.isdigit() and 0 <= int(cur) <= 36:
        out.insert(0, app_commands.Choice(name=f"number {cur}", value=cur))
    return out[:25]


# ══════════════════════════════════════════════════════════════
#  CASINO – /blackjack (spielbar mit Hit/Stand-Buttons)
# ══════════════════════════════════════════════════════════════
_BJ_RANKS: Dict[str, int] = {
    "A": 11, "K": 10, "Q": 10, "J": 10, "10": 10,
    "9": 9, "8": 8, "7": 7, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2,
}

def _bj_new_deck() -> List[str]:
    deck = [f"{rank}{suit}" for rank in _BJ_RANKS for suit in "♠♥♦♣"]
    random.shuffle(deck)
    return deck

def _bj_value(hand: List[str]) -> int:
    """Handwert mit flexiblen Assen (11 → 1 solange über 21)."""
    total, aces = 0, 0
    for card in hand:
        rank = card[:-1]
        total += _BJ_RANKS[rank]
        if rank == "A":
            aces += 1
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


class BlackjackView(discord.ui.View):
    """Interaktives Blackjack: Einsatz ist bereits abgebucht,
    Auszahlung erfolgt beim Auflösen (Win=2x, Push=1x, Blackjack=1+bonus)."""

    def __init__(self, interaction: discord.Interaction, bet: int, conf: Dict):
        super().__init__(timeout=120)
        self.user_id   = interaction.user.id
        self.guild_id  = interaction.guild_id
        self.bet       = bet
        self.payout_bj = float(conf.get("blackjack_payout", 1.5))
        self.cooldown_s = int(conf.get("cooldown_seconds", 30))
        self.deck      = _bj_new_deck()
        self.player    = [self.deck.pop(), self.deck.pop()]
        self.dealer    = [self.deck.pop(), self.deck.pop()]
        self.finished  = False
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.user_id:
            await itx.response.send_message("This is not your game.", ephemeral=True)
            return False
        return True

    def build_embed(self, reveal: bool = False, result_line: Optional[str] = None,
                    color: int = 0x5865F2) -> discord.Embed:
        dealer_hand = " ".join(self.dealer) if reveal else f"{self.dealer[0]} 🂠"
        dealer_val  = str(_bj_value(self.dealer)) if reveal else "?"
        e = discord.Embed(title="🃏 Blackjack", color=color)
        e.add_field(name=f"Your hand ({_bj_value(self.player)})",
                    value=" ".join(self.player), inline=False)
        e.add_field(name=f"Dealer ({dealer_val})", value=dealer_hand, inline=False)
        e.add_field(name="Bet", value=_fmt_money(self.bet), inline=True)
        if result_line:
            e.add_field(name="Result", value=result_line, inline=False)
        return e

    def _payout_and_log(self, mult: float, result: str) -> int:
        payout = int(round(self.bet * mult))
        if payout > 0:
            db.add_wallet(self.guild_id, self.user_id, payout)
        db.log_casino(self.guild_id, self.user_id, "blackjack", self.bet, payout, result)
        return payout

    def _dealer_play(self):
        # Dealer zieht bis mindestens 17
        while _bj_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())

    async def _finish(self, itx: Optional[discord.Interaction],
                      result: str, mult: float, color: int):
        if self.finished:
            return   # idempotent – verhindert doppelte Auszahlung bei Races
        self.finished = True
        for child in self.children:
            child.disabled = True
        payout = self._payout_and_log(mult, result)
        # Cooldown läuft ab SPIELENDE – der beim Start gesetzte wäre bei
        # längeren Partien schon abgelaufen und damit wirkungslos
        db.set_cooldown(self.guild_id, self.user_id, "blackjack", self.cooldown_s)
        wallet, _bank = db.get_balance(self.guild_id, self.user_id)
        net = payout - self.bet
        line = (f"{result}\nPayout: **{_fmt_money(payout)}** "
                f"(net **{'+' if net >= 0 else ''}{net:,}**) · Wallet: {_fmt_money(wallet)}")
        embed = self.build_embed(reveal=True, result_line=line, color=color)
        if itx is not None:
            await itx.response.edit_message(embed=embed, view=self)
        elif self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass
        self.stop()

    async def _resolve_stand(self, itx: Optional[discord.Interaction]):
        self._dealer_play()
        pv, dv = _bj_value(self.player), _bj_value(self.dealer)
        if dv > 21:
            await self._finish(itx, "Dealer busts – you win!", 2.0, 0x2ECC71)
        elif pv > dv:
            await self._finish(itx, "You win!", 2.0, 0x2ECC71)
        elif pv == dv:
            await self._finish(itx, "Push – bet returned.", 1.0, 0x95A5A6)
        else:
            await self._finish(itx, "Dealer wins.", 0.0, 0xE74C3C)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, itx: discord.Interaction, button: discord.ui.Button):
        if self.finished:   # Doppelklick-/Timeout-Race abfangen
            return await itx.response.defer()
        self.player.append(self.deck.pop())
        value = _bj_value(self.player)
        if value > 21:
            return await self._finish(itx, "Bust! You lose.", 0.0, 0xE74C3C)
        if value == 21:
            return await self._resolve_stand(itx)
        await itx.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, itx: discord.Interaction, button: discord.ui.Button):
        if self.finished:   # Doppelklick-/Timeout-Race abfangen
            return await itx.response.defer()
        await self._resolve_stand(itx)

    async def on_timeout(self):
        # Timeout = automatisch Stand, damit der Einsatz nicht verfällt
        if not self.finished:
            await self._resolve_stand(None)


@bot.tree.command(name="blackjack", description="🃏 Play blackjack against the dealer (Hit/Stand)")
@app_commands.describe(bet="Your bet (paid from wallet)")
async def cmd_blackjack(interaction: discord.Interaction, bet: app_commands.Range[int, 1]):
    if not await _require_guild(interaction):
        return
    conf = cfg.config.get("casino", {}).get("blackjack", {})
    gid, uid = interaction.guild_id, interaction.user.id
    bet = int(bet)

    err = _validate_bet(bet, conf)
    if err:
        return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
    remaining = db.cooldown_remaining(gid, uid, "blackjack")
    if remaining > 0:
        return await interaction.response.send_message(
            embed=_cooldown_embed("/blackjack", remaining), ephemeral=True)
    if not db.try_spend_wallet(gid, uid, bet):
        wallet, _ = db.get_balance(gid, uid)
        return await interaction.response.send_message(
            embed=_insufficient_embed(bet, wallet), ephemeral=True)
    db.set_cooldown(gid, uid, "blackjack", int(conf.get("cooldown_seconds", 30)))

    view = BlackjackView(interaction, bet, conf)
    pv, dv = _bj_value(view.player), _bj_value(view.dealer)

    # Natürlicher Blackjack → sofort auflösen, keine Buttons nötig
    if pv == 21 or dv == 21:
        if pv == 21 and dv == 21:
            result, mult, color = "Double blackjack – push, bet returned.", 1.0, 0x95A5A6
        elif pv == 21:
            result = f"BLACKJACK! Pays {view.payout_bj}x bonus."
            mult, color = 1.0 + view.payout_bj, 0xF1C40F
        else:
            result, mult, color = "Dealer has blackjack. You lose.", 0.0, 0xE74C3C
        payout = view._payout_and_log(mult, result)
        wallet, _bank = db.get_balance(gid, uid)
        net = payout - bet
        line = (f"{result}\nPayout: **{_fmt_money(payout)}** "
                f"(net **{'+' if net >= 0 else ''}{net:,}**) · Wallet: {_fmt_money(wallet)}")
        embed = view.build_embed(reveal=True, result_line=line, color=color)
        view.stop()
        return await interaction.response.send_message(embed=embed)

    await interaction.response.send_message(embed=view.build_embed(), view=view)
    view.message = await interaction.original_response()


# ══════════════════════════════════════════════════════════════
#  SHOP-COMMANDS – /shop list|pending|cleanup|setprice und /buy
# ══════════════════════════════════════════════════════════════
class ShopCatalog:
    """Item-Katalog: lädt bevorzugt shop_items.json (generiert aus types.xml),
    sonst shop_items aus config.json. Hält Indizes, damit Lookups und
    Autocomplete auch bei ~1700 Items schnell bleiben."""

    def __init__(self):
        self.items: List[Dict] = []
        self.source = "config.json"
        self._by_key: Dict[str, Dict] = {}              # name/classname (lower) → Item
        self.by_category: Dict[str, List[Dict]] = {}
        # (suchtext, label, value, enabled) – vorberechnet für Autocomplete
        self._ac_index: List[Tuple[str, str, str, bool]] = []

    def load(self):
        items: Optional[List[Dict]] = None
        path = str(cfg.config.get("shop_items_file") or "shop_items.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cand = data.get("items") if isinstance(data, dict) else data
                if isinstance(cand, list):
                    items, self.source = cand, path
            except Exception as e:
                log.error(f"[SHOP] {path} unlesbar ({e}) – Fallback auf config.json.")
        if items is None:
            items, self.source = list(cfg.config.get("shop_items", [])), "config.json"
        self.items = [it for it in items
                      if isinstance(it, dict) and (it.get("classname") or it.get("classnames"))]
        self.rebuild_index()
        log.info(f"[SHOP] Katalog geladen: {len(self.items)} Items aus {self.source}")

    def rebuild_index(self):
        self._by_key.clear()
        self.by_category.clear()
        self._ac_index = []
        sym = _cur_symbol()
        for it in self.items:
            cls_list = _item_classnames(it)
            if not cls_list:
                continue
            is_bundle = len(cls_list) > 1
            name = str(it.get("name") or cls_list[0])
            self._by_key.setdefault(name.lower(), it)
            if not is_bundle:
                # Classname nur für Einzelitems als Key – Bundles würden echte Items verdecken
                self._by_key.setdefault(cls_list[0].lower(), it)
            self.by_category.setdefault(str(it.get("category", "Misc")), []).append(it)
            enabled = bool(it.get("enabled", True))
            flag  = "" if enabled else "🚫 "
            if is_bundle:
                label = f"{flag}{name} – {int(it.get('price', 0)):,} {sym} (Bundle · {len(cls_list)} items)"
            else:
                label = f"{flag}{name} – {int(it.get('price', 0)):,} {sym} ({it.get('category', 'Misc')})"
            search = " ".join([name.lower()] + [c.lower() for c in cls_list])
            self._ac_index.append((search, label[:100], name[:100], enabled))

    def find(self, key: str) -> Optional[Dict]:
        return self._by_key.get(key.strip().lower())

    def save(self) -> bool:
        """Persistiert Änderungen (/shop setprice, /shop enable) in die geladene Quelle."""
        if self.source == "config.json":
            cfg.save_config()
            self.rebuild_index()
            return True
        data: Dict[str, Any] = {}
        try:
            with open(self.source, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            pass
        data["items"]    = self.items
        data["_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            with open(self.source, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.rebuild_index()
            return True
        except Exception as e:
            log.error(f"[SHOP] Konnte {self.source} nicht speichern: {e}")
            return False


catalog = ShopCatalog()


def _find_shop_item(name: str) -> Optional[Dict]:
    """Sucht ein Item per Anzeigename oder Classname (O(1) über den Katalog-Index)."""
    return catalog.find(name)

def _item_classnames(it: Dict) -> List[str]:
    """Classname-Liste eines Shop-Items: Bundle ("classnames") oder Einzelitem ("classname")."""
    cls = it.get("classnames")
    if isinstance(cls, list) and cls:
        return [str(c) for c in cls]
    cn = it.get("classname")
    return [str(cn)] if cn else []

def _shop_line(it: Dict) -> str:
    """Eine Katalog-Zeile für /shop list – Bundles zeigen ihren Inhalt kompakt."""
    cls_list = _item_classnames(it)
    name = str(it.get("name") or (cls_list[0] if cls_list else "?"))
    extra = ""
    if len(cls_list) > 1:
        inhalt = " + ".join(cls_list)
        if len(inhalt) > 60:
            inhalt = inhalt[:57] + "…"
        extra = f"Bundle: {inhalt}, "
    return (f"• **{name}** — {_fmt_money(int(it.get('price', 0)))} "
            f"*({extra}max {int(it.get('max_amount_per_buy', 1))}/buy)*")

def _make_item_autocomplete(only_enabled: bool):
    """Autocomplete über den vorberechneten Index (max. 25 Treffer, Substring-Suche)."""
    async def _ac(interaction: discord.Interaction,
                  current: str) -> List[app_commands.Choice[str]]:
        cur = current.strip().lower()
        out: List[app_commands.Choice] = []
        for search, label, value, enabled in catalog._ac_index:
            if only_enabled and not enabled:
                continue
            if cur and cur not in search:
                continue
            out.append(app_commands.Choice(name=label, value=value))
            if len(out) >= 25:
                break
        return out
    return _ac

_shop_item_autocomplete = _make_item_autocomplete(only_enabled=False)   # Admin-Befehle
_shop_buy_autocomplete  = _make_item_autocomplete(only_enabled=True)    # /buy

async def _shop_category_autocomplete(interaction: discord.Interaction,
                                      current: str) -> List[app_commands.Choice[str]]:
    cur = current.strip().lower()
    out: List[app_commands.Choice] = []
    for cat in sorted(catalog.by_category):
        if cur and cur not in cat.lower():
            continue
        n = sum(1 for i in catalog.by_category[cat] if i.get("enabled", True))
        if n == 0:
            continue
        out.append(app_commands.Choice(name=f"{cat} ({n} items)"[:100], value=cat))
        if len(out) >= 25:
            break
    return out


class ShopListView(discord.ui.View):
    """Einfache Seiten-Navigation für den Item-Katalog."""

    def __init__(self, pages: List[discord.Embed]):
        super().__init__(timeout=180)
        self.pages = pages
        self.index = 0
        self._sync()

    def _sync(self):
        self.prev_page.disabled = self.index <= 0
        self.next_page.disabled = self.index >= len(self.pages) - 1

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def prev_page(self, itx: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._sync()
        await itx.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, itx: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync()
        await itx.response.edit_message(embed=self.pages[self.index], view=self)


shop_group = app_commands.Group(name="shop", description="🛒 Item shop")

@shop_group.command(name="list", description="🛒 Show the shop catalog (all items or one category)")
@app_commands.describe(category="Category to list – leave empty for the overview")
async def shop_list(interaction: discord.Interaction, category: Optional[str] = None):
    enabled_items = [it for it in catalog.items if it.get("enabled", True)]
    if not enabled_items:
        return await interaction.response.send_message(
            "🛒 The shop is currently empty. Admins: put your `types.xml` next to the bot "
            "and restart (the catalog is generated automatically), or use `/add shopitem`.",
            ephemeral=True)

    if category is not None:
        # Eine Kategorie komplett auflisten
        wanted = category.strip().lower()
        match = next((c for c in catalog.by_category if c.lower() == wanted), None)
        items = ([i for i in catalog.by_category.get(match, []) if i.get("enabled", True)]
                 if match else [])
        if not items:
            return await interaction.response.send_message(
                f"❌ No category `{category}` – pick one from the autocomplete list.",
                ephemeral=True)
        lines = [_shop_line(it)
                 for it in sorted(items, key=lambda i: str(i.get("name", "")))]
        title = f"🛒 Item Shop – {match}"
    elif len(enabled_items) > 45:
        # Groß-Katalog (generierte shop_items.json): Kategorie-Übersicht statt 1700 Zeilen
        lines = []
        for cat in sorted(catalog.by_category):
            items = [i for i in catalog.by_category[cat] if i.get("enabled", True)]
            if not items:
                continue
            prices = [int(i.get("price", 0)) for i in items]
            lines.append(f"**{cat}** — {len(items)} items · "
                         f"{_fmt_money(min(prices))} – {_fmt_money(max(prices))}")
        lines.append("")
        lines.append("Use `/shop list category:<name>` to browse the items.")
        title = "🛒 Item Shop – Categories"
    else:
        # Kleiner Katalog: komplette Liste, nach Kategorie gruppiert
        by_cat: Dict[str, List[Dict]] = {}
        for it in enabled_items:
            by_cat.setdefault(it.get("category", "Misc"), []).append(it)
        lines = []
        for cat in sorted(by_cat):
            lines.append(f"__**{cat}**__")
            for it in sorted(by_cat[cat], key=lambda i: str(i.get("name", ""))):
                lines.append(_shop_line(it))
        title = "🛒 Item Shop"

    # In Seiten à 15 Zeilen aufteilen
    per_page = 15
    chunks = [lines[i:i + per_page] for i in range(0, len(lines), per_page)]
    pages: List[discord.Embed] = []
    for i, chunk in enumerate(chunks):
        e = discord.Embed(
            title=title,
            description="\n".join(chunk),
            color=0x5865F2)
        e.set_footer(text=(f"Page {i + 1}/{len(chunks)} · "
                           f"Buy with /buy <item> <amount> <x> <z> · "
                           f"Items spawn after the next server restart"))
        pages.append(e)

    if len(pages) == 1:
        return await interaction.response.send_message(embed=pages[0])
    await interaction.response.send_message(embed=pages[0], view=ShopListView(pages))

shop_list.autocomplete("category")(_shop_category_autocomplete)


@shop_group.command(name="pending", description="📦 Show purchases waiting for delivery (admin)")
async def shop_pending(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    rows = db.pending_purchases()
    if not rows:
        return await interaction.response.send_message(
            "✅ No pending deliveries.", ephemeral=True)
    lines = []
    for r in rows[:25]:
        lines.append(f"`#{r['id']}` <@{r['user_id']}> — **{r['amount']}× {r['item_name']}** "
                     f"({_fmt_money(int(r['total_price']))}) · <t:{int(r['created_at'])}:R>")
    embed = discord.Embed(
        title=f"📦 Pending deliveries ({len(rows)})",
        description="\n".join(lines),
        color=0xF39C12)
    embed.set_footer(text="Items spawn at the next server restart · /shop cleanup to finish manually")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@shop_group.command(name="cleanup",
                    description="🧹 Mark ALL pending purchases as delivered and clean cfgEffectArea.json (admin)")
async def shop_cleanup(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    await interaction.response.defer(ephemeral=True)
    if not bot.shop:
        return await interaction.followup.send("❌ Shop manager not ready yet.", ephemeral=True)
    rows = db.pending_purchases()
    ids, names = [], []
    for r in rows:
        ids.append(int(r["id"]))
        try:
            names.extend(json.loads(r["area_names"] or "[]"))
        except Exception:
            pass
    if names:
        ok = await bot.shop.remove_area_entries(names)
        if not ok:
            return await interaction.followup.send(
                "❌ Could not clean cfgEffectArea.json (FTP/parse error) – nothing was changed.",
                ephemeral=True)
    if ids:
        db.mark_delivered(ids)
        bot.shop.cleanup_retry_needed = False

    # Selbstheilung: verwaiste SHOP_-Einträge ohne zugehörigen Kauf entfernen
    orphans = await bot.shop.sweep_orphans()

    parts = []
    if ids:
        parts.append(f"**{len(ids)}** purchase(s) marked as delivered, "
                     f"**{len(names)}** entries removed from cfgEffectArea.json.")
    if orphans > 0:
        parts.append(f"**{orphans}** orphaned `SHOP_` entr{'y' if orphans == 1 else 'ies'} removed.")
    elif orphans < 0:
        parts.append("⚠️ Orphan sweep failed (FTP/parse error).")
    if not parts:
        parts.append("Nothing to clean – no pending deliveries and no orphaned entries.")
    await interaction.followup.send("🧹 " + " ".join(parts), ephemeral=True)


@shop_group.command(name="check",
                    description="🩺 Delivery-Diagnose: prüft cfgEffectArea.json & repariert fehlende Einträge (admin)")
async def shop_check(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    await interaction.response.defer(ephemeral=True)
    if not bot.shop:
        return await interaction.followup.send("❌ Shop manager not ready yet.", ephemeral=True)
    rep = await bot.shop.check_and_heal()

    embed = discord.Embed(title="🩺 Shop-Delivery-Diagnose", color=0x5865F2)
    path = rep.get("path")
    embed.add_field(name="Pfad", value=f"`{path}`" if path else
                    "❌ Nicht konfiguriert – `/ftp_scan` ausführen oder "
                    "`cfg_effect_area_path` in config.json setzen.", inline=False)
    status = rep.get("status")
    if status == "no_path":
        embed.colour = 0xE74C3C
        return await interaction.followup.send(embed=embed, ephemeral=True)
    if status == "error":
        embed.colour = 0xE74C3C
        embed.add_field(name="Datei", value="❌ FTP-Lesefehler – Verbindung prüfen "
                        "(`/ftp_status`), dann erneut versuchen.", inline=False)
        return await interaction.followup.send(embed=embed, ephemeral=True)
    if status == "parse_error":
        embed.colour = 0xE74C3C
        embed.add_field(name="Datei", value=f"❌ Ungültiges JSON: `{rep.get('error')}`",
                        inline=False)
        return await interaction.followup.send(embed=embed, ephemeral=True)

    file_line = ("✅ lesbar, gültiges JSON" if status == "ok" else
                 "⚠️ existiert noch nicht – wird beim ersten Kauf angelegt")
    embed.add_field(name="Datei", value=file_line, inline=False)
    embed.add_field(name="Einträge",
                    value=(f"{rep.get('areas_total', 0)} gesamt · "
                           f"{rep.get('shop_entries', 0)} SHOP_ · "
                           f"{rep.get('vanilla_entries', 0)} Vanilla"), inline=False)

    pending = rep.get("pending", 0)
    healed  = rep.get("healed_entries", 0)
    if healed:
        ok_write = rep.get("heal_written", False)
        heal_txt = (f"🔧 **{healed}** fehlende Einträge aus "
                    f"{len(rep.get('healed_purchases', []))} offenen Käufen wieder "
                    f"eingetragen" + ("" if ok_write else " – ❌ FTP-Schreibfehler!"))
        embed.add_field(name="Self-Heal", value=heal_txt, inline=False)
        if not ok_write:
            embed.colour = 0xE74C3C
    embed.add_field(name="Offene Käufe", value=str(pending), inline=True)

    if pending and not cfg.config.get("auto_restart_after_purchase", False):
        embed.add_field(
            name="Hinweis",
            value=("`auto_restart_after_purchase` ist **aus** – Items spawnen erst "
                   "beim nächsten (manuellen/geplanten) Server-Neustart."), inline=False)
    last = rep.get("last_restart_at") or 0
    embed.set_footer(text=("Letzter erkannter Server-Neustart: " +
                           (f"vor {int((time.time() - last) // 60)} Min"
                            if last else "seit Bot-Start keiner")))
    await interaction.followup.send(embed=embed, ephemeral=True)


@shop_group.command(name="setprice", description="💲 Change the price of a shop item (admin)")
@app_commands.describe(item="Item name", price="New price")
async def shop_setprice(interaction: discord.Interaction,
                        item: str, price: app_commands.Range[int, 0]):
    if not _is_admin(interaction):
        return await _deny(interaction)
    it = _find_shop_item(item)
    if not it:
        return await interaction.response.send_message(
            f"❌ Item `{item}` not found in the shop catalog.", ephemeral=True)
    old = int(it.get("price", 0))
    it["price"] = int(price)
    saved = catalog.save()
    note = "" if saved else f"\n⚠️ Could not persist to `{catalog.source}` – change is in memory only."
    await interaction.response.send_message(
        f"💲 **{it['name']}**: {_fmt_money(old)} → **{_fmt_money(int(price))}**{note}",
        ephemeral=True)

shop_setprice.autocomplete("item")(_shop_item_autocomplete)


@shop_group.command(name="enable", description="🔧 Enable or disable a shop item (admin)")
@app_commands.describe(item="Item name", enabled="True = buyable, False = hidden from the shop")
async def shop_enable(interaction: discord.Interaction, item: str, enabled: bool):
    if not _is_admin(interaction):
        return await _deny(interaction)
    it = _find_shop_item(item)
    if not it:
        return await interaction.response.send_message(
            f"❌ Item `{item}` not found in the shop catalog.", ephemeral=True)
    it["enabled"] = bool(enabled)
    saved = catalog.save()
    state = "✅ **enabled**" if enabled else "🚫 **disabled**"
    note  = "" if saved else f"\n⚠️ Could not persist to `{catalog.source}` – change is in memory only."
    await interaction.response.send_message(
        f"🔧 **{it['name']}** is now {state}.{note}", ephemeral=True)

shop_enable.autocomplete("item")(_shop_item_autocomplete)


@shop_group.command(name="removeitem",
                    description="🗑️ Remove an item/bundle from the shop catalog (admin)")
@app_commands.describe(item="Item name")
async def shop_removeitem(interaction: discord.Interaction, item: str):
    if not _is_admin(interaction):
        return await _deny(interaction)
    it = _find_shop_item(item)
    if not it:
        return await interaction.response.send_message(
            f"❌ Item `{item}` not found in the shop catalog.", ephemeral=True)
    try:
        catalog.items.remove(it)
    except ValueError:
        pass
    saved = catalog.save()
    note = "" if saved else f"\n⚠️ Could not persist to `{catalog.source}` – change is in memory only."
    await interaction.response.send_message(
        f"🗑️ **{it.get('name', item)}** was removed from the catalog.{note}", ephemeral=True)

shop_removeitem.autocomplete("item")(_shop_item_autocomplete)

bot.tree.add_command(shop_group)


# ══════════════════════════════════════════════════════════════
#  /add shopitem – Items/Bundles zur Laufzeit in den Katalog
# ══════════════════════════════════════════════════════════════
add_group = app_commands.Group(name="add", description="➕ Add entries to the shop catalog")

@add_group.command(name="shopitem",
                   description="➕ Add an item or bundle to the shop catalog (admin)")
@app_commands.describe(
    classnames="One classname, or several separated by comma/space = bundle (e.g. M4A1, Mag_STANAG_60Rnd)",
    price="Price for the item / the whole bundle",
    name="Display name (optional – default: the classname itself)",
    category="Shop category (optional – default: Custom, bundles: Bundles)",
    max_amount="Max amount per purchase (optional – default: 5, bundles: 1)")
async def add_shopitem(interaction: discord.Interaction, classnames: str,
                       price: app_commands.Range[int, 0],
                       name: Optional[str] = None,
                       category: Optional[str] = None,
                       max_amount: Optional[app_commands.Range[int, 1]] = None):
    if not _is_admin(interaction):
        return await _deny(interaction)

    # Classnames parsen: Komma/Semikolon/Leerzeichen, Reihenfolge behalten, Duplikate raus
    parts: List[str] = []
    seen: set = set()
    for tok in re.split(r"[,;\s]+", classnames.strip()):
        if tok and tok.lower() not in seen:
            seen.add(tok.lower())
            parts.append(tok)
    if not parts:
        return await interaction.response.send_message(
            "❌ No classname given. Example: `M4A1` or `M4A1, Mag_STANAG_60Rnd` for a bundle.",
            ephemeral=True)

    is_bundle = len(parts) > 1
    # Anforderung: der Classname IST der Anzeigename in /shop list (Bundles brauchen einen eigenen)
    display = (name or "").strip() or (f"{parts[0]} Bundle ({len(parts)} items)" if is_bundle else parts[0])
    if catalog.find(display):
        return await interaction.response.send_message(
            f"❌ `{display}` already exists in the catalog. Pick a different `name` or "
            f"remove the existing entry first (`/shop removeitem`).", ephemeral=True)

    # Tippfehler-Schutz VOR dem Einfügen: unbekannte Classnames melden (nicht blockierend)
    unknown = [c for c in parts if catalog.find(c) is None]

    cat = (category or "").strip() or ("Bundles" if is_bundle else "Custom")
    mx  = int(max_amount) if max_amount is not None else (1 if is_bundle else 5)

    it: Dict[str, Any] = {
        "name":               display[:100],
        "price":              int(price),
        "category":           cat,
        "enabled":            True,
        "max_amount_per_buy": mx,
        "custom":             True,   # übersteht die automatische Katalog-Regenerierung
    }
    if is_bundle:
        it["classnames"] = parts
    else:
        it["classname"] = parts[0]

    catalog.items.append(it)
    saved = catalog.save()

    embed = discord.Embed(
        title="➕ Shop bundle added" if is_bundle else "➕ Shop item added",
        description=f"**{display}** — {_fmt_money(int(price))}",
        color=0x2ECC71)
    cls_txt = ", ".join(f"`{c}`" for c in parts)
    if len(cls_txt) > 1000:
        cls_txt = cls_txt[:997] + "…"
    embed.add_field(name="Classnames" if is_bundle else "Classname", value=cls_txt, inline=False)
    embed.add_field(name="Category", value=cat,     inline=True)
    embed.add_field(name="Max/buy",  value=str(mx), inline=True)
    if unknown:
        embed.add_field(
            name="⚠️ Not found in the types.xml catalog",
            value=(", ".join(f"`{c}`" for c in unknown))[:900] +
                  "\nCheck the spelling – an unknown classname will NOT spawn in game.",
            inline=False)
    if not saved:
        embed.add_field(name="⚠️ Warning",
                        value=f"Could not persist to `{catalog.source}` – item is in memory only.",
                        inline=False)
    embed.set_footer(text=f"Catalog: {catalog.source} · buy it with /buy {display[:40]}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

add_shopitem.autocomplete("category")(_shop_category_autocomplete)

bot.tree.add_command(add_group)


# ══════════════════════════════════════════════════════════════
#  /edit shopitem – Classnames, Preis, Name usw. eines Items ändern
# ══════════════════════════════════════════════════════════════
edit_group = app_commands.Group(name="edit", description="✏️ Edit entries of the shop catalog")

@edit_group.command(name="shopitem",
                    description="✏️ Edit a shop item/bundle – change classnames, price, name, … (admin)")
@app_commands.describe(
    item="Item to edit (pick from the autocomplete list)",
    classnames="New classname(s) – several separated by comma/space = bundle (optional)",
    price="New price (optional)",
    name="New display name (optional)",
    category="New category (optional)",
    max_amount="New max amount per purchase (optional)")
async def edit_shopitem(interaction: discord.Interaction, item: str,
                        classnames: Optional[str] = None,
                        price: Optional[app_commands.Range[int, 0]] = None,
                        name: Optional[str] = None,
                        category: Optional[str] = None,
                        max_amount: Optional[app_commands.Range[int, 1]] = None):
    if not _is_admin(interaction):
        return await _deny(interaction)
    it = _find_shop_item(item)
    if not it:
        return await interaction.response.send_message(
            f"❌ Item `{item}` not found in the shop catalog.", ephemeral=True)
    if classnames is None and price is None and name is None \
            and category is None and max_amount is None:
        return await interaction.response.send_message(
            "❌ Nothing to change – set at least one of `classnames`, `price`, "
            "`name`, `category`, `max_amount`.", ephemeral=True)

    changes: List[str] = []
    unknown: List[str] = []

    # ── Classnames ändern (einer = Einzelitem, mehrere = Bundle) ──
    if classnames is not None:
        parts: List[str] = []
        seen: set = set()
        for tok in re.split(r"[,;\s]+", classnames.strip()):
            if tok and tok.lower() not in seen:
                seen.add(tok.lower())
                parts.append(tok)
        if not parts:
            return await interaction.response.send_message(
                "❌ No valid classname given. Example: `M4A1` or `M4A1, Mag_STANAG_60Rnd`.",
                ephemeral=True)
        old_cls = " + ".join(_item_classnames(it)) or "—"
        if len(parts) > 1:
            it["classnames"] = parts
            it.pop("classname", None)
        else:
            it["classname"] = parts[0]
            it.pop("classnames", None)
        # Tippfehler-Schutz: unbekannte Classnames nur melden, nicht blockieren
        unknown = [c for c in parts if catalog.find(c) is None]
        changes.append(f"Classnames: `{old_cls}` → `{' + '.join(parts)}`")

    # ── Preis ─────────────────────────────────────────────────
    if price is not None:
        old_price = int(it.get("price", 0))
        it["price"] = int(price)
        changes.append(f"Price: {_fmt_money(old_price)} → **{_fmt_money(int(price))}**")

    # ── Anzeigename (Kollision mit anderem Eintrag abfangen) ──
    if name is not None:
        new_name = name.strip()[:100]
        if not new_name:
            return await interaction.response.send_message(
                "❌ `name` must not be empty.", ephemeral=True)
        existing = catalog.find(new_name)
        if existing is not None and existing is not it:
            return await interaction.response.send_message(
                f"❌ `{new_name}` is already used by another catalog entry.", ephemeral=True)
        changes.append(f"Name: **{it.get('name', '?')}** → **{new_name}**")
        it["name"] = new_name

    # ── Kategorie / Max-Menge ─────────────────────────────────
    if category is not None and category.strip():
        changes.append(f"Category: {it.get('category', 'Misc')} → **{category.strip()}**")
        it["category"] = category.strip()
    if max_amount is not None:
        changes.append(f"Max/buy: {int(it.get('max_amount_per_buy', 1))} → **{int(max_amount)}**")
        it["max_amount_per_buy"] = int(max_amount)

    saved = catalog.save()   # persistiert + Index/Autocomplete neu aufbauen

    embed = discord.Embed(
        title="✏️ Shop item updated",
        description=f"**{it.get('name', item)}**\n" + "\n".join(f"• {c}" for c in changes),
        color=0x5865F2)
    if unknown:
        embed.add_field(
            name="⚠️ Not found in the types.xml catalog",
            value=(", ".join(f"`{c}`" for c in unknown))[:900] +
                  "\nCheck the spelling – an unknown classname will NOT spawn in game.",
            inline=False)
    if not saved:
        embed.add_field(name="⚠️ Warning",
                        value=f"Could not persist to `{catalog.source}` – change is in memory only.",
                        inline=False)
    embed.set_footer(text=f"Catalog: {catalog.source}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

edit_shopitem.autocomplete("item")(_shop_item_autocomplete)
edit_shopitem.autocomplete("category")(_shop_category_autocomplete)

@edit_group.command(name="ankuendigung",
                    description="✏️ Bearbeitet eine geplante Ankündigung (Nachricht/Bild)")
@app_commands.describe(index="Nummer der Ankündigung (siehe /liste)")
async def edit_ankuendigung(interaction: discord.Interaction, index: int):
    if not _is_admin(interaction):
        return await _deny(interaction)

    if index < 0 or index >= len(ann_data["announcements"]):

        return await interaction.response.send_message(
            "❌ Ungültiger Index",
            ephemeral=True
        )

    modal = EditAnnouncementModal(index)

    await interaction.response.send_modal(modal)

bot.tree.add_command(edit_group)


# ══════════════════════════════════════════════════════════════
#  /bundle add – Bundle über ein Modal anlegen (mehrere Items,
#  ein Kauf). Eingabe pro Zeile: "<Menge>x<Classname>", z. B.
#      1xAKM
#      2xMag_AKM_30Rnd
#  Da Discord-Modals keine Dropdowns erlauben, wird die Kategorie
#  über ein vorgeschaltetes Select-Menü gewählt; danach öffnet
#  das Modal mit den restlichen Feldern.
# ══════════════════════════════════════════════════════════════
MAX_BUNDLE_PIECES = 60   # Sicherheitslimit: so viele Einzelstücke max. pro Bundle

# Zeilenformat: optionaler Mengen-Präfix "<zahl>x" / "<zahl> * " vor dem Classname.
_BUNDLE_LINE_RE = re.compile(r"^\s*(?:(\d+)\s*[x×*]\s*)?(\S.*?)\s*$", re.IGNORECASE)


def _parse_bundle_items(text: str) -> Tuple[List[str], List[Tuple[int, str]], List[str]]:
    """Parst die Modal-Eingabe (eine Zeile je Position, Format ``2xClassname``).

    Rückgabe: (expanded, summary, errors)
      * expanded – Classname-Liste MIT Wiederholung (2xMag → zweimal Mag);
        genau diese Liste landet als ``classnames`` im Katalog und spawnt
        pro Eintrag ein Stück (siehe ShopManager.add_purchase_entries).
      * summary  – [(menge, classname)] je Zeile, für die Bestätigungsanzeige.
      * errors   – menschenlesbare Fehler (leere/kaputte Zeilen, Menge <1)."""
    expanded: List[str] = []
    summary: List[Tuple[int, str]] = []
    errors: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _BUNDLE_LINE_RE.match(line)
        if not m:
            errors.append(f"`{line[:60]}` – not understood (use `2xClassname`).")
            continue
        count_txt, classname = m.group(1), m.group(2).strip()
        # Nur der reine Classname (keine Leerzeichen) – nimm das erste Token.
        classname = classname.split()[0] if classname else ""
        if not classname:
            errors.append(f"`{line[:60]}` – no classname found.")
            continue
        try:
            count = int(count_txt) if count_txt else 1
        except ValueError:
            count = 1
        if count < 1:
            errors.append(f"`{line[:60]}` – amount must be at least 1.")
            continue
        summary.append((count, classname))
        expanded.extend([classname] * count)
    return expanded, summary, errors


def _bundle_category_options(preselect: str = "Bundles") -> List[discord.SelectOption]:
    """Kategorie-Optionen fürs Dropdown: 'Bundles' zuerst, dann bestehende
    Katalog-Kategorien (Discord erlaubt max. 25 Optionen)."""
    opts: List[discord.SelectOption] = [
        discord.SelectOption(label="Bundles", value="Bundles", emoji="📦",
                             description="Default category for bundles",
                             default=(preselect == "Bundles")),
    ]
    for cat in sorted(catalog.by_category):
        if cat.lower() == "bundles":
            continue
        opts.append(discord.SelectOption(label=cat[:100], value=cat[:100],
                                         default=(cat == preselect)))
        if len(opts) >= 25:
            break
    return opts


class BundleAddModal(discord.ui.Modal, title="📦 Create shop bundle"):
    """Modal mit den Bundle-Feldern. Die Kategorie kommt aus dem vorgelagerten
    Dropdown und wird hier nur noch mitgeführt."""

    def __init__(self, category: str):
        super().__init__()
        self.category = category or "Bundles"
        self.items_in = discord.ui.TextInput(
            label="Items – one per line: 2xClassname",
            style=discord.TextStyle.paragraph,
            placeholder="1xAKM\n2xMag_AKM_30Rnd\n1xNVGoggles",
            required=True, max_length=1500)
        self.name_in = discord.ui.TextInput(
            label="Name in the shop",
            placeholder="e.g. AKM Starter Bundle",
            required=True, max_length=100)
        self.price_in = discord.ui.TextInput(
            label="Price (for the whole bundle)",
            placeholder="e.g. 2500", required=True, max_length=15)
        self.max_in = discord.ui.TextInput(
            label="Max amount per purchase",
            placeholder="1", required=False, default="1", max_length=6)
        for comp in (self.items_in, self.name_in, self.price_in, self.max_in):
            self.add_item(comp)

    async def on_submit(self, interaction: discord.Interaction):
        # Admin-Recht erneut prüfen (Modal kann verzögert abgeschickt werden)
        if not _is_admin(interaction):
            return await _deny(interaction)

        # ── Items parsen ─────────────────────────────────────────
        expanded, summary, errors = _parse_bundle_items(str(self.items_in.value))
        if not summary:
            return await interaction.response.send_message(
                "❌ No valid items. Enter one per line, e.g. `1xAKM` or "
                "`2xMag_AKM_30Rnd`." +
                ("\n" + "\n".join(f"• {e}" for e in errors[:5]) if errors else ""),
                ephemeral=True)
        if len(expanded) > MAX_BUNDLE_PIECES:
            return await interaction.response.send_message(
                f"❌ Too many pieces ({len(expanded)}). A bundle may contain at "
                f"most **{MAX_BUNDLE_PIECES}** individual items.", ephemeral=True)

        # ── Preis parsen (Tausenderpunkte/-kommas tolerieren) ────
        price_digits = re.sub(r"[^\d]", "", str(self.price_in.value))
        if not price_digits:
            return await interaction.response.send_message(
                "❌ Price must be a whole number, e.g. `2500`.", ephemeral=True)
        price = int(price_digits)

        # ── Max-Menge parsen ─────────────────────────────────────
        max_digits = re.sub(r"[^\d]", "", str(self.max_in.value or "")) or "1"
        max_amount = max(1, int(max_digits))

        # ── Name / Kollision ─────────────────────────────────────
        display = str(self.name_in.value).strip()[:100]
        if not display:
            return await interaction.response.send_message(
                "❌ The shop name must not be empty.", ephemeral=True)
        if catalog.find(display):
            return await interaction.response.send_message(
                f"❌ `{display}` already exists in the catalog. Pick a different "
                f"name or remove the existing entry first (`/shop removeitem`).",
                ephemeral=True)

        # Tippfehler-Schutz: unbekannte Classnames melden (nicht blockierend)
        seen_unknown: set = set()
        unknown: List[str] = []
        for _, cn in summary:
            if catalog.find(cn) is None and cn.lower() not in seen_unknown:
                seen_unknown.add(cn.lower())
                unknown.append(cn)

        # ── Katalog-Eintrag bauen (immer als Bundle: classnames-Liste) ──
        it: Dict[str, Any] = {
            "name":               display,
            "price":              price,
            "category":           self.category,
            "enabled":            True,
            "max_amount_per_buy": max_amount,
            "classnames":         expanded,
            "custom":             True,   # übersteht die Katalog-Regenerierung
        }
        catalog.items.append(it)
        saved = catalog.save()

        # ── Bestätigung ──────────────────────────────────────────
        sym = _cur_symbol()
        total_pieces = len(expanded)
        embed = discord.Embed(
            title="📦 Shop bundle added",
            description=f"**{display}** — {_fmt_money(price)}",
            color=0x2ECC71)
        content_lines = [f"• **{cnt}×** `{cn}`" for cnt, cn in summary]
        content_txt = "\n".join(content_lines)
        if len(content_txt) > 1000:
            content_txt = content_txt[:997] + "…"
        embed.add_field(name=f"Contents ({total_pieces} pieces)",
                        value=content_txt, inline=False)
        embed.add_field(name="Category", value=self.category, inline=True)
        embed.add_field(name="Max/buy",  value=str(max_amount), inline=True)
        if unknown:
            embed.add_field(
                name="⚠️ Not found in the types.xml catalog",
                value=(", ".join(f"`{c}`" for c in unknown))[:900] +
                      "\nCheck the spelling – an unknown classname will NOT spawn in game.",
                inline=False)
        if not saved:
            embed.add_field(
                name="⚠️ Warning",
                value=f"Could not persist to `{catalog.source}` – bundle is in memory only.",
                inline=False)
        embed.set_footer(text=f"Catalog: {catalog.source} · buy it with /buy {display[:40]}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error(f"[SHOP] Bundle-Modal-Fehler: {error}")
        msg = "❌ Something went wrong while creating the bundle. Please try again."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


class BundleCategorySelect(discord.ui.Select):
    """Dropdown zur Kategorie-Wahl; öffnet danach das Bundle-Modal."""

    def __init__(self):
        super().__init__(placeholder="📂 Choose a category for the bundle…",
                         min_values=1, max_values=1,
                         options=_bundle_category_options())

    async def callback(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            return await _deny(interaction)
        await interaction.response.send_modal(BundleAddModal(self.values[0]))


class BundleCategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(BundleCategorySelect())


bundle_group = app_commands.Group(
    name="bundle", description="📦 Create shop bundles (several items, one purchase)")


@bundle_group.command(
    name="add",
    description="📦 Create a bundle via a form: several items, sold as one purchase (admin)")
async def bundle_add(interaction: discord.Interaction):
    if not _is_admin(interaction):
        return await _deny(interaction)
    embed = discord.Embed(
        title="📦 Create a shop bundle",
        description=("Choose a **category** below – then a form opens where you "
                     "enter the items, name, price and max amount.\n\n"
                     "**Items:** one per line as `<amount>x<classname>`, e.g.\n"
                     "```\n1xAKM\n2xMag_AKM_30Rnd\n1xNVGoggles\n```\n"
                     "All items of the bundle spawn together on a single `/buy`."),
        color=0x5865F2)
    await interaction.response.send_message(
        embed=embed, view=BundleCategoryView(), ephemeral=True)


bot.tree.add_command(bundle_group)


@bot.tree.command(
    name="buy",
    description="🛒 Buy an item – it spawns at your coordinates after the next server restart")
@app_commands.describe(
    item="Item name (pick from the autocomplete list)",
    amount="How many to buy",
    x="iZurvive X coordinate (East – the FIRST number on iZurvive)",
    z="iZurvive Y coordinate (North – the SECOND number on iZurvive)",
    y="Height / altitude (OPTIONAL – leave empty for default ground level)")
async def cmd_buy(interaction: discord.Interaction, item: str,
                  amount: app_commands.Range[int, 1], x: float, z: float,
                  y: Optional[float] = None):
    if not await _require_guild(interaction):
        return
    gid, uid = interaction.guild_id, interaction.user.id

    # ── 1. Item & Menge validieren ────────────────────────────
    it = _find_shop_item(item)
    if not it or not it.get("enabled", True):
        return await interaction.response.send_message(
            f"❌ Item `{item}` is not available. Use `/shop list` to see the catalog.",
            ephemeral=True)
    max_amount = int(it.get("max_amount_per_buy", 1))
    if amount > max_amount:
        return await interaction.response.send_message(
            f"❌ You can buy at most **{max_amount}× {it['name']}** per purchase.",
            ephemeral=True)
    cls_list = _item_classnames(it)
    if not cls_list:
        return await interaction.response.send_message(
            f"❌ Item `{it.get('name', item)}` has no classnames configured – "
            f"ask an admin to fix the catalog entry.", ephemeral=True)

    # ── 2. Koordinaten validieren (iZurvive: x=Ost, z=Nord) ───
    if not (0.0 <= x <= 20000.0 and 0.0 <= z <= 20000.0):
        return await interaction.response.send_message(
            "❌ Coordinates out of range. Enter the two iZurvive numbers as "
            "`x` (East) and `z` (North), e.g. `x: 4640` `z: 10350`.", ephemeral=True)
    # ACHTUNG Achsen-Mapping: cfgEffectArea Pos = [X, HÖHE, NORD]
    # → iZurvive-X → Pos[0], Höhe (y-Parameter) → Pos[1], iZurvive-Y → Pos[2]
    y_val = float(cfg.config.get("default_pos_y", 0.0)) if y is None else float(y)
    if not (-100.0 <= y_val <= 1000.0):
        return await interaction.response.send_message(
            "❌ Height `y` out of range (−100 … 1000). Leave it empty for ground level.",
            ephemeral=True)

    # ── 3. Preis prüfen (Vorprüfung, Abbuchung erst nach FTP-Erfolg) ──
    total = int(it.get("price", 0)) * int(amount)
    wallet, _bank = db.get_balance(gid, uid)
    if wallet < total:
        return await interaction.response.send_message(
            embed=_insufficient_embed(total, wallet), ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    if not bot.shop:
        return await interaction.followup.send(
            "❌ Shop system is still starting up – try again in a moment.", ephemeral=True)

    # ── 4. Erst in cfgEffectArea.json schreiben ... ───────────
    ok, err, area_names = await bot.shop.add_purchase_entries(
        cls_list, int(amount), x, y_val, z)
    if not ok:
        return await interaction.followup.send(
            embed=discord.Embed(title="❌ Purchase failed", description=err, color=0xE74C3C),
            ephemeral=True)

    # ── 5. ... dann Geld abbuchen (atomar). Bei Fehlschlag: Rollback ──
    if not db.try_spend_wallet(gid, uid, total):
        rollback_ok = await bot.shop.remove_area_entries(area_names)   # Einträge zurückrollen
        if not rollback_ok:
            # Verwaiste Einträge würden bei jedem Neustart gratis spawnen → Admins warnen
            log.error(f"[SHOP] Rollback fehlgeschlagen – verwaiste Areas: {area_names}")
            warn = discord.Embed(
                title="⚠️ Orphaned shop entries",
                description=("A cancelled purchase could not be rolled back in "
                             "`cfgEffectArea.json`. Run `/shop cleanup` to remove the "
                             "orphaned entries, otherwise the items respawn on every restart."),
                color=0xE67E22)
            await _post_feed(gid, "shop_log", warn)
        wallet, _bank = db.get_balance(gid, uid)
        return await interaction.followup.send(
            embed=_insufficient_embed(total, wallet), ephemeral=True)

    # ── 6. Kauf als pending speichern ─────────────────────────
    purchase_id = db.create_purchase(
        gid, uid, str(interaction.user), it["name"], "+".join(cls_list),
        int(amount), total, x, y_val, z, area_names)

    # ── 7. Auto-Restart oder Hinweis auf nächsten Neustart ────
    if cfg.config.get("auto_restart_after_purchase", False):
        bot.shop.schedule_auto_restart()
        cooldown = int(cfg.config.get("restart_cooldown_seconds", 300))
        delivery_info = (f"🔄 A server restart has been scheduled – your items will spawn "
                         f"in about **{max(5, cooldown)} seconds** (plus boot time).")
    else:
        delivery_info = "⏳ Your items will spawn at the **next scheduled server restart**."

    # ── 8. Bestätigung an den Käufer (Ort + iZurvive-Link) ────
    map_name = cfg.config.get("map_name", "ChernarusPlus")
    loc_url  = _izurvive_url(x, z, map_name)
    near     = _nearest_location(x, z, map_name)
    near_txt = f"\n*(Near {near})*" if near else ""
    wallet, _bank = db.get_balance(gid, uid)

    embed = discord.Embed(
        title="🛒 Purchase successful",
        description=f"You bought **{amount}× {it['name']}** for **{_fmt_money(total)}**.",
        color=0x2ECC71)
    embed.add_field(name="📍 Spawn location",
                    value=f"[{x:.1f} / {z:.1f}]({loc_url}){near_txt}", inline=False)
    embed.add_field(name="🚚 Delivery", value=delivery_info, inline=False)
    embed.add_field(name="👛 Wallet",   value=_fmt_money(wallet), inline=True)
    embed.set_footer(text=f"Purchase #{purchase_id}")
    await interaction.followup.send(embed=embed, ephemeral=True)

    # ── 9. Kauf in den shop_log-Feed posten ───────────────────
    feed = discord.Embed(
        title="🛒 SHOP PURCHASE",
        description=f"{interaction.user.mention} bought **{amount}× {it['name']}**",
        color=0x3498DB)
    feed.add_field(name="Price",    value=_fmt_money(total), inline=True)
    feed.add_field(name="Location", value=f"[{x:.1f} / {z:.1f}]({loc_url}){near_txt}", inline=True)
    feed.add_field(name="Status",   value="⏳ pending (spawns after restart)", inline=False)
    feed.set_footer(text=(f"Purchase #{purchase_id} · " + "+".join(cls_list))[:100])
    await _post_feed(gid, "shop_log", feed)

cmd_buy.autocomplete("item")(_shop_buy_autocomplete)


# ══════════════════════════════════════════════════════════════
#  KATALOG-GENERATOR – shop_items.json aus der types.xml erzeugen
#  (in den Bot integriert, damit alles in EINER Datei bleibt.
#   Läuft beim Start automatisch, wenn shop_items.json fehlt und
#   eine types.xml im Bot-Ordner liegt.)
# ══════════════════════════════════════════════════════════════
TYPES_XML_FILE = "types.xml"

# Keine kaufbaren Items → gar nicht in den Katalog aufnehmen
_GEN_EXCLUDED = {"Animals", "Infected", "Static Objects", "Land Items", "UNCATEGORIZED"}
# Aufnehmen, aber deaktiviert: Fahrzeug-Spawn über cfgEffectArea ist unzuverlässig
# (fehlende Anbauteile/Persistenz) – Admins können einzelne per /shop enable freischalten
_GEN_DISABLED = {"Vehicles"}
_GEN_MAX_AMOUNT = {
    "Ammo": 10, "Food": 10, "Medical Items": 10, "Supplies": 10,
    "Seeds": 10, "Plants": 10,
    "Firearms": 2, "Optics": 2,
    "Bags": 3, "Vests": 3,
    "Vehicles": 1,
}
_GEN_RE_CATEGORY = re.compile(r"<!--#+\s*(.+?)\s*#+-->")
_GEN_RE_TYPE     = re.compile(r'<type\s+name="([^"]+)"')


def _gen_prettify(classname: str) -> str:
    """Anzeigename aus Classname: 'Armband_BabyDeer' → 'Armband Baby Deer'."""
    s = classname.replace("_", " ")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)      # klein/Ziffer → GROSS
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)    # GROSS-Serie → Wortanfang
    return re.sub(r"\s+", " ", s).strip()


def generate_shop_items_from_types(input_path: str = TYPES_XML_FILE,
                                   output_path: Optional[str] = None) -> Optional[int]:
    """Erzeugt shop_items.json aus einer types.xml (DayZBoosterZ-Format).
    Kategorie-Preise kommen aus shop_category_prices in config.json.
    Per /add shopitem angelegte Items ("custom": true) werden übernommen.
    Gibt die Item-Anzahl zurück, None bei Fehler."""
    out_file = output_path or str(cfg.config.get("shop_items_file") or "shop_items.json")
    if not os.path.exists(input_path):
        return None

    prices        = cfg.config.get("shop_category_prices") or {}
    default_price = int(cfg.config.get("shop_default_price", 100))

    # types.xml zeilenweise parsen: Kategorie-Kommentare + <type name="...">
    category = "UNCATEGORIZED"
    entries: List[Tuple[str, str]] = []
    seen: set = set()
    try:
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m_cat = _GEN_RE_CATEGORY.search(line)
                if m_cat:
                    category = m_cat.group(1).strip()
                    continue
                m_type = _GEN_RE_TYPE.search(line)
                if m_type:
                    cn = m_type.group(1).strip()
                    if cn.lower() not in seen:      # Duplikate überspringen
                        seen.add(cn.lower())
                        entries.append((cn, category))
    except Exception as e:
        log.error(f"[GEN] types.xml nicht lesbar: {e}")
        return None
    if not entries:
        log.error("[GEN] Keine <type name=...>-Eintraege in der types.xml gefunden.")
        return None

    items: List[Dict] = []
    name_counts: Dict[str, int] = {}
    for cn, cat in entries:
        if cat in _GEN_EXCLUDED:
            continue
        nm = _gen_prettify(cn)
        name_counts[nm.lower()] = name_counts.get(nm.lower(), 0) + 1
        items.append({
            "name":               nm,
            "classname":          cn,
            "price":              int(prices.get(cat, default_price)),
            "category":           cat,
            "enabled":            cat not in _GEN_DISABLED,
            "max_amount_per_buy": int(_GEN_MAX_AMOUNT.get(cat, 5)),
        })
    # Namens-Kollisionen eindeutig machen (Anzeigename ist der Lookup-Schlüssel)
    for it in items:
        if name_counts.get(it["name"].lower(), 0) > 1:
            it["name"] = f"{it['name']} ({it['classname']})"
    items.sort(key=lambda i: (i["category"].lower(), i["name"].lower()))

    # Manuell angelegte Items (/add shopitem, "custom": true) aus einer
    # bestehenden Datei übernehmen – sonst gehen sie beim Regenerieren verloren
    if os.path.exists(out_file):
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                old = json.load(f)
            old_items = old.get("items") if isinstance(old, dict) else old
            if isinstance(old_items, list):
                gen_names = {i["name"].lower() for i in items}
                keep = [i for i in old_items
                        if isinstance(i, dict) and i.get("custom")
                        and str(i.get("name", "")).lower() not in gen_names]
                items.extend(keep)
        except Exception as e:
            log.warning(f"[GEN] Bestehende {out_file} nicht lesbar ({e}) - "
                        f"Custom-Items nicht uebernommen.")

    out = {
        "_generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "_source":    os.path.basename(input_path),
        "_note":      ("Automatisch aus types.xml generiert. Neu erzeugen: diese Datei "
                       "löschen und den Bot neu starten. Preise: /shop setprice oder "
                       "/edit shopitem; Kategorie-Preise: shop_category_prices in config.json."),
        "items": items,
    }
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[GEN] Konnte {out_file} nicht schreiben: {e}")
        return None
    log.info(f"[GEN] Katalog generiert: {len(items)} Items -> {out_file}")
    return len(items)


# ══════════════════════════════════════════════════════════════
#  Auto-Erkennung beim Start: Service-ID, FTP-Zugang & Karte
#  werden über den Nitrado-Token ermittelt und in config.json
#  als Cache gespeichert – der Nutzer trägt nur noch bot_token,
#  nitrado_token und guild_ids ein.
# ══════════════════════════════════════════════════════════════
def _cached_ftp_available(reason: str) -> bool:
    """Fallback: Sind aus einem früheren Start noch gültige Werte in
    config.json gecacht, kann der Bot trotz fehlgeschlagener Erkennung starten."""
    if all(str(cfg.config.get(k) or "").strip()
           for k in ("service_id", "ftp_host", "ftp_user", "ftp_password")):
        print(f"⚠️  {reason} – verwende gespeicherte Zugangsdaten aus config.json.")
        return True
    return False


def _apply_gameserver_info(info: Dict) -> None:
    """Schreibt FTP-Zugang, aktuelle Karte und (falls leer) Server-IP/Query-Port
    aus den Nitrado-Gameserver-Infos in cfg.config. Speichert NICHT selbst."""
    ftp = NitradoAPI.extract_ftp_credentials(info)
    if ftp:
        # Immer überschreiben – fängt von Nitrado geänderte Passwörter ab
        cfg.config["ftp_host"]     = ftp["host"]
        cfg.config["ftp_port"]     = ftp["port"]
        cfg.config["ftp_user"]     = ftp["user"]
        cfg.config["ftp_password"] = ftp["password"]
        log.info(f"[NITRADO] ✅ FTP-Zugang automatisch erkannt: "
                 f"{ftp['user']}@{ftp['host']}:{ftp['port']}")
    else:
        log.warning("[NITRADO] ⚠️ Keine FTP-Zugangsdaten in den "
                    "Gameserver-Infos gefunden.")

    detected_map = NitradoAPI.extract_map(info)
    if detected_map and detected_map != cfg.config.get("map_name"):
        log.info(f"[NITRADO] 🗺️ Aktuelle Karte erkannt: {detected_map} "
                 f"(vorher: {cfg.config.get('map_name')})")
        cfg.config["map_name"] = detected_map

    # Bonus: Server-IP/Query-Port nur befüllen, wenn noch nicht gesetzt
    if not cfg.config.get("server_ip") and info.get("ip"):
        cfg.config["server_ip"] = str(info["ip"])
        qport = (info.get("query") or {}).get("connect_port") or info.get("query_port")
        if qport:
            try:
                cfg.config["query_port"] = int(qport)
            except (TypeError, ValueError):
                pass
        log.info(f"[NITRADO] Server-IP automatisch gesetzt: {info['ip']}")


async def auto_detect_from_nitrado() -> bool:
    """Erkennt service_id, FTP-Zugangsdaten und die aktuelle Karte über den
    Nitrado-Token und speichert sie in config.json. Gibt True zurück, wenn
    der Bot mit gültigen FTP-Zugangsdaten starten kann."""
    # Platzhalter aus alten config.json-Versionen wie leere Felder behandeln
    for key in ("service_id", "ftp_host", "ftp_user", "ftp_password"):
        val = str(cfg.config.get(key) or "")
        if "HIER" in val or "EINTRAGEN" in val:
            cfg.config[key] = ""

    api = NitradoAPI(
        token=cfg.config["nitrado_token"],
        service_id=str(cfg.config.get("service_id") or "").strip(),
        base=cfg.config.get("nitrado_api_base", "https://api.nitrado.net"),
    )
    try:
        # ── 1. Service-ID: manuell gesetzter Wert hat Vorrang ────
        if not api.service_id:
            sid = await api.detect_service()
            if not sid:
                return _cached_ftp_available("Service-Erkennung fehlgeschlagen")
            cfg.config["service_id"] = sid
            cfg.save_config()

        # ── 2. FTP-Zugang + Karte aus den Gameserver-Infos ───────
        info = await api.get_info()
        if not info:
            return _cached_ftp_available(
                f"Nitrado-API nicht erreichbar (Service {api.service_id})")

        _apply_gameserver_info(info)
        cfg.save_config()

        if all(str(cfg.config.get(k) or "").strip()
               for k in ("ftp_host", "ftp_user", "ftp_password")):
            return True
        return _cached_ftp_available("FTP-Zugangsdaten unvollständig")
    finally:
        await api.close()


# ══════════════════════════════════════════════════════════════
#  Start
# ══════════════════════════════════════════════════════════════
def main():
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║        DayZ Discord Bot – Server Management          ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    cfg.load_all()

    # Katalog bei Bedarf automatisch aus der types.xml erzeugen (Generator ist integriert)
    shop_file = str(cfg.config.get("shop_items_file") or "shop_items.json")
    if not os.path.exists(shop_file) and os.path.exists(TYPES_XML_FILE):
        n = generate_shop_items_from_types(TYPES_XML_FILE, shop_file)
        if n:
            print(f"   Shop-Katalog aus types.xml generiert: {n} Items -> {shop_file}")

    catalog.load()   # Item-Katalog (shop_items.json bzw. shop_items aus config.json)

    valid, missing = cfg.is_valid()
    if not valid:
        print("❌ KONFIGURATION UNVOLLSTÄNDIG!")
        print(f"   Bitte öffne '{CONFIG_FILE}' und fülle folgende Felder aus:")
        for field in missing:
            print(f"   → {field}")
        print()
        print(f"   Die Datei '{CONFIG_FILE}' wurde automatisch erstellt.")
        print("   Es werden nur bot_token und guild_ids benötigt – die Nitrado-")
        print("   Anbindung richtest du danach im Discord mit /setup token ein.")
        print()
        sys.exit(1)

    if cfg.has_nitrado_token():
        print("🔎 Erkenne Nitrado-Server (Service-ID, FTP-Zugang, Karte)...")
        if not asyncio.run(auto_detect_from_nitrado()):
            print()
            print("⚠️  NITRADO-AUTO-ERKENNUNG FEHLGESCHLAGEN!")
            print("   Der Bot startet trotzdem – richte die Nitrado-Anbindung im")
            print("   Discord (neu) ein: /setup token <dein-nitrado-token>")
            print()
    else:
        print("ℹ️  Noch kein Nitrado-Token gesetzt – der Bot startet ohne")
        print("   Nitrado-Anbindung. Richte ihn im Discord ein:")
        print("   /setup token <dein-nitrado-token> → Server im Dropdown auswählen")
        print("   → bestätigen. FTP-Zugang & Karte werden automatisch erkannt.")
        print()

    print(f"✅ Konfiguration geladen")
    print(f"   Service-ID:     {cfg.config.get('service_id') or '(per /setup token einrichten)'}")
    print(f"   FTP-Host:       {cfg.config.get('ftp_host') or '(per /setup token einrichten)'}")
    print(f"   Karte:          {cfg.config.get('map_name', 'ChernarusPlus')}")
    print(f"   Log-Verzeichnis:{cfg.config.get('ftp_log_dir') or '(wird automatisch gesucht)'}")
    print(f"   Server-IP:      {cfg.config.get('server_ip') or '(nicht gesetzt)'}")
    print(f"   Query-Port:     {cfg.config.get('query_port', 2302)}")
    print(f"   RCON-Port:      {cfg.config.get('rcon_port',  2310)}")
    print(f"   Guild IDs:      {cfg.config.get('guild_ids', [])}")
    print(f"   Poll-Intervall: {cfg.config.get('log_poll_interval_seconds', 10)}s")
    print(f"   Admin-Rolle:    {cfg.config.get('admin_role_name')}")
    print(f"   Admin-Rollen-IDs: {cfg.config.get('admin_role_ids', []) or '(keine – Fallback Rollen-Name)'}")
    print(f"   Währung:        {cfg.config.get('currency_name')} ({cfg.config.get('currency_symbol')})")
    print(f"   Shop-Items:     {len([i for i in cfg.config.get('shop_items', []) if i.get('enabled', True)])} aktiv")
    print(f"   Auto-Restart:   {'AN' if cfg.config.get('auto_restart_after_purchase') else 'AUS (Items spawnen beim nächsten regulären Neustart)'}")
    print()
    print("🚀 Starte Bot...")
    print()

    bot.run(cfg.config["bot_token"], log_handler=None)


if __name__ == "__main__":
    main()
