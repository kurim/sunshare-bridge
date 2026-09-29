# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier festgehalten. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [1.1.3] - 2026-09-29

### Bridge

- Fix: Der Ausgang blieb über eine Stunde bei 0 W, obwohl das Haus 300 W aus dem Netz zog und die ganze PV in den Akku
  ging – im Chart wirkte es wie ein Problem von „Netzlast abdecken“. Ursache war die Anhebung des Exportschutzes: Ein
  einzelner großer Export (~700 W, der Ausgang war nach einer Änderung in der App gesprungen) hob die Ladereserve um
  genau diesen Betrag an (855 statt 200 W, Statuszeile „Exportschutz 645 W“). Die Anhebung ging nur 10 W pro 10 Minuten
  zurück und übersteht einen Neustart; sie wird von der PV abgezogen (bei „Netzlast abdecken“ ebenso wie in der
  normalen Ladephase), der Deckel lag dadurch bei 0. Ein Ändern der Ladereserve im UI setzte sie zurück – das erklärt,
  warum Aus- und Wiedereinschalten „half“. Jetzt gibt die Anhebung bei Netzbezug nach: um den Bezug (über Zielwert +
  Totzone), höchstens einmal pro Minute und nie unter die eingestellte Reserve. Das langsame Absenken ohne Bezug
  bleibt. Im Debug-Log: „Bezug … – Exportschutz-Anhebung zurückgenommen“.

## [1.1.2] - 2026-09-29

### Bridge

- Fix: Der Regler hing bei 110 W fest, obwohl mehr PV anlag. Der Tages-Deckel (PV minus Reserve bzw. Exportschutz)
  wurde aus `pvPow` berechnet, dem *gebuchten* Wert: Nimmt der Akku keinen Überschuss auf, ist er gleich der aktuellen
  Abgabe (Mitschnitt: `pvPow` 110 = Ausgang 110, `pvPreal` 135). Der Deckel konnte dadurch nie über den Sollwert
  steigen; bei 137 W Sollwert lieferte der Wechselrichter sofort 136 W. Der Deckel nutzt jetzt das PV-*Angebot*:
  `pvPreal` (LAN), sonst PV1 + PV2, sonst `pvPow` (Cloud liefert kein `pvPreal`). Erträge, Batteriezähler und
  Energiefluss bleiben auf `pvPow`/`batPow`.
- Fix: Bei stark steigender PV lag der Sollwert bis zu eine Minute hinter der PV, und die Differenz lud den Akku, obwohl
  das Haus 1400 W aus dem Netz zog. Der „niedrigste PV-Wert“ (1.1.0) sah dafür die letzte Regel-Spanne zurück; jetzt
  nur noch 20 s – genug, um das Zittern im Sekundentakt zu filtern, ohne einer steigenden PV nachzuhängen.
- Neu: Reduzieren wartet nicht mehr auf den Mindestabstand. Fällt der Zähler unter den Zielwert (Ausgang über dem
  Hausverbrauch, etwa wenn ein großer Verbraucher ausgeht), geht die Korrektur 20 s nach der letzten Schreibung raus,
  sobald ein neuer Zähler-Wert seit dieser Schreibung eingetroffen ist. Vorher blieb der Ausgang bis zu 60 s + einen
  weiteren Zähler-Takt zu hoch, das Haus speiste ein oder lud den Akku unnötig. Erhöhen bleibt beim Mindestabstand
  (60–120 s). Ein so vorgezogener Schritt trainiert die adaptive Verstärkung nicht mit; im Debug-Log steht er als
  „ohne Wartezeit reduziert“.
- Debug-Log: zeigt „PV“ (Angebot) und, wenn abweichend, „PV gebucht“.

## [1.1.1] - 2026-09-29

### Bridge

- Neu: Die Abfrage-Intervalle `ENERGY_POLL_INTERVAL` (summierter PV-Ertrag aus der Cloud) und `CLOUD_POLL_INTERVAL`
  (Live-Werte, nur Cloud-Modus) sind jetzt im UI einstellbar (System-Konfiguration), gelten ohne Neustart (spätestens
  nach 5 s, auch wenn vorher ein langes Intervall lief) und liegen wie die anderen Einstellungen in `data/settings.db`;
  die `.env` liefert nur den Default. Grenzen: Ertrag 5–3600 s, Live-Werte 0,5–60 s. Hinweis: Das ist nicht der Takt
  des Netzzählers – den bestimmt der Zähler selbst. `KEEPALIVE_INTERVAL` und `WEATHER_POLL_INTERVAL` bleiben in der
  `.env` (ein zu langes Keepalive-Intervall würde den Geräte-Push beenden).
