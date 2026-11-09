"""Client LLM interchangeable : anthropic, openai, ollama. Sans dépendance (urllib).

Les clés sont lues dans l'environnement, ou à défaut dans ~/.config/slapsci/llm_api_keys.txt.
Les modèles et paramètres viennent de config.yaml (section llm.providers).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

import yaml

from renpy_maker import keys
from renpy_maker import paths

CONFIG = paths.CONFIG_FILE


class LLMError(RuntimeError):
    pass


def _key(name: str) -> str:
    value = keys.get(name)
    if not value:
        raise LLMError(f"Clé {name} absente : saisissez-la dans les réglages de l'application")
    return value




def provider_settings(name: str) -> dict:
    """Réglages d'un fournisseur : config.yaml, surchargés par les modèles choisis dans l'interface."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    try:
        base = dict(cfg["llm"]["providers"][name])
    except KeyError:
        raise LLMError(f"Fournisseur '{name}' absent de config.yaml") from None
    if paths.llm_models_file().exists():
        override = (yaml.safe_load(paths.llm_models_file().read_text(encoding="utf-8")) or {}).get(name, {})
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


RETRY_CODES = {429, 500, 502, 503, 504, 529}  # surcharge ou panne passagère du fournisseur
RETRY_WAITS = (5, 15, 45)                     # secondes entre deux tentatives


def _post(url: str, headers: dict, payload: dict, timeout: int = 600) -> dict:
    """Appel HTTP d'un fournisseur. Toute erreur devient une LLMError ; les surcharges et coupures
    passagères sont réessayées quelques fois, à délai croissant."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    for wait in (*RETRY_WAITS, None):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            if not isinstance(data, dict):
                raise LLMError("Réponse du fournisseur inattendue (objet JSON attendu)")
            return data
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            error = LLMError(f"HTTP {e.code} : {body[:500]}")
            if e.code not in RETRY_CODES:
                raise error from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            error = LLMError(f"Fournisseur injoignable : {getattr(e, 'reason', e)}")
        except ValueError:  # corps non JSON (page d'erreur d'un proxy…)
            error = LLMError("Réponse du fournisseur illisible (pas du JSON)")
        if wait is None:
            raise error from None
        print(f"{error} : nouvelle tentative dans {wait} s", flush=True)
        time.sleep(wait)
    raise AssertionError("inaccessible")


def complete(provider: str, system: str, user: str, model: str | None = None) -> str:
    """Renvoie le texte produit par le modèle. Lève LLMError en cas d'échec.
    model : modèle choisi pour cette tâche (sinon celui de config.yaml ou de la roue de réglages)."""
    p = provider_settings(provider)
    if model:
        p = {**p, "model": model}
    if provider == "ollama":
        from renpy_maker import appsettings
        if appsettings.free_comfy_before_ollama():
            from renpy_maker import comfy_image
            comfy_image.free_memory(comfy_image.base_url())  # la VRAM de ComfyUI laisse place à Ollama
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
        if data.get("stop_reason") == "max_tokens":
            raise LLMError("Réponse coupée (max_tokens atteint) : augmentez max_tokens dans config.yaml")
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if provider == "openai":
        data = _post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {_key(p['api_key_env'])}"},
            {"model": p["model"], "temperature": p["temperature"],
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        )
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        if not content:
            raise LLMError("Réponse vide du modèle (refus ou réponse coupée)")
        return content
    if provider == "ollama":
        data = _post(
            p["base_url"].rstrip("/") + "/api/chat", {},
            {"model": p["model"], "stream": False, "options": {"temperature": p["temperature"]},
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        )
        return data["message"]["content"]
    raise LLMError(f"Fournisseur inconnu : {provider}")


def unload_ollama_models(base_url: str | None = None) -> list[str]:
    """Décharge de la mémoire les modèles Ollama en cours (libère la VRAM pour ComfyUI).
    Sans effet si Ollama n'est pas lancé. Renvoie les modèles déchargés."""
    import json as _json
    base = (base_url or provider_settings("ollama").get("base_url", "http://localhost:11434")).rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/ps", timeout=5) as r:
            running = [m["name"] for m in _json.loads(r.read()).get("models", [])]
    except (OSError, ValueError, KeyError):
        return []
    for name in running:
        payload = _json.dumps({"model": name, "keep_alive": 0}).encode()
        req = urllib.request.Request(base + "/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60):
                pass
        except OSError:
            pass
    return running


def complete_task(task: str, system: str, user: str, story_provider: str | None = None) -> str:
    """Appel LLM pour une tâche (histoire, dialogue, prompt), avec le fournisseur et le modèle choisis."""
    from renpy_maker import appsettings
    provider, model = appsettings.llm_for(task, story_provider or "anthropic")
    return complete(provider, system, user, model or None)


def _replicate_text(p: dict, system: str, user: str) -> str:
    """Texte par un modèle de langage hébergé sur Replicate (même compte que les images)."""
    import time

    from renpy_maker import image_replicate as rep
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
    decoder = json.JSONDecoder()
    # Premier objet JSON complet, en ignorant le texte autour (blocs ```json, phrase après l'objet…).
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    raise LLMError("Réponse du modèle non exploitable (JSON invalide) :\n" + text[:800])
