"""Tests du modèle d'histoire (unittest, sans dépendance)."""

import unittest

from renpy_maker import appsettings
from renpy_maker import story as S  # noqa: E402

ASSETS = {"assets": {
    "char_eve": {"kind": "character"},
    "outfit_robe": {"kind": "outfit"},
    "loc_cuisine": {"kind": "location"},
}}


def make(total=3):
    st = S.new_story("Test", "idée", total_scenes=total)
    ch = S.add_chapter(st, "ch1", "Chapitre 1", "résumé", scene_count=total)
    for i in range(1, total + 1):
        S.add_scene(ch, f"s{i}", f"Scène {i}", "…", ["char_eve"], "loc_cuisine", {"char_eve": "outfit_robe"})
    ch["scenes"][-1]["ending"] = True   # la dernière scène est une fin
    return st


class StoryTests(unittest.TestCase):
    def test_migrate_fills_fields_added_later(self):
        st = make()
        sc = st["chapters"][0]["scenes"][0]
        del sc["plans"], sc["dialogue"]
        S.migrate(st)
        self.assertEqual(sc["plans"], [])
        self.assertEqual(sc["dialogue"], [])

    def test_linear_story_is_valid(self):
        self.assertEqual(S.validate(make(), ASSETS), [])

    def test_chapter_size_mismatch(self):
        st = make()
        st["chapters"][0]["scene_count"] = 5
        self.assertTrue(any("5" in e for e in S.validate(st, ASSETS)))

    def test_choice_to_missing_scene(self):
        st = make()
        st["chapters"][0]["scenes"][0]["choices"] = [{"label": "Oui", "target": "nowhere"}]
        self.assertTrue(any("inexistante" in e for e in S.validate(st, ASSETS)))

    def test_last_scene_must_be_ending(self):
        st = make()
        st["chapters"][0]["scenes"][-1]["ending"] = False
        self.assertTrue(any("sans suite" in e for e in S.validate(st, ASSETS)))
        st["chapters"][0]["scenes"][-1]["ending"] = True
        self.assertEqual(S.validate(st, ASSETS), [])

    def test_unknown_asset(self):
        st = make()
        st["chapters"][0]["scenes"][0]["location"] = "loc_inconnu"
        self.assertTrue(any("lieu inconnu" in e for e in S.validate(st, ASSETS)))

    def test_wrong_asset_kind(self):
        st = make()
        st["chapters"][0]["scenes"][0]["characters"] = ["loc_cuisine"]
        self.assertTrue(any("personnage inconnu" in e for e in S.validate(st, ASSETS)))

    def test_total_scenes_target(self):
        st = make(total=3)
        st["settings"]["total_scenes"] = 6
        self.assertTrue(any("3 scène(s) au total, 6" in e for e in S.validate(st, ASSETS)))

    def test_bad_provider_is_refused_in_app_settings(self):
        with self.assertRaises(ValueError):
            appsettings.set_provider("text", "inconnu")

    def test_duplicate_scene_id(self):
        st = make()
        st["chapters"][0]["scenes"][1]["id"] = "s1"
        self.assertTrue(any("en double" in e for e in S.validate(st, ASSETS)))


if __name__ == "__main__":
    unittest.main()
