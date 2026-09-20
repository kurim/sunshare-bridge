# Gerätewissen (Reverse-Engineering-Notizen)

Was über die Sunshare-Cloud, den Wechselrichter und die Datenfelder bekannt ist – die Grundlage der Bridge.
Alles ist **empirisch** ermittelt (Analyse der iShareCloud-App, Mitschnitte am eigenen Gerät) und kann sich mit
Firmware- oder Backend-Änderungen ändern. Gemessen wurde an einem Sunshare-Mikro-Wechselrichter mit Batterie
(2 PV-Eingänge, Steckdosen-Ausgang), `deviceType` `"2"`.

Die Basis-Endpunkte und die Verschlüsselung stammen aus dem Projekt
[DelphiXE5/homeassistant-sunshare](https://github.com/DelphiXE5/homeassistant-sunshare)
(`API_DOCUMENTATION.md`; laut dessen README KI-erstellt und nicht vollständig auditiert – „bestätigt“ heißt dort
„zum Testzeitpunkt bestätigt“). Die App selbst ist eine Flutter-App (`com.sunshare.cloud`); ihr Code steckt im
kompilierten Dart-Snapshot, Pfade und Klassennamen lassen sich per `strings` auf `libapp.so` auslesen.

## Cloud-API

- Host: **`https://web.sunsharetek.com/app/`** (`iot.sunsharetek.com` und `dev.sunsharetek.com` existieren, lehnen
  aber echte Account-Zugangsdaten ab).
- Login: `POST auth/login` mit `{"userAccount": "...", "password": "..."}` →
  `{"code":200,"data":{"access_token":"..."}}`. Das Token geht als `Authorization`-Header mit (ohne `Bearer `).
- **Eine aktive Session pro Account:** Ein neuer Login (App oder Skript) beendet jede andere Session dieses Accounts
  sofort (HTTP 401). Ein **eingeladener Nutzer-Account** (zweiter Account, der in der App zum Gerät eingeladen wird)
  reicht der Bridge aus – dann bleibt die Handy-App mit dem Hauptaccount eingeloggt.
- **Trigger für Live-Daten:** Das Gerät pusht nur, solange eine „Real-Time-Session“ offen ist, geöffnet per
  `POST app/sysDeviceInfo/queryOnlineStatusByDeviceIdAndOpenRealTime` mit `{"deviceId": <id>}`. Ohne regelmäßigen
  Aufruf (Keepalive, die Bridge nutzt 3 s) ist das Gerät still. Das gilt für **beide** Datenwege unten.
- Kumulierte PV-Erzeugung (heute/gesamt): `POST app/inveRealDataMinute/selectInveSummary` (unabhängig von der
  Real-Time-Session).
- Ausgangsleistung setzen: `updateEmsParaById` (Feld `permPower`) – wird vom Nulleinspeisungs-Regler genutzt.

## Zwei Wege zu den Live-Daten

1. **Cloud (AES):** `POST app/sysDeviceInfo/systemDiagramUpdate` mit Header `encchannel: 1`. Request und Response
   sind `{"encryptData": base64(AES-128-ECB(JSON))}`, **statischer Schlüssel `sunsharesunshare`** (16 ASCII-Bytes),
   PKCS7-Padding, keine IV. Request-JSON: `{"clientId":"GID_sun@@@<SN>","deviceId":<id>}`.
2. **LAN (Klartext):** Das WLAN-Modul des Geräts (ESP32, `User-Agent: ESP32 HTTP Client/1.0`) sendet etwa alle 3 s
   **unverschlüsselt per HTTP (Port 80)** ein JSON an
   `http://web.sunsharetek.com/collect-service/collect/emsRealDataMinute/realTimeElectricFlow` – ohne
   `Authorization`. Der Server antwortet immer `{"msg":"success","code":200}`. Genau diesen Traffic leitet die
   NAT-Regel (siehe README) auf die Bridge um, die ihn auswertet und unverändert weiterreicht.

## Felder der Live-Daten

Beispiel-Push (Werte in Watt, `soc` in %, `time` = Epoch-Millisekunden):

```json
{"clientId":"GID_sun@@@<SN>","deviceType":"2","time":1789907199027,
 "pvPow":0,"pv1Pow":0,"pv2Pow":25,"offGridPow":0,"otherPow":0,"batPow":0,"loadPow":0,"invPow":0,"gridPow":0,
 "pvPreal":25,"batPreal":-3,"invPreal":-1,"smtdP":0,"iPa":null,"iPb":null,"iPc":null,"soc":18,"bhs":0}
```

| Feld | Bedeutung (empirisch) |
|---|---|
| `pv1Pow`, `pv2Pow` | Leistung der beiden PV-Eingänge |
| `pvPreal` | echte PV-Summe (= `pv1Pow` + `pv2Pow`) |
| `pvPow` | „gebuchte“ PV-Leistung (ins System geflossen, zeitweise 0 bei Schwachlicht) |
| `batPow` | „gebuchte“ Batterieleistung an der PV/Wechselrichter-Seite; **+ = entladen, − = laden** |
| `batPreal` | echte Batterieleistung (gleiches Vorzeichen); beim Laden ≈ 0,82 · `batPow` (Wandlungsverlust) |
| `invPow` | Gesamtabgabe des Wechselrichters (Steckdose + Abgabe ins Hausnetz) |
| `loadPow` | folgt `invPow` – **nicht** der Hausverbrauch |
| `offGridPow` | tatsächliche Last an der **Steckdose** |
| `gridPow` | Netz **durch die Steckdose** (+ = Netz speist die Steckdose; kurz − beim Umschalten), sonst 0 |
| `soc` | Batterie-Ladezustand in % |
| `invPreal` | ≈ `invPow`; `otherPow`, `smtdP` immer 0; `iPa/iPb/iPc` null; `bhs` 0 |

Abgeleitet (wird von der Bridge berechnet):

- **Abgabe ins Hausnetz** = `invPow − offGridPow` (Rauschen ≤ 3 W ignoriert) → Feld/Sensor `exportPow`. Beim
  Test mit aktivierter Abgabe: 113 W Gesamtabgabe, 33 W an der Steckdose ⇒ ~80 W ins Hausnetz.
- **Was speist die Steckdose?** Akku: `batPow` > 0 · PV: `pvPow` > 0 · Netz-Durchleitung: `gridPow` > 0.

Beobachtungen aus Mitschnitten (26 min, ~100–140 W PV):

- `pvPow`/`batPow` springen (z. B. `pvPow` 34 ↔ 89 W bei konstant ~90 W an `pv2Pow`), die Real-Werte bilden die
  echte Schwankung ab und sind **nicht** ruhiger (mittlere Änderung je Messung: PV 12,5 → 18,6 W, Akku 12,0 →
  31,7 W). Gleitender Durchschnitt über ~20 s beruhigt die Anzeige.
- Energie über den Zeitraum: PV `pvPow` 33,1 Wh vs. `pvPreal` 39,0 Wh (−15 %); Batterie geladen `batPow` 19,1 Wh vs.
  `batPreal` 18,3 Wh (−4 %). Erträge aus `pvPow` sind bei Schwachlicht also zu niedrig, Batteriezähler aus `batPow`
  liegen nah an den Real-Werten. Die Bridge rechnet deshalb weiter mit `pvPow`/`batPow` und stellt die Real-Werte
  zusätzlich als eigene Sensoren bereit.
- Die Live-Kacheln der iShareCloud-App zeigen `pvPow`/`batPow`, ihre Verlaufs-Charts die Real-Werte.
- Tagsüber schaltet der Wechselrichter periodisch (etwa alle 33 s für ein Sample) auf Netz-Durchleitung um.

## Sackgassen und Warnungen

- **Geräte-MQTT:** Das Gerät hängt an einem Alibaba-Cloud-IoT-MQTT-Broker. Die Broker-ACL ist an die Geräte-
  `clientId` gebunden – Mitlesen als zweiter Client funktioniert nicht (das Gerät würde rausgeworfen). Nicht nutzbar.
- **BLE:** Die App enthält einen BLE-Stack, der laut Referenzprojekt nie verifiziert wurde; das Gerät wird per Cloud
  gesteuert. Sackgasse.
- **OTA/Firmware (`app/sysOtaVersion/*`):** Endpunkte existieren, eine Firmware-Datei ist über die App nicht
  erreichbar. **Diese Endpunkte nie gegen ein echtes Gerät testen** (Brick-Risiko).
