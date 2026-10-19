# renpy_maker — conception détaillée

Ce document complète `PLAN.md`. Il fixe les décisions d'architecture avant le code.

## 1. Contraintes

- **Cible finale** : une machine locale avec 2× RTX 5090 (64 Go VRAM au total), 128 Go de RAM. Tout modèle utilisé en test sur Replicate doit donc pouvoir tourner en local.
- **Phase de test** : Replicate (API) pour valider vite les modèles et le pipeline, sans infrastructure.
- **Bascule** : passer de Replicate à ComfyUI doit se faire par configuration, sans réécrire le pipeline.
- **Histoire** : un graphe de scènes avec dialogues, choix et images. Premier chapitre : érotique simple.
- **Cohérence** : les modèles de génération pure ne tiennent pas un personnage d'une image à l'autre. On passe par des modèles d'édition (FLUX.2 Klein 9B) avec images de référence.

## 2. Architecture en couches

```
 config.yaml (choix des backends : llm, image, video)
        │
 ┌──────┴────────────────────────────────────────────────────────┐
 │ Couche 1 — Fournisseurs (interfaces, implémentations)         │
 │   LLMProvider : anthropic | openai | ollama                    │
 │   ImageBackend : generate(prompt,size,seed)                    │
 │                  edit(prompt, refs[], size, seed)              │
 │       ├─ ReplicateImageBackend  (test)                         │
 │       └─ ComfyImageBackend      (production, workflows JSON)   │
 │   VideoBackend : plus tard (Wan 2.2 via ComfyUI)               │
 ├───────────────────────────────────────────────────────────────┤
 │ Couche 2 — Registre d'actifs (assets)                          │
 │   personnages, tenues, lieux : id, description, images de      │
 │   référence validées, statut (brouillon / validé / rejeté)     │
 ├───────────────────────────────────────────────────────────────┤
 │ Couche 3 — Graphe d'histoire (spec YAML, source de vérité)     │
 │   scènes, lignes de dialogue, choix, variables, actifs utilisés │
 ├───────────────────────────────────────────────────────────────┤
 │ Couche 4 — Compilateur déterministe → game_project/game/*.rpy  │
 │   + renpy lint                                                 │
 └───────────────────────────────────────────────────────────────┘
```

Règle : le LLM ne produit que des données (graphe, prompts). Aucune étape de code Ren'Py n'est générée librement.

## 3. Cohérence des personnages

C'est le point dur. Décisions :

1. **Ancres canoniques.** Chaque personnage a une image d'identité (ancre) générée une fois, puis validée par l'humain. Chaque tenue a sa propre ancre, chaque lieu aussi.
2. **Toute image de scène est une édition, jamais une génération libre.** Entrée : ancre du personnage + ancre de tenue + ancre de lieu. Sortie : la scène demandée (pose, expression, cadrage).
3. **Éditer depuis les ancres, pas depuis la dernière image.** Enchaîner des éditions sur la sortie précédente accumule la dérive. Chaque image dépend donc uniquement des ancres et de sa description.
4. **Validation humaine avant usage.** Les ancres ne passent dans le graphe qu'avec le statut « validé ». Une image rejetée est régénérée avec la même requête et une graine différente, jusqu'à validation.
5. **Graine et paramètres enregistrés** dans un manifeste par image (modèle, version, graine, prompt, références). Un rendu est donc reproductible et réutilisable sans coût.

Limite à vérifier : Klein accepte plusieurs images de référence. Il faut tester combien de références restent bien prises en compte avant de fixer la règle « personnage + tenue + lieu ».

## 4. Modèle d'édition

