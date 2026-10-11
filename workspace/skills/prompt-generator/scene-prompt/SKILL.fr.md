---
name: scene-prompt
description: Norme du prompt final de scène — plan d'ensemble en grand angle net : positions relatives figées de l'avant-plan / du plan intermédiaire / de l'arrière-plan / des accès / du sol / des murs / des aménagements principaux, espace continu, cohérent et réutilisable, sans personnage
---

# Prompt final de scène (plan d'ensemble en grand angle · décor vide sans personnage)

Ce qui est généré est une image de scène en **plan d'ensemble en grand angle net (establishing shot)** : un décor pur et vide **totalement sans personnage**, montrant intégralement **les positions relatives figées de l'avant-plan, du plan intermédiaire, de l'arrière-plan, des accès, du sol, des murs et des aménagements principaux**, avec une structure spatiale continue, cohérente et réutilisable.

Cette image sert d'ancre de référence de fond pour tous les plans de cette scène : le spectateur comme le modèle doivent pouvoir lire dans cette image la disposition complète de l'espace — par où l'on entre et sort, quelle est la texture du sol et des murs, où se trouve fixé chaque aménagement clé. Le point de vue doit être stable et d'usage général.

## Structure de sortie (assemblez un seul paragraphe cohérent dans cet ordre, la langue suit la consigne de langue de la session)

```
Plan en grand angle à caméra fixe, establishing shot net, [lieu + texture d'époque], [plage horaire],
composition en trois couches : avant-plan ([éléments d'avant-plan]), plan intermédiaire ([espace principal du plan intermédiaire]), arrière-plan ([profondeur de l'arrière-plan]),
accès ([position et style des portes / passages]), sol ([matière et état du sol]), murs ([matière et couleur des murs]),
[aménagements principaux et leurs positions relatives figées],
structure spatiale continue et cohérente,
[source de lumière + température de couleur + contraste clair-obscur], [ambiance],
aucun personnage dans l'image, scène vide, rendu cinématographique
```

## Règles de structure spatiale

L'espace doit être **lisible, cohérent et réutilisable** :

- **Avant-plan** : éléments de cadrage / d'occlusion (encadrement de porte, coin de table, plante, bord d'une machine) qui créent la profondeur — écrire 1-2 éléments concrets
- **Plan intermédiaire** : espace principal de la scène et aménagements essentiels (chaîne de fabrication, couchage, comptoir)
- **Arrière-plan** : prolongement de l'espace (mur lointain, fenêtre, couloir, silhouette urbaine)
- **Accès** : la position et le style des portes, escaliers et passages doivent être explicites (par ex. « une porte de fer sur la gauche du cadre ») ; c'est la base des entrées et sorties des personnages dans les plans suivants
- **Sol et murs** : matérialisez matière, couleur et état (par ex. « sol en béton taché d'huile », « mur d'enduit à la chaux écaillé par plaques »)
- **Aménagements principaux** : écrivez 2-4 aménagements essentiels et leurs **positions relatives figées** (par ex. « la chaîne de fabrication longe le mur et s'achève au bar ») ; les relations gauche-droite / proche-lointain entre les aménagements doivent être cohérentes — ne vous contentez pas d'énumérer des noms d'objets

## Personnages (règle dure · priorité maximale)

**Aucun être humain ne doit apparaître dans l'image de scène — ne conservez que la scène elle-même.**

- Le prompt ne décrit aucun personnage et n'évoque rien de lié à des personnages
- Toute information relative à des personnages présente dans la description de la scène (prompt) est ignorée et ne s'écrit pas dans le prompt
- Le prompt doit se terminer par : « aucun personnage dans l'image, scène vide »

Les aménagements, la texture d'époque et les éléments visuels clés du `prompt` (description de scène) doivent être intégralement retranscrits ; `lighting` (lumière de la scène) doit être rendu concret : direction des sources, température chaude ou froide, contraste clair-obscur (par ex. « les néons du plafond émettent une lumière blanche froide, projetant des ombres dures sous les machines »).

## Point de vue et ambiance

- Grand angle stable à hauteur d'œil ou légèrement en plongée ; pas de plongées et contre-plongées extrêmes, pas de fisheye, pas de composition penchée (l'image sera réutilisée en boucle comme scène fixe)
- Déterminez la plage horaire et la tonalité lumineuse à partir de `location` + `time` (la lumière du jour / de nuit / du crépuscule est radicalement différente)
- Rendez les mots d'ambiance concrets : « oppressante » → « air étouffant, lumière sombre et sourde », n'écrivez pas seulement des mots d'émotion abstraits
- La sortie utilise la langue cible indiquée par la consigne de langue de la session, sans mélanger de mots hors sujet

## Interdictions

- Tout personnage — **aucun être humain ne doit apparaître dans l'image de scène ; ne conservez que la scène elle-même**
- Textes, écritures lisibles sur les enseignes, filigranes, signatures, logos de marques réelles
- Flou de mouvement, objets en mouvement (l'image de référence de scène doit être immobile et stable)
- Énumération d'aménagements sans positions relatives (la structure spatiale doit être continue et cohérente)

## Enregistrement

