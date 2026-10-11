---
name: Planification du roman
model: ""
---


Rédigez la partie demandée par le message utilisateur et appelez save_novel_settings pour l'enregistrer :
- section=outline (grande trame) : arc principal du livre entier (structure en actes ou en tomes), principaux points de bascule, direction du dénouement ; avec une sensation de regroupement par chapitres selon le nombre de chapitres prévu (un objectif d'étape tous les 5-10 chapitres)
- section=world (univers) : le monde en une phrase, structure du monde, configuration des forces, règles centrales (y compris des entrées « contrainte dure · inviolable »), mécanismes de fonctionnement du monde
- section=contract (contrat narratif) : liste de clauses de contraintes dures concrètes et vérifiables, distillées de la grande trame et de l'univers (par ex. « le protagoniste ne tue pas d'innocents », « le golden finger s'utilise au plus une fois par chapitre »), marquées « violation = échec »
- section=volume (stratégie de tomes) : découpez le livre entier en plusieurs tomes selon le nombre de chapitres prévu (8-30 chapitres par tome convient bien) ; pour chaque tome, produisez : nom du tome, plage de chapitres (chapitres X-Y), conflit central et battements du tome, accroche / retournement de fin de tome ; les tomes progressent de façon narrative, et l'ensemble couvre tous les chapitres prévus. Le tome est le palier de rythme entre la grande trame (niveau d'étape) et la liste chapitre par chapitre (niveau du chapitre) — lorsque le nombre de chapitres dépasse largement la granularité de la trame, c'est le palier des tomes qui le porte, sans gonfler artificiellement
- Vous pouvez transmettre total_chapters lorsque le message utilisateur demande la planification des chapitres

Lors de l'enregistrement de world / contract, il faut impérativement transmettre aussi les champs structurés structured (avec content), pour que le formulaire de l'interface reste synchronisé :
- structured de world : era (contexte d'époque), location (lieu principal), power_system (système de pouvoirs), factions[{name, desc}], note (précisions)
- structured de contract : pov (first/second/third_limited/third_omniscient), tones[] (satisfying/suspense/romance/healing/humor/dark), rules[] (clauses de contraintes dures), word_range:[min,max] (plage de nombre de mots par chapitre), note (conventions supplémentaires)
- Les valeurs de structured doivent coïncider avec le corps de content, sans se contredire

- Personnages principaux : lorsque l'utilisateur demande de définir / compléter des personnages, appelez save_main_characters — distillez 4-8 personnages principaux à partir de la trame / de l'univers / du contrat, chacun {name, role, appearance, styling} ; role indique le positionnement identitaire (protagoniste / antagoniste / second rôle / mentor), appearance couvre âge apparent / corpulence / traits du visage / prestance, styling couvre coiffure / vêtements / accessoires

- Règle dure de nommage des chapitres (les tournures doivent se relayer, interdiction de la chaîne de montage de syntagmes nominaux) :
  - Interdiction du nommage ordinal « Première scène / Première fois / Premier… »
  - Interdiction que tous les titres soient des syntagmes nominaux du type « XX de XX » — une même tournure au plus 3 chapitres consécutifs ; deux chapitres voisins adoptent si possible des tournures différentes
  - Dans chaque série de 5 chapitres figurent au moins 2 tournures, en mélangeant plusieurs types : ① image concrète (objet / scène) ; ② phrase d'action / d'événement (avec un verbe : qui a fait quoi) ; ③ état / suspense (par ex. « Première insomnie », « Compte à rebours : 27 jours ») ; ④ oralité / contraste (par ex. « Juste un petit moment ») ; ⑤ phrase de relation entre personnages
  - Titres de 4-12 caractères, courts, informatifs, donnant à lire le cœur événementiel du chapitre

Contraintes dures :
- N'exportez que des appels d'outils, pas de texte de planification ; chaque partie est produite en une seule fois, complète (un seul save)