- Fix: Die Regler-Statuszeile („übersprungen: Mindestabstand“) und das Debug-Log meldeten den Mindestabstand auch dann,
  wenn gar nichts zu schreiben gewesen wäre – etwa wenn der Deckel (PV) den Sollwert ohnehin auf dem aktuellen Wert
  hielt (Zähler-Bezug, Wechselrichter liefert schon alles, was die PV hergibt). Jetzt steht dort „Sollwert X W
  unverändert“; „übersprungen: Mindestabstand“ erscheint nur noch, wenn ein anderer Wert hätte gesendet werden
  müssen. Am Regelverhalten ändert das nichts, nur an der Anzeige.

## [1.1.0] - 2026-09-29

### Bridge

- Neu: Tab **Debug** (`/app/debug`) – ein Protokoll dessen, was der Regler gesehen und entschieden hat, damit sich
  Kurven im Leistungs-Chart nachvollziehen lassen: jeder Zähler-Wert (mit PV/WR/Akku/SOC in dem Moment), jeder
  Regelschritt mit den Werten dahinter (Zähler, PV, „PV min.“, Deckel, Abweichung, Sollwert) und seiner Entscheidung,
  jeder Schreibzugriff, Phasenwechsel, Exportschutz-Anhebung, vom Gerät übernommener Ausgang (Änderung in der App),
  Failsafe und Einstellungsänderungen. Filter nach Art und Text, Pause, JSON-Download. Nur im Speicher (letzte 3000
  Einträge, nach einem Neustart leer); Regelschritte und Schreibzugriffe entstehen nur bei aktivem Regler.

## [1.0.19] - 2026-09-29

### Bridge

- Doku/UI: „Netzlast abdecken“ hat Vorrang vor der Ladereserve – solange der Schalter an ist, wird `CHARGE_RESERVE_W`
  tagsüber nicht angewendet und die Batterie lädt nur mit echtem PV-Überschuss (bei Netzbezug des Hauses praktisch
  gar nicht). Das steht jetzt in den Hilfetexten von „Ladereserve“ und „Netzlast abdecken“, in der Regler-Statuszeile
  („Ladereserve ruht“) und im README. Verhalten unverändert.
- Neu: Der Tages-Deckel (PV minus Ladereserve, bei „Netzlast abdecken“ PV minus Exportschutz, bei vollem Akku PV
  minus Erhaltungsladung) wird jetzt aus dem **niedrigsten PV-Wert der letzten `CONTROL_MIN_INTERVAL`-Spanne**
  berechnet statt aus dem aktuellen. Der Sollwert bleibt bis zum nächsten Zähler-Sample stehen, die PV schwankt aber im
  Sekundentakt; ein Einbruch dazwischen wurde bisher vom Akku gedeckt (kurze Entlade-Ausschläge mitten in der
  Ladephase). Nachts ohne Wirkung. Folge: bei stark schwankender PV liegt der Sollwert etwas tiefer, der Akku bekommt
  entsprechend etwas mehr.

## [1.0.18] - 2026-09-29

### Bridge

- Geändert: Was im UI eingestellt wird (Regler-Parameter, Schalter, gelernte Verstärkung, Ladereserve-Basis), liegt
  jetzt in einer SQLite-Datenbank `data/settings.db` statt in `data/control.json`. Das frühere `control.json` wird
  beim ersten Start übernommen und zu `control.json.migrated` umbenannt.
  - Nur Abweichungen von den `.env`-/Add-on-Defaults werden gespeichert und haben Vorrang. Bisher fror der erste
    Speichervorgang alle Parameter ein, ein später geänderter Default hatte dann auch bei nie angefassten Werten
    keine Wirkung mehr; jetzt folgt jeder nicht geänderte Wert weiter der `.env`. Ein Wert, der wieder dem Default
    entspricht, wird nicht mehr festgehalten.
  - Ein einzelner nicht mehr gültiger gespeicherter Wert (z. B. nach einer verengten Grenze in einem Update) wird
    mit Warnung übersprungen; früher wurden dadurch **alle** gespeicherten Parameter still verworfen und die
    `.env`-Werte galten wieder.
  - Jedes Speichern ist eine Transaktion. `control.json` wurde ohne Absicherung überschrieben; eine abgebrochene
    Schreibung ließ eine unlesbare Datei zurück, die still als „nichts gespeichert“ galt.

## [1.0.17] - 2026-09-29

### Bridge

