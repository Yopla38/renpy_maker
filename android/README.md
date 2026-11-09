# Mon histoire (Android)

Application Android pour créer et lire une histoire illustrée, pensée pour les enfants et les adolescents.
Le texte et les images sont générés avec **Replicate**, avec la clé de la personne qui utilise l'application.

## Comment ça marche

- Le **moteur** est à la racine du dépôt `renpy_maker` (dossier parent de `android/`). Il n'est pas recopié à la main : la tâche Gradle `syncEngine`
  le copie dans `app/src/main/python` à chaque compilation (et `bridge/launcher.py` avec lui).
- Au lancement, l'application démarre le moteur **dans l'appareil** (Chaquopy : Python embarqué), sur
  `127.0.0.1`. Une `WebView` affiche la page de création (`/facile`) ; la lecture est sur `/jouer`.
- Les données (histoire, images, clé) sont dans le **dossier privé** de l'application. Rien n'est envoyé à un
  serveur à nous. Les seuls envois sont vers Replicate (texte et images).
- Un service de premier plan garde le moteur actif quand l'application passe en arrière-plan.

## Mode enfants

L'application est lancée avec `RENPY_MAKER_MODE=enfants` (défini dans `bridge/launcher.py`) :

- pas de contenu explicite (la case n'apparaît pas, et le prompt d'écriture l'interdit) ;
- le filtre de sécurité des images reste **activé**, même si le réglage du moteur le demandait ;
- le texte passe par Replicate (modèle `meta/meta-llama-3-70b-instruct`, réglable dans `../config.yaml`).

## Prérequis

- Android Studio, ou le SDK Android (plateforme 35) et Java 17.
- Un Python 3 sur la machine de compilation (Chaquopy l'utilise pour installer PyYAML).
- Une clé API Replicate, saisie dans l'application (roue de réglages).

## Compiler et installer

```bash
cd histoire_android
./gradlew assembleDebug                       # l'APK : app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

`local.properties` doit indiquer le SDK : `sdk.dir=/chemin/vers/Android/Sdk`.

## Ce qui n'est pas encore fait

- **Ren'Py** : la lecture est une page qui imite Ren'Py (image plein écran, boîte de dialogue, fondus).
  La fabrication d'un jeu Ren'Py se fait sur un PC, pas ici.
- **iPhone** : Chaquopy ne fonctionne que sous Android.
- **Publication** : l'APK se distribue directement. Google Play encadre les applications d'IA générative.
- **Icône** : l'icône système par défaut est utilisée.
- **Hors connexion** : la création a besoin d'Internet (Replicate). La lecture d'une histoire déjà faite fonctionne sans.

## Tests

Les tests du moteur s'exécutent depuis la racine du dépôt (`..`) : `python3 -m pytest` (aucun appel réseau).
