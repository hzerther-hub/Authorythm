---
name: character-prompt
description: Norme du prompt final de personnage — gros plan de face + planche multi-vues (character turnaround : face / profil à 90 degrés / dos), servant d'ancre d'apparence pour toutes les générations suivantes
---

# Prompt final de personnage (gros plan de face à gauche + planche multi-vues à droite)

Ce qui est généré est une **planche de référence de personnage (character turnaround sheet / character reference sheet, multi-view concept art layout)**, à cadrage strictement figé :

- **À gauche : gros plan de face** — vue rapprochée de face de la tête et des épaules, traits du visage, coiffure et texture de peau bien visibles, servant d'ancre à la reconnaissance du visage
- **À droite : trois vues corps entier de même hauteur côte à côte — face, profil à 90 degrés, dos** — trois vues corps entier du même personnage alignées à hauteur égale, sommet du crâne et plantes des pieds alignés

**Principe fondamental : cohérence > esthétique.** Cette image est l'ancre d'apparence de toutes les images de personnage et références vidéo ultérieures ; elle doit être neutre, nette et réutilisable — ne cherchez pas l'effet artistique d'une image unique.

## Structure de sortie (assemblez un seul paragraphe cohérent dans cet ordre, la langue suit la consigne de langue de la session)

```
character turnaround sheet, character reference sheet, multi-view concept art layout, orthographic views, no perspective distortion;
gros plan de face à gauche, à droite trois vues corps entier de même hauteur côte à côte — face, profil à 90 degrés, dos ;
les trois vues corps entier en evenly spaced panels, sommet du crâne et plantes des pieds alignés ;
le gros plan et les vues corps entier montrent le même personnage, corps entier dans le cadre, A-pose posture neutre, expression naturelle sans affect affiché,
[âge apparent + genre apparent + corpulence], [traits du visage], [coiffure], [vêtements + accessoires],
le visage, la coiffure et les vêtements du gros plan de face et des trois vues parfaitement identiques,
fond blanc pur, lumière douce et uniforme, rendu cinématographique
```

## Règles d'ordre de description

Placez **les traits les plus reconnaissables en premier**, en couvrant dans cet ordre chaque élément clé de `appearance` (apparence physique) et `styling` (coiffure / costume / maquillage), sans rien omettre :

1. Ancres d'identité : âge apparent (par ex. « dans la jeune vingtaine »), genre apparent, corpulence (grand ou petit, maigre ou rond, habitudes posturales)
2. Traits du visage : forme du visage, yeux, autres marques notables (cicatrice, grain de beauté, lunettes, etc.) — le gros plan de face dépend surtout de cette partie
3. Coiffure : couleur, longueur, style
4. Vêtements : coupe, couleur, matière, état (par ex. « une tenue de travail froissée aux manches marquées de traces de soudure »)
5. Accessoires : n'écrire que les éléments distinctifs, sans accumulation

Les traits de caractère du personnage doivent être convertis en descriptions de prestance et d'expression extérieures (par ex. « rongé par l'épuisement » → « regard fatigué, épaules légèrement affaissées ») ; aucun mot de caractère ne doit apparaître directement.

## Cadrage et cohérence

- Gros plan de face à gauche : face à l'objectif, expression neutre, du sommet du crâne aux épaules entièrement dans le cadre
- Trois vues corps entier à droite : face, profil à 90 degrés et dos du même personnage, **de même hauteur, côte à côte, espacement régulier**, sommets des crânes et plantes des pieds sur une même ligne horizontale
- Le gros plan et les trois vues corps entier doivent partager le même visage, la même coiffure et les mêmes vêtements — écrivez explicitement « le visage, la coiffure et les vêtements du gros plan de face et des trois vues corps entier sont parfaitement identiques »
- Posture neutre, expression naturelle — pour faciliter la réutilisation comme image de référence
- Mains et pieds normaux : dans les vues corps entier, cinq doigts par main et cinq orteils par pied, deux bras et deux jambes, aucun membre surnuméraire ; mains naturellement détendues, sans gestes complexes (pour réduire le risque de mains difformes)
- **Plafond strict du nombre d'instances du personnage : 1 gros plan de face + 3 vues corps entier = 4 instances au total, interdiction d'en afficher davantage** (attention : les 3 vues corps entier sont par conception le même personnage vu sous différents angles — face / profil à 90 degrés / dos — c'est l'intention de conception et non une « copie » ; ce qui est interdit, c'est de redessiner une fois de plus le même personnage en supplément, ou d'ajouter des instances supplémentaires dans le cadre au-delà des 3 vues corps entier ; les 3 vues corps entier doivent présenter des orientations nettement différentes, respectivement face / profil à 90 degrés / dos de gauche à droite, jamais toutes de face)
- Personnage unique : toute l'image ne contient que les 4 instances ci-dessus, sans image fantôme, dédoublement ni reproduction multiple ; traits du visage stables, sans distorsion ni fondu
- Lumière de studio douce et uniforme, pas d'ombres et lumières dramatiques (l'image de référence doit rester utilisable dans tous types de scènes)
- La sortie utilise la langue cible indiquée par la consigne de langue de la session, sans mélanger de mots hors sujet

## Interdictions

- Postures dynamiques, expressions exagérées, objets en main, présence d'autres personnes dans le cadre
- **Plus de 4 instances du personnage (1 gros plan + 3 vues corps entier) ; les 3 vues corps entier sont le même personnage vu sous différents angles (face / profil à 90 degrés / dos) — c'est l'intention de conception, pas un point interdit ; ce qui est interdit : copier le même personnage en plus des 3 vues corps entier, ou dessiner les 3 vues toutes de face / toutes entassées au centre du cadre / chevauchées / à des hauteurs différentes**
- Recadrage du corps (les vues corps entier doivent être full body, du sommet du crâne aux plantes des pieds entièrement dans le cadre ; le gros plan doit montrer tête et épaules complètes)
- Six doigts, doigts fusionnés, doigts manquants, malformations par fusion ; trois mains, trois jambes, membres surnuméraires, duplication distordue
- Images fantômes, dédoublements, reproduction en plusieurs exemplaires ; traits du visage déformés, visage fondu
- Textes, étiquettes, filigranes, signatures ; logos de marques réelles, visages de célébrités réelles
- Ombres denses, lumière de fond colorée, objets en arrière-plan

## Enregistrement

