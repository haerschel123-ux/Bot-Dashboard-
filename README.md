# DayZ Bot + Web-Dashboard

Discord-Bot für Nitrado-DayZ-Server (Konsole) mit Killfeed, Shop/Economy,
Zonen, Whitelist, Auto-Restarts – plus **Web-Dashboard**, das komplett über
**GitHub Pages** läuft (kein eigener Server nötig).

## Schnellstart Bot

1. `bot_42.py` auf deinem Bot-Host starten (Python 3.10+, Abhängigkeiten
   installiert der Bot selbst).
2. In `config.json` nur **`bot_token`** und **`guild_ids`** eintragen.
3. Im Discord `/setup token <dein-nitrado-token>` ausführen → Server im
   Dropdown wählen. FTP-Zugang, aktive Karte und Log-Verzeichnisse werden
   automatisch erkannt.

## Dashboard aktivieren (GitHub Pages)

Das Dashboard liegt fertig im Ordner [`docs/`](docs/):

1. GitHub-Repo → **Settings → Pages**
2. Bei *Build and deployment*: **Deploy from a branch**,
   Branch = dein Haupt-Branch, Ordner = **`/docs`** → Save
3. Nach ~1 Minute ist das Dashboard erreichbar unter
   `https://<dein-name>.github.io/<repo-name>/`

### Ablauf im Dashboard

1. **Nitrado-Token eingeben** (Nitrado → Benutzereinstellungen →
   API-Schlüssel, Long-Life-Token) → **Bestätigen**
2. **Server auswählen** → die aktive Karte (ChernarusPlus / Livonia /
   Sakhal) wird automatisch erkannt
3. Kategorien:
   - **📢 Feeds** – jeden Feed (Killfeed, Damage, Join/Leave, …) optional
     einem Discord-Channel zuweisen (wie `/setup feeds`)
   - **🛡️ Zonen** – Zonen wie `/zone create`, zusätzlich direkt auf der
     interaktiven Karte **zeichnen** (Klick = Zentrum, ziehen = Radius)
   - **⏰ Auto-Aufgaben** – automatische Server-Neustarts planen
   - **🛒 Shop** – Items/Bundles per Formular anlegen: Name, Kategorie
     (inkl. „Neue Kategorie“), Preis, Items mit Autofill, Kauf-Limit
   - **🗺️ Karte** – echte DayZ-Karte (iZurvive-Kartenbilder) mit allen
     letzten Events (Kills, Treffer, Bau, Fahrzeug, Verbinden/Trennen, …)
     und Spielerpositionen; Filterpanel links ein-/ausklappbar, jeder
     Event-Typ einzeln ein-/ausblendbar

### Wie Dashboard und Bot kommunizieren

Ohne eigenen Server: Das Dashboard spricht direkt mit der **Nitrado-API**
(sie erlaubt Browser-Zugriffe) und tauscht mit dem Bot zwei JSON-Dateien
auf deinem DayZ-Server aus:

| Datei                     | Richtung        | Inhalt                          |
|---------------------------|-----------------|---------------------------------|
| `dashboard_sync.json`     | Dashboard → Bot | Befehle (Feeds, Zonen, Shop, …) |
| `dashboard_state.json`    | Bot → Dashboard | Channels, Zonen, Events, Status |
| `dashboard_catalog.json`  | Bot → Dashboard | Item-Katalog für das Autofill   |

Der Bot muss dafür einfach nur laufen (egal wo – es wird **kein offener
Port** benötigt). Abschalten: `"dashboard_enabled": false` in `config.json`.

### Falls die Karte/Daten nicht laden (CORS)

Sollte die Browser-Konsole beim Laden von `dashboard_state.json`
CORS-Fehler zeigen, hilft ein kostenloser Cloudflare-Worker als Mini-Proxy:
Anleitung und fertiger Code stehen in [`docs/worker.js`](docs/worker.js).

## Discord-Befehle (Auszug)

Siehe `README.txt` (wird vom Bot erzeugt) bzw. `/hilfe` im Discord.
Wichtigste: `/setup token`, `/setup feeds`, `/neustart`, `/ban`,
`/whitelist add|remove|show`, `/send whitelist panel`, `/zone create`,
`/auto restart`, `/shop`, `/buy`, `/bundle add`.
