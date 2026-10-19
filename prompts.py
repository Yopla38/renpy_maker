"""Suggestion de prompt image (en anglais, forme Flux) par le LLM d'écriture.

Le prompt proposé est affiché dans le champ, l'auteur peut le modifier avant génération.
Rien n'est envoyé au modèle image sans l'accord de l'auteur.
"""

from __future__ import annotations

import llm
import story as S

SYSTEM = """You write prompts for FLUX image models.
Rules:
- Output ONLY the prompt: one paragraph, in English, 40 to 90 words.
- Natural descriptive sentences, not comma-separated tags.
- Be concrete: age, hair, eyes, build, clothing, pose, expression, setting, lighting, framing.
- No negative prompt, no quality tags, no text or captions, no French.
- Finish the prompt with this rendering style, word for word: {style}
{framing}"""

FRAMING = {
    "character": "- Show the character alone, in a clear portrait or three-quarter framing.",
    "outfit": "- Show the character wearing the outfit, full body, the clothing clearly visible.",
    "location": "- Describe the place only: a wide establishing shot with no people in it.",
}


def match_asset(assets: dict, el: dict, chars: dict) -> str | None:
    """Renvoie l'identifiant de l'actif du registre correspondant à un élément de l'histoire."""
    parent_id = chars.get(S.norm(el["parent_name"] or "")) if el["kind"] == "outfit" else None
    for aid, a in assets.items():
        if a["kind"] != el["kind"] or S.norm(a["name"]) != S.norm(el["name"]):
            continue
        if el["kind"] == "outfit" and a.get("parent") != parent_id:
            continue
        return aid
    return None


def story_context(st: dict, assets: dict, aid: str) -> list[str]:
    """Résumés des scènes où apparaît l'actif `aid` (en français, comme le texte de l'histoire)."""
    chars = {S.norm(a["name"]): k for k, a in assets.items() if a["kind"] == "character"}
    scenes_by_id = {sc["id"]: sc for sc in S.all_scenes(st)}
    lines: list[str] = []
    for el in S.story_elements(st):
        if match_asset(assets, el, chars) != aid:
            continue
        for sid in el["scenes"]:
            sc = scenes_by_id.get(sid)
            if sc and f"{sc['title']} : {sc['summary']}" not in lines:
                lines.append(f"{sc['title']} : {sc['summary']}")
    return lines


def build_request(st: dict, assets: dict, aid: str) -> tuple[str, str]:
    a = assets[aid]
    style = llm_style()
    framing = FRAMING.get(a["kind"], "")
    system = SYSTEM.format(style=style, framing=framing)
    lines = [
        f"Type : {a['kind']}",
        f"Name : {a['name']}",
    ]
    if a.get("description"):
        lines.append(f"Notes (French) : {a['description']}")
    if a.get("parent"):
        parent = assets.get(a["parent"])
        if parent:
            lines.append(f"Worn by : {parent['name']}")
            if parent.get("prompt"):
                lines.append(f"Character appearance (English, from the existing prompt) : {parent['prompt']}")
    ctx = story_context(st, assets, aid)
    if ctx:
        lines.append("Story context (French) :")
        lines += [f"- {c}" for c in ctx]
    return system, "\n".join(lines)


def llm_style() -> str:
    import assets as A
    return A.reference_style()["positive_suffix"]


def clean(text: str) -> str:
    """Garde le premier paragraphe, sans guillemets ni balises."""
    t = text.strip().strip("`").strip()
    t = t.split("\n\n")[0].strip()
    t = " ".join(t.split())
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    if not t:
        raise llm.LLMError("Le modèle n'a pas renvoyé de prompt")
    return t


def suggest(st: dict, assets_data: dict, aid: str, provider: str | None = None) -> str:
    system, user = build_request(st, assets_data["assets"], aid)
    provider = provider or st["settings"]["providers"]["text"]
    return clean(llm.complete(provider, system, user))
