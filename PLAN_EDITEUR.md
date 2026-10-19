# Éditeur d'histoire — plan du point de vue de l'utilisateur

Objectif : un auteur décrit vaguement une histoire, obtient une trame structurée, la corrige à sa main, génère les images de tous les éléments, puis définit les chemins. Quand la trame est validée, on passe à l'écriture des scènes et au rendu.

Cette étape s'arrête à la **trame validée** : histoire, personnages, lieux, tenues, images validées, chemins. Les dialogues détaillés et le compilateur Ren'Py viennent après.

## 1. Parcours de l'auteur

```
[1] Idée  →  [2] Plan  →  [3] Personnages & lieux  →  [4] Images  →  [5] Chemins  →  [6] Trame validée
  texte       arbre         fiches + ancres          lot à valider     graphe         verrouillage
  libre       éditable      éditables                                                  (étape suivante)
```

Chaque étape a un bouton « Suivant » qui n'est actif que si l'étape précédente est complète. Chaque étape reste accessible en arrière : rien n'est figé tant que la trame n'est pas validée.

### Étape 1 — Idée
- Champ de texte libre : quelques lignes sur le sujet, le ton, le cadre.
- Réglages : nombre de scènes visé, nombre de chapitres, public (adulte, indication de contenu), langue du texte (français pour le jeu).
- Bouton « Générer le plan ».

### Étape 2 — Plan (arbre éditable)
Le LLM produit une structure, qui s'affiche comme un arbre :
- **Synopsis** (résumé en quelques phrases, modifiable)
- **Chapitres**, chacun avec un titre et un résumé
- **Scènes** dans chaque chapitre : titre, résumé, personnages présents, lieu, tenue(s), et éventuellement un **choix** qui ouvre un embranchement
- **Fins** possibles

Actions de l'auteur :
- modifier n'importe quel texte en ligne
- ajouter, supprimer, déplacer une scène ou un chapitre
- **régénérer** une seule scène ou un seul chapitre, avec une consigne (« plus tendu », « fin plus douce »), sans toucher au reste
- **verrouiller** un élément : le régénérer ne doit jamais l'écraser
- historique : annuler / rétablir

Règle : le LLM ne renomme jamais un élément verrouillé, et ne supprime jamais un élément sans confirmation.

### Étape 3 — Personnages et lieux
Le plan fait apparaître des personnages, des tenues et des lieux. Chacun devient une **fiche** :
- nom, rôle, description (modifiables)
- pour un personnage : liste de tenues, avec une tenue par défaut
- pour un lieu : description, ambiance
- statut : à créer / existant

Renommer une fiche met à jour toutes les scènes qui la citent. Les identifiants internes ne changent jamais : le nom est affiché, l'identifiant est technique (c'est déjà le cas dans `assets.yaml`).

### Étape 4 — Images
L'auteur voit la liste complète de ce qu'il faut générer, avec une estimation de coût et de durée :
- une **ancre** par personnage, par tenue et par lieu
- les ancres sans référence utilisent `flux-dev`
- les tenues et lieux qui dépendent d'un personnage utilisent Klein, avec l'ancre du personnage en référence

Pour chaque élément :
- « Générer » (un candidat, avec le prompt modifiable avant envoi)
- « Régénérer » (autre graine, même prompt)
- galerie de candidats, valider ou rejeter
- un élément n'est « prêt » que lorsqu'un candidat est validé

