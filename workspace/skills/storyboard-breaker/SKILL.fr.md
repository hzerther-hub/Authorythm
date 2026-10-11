---
name: storyboard-breaker
description: Normes professionnelles du découpage en storyboard — scinder un scénario en segments de storyboard capables de porter plusieurs sous-plans
---

# Guide du découpage en storyboard

## Définition centrale : le segment de storyboard

Un storyboard = un **segment de storyboard** (segment) = une tâche de génération vidéo.

- Chaque segment dure **8-15 secondes** et porte en interne **2-4 sous-plans**
- Entre sous-plans, **les coupes sont autorisées** : changement d'échelle de plan, d'angle ou de sujet, reliés par des coupes franches
- Les sous-plans **ne changent jamais de scène** : un segment se déroule dans une seule scène (`scene_id` est une liaison au niveau du segment)
- Chaque sous-plan dure 2-6 secondes et se concentre sur une unité visuelle (une action, une réaction, un gros plan)

## Processus de découpage (quatre étapes)

2. **Identification des battements** : identifiez d'abord les battements narratifs du scénario — marqueurs tels que 【开场】【触发】【高潮】【收尾】 dans le scénario, ou points de bascule narratifs (changement de lieu, révélation d'une règle, explosion émotionnelle, retournement). **Les frontières de battements forcent une coupure de segment** ; les sous-plans d'un même battement sont en priorité regroupés dans le même segment, sans disperser une chaîne causale (préparation-événement-réaction) entre plusieurs segments
3. **Ancrage du volume total** : durée totale cible = nombre de caractères du scénario ÷ 500 caractères/minute ; nombre de segments ≈ durée totale cible ÷ 12 secondes, avec une tolérance de ±20 %. Ne dépassez ni ne manquez sensiblement le volume

## Durées par palier de rythme

Déterminez la durée selon la fonction du segment — pas de traitement uniforme :

| Type de segment | Durée | Remarques |
|---|---|---|
| Segment de transition | 8-10 secondes | Déplacements, plans vides, installation de l'environnement, transitions |
| Segment narratif | 10-15 secondes | Progression ordinaire de l'intrigue, dialogues |
| Segment de temps fort | 12-15 secondes | Gros plans, révélations de règle, explosions émotionnelles, retournements ; rythme des sous-plans ralenti, un sous-plan isolé peut se tenir 4-6 secondes |

## Durée plancher des dialogues (règle dure)

**Durée du segment ≥ nombre total de caractères des répliques et narrations du segment (la partie écrite dans description) ÷ 4.5 caractères/seconde + 2 secondes de marge de jeu**

Les répliques qui ne tiennent pas doivent être déplacées au segment suivant ; il est interdit d'entasser dans un seul segment des répliques injouables.

## Éléments du plan

