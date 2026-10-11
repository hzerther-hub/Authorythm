---
name: storyboard-breaker
description: Professionelle Spezifikation für den Storyboard-Breakdown — ein Drehbuch in Storyboard-Segmente zerlegen, die jeweils mehrere Sub-Shots tragen
---

# Leitfaden zum Storyboard-Breakdown

## Kerndefinition: Storyboard-Segment

Ein Storyboard = ein **Storyboard-Segment** = eine Video-Generierungsaufgabe.

- Jedes Segment dauert **8-15 Sekunden** und trägt intern **2-4 Sub-Shots**
- Zwischen Sub-Shots **darf geschnitten** werden: Wechsel von Einstellungsgröße, Winkel oder Aufnahmegenstand, verbunden mit harten Schnitten
- Sub-Shots **wechseln nie die Szene**: Ein Segment spielt innerhalb einer einzigen Szene (`scene_id` ist eine Bindung auf Segmentebene)
- Jeder Sub-Shot dauert 2-6 Sekunden und bündelt eine Bildeinheit (eine Aktion, eine Reaktion, ein Close-up)

## Zerlegungsprozess (vier Schritte)

2. **Beat-Erkennung**: zuerst die narrativen Beats des Drehbuchs identifizieren — Markierungen wie 【Eröffnung】【Auslöser】【Höhepunkt】【Abschluss】 oder narrative Wendepunkte (Ortswechsel, Enthüllung einer Regel, emotionaler Ausbruch, Wendung). **Beat-Grenzen erzwingen den Segmentwechsel**; Sub-Shots desselben Beats gehören vorzugsweise in dasselbe Segment, und eine Kausalkette (Aufbau-Ereignis-Reaktion) wird nicht über verschiedene Segmente verstreut
3. **Gesamtumfang verankern**: Zieldauer gesamt = Drehbuchzeichen ÷ 500 Zeichen/Minute; Segmentzahl ≈ Zieldauer gesamt ÷ 12 Sekunden, mit ±20 % Spielraum. Nicht deutlich über- oder unterschreiten

## Tempogestaffelte Dauern

Die Dauer nach der Funktion des Segments festlegen — nicht alles über einen Kamm scheren:

| Segmenttyp | Dauer | Hinweise |
|---|---|---|
| Übergangssegment | 8-10 Sekunden | Reise und Aufbruch, Empty Shots, Etablierung der Umgebung, Übergänge |
| narratives Segment | 10-15 Sekunden | regulärer Handlungsfortschritt, Dialog |
| Highlight-Segment | 12-15 Sekunden | Close-ups, Regel-Enthüllungen, emotionaler Ausbruch, Wendung; Sub-Shot-Tempo verlangsamt, ein einzelner Sub-Shot kann 4-6 Sekunden verweilen |

## Mindestdauer für Dialog (harte Regel)

**Segmentdauer ≥ Gesamtzeichenzahl von Dialog und Erzählung im Segment (der in description geschriebene Teil) ÷ 4.5 Zeichen/Sekunde + 2 Sekunden Spielreserve für die Darstellung**

Repliken, die nicht hineinpassen, müssen in das nächste Segment verschoben werden; ausufernde Repliken in ein Segment zu stopfen, ist nicht erlaubt.

## Einstellungselemente

1. **Einstellungstitel**: 3-5 Zeichen als Zusammenfassung des Kerninhalts des Segments (z. B. „Albtraum-Erwachen“)
2. **Zeit**: konkrete Uhrzeit bzw. Tageszeit + Lichtbeschreibung
3. **Ort**: vollständige Szenenbeschreibung + Raumlayout + Umgebungsdetails
4. **Einstellungsgröße**: die dominierende Einstellungsgröße des Segments; bei Segmenten mit mehreren Größen die Kombination notieren, z. B. „halbtotal + Großaufnahme“
5. **Winkel**: Augenhöhe/Untersicht/Aufsicht/Seitenansicht/Rückansicht
6. **Kamerabewegung** `movement`: Jeder Sub-Shot braucht eine Kamerabewegung, aus dem Vokabular gewählt und notiert (Sub-Shots eines Segments dürfen unterschiedlich sein). Vokabular: statisch mit Mikrobewegung (atmendes Auf und Ab) / langsames Heranfahren / Zurückfahren / seitliche Mitfahrt / Kranfahrt auf-ab / Bogen-Orbit / Handkamera-Wackeln / Lauer-Perspektive / Blick-Fokus / Zittern / sanfter Orbit / Highspeed-Verfolgung / Kampf-Weave / Sprung-Sturzflug / extreme Untersicht / holländischer Winkel / Over-the-Shoulder-Nahsicht / POV / Whip Pan / Verdeckungswipe / Bremsstopp-Freeze / Bullet-Time. Auswahl nach Segmenttyp: Aufbau-Segmente → Zurückfahren zur Enthüllung, Kranfahrt auf-ab, seitliche Mitfahrt; Dialog-Segmente → Over-the-Shoulder-Nahsicht, langsames Heranfahren, atmendes Auf und Ab; Emotions-Segmente → herzschlagartiges langsames Heranfahren, Handkamera-Wackeln, Zittern; Aktions-Segmente → für Kampf-/Highspeed-Beats zuerst die Positionsformeln der fight-cinematography-Fähigkeit wählen, sonst Highspeed-Verfolgung, Kampf-Weave, seitliche Mitfahrt; Highlight-Segmente → Bullet-Time, Bremsstopp-Freeze, Blick-Fokus; Suspense/Thriller → Lauer-Perspektive, holländischer Winkel, POV. Akzent-Spezialeffekte (Bullet-Time / Slow Motion / Fisheye) höchstens 1-2 pro Folge
7. **Bildbeschreibung** `description`: Sub-Shot für Sub-Shot als `【镜头1】…【镜头2】…` beschreiben, was das Publikum tatsächlich sieht und hört — wie gedreht wird (die Kamerabewegung, z. B. „die Kamera fährt gleichmäßig und langsam von halbtotal zur Großaufnahme heran“), steht am Anfang des Sub-Shots, das Bild (wer + konkrete Aktion + Körperdetails + Mimik) danach; hat der Sub-Shot eine Replik, steht sie im jeweiligen `【镜头N】` als „Charaktername sagt: ‚Replik‘“, Erzählung als „Erzähler: Inhalt“
8. **Bildergebnis** `result`: unmittelbare Folge am Ende des Segments + visuelle Details
9. **Atmosphäre** `atmosphere`: Licht + Farbstich + Klang + Gesamtstimmung
10. **Dauer** `duration`: Gesamtdauer des Segments 8-15 Sekunden, zusätzlich muss die Mindestdauer für Dialog erfüllt sein
11. **Szenenbindung**: lässt es sich auf eine bestehende Szene matchen, muss `scene_id` ausgefüllt werden
12. **Figurenbindung**: `character_ids` ausfüllen und die 0 bis mehreren an diesem Segment beteiligten Figuren binden
13. **Requisitenbindung**: `prop_ids` ausfüllen und die im Segment auftauchenden Schlüsselrequisiten binden (0 bis mehrere)

