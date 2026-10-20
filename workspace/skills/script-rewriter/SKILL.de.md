---
name: script-rewriter
description: Methodik und Regeln für das Umschreiben eines Romans in ein formatiertes Drehbuch
---

# Leitfaden zum Drehbuch-Rewriting

## Umschreibprinzipien

1. **Den Kernplot erhalten**: Hauptstoryline und Figurenbeziehungen nicht verändern
2. **Bildkraft verstärken**: erzählende Prosa in visualisierbare Szenenbeschreibungen übersetzen
3. **Dialoggetrieben**: die Handlung mit Repliken vorantreiben, die Erzählung reduzieren
4. **Tempokontrolle**: jede Szene auf 30-60 Sekunden halten, passend für Kurzvideo
5. **Keine Filmsprache**: keine Einstellungsgrößen, Winkel oder Kamerabewegungen — das gehört zum Schritt des Storyboard-Breakdowns

## Format des formatierten Drehbuchs

```
## S01 | Innen · Café | Abenddämmerung

Das Licht der Abenddämmerung fällt durch die bodentiefen Fenster ins Café; über den Kaffeetassen auf der Theke steigt Dampf auf.

Lukas sitzt allein in der Nische in der Ecke, den Blick auf sein Handy gesenkt, die Miene etwas nervös.

Die Türklingel schellt, Mia stößt die Tür auf. Sie sieht Lukas und geht lächelnd hinüber.

Mia: (lächelnd) Wartest du schon lange?
Lukas: (blickt auf) Nicht wirklich, bin gerade angekommen.
```

### Formatregeln

- `## S<Nummer> | Innen/Außen · Ort | Tageszeit` — Szenenkopf
- Aktionsbeschreibung in natürlichen Absätzen — keinerlei Filmsprache
- `Charaktername: (Zustand/Mimik) Repliktext` — Dialogformat

### Referenz für den Textumfang

Das formatierte Drehbuch ist etwa 20-30 % umfangreicher als der Originaltext; der Zuwachs entsteht vor allem durch die Szenenkopf-Markierungen und das Dialogformat, nicht durch eine Ausweitung des Inhalts.

## Umschreibschritte

1. Zuerst `read_episode_script` aufrufen und den Originaltext lesen
2. Die Textstruktur analysieren (Anteile von Dialog, Erzählung und Innenmonolog)
3. `rewrite_to_screenplay` aufrufen und das Umschreiben ausführen
4. Das Umschreibungsergebnis prüfen und bestätigen, dass es dem Format des formatierten Drehbuchs entspricht
5. `save_script` aufrufen und das Endergebnis speichern

## Hinweise

- Innenmonologe müssen über Mimik/Aktionen/Entscheidungen der Figur oder über gesprochene Worte veräußert werden — **Voice-over, Erzählerstimme und Innenmonolog sind verboten**
- In jeder Szene stehen mindestens zwei Figuren vor der Kamera und reagieren aufeinander; keine Szene mit einer Person allein in einem leeren Raum
- Zwischen aufeinanderfolgenden Szenen Ort oder Tageszeit wechseln; nicht dieselbe Szene in einem Raum wiederholen
- Lange Erzählpassagen in mehrere kurze Szenen teilen
- Sicherstellen, dass jede Szene einen klaren emotionalen Wendepunkt hat
- Den Sprachstil jeder Figur konsistent halten
- Szenennummern steigen fortlaufend (S01, S02, S03...)
- Tageszeiten konkret angeben (Abenddämmerung, tiefe Nacht, früher Morgen), kein vages „tagsüber“