1. **Titre du plan** : résumé du contenu central du segment en 3-5 caractères (par ex. « réveil en plein cauchemar »)
2. **Heure** : heure précise + description de la lumière
3. **Lieu** : description complète de la scène + disposition spatiale + détails d'environnement
4. **Échelle de plan** : échelle dominante dans le segment ; pour les segments multi-échelles, écrivez une combinaison, par ex. « plan moyen + gros plan »
5. **Angle** : hauteur d'œil / contre-plongée / plongée / profil / dos
6. **Mouvement de caméra** `movement` : chaque sous-plan doit comporter un mouvement de caméra, choisi dans le vocabulaire et consigné (des sous-plans différents au sein d'un segment peuvent différer). Vocabulaire : fixe en micro-mouvement (ondulation respiratoire) / avance lente / recul de révélation / travelling latéral de suivi / travelling vertical en plongée / orbite en arc / tremblement à l'épaule / angle voyeur / mise au point du regard / tremblement / orbite tendre / filature à grande vitesse / tissage de combat / piqué plongeant / contre-plongée extrême / angle hollandais incliné / plan rapproché par-dessus l'épaule / plan subjectif / panoramique fouetté / transition par obstruction / arrêt sur image après freinage / bullet time. Choix selon le type de segment : préparation → recul de révélation, travelling vertical en plongée, travelling latéral de suivi ; dialogue → plan rapproché par-dessus l'épaule, avance lente, ondulation respiratoire ; émotion → avance lente façon pouls cardiaque, tremblement à l'épaule, tremblement ; action → pour les combats / actions à grande vitesse, choisissez d'abord une formule de position de caméra auprès de la compétence fight-cinematography, sinon filature à grande vitesse, tissage de combat, travelling latéral de suivi ; temps fort → bullet time, arrêt sur image après freinage, mise au point du regard ; suspense / thriller → angle voyeur, angle hollandais, plan subjectif. Figures d'accent (bullet time / ralenti / fisheye) : 1-2 occurrences au maximum par épisode
7. **Description visuelle** `description` : décrivez sous-plan par sous-plan, sous la forme `【镜头1】…【镜头2】…`, ce que le spectateur voit et entend réellement — la façon de filmer (le mouvement de caméra, par ex. « la caméra avance lentement et à vitesse constante du plan moyen jusqu'au gros plan ») s'écrit au début du sous-plan concerné, l'image (qui + action concrète + détails corporels + expression) s'écrit après le mouvement ; lorsqu'un sous-plan porte une réplique, écrivez-la dans le `【镜头N】` correspondant sous la forme « NomDuPersonnage dit : « réplique » », et la narration « Narration : contenu »
8. **Résultat visuel** `result` : conséquence immédiate à la fin du segment + détails visuels
9. **Ambiance** `atmosphere` : lumière + tonalité + sons + atmosphère générale
10. **Durée** `duration` : durée totale du segment de 8-15 secondes, et elle doit satisfaire la durée plancher des dialogues
11. **Liaison de scène** : si une correspondance avec une scène existante est possible, `scene_id` doit être renseigné
12. **Liaison de personnages** : renseignez `character_ids`, en liant de 0 à plusieurs personnages impliqués dans le segment en cours
13. **Liaison d'accessoires** : renseignez `prop_ids`, en liant de 0 à plusieurs accessoires clés apparaissant dans le segment en cours

## Règles de liaison de scène

- Lorsque `location + time` permet une correspondance explicite, le bon `scene_id` doit être re-renseigné
- Ne fabriquez pas d'ID de scène qui n'existent pas
- Si le contenu du scénario se situe manifestement dans une scène existante, ne recréez pas une description de scène en doublon

## Règles de liaison de personnages

- Un segment peut n'avoir aucun personnage comme en lier plusieurs
- Tout personnage clairement présent dans le segment — vu, agissant ou parlant — doit être lié
- Les segments purement environnementaux, les plans vides et les gros plans d'objets peuvent passer un tableau vide

## Règles de liaison d'accessoires

- Lorsqu'un accessoire est utilisé par un personnage, remis, montré en gros plan, ou nettement visible à l'image et porteur de sens pour le récit, il doit être lié au segment
- Les segments de gros plan d'accessoire (sans personnage) lient eux aussi l'accessoire ; `character_ids` peut être vide
- Ne liez pas les objets d'arrière-plan ni les aménagements de scène sans rapport avec l'intrigue ; les segments sans accessoires passent un tableau vide
- Les accessoires liés servent d'images de référence pour la génération vidéo (visuels produit sur fond blanc), garantissant une apparence d'accessoire cohérente d'un segment à l'autre

## Exigences de qualité

- `description` doit être lisible par un humain, décrivant sous-plan par sous-plan ce que le spectateur voit et entend réellement ; répliques / narrations s'écrivent directement dans le `【镜头N】` correspondant
- `image_prompt` doit mettre en avant la composition de l'image fixe, l'apparence des personnages, l'environnement et la lumière (correspondant au premier sous-plan du segment)
- `bgm_prompt` et `sound_effect` peuvent être des formules concises, mais sans vides de sens jusqu'à se réduire à « tendu » ou « triste »
- Pour tout ajustement, appelez `update_storyboard` pour modifier le segment concerné

## Naturalité et vraisemblance des personnages (règles dures)

- `description` / `result` doivent relever d'un langage narratif visuel naturel : n'écrivez que ce que le spectateur voit et entend ; interdiction du ton analytique et de l'énumération à puces (« premièrement / ensuite », « 1. 2. 3. » façon exposé) ; la numérotation `【镜头N】` est le seul marqueur structurel autorisé
- Le comportement des personnages doit correspondre à leur identité, leur âge et leurs capacités : un analphabète ne sait pas lire ni écrire, et ne peut donc ni écrire, ni lire une lettre, ni lire un texte à voix haute ; un tout-petit est trop jeune pour qu'intervienne une logique d'écriture ; un personnage qui ne lit pas une langue étrangère n'en fait ni la lecture ni l'écriture. Seule exception : le texte du scénario énonce explicitement ce geste — si le scénario ne le dit pas, ne l'ajoutez pas de vous-même
- À défaut de justification par une compétence comme la lecture-écriture ou le calcul, exprimez les émotions et les informations par des actions, des attitudes, des accessoires, sans retomber sur « écrire / lire »