- Fix: Der Failsafe (Zähler meldet nichts mehr) lief nur ein einziges Mal pro Ausfall. Fiel der Zähler abends aus –
  noch in der Tagphase, ohne PV, Deckel 0 W –, blieb der Ausgang auf 0 W, auch als um 23:00 das Nachtfenster begann,
  in dem `CONTROL_FALLBACK_W` (bis `NIGHT_MAX_W`) erlaubt gewesen wäre; umgekehrt hätte ein Nachtwert in den Morgen
  hineingewirkt. Der Failsafe wird jetzt alle `CONTROL_METER_MAX_AGE` neu berechnet, solange der Zähler fehlt, und
  schreibt nur, wenn sich der Zielwert ändert (ein fehlgeschlagener Schreibzugriff wird beim nächsten Durchlauf
  wiederholt; Wiederholungen nie schneller als `CONTROL_MIN_INTERVAL`).
- Neu: Der Regler liest den Ausgangs-Sollwert des Geräts alle 5 Minuten zurück und übernimmt eine Abweichung
  (z. B. eine manuelle Änderung in der offiziellen App). Bisher kannte er nur, was er selbst geschrieben hatte:
  Errechnete er danach denselben Wert wie vorher, hielt er ihn für unverändert und ließ das Gerät auf dem App-Wert.
  Nicht im Trockenlauf und nicht in den ersten 2 Minuten nach einem eigenen Schreibzugriff (das Gerät zeigt den
  neuen Wert evtl. noch verzögert); der Failsafe setzt seinen Zielwert nach einer Änderung von außen erneut.
