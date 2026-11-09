"""Tâches de fond hors du parcours simple (page experte, pipeline) : comptées, pour qu'on ne change
pas d'histoire pendant qu'une d'elles écrit encore dans l'histoire ouverte."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_local = threading.local()
_running = 0


def start(target, *args) -> None:
    """Lance target(*args) dans un thread, compté tant qu'il tourne."""
    global _running
    with _lock:
        _running += 1

    def run():
        global _running
        try:
            target(*args)
        finally:
            with _lock:
                _running -= 1

    threading.Thread(target=run, daemon=True).start()


def running() -> int:
    with _lock:
        return _running


def set_stop_check(check) -> None:
    """Fonction qui dit si l'auteur a demandé l'arrêt de la tâche du thread courant (None : aucune)."""
    _local.check = check


def should_stop() -> bool:
    """Vrai si l'arrêt de la tâche courante est demandé. Lu par les boucles d'attente des moteurs
    (ComfyUI, Replicate) pour ne pas attendre une image dont on ne veut plus."""
    check = getattr(_local, "check", None)
    return bool(check and check())
