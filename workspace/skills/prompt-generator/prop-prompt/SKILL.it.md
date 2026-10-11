---
name: prop-prompt
description: Regole del prompt finale del prop — natura morta a pezzo singolo su fondo bianco, punto di vista standard di fotografia di prodotto: proporzioni accurate, bordi completi, sfondo privo di narrativa
---

# Prompt finale del prop (pezzo singolo su fondo bianco · fotografia standard di prodotto)

Ciò che viene generato è un'immagine a pezzo singolo su fondo bianco (product shot): **con un punto di vista standard di fotografia di prodotto**, nell'inquadratura c'è solo il prop, collocato isolato su uno sfondo bianco puro, **senza alcun altro elemento mescolato** — niente altri oggetti, niente persone, niente ambiente di scena, niente mani che lo reggono.

Tre requisiti rigidi:
1. **Proporzioni accurate di ogni parte dell'oggetto** — niente esagerazioni, deformazioni o allungamenti stilizzati; i rapporti dimensionali relativi del prop devono essere veri
2. **Bordi completi** — il prop è interamente in campo come insieme, con margine su tutti i lati; nessuna parte può essere tagliata dal bordo dell'inquadratura
3. **Lo sfondo non trasporta alcun contenuto narrativo** — lo sfondo bianco puro è solo un fondo neutro, senza senso di luogo, senza allusioni alla trama, senza elementi decorativi

## Struttura di output (assembla un unico blocco coerente in questo ordine, seguendo la direttiva di lingua della sessione)

```
Immagine prodotto a pezzo singolo, punto di vista standard di fotografia di prodotto, [nome del prop + materiale/colore/forma/dimensione + grado di usura e dettagli di deterioramento],
proporzioni accurate di ogni parte dell'oggetto, collocato isolato su sfondo bianco puro, centrato e interamente in campo, bordi completi senza tagli,
sfondo pulito e privo di qualsiasi contenuto narrativo, nessun altro oggetto, nessuna persona, nessuna scena,
luce da studio morbida e uniforme, ombre leggere, alto livello di dettaglio
```

## Regole di generazione

- Costruisci attorno al `name` (nome) e alla `description` (aspetto fisico) del prop: materiale, colore, forma, dimensione, grado di usura, segni di deterioramento e ogni altro dettaglio fisico vanno **realizzati punto per punto** — sono la fonte della riconoscibilità del prop
- Punto di vista standard di fotografia di prodotto: vista a 3/4 leggermente dall'alto (si vedono insieme la superficie superiore e un lato, il massimo del volume); per i props piatti (carta, documenti, fotografie) si usa il flat lay dall'alto a perpendicolo
- Presenta il pezzo singolo centrato e completo, con margine su tutti i lati, proporzioni accurate e bordi completi, senza tagliare il corpo del prop
- Luce da studio morbida e uniforme, ombre leggere, alto livello di dettaglio
- Descrivi solo l'oggetto in sé, senza accennare a trama, personaggi o uso (né lo sfondo né l'inquadratura trasportano contenuto narrativo)
- L'output usa la lingua di destinazione indicata dalla direttiva di lingua della sessione, senza mescolare parole non pertinenti; **niente** vocaboli tipo «qualità cinematografica» (l'immagine del prop è una foto di prodotto, non una fotogramma di film)

## Divieti

- Mani che lo reggono, persone, altri oggetti o ambiente di scena in campo
- Confezioni, basi, espositori (a meno che non facciano parte del prop stesso)
- Testo, watermark, firme, loghi di marchi reali (testo e grafiche stampate sul corpo del prop possono restare ed essere descritti)
- Riflessi d'ambiente, luce colorata
- Prospettive esagerate, deformazioni, proporzioni errate, tagli ai bordi

## Salvataggio

