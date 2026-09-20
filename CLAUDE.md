# Sunshare Bridge – Projektkontext

Docker-Container (Python 3.12, aiohttp, paho-mqtt), der die Live-Daten eines Sunshare-Mikro-Wechselrichters mit
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
| `templates.py` | Web-UI als Python-Strings (4 Seiten, plain CSS/JS, keine Build-Abhängigkeit) |

## Entwickeln und testen

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                      # Unit-Tests (ohne Gerät/Broker); prüft u. a. die UI-JS-Syntax, falls node vorhanden
docker compose up -d --build
```

## Konventionen

- UI-Texte und Doku: Deutsch. Code und Kommentare: Englisch.
- **Berechnungen laufen auf `pvPow`/`batPow`** (Entscheidung des Autors). Die Real-Werte (`pvPreal`/`batPreal`/
  `invPreal`) werden nur angezeigt und als eigene MQTT-Sensoren veröffentlicht – nicht in Berechnungen mischen.
- `templates.py` nutzt Raw-Strings (`r"""`), damit `\n` im JS unverändert im Browser ankommt.
- Die Web-UI hat **keine Authentifizierung** und kann die Ausgangsleistung des Geräts ändern → nur im
  vertrauenswürdigen LAN betreiben (siehe README, „Sicherheit“).
- Der Regler ist standardmäßig **aus + Trockenlauf**; echte Schreibzugriffe brauchen eine Bestätigung im UI.

## Sicherheits-/Ethik-Hinweise

- Reverse-Engineering-/Interop-Arbeit ausschließlich an **eigenem Gerät und eigenem Account**.
- Zugangsdaten gehören nie in Code, Git, Issues oder Logs – nur in `.env` (ist in `.gitignore`). Raw-Logs und
  Mitschnitte vor dem Teilen auf Seriennummer, Geräte-ID und IPs prüfen.
- OTA-Endpunkte (`app/sysOtaVersion/*`) nie gegen ein echtes Gerät testen (Brick-Risiko).
- Schwachstellenverdacht am Sunshare-Backend: nicht öffentlich ausarbeiten, sondern dem Hersteller melden
  (Responsible Disclosure).
