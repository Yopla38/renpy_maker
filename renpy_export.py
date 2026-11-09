"""Export de l'histoire vers un projet Ren'Py (game_project/).

Produit :
  game/story.rpy     : une étiquette par scène, répliques, images (généré, ne pas éditer)
  game/options.rpy   : titre et résolution
  game/images/       : une image par plan, copiée depuis le registre (image retenue)

Le lint (renpy.sh <projet> lint) vérifie le résultat. L'export refuse si l'histoire a des points
bloquants : mieux vaut un message clair que un script cassé.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

import yaml

import story as S

import paths

CONFIG = paths.CODE / "config.yaml"
DEFAULTS = {"title": "Mon histoire", "width": 1920, "height": 1080}


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def project_dir() -> Path:
    """Projet Ren'Py : celui de la configuration pour l'histoire d'origine, un dossier propre à chaque
    autre histoire (renpy/, à côté de ses données)."""
    if paths.active_folder() is None:
        return Path(_config()["project"]["game_dir"])
    return paths.data_root() / "renpy"


def renpy_sh() -> Path:
    return Path(_config()["renpy"]["sdk_dir"]) / "renpy.sh"


def settings(st: dict) -> dict:
    return {**DEFAULTS, **st.get("settings", {}).get("renpy", {})}


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_") or "x"


def char_var(name: str) -> str:
    return "c_" + slug(name)


def char_vars(names: list[str]) -> dict[str, str]:
    """Variable Ren'Py unique par personnage : Léa et Lea, ou 李 et 王, ne se confondent pas."""
    out: dict[str, str] = {}
    for name in names:
        base = var = char_var(name)
        n = 2
        while var in out.values():
            var, n = f"{base}_{n}", n + 1
        out[name] = var
    return out


IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def scene_labels(scenes: list[dict]) -> dict[str, str]:
    """Label Ren'Py de chaque scène : l'identifiant s'il est valide (s1, s2…), sinon une version
    slugifiée préfixée. Deux scènes ne partagent jamais un label."""
    out: dict[str, str] = {}
    used = {"start"}
    for sc in scenes:
        sid = str(sc["id"])
        if sid in out:
            continue
        base = sid if IDENT_RE.fullmatch(sid) and sid not in used else "scene_" + slug(sid)
        label, n = base, 2
        while label in used:
            label, n = f"{base}_{n}", n + 1
        used.add(label)
        out[sid] = label
    return out


def one_line(text) -> str:
    """Texte placé dans un commentaire : sur une seule ligne, pour ne jamais sortir du commentaire."""
    return " ".join(str(text).split())


def image_name(sc: dict, plan: dict) -> str:
    return f"{slug(sc['id'])}_{slug(plan['id'])}"


def rpy_string(text: str) -> str:
    """Chaîne Python entre guillemets (nom de personnage, titre) : pas d'interpolation Ren'Py."""
    return " ".join(str(text).split()).replace("\\", "\\\\").replace('"', '\\"')


def rpy_text(text: str) -> str:
    """Texte d'une réplique : guillemets et accolades échappés, pas de retour ligne."""
    t = " ".join(str(text).split())
    t = t.replace("\\", "\\\\").replace('"', '\\"')
    return t.replace("{", "{{").replace("[", "[[")


def plan_index(plan: dict, asset: dict):
    """Candidat affiché pour un plan : celui choisi, sinon l'image retenue de l'élément."""
    return plan.get("candidate", asset.get("validated_candidate"))


def has_image(plan: dict, assets: dict) -> bool:
    """Image exportable : un candidat choisi existe. Une image vide (rien de généré) est ignorée."""
    a = assets.get(plan["asset"])
    if a is None:
        return False
    idx = plan_index(plan, a)
    return idx is not None and 0 <= idx < len(a.get("candidates", []))


def _say_line(out: list, speaker: str, text_value: str, expr, chars: dict[str, str]) -> None:
    text = rpy_text(text_value)
    note = f"  # expression : {one_line(expr)}" if expr and one_line(expr) else ""
    if speaker == S.NARRATOR:
        out.append(f'    "{text}"{note}')
    else:
        out.append(f'    {chars.get(speaker) or char_var(speaker)} "{text}"{note}')


