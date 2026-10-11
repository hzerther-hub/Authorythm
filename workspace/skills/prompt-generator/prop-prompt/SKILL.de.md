---
name: prop-prompt
description: Spezifikation für den finalen Requisiten-Prompt — Einzelproduktfoto vor weißem Hintergrund, Standard-Perspektive der Produktfotografie: korrekte Proportionen, vollständige Kanten, der Hintergrund trägt keine Erzählung
---

# Finaler Requisiten-Prompt (weißer Hintergrund · Einzelrequisite · Standard-Produktfotografie)

Erzeugt wird ein Einzelproduktfoto (Product Shot) vor weißem Hintergrund: **in der Standard-Perspektive der Produktfotografie**, im Bild nur die Requisite selbst, isoliert auf rein weißem Hintergrund platziert, **ohne Beimischung jeglicher anderen Elemente** — keine weiteren Gegenstände, keine Personen, keine Szenenumgebung, keine haltende Hand.

Drei harte Anforderungen:
1. **Korrekte Proportionen aller Teile des Gegenstands** — keine Übertreibung, Verzerrung oder stilisierte Streckung; die relativen Größenverhältnisse der Requisite müssen real sein
2. **Vollständige Kanten** — die Requisite als Ganzes vollständig im Bild, mit Weißraum rundum; kein Teil darf vom Bildrand beschnitten werden
3. **Der Hintergrund trägt keinerlei erzählerischen Inhalt** — der reine weiße Hintergrund ist nur Untergrund, ohne Szenengefühl, ohne Handlungsandeutung, ohne Deko-Elemente

## Ausgabestruktur (in dieser Reihenfolge einen einzigen zusammenhängenden Absatz aufbauen; die Sprache folgt der Sprachanweisung der Sitzung)

```
Einzelproduktfoto, Standard-Perspektive der Produktfotografie, [Requisitenname + Material/Farbe/Form/Größe + Zustandsgrad und Abnutzungsdetails],
korrekte Proportionen aller Teile, isoliert auf rein weißem Hintergrund platziert, zentriert und vollständig im Bild, Kanten vollständig ohne Beschnitt,
Hintergrund rein und ohne jeglichen erzählerischen Inhalt, keine anderen Gegenstände, keine Personen, keine Szene,
weiches gleichmäßiges Studiolicht, dezente Schatten, hoher Detailgrad
```

## Generierungsregeln

- An `name` (Name) und `description` (Äußeres des Gegenstands) der Requisite orientieren: Material, Farbe, Form, Größe, Abnutzungsgrad, Gebrauchsspuren und weitere physische Details **Punkt für Punkt umsetzen** — sie sind die Quelle der Wiedererkennbarkeit der Requisite
- Standard-Perspektive der Produktfotografie: leichte Aufsicht im 3/4-Winkel (Oberseite und Seite zugleich sichtbar, maximal plastisch); flache Requisiten (Papiere, Ausweise, Fotos) flach liegend in strenger Draufsicht
- Einzelstück zentriert und vollständig zeigen, mit Weißraum rundum, korrekte Proportionen, vollständige Kanten — den Korpus der Requisite nicht beschneiden
- Weiches, gleichmäßiges Studiolicht, dezente Schatten, hoher Detailgrad
- Nur den Gegenstand selbst beschreiben; Handlung, Figuren oder Verwendungszweck nicht erwähnen (weder Hintergrund noch Bild tragen erzählerischen Inhalt)
- Ausgabe in der Zielsprache gemäß der Sprachanweisung der Sitzung, keine zusammenhanglosen Vokabeln einmischen; **keine** Vokabeln der Kategorie „filmische Anmutung“ verwenden (ein Requisitenbild ist ein Produktfoto, kein Filmstill)

## Verbotsliste

- Haltende Hände, Personen, andere Gegenstände oder Szenenumgebung im Bild
- Verpackung, Sockel, Präsentationsständer (es sei denn, sie sind Teil der Requisite selbst)
- Text, Wasserzeichen, Signaturen, Logos echter Marken (auf der Requisite selbst aufgedruckte Texte und Muster dürfen erhalten bleiben und beschrieben werden)
- Umgebungsreflexionen, farbiges Licht
- Überzeichnete Perspektive, Verzerrung, Proportionsfehler, Kantenbeschnitt

## Speichern

