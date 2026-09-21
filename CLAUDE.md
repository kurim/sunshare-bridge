# Sunshare Bridge – Projektkontext

Docker-Container (Python 3.12, aiohttp, paho-mqtt; UI: React/TypeScript in `frontend/`), der die Live-Daten eines Sunshare-Mikro-Wechselrichters mit
Batterie ausliest (Cloud-Poll oder LAN-Push-Proxy), per MQTT mit Home-Assistant-Discovery veröffentlicht und eine
Web-UI, einen Langzeit-Verlauf und einen Nulleinspeisungs-Regler bietet. Nutzer-Doku: `README.md`. Gerätewissen
(Endpunkte, Datenfelder, empirische Erkenntnisse, Sackgassen): `docs/DEVICE_NOTES.md` – bei Änderungen an der Feld-
Interpretation dort nachziehen.

## Architektur (`app/`)

| Datei | Aufgabe |
|---|---|
| `main.py` | Einstieg: LAN-Proxy (Port 80), Web-UI (Port 8099), Keepalive-, Cloud-Poll- und Energie-Poll-Loop, Regler – alles in einem asyncio-Prozess |
| `sunshare_cloud.py` | Login, `openRealTime`-Keepalive, AES-Cloud-Read, Leistung setzen |
| `lan_proxy.py` | Transparenter Reverse-Proxy: wertet den Telemetrie-Push aus, reicht **alles** unverändert an `web.sunsharetek.com` weiter, schreibt `raw_log` |
| `models.py` | `normalize_cloud()` / `normalize_lan()` → gemeinsames Schema |
| `state.py` | Letzter Messwert (gemerged), Energie-Integration (Trapezregel), abgeleitete Werte (`exportPow`, `batCharge/DischargePow`, `meterPow`), SSE-Broadcast, Lade-Effizienz-Basis |
| `mqtt_publisher.py` | State-Topic + HA-Discovery (`_SENSORS`) |
| `grid_control.py` | Nulleinspeisungs-Regler + Batterie-Plan; Parameter (`PLAN_SETTINGS`) zur Laufzeit änderbar, in `data/control.json` gespeichert |
| `history_db.py` | Langzeit-Verlauf: ein Ø-Wert/Minute in SQLite (`data/history.db`), Migration fehlender Spalten |
| `raw_log.py` | Flüchtiger Ringpuffer der rohen Geräte-Pushes (`/raw`) |
| `env_view.py` | Read-only-Sicht auf die `.env` (Passwörter maskiert) |
| `auth.py` | Single-User-Login (`UI_USER`/`UI_PASSWORD`), signiertes Session-Cookie, Rate-Limit, Origin-Prüfung; Middleware schützt UI + API |
| `spa.py` | Liefert die gebaute React-App unter `/app/` aus (SPA-Fallback, Cache-Header) |
| `frontend/` | React + Vite + TypeScript, PWA (Manifest, `public/sw.js`); Build im Multi-Stage-`Dockerfile`, Ausgabe nach `app/web` |

