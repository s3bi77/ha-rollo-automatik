# Rollo Automatik

Home-Assistant-Integration für die automatische Rollladensteuerung pro Raum.

## Einrichtung

Einstellungen → Geräte & Dienste → Integration hinzufügen → „Rollo Automatik“. Pro Bereich ein Eintrag:

1. **Bereich** wählen. Angeboten werden Bereiche mit Rollos.
2. **Raum:** Rollos des Bereichs, Präsenzmelder, optional Schlafmodus-Schalter und Heizung/Klima. Vorgeschlagen werden Entitäten aus dem Bereich.
3. **Je Rollo:** Fensterkontakt, optional Breite, Höhe und Laibungstiefe des Fensters, Ausrichtung des Fensters (Himmelsrichtung oder Azimut in Grad), optional eine eigene Beschattungsposition und Bedingungen, wann beschattet werden darf. Die Bedingungen sind normale Home-Assistant-Bedingungen.
4. **Außensensoren:** Außenhelligkeit, Außentemperatur, optional Dämmerung und ein Binärsensor für die Präsenz im Haus. Beim nächsten Raum werden diese Werte vorgeschlagen.

Alles lässt sich später über „Konfigurieren“ ändern.

Jeder Raum bekommt ein Gerät „Rollos“ im Bereich. Die Entity-IDs setzt Home Assistant aus Bereich, Gerät und Entität zusammen, z.B. `switch.wohnzimmer_rollos_automatik`:

| Entität | Zweck |
|---|---|
| Automatik | Automatik an/aus |
| Beschattung | Beschattung bei direkter Sonne an/aus |
| Position bei offenem Fenster | Mindestposition, solange das Fenster offen ist |
| Beschattungsposition | Position beim Beschatten |
| Schlafposition | Position im Schlafmodus (nur mit Schlafmodus-Schalter) |
| Schlafposition bei offenem Fenster | Schlafmodus und Fenster offen (nur mit Schlafmodus-Schalter) |
| Helligkeitsschwelle / Helligkeit Hysterese | Ab wann es „hell“ ist |
| Kälteschwelle | Ab wann es „kalt“ ist (aus erst bei Schwelle + 1 °C) |
| Totzone | Kleinere Abweichungen werden nicht gefahren |
| Status | Ziel und Grund pro Rollo, Details in den Attributen |

## Logik

Für jedes Rollo werden die Regeln der Reihe nach angewendet. „Höchstens“ begrenzt die Position nach oben, „mindestens“ nach unten. Die letzte greifende Regel bestimmt das Ziel:

1. **Dämmerung** → höchstens 0 (zu). Ohne Dämmerungssensor gilt der Sonnenuntergang.
2. Sonst **Anwesenheit** im Raum oder Rollo ganz offen → mindestens 100.
3. Sonst bei **Abwesenheit**:
   - Heizen, hell und Sonne direkt → mindestens 100 (Sonnenwärme)
   - kalt → höchstens 0
   - Kühlen und hell → höchstens 0 (Hitzeschutz)
4. **Beschattung** (Schalter an, hell, Sonne direkt, Bedingungen erfüllt) → höchstens Beschattungsposition.
5. **Fenster offen** → mindestens Fensterposition.
6. **Schlafmodus** → genau Schlafposition; bei offenem Fenster mindestens die Schlafposition bei offenem Fenster.

Die Sonne gilt als direkt, wenn sie zwischen 10° und 80° hoch steht und ihr Azimut höchstens 65° von der Ausrichtung des Fensters abweicht. Sind Breite und Höhe des Fensters eingetragen, rechnet die Integration stattdessen, wie viel Sonne an Laibung und Sturz vorbei auf das Glas fällt (Laibungstiefe Standard 25 cm). Direkt ist die Sonne dann, sobald mindestens ein Viertel der Glasfläche besonnt ist. Breite Fenster bekommen so auch schräg einfallende Sonne ab, schmale tiefe Fenster weniger. Sonnenstand aus `sun.sun`.

Gefahren wird nur, wenn sich die greifenden Regeln seit der letzten Auswertung geändert haben und die Abweichung größer als die Totzone ist. Von Hand verstellte Rollos bleiben so in Ruhe, bis sich die Lage ändert.

Anwesenheit bleibt nach einmaliger Erkennung gesetzt, bis der Sensor für die Präsenz im Haus aus ist. Nach einer Fahrt bei Abwesenheit wird sie 4 Minuten ignoriert, damit das fahrende Rollo den Melder nicht auslöst.

Die drei Schlaf- und Fensterpositionen halten sich gegenseitig in der Reihenfolge Schlafposition ≤ Schlafposition bei offenem Fenster ≤ Position bei offenem Fenster.

## Installation über HACS

1. HACS → Benutzerdefinierte Repositories → `https://github.com/s3bi77/ha-rollo-automatik`, Typ „Integration“.
2. „Rollo Automatik“ installieren und Home Assistant neu starten. Benötigt Home Assistant 2026.3 oder neuer.

## Entwicklung

```bash
python -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/pytest
```

## Lizenz und Haftung

MIT-Lizenz, siehe [LICENSE](LICENSE). Nutzung auf eigene Verantwortung: Die Integration fährt Rollläden selbstständig. Vor dem Einsatz prüfen, dass niemand eingeklemmt werden kann und Fluchtwege nicht verschlossen werden.

„Home Assistant“ ist eine Marke der Open Home Foundation. Dieses Projekt ist kein offizieller Bestandteil von Home Assistant.
