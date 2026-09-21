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
- **Login-Sperre:** Zu viele Login-Versuche sperren den Account: `{"code":500,"msg":"Account locked Please try again in 5 minutes"}`
  (HTTP 200). Die Bridge versucht deshalb nach einem Fehlschlag nicht sofort erneut (Wartezeit aus der Meldung + 60 s,
  sonst 5 → 10 → 20 → 30 min; bei Netzfehlern 15 s), beendet sich dabei nicht (ein Absturz mit
  `restart: unless-stopped` würde den Login in Schleife wiederholen) und meldet den Fehler in der UI.
- **Trigger für Live-Daten:** Das Gerät pusht nur, solange eine „Real-Time-Session“ offen ist, geöffnet per
  `POST app/sysDeviceInfo/queryOnlineStatusByDeviceIdAndOpenRealTime` mit `{"deviceId": <id>}`. Ohne regelmäßigen
  Aufruf (Keepalive, die Bridge nutzt 3 s) ist das Gerät still. Das gilt für **beide** Datenwege unten.
- Kumulierte PV-Erzeugung (heute/gesamt): `POST app/inveRealDataMinute/selectInveSummary` (unabhängig von der
  Real-Time-Session).
- Ausgangsleistung setzen: `updateEmsParaById` (Feld `permPower`) – wird vom Nulleinspeisungs-Regler genutzt.
- Steuer-Einstellungen lesen: `POST app/sysDeviceInfo/queryMesSettingUpdate` (`mesSettingUpdatePojo.permPower`,
  `emsStrategyType`, `emsModeAdvan.countryMaxPower`; siehe „Batterie-SOC-Grenzen“ unten).

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

## Batterie-SOC-Grenzen und `NIGHT_MIN_SOC`

- **Ab Bridge-Version mit `SUNSHARE_USER_GUEST=FALSE` (Haupt-Account)** wird `NIGHT_MIN_SOC` zusätzlich als `socMin` ins
  Gerät geschrieben (auf max. 20 % begrenzt; darüber bleibt die Bridge-Logik aktiv), `countryMaxPower` ist nur dann
  änderbar. Als Gast (Default) gilt das Folgende unverändert. Die App-Route ist für den Gast-Account nicht geprüft.
- **`NIGHT_MIN_SOC` ist im Gast-Modus reine Bridge-Logik** und geht nie an Cloud oder Gerät. Der Regler (`grid_control._plan_cap`)
  setzt nachts bei `soc <= NIGHT_MIN_SOC` nur die **Ziel-Ausgangsleistung auf 0 W** (`updateEmsParaById`,
  `permPower`). Eine geräteseitige Entladegrenze wird dabei nicht verändert. Der Schutz gilt also nur, solange der
  Regler läuft (aktiviert, kein Trockenlauf, frischer Zählerwert) und schreiben kann.
- Die Geräte-Einstellung „Batteriesettings“ der App liegt in der Antwort von `queryMesSettingUpdate` unter
  `emsModeAdvan` (am eigenen Gerät bestätigt): `socMin` = Entladestopp (20), `socMax` = Ladestopp (100),
  `countryMaxPower` (800), `adVanSetType` (1), `zeroNetworkButton` (0), `deviceId` (int), `isOnlySave` (0).
  Laut Betreiber lässt die App für `socMin` höchstens 20 % zu; die Geräte-Entladegrenze kann also nicht über 20 %
  gelegt werden (ein `NIGHT_MIN_SOC` > 20 muss weiter in der Bridge laufen).
  Die Bridge wertet die Felder nicht aus. Lese-Probe: `scripts/sunshare_probe.py` (read-only, maskiert IDs).
- Schreiben, am eigenen Gerät getestet (Werte jeweils auf den aktuellen Stand bzw. `socMin` 20 → 19 → 20 zurück):
  - `updateEmsModeAdvanById` liefert bei 5 Body-Formen mit dem Lese-Schlüssel `emsModeAdvan` (verschachtelt, flach,
    `deviceId` als int/str, komplette Lese-Struktur) HTTP 200 mit `{"code":500,"msg":null}` – wie schon im
    Referenzprojekt (6 Varianten). **Ursache: falscher Wrapper-Schlüssel, siehe nächster Punkt.**
  - `updateEmsParaById` mit `mesSettingUpdatePojo` + `emsModeAdvan` (als Geschwister oder verschachtelt) antwortet
    `{"code":200,"data":true}`, **ändert `socMin` aber nicht** (Rücklesen zeigt weiter 20). Das Feld wird ignoriert.