## Entwickeln und testen

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                      # (mit globalen HA-/pytest-socket-Plugins: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest) Unit-Tests (ohne Gerät/Broker)
cd frontend && npm ci && npm test && npm run build   # React-UI (Build auch im Docker-Build); npm run dev = Dev-Server
docker compose up -d --build
```

## Konventionen

- UI-Texte und Doku: Deutsch. Code und Kommentare: Englisch.
- **Berechnungen laufen auf `pvPow`/`batPow`** (Entscheidung des Autors). Die Real-Werte (`pvPreal`/`batPreal`/
  `invPreal`) werden nur angezeigt und als eigene MQTT-Sensoren veröffentlicht – nicht in Berechnungen mischen.
- Die Web-UI kann die Ausgangsleistung des Geräts ändern. Login nur, wenn `UI_USER`/`UI_PASSWORD` gesetzt sind; ohne
  sie **keine Authentifizierung** → nur im vertrauenswürdigen LAN. Für Zugriff von außen (Cloudflare Tunnel) ist der
  Login Pflicht, und der Tunnel darf nur auf den UI-Port zeigen (nie auf den LAN-Proxy-Port 80). Siehe README,
  „Sicherheit“.
- **Frontend-Texte:** kein fest verdrahteter UI-Text in den Komponenten – alles über `t("schlüssel")` aus
  `frontend/src/i18n/` (`de.ts` ist die Quelle der Schlüssel, weitere Sprachen ziehen nach; `npm run build` prüft Schlüssel
  und `{Platzhalter}`). Zahlen über `fmt()` (folgt der Sprache).
- **Backend-Texte:** das Backend baut keine Sätze für die UI, sondern `Msg("schlüssel", "ok"|"warn"|"error"|"info", param=…)`
  (`app/messages.py`, englische Vorlage für Logs/API). Neuer Text = Schlüssel in `messages.EN` + `msg.<schlüssel>` in
  `de.ts` und `en.ts` (gleiche `{Platzhalter}`); `tests/test_messages.py` erzwingt das. Die Farbstufe (`level`) kommt vom
  Backend – nie im Frontend nach Wörtern im Text suchen. Abgelehnte Eingaben: `MsgError` (die API liefert `error` + `msg`).
- **Frontend-Farben:** nur über CSS-Variablen aus `styles.css` (`--bg`, `--card`, `--accent`, Serienfarben `--c-pv`,
  `--c-bat`, …), keine festen Hex-Werte in Komponenten – sonst stimmt der Hell/Dunkel/Auto-Umschalter (`theme.ts`,
  `data-theme` am `<html>`; Auto = Attribut fehlt) nicht. In SVG die Farben per `style`, nicht als Attribut setzen
  (Attribute nehmen kein `var()`).
- **Energiefluss-Diagramm** (`components/EnergyFlow.tsx`, Zuordnung in `flows.ts`, Tests mit `npm test`): Solar = `pvPow`,
  Batterie = `batPow` (+ entlädt), Netz = `meterPow` (+ Bezug, braucht den MQTT-Zähler), Zuhause = Zähler + WR-Ausgang (ohne
  Zähler nur WR-Ausgang, mit Hinweis). Das Gerät misst nur Summen: die Leitungen zwischen den Knoten sind eine **Zuordnung**
  (Solar lädt zuerst die Batterie, der gemessene WR-Ausgang geht an Haus, dann Netz; das Netz deckt den Rest). Änderungen an
  `flows.ts` brauchen einen Test. Linien unter 5 W sind ruhig; `prefers-reduced-motion` schaltet die Animation ab.
- **iOS-PWA:** Sicherheitsabstände nur über `--sat`/`--sab` (`styles.css`), nie `env(safe-area-inset-*)` direkt für oben/unten
  (so lassen sie sich im Test überschreiben). Installiert auf iOS (`html.is-ios.is-standalone`, gesetzt in `index.html`) gibt es
  den Streifen `#status-bar-tint` gegen den Blur der iOS-27-Beta; Eingabefelder haben auf Touch-Geräten 16 px (sonst zoomt iOS).
- **iOS-Startbilder** (`public/splash/*.png` und die `apple-touch-startup-image`-Tags in `index.html`) sind erzeugt:
  `python3 frontend/scripts/make-splash.py` (Pillow) statt von Hand ändern; iOS braucht pro Gerätegröße ein exakt passendes Bild.
- **Frontend-Layout:** Handy = eine Spalte + untere Tab-Leiste mit Icons, ab 900 px Navigation in der Kopfzeile und
  Zwei-Spalten-Raster (`.col`, `*-grid` in `styles.css`); jede Seite muss bei 390 px ohne waagerechtes Scrollen passen.
- **Frontend:** neue Seiten kommen in `frontend/` (React + TS, mobile-first, Light/Dark über `prefers-color-scheme`);
  der Service Worker cached nur die App-Shell, **nie** `/api/*`. Die Adressen der früheren Oberfläche (`/`, `/flow`,
  `/control`, `/raw`) leiten auf `/app/…` um (`LEGACY_REDIRECTS` in `main.py`).
- Der Regler ist standardmäßig **aus + Trockenlauf**; echte Schreibzugriffe brauchen eine Bestätigung im UI.
- **Haupt- vs. Gast-Account** (`SUNSHARE_USER_GUEST`, Default `TRUE`): Nur mit dem Haupt-Account (`FALSE`) schreibt die
  Bridge `NIGHT_MIN_SOC` als Entladestopp `socMin` (max. 20 %) ins Gerät (`updateEmsModeAdvanById`) und darf
  `countryMaxPower` ändern; als Gast setzt die Bridge `NIGHT_MIN_SOC` selbst um. Auch diese Geräte-Schreibzugriffe
  laufen nur bei aktivem Regler ohne Trockenlauf.

## Sicherheits-/Ethik-Hinweise

- Reverse-Engineering-/Interop-Arbeit ausschließlich an **eigenem Gerät und eigenem Account**.
- Zugangsdaten gehören nie in Code, Git, Issues oder Logs – nur in `.env` (ist in `.gitignore`). Raw-Logs und
  Mitschnitte vor dem Teilen auf Seriennummer, Geräte-ID und IPs prüfen.
- OTA-Endpunkte (`app/sysOtaVersion/*`) nie gegen ein echtes Gerät testen (Brick-Risiko).
- Schwachstellenverdacht am Sunshare-Backend: nicht öffentlich ausarbeiten, sondern dem Hersteller melden
  (Responsible Disclosure).
