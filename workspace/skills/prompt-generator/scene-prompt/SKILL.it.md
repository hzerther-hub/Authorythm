---
name: scene-prompt
description: Regole del prompt finale della scena — chiaro establishing shot grandangolare: posizioni relative fisse di primo piano/piano medio/sfondo/ingressi/pavimento/pareti/arredi principali; struttura spaziale continua, autoconsistente e riutilizzabile, senza persone
---

# Prompt finale della scena (establishing shot grandangolare · inquadratura vuota senza persone)

Ciò che viene generato è un'immagine di scena in forma di **chiaro establishing shot grandangolare**: un'inquadratura pura di ambiente **completamente priva di persone**, che mostra integralmente le **posizioni relative fisse di primo piano, piano medio, sfondo, ingressi/uscite, pavimento, pareti e arredi principali**; la struttura spaziale è continua, autoconsistente e riutilizzabile.

Questa immagine funge da ancora di riferimento di sfondo per tutte le inquadrature della scena: sia il pubblico sia il modello devono poter leggere da qui l'intero layout dello spazio — da dove si entra e si esce, quale texture hanno pavimento e pareti, dove è fissato ogni arredo principale. Il punto di vista deve essere stabile e universale.

## Struttura di output (assembla un unico blocco coerente in questo ordine, seguendo la direttiva di lingua della sessione)

```
inquadratura grandangolare a macchina fissa, chiaro establishing shot, [luogo + texture d'epoca], [fascia oraria],
composizione a tre livelli di primo piano ([elementi in primo piano]), piano medio ([spazio principale del piano medio]), sfondo ([profondità dello sfondo]),
ingressi/uscite ([posizione e stile di porte/passaggi]), pavimento ([materiale e stato del pavimento]), pareti ([materiale e colore delle pareti]),
[arredi principali e loro posizioni relative fisse],
struttura spaziale continua e autoconsistente,
[sorgente luminosa + temperatura del colore + contrasto chiaro/scuro], [atmosfera],
nessuna persona nell'inquadratura, scena vuota, qualità cinematografica
```

## Regole della struttura spaziale

Lo spazio deve essere **leggibile, coerente e riutilizzabile**:

- **Primo piano**: elementi di incorniciamento/occlusione (telai delle porte, spigoli dei tavoli, piante, bordi di macchinari) che creano profondità — scrivi 1-2 elementi specifici
- **Piano medio**: lo spazio principale della scena e gli arredi centrali (linea di montaggio, letto, bancone)
- **Sfondo**: l'estensione dello spazio (muro lontano, finestre, corridoio, skyline cittadina)
- **Ingressi/uscite**: la posizione e lo stile di porte, scale e passaggi devono essere espliciti (es. «una porta di ferro sul lato sinistro dell'inquadratura»); è la base su cui regolare entrate e uscite dei personaggi nelle inquadrature successive
- **Pavimento e pareti**: materiali, colori e stato resi specifici (es. «pavimento in cemento con macchie d'olio», «intonaco di calce screpolato sulle pareti»)
- **Arredi principali**: scrivi 2-4 arredi centrali e le loro **posizioni relative fisse** (es. «la linea di montaggio corre lungo la parete e termina al bancone»); le relazioni sinistra/destra e vicino/lontano tra gli arredi devono essere autoconsistenti, non limitarti a elencare nomi di oggetti

## Persone (regola rigida · priorità massima)

**Nell'immagine della scena non può comparire alcuna persona; resta solo la scena stessa.**

- Nel prompt non si descrivono persone né si accenna a nulla di riferito a persone
- Le informazioni sulle persone presenti nella descrizione della scena (prompt) vanno ignorate tutte e non scritte nel prompt
- Il prompt deve terminare con: «nessuna persona nell'inquadratura, scena vuota»

Gli arredi, la texture d'epoca e gli elementi visivi chiave del `prompt` (descrizione della scena) devono essere tutti realizzati; il `lighting` (luce della scena) va reso specifico: direzione delle sorgenti luminose, temperatura caldo/freddo del colore, contrasto chiaro/scuro (es. «le lampade a tubo al soffitto emettono luce bianca fredda, proiettando ombre dure sotto le macchine»).

## Punto di vista e atmosfera

- Grandangolo stabile a livello occhi o leggermente dall'alto; niente angolazioni estreme dall'alto o dal basso, fisheye o composizioni inclinate (fungerà da scena fissa da riutilizzare ripetutamente)
- Determina fascia oraria e tono luminoso di base da `location` + `time` (la luce di giorno/notte/tramonto è completamente diversa)
- Rendi concrete le parole dell'atmosfera: «opprimente» → «aria afosa, luce fioca e cupa»; non scrivere solo vocaboli emotivi astratti
- L'output usa la lingua di destinazione indicata dalla direttiva di lingua della sessione, senza mescolare parole non pertinenti

## Divieti

- Qualsiasi persona — **nell'immagine della scena non può comparire alcuna persona; resta solo la scena stessa**
- Testo, testo leggibile sugli insegne, watermark, firme, loghi di marchi reali
- Motion blur, oggetti in movimento (l'immagine di riferimento della scena deve essere ferma e stabile)
- Elencare soltanto gli arredi senza chiarire le posizioni relative (la struttura spaziale deve essere continua e autoconsistente)

## Salvataggio

