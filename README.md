# Renpy Maker

Éditeur d'histoires visuelles, qui produit un jeu Ren'Py : scénario, personnages, lieux, tenues, répliques,
images et routes. Le texte est écrit par un modèle de langage (Anthropic, OpenAI, Ollama ou Replicate) ; les
images sont dessinées par Replicate ou par ComfyUI installé sur ta machine.

Tout tourne en local : le serveur écoute uniquement sur `127.0.0.1`.

---

## 1. Installation

Prérequis : [uv](https://docs.astral.sh/uv/) et Python 3.10 ou plus récent (uv peut l'installer).

```bash
uv sync                 # installe les dépendances (PyYAML) et le paquet renpy_maker
uv run python -m pytest -q   # lance les tests (hors ligne, sans appel au modèle)
```

Le code est dans `src/renpy_maker/`. Les pages web sont dans `src/renpy_maker/webapp/`.

---

## 2. Lancer l'application

```bash
uv run renpy-maker
```

Puis ouvre **http://127.0.0.1:8765/projets** dans ton navigateur (Chrome conseillé).

Au démarrage, l'application reprend la **dernière histoire ouverte**. Pour en choisir une autre, va sur
« Mes histoires » (`/projets`).

### Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `RENPY_MAKER_PORT` | port du serveur | `8765` (souvent pris : utilise `8766`, etc.) |
| `RENPY_MAKER_MODE` | `expert` ou `enfants` (voir plus bas) | `expert` |
| `RENPY_MAKER_HOME` | dossier des données (histoires, images, sauvegardes) | la racine du dépôt |
| `RENPY_MAKER_CONFIG_DIR` | dossier qui contient `config.yaml` | la racine du dépôt |

Exemples :

```bash
RENPY_MAKER_PORT=8766 uv run renpy-maker
RENPY_MAKER_HOME=/chemin/vers/mes_donnees uv run renpy-maker
```

---

## 3. Les pages

**Le studio (`/studio`) est l'application à utiliser** : une seule fenêtre pour concevoir l'histoire, avec cinq
espaces autour de la carte de l'histoire (Carte, Scènes, Personnages, Lieux, Lecture) et l'export Ren'Py. L'IA
propose partout, l'auteur garde la main. Détails et correspondance avec les anciennes pages :
[docs/studio.md](docs/studio.md).

| Adresse | À quoi elle sert |
|---|---|
| `/projets` | **Mes histoires** : créer, ouvrir, renommer, supprimer (corbeille). « Continuer » ouvre le studio. |
| `/studio` | **Le studio** (recommandé) : carte et chemins, scènes (répliques et images, « Continuer avec l'IA »), personnages et garde-robe, lieux et points de vue, lecture avec les choix, export, réglages |

Les pages suivantes restent accessibles (⚙ › Outils avancés dans le studio) le temps que tout soit repris :

| Adresse | À quoi elle sert |
|---|---|
| `/atelier` | **Création pas à pas** : thème, personnages, lieu, réplique, image, réplique suivante ; graphe des références |
| `/recit` | **Récit** : jouer l'histoire comme un jeu de rôle guidé. Le conteur propose chaque moment (voix off, réplique, image), on le garde, on le modifie ou on dit (micro) ce qui doit changer ; choix et lignes de vie |
| `/facile` | **Parcours guidé** en étapes : Style, Idée, Carte, Personnages, Lieux, Tenues, Histoire, Plans, Jouer |
| `/jouer` | **Lecteur** : lit l'histoire comme le jeu final |
| `/histoire` | Mode expert : éditer l'histoire scène par scène |
| `/automatique` | Mode expert : génération automatique de l'histoire |
| `/` | Mode expert : page d'accueil de l'expert |

Toutes les pages travaillent sur l'histoire ouverte. Le réglage de l'histoire (modèles, moteur d'image, ComfyUI)
est accessible depuis la roue ⚙.

---

## 4. Mode enfants

L'application grand public (enfants et adolescents) se lance avec :

```bash
RENPY_MAKER_MODE=enfants uv run renpy-maker
```

Dans ce mode :
- les images passent **uniquement par Replicate** (pas de ComfyUI, pas de LoRA) ;
- le texte passe uniquement par Replicate ;
- le contenu explicite est **interdit**, et les filtres de sécurité des fournisseurs restent actifs.

L'application Android lance ce mode automatiquement (voir section 8).

---

## 5. Données et sauvegardes

Chaque histoire vit dans son dossier :

```
projects/<identifiant>/
  project.json        nom et date de création
  game_spec/          histoire (story.yaml), registre d'images (assets.yaml), réglages (app_settings.yaml)
  assets/             images générées (aucune n'est perdue : les anciennes versions restent)
  work/               sauvegardes et corbeille
  renpy/              jeu Ren'Py exporté (game/)
projects/dernier.json identifiant de la dernière histoire ouverte
```

- **Supprimer une histoire** la déplace dans `work/corbeille/` : rien n'est effacé.
- Les clés d'API saisies dans l'application sont dans `secrets.json` (à la racine des données). Elles ne sont
  jamais réaffichées.
- `game_spec/`, `projects/`, `assets/`, `work/` et `secrets.json` sont **ignorés par git**. Ne les commite pas :
  ce sont tes données.

---

## 6. Outils en ligne de commande

### Le registre d'images (`renpy_maker.assets`)

Agit sur les données du dossier `RENPY_MAKER_HOME`. Pour une histoire précise, pointe ce dossier vers elle :

```bash
RENPY_MAKER_HOME=projects/ecole uv run python -m renpy_maker.assets list
RENPY_MAKER_HOME=projects/ecole uv run python -m renpy_maker.assets check
RENPY_MAKER_HOME=projects/ecole uv run python -m renpy_maker.assets add char_lea personnage "Léa" "Jeune femme, cheveux châtains"
RENPY_MAKER_HOME=projects/ecole uv run python -m renpy_maker.assets generate char_lea --refs loc_salle --prompt "A young woman..." --aspect 3:4
RENPY_MAKER_HOME=projects/ecole uv run python -m renpy_maker.assets validate char_lea 2
RENPY_MAKER_HOME=projects/ecole uv run python -m renpy_maker.assets reject char_lea 1
```

- `list` : liste les éléments et leur image retenue.
- `check` : signale les éléments incohérents (image manquante, référence cassée).
- `generate <id>` : crée une nouvelle image candidate. `--refs` prend des identifiants séparés par des virgules.
- `validate <id> <n>` : retient la candidate n° n comme image de l'élément.
- `reject <id> <n>` : écarte une candidate.

### Workflows ComfyUI

```bash
# décrire un workflow et insérer des LoRA (sortie dans un fichier)
uv run python -m renpy_maker.comfy_graph comfy/workflows/FLUX1_API.json --lora mon_style.safetensors:0.8 --out /tmp/graphe.json
#   --with-clip : les LoRA modifient aussi le texte

# lancer un workflow sur le ComfyUI local
uv run python -m renpy_maker.comfy_client workflow.json --set 6.text="a red door" --out work/comfy_out --url http://127.0.0.1:8188
#   --set NOEUD.entrée=valeur (répétable) ; --url par défaut http://127.0.0.1:8188
```

---

## 7. Configuration (`config.yaml`)

Le fichier `config.yaml` (à la racine du dépôt) donne les valeurs par défaut de l'installation :

- `llm` : fournisseurs de texte et leurs modèles ;
- `llm_tasks` : modèle par tâche (histoire, dialogue, prompt, décision) ;
- `image_engines` : moteur par rôle d'image (`replicate` ou `comfyui`) et workflow ;
- `comfy` : adresse de ComfyUI, dossier des modèles, mémoire partagée avec Ollama ;
- `renpy.sdk_dir` : dossier du SDK Ren'Py (pour vérifier et lancer le jeu exporté) ;
- `project.game_dir` : ancien dossier d'export (les nouvelles histoires exportent dans leur propre `renpy/`).

Les chemins absolus de ce fichier correspondent à la machine d'origine : adapte-les à la tienne.

### Clés d'API

Dans l'ordre de recherche :
1. la variable d'environnement (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `REPLICATE_API_TOKEN`…) ;
2. `secrets.json` (saisi dans l'application, dans la roue ⚙) ;
3. le fichier `~/.config/slapsci/llm_api_keys.txt` (ancien emplacement).

### Prompts (`prompts.yaml`)

Tous les textes envoyés aux modèles sont dans `src/renpy_maker/prompts.yaml`. Ils sont rangés par usage :
- écriture : `chapter` (plan d'un chapitre), `dialogue` (répliques d'une scène) ;
- propositions : `atelier` (personnages, lieux, réplique, tenues, ce que l'on voit, points de vue), `recit` (le
  conteur, les choix, le metteur en scène) ;
- découpage d'une scène : `shots` (plans), `outfit_change` (changement de tenue) ;
- personnages : `identity` (description, genre et âge), `outfit_edit` (retouche d'une tenue) ;
- prompts d'image : `image` (personnage, tenue, lieu, objet), `scene_image` (image d'une scène, éléments visibles) ;
- `styles` : les styles d'image proposés, et le suffixe ajouté à chaque prompt d'image.

Dans un texte, `${nom}` est rempli par le programme (garder le nom), `${nom|texte}` donne `texte` quand la valeur
est vide, et `$$` écrit un `$`. Les clés JSON des réponses attendues sont lues par le programme : les garder.

Pour garder ses changements d'une mise à jour à l'autre, crée un fichier `prompts.yaml` **à côté de
`config.yaml`** et copies-y seulement les clés à changer, avec leur chemin complet. Par exemple :

```yaml
recit:
  safety: "Contenu tout public : ni nudité, ni violence, ni gros mots."
styles:
  aquarelle:
    label: Aquarelle
    desc: Couleurs douces
    suffix: soft watercolor illustration, light paper texture
```

Les fichiers sont relus dès qu'ils changent : pas besoin de relancer l'application. Un texte mal écrit (variable
inconnue, YAML invalide) donne un message qui nomme le fichier et la clé.

---

## 8. Application Android

Le dossier `android/` contient l'application (Chaquopy : le moteur Python tourne dans l'appareil).

```bash
cd android
./gradlew :app:assembleDebug    # génère app/build/outputs/apk/debug/app-debug.apk
```

- `android/local.properties` indique le SDK Android de ta machine (`sdk.dir=…`) : ce fichier n'est pas commité.
- La tâche Gradle `syncEngine` copie automatiquement le moteur (`src/renpy_maker`) et `config.yaml` dans
  l'application à chaque compilation : pas de copie à la main.
- L'application lance le serveur sur l'appareil avec `RENPY_MAKER_MODE=enfants`.

---

## 9. Export et vérification du jeu Ren'Py

Dans l'étape **Jouer** (`/facile`), « Fabriquer le jeu » écrit `story.rpy` et `options.rpy` dans
`projects/<id>/renpy/game/`, copie les images retenues, puis lance la vérification (`renpy lint`) avec le SDK
indiqué dans `config.yaml`. Le journal de la vérification s'affiche sous le bouton.

« Lancer dans Ren'Py » ouvre le jeu dans la fenêtre Ren'Py.

---

## 10. Consignes de travail

- **Ne commite jamais les données** (histoires, images, clés). Le `.gitignore` les exclut ; vérifie `git status`
  avant chaque commit.
- Les images envoyées aux modèles de dessin sont en **anglais** ; les textes de l'histoire sont en **français**.
- Ne jamais donner un prénom dans un prompt d'image : on décrit la personne par son genre et son âge.
- **Contenu explicite** : coché par histoire (« Contenu adulte »). Chaque personnage doit avoir un âge adulte
  précis dans sa description. Le corps nu n'est proposé qu'avec ComfyUI, pour une histoire explicite, hors mode
  enfants.
- Les filtres de sécurité des fournisseurs ne sont jamais désactivés par le code.
- Après une modification du code Python, **redémarre le serveur** : il ne recharge pas les modules tout seul.

---

## 11. Dépannage

| Problème | Solution |
|---|---|
| Le port est déjà utilisé | `RENPY_MAKER_PORT=8766 uv run renpy-maker` |
| Un bouton répond « introuvable » | le serveur tourne avec un ancien code : arrête-le (Ctrl+C) et relance-le |
| Une tâche ne s'arrête pas | le bouton **Arrêter** (bas de l'écran) annule le dessin ; une proposition de texte est simplement abandonnée |
| Un personnage ou un lieu n'a pas d'image | dessine-le d'abord : un moment ne se dessine qu'avec son lieu et ses personnages |
| L'export échoue | vérifie `renpy.sdk_dir` dans `config.yaml` et le journal affiché dans « Jouer » |

---

## Documents de conception

- `DESIGN.md`, `PLAN.md`, `PLAN_EDITEUR.md` : notes de conception de l'éditeur (historiques).
