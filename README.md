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

## Lokal in VS Code testen

Bot **und** Dashboard laufen im **selben Prozess** und teilen sich dieselben Live-Objekte.
Wenn du also lokal testen willst, ob das Dashboard den Bot wirklich anspricht und Dinge
ändert (Zonen, Feeds, Shop, Auto-Restart …), starte den **vollen Bot**:

1. Ordner in **VS Code** öffnen, empfohlene **Python-Erweiterung** installieren
   (Vorschlag erscheint automatisch, siehe `.vscode/extensions.json`).
2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```
3. `config.json` anlegen (`cp config.example.json config.json`) und deinen
   **Discord-`bot_token`** + `guild_ids` eintragen. Tipp: nimm einen **Test-Bot**,
   damit du nicht denselben Token gleichzeitig auf PebbleHost und lokal laufen lässt
   (zwei Instanzen mit demselben Token trennen sich gegenseitig).
4. **F5** → **„Bot + Dashboard (voll – steuert den echten Bot)"**
   (oder im Terminal `python bot.py`).
5. Browser: `http://127.0.0.1:8080` → Nitrado-Token eingeben → Server wählen.
   Ab jetzt steuert jede Änderung im Dashboard den **laufenden** Bot direkt:
   z. B. ein Feed-Channel wird sofort für die Discord-Posts genutzt, eine Zone
   sofort überwacht, ein „Neustart" ruft direkt die Nitrado-API.

**Nur schnell die Oberfläche ansehen** (ohne Discord-Token)? Dann die zweite
Konfiguration **„Nur Dashboard (UI-Vorschau, ohne Discord)"** bzw.
`python bot.py --dashboard-only` nutzen. Damit funktionieren Zonen, Shop, Karte &
Feeds-Konfig; nur die Live-Channel-/Rollen-Listen bleiben leer, weil der Bot dabei
nicht bei Discord eingeloggt ist. (Es gibt nur **eine** Datei – `bot.py` – die je
nach Startargument den Vollbetrieb oder die Vorschau fährt.)

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

## Fehlerbehebung: Dashboard „nicht erreichbar“

- **`0.0.0.0` oder `127.0.0.1` im Browser → „Verbindung abgelehnt“:** Das sind
  Adressen deines **eigenen Geräts**, nicht des Servers. Öffne das Dashboard immer
  über die **öffentliche Server-Adresse** aus dem Panel, z. B.
  `http://45.143.198.35:<Port>`. Das Log-Zeile `gebunden an 0.0.0.0:<Port>` bedeutet
  nur, dass der Server auf allen Interfaces lauscht – **nicht**, dass du `0.0.0.0`
  eintippen sollst.
- **Welchen Port?** Nimm den vom Host **zugewiesenen/freigegebenen Port**
  (bei PebbleHost/Pterodactyl die Umgebungsvariable `SERVER_PORT`, sichtbar im
  Panel unter „Network“/„Allocation“). Dieser Port hat **Vorrang** vor
  `dashboard_port` in der `config.json`. Trage in der config am besten **keinen**
  eigenen Port ein, dann wird automatisch der richtige genommen.
- **`[DASHBOARD] Start fehlgeschlagen: cannot assign requested address`:** Du hast
  `dashboard_host` in der `config.json` auf eine **öffentliche IP** gesetzt – die
  kann der Container nicht binden. Lass `dashboard_host` auf `0.0.0.0` (oder
  entferne den Schlüssel). Der Bot fällt inzwischen automatisch auf `0.0.0.0`
  zurück, falls ein nicht bindbarer Host konfiguriert ist.

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