- **FLUX.2 Klein 9B** est le modèle de référence (vous l'avez demandé). En local, le fichier `unet/flux-2-klein-9b-fp8.safetensors`, le VAE `vae/flux2-vae.safetensors` et un encodeur de texte Qwen3 sont présents ; l'encodeur `qwen_3_8b_fp8mixed.safetensors` est actuellement un fichier de 146 octets, à réparer.
- **Aucun des workflows fournis n'utilise Klein.** `FLUX2_API.json` utilise Kontext. Il faudra écrire un workflow Klein d'édition multi-référence, ou adapter celui-ci.
- **Licence** : une source indique que Klein 9B est sous licence FLUX non commerciale. À vérifier avant toute diffusion commerciale du jeu.
- **Replicate** : je n'ai pas pu confirmer le nom exact du modèle Klein 9B ni ses paramètres sur Replicate. D'autres hébergeurs (Eachlabs, MuAPI, Oxen, Opper) proposent des variantes, avec des prix de l'ordre de quelques centimes par image. À confirmer depuis votre compte.
- **Parité de test** : les versions hébergées et les versions locales quantifiées (fp8) ne donnent pas exactement les mêmes images, et les graines ne sont pas portables. Les tests de cohérence doivent donc être refaits en local avant validation finale.

## 5. Modèles de génération de base

Pour les ancres initiales (sans référence), on peut utiliser un modèle de texte vers image, par exemple Z-Image Turbo (workflow `_dbimage_z_image_turbo.json`, déjà testé en local). Il reste en test sur Replicate avec un modèle équivalent si disponible.

## 6. Graphe d'histoire et budget d'images

- Chaque scène référence des actifs par identifiant (`char:eve`, `outfit:eve_robe_soir`, `loc:chambre`). Les images sont produites par action de rendu, pas à la main.
- **Budget** : nombre d'images = ancres + (scènes × images par scène). Le pipeline doit afficher ce budget avant de lancer le rendu, avec le coût estimé sur Replicate.
- **Réutilisation** : un lieu et une tenue n'ont qu'une ancre, réutilisée par toutes les scènes. Les choix qui ne changent que le texte ne demandent aucune nouvelle image.
- Les embranchements n'ont besoin de nouvelles images que si la scène change visuellement.

## 7. Sécurité du contenu et fournisseurs

Point important pour la phase de test :

- **Anthropic** interdit en général le contenu sexuellement explicite dans l'API. Des scènes romantiques ou sensuelles restent possibles selon les conditions.
- **Replicate** héberge des modèles qui appliquent souvent des filtres de sécurité sur les images. Des requêtes explicites peuvent être refusées ou censurées, ce qui rend les tests sur Replicate non représentatifs de la production locale.
- Conséquence : valider le pipeline (structure, cohérence, graphe, compilation) sur Replicate avec du contenu non explicite. Valider le contenu explicite uniquement en local, avec les modèles qui le permettent.

À vérifier avant de dépendre d'un fournisseur : ses règles exactes et ses filtres sur ce type de contenu.

## 8. Feuille de route

| Phase | Contenu | Sortie vérifiable |
|---|---|---|
| P0 | Configuration des backends (`config.yaml`), réparation du chemin Windows et de l'encodeur Qwen3, test Klein sur Replicate avec un prompt non explicite | Une image éditée depuis une ancre |
| P1 | Registre d'actifs, génération d'ancres avec validation humaine, test de cohérence (3 tenues, 3 lieux) | Manifeste d'actifs validés |
| P2 | Schéma du graphe, compilateur `.rpy`, petit embranchement de test (3 scènes, 1 menu) | `renpy lint` sans erreur, jeu jouable |
| P3 | Écrivain LLM : produit le graphe selon le schéma, validé à l'entrée du compilateur | Un chapitre complet généré et compilé |
| P4 | Backend ComfyUI pour Klein (workflow d'édition), bascule par configuration | Mêmes actifs rendus en local |
| P5 | Vidéo Wan 2.2 (plus tard, selon le résultat du test précédent) | — |

## 9. Points à trancher avec vous

1. **Fournisseur de l'écrivain** : Anthropic (avec limites sur l'explicite) ou un modèle local ?
2. **Licence de Klein** : acceptable pour un usage personnel uniquement, ou faut-il un modèle libre pour une diffusion ?
3. **Compte Replicate** : pouvez-vous définir la variable `REPLICATE_API_TOKEN` dans l'environnement (et non dans le chat) pour que je puisse interroger le catalogue et lancer les tests ?
4. **Style visuel** : à fixer avant la génération des ancres (il conditionne le modèle de base).
5. **Disque Windows** : il n'est plus monté depuis ce shell. Les liens vers `checkpoints/` et `loras/` sont donc cassés. Pouvez-vous le remonter ?
