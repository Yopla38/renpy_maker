# Mode « récit » : un jeu de rôle guidé

Branche : `recit` (créée à partir de `ui`). Ce mode s'ajoute à côté de `/atelier` et de `/facile` : aucune
page, aucun module existant n'est modifié, sauf pour réutiliser leurs fonctions.

## L'idée

On donne le cadre (titre, idée, ambiance, style), puis l'histoire s'écrit devant nous, comme un jeu de rôle
simple : le récit avance, on répond, il réagit.

- Le récit avance par **lignes de vie** (une suite de moments). À chaque moment : une réplique proposée par
  l'IA, éventuellement une **voix off** (narration qui suit le récit), et une **image**.
- À certains moments, le récit propose des **choix**. Choisir ouvre une ligne de vie ; choisir autrement en
  ouvre une autre. On peut vivre une ligne jusqu'au bout, revenir à un choix, et en vivre un autre.
- Deux lignes peuvent se **rejoindre** au même point, ou rester séparées. Un choix peut aussi n'être qu'une
  **sortie de branche** qui revient au même endroit (la ligne sort, puis retourne dans la ligne principale).
- Tout est **modifiable** : la réplique proposée, la voix off, et le choix. La voix off peut aussi **changer le
  cours des choses** : l'auteur écrit ce qui doit arriver, l'IA reprend le fil à partir de là.

## Parcours

1. **Cadre** : titre, idée, ambiance, style des images (étapes existantes de `/atelier`).
2. **Préparatif des personnages** : propositions, description, genre et âge, dessin (repris de l'atelier).
3. **Boucle de récit**, pour chaque moment :
   - la réplique proposée (modifiable) et la voix off proposée (modifiable, facultative) ;
   - si le moment est un choix : 2 ou 3 choix proposés, ou un choix écrit par l'auteur ;
   - l'image proposée, avec le cadrage et le point de vue ; l'auteur peut **garder l'ancienne image** si elle
     convient encore (économie de ressources : pas de nouvelle génération) ;
   - **Générer** ; une roue ouvre les détails (prompt, panneau de références, LoRA).
4. **Lignes de vie** : une vue en graphe (on voit les lignes, leurs choix, leurs rencontres) pour revenir à
   un choix, vivre une autre ligne, ou rassembler deux lignes.

## Ce qui est réutilisé (tel quel)

- Les données : une **ligne de vie = une scène** (même modèle qu'aujourd'hui) ; un **choix** = un `choice` de
  la scène ; une **sortie qui revient** = un choix vers une scène qui rejoint la suite (`next`) ; une **voix
  off** = une réplique du locuteur `Narration`.
- Les fonctions existantes : proposition de personnages et de lieux, proposition de réplique, description de ce
  qui est à l'écran, prompts, dessin, références, copie d'image, graphe des routes (`story_graph`).
- Les histoires déjà faites restent lisibles dans tous les modes.

## Ce qui est nouveau

- Une page `/recit` et des routes `/api/recit/...`, dans un module `recit.py`.
- Une proposition **à chaque pas** : réplique, voix off, choix, cadrage de l'image.
- La réutilisation d'image : si le point de vue et le cadrage ne changent pas, le moment garde le candidat
  existant au lieu d'en générer un nouveau.

## Phases proposées

- **P1** : cadre, préparatif, boucle d'une seule ligne (réplique, voix off, image, « ligne suivante »).
- **P2** : les choix, et plusieurs lignes de vie avec leur retour au choix.
- **P3** : rassembler deux lignes, sorties de branche qui reviennent au même point.
- **P4** : réutilisation d'image, roue de détails, « changer le cours des choses ».

## Ce qui a été fait

Tout se joue sur `/recit` (lien « Jouer le récit » sur la page des histoires). Le joueur est **dans** l'histoire ;
les réglages restent à portée, mais discrets.

- **Cadre**, puis **personnages** (propositions de l'IA, ajout à la main, portrait, garde-robe dans l'atelier).
- **La scène** : l'image, la voix off dans un encadré jaune (récitatif de BD), la réplique dans une bulle avec le
  nom de qui parle. Tout est modifiable sur place. « Garder l'image » ou « Nouvelle image » (avec ce que l'on
  voit). **Continuer** (ou Entrée) garde le moment ; le suivant est proposé tout seul.
- **Votre voix** : micro (reconnaissance vocale du navigateur, Chrome conseillé ; touche M) ou texte. La consigne
  part au « metteur en scène » (le modèle de langage), qui l'applique :
  - sur le moment proposé : « elle est assise », « plutôt avec sa robe rouge », « Tom refuse » ; une tenue qui
    n'existe pas encore est ajoutée à la garde-robe ; une consigne durable (« Léa ne sourit jamais ») est retenue ;
  - sur une image déjà vécue (ouverte depuis le fil) : description, cadrage, point de vue, personnages, tenues,
    et le prompt est réécrit ; « Redessiner » ensuite ;
  - devant un choix : la consigne devient votre propre choix.
- **Choix** : proposés avec un moment (ou sur demande), touches 1 à 4, ou « Autre chose… ». Chaque option ouvre une
  ligne ; les autres restent à vivre. Les choix en attente survivent à un rechargement de la page.
- **Le fil** (en bas) : la ligne vécue, image par image. Une image ouverte montre ses répliques (modifiables) et,
  après chaque réplique, « vivre autrement » : la ligne se sépare, la suite d'avant reste une option, et la
  nouvelle ligne pourra **revenir au fil**.
- **Lignes de vie** : la carte (lignes à vivre, fins, choix). Vivre une ligne, aller au prochain choix, rejoindre
  une autre ligne à un moment précis, revenir au fil, terminer, rouvrir, renommer un choix.
- **Rejouer** : relire l'histoire comme le jeu, en choisissant aux carrefours.
- **La roue** (en haut à droite de l'image) : qui est là, lieu et décor, cadrage, point de vue, personnages
  visibles, tenues, références (écarter, ajouter), continuité, prompt (proposer, enregistrer), LoRA, reprendre une
  image existante, dessiner ; dessin automatique de chaque nouvelle image ; cadre, personnages, modèles.

Choix retenus pour les questions de départ :

1. **Rassembler** : à la main, depuis la carte (« Rejoindre une autre ligne », à n'importe quel moment de la
   scène visée) ; une sortie de branche propose « Revenir au fil ».
2. **Choix** : le conteur en propose 2 ou 3 ; le joueur peut toujours écrire le sien (4 au plus).
3. **Voix off** : seulement quand le récit en a besoin ; elle reste modifiable ou effaçable.
4. **Garder l'image** : le conteur le propose quand rien ne change à l'écran ; le joueur décide. Un nouveau lieu
   demande toujours une nouvelle image. Une image gardée n'est jamais modifiée par les réglages d'un autre
   moment : redessiner ou régler ce moment lui donne sa propre image.

Données : `story.yaml` reçoit `recit` (ligne en cours, ambiance, consignes, dernier moment pour « Annuler »,
choix en attente) et, sur les scènes, `open` (ligne qui attend sa suite) et `return_to`. Les autres modes
lisent l'histoire comme avant ; seule la carte (`story_graph`) sait qu'une ligne ouverte n'est pas une impasse.

Limite connue : l'export Ren'Py et le lecteur `/jouer` restent linéaires (ils ignorent les choix), comme avant.