## Regeln der Szenenbindung

- Lässt sich `location + time` eindeutig matchen, muss die korrekte `scene_id` zurückgeschrieben werden
- Keine nicht existierenden Szenen-IDs aus dem Nichts erzeugen
- Liegt der Drehbuchinhalt offensichtlich in einer bestehenden Szene, keine neue Szenenbeschreibung doppelt erzeugen

## Regeln der Figurenbindung

- Ein Segment kann figurenlos sein oder mehrere Figuren binden
- Jede Figur mit klarer Präsenz im Segment — gesehen, handelnd oder sprechend — sollte gebunden werden
- Reine Umgebungssegmente, Empty Shots und Gegenstands-Close-ups dürfen ein leeres Array übergeben

## Regeln der Requisitenbindung

- Wird eine Requisite von einer Figur benutzt, übergeben, im Close-up gezeigt oder ist im Bild klar sichtbar und für die Erzählung bedeutsam, muss sie an das Segment gebunden werden
- Auch Requisiten-Close-up-Segmente (ohne Figuren) binden die Requisite; `character_ids` darf leer sein
- Hintergrundgegenstände ohne Plotbezug und Szenenausstattung nicht binden; Segmente ohne Requisiten übergeben ein leeres Array
- Gebundene Requisiten dienen als Referenzbilder der Videogenerierung (Produktbilder vor weißem Hintergrund) und sichern ein über Segmente hinweg gleichbleibendes Aussehen der Requisite

## Qualitätsanforderungen

- `description` soll für Menschen lesbar sein und Sub-Shot für Sub-Shot beschreiben, was das Publikum tatsächlich sieht und hört; Repliken/Erzählung stehen direkt im jeweiligen `【镜头N】`
- `image_prompt` soll Einzelbild-Komposition, Figurenerscheinung, Umgebung und Licht hervorheben (entsprechend dem ersten Sub-Shot des Segments)
- `bgm_prompt` und `sound_effect` dürfen knappe Phrasen sein, aber nicht so inhaltsleer wie nur „angespannt“ oder „traurig“
- Bei Anpassungen `update_storyboard` aufrufen, um das konkrete Segment zu ändern

## Natürlichkeit und Plausibilität der Figuren (harte Regeln)

- `description` / `result` müssen natürliche bildhafte Erzählsprache sein: nur was das Publikum sieht und hört; verboten sind Analyse-Ton und aufzählende Stichpunkt-Stilistik („erstens/zweitens“, „1. 2. 3.“-Erklärstil); die `【镜头N】`-Nummerierung ist das einzige erlaubte Strukturmerkmal
- Das Verhalten der Figuren muss zu Identität, Alter und Fähigkeiten passen: Analphabeten beherrschen keine Schrift — Handlungen wie Schreiben, Brieflesen, Vortexten dürfen nicht auftreten; Kleinkinder sind zu jung für Schreiblogik; Figuren ohne Fremdsprachenkenntnisse lesen und schreiben keine Fremdsprache. Einzige Ausnahme: Das Drehbuch schreibt die Handlung im Originaltext ausdrücklich vor — ohne Vorlage nicht selbst hinzuerfinden
- Fehlt eine Grundlage für Fachfähigkeiten wie Schriftlichkeit/Rechnen, Emotionen und Informationen stattdessen über Aktionen, Miene und Requisiten ausdrücken, nicht über „Schreiben/Lesen“
