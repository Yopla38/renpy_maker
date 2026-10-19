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

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.yaml"
KEYFILE = Path.home() / ".config/slapsci/llm_api_keys.txt"


class LLMError(RuntimeError):
    pass


def _key(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    if KEYFILE.exists():
        for line in KEYFILE.read_text(encoding="utf-8").splitlines():
            m = re.match(rf"^\s*(?:export\s+)?{name}\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip("'\"")
    raise LLMError(f"Clé {name} introuvable (environnement ou {KEYFILE})")


def provider_settings(name: str) -> dict:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    try:
        return cfg["llm"]["providers"][name]
    except KeyError:
        raise LLMError(f"Fournisseur '{name}' absent de config.yaml") from None


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


def extract_json(text: str) -> dict:
    """Extrait le premier objet JSON d'une réponse (tolère les blocs ```json)."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise LLMError("Réponse du modèle non exploitable (JSON invalide) :\n" + text[:800]) from None
