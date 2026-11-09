"""Génération du plan, chapitre par chapitre (lot B).

Le LLM produit un chapitre au format JSON. On normalise la réponse, on attribue les
identifiants (ch1…, s1… uniques dans l'histoire), et on renvoie un chapitre prêt à être
ajouté au modèle d'histoire (story.py). Aucune scène n'est écrite en détail ici : ce sont
des résumés qui serviront ensuite à l'écriture des dialogues.
"""

from __future__ import annotations

from renpy_maker import appsettings
from renpy_maker import llm
from renpy_maker import paths
from renpy_maker import story as S
from renpy_maker.prompt_texts import t

def build_prompt(st: dict, chapter_index: int, scene_count: int, guidance: str) -> tuple[str, str]:
    explicit = bool(st["settings"].get("explicit_content")) and not paths.KIDS
    public = t("chapter.public_kids") + " " if paths.KIDS else ""
    system = t("chapter.system", public=public, explicit=t("common.explicit_yes" if explicit else "common.explicit_no"),
               schema=t("chapter.schema"))
    u = "chapter.user."
    lines = [t(u + "title", title=st.get("title")), t(u + "idea", idea=st.get("idea"))]
    if st.get("synopsis"):
        lines.append(t(u + "synopsis", synopsis=st["synopsis"]))
    if st["chapters"]:
        lines.append(t(u + "previous"))
        for ch in st["chapters"]:
            lines.append(t(u + "previous_chapter", title=ch["title"], summary=ch["summary"]))
            for sc in ch["scenes"][-2:]:
                lines.append(t(u + "previous_scene", title=sc["title"], summary=sc["summary"]))
    lines.append("\n" + t(u + "write", number=chapter_index, count=scene_count))
    if guidance:
        lines.append(t(u + "guidance", guidance=guidance))
    return system, "\n".join(lines)


def normalize(raw: dict, scene_count: int, first_scene_number: int) -> dict:
    """Vérifie la forme de la réponse et attribue les identifiants."""
    scenes = raw.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != scene_count:
        got = len(scenes) if isinstance(scenes, list) else "aucune"
        raise llm.LLMError(f"{scene_count} scène(s) demandée(s), {got} reçue(s)")
    out_scenes = []
    for k, sc in enumerate(scenes):
        out_scenes.append({
            "id": f"s{first_scene_number + k}",
            "title": str(sc.get("title", "")).strip(),
            "summary": str(sc.get("summary", "")).strip(),
            "characters": [str(c).strip() for c in sc.get("characters", []) if str(c).strip()],
            "location": str(sc.get("location") or "").strip() or None,
            "outfits": {str(k2): str(v) for k2, v in (sc.get("outfits") or {}).items()},
            "choices": [],
            "ending": False,
            "locked": False,
            "dialogue": [],
        })
    return {"title": str(raw.get("title", "")).strip(), "summary": str(raw.get("summary", "")).strip(),
            "scenes": out_scenes}


def generate_chapter(st: dict, scene_count: int, guidance: str = "", provider: str | None = None) -> dict:
    """Appelle le LLM et renvoie le chapitre normalisé (non encore ajouté à l'histoire)."""
    provider = provider or appsettings.provider("text")
    chapter_index = len(st["chapters"]) + 1
    first_scene = len(S.all_scenes(st)) + 1
    system, user = build_prompt(st, chapter_index, scene_count, guidance)
    text = llm.complete_task("histoire", system, user, provider)
    raw = llm.extract_json(text)
    ch = normalize(raw, scene_count, first_scene)
    ch["id"] = f"ch{chapter_index}"
    ch["provider"] = provider
    return ch


def _next_number(ids: set, prefix: str) -> int:
    """Premier numéro libre après le plus grand identifiant « <prefix><n> » existant."""
    nums = [int(i[len(prefix):]) for i in ids if str(i).startswith(prefix) and str(i)[len(prefix):].isdigit()]
    return max(nums, default=len(ids)) + 1


