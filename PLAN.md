# renpy_maker — plan d'architecture (brouillon)

Objectif : produire un jeu Ren'Py complet (scénario, personnages, images, éventuellement vidéos) à partir de LLM, d'agents et de ComfyUI.

## Briques existantes (vérifiées)

| Brique | Chemin | Rôle dans le projet |
|---|---|---|
| agent-slapsci | `/home/yopla/PycharmProjects/agent-slapsci` | Agents pilotés par YAML (`agent-slapsci -c config.yaml`), `AgentPool` avec délégation entre agents, outils de fichiers et skills. Sert à l'écriture et à la conception. |
| hopa_aom | `/home/yopla/PycharmProjects/hopa_aom` | Mémoire AOM en SQLite (`aom_format` = contrat, `aom_ingest` = écriture, `aom_query` = lecture). Sert de mémoire de continuité : personnages, lieux, faits établis, événements déjà joués. |
| ComfyUI | `/home/yopla/Applications/SD/comfyui/Comfyui` | Génération d'images et de vidéos. API HTTP : `POST /prompt` (workflow JSON), `GET /history/{id}`, `GET /queue`. Port par défaut 8188 (à confirmer sur cette installation). |
| Ren'Py | **non installé** | Moteur du jeu. Les scripts sont des fichiers `.rpy`. |

## Architecture proposée

```
  idée / contraintes
        │
        ▼
 [1] Agents de conception (agent-slapsci, AgentPool)
     scénariste · designer personnages · directeur de scènes · vérificateur de continuité
        │  écrit une spec structurée (YAML/JSON) + mémoire AOM du jeu (hopa_aom)
        ▼
 [2] Spec du jeu  (game_spec/*.yaml : personnages, lieux, scènes, embranchements, prompts visuels)
        │
        ├──► [3a] Génération d'assets (ComfyUI)
        │         prompts visuels → workflows → images/ et vidéos/ du jeu
        │
        └──► [3b] Compilateur spec → .rpy  (Python déterministe, PAS de LLM)
                  + renpy lint pour valider la syntaxe
        │
        ▼
 [4] Projet Ren'Py jouable (game/)  — lancement et test manuel
```

### Principes

- **Le LLM écrit la spec, le code produit le `.rpy`.** La syntaxe Ren'Py ne doit pas dépendre d'une génération libre : le compilateur est déterministe et testable.
- **La spec est la source de vérité.** Les agents la modifient, pas les fichiers `.rpy` générés.
- **La continuité passe par la mémoire AOM** : avant chaque scène, on interroge le jeu (qui sait quoi, quel état, quels choix ont été faits).
- **Les assets sont adressés par identifiant** dans la spec ; les prompts ComfyUI sont dérivés de la spec, avec une graine fixée pour la reproductibilité.

## Découpage en étapes

1. Installer Ren'Py et vérifier qu'il lance un projet vide (`renpy lint`).
2. Définir le schéma de la spec (YAML) avec un exemple d'une scène.
3. Compilateur spec → `.rpy` (dialogues, personnages, choix, variables), avec tests.
4. Client ComfyUI minimal : un workflow, envoi, attente, récupération de l'image.
5. Agents de conception dans agent-slapsci (config YAML + prompts).
6. Branchement de la mémoire AOM (un jeu = une base SQLite).
7. Boucle complète sur une courte histoire de test.

## Points à trancher

1. **Concept** : genre, ton, langue du jeu (français ?), longueur visée (une scène, un chapitre, un jeu complet ?).
2. **Fournisseur LLM** pour les agents : Anthropic, OpenAI, local (Ollama / llama.cpp) ?
3. **Chemin d'installation de Ren'Py** (ou autorisation de le télécharger dans le projet).
4. **Modèles ComfyUI disponibles** (checkpoints, LoRA) : le style visuel en dépend.
5. **Vidéo** : indispensable au premier jet, ou plus tard ?
