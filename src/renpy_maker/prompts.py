"""Suggestion de prompt image (en anglais, forme Flux) par le LLM d'écriture.

Le prompt proposé est affiché dans le champ, l'auteur peut le modifier avant génération.
Rien n'est envoyé au modèle image sans l'accord de l'auteur.
"""

from __future__ import annotations

from renpy_maker import appsettings, paths
import re

from renpy_maker import llm
from renpy_maker import story as S
from renpy_maker.prompt_texts import get as prompt_get, t

# Les textes des prompts sont dans prompts.yaml (section « image ») : voir prompt_texts.py.


# Mots qui signalent une personne dans un prompt d'objet ou de lieu.
PEOPLE_WORDS = re.compile(r"\b(man|woman|men|women|person|people|farmer|girl|boy|he|she|his|her|hands?|"
                          r"character|figure|someone|pierre|eve|marguerite)\b", re.I)


# Interdictions (« No people », « without hands ») : elles ne désignent pas une personne présente.
NEGATED = re.compile(r"\b(?:no|without|nobody|never any)\s+(?:\w+\s+)?(?:people|person|persons|hands?|body parts?|"
                     r"characters?|figures?|humans?|men|women|someone|anybody|anyone|faces?)\b", re.I)


def people_in_prompt(text: str, kind: str) -> bool:
    """Vrai si un prompt d'objet ou de lieu MENTIONNE une personne (les interdictions ne comptent pas)."""
    if kind not in ("object", "location"):
        return False
    return bool(PEOPLE_WORDS.search(NEGATED.sub(" ", text)))


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


def character_names(assets: dict) -> list[str]:
    return [a["name"] for a in assets.values() if a["kind"] == "character" and a.get("name")]


GENDER_WORDS = {"woman", "man", "girl", "boy", "female", "male", "lady", "gentleman", "teenager", "child"}


def valid_descriptor(text: str | None) -> bool:
    """Un descriptif vaut quelque chose s'il contient un mot de genre et tient en peu de mots."""
    if not text:
        return False
    words = [w.strip(".,;:!?").lower() for w in text.split()]
    return 1 <= len(words) <= 5 and any(w in GENDER_WORDS for w in words)


def person_word(assets: dict, name: str) -> str:
    """Comment désigner une personne dans un prompt : son genre et son âge, jamais son prénom."""
    chars = {S.norm(a["name"]): k for k, a in assets.items() if a["kind"] == "character"}
    aid = match_asset(assets, {"kind": "character", "name": name, "parent_name": None}, chars)
    descriptor = assets[aid].get("descriptor") if aid else None
    return descriptor if valid_descriptor(descriptor) else "person"


def anonymize(text: str, assets: dict, names: list[str] | None = None) -> str:
    """Remplace les prénoms des personnages par leur genre et âge dans un texte destiné au modèle image."""
    for name in sorted(names if names is not None else character_names(assets), key=len, reverse=True):
        text = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", person_word(assets, name), text)
    return text


def clean_descriptor(text: str) -> str:
    words = " ".join(text.strip().strip("`\"'.").split()).lower().split()
    return " ".join(words[:5]) or "person"


def describe_person(st: dict, name: str, description: str = "", provider: str | None = None) -> str | None:
    """Genre et âge d'un personnage, en quelques mots anglais. None si le LLM ne donne rien d'utilisable
    (on réessaie plus tard, au lieu d'enregistrer une phrase de refus comme descriptif)."""
    provider = provider or appsettings.provider("text")
    story = " ".join(x for x in (st.get("idea"), st.get("synopsis")) if x)
    lines = [t("image.describe_person.person", name=name)]
    if description:
        lines.append(t("image.describe_person.notes", description=description))
    if story:
        lines.append(t("image.describe_person.story", story=story))
    user = "\n".join(lines)
    system = t("image.describe_person.system")
    for extra in ("", "\n" + t("image.describe_person.retry")):
        raw = clean_descriptor(llm.complete_task("prompt", system, user + extra, provider))
        if valid_descriptor(raw):
            return raw
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


def person_noun(descriptor: str | None) -> str:
    """Le mot de genre du personnage (« man », « girl »…), tel qu'il figure dans son descriptif."""
    words = (descriptor or "").lower().split()
    return words[-1] if words and words[-1] in GENDER_WORDS else "person"


def _retained(assets: dict, rid: str) -> bool:
    return rid in assets and assets[rid].get("validated_candidate") is not None


