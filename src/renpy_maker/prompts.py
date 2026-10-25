"""Suggestion de prompt image (en anglais, forme Flux) par le LLM d'écriture.

Le prompt proposé est affiché dans le champ, l'auteur peut le modifier avant génération.
Rien n'est envoyé au modèle image sans l'accord de l'auteur.
"""

from __future__ import annotations

from renpy_maker import appsettings
import re

from renpy_maker import llm
from renpy_maker import story as S

# Les modèles d'image ne connaissent pas les prénoms : une personne se décrit par son genre et son âge.
NO_NAMES = ("Never write a first name or any proper name of a person in the prompt: describe each person by gender "
            "and age instead ('a young woman', 'a teenage boy', 'an old man').")
DESCRIBE_SYSTEM = ("Give the gender and age group of the person described, as a 2 to 4 word English noun phrase, "
                   "for example 'young woman', 'teenage boy', 'old man'. Output only that phrase, never a name.")

SYSTEM = """You write prompts for FLUX image models.
Rules:
- Output ONLY the prompt: one paragraph, in English, 40 to 90 words.
- """ + NO_NAMES + """
- Natural descriptive sentences, not comma-separated tags.
- Be concrete: age, hair, eyes, build, clothing, pose, expression, setting, lighting, framing.
- No negative prompt, no quality tags, no text or captions, no French.
- Finish the prompt with this rendering style, word for word: {style}
{framing}"""

FRAMING = {
    "character": ("- Show the character alone against a plain neutral studio backdrop, in a clear portrait or "
                  "three-quarter framing. No location, no props, no other people. The story's mood may shape the "
                  "lighting and the expression only."),
    "outfit": "- Show the character wearing the outfit, full body, the clothing clearly visible.",
    "location": "- Describe the place only: a wide establishing shot with no people in it.",
    "object": "- Show the object alone, centred, clearly lit. No people, no hands, no body parts, no characters at all.",
}

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
    user = f"Person : {name}\nNotes (French) : {description}" if description else f"Person : {name}"
    if story:
        user += f"\nStory (French, the person's looks may be described here) : {story}"
    for extra in ("", "\nAnswer with exactly two words: gender then age group, for example 'young woman'."):
        raw = clean_descriptor(llm.complete_task("prompt", DESCRIBE_SYSTEM, user + extra, provider))
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


EDIT_SYSTEM = """You write prompts for FLUX.2 Klein, an image EDITING model. The reference image 1 is the character
as they already look. Your prompt is an instruction to edit that image, not a description of a new person.
Output ONLY the prompt, in English, one paragraph of 30 to 80 words, never more than 100.
- Start with what must stay identical: 'Keep the {noun} from image 1 exactly as they are: their face, hair, body, pose and framing.'
- Then state the change: the clothing to put on, and what to remove (any garment or accessory not in the outfit).
- Do not re-describe her face, hair or body: the reference already shows them.
- Describe the clothes concretely (garments, colours, fit, footwear, accessories). No negative terms, no quality words.
- Never write a first name. Refer to the person only as 'the {noun} from image 1'.
- Finish with this rendering style, word for word: {style}"""


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
    if a["kind"] == "outfit":
        base = a.get("based_on") or ""
        if base and base != aid and _retained(assets, base):
            order.append(base)
        parent = a.get("parent") or ""
        if parent and _retained(assets, parent) and parent not in order:
            order.append(parent)
    for rid in a.get("refs", []):
        if rid != aid and _retained(assets, rid) and rid not in order:
            order.append(rid)
    return order


def _ref_line(assets: dict, number: int, rid: str) -> str:
    r = assets[rid]
    if r["kind"] == "character":
        return f"Reference image {number} : the {r.get('descriptor') or 'person'}, as they look now."
    if r["kind"] == "outfit":
        return f"Reference image {number} : clothes worn by the person ({anonymize(r['name'], assets)})."
    return f"Reference image {number} : {anonymize(r['name'], assets)}, use it as a visual reference."