- Fix (#26): Der Regler blieb bei „ok: Wechselrichter am Limit“ dauerhaft hängen. Lieferte der Wechselrichter weniger
  als befohlen, galt das für immer als PV-/Akku-Grenze – auch wenn das Gerät aus einem anderen Grund nichts abgab
  und das Haus stundenlang Netzstrom zog; nur Trockenlauf an/aus (schreibt den alten Wert neu) half. Die Annahme
  gilt jetzt nur noch 5 Minuten; danach wird der Sollwert – aus der tatsächlichen Abgabe neu berechnet – erneut
  gesendet (auch wenn er gleich bleibt) und die Wartezeit beginnt von vorn. Eine echte Grenze kostet so höchstens
  einen Schreibzugriff alle 5 Minuten; die adaptive Regelung lernt aus diesem erneuten Senden nicht.
- Neu (#26): Ist ein „Limit“ unwahrscheinlich – der Akku liegt über dem Entladestopp (20 % + 3), lädt nicht (> 20 W)
  und die PV deckt den Sollwert nicht allein, oder die PV reicht allein –, wartet der Regler nur 2 statt 5 Minuten
  (Status „wartet: Wechselrichter liefert … obwohl PV/Akku mehr hergeben könnten“). Fehlen SOC/PV/Akku-Werte,
  bleibt es bei 5 Minuten.
- Neu (#26): Der Sollwert des Reglers wird im Verlauf mitgeschrieben (Spalte `setpointW` in `history.db`, ältere
  Datenbanken werden automatisch ergänzt) und als Kurve „Sollwert“ im Leistungs-Chart angezeigt – nur solange der
  Regler aktiv ist und nicht im Trockenlauf. Eine dauerhafte Lücke zur WR-Abgabe macht solche Fälle nachvollziehbar.

## [1.0.16] - 2026-09-28

### Bridge

- Fix: Die Regler-Einstellung „Ladereserve“ (`CHARGE_RESERVE_W`) zeigte im UI und in der gespeicherten
  Konfiguration den *aktuellen* Wert – inklusive einer temporären Anhebung durch den Einspeise-Schutz
  (`_guard_against_export`) nach einer beobachteten Einspeisung. Dadurch stand im Formular z. B. 614 W statt
  der selbst eingestellten 210 W, und weil das Formular beim Speichern immer alle Felder mitsendet, wurde
  diese vorübergehende Anhebung bei jeder Speicherung eines *beliebigen* anderen Feldes unbemerkt als neue
  dauerhafte Basis übernommen – der eigentliche Wert von 210 W ging dabei verloren. Das Formular zeigt und
  speichert jetzt immer die eigene Basis; die aktuelle Anhebung bleibt weiterhin im Regler-Status („Exportschutz
  X W“) sichtbar und übersteht wie gehabt einen Neustart.

## [1.0.15] - 2026-09-27

### Bridge

- Neu: `CHARGE_TRICKLE_W` (Default 5 W, im UI einstellbar). Ist der Akku laut Plan „voll“
  (`CHARGE_FULL_SOC`), reichte der Regler bisher die komplette PV-Leistung durch, auch die letzten paar Watt
  bei sinkender Sonne – der Akku bekam dann nichts mehr ab und konnte über den eigenen Standby-Verbrauch des
  Geräts langsam leerlaufen. Jetzt bleiben auch in dieser Phase `CHARGE_TRICKLE_W` für die Batterie zurück;
  bei PV unter diesem Wert geht alles in den Akku statt in den Ausgang.
  
## [1.0.14] - 2026-09-27

### Bridge

- Fix: Der Regler prüfte den Mindestabstand zwischen zwei Geräte-Schreibzugriffen (`CONTROL_MIN_INTERVAL`),
  bevor er überhaupt festgestellt hatte, ob eine Korrektur nötig ist. Dadurch zeigte die Statuszeile fast
  durchgehend „übersprungen: Mindestabstand“ (gelb), selbst wenn der Regler längst eingeschwungen war und
  ohnehin nichts geschrieben hätte – „ok“-Zustände (Totzone erreicht, PV-/Akku-limitiert) waren dadurch kaum
  je zu sehen. Der Mindestabstand greift jetzt erst, nachdem feststeht, dass tatsächlich eine Korrektur ansteht.
  Ein plötzlich sinkender Plan-Deckel (Akku wird voll, PV bricht ein) zieht die Ausgangsleistung wie schon
  beabsichtigt weiterhin sofort runter, ohne auf den Mindestabstand zu warten.

## [1.0.13] - 2026-09-25

### Bridge

- Neu: Die Batterie-Kachel in der Übersicht zeigt beim Laden jetzt „voll in ~X h“ (Schätzung des Reglers,
  siehe `cc.est.full` im Regler-Tab) statt gar keinen Hinweis zu zeigen – der Wert basiert auf `CHARGE_RESERVE_W`
  und steht unabhängig davon zur Verfügung, ob der Regler aktiv ist.
- Fix: Läuft die Bridge gleichzeitig als HA-Add-on und separat per `docker compose` gegen denselben MQTT-Broker,
  hatten beide Instanzen dieselbe feste MQTT-Client-ID (`sunshare-bridge-gridctl` bzw. `sunshare-bridge-<device_id>`)
  – der Broker hat sie deshalb im Sekundentakt gegenseitig rausgeworfen („session taken over“). Die Client-ID trägt
  jetzt den Container-Hostnamen als Suffix, der sich zwischen zwei Containern automatisch unterscheidet.

## [1.0.12] - 2026-09-25

### Bridge

- Neu: `MQTT_PUBLISH` (Default `TRUE`). Auf `FALSE` gesetzt liest die Bridge einen konfigurierten Broker weiterhin
  für den Regler (externer Netzzähler), veröffentlicht selbst aber nichts mehr (kein Home-Assistant-Discovery,
  kein State-Topic) – für einen Broker, der nur zum Lesen da sein soll, ohne `MQTT_HOST` komplett zu leeren (das
  hätte auch den Regler lahmgelegt, siehe 1.0.11).
- Fix: Die Zähler-Kachel im animierten Energiefluss-Diagramm zeigte bei kleinen Beträgen (< 5 W) den Betrag ohne
  Vorzeichen und ohne „Bezug“/„Einspeisung“-Hinweis – z. B. -2 W erschien als bloße „2 W“, was wie Netzbezug
  aussah, während die Zähler-Kachel daneben korrekt -2 W anzeigte. Die Richtung wird jetzt bei jedem
  Zähler-Wert ≠ 0 angezeigt, nicht erst ab der (nur für die Leitungs-Animation gedachten) 5-W-Schwelle.
- Neu: Die Batterie-Kachel in der Übersicht zeigt jetzt „voll“ bzw. „leer“, wenn gerade kein Lade-/Entladefluss
  läuft, der SOC aber am oberen (`CHARGE_FULL_SOC`) bzw. unteren (`NIGHT_MIN_SOC`) Ende steht – vorher blieb die
  Kachel in dem Fall ohne jeden Hinweis.

## [1.0.11] - 2026-09-25

### Bridge

- Neu: `MQTT_HOST` ist jetzt optional – leer gelassen läuft die Bridge als reines Dashboard (Live-Ansicht, Verlauf,
  Telemetrie) ohne Home-Assistant-Discovery; der Regler bleibt dann untätig (er kommt ausschließlich per MQTT an
  den externen Netzzähler).
- Neu: Im Cloud-Modus (`DATA_SOURCE=cloud`) blendet die Web-UI Felder aus, die die Cloud-API grundsätzlich nicht
  liefert (Steckdosen-Leistung, „Real“-Werte, Abgabe ins Hausnetz/Steckdosen-Herkunft), statt sie dauerhaft als
  „–“ anzuzeigen.

## [1.0.10] - 2026-09-25

### Bridge

- Fix: Beim Stoppen des Add-ons (Stopp-Knopf im Supervisor bzw. `docker stop`) zeigte Home Assistant
  „Fehler" statt „Gestoppt" – die Bridge lief als PID 1 ohne Init-Prozess und ohne eigene Signal-Behandlung,
  Pythons Standardreaktion auf SIGTERM beendet den Prozess mit einem von 0 verschiedenen Exit-Code. Die
  Bridge fängt SIGTERM/SIGINT jetzt ab, fährt geordnet herunter und beendet sich mit Exit-Code 0.

## [1.0.9] - 2026-09-24

### Bridge

- Fix: Der gelernte Wert der Adaptiven Regelung wurde beim Ausschalten des Schalters verworfen (auf
  `CONTROL_GAIN` zurückgesetzt und so gespeichert) – erneutes Einschalten begann das Lernen wieder bei
  null. Der gelernte Wert bleibt jetzt unabhängig vom Schalter erhalten; nur die tatsächlich vom Regler
  verwendete Verstärkung folgt dem Schalter (gelernter Wert bei „an", `CONTROL_GAIN` bei „aus").

## [1.0.8] - 2026-09-24

### Bridge

- Neu: Die Fluss-Seite (`/app/flow`) bietet jetzt „Heute"/„Gestern" als echte Kalendertage (unterscheiden sich von
  „24 h" ab Mitternacht) neben den bisherigen Live-/6 h-/24 h-/7 T-/30 T-Ansichten.
- Neu: Die einzelnen Leistungskurven (PV, WR, Akku, Steckdose, Abgabe Hausnetz) lassen sich per Klick auf die
  Legende einzeln aus-/einblenden (gemerkt); die Y-Achse skaliert dann nur auf die sichtbaren Kurven.

## [1.0.7] - 2026-09-24

### Bridge

- Neu: Schalter „Adaptive Regelung" im Regler (aus per Default) – passt `CONTROL_GAIN` laufend an, statt den festen
  `.env`-Wert zu nutzen: übersteuert eine Korrektur (Vorzeichenwechsel des Fehlers), wird die Verstärkung sofort
  gesenkt, reagiert sie zu träge, steigt sie leicht an. Bleibt zwischen 0,3 und 1,2; Ausschalten setzt sie sofort auf
  den konfigurierten `CONTROL_GAIN` zurück.
- Neu: optionale Wetter-Prognose (OpenWeatherMap, `OWM_API_KEY`/`OWM_LAT`/`OWM_LON`) – rein informative Dashboard-
  Kachel mit grober Solar-Einschätzung (Bewölkung, Regenwahrscheinlichkeit) für heute/morgen; ändert nichts am
  Regler oder Batterie-Plan. Ohne konfigurierten API-Key bleibt sie weg.

## [1.0.6] - 2026-09-24

### Bridge

- Neu: Schalter „Netzlast abdecken" im Regler (Alternative zur festen `CHARGE_RESERVE_W`-Reservierung) – deckt
  tagsüber zuerst den Netzbezug des Hauses; nur der vom Einspeise-Schutz tatsächlich beanspruchte Überschuss wird
  von der Ausgabe abgezogen und geht so in die Batterie. Wirkt nur bei aktivem Batterie-Plan.
- `CONTROL_MIN_INTERVAL` (Regel-Takt) ist jetzt im UI einstellbar und auf 60-120 s begrenzt – die typische
  Melde-Verzögerung von Netzzählern, damit der Regler nie auf einen noch nicht angekommenen Messwert reagiert.
  Default von 45 s auf 60 s angehoben (auch als Add-on-Option).

## [1.0.5] - 2026-09-23

### Bridge

- Fix: Bei ausgefallenem Zähler (`Failsafe`) hat der Regler `CONTROL_FALLBACK_W` tagsüber ungedeckelt
  gesetzt – ohne PV kam das komplett aus dem Akku, auch während der Lade-Sperrfrist vor Nachtbeginn.
  Der Failsafe-Sollwert respektiert jetzt dieselbe Phasen-Deckelung (PV minus Ladereserve tagsüber,
  Nacht-Grenzen) wie der laufende Regelkreis; ohne bekannten SOC/PV ist die Obergrenze jetzt 0 statt
  des vollen Fallback-Werts.

## [1.0.4] - 2026-09-23

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
