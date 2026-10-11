---
name: storyboard-breaker
description: Regole professionali per la suddivisione in storyboard — spezzare la sceneggiatura in segmenti storyboard capaci di ospitare più sotto-inquadrature
---

# Guida alla suddivisione in storyboard

## Definizione cardine: il segmento storyboard

Uno storyboard = un **segmento storyboard** = un compito di generazione video.

- Ogni segmento dura **8-15 secondi** e ospita internamente **2-4 sotto-inquadrature**
- Tra le sotto-inquadrature **si può cambiare inquadratura**: cambio di ampiezza, di angolazione o di soggetto, raccordato con hard cut
- Tra le sotto-inquadrature **non si cambia mai scena**: un segmento si svolge in un'unica scena (`scene_id` è un collegamento a livello di segmento)
- Ogni sotto-inquadratura dura 2-6 secondi e si concentra su una singola unità visiva (un'azione, una reazione, un primissimo piano)

## Flusso di suddivisione (quattro passi)

2. **Identificazione dei beat**: individua prima i beat narrativi della sceneggiatura — marcatori come 【Apertura】【Innesco】【Climax】【Conclusione】, oppure punti di svolta narrativi (cambi di luogo, rivelazioni di regole, esplosioni emotive, colpi di scena). **I confini dei beat impongono il taglio del segmento**; le sotto-inquadrature dello stesso beat vanno riunite preferibilmente nello stesso segmento, senza disperdere una catena causale (preparazione-evento-reazione) su segmenti diversi
3. **Ancoraggio del totale**: durata totale obiettivo = numero di caratteri della sceneggiatura ÷ 500 caratteri/minuto; numero di segmenti ≈ durata totale obiettivo ÷ 12 secondi, con oscillazione ammessa del ±20%. Non superare né restare sensibilmente sotto

## Durata a livelli di ritmo

Determina la durata in base alla funzione del segmento, senza fare taglie uniche:

| Tipo di segmento | Durata | Note |
|---|---|---|
| Segmento di transizione | 8-10 secondi | Viaggi, inquadrature vuote di ambiente, definizione dell'ambiente, transizioni |
| Segmento narrativo | 10-15 secondi | Avanzamento regolare della trama, dialoghi |
| Segmento clou | 12-15 secondi | Primissimi piani, rivelazioni di regole, esplosioni emotive, colpi di scena; ritmo delle sotto-inquadrature rallentato, una singola sotto-inquadratura può sostenersi 4-6 secondi |

## Minimo di durata per i dialoghi (regola rigida)

**Durata del segmento ≥ numero totale di caratteri di battute e narrazione nel segmento (la parte scritta nella description) ÷ 4.5 caratteri/secondo + 2 secondi di margine recitativo**

Le battute che non stanno dentro vanno spostate al segmento successivo; non è ammesso stipare in un solo segmento battute non recitabili.

## Elementi dell'inquadratura

1. **Titolo dell'inquadratura**: sintesi di 3-5 caratteri del contenuto centrale del segmento (es. «risveglio da incubo»)
2. **Tempo**: ora specifica + descrizione della luce
3. **Luogo**: descrizione completa della scena + layout spaziale + dettagli d'ambiente
4. **Ampiezza**: ampiezza dominante nel segmento; per i segmenti a più ampiezze scrivi una combinazione, es. «piano medio + primissimo piano»
5. **Angolazione**: normale/dal basso/dall'alto/di lato/di spalle
6. **Movimento di macchina** `movement`: ogni sotto-inquadratura deve avere un movimento di macchina, scelto dal lessico e trascritto (sotto-inquadrature diverse nello stesso segmento possono avere movimenti diversi). Lessico: macchina fissa con micro-movimento (ondeggiamento da respiro) / lento carrello in avanti / arretramento di rivelazione / carrello laterale di inseguimento / gru in salita-discesa / orbita ad arco / tremolio a mano / angolo voyeur / messa a fuoco sullo sguardo / tremore / orbita delicata / inseguimento ad alta velocità / intreccio di combattimento / picchiata in volo / ripresa dal basso estrema / inclinazione olandese (Dutch angle) / piano sopra la spalla / soggettiva / panoramica a frusta / transizione per occlusione / arresto su fermo / bullet time. Scelta in base al tipo di segmento: segmenti di preparazione → arretramento di rivelazione, gru in salita-discesa, carrello laterale di inseguimento; segmenti di dialogo → piano sopra la spalla, lento carrello in avanti, ondeggiamento da respiro; segmenti emotivi → lento carrello in avanti a impulso cardiaco, tremolio a mano, tremore; segmenti d'azione → per i beat di lotta/alta velocità scegli prima la formula di posizione dalla skill fight-cinematography, per il resto inseguimento ad alta velocità, intreccio di combattimento, carrello laterale di inseguimento; segmenti clou → bullet time, arresto su fermo, messa a fuoco sullo sguardo; suspense/thriller → angolo voyeur, inclinazione olandese, soggettiva. Trucchi di rilievo (bullet time/slow motion/fisheye) al massimo 1-2 per episodio
7. **Descrizione visiva** `description`: descrivi sotto-inquadratura per sotto-inquadratura come `【镜头1】…【镜头2】…` ciò che il pubblico vede e sente davvero — come l'inquadratura è girata (il movimento di macchina, es. «la macchina esegue un lento carrello in avanti a velocità costante dal piano medio al primissimo piano») si scrive all'inizio della sotto-inquadratura, le immagini (chi + azione specifica + dettagli del linguaggio del corpo + espressione) si scrivono dopo il movimento di macchina; quando la sotto-inquadratura ha battute, scrivile con «NomePersonaggio dice: "battuta"» dentro la corrispondente `【镜头N】`, e la narrazione con «Narratore: contenuto»
8. **Risultato visivo** `result`: la conseguenza immediata alla fine del segmento + dettagli visivi
9. **Atmosfera** `atmosphere`: luce + tonalità + suono + atmosfera complessiva
10. **Durata** `duration`: durata totale del segmento 8-15 secondi, e deve soddisfare il minimo di durata per i dialoghi
11. **Collegamento alla scena**: se si può abbinare a una scena esistente, `scene_id` va compilato obbligatoriamente
12. **Collegamento ai personaggi**: compila `character_ids`, collegando da 0 a più personaggi coinvolti nel segmento
13. **Collegamento ai props**: compila `prop_ids`, collegando da 0 a più props chiave comparsi nel segmento

## Regole di collegamento alla scena

- Quando `location + time` consente un abbinamento chiaro, `scene_id` corretto va inserito obbligatoriamente
- Non generare di sana pianta ID di scene inesistenti
- Se il contenuto della sceneggiatura ricade evidentemente in una scena esistente, non creare una descrizione di nuova scena duplicata

## Regole di collegamento dei personaggi

- Un segmento può non avere personaggi, oppure collegarne più di uno
- Ogni personaggio con presenza chiara nel segmento — visto, in azione o che parla — va collegato
- I segmenti di puro ambiente, le inquadrature vuote e i primissimi piani di oggetti possono passare un array vuoto

## Regole di collegamento dei props

- Quando un prop è usato da un personaggio, consegnato, mostrato in primissimo piano, o chiaramente visibile in campo e rilevante per la narrazione, va collegato al segmento
- Anche i segmenti di primissimo piano sul prop (senza personaggi) devono collegare il prop; `character_ids` può restare vuoto
- Non collegare oggetti di sfondo o arredi di scena irrilevanti per la trama; i segmenti senza props passano un array vuoto
- I props collegati servono da immagini di riferimento per la generazione video (immagini prodotto su fondo bianco), garantendo la coerenza dell'aspetto del prop tra i segmenti

## Requisiti di qualità

- `description` deve essere leggibile a una persona, e descrivere sotto-inquadratura per sotto-inquadratura ciò che il pubblico vede e sente davvero; battute/narrazione si scrivono direttamente dentro la corrispondente `【镜头N】`
- `image_prompt` deve mettere in risalto la composizione del singolo fotogramma, l'aspetto dei personaggi, l'ambiente e la luce (corrisponde alla prima sotto-inquadratura del segmento)
- `bgm_prompt` e `sound_effect` possono essere frasi sintetiche, ma non tanto vaghe da ridursi solo a «teso» «triste»
- Per gli aggiustamenti, chiama `update_storyboard` per modificare il segmento specifico

## Naturalità e plausibilità dei personaggi (regole rigide)

- `description` / `result` devono leggere come narrazione visiva naturale: solo ciò che lo spettatore vede e sente; vietati il tono analitico e gli elenchi puntati («in primo luogo/in secondo luogo», esposizioni tipo «1. 2. 3.»); i marcatori `【镜头N】` sono l'unica notazione strutturale ammessa
- Il comportamento dei personaggi deve corrispondere a identità, età e abilità stabilite: un analfabeta non sa leggere e non può scrivere, leggere lettere o pronunciare testi; i bambini piccoli non possono nemmeno loro esibire logiche di scrittura; i personaggi che non conoscono una lingua straniera non leggono né scrivono in quella lingua. L'unica eccezione è quando il testo originale della sceneggiatura indica esplicitamente quell'azione — se la sceneggiatura non la prevede, non aggiungerla di tuo
- In assenza di basi di alfabetizzazione/calcolo e simili, esprimi emozioni e informazioni con azioni, espressioni, oggetti e simili, senza ricadere sul «scrivere/leggere»
