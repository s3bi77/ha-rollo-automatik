# Rollo Automatik

Home-Assistant-Integration für die automatische Rollladensteuerung pro Raum. Sie löst den Node-RED-Subflow „Rollo Automatik“ ab und übernimmt dessen Logik 1:1.

Jeder Raum ist ein eigener Eintrag mit einem Gerät „<Raum> Rollo“. Das Gerät bringt diese Entitäten mit (die IDs sind dieselben wie bisher aus Node-RED):

| Entität | Zweck |
|---|---|
| `switch.<präfix>_rollo_automatik_aktiv` | Automatik an/aus |
| `switch.<präfix>_rollo_automatische_beschattung` | Beschattung bei direkter Sonne |
| `number.<präfix>_rollo_zielposition_fenster_offen` | Mindestposition bei offenem Fenster |
| `number.<präfix>_rollo_zielposition_beschattung` | Position beim Beschatten |
| `number.<präfix>_rollo_zielposition_schlafmodus` | Position im Schlafmodus (nur mit Schlafmodus) |
| `number.<präfix>_rollo_zielposition_schlafmodus_fenster_offen` | Schlafmodus + Fenster offen (nur mit Schlafmodus) |
| `number.<präfix>_rollo_lux_threshold` / `_lux_hysteresis` | Ab wann es „hell“ ist |
| `number.<präfix>_rollo_kalte_threshold` | Ab wann es „kalt“ ist (Hysterese +1 °C) |
| `number.<präfix>_rollo_automatik_totzone` | Kleinere Abweichungen werden nicht gefahren |
| `sensor.<präfix>_rollo_automatik_status` | Ziel und Grund pro Rollo, Details in den Attributen |

## Logik

Für jedes Rollo werden die Regeln der Reihe nach angewendet. „Max“ begrenzt die Position nach oben, „Min“ nach unten:

1. **Dämmerung** → max 0 (zu).
2. Sonst: **Präsenz im Raum** oder Rollo steht auf 100 → min 100 (offen).
3. Sonst bei **Abwesenheit**: Heizen + hell + Sonne direkt → min 100. Kalt → max 0. Kühlen + hell → max 0.
4. **Beschattung** (Schalter an, hell, Sonne direkt, Sonnenregel erfüllt) → max Beschattungsposition.
5. **Fenster offen** → min Fensterposition.
6. **Schlafmodus** → genau Schlafposition; mit offenem Fenster min „Schlafmodus Fenster offen“.

Gefahren wird nur, wenn sich die greifenden Regeln seit der letzten Auswertung geändert haben und die Abweichung größer als die Totzone ist. Von Hand verstellte Rollos bleiben so in Ruhe.

Präsenz bleibt nach einmaliger Erkennung gesetzt, bis kein Präsenzmelder im Haus (Label „Präsenz“) mehr an ist. Nach einer Fahrt bei Abwesenheit wird sie 4 Minuten ignoriert, damit das fahrende Rollo den Melder nicht auslöst.

### Namenskonvention

Ohne eigene Angaben nutzt ein Raum mit Präfix `kind_1` und Rollo-Suffix `fenster`:

- Rollo: `cover.kind_1_rollo_fenster`
- Fensterkontakt: `binary_sensor.kind_1_fenster_geoffnet`
- Präsenz: `binary_sensor.kind_1_prasenz`
- Schlafmodus: `switch.kind_1_schlafmodus`
- Heizen/Kühlen: `climate.kind_1`

### Rollo-Liste

```yaml
- suffix: fenster          # Pflicht
  direction: 0             # 0 = Ost/Süd (Azimut 80–210°), 1 = Süd/West, 2 = West, 3 = Nord
  overrideSunPos: 30       # optional: eigene Beschattungsposition
  cover: cover.x           # optional: abweichendes Rollo
  window: binary_sensor.y  # optional: abweichender Fensterkontakt
  sunRule:                 # optional: wann beschattet werden darf (ohne Regel: immer)
    allOf:
      - entity: select.heizung_betriebsmodus
        eq: Kühlen
      - entity: cover.markise_controller_markise_1
        ne: closed
```

