"""Tâches de fond hors du parcours simple (page experte, pipeline) : comptées, pour qu'on ne change
pas d'histoire pendant qu'une d'elles écrit encore dans l'histoire ouverte."""

from __future__ import annotations

import threading

_lock = threading.Lock()
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