- **Lösung (blutter auf `libapp.so`, `DeviceSsPageProvider.updateStorageAdvanceEmsData`, am eigenen Gerät
  bestätigt):** Der Body von `POST app/sysDeviceInfo/updateEmsModeAdvanById` ist nicht in `emsModeAdvan`, sondern in
  **`emsAdvanStagePojo`** verpackt (`Map<String, Map<String, int?>>`, alle Werte int):

  ```json
  {"emsAdvanStagePojo": {"deviceId": <id>, "isOnlySave": 0, "adVanSetType": 1,
                         "socMin": 20, "socMax": 100, "countryMaxPower": 800, "zeroNetworkButton": 0}}
  ```

  Antwort `{"code":200,"data":true}`; Rücklesen über `queryMesSettingUpdate` zeigt den neuen Wert sofort
  (`socMin` 20 → 19 → 20 getestet, übrige Felder und `permPower` unverändert). Es muss also das komplette Objekt mit
  den aktuellen Werten der übrigen Felder gesendet werden (vorher lesen). Das Limit `socMin` ≤ 20 % kommt von der
  App/dem Gerät (Angabe des Betreibers), nicht getestet; `socMax` wurde nicht geschrieben.
- `strings` auf `libapp.so` (iShareCloud 1.2.1, arm64): Die App kennt `app/sysDeviceInfo/updateEmsModeAdvanById`
  (kein anderer Pfad mit „Advan“/„Soc“ im Namen), die Seite `EmsBatterySettingPage` und die DTO-Klasse
  `MicroStorageEmsEmsModeAdvan` (mit `fromJson`/`toJson`; Felder wie beim Lesen: `adVanSetType`, `socMin`, `socMax`,
  `countryMaxPower`, `zeroNetworkButton`, `deviceId`, `isOnlySave`). Weitere Einstellungs-Pfade, nicht getestet:
  `deviceSetting`, `deviceSocketSetting`, `getMaxGrid`, `updateFristEmsSetByDeviceId`, `updateFirstEmsSetBySn`,
  `fristEmsSetByPersonNum` (die drei letzten wirken wie Erst-Einrichtung – nicht blind gegen das Gerät testen).
  `strings` allein verrät nicht, welcher Aufruf zur Batterie-Seite gehört; das ergab erst die Disassemblierung mit
  [blutter](https://github.com/worawit/blutter) (Dart 3.11.5, arm64; braucht `cmake ninja-build pkg-config
  libicu-dev libcapstone-dev python3-pyelftools python3-requests`, Aufruf `python3 blutter.py <lib/arm64-v8a> <out>`,
  Ausgabe unter `asm/sunshare/…`).
- Ein möglicher Grund, warum die Begrenzung über die Ausgangsleistung nicht reicht (Hypothese, ungeprüft): Die
  Steckdose (`offGridPow`) wird unabhängig von `permPower` aus dem Akku gespeist.

Quelle für den Einstieg: Recherche-Session „Night_MIN_SOC Cloud-Schreibverhalten“ (Branch
`claude/ecstatic-albattani-pqtfx1`, `docs/NIGHT_MIN_SOC_NOTES.md`; deren Schluss „nicht schreibbar“ ist durch die
Lösung oben überholt).

## Sackgassen und Warnungen

- **Geräte-MQTT:** Das Gerät hängt an einem Alibaba-Cloud-IoT-MQTT-Broker. Die Broker-ACL ist an die Geräte-
  `clientId` gebunden – Mitlesen als zweiter Client funktioniert nicht (das Gerät würde rausgeworfen). Nicht nutzbar.
- **BLE:** Die App enthält einen BLE-Stack, der laut Referenzprojekt nie verifiziert wurde; das Gerät wird per Cloud
  gesteuert. Sackgasse.
- **OTA/Firmware (`app/sysOtaVersion/*`):** Endpunkte existieren, eine Firmware-Datei ist über die App nicht
  erreichbar. **Diese Endpunkte nie gegen ein echtes Gerät testen** (Brick-Risiko).