Regeln: `{entity, eq}` oder `{entity, ne}`, kombinierbar mit `allOf` / `anyOf`.

## Installation über HACS

1. HACS → Benutzerdefinierte Repositories → `https://github.com/s3bi77/ha-rollo-automatik`, Typ „Integration“.
2. „Rollo Automatik“ installieren, Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → „Rollo Automatik“, einmal pro Raum.

## Umstieg von Node-RED (pro Raum)

1. Raum in HA anlegen, dabei **„Werte und Entity-IDs von Node-RED übernehmen“** anhaken. Die aktuellen Einstellungen werden gelesen, die Node-RED-Entitäten entfernt und ihre IDs übernommen. Dashboards und Automationen bleiben gültig.
2. **Direkt danach** in Node-RED die Subflow-Instanz des Raums löschen und deployen. Sonst legt Node-RED die Entitäten beim nächsten Start mit `_2` neu an, und beide Systeme fahren das Rollo.

Die Rollo-Listen der bisherigen Räume:

<details>
<summary>Kind 1 / Kind 2 (Präfix <code>kind_1</code> / <code>kind_2</code>, Schlafmodus an)</summary>

```yaml
- suffix: fenster
  direction: 0
  sunRule:
    entity: select.heizung_betriebsmodus
    eq: Kühlen
```
</details>

<details>
<summary>Bad OG, Büro EG, Schlafzimmer (Präfix <code>bad_og</code>, <code>buro_eg</code>, <code>schlafzimmer</code>, Schlafmodus an)</summary>

```yaml
- suffix: fenster
  direction: 2
  sunRule:
    entity: select.heizung_betriebsmodus
    eq: Kühlen
```
</details>

<details>
<summary>Büro OG (Präfix <code>buro_og</code>, Schlafmodus aus)</summary>

```yaml
- suffix: fenster
  direction: 0
  sunRule:
    anyOf:
      - entity: binary_sensor.buro_og_prasenz
        eq: "on"
      - entity: select.heizung_betriebsmodus
        eq: Kühlen
```
</details>

<details>
<summary>Wohnzimmer (Präfix <code>wohnzimmer</code>, Schlafmodus aus)</summary>

```yaml
- suffix: tur_links
  direction: 0
  sunRule:
    allOf:
      - anyOf:
          - entity: select.heizung_betriebsmodus
            eq: Kühlen
          - entity: binary_sensor.wohnzimmer_tv_status
            eq: "on"
      - entity: cover.markise_controller_markise_1
        ne: closed
- suffix: tur_rechts
  direction: 0
  sunRule:
    allOf:
      - entity: select.heizung_betriebsmodus
        eq: Kühlen
      - entity: cover.markise_controller_markise_1
        ne: closed
- suffix: kuchenfenster
  direction: 1
  overrideSunPos: 30
  sunRule:
    entity: select.heizung_betriebsmodus
    eq: Kühlen
```
</details>

## Unterschiede zu Node-RED

- Ein Einstellwert von 0 wird jetzt als 0 genommen. Node-RED hat 0 bei Fenster-/Beschattungsposition stillschweigend durch den Standardwert ersetzt.
- Eine Außentemperatur von genau 0 °C zählt jetzt als Messwert. Ohne Messwert bleibt der letzte Kälte-Zustand erhalten.
- Ein Rollo ohne `sunRule` darf beschatten. In Node-RED hat ein fehlendes `sunRule` die Beschattung blockiert. Alle bisherigen Räume haben eine Regel, betroffen ist also keiner.
- Die Hauspräsenz wird direkt aus den Meldern mit Label „Präsenz“ gelesen. In Node-RED galt sie bis zur ersten Änderung nach einem Neustart als „niemand da“.
- Der Status-Sensor zeigt eine Kurzfassung. Die vollständige Begründung steht in den Attributen.

## Entwicklung

```bash
python -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/pytest
```
