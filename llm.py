"""Client LLM interchangeable : anthropic, openai, ollama. Sans dépendance (urllib).

Les clés sont lues dans l'environnement, ou à défaut dans ~/.config/slapsci/llm_api_keys.txt.
Les modèles et paramètres viennent de config.yaml (section llm.providers).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import yaml

import keys
import paths

CONFIG = paths.CODE / "config.yaml"


class LLMError(RuntimeError):
    pass


def _key(name: str) -> str:
    value = keys.get(name)
    if not value:
        raise LLMError(f"Clé {name} absente : saisissez-la dans les réglages de l'application")
    return value


MODELS_FILE = paths.GAME_SPEC / "llm_models.yaml"  # modèles choisis dans la page (roue de réglages)


def provider_settings(name: str) -> dict:
    """Réglages d'un fournisseur : config.yaml, surchargés par les modèles choisis dans l'interface."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    try:
        base = dict(cfg["llm"]["providers"][name])
    except KeyError:
        raise LLMError(f"Fournisseur '{name}' absent de config.yaml") from None
    if MODELS_FILE.exists():
        override = (yaml.safe_load(MODELS_FILE.read_text(encoding="utf-8")) or {}).get(name, {})
        base.update({k: v for k, v in override.items() if v})
    return base


def key_available(name: str) -> bool:
    """Vrai si la clé du fournisseur est trouvée (sans jamais l'afficher)."""
    if name == "replicate":
        return keys.present("REPLICATE_API_TOKEN")
    if "api_key_env" not in provider_settings(name):
        return True  # fournisseur local (Ollama) : pas de clé
    try:
        return bool(_key(provider_settings(name)["api_key_env"]))
    except LLMError:
        return False


def _post(url: str, headers: dict, payload: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise LLMError(f"HTTP {e.code} : {body[:500]}") from None


def complete(provider: str, system: str, user: str) -> str:
    """Renvoie le texte produit par le modèle. Lève LLMError en cas d'échec."""
    p = provider_settings(provider)
    if provider == "replicate":
        return _replicate_text(p, system, user)
    if provider == "anthropic":
        data = _post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": _key(p["api_key_env"]), "anthropic-version": "2023-06-01"},
            {"model": p["model"], "max_tokens": p["max_tokens"], "temperature": p["temperature"],
             "system": system, "messages": [{"role": "user", "content": user}]},
        )
        if data.get("stop_reason") == "refusal":
            raise LLMError("Le modèle a refusé la demande (refusal)")
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if provider == "openai":
        data = _post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {_key(p['api_key_env'])}"},
            {"model": p["model"], "temperature": p["temperature"],
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        )
        return data["choices"][0]["message"]["content"]
    if provider == "ollama":
        data = _post(
            p["base_url"].rstrip("/") + "/api/chat", {},
            {"model": p["model"], "stream": False, "options": {"temperature": p["temperature"]},
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        )
        return data["message"]["content"]
    raise LLMError(f"Fournisseur inconnu : {provider}")


def _replicate_text(p: dict, system: str, user: str) -> str:
    """Texte par un modèle de langage hébergé sur Replicate (même compte que les images)."""
    import time

    import image_replicate as rep
    body = {"input": {"prompt": user, "system_prompt": system, "max_tokens": p["max_tokens"],
                      "temperature": p["temperature"]}}
    data = rep._req("POST", f"https://api.replicate.com/v1/models/{p['model']}/predictions", body, timeout=600)
    for _ in range(300):  # environ dix minutes au pire
        if data.get("status") in ("succeeded", "failed", "canceled"):
            break
        time.sleep(2)
        data = rep._req("GET", data["urls"]["get"], timeout=60)
    if data.get("status") != "succeeded":
        raise LLMError(f"Replicate : {data.get('error') or data.get('status')}")
    out = data.get("output")
    return "".join(out) if isinstance(out, list) else str(out or "")


def extract_json(text: str) -> dict:
    """Extrait le premier objet JSON d'une réponse (tolère les blocs ```json)."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise LLMError("Réponse du modèle non exploitable (JSON invalide) :\n" + text[:800]) from None