def exportable_plans(sc: dict, assets: dict) -> list[dict]:
    return [p for p in sc.get("plans", []) if has_image(p, assets)]


def split_problems(st: dict, assets_data: dict) -> tuple[list[str], list[str]]:
    """(bloquants, à vérifier). Seuls les bloquants empêchent l'export : ils rendraient le script
    invalide ou une image introuvable. Le reste est indicatif."""
    assets = assets_data["assets"]
    blocking: list[str] = []
    warnings: list[str] = []
    scenes = S.all_scenes(st)
    if not scenes:
        blocking.append("aucune scène")
    ids = [sc["id"] for sc in scenes]
    for sid in sorted({i for i in ids if ids.count(i) > 1}, key=str):
        blocking.append(f"scène en double : {sid}")
    for sc in scenes:
        where = sc["id"]
        for c in sc.get("choices", []):
            if c.get("target") not in ids:
                blocking.append(f"{where} : choix vers une scène inexistante '{c.get('target')}'")
        if not sc.get("dialogue"):
            blocking.append(f"{where} : pas de répliques")
        for n, line in enumerate(sc.get("dialogue", []), 1):
            if not str(line.get("text", "")).strip():
                blocking.append(f"{where} : réplique {n} vide")
        if sc.get("dialogue") and (not sc.get("plans") or sc["plans"][0]["from_line"] != 0):
            warnings.append(f"{where} : pas d'image au début de la scène")
        for plan in sc.get("plans", []):
            a = assets.get(plan["asset"])
            if a is None:
                blocking.append(f"{where} / {plan['id']} : image absente du registre")
                continue
            if not has_image(plan, assets):
                warnings.append(f"{where} / {plan['id']} : image vide, ignorée à l'export (rien n'est généré)")
                continue
            idx = plan_index(plan, a)
            cand = a["candidates"][idx]
            if not (paths.data_root() / cand["file"]).exists():
                blocking.append(f"{where} / {plan['id']} : fichier d'image introuvable")
            elif idx != a.get("validated_candidate"):
                warnings.append(f"{where} / {plan['id']} : image « {a.get('name', plan['asset'])} » non retenue")
    warnings += [w for w in S.validate(st, assets_data) if w not in blocking and w not in warnings]
    return list(dict.fromkeys(blocking)), list(dict.fromkeys(warnings))


def problems(st: dict, assets_data: dict) -> list[str]:
    blocking, warnings = split_problems(st, assets_data)
    return blocking + warnings


def _speakers(st: dict) -> list[str]:
    """Personnages qui parlent : dans les répliques, et dans les bulles des images seules."""
    seen = []
    for sc in S.all_scenes(st):
        names = [line["speaker"] for line in sc.get("dialogue", [])]
        names += [p.get("speaker") for p in sc.get("plans", []) if p.get("pause") and p.get("speech")]
        for name in names:
            if name and name != S.NARRATOR and name not in seen:
                seen.append(name)
    return seen


