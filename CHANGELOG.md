# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier festgehalten. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

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
- PV-Tageshöchstwert und Zähler-Frische (`CONTROL_METER_MAX_AGE`) als im UI einstellbare Parameter.
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
