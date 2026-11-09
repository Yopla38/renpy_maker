# Studio : une seule application pour concevoir l'histoire

Adresse : `/studio`. Elle remplace, à terme, les huit pages d'aujourd'hui (`/facile`, `/atelier`, `/recit`,
`/histoire`, `/`, `/automatique`, `/jouer`, et l'essentiel de `/projets`).

## Pourquoi

Chaque mode avait sa façon de faire la même chose : trois cartes de l'histoire, cinq façons de dessiner une
image, trois éditeurs de références, quatre styles visuels et deux systèmes de tâches. On passait d'un mode à
l'autre pour trouver une fonction. Le studio garde **toutes** les possibilités, mais chacune n'a plus qu'une
place.

## Le principe : une histoire, cinq espaces, l'IA partout

```
┌ Le phare ─────────────────────────────── ● Dessin de Mara 40 % [Arrêter]   ▶ Lire   ⚙ ┐
│ ◇ Carte    │                                                                          │
│ ▤ Scènes   │      (l'espace choisi)                         │ (panneau de l'élément    │
│ ☺ Personn. │                                                │  sélectionné)            │
│ ⌂ Lieux    │                                                │                          │
│ ▶ Lecture  │                                                │                          │
│ ⇪ Export   │                                                │                          │
└────────────┴──────────────────────────────────────────────────────────────────────────┘
```

- **Carte** (le centre) : les scènes et les chemins qui les relient (la carte des lignes de vie). On y voit
  la forme de l'histoire, ce qui reste à faire, les impasses. On y crée les choix, on rattache, on termine ou
  on rouvre une ligne, on range une route dans la réserve. Un clic sur une scène l'ouvre.
- **Scènes** : le scénario et le storyboard d'une scène, côte à côte : chaque réplique avec l'image qui
  l'accompagne. On corrige le texte sur place, on dessine, on règle une image dans son panneau (ce que l'on
  voit, cadrage, point de vue, personnages visibles, références, continuité, prompt, LoRA, reprendre une
  image existante). En bas : la **suite** de la scène (choix, fin, ligne ouverte) et **Continuer avec l'IA**,
  la boucle du mode récit : l'IA propose le moment suivant (voix off, réplique, image, choix), on le garde, on
  le modifie, ou on lui dit ce qui doit changer.
- **Personnages** : la distribution. Portrait, identité (genre et âge), description, prompt, références,
  LoRA, et la **garde-robe** (tenues proposées par l'IA ou écrites à la main, tenue par défaut, retouches).
- **Lieux** : les décors et leurs **points de vue**.
- **Lecture** : l'histoire comme le jeu final, **avec les choix**.
- **Export** : le projet Ren'Py (titre, résolution, points bloquants, export, vérification, lancement).

La barre du haut montre la tâche en cours (avec sa progression et « Arrêter »), « Lire », et la roue ⚙ des
réglages (modèles, moteurs d'image, clés, options de l'histoire).

Une histoire vide s'ouvre sur **Commencer** : le cadre (titre, idée, ambiance, style), puis deux départs :
« L'IA écrit le plan » (chapitre complet) ou « Écrire en jouant » (premier moment, à la manière du récit).

## Où est passée chaque fonction

| Avant | Dans le studio |
|---|---|
| `/projets` : choisir, créer, renommer, supprimer | `/projets` (inchangé), « Continuer » ouvre le studio |
| `/facile` Style, Idée | Commencer (histoire vide) ; style et options dans ⚙ |
| `/facile` Carte, `/recit` Lignes de vie | Carte |
| `/facile` Personnages, Tenues ; `/atelier` personnages, garde-robe | Personnages |
| `/facile` Lieux ; `/atelier` points de vue | Lieux |
| `/facile` Histoire (répliques, réécriture) ; `/histoire` répliques | Scènes |
| `/facile` Plans (découpage, images, références, continuité, copie) | Scènes, panneau de l'image |
| `/facile` routes en lignes (bifurcation, réserve, rattacher) | Carte (rattacher, réserve) ; Scènes (bifurquer après une réplique) |
| `/atelier` réplique par réplique, image du moment | Scènes : Continuer avec l'IA |
| `/recit` boucle de récit, consignes, choix | Scènes : Continuer avec l'IA |
| `/recit` Rejouer, `/jouer` | Lecture (avec les choix) |
| `/facile` Jouer, `/histoire` Ren'Py | Export |
| Roues ⚙ de `/facile`, `/atelier`, `/recit` | ⚙ (une seule) |
| Ajouter un chapitre, compléter l'histoire | Carte, menu « Écrire avec l'IA » |

Pas encore repris (accessibles depuis ⚙ › Outils avancés tant qu'ils ne sont pas portés) :
la scène de théâtre plein écran et le micro du récit, le graphe de références de l'atelier (glisser-déposer
depuis la bobine), le registre brut (`/` : objets, rejet d'un candidat, graine, format), le pipeline
automatique, le verrouillage des chapitres et l'expression par réplique de `/histoire`.

## Technique

- Une page (`webapp/studio/index.html`) et des modules JavaScript sans compilation (`app.js`, `api.js`,
  `ui.js`, `views/*.js`) : rien à installer, fonctionne dans la WebView Android.
- Une seule source de données : `GET /api/recit` (la vue complète de l'histoire, plus les lignes de vie et la
  carte). Les actions passent par les routes existantes `/api/facile`, `/api/atelier` et `/api/recit`.
- Une seule file de tâches : `/api/facile/jobs/<id>` (progression, arrêt).
- Pas de `window.confirm` ni `window.prompt` (absents de la WebView Android) : le studio a ses propres
  fenêtres de confirmation.
- Mode enfants : pas de LoRA, pas de ComfyUI, pas de contenu explicite, pas d'export Ren'Py (lecture seule).
