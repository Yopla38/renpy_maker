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
import urllib.request
from pathlib import Path

API = "https://api.replicate.com/v1"
MODEL_BASE = "black-forest-labs/flux-dev"
MODEL_EDIT = "black-forest-labs/flux-2-klein-9b"


def _token() -> str:
    tok = os.environ.get("REPLICATE_API_TOKEN")
    if not tok:
        raise RuntimeError("REPLICATE_API_TOKEN absent de l'environnement")
    return tok


def _req(method: str, url: str, body: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "Prefer": "wait=60",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


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
    disable_safety_checker: bool = True
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
            "disable_safety_checker": disable_safety_checker
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

    pred = _req("POST", f"{API}/models/{model}/predictions", {"input": inp})
    t0 = time.time()
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if time.time() - t0 > timeout_s:
            raise TimeoutError(f"Prédiction {pred.get('id')} trop longue")
        time.sleep(2)
        pred = _req("GET", pred["urls"]["get"])
    if pred["status"] != "succeeded":
        raise RuntimeError(f"Échec Replicate ({model}) : {pred.get('error')}")

    url = pred["output"][0] if isinstance(pred["output"], list) else pred["output"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r:
        out_path.write_bytes(r.read())
    return model
