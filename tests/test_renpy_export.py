"""Export Ren'Py : texte généré et refus des histoires incomplètes (sans lancer Ren'Py)."""

import re
import unittest
from pathlib import Path

from renpy_maker import renpy_export as RE  # noqa: E402
from renpy_maker import story as S  # noqa: E402


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


class ImageOnlyPlanExportTests(unittest.TestCase):
    def test_image_only_plans_are_exported_in_playback_order(self):
        st, data = sample()
        s1 = st["chapters"][0]["scenes"][0]
        s1["plans"] = [
            {"id": "p1", "from_line": 0, "characters": [], "asset": "scene_s1_p1"},
            {"id": "p2", "from_line": 1, "characters": [], "asset": "scene_s1_p2", "pause": True,
             "speaker": "Eve", "speech": "Je reste là."},
            {"id": "p3", "from_line": 1, "characters": [], "asset": "scene_s1_p3", "pause": True},
            {"id": "p4", "from_line": 2, "characters": [], "asset": "scene_s1_p1", "pause": True},
        ]
        text = RE.build_story(st, data["assets"])
        block = text.split("label s1:")[1].split("label s2:")[0]
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        self.assertEqual(lines, [
            "# Arrivée",
            "scene s1_p1 with dissolve",
            '"Il fait jour."  # expression : neutre',
            "scene s1_p2 with dissolve",
            'c_eve "Je reste là."',
            "scene s1_p3 with dissolve",
            '""',
            'c_eve "Dit \\"bonjour\\" {{ok}"  # expression : sourire',
            "scene s1_p4 with dissolve",
            '""',
            "jump s2",
        ])


def statements(text: str) -> list[str]:
    """Instructions produites (hors commentaires), sans l'indentation."""
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


ALLOWED = re.compile(r'(define c_\w+ = Character\(".*"\)|image \w+ = Transform\(.*\)|label \w+:|jump \w+|return|menu:'
                     r'|scene \w+ with dissolve|with Pause\(1\.0\)|(c_\w+ )?".*"(  # .*)?|".*":)')


