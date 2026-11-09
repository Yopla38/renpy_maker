"""Backend image Replicate (phase de test).

Le jeton est lu dans la variable d'environnement REPLICATE_API_TOKEN, jamais écrit dans le projet.
Deux modèles, un rôle chacun :
  - MODEL_BASE (flux-dev) : génération pure, sans référence. Sert aux ancres de base.
  - MODEL_EDIT (flux-2-klein-9b) : édition avec 1 à 5 images de référence. Jamais sans référence.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request

import paths
from pathlib import Path

API = "https://api.replicate.com/v1"
MODEL_BASE = "black-forest-labs/flux-dev"
MODEL_EDIT = "black-forest-labs/flux-2-klein-9b"


def ensure_token() -> None:
    """Rend le jeton disponible dans l'environnement (lu par _token)."""
    import keys
    value = keys.get("REPLICATE_API_TOKEN")
    if value:
        os.environ["REPLICATE_API_TOKEN"] = value


def _token() -> str:
    ensure_token()
    tok = os.environ.get("REPLICATE_API_TOKEN")
    if not tok:
        raise RuntimeError("Clé Replicate absente : saisissez-la dans les réglages de l'application")
    return tok


def _req(method: str, url: str, body: dict | None = None, timeout: int = 120, retries: int = 6) -> dict:
    """Appel Replicate, avec nouvelles tentatives à délai croissant :
    - 429 (trop de requêtes, souvent faute de crédit) et 5xx : toujours (Retry-After respecté) ;
    - coupure réseau : seulement pour une lecture (GET). Une création (POST) n'est pas renvoyée,
      pour ne pas lancer deux prédictions payantes."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {_token()}", "User-Agent": "histoire-ia/0.1",
               "Content-Type": "application/json"}
    if method == "POST" and url.endswith("/predictions"):
        headers["Prefer"] = "wait=60"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if not (e.code == 429 or e.code >= 500) or attempt == retries:
                raise
            wait = _retry_after(e) or 10 * (2 ** attempt)  # 10, 20, 40, 80… secondes
            print(f"Replicate {e.code} : nouvelle tentative dans {wait} s", flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if method != "GET" or attempt == retries:
                raise
            wait = min(5 * (2 ** attempt), 60)
            print(f"Replicate injoignable ({e}) : nouvelle tentative dans {wait} s", flush=True)
        time.sleep(wait)
    raise AssertionError("inaccessible")


def _retry_after(e: urllib.error.HTTPError) -> int | None:
    try:
        return max(1, min(int(e.headers.get("Retry-After", "")), 300))
    except (TypeError, ValueError, AttributeError):
        return None


def _cancel(pred: dict) -> None:
    """Annule une prédiction en cours chez Replicate (elle ne coûte plus rien)."""
    url = (pred.get("urls") or {}).get("cancel")
    if not url:
        return
    try:
        _req("POST", url, retries=1)
    except Exception as e:  # noqa: BLE001 — l'annulation est un effort, l'erreur d'origine prime
        print(f"Annulation Replicate impossible : {e}", flush=True)


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def generate(
    prompt: str,
    out_path: Path,
    *,
    images: list[Path] | None = None,
    seed: int | None = None,
    aspect_ratio: str = "2:3",
    megapixels: str = "1",
    output_format: str = "png",
    timeout_s: int = 600,
    disable_safety_checker: bool = False  # filtre de sécurité actif par défaut
) -> str:
    """Génère (sans images) avec MODEL_BASE, ou édite (avec images) avec MODEL_EDIT.

    Renvoie le nom du modèle utilisé, pour le manifeste.
    """
    if images:
        if len(images) > 5:
            raise ValueError("Klein accepte au plus 5 images de référence")
        model = MODEL_EDIT
        inp: dict = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "megapixels": megapixels,
            "output_format": output_format,
            "images": [_data_uri(p) for p in images],
            "disable_safety_checker": disable_safety_checker and not paths.KIDS
        }
    else:
        model = MODEL_BASE
        inp = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": output_format,
            "num_outputs": 1,
        }
    if seed is not None:
        inp["seed"] = seed

    import background
    pred = _req("POST", f"{API}/models/{model}/predictions", {"input": inp})
    t0 = time.time()
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if background.should_stop():
            _cancel(pred)
            raise RuntimeError("Génération arrêtée")
        if time.time() - t0 > timeout_s:
            _cancel(pred)
            raise TimeoutError(f"Prédiction {pred.get('id')} trop longue")
        time.sleep(2)
        pred = _req("GET", pred["urls"]["get"])
    if pred["status"] != "succeeded":
        raise RuntimeError(f"Échec Replicate ({model}) : {pred.get('error')}")

    output = pred.get("output")
    url = (output[0] if output else None) if isinstance(output, list) else output
    if not isinstance(url, str) or not url.startswith("https://"):
        raise RuntimeError(f"Réponse Replicate sans image ({model}) : {output!r}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r:
        out_path.write_bytes(r.read())
    return model
