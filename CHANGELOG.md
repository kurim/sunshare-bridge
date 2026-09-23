# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier festgehalten. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [Unreleased]

### Bridge

- Fix: Ein einzelner ausbleibender Ertragswert (`selectInveSummary` liefert `dayPower`/`totalAllPower`
  z. B. bei einem Cloud-Hänger nicht mit) hat `PV Energy Today`/`PV Energy Lifetime` auf `null`
  gesetzt statt den letzten bekannten Wert zu behalten – bei `state_class: total_increasing` wertet
  Home Assistant das als Zähler-Sprung in der Statistik. Der Poll überschreibt die Felder jetzt nur,
  wenn er tatsächlich Werte liefert.
- Kann `data/battery_energy.json` (Batterie-/PV-Zähler) beim Start nicht gelesen werden, steht das
  jetzt als Warnung im Log, statt die Zähler stillschweigend bei 0 neu zu starten.

## [1.0.3] - 2026-09-23

### Bridge

- Der HTTP-Access-Log (`aiohttp.access`, eine Zeile pro Request) ist jetzt abgeschaltet – bei
  Telemetrie-Push alle ~3 s und UI-Polling war das deutlich mehr als die eigenen, aussagekräftigen
  INFO-Zeilen. Einzelne Probleme bleiben über die jeweiligen Handler (z. B. Raw-Log) oder
  `LOG_LEVEL=DEBUG` sichtbar.
- `LOG_LEVEL` (bestand schon im Code) steht jetzt auch in `.env.example` und als Add-on-Option –
  `WARNING`/`ERROR` zeigen nur noch Probleme.

### Home Assistant

- Der Hinweis „Kein Login eingerichtet …“ erscheint nicht mehr unter Ingress – dort ist HAs eigener
  Zugriffsschutz bereits der Zugangsweg, der Hinweis gilt nur für eine direkt erreichbare UI.

## [1.0.2] - 2026-09-23

### Home Assistant

- Add-on: `repository.yaml` ergänzt (fehlte, Supervisor konnte das Repo sonst nicht als
  Add-on-Repository hinzufügen), Icon/Logo für den Add-on Store ergänzt, README-Screenshots auf
  absolute Links umgestellt (Supervisors Doku-Ansicht kennt keine Repo-Basis-URL).
- Fix: `DATA_SOURCE`/`RAW_LOG_SIZE` aus den Add-on-Optionen wurden ignoriert, weil sie erst nach
  dem Import der Module gesetzt wurden, die sie beim Start einmalig lesen – `DATA_SOURCE=cloud`
  blieb dadurch wirkungslos (UI zeigte weiter `lan` und keine Live-Daten).
- Fix: die in der UI angezeigte Version blieb unter dem Add-on immer auf `dev`, weil Supervisors
  lokaler Build die Versionsnummer als `BUILD_VERSION` übergibt, das `Dockerfile` aber nur den
  eigenen CI-Build-Arg `VERSION` kannte.

## [1.0.1] - 2026-09-23

### Behoben

- Failsafe-Ausgabe (`CONTROL_FALLBACK_W`): wurde fälschlich zusätzlich auf die Tages-Ladereserve gedeckelt
  (PV minus `CHARGE_RESERVE_W`), sodass ein konfigurierter Wert wie 200 W je nach aktueller PV-Leistung z. B. als
  120 W gesetzt wurde. Gilt jetzt wie eingestellt; nachts bleiben Tiefentladeschutz und Nacht-Deckelung weiterhin
  eine Grenze.

### Home Assistant

- Neu: Add-on mit Ingress-Unterstützung (`config.yaml`) – die UI läuft optional im HA-Frontend statt über einen
  eigenen Host-Port; Docker Compose/Standalone-Betrieb bleibt unverändert.

### Docker

- `docker-compose.yml` verwendet jetzt standardmäßig das veröffentlichte Image
  (`ghcr.io/kurim/sunshare-bridge:latest`) statt eines lokalen Builds; `build: .` bleibt als Alternative möglich.

## [1.0.0] - 2026-09-23

Erstes Release.

### Bridge

- Live-Daten des Sunshare-Mikro-Wechselrichters per Cloud-Poll oder LAN-Push-Proxy, MQTT-Veröffentlichung mit
  Home-Assistant-Discovery.
- Nulleinspeisungs-Regler: folgt einem Netzzähler per MQTT und stellt die Ausgangsleistung des Wechselrichters
  (`permPower`) darauf ein; Batterie-Plan mit Tag-Ladereserve und Nacht-Abgabe bis zu einem Tiefentladeschutz;
  Unterstützung für Haupt- und Gast-Account (Entladestopp bzw. Einspeise-Grenze am Gerät). Standardmäßig **aus und
  im Trockenlauf**, echte Schreibzugriffe brauchen eine Bestätigung im UI.
- Einspeise-Schutz: hebt die Ladereserve automatisch an, sobald der Zähler eine Einspeisung meldet, und senkt sie
  danach träge wieder ab, sobald keine mehr auftritt – nie unter den von dir konfigurierten Wert.
- PV-Tageshöchstwert, Zähler-Frische (`CONTROL_METER_MAX_AGE`) und Failsafe-Ausgabe (`CONTROL_FALLBACK_W`, gedeckelt
  vom Batterie-Plan) als im UI einstellbare Parameter.
- Langzeit-Verlauf in SQLite mit konfigurierbarer Aufbewahrung, flüchtiger Ringpuffer der rohen Geräte-Pushes.

### Web-UI

- Neue React/TypeScript-PWA: Übersicht mit Energiefluss-Diagramm, Telemetrie-Charts, Regler & Batterie-Plan,
  Roh-Log der Geräte-Pushes.
- Hell/Dunkel (folgt dem System) und Deutsch/Englisch.
- Optionaler Login (`UI_USER`/`UI_PASSWORD`) mit signiertem Session-Cookie, Rate-Limit und Origin-Prüfung.
- Versionsanzeige auf der Login-Seite und in der Kopfzeile.

### Docker

- Mehrstufiger Build (React-UI + Python-Bridge in einem Image).
- Veröffentlichung auf `ghcr.io/kurim/sunshare-bridge`: `latest` folgt `main`, ein Git-Tag `vX.Y.Z` veröffentlicht
  `vX.Y.Z` und aktualisiert `stable` auf das jeweils neueste Release.
