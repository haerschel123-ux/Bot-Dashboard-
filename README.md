# DayZ Nitrado Bot + Web-Dashboard

Ein DayZ-Server-Verwaltungsbot für Discord (Nitrado-Konsolen-Server) **mit
integriertem Web-Dashboard**. Bot und Dashboard laufen in **einem** Prozess
(`python bot.py`) und teilen sich dieselbe Konfiguration und Live-Daten – alles,
was du früher per Slash-Command gemacht hast, geht jetzt auch bequem im Browser.

## Funktionen des Dashboards

| Kategorie | Was du dort machst |
|-----------|--------------------|
| **Übersicht** | Kennzahlen & Schnellzugriff |
| **Feeds** | Jeden Log-Feed (Killfeed, Join/Leave, Chat, Basebuild …) einem Discord-Channel zuweisen – wie `/setup feeds` |
| **Zones** | Überwachte Zonen anlegen/bearbeiten – manuell **oder per interaktiver Karte** (Kreis ziehen → Position & Radius) |
| **Auto-Aufgaben** | Automatische Server-Neustarts planen (Startzeit + Intervall) |
| **Shop** | Items & **Bundles** anlegen: Name, Kategorie (mit „＋ neue Kategorie“), mehrere Items mit **Autofill**, Preis & Limit |
| **Karte** | Aktuelle Karte mit Live-Spielern und den letzten Events (Connect, Hit, Kill, Bau, Fahrzeug-/Heli-Crash …), mit ein-/ausklappbarem Filter-Panel |
| **Bans / Whitelist** | Ban- und Whitelist des Nitrado-Servers pflegen |
| **Economy** | Guthaben der Spieler ansehen & anpassen |
| **Ankündigungen** | Wiederkehrende Nachrichten planen |
| **Server** | Status ansehen, neustarten, stoppen |

## Voraussetzungen

- **Python 3.9+**
- Ein **Discord-Bot-Token** (https://discord.com/developers/applications)
- Ein **Nitrado Long-Life-Token** (Nitrado → Benutzereinstellungen → API-Schlüssel) –
  wird **nicht** in Dateien gespeichert committet, sondern im Dashboard eingegeben.

Die benötigten Python-Pakete (`discord.py`, `aiohttp`, `requests`) installiert
der Bot beim ersten Start automatisch (siehe `requirements.txt`).

## Schnellstart (lokal)

```bash
git clone <dein-repo>
cd Bot-Dashboard-
cp config.example.json config.json      # bot_token + guild_ids eintragen
python bot.py
```

Beim Start:
1. Der Bot verbindet sich mit Discord und startet das Dashboard auf dem konfigurierten Port.
2. Öffne **`http://<host>:<port>`** (Standard-Port `8080`).
3. Gib deinen **Nitrado-Token** ein → **Server auswählen** → Karte/FTP werden automatisch erkannt.
4. Fertig – alle Kategorien sind freigeschaltet.

Der Web-Port wird in dieser Reihenfolge bestimmt:
**Umgebungsvariable `SERVER_PORT` → `PORT` → `config.json` (`dashboard_port`) → 8080**.

## Deployment auf PebbleHost

1. **Dateien hochladen** (dieses Repo) bzw. per Git-Deploy in deinen PebbleHost-Server ziehen.
2. **Startbefehl** auf `python bot.py` setzen (Python-Umgebung wählen).
3. **Port**: PebbleHost weist deinem Server einen Port zu. Setze ihn entweder als
   Umgebungsvariable `SERVER_PORT` **oder** trage ihn in `config.json` als
   `"dashboard_port": <zugewiesener Port>` ein. Der Bot bindet das Dashboard an
   `0.0.0.0:<Port>`.
4. **Aufrufen**: Das Dashboard ist dann unter `http://<deine-server-ip>:<Port>` erreichbar.
5. `config.json` bleibt auf dem Server (nicht im öffentlichen Repo – siehe `.gitignore`).

> Falls dein Tarif keinen öffentlich erreichbaren HTTP-Port bereitstellt, ist das
> Dashboard nur intern erreichbar. In dem Fall einen Tarif mit freiem Port bzw.
> einen kleinen VPS nutzen.

## Kartenbilder (interaktive Karte)

Die Karte erkennt automatisch die aktive Map (Chernarus, Livonia, Sakhal) und zeigt
den Hintergrund in dieser Reihenfolge:

1. **Kachel-URL** aus `config.json → dashboard_map_tiles`, z. B.
   ```json
   "dashboard_map_tiles": { "ChernarusPlus": "https://dein-tileserver/{z}/{x}/{y}.png" }
   ```
2. **Eigenes Bild**: lege eine Datei `dashboard/static/maps/<Karte>.jpg` ab
   (`ChernarusPlus.jpg`, `Livonia.jpg`, `Sakhal.jpg`). Sie wird passgenau über die
   Weltgröße gelegt.
3. **Schematische Karte** mit echten Ortsnamen (Fallback) – funktioniert immer,
   auch ohne Bild/Internet.

So bleibt die Karte immer nutzbar; für „echte“ Optik reicht es, ein Kartenbild in den
`maps`-Ordner zu legen oder eine Kachel-URL einzutragen.

## Sicherheit

Das Dashboard ist – wie gewünscht – **nur über den Nitrado-Token** abgesichert:
Ohne gültigen Token kommt man nicht hinein. Da das Dashboard den Server neustarten
kann, halte die URL/den Port **privat**. Ein optionaler Passwort-Schutz ist im Code
vorbereitet (`dashboard/auth.py`) und kann später aktiviert werden.

## Hinweise

- **Heli-/Zug-Events**: Der Bot liest die `.ADM`-Logs. Helikopter-Crashes werden best
  effort erkannt; „Zug-Unfall“ und exakte Crash-Site-Koordinaten stehen meist nur in
  der `.RPT`-Datei – diese Events erscheinen als umschaltbarer Filter, Marker nur wenn
  Koordinaten ableitbar sind. (`.RPT`-Auswertung ist als spätere Erweiterung möglich.)
- **Ein Server pro Bot**: Nitrado/FTP/Economy gelten global; die Feed-Channel-Zuordnung
  ist pro Discord-Guild.
- Discord-Slash-Commands funktionieren unverändert weiter – das Dashboard ist ein
  zusätzlicher Weg, keine Ersetzung.
