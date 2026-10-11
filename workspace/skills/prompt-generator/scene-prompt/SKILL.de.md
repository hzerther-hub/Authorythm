---
name: scene-prompt
description: Spezifikation für den finalen Szenen-Prompt — klarer Weitwinkel-Establishing-Shot: feste relative Positionen von Vordergrund/Mittelgrund/Hintergrund/Ein- und Ausgängen/Boden/Wänden/zentraler Ausstattung, räumlich kontinuierlich, in sich stimmig und wiederverwendbar, ohne Personen
---

# Finaler Szenen-Prompt (Weitwinkel-Establishing-Shot · leere Szene ohne Personen)

Erzeugt wird ein Szenenbild als **klarer Weitwinkel-Establishing-Shot**: eine reine Leerlauf-Einstellung der Szene **vollkommen ohne Personen**, die **die festen relativen Positionen von Vordergrund, Mittelgrund, Hintergrund, Ein- und Ausgängen, Boden, Wänden sowie der zentralen Ausstattung vollständig zeigt** — räumliche Struktur kontinuierlich, in sich stimmig und wiederverwendbar.

Dieses Bild dient als Hintergrund-Referenzanker für alle Einstellungen dieser Szene: Zuschauer und Modell müssen daraus das gesamte Raumlayout ablesen können — wo man hinein- und hinausgeht, welche Materialwirkung Boden und Wände haben, an welcher festen Position sich jede zentrale Ausstattung befindet. Die Perspektive muss stabil und universell einsetzbar sein.

## Ausgabestruktur (in dieser Reihenfolge einen einzigen zusammenhängenden Absatz aufbauen; die Sprache folgt der Sprachanweisung der Sitzung)

```
Weitwinkel-Aufnahme aus fester Kameraposition, klarer Establishing-Shot, [Ort + zeittypische Anmutung], [Tageszeit],
dreischichtige Komposition aus Vordergrund ([Vordergrundelemente]), Mittelgrund ([Hauptraum des Mittelgrunds]) und Hintergrund ([Tiefe des Hintergrunds]),
Ein- und Ausgänge ([Position und Stil von Türen/Passagen]), Boden ([Material und Zustand des Bodens]), Wände ([Material und Farbe der Wände]),
[zentrale Ausstattung und ihre festen relativen Positionen],
räumliche Struktur kontinuierlich und in sich stimmig,
[Lichtquellen + Farbtemperatur + Hell-Dunkel-Kontrast], [Atmosphäre],
keine einzige Person im Bild, leere Szene, filmische Anmutung
```

## Regeln der Raumstruktur

Der Raum muss **lesbar, stimmig und wiederverwendbar** sein:

- **Vordergrund**: rahmende/verdeckende Elemente (Türrahmen, Tischecke, Pflanzen, Gerätekanten), die Tiefe erzeugen — 1-2 konkrete Elemente nennen
- **Mittelgrund**: der Hauptraum der Szene und ihre zentrale Ausstattung (Fließband, Betten, Theke)
- **Hintergrund**: die Fortsetzung des Raums (ferne Wand, Fenster, Flur, Stadtsilhouette)
- **Ein- und Ausgänge**: Position und Stil von Türen, Treppen und Passagen müssen eindeutig sein (z. B. „eine Eisentür links im Bild“) — sie sind die Grundlage dafür, wie spätere Einstellungen Figuren eintreten und verlassen lassen
- **Boden und Wände**: Material, Farbe und Zustand konkretisieren (z. B. „Ölflecken auf dem Zementboden“, „fleckiger Kalkputz an den Wänden“)
- **Zentrale Ausstattung**: 2-4 Kernstücke nennen und ihre **festen relativen Positionen** (z. B. „das Fließband zieht sich an der Wand entlang und endet an der Theke“); die Links-Rechts-/Nah-Fern-Beziehungen zwischen den Stücken müssen stimmig sein — nicht bloß Gegenstandsnamen auflisten

## Personen (harte Regel · höchste Priorität)

**Im Szenenbild darf keine einzige Person erscheinen — nur die Szene selbst bleibt.**

- Der Prompt beschreibt keine Personen und erwähnt nichts Personenbezogenes
- Personeninformationen, die in der Szenenbeschreibung (prompt) auftauchen, werden ausnahmslos ignoriert und nicht in den Prompt übernommen
- Der Prompt muss enden mit: „Keine einzige Person im Bild, leere Szene“

Sämtliche Ausstattung, zeittypische Anmutung und zentrale visuelle Elemente aus `prompt` (Szenenbeschreibung) müssen umgesetzt werden; `lighting` (Licht und Schatten der Szene) ist zu konkretisieren: Lichtrichtung, warme/kühle Farbtemperatur, Hell-Dunkel-Kontrast (z. B. „die Leuchtstoffröhren über Kopf werfen kaltes weißes Licht, unter den Maschinen liegen harte Schatten“).

## Perspektive und Atmosphäre

- Stabile Augenhöhe oder leichter Weitwinkel aus leichter Aufsicht; keine extremen Auf-/Untersichten, kein Fisheye, keine schräge Komposition (das Bild wird als feste Szene immer wieder wiederverwendet)
- Tageszeit und Lichtgrundton über `location` + `time` festlegen (Tag/Nacht/Dämmerung sind völlig unterschiedliche Lichtstimmungen)
- Atmosphäre-Wörter konkretisieren: „beklemmend“ → „drückend schwüle Luft, dumpfes schwaches Licht“; nicht nur abstrakte Emotionswörter schreiben
- Ausgabe in der Zielsprache gemäß der Sprachanweisung der Sitzung, keine zusammenhanglosen Vokabeln einmischen

## Verbotsliste

- Jegliche Personen — **im Szenenbild darf keine einzige Person erscheinen, nur die Szene selbst bleibt**
- Text, lesbare Schrift auf Schildern, Wasserzeichen, Signaturen, Logos echter Marken
- Motion Blur, bewegte Objekte (das Szenen-Referenzbild muss ruhig und stabil sein)
- Bloßes Aufzählen der Ausstattung ohne Angabe relativer Positionen (die Raumstruktur muss kontinuierlich und in sich stimmig sein)

## Speichern