class HostileInputTests(unittest.TestCase):
    """Le compilateur ne produit que les instructions prévues, quel que soit le texte reçu."""

    HOSTILE = ["Titre\n    $ import os; os.system('id')", "x\ninit python:\n    import os",
               'a"b\\c', "[var] {b}gras{/b} 100%", "\r\n\t", "李"]

    def test_hostile_text_never_becomes_a_statement(self):
        st, data = sample()
        s1 = st["chapters"][0]["scenes"][0]
        for bad in self.HOSTILE:
            s1["title"] = bad
            s1["dialogue"][0]["expression"] = bad
            s1["dialogue"][0]["text"] = bad
            text = RE.build_story(st, data["assets"])
            for line in statements(text):
                self.assertRegex(line, ALLOWED)

    def test_choices_ending_and_next_scene_are_explicit(self):
        st, data = sample()
        ch = st["chapters"][0]
        s1, s2 = ch["scenes"]
        s3 = S.add_scene(ch, "s3", "Autre fin", "c", ["Eve"], "Ferme", {})
        s3["dialogue"] = [{"speaker": "Eve", "text": "Fin heureuse.", "expression": "neutre"}]
        s1["choices"] = [{"label": "Vers \"la fin\" [x]", "target": "s3"}, {"label": "Rester", "target": "s2"}]
        text = RE.build_story(st, data["assets"])
        block1 = text.split("label s1:")[1].split("label s2:")[0]
        self.assertIn('    menu:\n        "Vers \\"la fin\\" [[x]":\n            jump s3\n', block1)
        self.assertIn("            jump s2", block1)
        block2 = text.split("label s2:")[1].split("label s3:")[0]
        self.assertIn("    return", block2)          # s2 est une fin : pas d'enchaînement sur s3

    def test_scene_without_choice_jumps_to_next(self):
        st, data = sample()
        st["chapters"][0]["scenes"][1]["ending"] = False
        text = RE.build_story(st, data["assets"])
        self.assertIn("    jump s2\n", text.split("label s2:")[0])
        self.assertTrue(text.rstrip().endswith("return"))  # la dernière scène finit le jeu

    def test_choice_to_missing_scene_blocks_export(self):
        st, data = sample()
        st["chapters"][0]["scenes"][0]["choices"] = [{"label": "?", "target": "nulle_part"}]
        blocking, _ = RE.split_problems(st, data)
        self.assertTrue(any("nulle_part" in b for b in blocking))

    def test_duplicate_scene_blocks_export(self):
        st, data = sample()
        st["chapters"][0]["scenes"][1]["id"] = "s1"
        blocking, _ = RE.split_problems(st, data)
        self.assertTrue(any("en double" in b for b in blocking))

    def test_invalid_scene_ids_get_valid_unique_labels(self):
        labels = RE.scene_labels([{"id": "1-début"}, {"id": "s1"}, {"id": "start"}, {"id": "1 début"}])
        self.assertEqual(labels["s1"], "s1")
        self.assertTrue(all(RE.IDENT_RE.fullmatch(v) for v in labels.values()))
        self.assertEqual(len(set(labels.values())), 4)
        self.assertNotEqual(labels["start"], "start")

    def test_similar_names_get_distinct_variables(self):
        chars = RE.char_vars(["Léa", "Lea", "李", "王"])
        self.assertEqual(len(set(chars.values())), 4)
        self.assertEqual(chars["Léa"], "c_lea")

    def test_image_only_speaker_is_defined(self):
        st, data = sample()
        s1 = st["chapters"][0]["scenes"][0]
        s1["characters"].append("Tom")
        s1["plans"].append({"id": "p9", "from_line": 2, "characters": [], "asset": "scene_s1_p1",
                            "pause": True, "speaker": "Tom", "speech": "Coucou"})
        text = RE.build_story(st, data["assets"])
        self.assertIn('define c_tom = Character("Tom")', text)
        self.assertIn('c_tom "Coucou"', text)

    def test_options_title_is_not_interpolated(self):
        st, _ = sample()
        st["title"] = 'Mon [jeu] "x"'
        self.assertIn('define config.name = _("Mon [jeu] \\"x\\"")', RE.build_options(st))


class RenameTests(unittest.TestCase):
    def test_rename_character_updates_image_only_speaker_and_tags(self):
        from renpy_maker import facile_elements as FE
        st, _ = sample()
        s1 = st["chapters"][0]["scenes"][0]
        s1["plans"].append({"id": "p9", "from_line": 2, "pause": True, "speaker": "Eve", "speech": "Hé"})
        s1["line_tags"] = {"1": {"characters": ["Eve"], "location": "", "outfits": {"Eve": "robe"}}}
        FE._rename_character(st, "Eve", "Ève")
        self.assertEqual(s1["plans"][-1]["speaker"], "Ève")
        self.assertEqual(s1["line_tags"]["1"]["characters"], ["Ève"])
        self.assertEqual(s1["line_tags"]["1"]["outfits"], {"Ève": "robe"})
        self.assertEqual(S.validate(st), [])


class RouteRulesTests(unittest.TestCase):
    def test_explicit_next_and_open_line_follow_the_map(self):
        st, data = sample()
        ch = st["chapters"][0]
        s1, s2 = ch["scenes"]
        s3 = S.add_scene(ch, "s3", "Rattachée", "c", ["Eve"], "Ferme", {})
        s3["dialogue"] = [{"speaker": "Eve", "text": "Ici.", "expression": "neutre"}]
        s2["ending"] = False
        s1["next"] = "s3"          # route rattachée : s1 mène à s3, pas à s2
        s2["open"] = True          # ligne ouverte : elle attend sa suite
        text = RE.build_story(st, data["assets"])
        self.assertIn("    jump s3\n", text.split("label s2:")[0])
        self.assertIn("    return\n", text.split("label s2:")[1].split("label s3:")[0])