def add_generated(st: dict, ch: dict) -> dict:
    """Ajoute un chapitre généré à l'histoire et renvoie le chapitre inséré.

    Les identifiants ont été choisis sur un instantané pris avant l'appel au LLM : si une autre
    génération a ajouté un chapitre entre-temps, ils sont renumérotés pour rester uniques."""
    ch_ids = {c["id"] for c in st["chapters"]}
    sc_ids = {sc["id"] for sc in S.all_scenes(st)}
    if ch["id"] in ch_ids:
        ch["id"] = f"ch{_next_number(ch_ids, 'ch')}"
    if any(sc["id"] in sc_ids for sc in ch["scenes"]):
        first = _next_number(sc_ids, "s")
        for k, sc in enumerate(ch["scenes"]):
            sc["id"] = f"s{first + k}"
    chapter = S.add_chapter(st, ch["id"], ch["title"], ch["summary"], len(ch["scenes"]))
    for sc in ch["scenes"]:
        S.add_scene(chapter, sc["id"], sc["title"], sc["summary"], sc["characters"],
                    sc["location"], sc["outfits"])
    return chapter


def build_dialogue_prompt(st: dict, ch: dict, sc: dict, previous: list[dict]) -> tuple[str, str]:
    explicit = bool(st["settings"].get("explicit_content"))
    system = t("dialogue.system", explicit=t("common.explicit_yes" if explicit else "common.explicit_no"),
               narrator=S.NARRATOR, schema=t("dialogue.schema"))
    u = "dialogue.user."
    lines = [t(u + "story", title=st.get("title"), idea=st.get("idea"))]
    if st.get("synopsis"):
        lines.append(t(u + "synopsis", synopsis=st["synopsis"]))
    lines.append(t(u + "chapter", title=ch["title"], summary=ch["summary"]))
    lines.append(t(u + "scene", title=sc["title"], summary=sc["summary"]))
    lines.append(t(u + "location", location=sc.get("location")))
    lines.append(t(u + "characters", characters=", ".join(sc.get("characters", []))))
    if previous:
        lines.append(t(u + "previous"))
        lines += [t(u + "previous_line", speaker=l["speaker"], text=l["text"]) for l in previous]
    return system, "\n".join(lines)


def normalize_dialogue(raw: dict, characters: list[str]) -> list[dict]:
    lines = raw.get("lines")
    if not isinstance(lines, list) or not lines:
        raise llm.LLMError("Aucune réplique dans la réponse")
    allowed = set(characters) | {S.NARRATOR}
    out = []
    for i, line in enumerate(lines, 1):
        speaker = str(line.get("speaker", "")).strip()
        text = str(line.get("text", "")).strip()
        if speaker not in allowed:
            raise llm.LLMError(f"Réplique {i} : locuteur '{speaker}' absent de la scène")
        if not text:
            raise llm.LLMError(f"Réplique {i} vide")
        out.append({"speaker": speaker, "text": text,
                    "expression": str(line.get("expression") or "neutre").strip()})
    return out


DIALOGUE_ATTEMPTS = 3  # une réponse avec un mauvais locuteur est redemandée avec la correction


def generate_dialogue(st: dict, scene_id: str, provider: str | None = None) -> list[dict]:
    """Écrit les répliques d'une scène. Ne modifie pas l'histoire : renvoie la liste."""
    scenes = S.all_scenes(st)
    idx = next(i for i, sc in enumerate(scenes) if sc["id"] == scene_id)
    sc = scenes[idx]
    ch = next(c for c in st["chapters"] if any(x["id"] == scene_id for x in c["scenes"]))
    previous = scenes[idx - 1].get("dialogue", [])[-3:] if idx > 0 else []
    provider = provider or appsettings.provider("text")
    system, user = build_dialogue_prompt(st, ch, sc, previous)
    allowed = ", ".join(list(sc.get("characters", [])) + [S.NARRATOR])
    failure = ""
    for _ in range(DIALOGUE_ATTEMPTS):
        # Après un refus, le LLM reçoit l'erreur exacte et la liste des locuteurs autorisés.
        correction = (f"\n\nTentative précédente refusée : {failure}. Les seuls locuteurs autorisés sont : "
                      f"{allowed}. Réécris la réponse complète en respectant cette liste."
                      if failure else "")
        try:
            raw = llm.extract_json(llm.complete_task("dialogue", system, user + correction, provider))
            return normalize_dialogue(raw, sc.get("characters", []))
        except llm.LLMError as e:
            failure = str(e)
    raise llm.LLMError(f"{failure} (après {DIALOGUE_ATTEMPTS} tentatives)")
