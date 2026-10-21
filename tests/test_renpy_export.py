"""Export Ren'Py : texte généré et refus des histoires incomplètes (sans lancer Ren'Py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import renpy_export as RE  # noqa: E402
import story as S  # noqa: E402


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "image_test.png"
# PNG 1x1 minimal : les tests ne dépendent pas des images générées du projet
_PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                     "0000000d49444154789c6360f8ffff3f0005fe02fea7d9e1d30000000049454e44ae426082")
FIXTURE.parent.mkdir(exist_ok=True)
if not FIXTURE.exists():
    FIXTURE.write_bytes(_PNG)


def asset(kind, name, validated=True, file=None):
    file = file or str(FIXTURE.relative_to(Path(__file__).resolve().parent.parent))
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
        st, data = sample()
        text = RE.build_story(st, data["assets"])
        self.assertIn('define c_eve = Character("Eve")', text)
        self.assertIn("label s1:", text)
        self.assertIn("    scene s1_p1 with dissolve", text)
        self.assertIn("    with Pause(1.0)", text)          # deux images au même endroit
        self.assertIn("    scene s1_p3 with dissolve", text)
        self.assertIn('    "Il fait jour."', text)           # narration sans nom
        self.assertIn('    c_eve "Dit \\"bonjour\\" {{ok}"  # expression : sourire', text)
        self.assertTrue(text.rstrip().endswith("return"))

    def test_images_declared_for_every_plan(self):
        st, data = sample()
        text = RE.build_story(st, data["assets"])
        self.assertIn('image s1_p2 = Transform("images/s1_p2.png", xysize=(1920, 1080), fit="cover")', text)
        self.assertIn('image s2_p1 = Transform("images/s2_p1.png", xysize=(1920, 1080), fit="cover")', text)

    def test_unretained_image_is_only_a_warning(self):
        st, data = sample()
        data["assets"]["scene_s1_p2"]["status"] = "draft"
        data["assets"]["scene_s1_p2"]["validated_candidate"] = None
        st["chapters"][0]["scenes"][0]["plans"][1]["candidate"] = 0  # un candidat est choisi, sans être retenu
        blocking, warnings = RE.split_problems(st, data)
        self.assertEqual(blocking, [])
        self.assertTrue(any("non retenue" in w for w in warnings))

    def test_missing_image_file_blocks_export(self):
        st, data = sample()
        data["assets"]["scene_s1_p2"]["candidates"] = [{"index": 0, "file": "assets/inexistant.png"}]
        blocking, _ = RE.split_problems(st, data)
        self.assertTrue(any("introuvable" in b for b in blocking))

    def test_empty_line_blocks_export(self):
        st, data = sample()
        st["chapters"][0]["scenes"][1]["dialogue"][0]["text"] = " "
        blocking, _ = RE.split_problems(st, data)
        self.assertTrue(any("vide" in b for b in blocking))

    def test_first_image_must_start_the_scene(self):
        st, data = sample()
        st["chapters"][0]["scenes"][0]["plans"][0]["from_line"] = 1
        self.assertTrue(any("pas d'image au début" in i for i in RE.problems(st, data)))

    def test_empty_image_is_skipped_not_blocking(self):
        st, data = sample()
        data["assets"]["scene_s1_p3"]["candidates"] = []
        data["assets"]["scene_s1_p3"]["validated_candidate"] = None
        blocking, warnings = RE.split_problems(st, data)
        self.assertEqual(blocking, [])
        self.assertTrue(any("image vide" in w for w in warnings))
        text = RE.build_story(st, data["assets"])
        self.assertNotIn("scene s1_p3 with dissolve", text)

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
