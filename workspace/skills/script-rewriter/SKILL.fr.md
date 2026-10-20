---
name: script-rewriter
description: Méthodologie et normes de réécriture d'un roman en scénario formaté
---

# Guide de réécriture en scénario

## Principes de réécriture

1. **Préserver l'intrigue centrale** : ne pas modifier l'histoire principale ni les relations entre personnages
2. **Renforcer la visualité** : transformer les passages narratifs en descriptions de scènes visualisables
3. **Pilotage par les dialogues** : faire avancer l'intrigue par les dialogues, réduire la narration
4. **Maîtrise du rythme** : maintenir chaque scène entre 30-60 secondes, adapté à la vidéo courte
5. **Pas de langage de caméra** : aucune échelle de plan, angle ni mouvement de caméra — cela relève de l'étape de découpage en storyboard

## Format du scénario formaté

```
## S01 | INT · Café | Crépuscule

La lumière du crépuscule entre à flots par les baies vitrées du café ; la vapeur s'élève des tasses posées sur le comptoir.

Xiaoming est assis seul dans un coin banquette, tête baissée sur son téléphone, l'air quelque peu anxieux.

La sonnette retentit, Xiaohong pousse la porte et entre. Elle aperçoit Xiaoming et s'avance en souriant.

Xiaohong : (souriant) Vous attendez depuis longtemps ?
Xiaoming : (levant la tête) Pas vraiment, je viens d'arriver.
```

### Règles de format

- `## S numéro | INT/EXT · lieu | plage horaire` — en-tête de scène
- Description d'action en paragraphes naturels — sans aucun langage de caméra
- `NomDuPersonnage : (état/expression) contenu de la réplique` — format de dialogue

### Repère de volume de contenu

Le scénario formaté est environ 20-30 % plus long que le contenu d'origine ; l'augmentation provient principalement des marqueurs d'en-tête de scène et du formatage des dialogues, pas d'un développement rédactionnel.

## Étapes de réécriture

1. Appelez d'abord `read_episode_script` pour lire le contenu d'origine
2. Analysez la structure du contenu (proportions de dialogues, de narration et de monologue intérieur)
3. Appelez `rewrite_to_screenplay` pour exécuter la réécriture
4. Vérifiez le résultat réécrit et confirmez qu'il est conforme au format du scénario formaté
5. Appelez `save_script` pour enregistrer le résultat final

## Points d'attention

- Le monologue intérieur doit être extériorisé par les expressions/actions/choix du personnage ou par une réplique dite à voix haute — **voix off, narration et monologue intérieur sont interdits**
- Chaque scène doit mettre en présence au moins deux personnages qui interagissent devant la caméra; n'écrivez pas une scène d'une seule personne dans une pièce vide
- Changez de lieu ou d'heure entre deux scènes consécutives; ne recommencez pas la même pièce
- Décomposez les longues plages narratives en plusieurs scènes courtes
- Assurez-vous que chaque scène possède un point de bascule émotionnel clair
- Maintenez la cohérence du style de langage de chaque personnage
- Les numéros de scène augmentent de façon continue (S01, S02, S03...)
- Les plages horaires doivent être précises (crépuscule, pleine nuit, petit matin) — n'écrivez pas un vague « journée »
