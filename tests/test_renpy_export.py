"""Export Ren'Py : texte généré et refus des histoires incomplètes (sans lancer Ren'Py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import renpy_export as RE  # noqa: E402
import story as S  # noqa: E402


def asset(kind, name, validated=True, file="assets/x/cand_00.png"):
    return {"kind": kind, "name": name, "description": "", "prompt": "", "parent": None,
            "status": "validated" if validated else "draft",
            "validated_candidate": 0 if validated else None,
            "candidates": [{"index": 0, "file": file}]}


def sample():
    st = S.new_story("T", "i", total_scenes=2)
    ch = S.add_chapter(st, "ch1", "Chapitre 1", "r", 2)
    s1 = S.add_scene(ch, "s1", "Arrivée", "a", ["Eve"], "Ferme", {})
    s1["dialogue"] = [{"speaker": "Narration", "text": "Il fait jour.", "expression": "neutre"},
                      {"speaker": "Eve", "text": 'Dit "bonjour" {ok}', "expression": "sourire"}]
    s1["plans"] = [{"id": "p1", "from_line": 0, "characters": [], "asset": "scene_s1_p1"},
                   {"id": "p2", "from_line": 1, "characters": [], "asset": "scene_s1_p2"},
                   {"id": "p3", "from_line": 1, "characters": [], "asset": "scene_s1_p3"}]
    s2 = S.add_scene(ch, "s2", "Fin", "b", ["Eve"], "Ferme", {})
    s2["dialogue"] = [{"speaker": "Eve", "text": "Au revoir.", "expression": "neutre"}]
    s2["plans"] = [{"id": "p1", "from_line": 0, "characters": [], "asset": "scene_s2_p1"}]
    s2["ending"] = True
    assets = {
        "char_eve": asset("character", "Eve"), "loc_ferme": asset("location", "Ferme"),
        "scene_s1_p1": asset("scene", "img1"), "scene_s1_p2": asset("scene", "img2"),
        "scene_s1_p3": asset("scene", "img3"), "scene_s2_p1": asset("scene", "img4"),
    }
    return st, {"assets": assets}


class ExportTests(unittest.TestCase):
    def test_script_structure(self):
        st, _ = sample()
        text = RE.build_story(st)
        self.assertIn('define c_eve = Character("Eve")', text)
        self.assertIn("label s1:", text)
        self.assertIn("    scene s1_p1 with dissolve", text)
        self.assertIn("    with Pause(1.0)", text)          # deux images au même endroit
        self.assertIn("    scene s1_p3 with dissolve", text)
        self.assertIn('    "Il fait jour."', text)           # narration sans nom
        self.assertIn('    c_eve "Dit \\"bonjour\\" {{ok}"  # expression : sourire', text)
        self.assertTrue(text.rstrip().endswith("return"))

    def test_images_declared_for_every_plan(self):
        st, _ = sample()
        text = RE.build_story(st)
        self.assertIn('image s1_p2 = Transform("images/s1_p2.png", xysize=(1920, 1080), fit="cover")', text)
        self.assertIn('image s2_p1 = Transform("images/s2_p1.png", xysize=(1920, 1080), fit="cover")', text)

    def test_export_refused_when_image_not_retained(self):
        st, data = sample()
        data["assets"]["scene_s1_p2"]["status"] = "draft"
        data["assets"]["scene_s1_p2"]["validated_candidate"] = None
        issues = RE.problems(st, data)
        self.assertTrue(any("non retenue" in i for i in issues))
        with self.assertRaises(ValueError):
            RE.export(st, data)

    def test_first_image_must_start_the_scene(self):
        st, data = sample()
        st["chapters"][0]["scenes"][0]["plans"][0]["from_line"] = 1
        self.assertTrue(any("pas d'image au début" in i for i in RE.problems(st, data)))

    def test_no_problem_on_complete_story(self):
        st, data = sample()
        self.assertEqual(RE.problems(st, data), [])

    def test_options_use_title_and_resolution(self):
        st, _ = sample()
        st["settings"]["renpy"] = {"title": "Ma ferme", "width": 1280, "height": 720}
        text = RE.build_options(st)
        self.assertIn('define config.name = _("Ma ferme")', text)
        self.assertIn("define config.screen_width = 1280", text)


if __name__ == "__main__":
    unittest.main()