def ref_order(assets: dict, aid: str) -> list[str]:
    """Images de référence d'un élément, dans l'ordre où le prompt les nomme (image 1, image 2…).
    Une tenue commence par la tenue de départ si elle en a une, puis par son personnage ; viennent ensuite
    les images choisies à la main. Seules les images retenues comptent."""
    a = assets[aid]
    order: list[str] = []
    if a["kind"] == "location" and a.get("parent"):  # point de vue : part de l'image de base de son lieu
        if _retained(assets, a["parent"]):
            order.append(a["parent"])
    if a["kind"] == "outfit":
        parent = a.get("parent") or ""
        # Tenue de départ choisie, sinon la tenue par défaut du personnage (si elle existe et est dessinée).
        base = a.get("based_on") or (assets.get(parent, {}).get("default_outfit") or "")
        if base and base != aid and _retained(assets, base):
            order.append(base)
        if parent and _retained(assets, parent) and parent not in order:
            order.append(parent)
    for rid in a.get("refs", []):
        if rid != aid and _retained(assets, rid) and rid not in order:
            order.append(rid)
    return order


def _ref_line(assets: dict, number: int, rid: str) -> str:
    r = assets[rid]
    if r["kind"] == "character":
        return t("image.reference.character", n=number, person=r.get("descriptor") or "person")
    if r["kind"] == "outfit":
        return t("image.reference.outfit", n=number, name=anonymize(r["name"], assets))
    return t("image.reference.other", n=number, name=anonymize(r["name"], assets))


def nude_base(st: dict) -> bool:
    """Corps de base nu : seulement avec ComfyUI pour le dessin de base, contenu explicite autorisé dans
    l'histoire, et jamais dans l'application enfants. Les tenues sont ensuite ajoutées par retouche (Klein)."""
    return (appsettings.image_for("base")["engine"] == "comfyui"
            and bool(st.get("settings", {}).get("explicit_content")) and not paths.KIDS)


def build_request(st: dict, assets: dict, aid: str) -> tuple[str, str]:
    a = assets[aid]
    if a["kind"] == "outfit" and a.get("parent") and assets.get(a["parent"]):
        # Tenue : la référence est le personnage, ou la tenue de départ si elle en a une.
        parent = assets[a["parent"]]
        system = t("image.outfit.system", style=llm_style(), noun=person_noun(parent.get("descriptor")))
        order = ref_order(assets, aid)
        base = a.get("based_on") if a.get("based_on") in order else None
        if base:
            first = t("image.outfit.first_based_on", noun=person_noun(parent.get("descriptor")),
                      base=anonymize(assets[base]["name"], assets))
        else:
            first = t("image.outfit.first", person=parent.get("descriptor") or "person")
        lines = [
            t("image.outfit.put_on", name=a["name"]),
            t("image.request.notes", notes=a.get("description", "")) if a.get("description") else "",
            first,
        ]
        # La première image est décrite plus haut ; les suivantes (personnage, images choisies) ici.
        lines += [_ref_line(assets, i + 2, rid) for i, rid in enumerate(order[1:])]
        # Pas de résumé de scène ici : il décrit souvent l'autre personnage (ici Léa, une femme) et le
        # modèle l'applique à la personne à habiller. La description de la tenue suffit.
        return system, "\n".join(l for l in lines if l)
    style = llm_style()
    framing = t(f"image.framing.{a['kind']}") if a["kind"] in (prompt_get("image.framing") or {}) else ""
    if a["kind"] in ("object", "location"):
        framing += " " + t("image.no_person")
    system = t("image.system", no_names=t("image.no_names"), style=style, framing=framing)
    lines = [
        t("image.request.type", kind=a["kind"]),
        t("image.request.name", name=anonymize(a["name"], assets)),
    ]
    # Un lieu se décrit par son nom seulement : ses notes reprennent le résumé des scènes, pleines de personnages.
    if a.get("description") and a["kind"] != "location":
        if a["kind"] == "character" and nude_base(st):
            # Corps nu : seuls les traits physiques comptent. Les vêtements des notes vont aux tenues.
            lines.append(t("image.request.nude_notes", notes=a["description"]))
        else:
            lines.append(t("image.request.notes", notes=a["description"]))
    if a["kind"] == "character":
        lines.append(t("image.request.full_body"))
    if a["kind"] == "character" and nude_base(st):
        lines.append(t("image.request.nude_word"))
        # Corps de base : la personne nue, sans vêtement ni accessoire. La tenue viendra par retouche.
        lines.append(t("image.request.nude_body"))
    if a["kind"] == "character":
        # Le genre et l'âge choisis sont la seule source : le contexte de l'histoire parle souvent d'un autre
        # personnage (une héroïne, pour un homme) et le modèle l'appliquerait à celui-ci.
        noun = person_noun(a.get("descriptor"))
        if noun == "person":
            lines.append(t("image.request.person_unknown"))
        else:
            lines.append(t("image.request.person_known", noun=noun, descriptor=a["descriptor"]))
    if a["kind"] == "character" and (st.get("synopsis") or st.get("idea")):
        # L'histoire décrit souvent l'apparence (couleur des yeux, cheveux) : elle doit être lue ici.
        story = st.get("synopsis") or st.get("idea")
        lines.append(t("image.request.story", story=anonymize(story, assets)))
    if a.get("parent"):
        parent = assets.get(a["parent"])
        if parent:
            lines.append(t("image.request.worn_by", person=parent.get("descriptor") or "person"))
            if parent.get("prompt"):
                lines.append(t("image.request.parent_prompt", prompt=anonymize(parent["prompt"], assets)))
    for i, rid in enumerate(ref_order(assets, aid), start=1):
        lines.append(_ref_line(assets, i, rid))
    ctx = story_context(st, assets, aid)
    if a["kind"] == "character":
        ctx = []  # un personnage se construit dans un milieu neutre : pas de décor ni de scène
    if a["kind"] == "location":
        ctx = []  # un lieu est vide : ni titres de scènes (« Un voisin encombrant »), ni personnages
    elif a["kind"] == "object":
        # Un objet : seulement le titre de la scène, pour ne pas y faire entrer les personnages.
        ctx = [c.split(" : ")[0] for c in ctx]
    if ctx:
        lines.append(t("image.request.context_titles") if a["kind"] in ("object", "location")
                     else t("image.request.context"))
        lines += [f"- {anonymize(c, assets)}" for c in ctx]
    return system, "\n".join(lines)


