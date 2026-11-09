"""Emplacements du moteur.

CODE : les fichiers du programme (lecture seule sur Android).
HOME : les données de l'application (écriture). Par défaut, le dossier du projet ; sur Android,
       le dossier privé de l'application, passé par RENPY_MAKER_HOME.
       HOME/game_spec, HOME/assets et HOME/work sont l'histoire « d'origine ». Chaque autre histoire
       vit dans HOME/projects/<id>/ avec les mêmes sous-dossiers (voir projects.py).

L'histoire ouverte change à l'exécution (choix sur la page des histoires) : les chemins se lisent
donc toujours au moment de l'usage, jamais à l'import.

RENPY_MAKER_MODE=enfants : application grand public (enfants et adolescents). Le contenu explicite
est alors interdit, et les filtres de sécurité des images restent activés.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

CODE = Path(__file__).resolve().parent                     # le paquet (code, pages web, workflows)
# Dossier qui contient config.yaml : la racine du dépôt sur ordinateur ; sur Android, le dossier de l'application.
REPO = Path(os.environ.get("RENPY_MAKER_CONFIG_DIR") or CODE.parents[1])
CONFIG_FILE = REPO / "config.yaml"
HOME = Path(os.environ.get("RENPY_MAKER_HOME") or REPO)
PROJECTS = HOME / "projects"
SECRETS = HOME / "secrets.json"          # clés saisies dans l'application (jamais dans le code)
KIDS = os.environ.get("RENPY_MAKER_MODE", "expert") == "enfants"

def atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    """Écrit un fichier texte d'un seul coup : jamais de fichier vide ou tronqué, même en cas d'arrêt.

    Le contenu va dans un fichier temporaire du même dossier, puis remplace l'ancien (os.replace).
    mode : droits du fichier (ex. 0o600 pour les secrets)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if mode is None else mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is None and path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        elif mode is None:
            os.chmod(tmp, 0o666 & ~_umask())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _umask() -> int:
    m = os.umask(0)
    os.umask(m)
    return m


_active: Path | None = None   # dossier de l'histoire ouverte ; None = histoire d'origine (racine)
_chosen = False                # faux tant que l'utilisateur n'a rien ouvert depuis le démarrage


def activate(folder: Path | None) -> None:
    """Ouvre une histoire (dossier dans PROJECTS) ou l'histoire d'origine (None)."""
    global _active, _chosen
    _active = folder
    _chosen = True


def chosen() -> bool:
    return _chosen


def active_folder() -> Path | None:
    return _active


def data_root() -> Path:
    return _active or HOME


def game_spec() -> Path:
    return data_root() / "game_spec"


def story_file() -> Path:
    return game_spec() / "story.yaml"


def assets_file() -> Path:
    return game_spec() / "assets.yaml"


def app_settings_file() -> Path:
    return game_spec() / "app_settings.yaml"


def llm_models_file() -> Path:
    return game_spec() / "llm_models.yaml"  # modèles choisis dans la page (roue de réglages)


def assets_dir() -> Path:
    return data_root() / "assets"


def work_dir() -> Path:
    return data_root() / "work"


def url_prefix(folder: Path | None) -> str:
    """Préfixe des adresses /files/ : l'histoire d'origine n'en a pas, chaque autre histoire a le sien
    (deux histoires peuvent avoir des images au même nom, le navigateur ne doit pas les confondre)."""
    if folder is None or folder.parent != PROJECTS:
        return ""
    return f"p/{folder.name}/"


def file_url(rel: str) -> str:
    """Adresse d'un fichier de l'histoire ouverte, relatif à son dossier (« assets/… »)."""
    return "/files/" + url_prefix(_active) + rel