def build_story(st: dict, assets: dict | None = None) -> str:
    out = ["# Généré par renpy_maker : ne pas éditer à la main, modifier l'histoire puis réexporter.", ""]
    chars = char_vars(_speakers(st))
    for name, var in chars.items():
        out.append(f'define {var} = Character("{rpy_text(name)}")')
    out.append("")
    s = settings(st)
    size = f"xysize=({int(s['width'])}, {int(s['height'])}), fit=\"cover\""
    assets = assets or {}
    for sc in S.all_scenes(st):
        for plan in exportable_plans(sc, assets):
            name = image_name(sc, plan)
            out.append(f'image {name} = Transform("images/{name}.png", {size})')
    scenes = S.all_scenes(st)
    labels = scene_labels(scenes)
    out += ["", "label start:", f"    jump {labels[scenes[0]['id']]}", ""]

    for n, sc in enumerate(scenes):
        out.append(f"label {labels[sc['id']]}:")
        if one_line(sc.get("title", "")):
            out.append(f"    # {one_line(sc['title'])}")
        plans = exportable_plans(sc, assets)
        dialogue = sc.get("dialogue", [])
        # Même ordre que la lecture : une image seule avant sa réplique (ou après la dernière), avec sa
        # réplique si elle en a une, sinon un clic pour la garder à l'écran.
        for i in range(len(dialogue) + 1):
            for plan in [p for p in plans if p["from_line"] == i and p.get("pause")]:
                out.append(f"    scene {image_name(sc, plan)} with dissolve")
                if plan.get("speech"):
                    _say_line(out, plan.get("speaker") or S.NARRATOR, plan["speech"], None, chars)
                else:
                    out.append('    ""')
            normal = [p for p in plans if p["from_line"] == i and not p.get("pause")]
            for j, plan in enumerate(normal):
                out.append(f"    scene {image_name(sc, plan)} with dissolve")
                if j < len(normal) - 1:
                    out.append("    with Pause(1.0)")
            if i < len(dialogue):
                line = dialogue[i]
                _say_line(out, line["speaker"], line["text"], line.get("expression"), chars)
        # Suite de la scène, toujours explicite : un label n'enchaîne jamais sur le suivant par défaut.
        choices = [c for c in sc.get("choices", []) if c.get("target") in labels]
        if choices:
            out.append("    menu:")
            for c in choices:
                out.append(f'        "{rpy_text(c.get("label") or c.get("text") or c["target"])}":')
                out.append(f"            jump {labels[c['target']]}")
        elif sc.get("ending") or n == len(scenes) - 1:
            out.append("    return")
        else:
            out.append(f"    jump {labels[scenes[n + 1]['id']]}")
        out.append("")
    return "\n".join(out) + "\n"


def build_options(st: dict) -> str:
    s = settings(st)
    # Titre réglé pour Ren'Py, sinon celui de l'histoire (le parcours simple ne règle que celui-ci).
    title = st.get("settings", {}).get("renpy", {}).get("title") or st.get("title") or s["title"]
    return "\n".join([
        "# Généré par renpy_maker.",
        f'define config.name = _("{rpy_string(title)}")',
        'define config.version = "0.1"',
        f"define config.screen_width = {int(s['width'])}",
        f"define config.screen_height = {int(s['height'])}",
        "",
    ])


def export(st: dict, assets_data: dict) -> dict:
    """Écrit le projet Ren'Py. Lève ValueError si l'histoire a des points bloquants."""
    assets = assets_data["assets"]
    blocking, _ = split_problems(st, assets_data)
    if blocking:
        raise ValueError("Export impossible : " + " · ".join(blocking))

    game = project_dir() / "game"
    images = game / "images"
    images.mkdir(parents=True, exist_ok=True)
    for old in images.glob("*.png"):
        old.unlink()

    copied = []
    for sc in S.all_scenes(st):
        for plan in exportable_plans(sc, assets):
            a = assets[plan["asset"]]
            cand = a["candidates"][plan_index(plan, a)]
            src = paths.data_root() / cand["file"]
            dst = images / f"{image_name(sc, plan)}.png"
            shutil.copyfile(src, dst)
            copied.append(dst.name)

    for legacy in (game / "script.rpy", game / "script.rpyc"):  # fichier de test initial : conflit avec story.rpy
        if legacy.exists():
            legacy.unlink()

    paths.atomic_write(game / "story.rpy", build_story(st, assets))
    paths.atomic_write(game / "options.rpy", build_options(st))
    return {"dir": str(project_dir()), "images": len(copied), "files": ["story.rpy", "options.rpy"]}


def lint() -> dict:
    """Lance renpy lint sur le projet. Renvoie le statut et les lignes d'erreur."""
    proc = subprocess.run([str(renpy_sh()), str(project_dir()), "lint"],
                          capture_output=True, text=True, timeout=600)
    text = (proc.stdout or "") + (proc.stderr or "")
    errors = [l for l in text.splitlines() if re.search(r"\berror\b|Error|Traceback", l)]
    return {"ok": proc.returncode == 0 and not errors, "returncode": proc.returncode,
            "errors": errors[:40], "tail": text.strip().splitlines()[-12:]}


def launch() -> dict:
    """Ouvre le jeu dans la fenêtre Ren'Py (processus détaché)."""
    subprocess.Popen([str(renpy_sh()), str(project_dir())], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"launched": True}
