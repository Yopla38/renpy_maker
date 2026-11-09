"""Pont entre l'application Android (Kotlin) et le moteur.

start(home) : démarre le serveur local (127.0.0.1) dans le dossier privé de l'appareil.
La page de l'application (WebView) charge ensuite http://127.0.0.1:<port>/facile.
"""

import os
import threading
from pathlib import Path

_server = None
_port = None


def start(home: str, port: int = 8765) -> int:
    global _server, _port
    if _server is not None:
        return _port
    os.environ["RENPY_MAKER_HOME"] = home
    os.environ["RENPY_MAKER_MODE"] = "enfants"
    # config.yaml est copié à côté de ce fichier au moment de la compilation
    os.environ["RENPY_MAKER_CONFIG_DIR"] = str(Path(__file__).resolve().parent)
    Path(home).mkdir(parents=True, exist_ok=True)
    from renpy_maker.webapp import server  # le paquet est copié à côté de ce fichier au moment de la compilation

    last_error = None
    for candidate in range(port, port + 20):
        try:
            _server = server.make_server(host="127.0.0.1", port=candidate)
            _port = candidate
            break
        except OSError as e:  # port déjà pris : on essaie le suivant
            last_error = e
    if _server is None:
        raise last_error
    threading.Thread(target=_server.serve_forever, daemon=True, name="histoire-http").start()
    return _port
