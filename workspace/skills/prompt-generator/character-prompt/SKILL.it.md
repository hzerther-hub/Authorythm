---
name: character-prompt
description: Regole del prompt finale del personaggio — primissimo piano frontale + turnaround a tre viste (fronte/profilo a 90 gradi/retro), come ancora visiva per tutte le generazioni successive
---

# Prompt finale del personaggio (a sinistra primissimo piano frontale + a destra turnaround a tre viste)

Ciò che viene generato è un **character turnaround sheet (character reference sheet / multi-view concept art layout)**, con composizione rigidamente fissa:

- **A sinistra: primissimo piano frontale** — vista ravvicinata frontale di testa e spalle, con tratti del viso, acconciatura e texture della pelle ben visibili; funge da ancora per la riconoscibilità del viso
- **A destra: tre viste a figura intera della stessa altezza affiancate — fronte, profilo a 90 gradi e retro** — tre viste a figura intera dello stesso personaggio affiancate alla stessa altezza, con la sommità del capo e la pianta dei piedi allineate

**Principio cardine: coerenza > bellezza.** Questa immagine è l'ancora visiva per tutte le immagini successive del personaggio e per i riferimenti video; deve essere neutra, nitida e riutilizzabile — non inseguire l'impatto artistico di una singola immagine.

## Struttura di output (assembla un unico blocco coerente in questo ordine, seguendo la direttiva di lingua della sessione)

```
character turnaround sheet, character reference sheet, multi-view concept art layout, orthographic views, no perspective distortion;
a sinistra il primissimo piano frontale, a destra tre viste a figura intera della stessa altezza affiancate (fronte, profilo a 90 gradi, retro),
le tre viste a figura intera evenly spaced panels, con la sommità del capo e la pianta dei piedi allineate;
il primissimo piano e le viste a figura intera sono lo stesso personaggio, a figura intera nell'inquadratura, posa A-pose neutra, espressione naturale che non tradisce emozioni,
[età percepita + carattere di genere + corporatura], [tratti del viso], [acconciatura], [abbigliamento + accessori],
il viso, l'acconciatura e l'abbigliamento del primissimo piano frontale e delle tre viste sono completamente identici,
sfondo bianco puro, luce morbida e uniforme, qualità cinematografica
```

## Regole dell'ordine di descrizione

Metti **i tratti più riconoscibili per primi**, realizzando in questo ordine ogni elemento chiave di `appearance` (aspetto) e `styling` (look), senza ometterne nessuno:

1. Ancore d'identità: età percepita (es. «poco oltre i vent'anni»), carattere di genere, corporatura (statura e costituzione, abitudini posturali)
2. Tratti del viso: forma del viso, occhi, altri elementi evidenti (cicatrici, nei, occhiali ecc.) — il primissimo piano frontale dipende in special modo da questa parte
3. Acconciatura: colore, lunghezza, stile
4. Abbigliamento: modello, colore, materiale, stato (es. «tuta da lavoro sgualcita con residui di stagno sui polsini»)
5. Accessori: scrivere solo quelli riconoscibili, senza accumularli

I tratti caratteriali del personaggio vanno trasformati in descrizioni di portamento esteriore ed espressione (es. «smunto» → «sguardo stanco, spalle leggermente cadenti»); i vocaboli del carattere non devono comparire direttamente.

## Composizione e coerenza

- Primissimo piano frontale a sinistra: rivolto verso la macchina da presa, espressione neutra, dalla sommità del capo alle spalle interamente in campo
- Tre viste a figura intera a destra: fronte, profilo a 90 gradi e retro dello stesso personaggio, **alla stessa altezza, affiancate, a spaziatura uniforme**, con la sommità del capo e la pianta dei piedi sulla stessa linea orizzontale
- Il primissimo piano e le tre viste a figura intera devono avere lo stesso viso, la stessa acconciatura e lo stesso abbigliamento — scrivi esplicitamente «il viso, l'acconciatura e l'abbigliamento del primissimo piano frontale e delle tre viste a figura intera sono completamente identici»
- Posa neutra, espressione naturale — così è comoda da riutilizzare come immagine di riferimento
- Mani e piedi normali: nelle viste a figura intera le mani hanno cinque dita normali e i piedi cinque dita, due braccia e due gambe, nessun arto in più; mani naturalmente rilassate, senza gesti complessi (per ridurre la probabilità di mani deformi)
- **Tetto rigido al totale delle istanze del personaggio: 1 primissimo piano frontale + 3 viste a figura intera = 4 istanze in totale, vietato averne di più** (attenzione: le 3 viste a figura intera sono per progetto lo stesso personaggio visto da angolazioni diverse — fronte / profilo a 90 gradi / retro; è un intento progettuale, non una «copia»; ciò che è vietato è disegnare una copia in più dello stesso personaggio, o aggiungere istanze in campo oltre le 3 viste a figura intera; tra le 3 viste a figura intera ci deve essere un orientamento chiaramente diverso: sinistra / centro / destra = fronte / profilo a 90 gradi / retro, mai tutte di fronte)
- Un solo personaggio: nell'intera immagine possono esserci solo le 4 istanze di personaggio sopra descritte, nessun fantasma, doppione o moltiplicazione di figure; tratti del viso stabili, senza deformazioni né fusioni
- Luce da studio morbida e uniforme, niente ombreggiature drammatiche (l'immagine di riferimento deve poter essere usata in ogni tipo di scena)
- L'output usa la lingua di destinazione indicata dalla direttiva di lingua della sessione, senza mescolare parole non pertinenti

## Divieti

- Posa dinamiche, espressioni esagerate, oggetti in mano, essere in campo insieme ad altre persone
- **Più di 4 istanze di personaggio (1 primissimo piano + 3 viste a figura intera); le 3 viste a figura intera sono lo stesso personaggio da angolazioni diverse (fronte / profilo a 90 gradi / retro) — è un intento progettuale, non un divieto; ciò che è vietato è duplicare lo stesso personaggio oltre le 3 viste a figura intera, o renderle tutte di fronte / stiparle al centro dell'inquadratura / sovrapposte / ad altezze diverse**
- Tagliare il corpo (le viste a figura intera devono essere full body, dalla sommità del capo alla pianta dei piedi interamente in campo; il primissimo piano deve avere testa e spalle interamente in campo)
- Sei dita, dita saldate, dita mancanti, malformazioni da fusione; tre mani, tre gambe, arti sovrannumerari, distorsioni da duplicazione
- Fantasmi, doppioni, moltiplicazione di figure; tratti del viso deformati, volto fuso
- Testo, etichette, watermark, firme; loghi di marchi reali, volti di celebrità reali
- Ombre pesanti, luci colorate di sfondo, oggetti di scena sullo sfondo

## Salvataggio