Un bouton « Générer tout ce qui manque » lance le lot, en séquence (ancres d'abord, éditions ensuite), avec une barre de progression. Les échecs sont listés, pas silencieux.

### Étape 5 — Chemins
Vue en graphe : chaque scène est un nœud, chaque choix une flèche.
- l'auteur crée les embranchements (ajouter un choix, pointer vers une scène)
- la liste des **chemins complets** est calculée automatiquement : de la première scène à une fin
- pour chaque chemin : scènes traversées, personnages et lieux utilisés, éléments encore non validés
- un chemin ne peut pas être validé si un de ses éléments est en attente d'image

Contrôles automatiques : scène sans sortie, fin inaccessible, boucle infinie non voulue, choix pointant vers une scène supprimée.

### Étape 6 — Trame validée
Une fois toutes les étapes vertes :
- la trame est verrouillée (les modifications repassent par un « déverrouiller » explicite)
- on passe à l'étape suivante : écriture des dialogues scène par scène

## 2. Ce que l'auteur ne doit pas avoir à faire

- écrire un prompt d'image pour chaque élément : l'application en propose un à partir de la fiche, modifiable
- savoir ce qu'est une ancre ou un modèle : les mots « flux-dev » et « Klein » n'apparaissent qu'en détail technique
- relancer chaque étape à la main : le lot fait le travail, l'auteur valide

## 3. Modèle de données

```
game_spec/
  story.yaml      # synopsis, chapitres, scènes, choix, fins, verrouillages, historique
  assets.yaml     # personnages, tenues, lieux, candidats  (existant)
  config.yaml     # réglages (existant)
```

`story.yaml`, en gros :
- `chapters[]` → `scenes[]` → `{id, title, summary, characters[], location, outfits{char: outfit}, choices[{label, target}], locked}`
- `endings[]`
- chaque élément a un `id` stable et un `name` modifiable

Les chemins ne sont pas stockés : ils sont calculés à partir du graphe.

## 4. Découpage en lots de travail

| Lot | Contenu | Sortie |
|---|---|---|
| A | Données : `story.yaml`, schéma, validation, historique | Tests sur le modèle de données |
| B | Génération du plan à partir d'une idée (LLM, sortie JSON validée contre le schéma) | Plan généré sur un exemple |
| C | Interface : étapes 1 et 2 (idée, arbre éditable, verrouillage, régénération partielle) | Parcours idée → plan utilisable |
| D | Fiches personnages / lieux / tenues, dérivées du plan, avec génération des ancres | Fiches + images validables |
| E | Lot de génération avec coût estimé, reprise sur échec, galerie | Tous les éléments générés |
| F | Graphe des chemins, contrôles, validation de la trame | Trame verrouillée |

Ordre conseillé : A, B, C, puis D et E (réutilisent le registre d'actifs existant), puis F. Le registre actuel (`assets.py` et la page de test) est repris dans D et E, il ne sera pas jeté.

## 5. Décisions prises

- **Plan chapitre par chapitre** : le LLM produit un chapitre à la fois, l'auteur valide, puis on passe au suivant.
- **Contenu explicite** : une case à cocher dans les réglages du projet. Elle est transmise au LLM et aux modèles d'image. Désactivée par défaut.
- **Page d'accueil = choix des modèles** : LLM (Anthropic, OpenAI, Ollama local…), génération d'image de base (flux-dev sur Replicate ou ComfyUI local), édition (Klein sur Replicate ou ComfyUI local). Chaque rôle a son propre choix, et les réglages sont enregistrés dans le projet.
- **Taille de chaque chapitre** : le nombre de scènes se règle par chapitre, et non globalement.
- **Test** : 6 scènes au total.

## 6. Points à trancher

1. **Plan en un seul appel LLM, ou par chapitres ?** Un seul appel est simple mais limité en longueur. Par chapitres est plus long mais permet de régénérer finement.
2. **Taille cible** : combien de scènes pour un premier chapitre (je propose 6 à 10), et combien de chemins maximum à gérer dans l'interface.
3. **Contenu explicite** : le plan et les dialogues doivent être produits par un fournisseur qui l'autorise. À régler avant lot B, car un refus au milieu d'un plan coûte du temps.
4. **Interface** : page locale (comme aujourd'hui) suffit pour un usage personnel. Pas de compte, pas de multi-utilisateur à ce stade.

## 7. Hors périmètre pour l'instant

- écriture des dialogues et des textes de scène
- rendu vidéo (Wan 2.2, mis de côté)
- compilation vers Ren'Py
- partage et multi-utilisateurs

## 8. Composition des scènes (décisions de l'auteur)

- **Pas de sprites** : chaque scène est une image complète, générée par Klein en édition à partir des images de référence.
- **Références d'une scène** : l'image validée du lieu, puis une image par personnage présent. Pour un personnage, on prend l'image validée de sa tenue dans la scène, à défaut son image de base. Klein accepte 5 références au plus : une scène comporte donc au plus 4 personnages (lieu compris dans les 5).
- **Dialogues écrits par le LLM**, par scène, en français. Chaque réplique a un personnage, un texte et une expression indicative.
- **Expressions** : pour l'instant, l'expression est décrite dans le prompt de l'image (Klein sait la modifier). Le modèle d'expressions dédié viendra plus tard ; les expressions sont donc déjà stockées par réplique.
- **Une scène est prête** quand ses dialogues existent et qu'une image de scène est retenue.

Étapes proposées :
1. Dialogues par scène (LLM, JSON validé : personnage, texte, expression).
2. Références automatiques d'une scène, avec contrôle du nombre (≤ 5) et message clair au-delà.
3. Prompt d'image de scène proposé par le LLM (anglais, style de référence, expressions mentionnées), relu par l'auteur.
4. Génération et validation de l'image de scène, dans le même registre que les autres images (kind "scene", format 16:9).