def llm_style() -> str:
    from renpy_maker import assets as A
    return A.reference_style()["positive_suffix"]


def clean(text: str) -> str:
    """Garde le premier paragraphe, sans guillemets ni balises."""
    out = text.strip().strip("`").strip()
    out = out.split("\n\n")[0].strip()
    out = " ".join(out.split())
    if len(out) >= 2 and out[0] == out[-1] and out[0] in "\"'":
        out = out[1:-1].strip()
    if not out:
        raise llm.LLMError("Le modèle n'a pas renvoyé de prompt")
    return out


def with_style(text: str, style: str) -> str:
    """Le style du projet doit terminer le prompt, une seule fois. Le LLM l'oublie ou le répète parfois."""
    text = text.replace(" .", ".").replace(" ,", ",").strip()
    if not style:
        return text
    if style in text:
        body = text.replace(style, "").rstrip(" .,")
    else:
        body = text.rstrip(" .,")
    return f"{body}. {style}" if body else style


PERSON_WORDS = re.compile(r"\b(man|men|woman|women|girl|girls|boy|boys|person|people|figure|figures|silhouette|"
                          r"someone|somebody|candidates?|he|she)\b", re.IGNORECASE)


def shows_person(text: str) -> bool:
    return bool(PERSON_WORDS.search(text))


CLOTHING = re.compile(r"\b(sweater|shirt|blouse|dress|skirt|miniskirt|jeans|trousers|pants|jacket|coat|suit|"
                      r"sweatshirt|underwear|lingerie|bra|panties|thong|stockings|shorts|clothes|clothing|garment|"
                      r"outfit|scarf|hat|shoes|boots|uniform|robe|costume|tie)\b", re.IGNORECASE)


def shows_clothing(text: str) -> bool:
    return bool(CLOTHING.search(text))


GENDER_NOUN = re.compile(r"\b(woman|man|girl|boy)\b", re.IGNORECASE)


def character_prompt_rules(text: str, nude: bool) -> str:
    """Règles de forme d'un prompt de personnage : il commence par « full body shot » ; en corps nu,
    « nude » est écrit juste avant le mot de genre (« a young nude woman »)."""
    text = text.strip()
    if not text.lower().startswith("full body shot"):
        text = "full body shot, " + text[:1].lower() + text[1:] if text else "full body shot"
    if nude and "nude" not in text.lower():
        text = GENDER_NOUN.sub(lambda m: "nude " + m.group(0), text, count=1)
    return text


def suggest(st: dict, assets_data: dict, aid: str, provider: str | None = None) -> str:
    system, user = build_request(st, assets_data["assets"], aid)
    provider = provider or appsettings.provider("text")
    text = clean(llm.complete_task("prompt", system, user, provider))
    if assets_data["assets"][aid]["kind"] == "character":
        text = character_prompt_rules(text, nude_base(st))
    if assets_data["assets"][aid]["kind"] == "character" and nude_base(st) and shows_clothing(text):
        # Corps nu : pas de vêtement dans le prompt. On redemande une fois, puis on refuse.
        strict = system + "\n" + t("image.retry_nude")
        text = clean(llm.complete_task("prompt", strict, user, provider))
        if shows_clothing(text):
            raise ValueError("Le prompt décrit encore des vêtements : les tenues se règlent dans la garde-robe.")
    if assets_data["assets"][aid]["kind"] == "location" and shows_person(text):
        # Un lieu doit rester vide : on redemande une fois, avec une consigne plus stricte.
        strict = system + "\n" + t("image.retry_empty_place")
        text = clean(llm.complete_task("prompt", strict, user, provider))
        if shows_person(text):
            raise ValueError("Le prompt du lieu montre encore des personnes : rédige-le à la main, ou réessaie.")
    return with_style(text, llm_style())
