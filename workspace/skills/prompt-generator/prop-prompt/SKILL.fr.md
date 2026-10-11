---
name: prop-prompt
description: Norme du prompt final d'accessoire — nature morte sur fond blanc, point de vue standard de photographie produit : proportions exactes, contours complets, arrière-plan sans charge narrative
---

# Prompt final d'accessoire (fond blanc, objet seul · photographie produit standard)

Ce qui est généré est une image produit sur fond blanc (product shot) : **avec un point de vue standard de photographie produit**, le cadre ne contient que l'accessoire lui-même, isolé sur un fond blanc pur, **sans qu'aucun autre élément ne s'y mêle** — pas d'autres objets, pas de personnage, pas d'environnement de scène, pas de main qui le tient.

Trois exigences impératives :
1. **Proportions exactes de toutes les parties de l'objet** — aucune exagération, déformation ni étirement stylisé ; les rapports de taille relatifs de l'accessoire doivent être vrais
2. **Contours complets** — l'accessoire entre en entier dans le cadre, avec une marge tout autour ; aucune partie ne doit être rognée par le bord du cadre
3. **L'arrière-plan ne porte aucun contenu narratif** — le fond blanc pur n'est qu'un fond de substitution, sans sensation de lieu, sans allusion à une intrigue, sans élément décoratif

## Structure de sortie (assemblez un seul paragraphe cohérent dans cet ordre, la langue suit la consigne de langue de la session)

```
Image produit d'un objet seul, point de vue standard de photographie produit, [nom de l'accessoire + matière / couleur / forme / taille + degré de vétusté et détails d'usure],
proportions exactes de toutes les parties de l'objet, isolé sur un fond blanc pur, centré et entièrement dans le cadre, contours complets sans recadrage,
arrière-plan épuré ne portant aucun contenu narratif, aucun autre objet, aucun personnage, aucune scène,
lumière de studio douce et uniforme, ombres légères, haut niveau de détail
```

## Règles de génération

- Partez du `name` (nom) et de la `description` (apparence de l'objet) de l'accessoire : matière, couleur, forme, taille, degré de vétusté, traces d'usure et autres détails physiques doivent être **retranscrits point par point**, car ils sont la source de la reconnaissabilité de l'accessoire
- Point de vue standard de photographie produit : vue aux trois quarts légèrement en plongée (permet de voir à la fois le dessus et un côté, au maximum de volume) ; les accessoires plats (papier, pièces d'identité, photos) se traitent en vue de dessus à plat
- L'objet seul est présenté centré et complet, avec une marge tout autour, proportions exactes et contours complets ; ne rognez pas le corps de l'accessoire
- Lumière de studio douce et uniforme, ombres légères, haut niveau de détail
- Décrivez uniquement l'objet lui-même ; n'évoquez ni l'intrigue, ni les personnages, ni l'usage (ni l'arrière-plan ni le cadre ne portent de contenu narratif)
- La sortie utilise la langue cible indiquée par la consigne de langue de la session, sans mélanger de mots hors sujet ; **pas** de termes du type « rendu cinématographique » (une image d'accessoire est une image produit, pas une photo de plateau)

## Interdictions

- Main qui tient l'objet, personnages, autres objets, environnement de scène dans le cadre
- Emballage, socle, présentoir (sauf s'ils font partie intégrante de l'accessoire lui-même)
- Textes, filigranes, signatures, logos de marques réelles (les textes et motifs imprimés sur le corps de l'accessoire peuvent être conservés et décrits)
- Reflets d'environnement, lumière colorée
- Perspective exagérée, déformation, proportions faussées, contours rognés

## Enregistrement