def build_request(st: dict, assets: dict, aid: str) -> tuple[str, str]:
    a = assets[aid]
    if a["kind"] == "outfit" and a.get("parent") and assets.get(a["parent"]):
        # Tenue : la référence est le personnage, ou la tenue de départ si elle en a une.
        parent = assets[a["parent"]]
        system = EDIT_SYSTEM.format(style=llm_style(), noun=person_noun(parent.get("descriptor")))
        order = ref_order(assets, aid)
        base = a.get("based_on") if a.get("based_on") in order else None
        if base:
            first = (f"Reference image 1 : the {person_noun(parent.get('descriptor'))} wearing "
                     f"{anonymize(assets[base]['name'], assets)}, as they look now. Keep those garments "
                     f"unless the outfit below replaces them.")
        else:
            first = f"Reference image 1 : the {parent.get('descriptor') or 'person'}, as they look now."
        lines = [
            f"Outfit to put on the character : {a['name']}",
            f"Notes (French) : {a.get('description', '')}" if a.get("description") else "",
            first,
        ]
        # La première image est décrite plus haut ; les suivantes (personnage, images choisies) ici.
        lines += [_ref_line(assets, i + 2, rid) for i, rid in enumerate(order[1:])]
        # Pas de résumé de scène ici : il décrit souvent l'autre personnage (ici Léa, une femme) et le
        # modèle l'applique à la personne à habiller. La description de la tenue suffit.
        return system, "\n".join(l for l in lines if l)
    style = llm_style()
    framing = FRAMING.get(a["kind"], "")
    if a["kind"] in ("object", "location"):
        framing += " Never mention a person, even if the story context does."
    system = SYSTEM.format(style=style, framing=framing)
    lines = [
        f"Type : {a['kind']}",
        f"Name (never write it in the prompt) : {anonymize(a['name'], assets)}",
    ]
    # Un lieu se décrit par son nom seulement : ses notes reprennent le résumé des scènes, pleines de personnages.
    if a.get("description") and a["kind"] != "location":
        lines.append(f"Notes (French) : {a['description']}")
    if a["kind"] == "character":
        # Le genre et l'âge choisis sont la seule source : le contexte de l'histoire parle souvent d'un autre
        # personnage (une héroïne, pour un homme) et le modèle l'appliquerait à celui-ci.
        noun = person_noun(a.get("descriptor"))
        if noun == "person":
            lines.append("Person to depict : gender and age not chosen yet. Do not guess them from the other "
                         "characters of the story.")
        else:
            lines.append(f"Person to depict : the {noun} described by the descriptor '{a['descriptor']}'. "
                         f"Describe only this {noun}, with this gender and age, even if the story context "
                         f"describes other people.")
    if a["kind"] == "character" and (st.get("synopsis") or st.get("idea")):
        # L'histoire décrit souvent l'apparence (couleur des yeux, cheveux) : elle doit être lue ici.
        story = st.get("synopsis") or st.get("idea")
        lines.append(f"Story (French, describes the people's looks): {anonymize(story, assets)}")
    if a.get("parent"):
        parent = assets.get(a["parent"])
        if parent:
            lines.append(f"Worn by : the {parent.get('descriptor') or 'person'}")
            if parent.get("prompt"):
                lines.append(f"Character appearance (English, from the existing prompt) : "
                             f"{anonymize(parent['prompt'], assets)}")
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
        lines.append("Scene where it appears (titles only) :" if a["kind"] in ("object", "location")
                     else "Story context (French) :")
        lines += [f"- {anonymize(c, assets)}" for c in ctx]
    return system, "\n".join(lines)


def llm_style() -> str:
    from renpy_maker import assets as A
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


def suggest(st: dict, assets_data: dict, aid: str, provider: str | None = None) -> str:
    system, user = build_request(st, assets_data["assets"], aid)
    provider = provider or appsettings.provider("text")
    text = clean(llm.complete_task("prompt", system, user, provider))
    if assets_data["assets"][aid]["kind"] == "location" and shows_person(text):
        # Un lieu doit rester vide : on redemande une fois, avec une consigne plus stricte.
        strict = system + "\nThe previous attempt showed people. The place must be EMPTY: no person, no figure, no silhouette."
        text = clean(llm.complete_task("prompt", strict, user, provider))
        if shows_person(text):
            raise ValueError("Le prompt du lieu montre encore des personnes : rédige-le à la main, ou réessaie.")
    return with_style(text, llm_style())
