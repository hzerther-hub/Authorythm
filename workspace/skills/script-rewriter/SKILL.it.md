---
name: script-rewriter
description: Metodologia e regole per riscrivere un romanzo in sceneggiatura formattata
---

# Guida alla riscrittura della sceneggiatura

## Principi di riscrittura

1. **Conserva la trama centrale**: non cambiare la storia principale né le relazioni tra personaggi
2. **Rafforza il senso visivo**: trasforma il testo narrativo in descrizioni di scena visualizzabili
3. **Guida dai dialoghi**: fai avanzare la trama con i dialoghi e riduci la narrazione
4. **Controllo del ritmo**: tieni ogni scena tra i 30-60 secondi, adatta ai video brevi
5. **Niente linguaggio di regia**: niente ampiezze di inquadratura, angolazioni o movimenti di macchina; appartengono alla fase di suddivisione in storyboard

## Formato della sceneggiatura formattata

```
## S01 | INT · Caffè | Tramonto

La luce del tramonto entra dai vetri a tutta altezza del caffè; dalle tazze di caffè sul bancone sale il vapore.

Marco è seduto da solo in una poltrona d'angolo, con la testa china sul telefono, l'aria un po' ansiosa.

Il campanello della porta suona, Anna spinge la porta ed entra. Vede Marco e si avvicina sorridendo.

Anna: (sorridente) Hai aspettato a lungo?
Marco: (alza la testa) Non troppo, sono appena arrivato.
```

### Regole di formato

- `## Snumero | INT/EST · Luogo | Fascia oraria` — intestazione di scena
- Descrizione d'azione in paragrafi naturali — senza alcun linguaggio di regia
- `NomePersonaggio: (stato/espressione) contenuto della battuta` — formato dei dialoghi

### Riferimento sul volume di contenuto

La sceneggiatura formattata è circa il 20-30% più lunga del contenuto originale; l'aumento deriva principalmente dai marcatori di intestazione di scena e dalla formattazione dei dialoghi, non da riscrittura espansiva.

## Passaggi di riscrittura

1. Chiama prima `read_episode_script` per leggere il contenuto originale
2. Analizza la struttura del contenuto (proporzioni tra dialoghi, narrazione e descrizioni psicologiche)
3. Chiama `rewrite_to_screenplay` per eseguire la riscrittura
4. Controlla il risultato della riscrittura e verifica che sia conforme al formato della sceneggiatura formattata
5. Chiama `save_script` per salvare il risultato finale

## Avvertenze

- Il monologo interiore deve essere esteriorizzato in espressioni/azioni/scelte del personaggio o in parole dette ad alta voce — **voice-over, narratore e monologo interiore sono vietati**
- In ogni scena devono esserci almeno due personaggi che interagiscono davanti alla camera; non scrivere una scena di una sola persona in una stanza vuota
- Cambia luogo o momento della giornata fra scene consecutive; non ripetere la stessa stanza
- Spezza i lunghi passaggi narrativi in più scene brevi
- Assicurati che ogni scena abbia un chiaro punto di svolta emotivo
- Mantieni la coerenza dello stile linguistico dei personaggi
- I numeri di scena crescono in sequenza continua (S01, S02, S03...)
- La fascia oraria deve essere specifica (tramonto, notte fonda, primo mattino), non scrivere un generico «giorno»
