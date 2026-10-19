"""Éléments de l'histoire, correspondance avec le registre, et verrouillage."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import story as S  # noqa: E402
from webapp import server as SRV  # noqa: E402


def sample():
    st = S.new_story("T", "idée", total_scenes=2)
    ch = S.add_chapter(st, "ch1", "C1", "…", 2)
    S.add_scene(ch, "s1", "A", "Au café", ["Eve", "Adrien"], "Le Velvet", {"Eve": "robe bleue"})
    S.add_scene(ch, "s2", "B", "Terrasse", ["eve"], "Le Velvet", {"Eve": "robe bleue"})
    ch["scenes"][-1]["ending"] = True
    return st


class ElementTests(unittest.TestCase):
    def test_elements_deduplicated_and_linked(self):
        els = S.story_elements(sample())
        kinds = sorted((e["kind"], e["name"]) for e in els)
        self.assertEqual(kinds, [("character", "Adrien"), ("character", "Eve"),
                                 ("location", "Le Velvet"), ("outfit", "robe bleue")])
        outfit = next(e for e in els if e["kind"] == "outfit")
        self.assertEqual(outfit["parent_name"], "Eve")
        self.assertEqual(outfit["scenes"], ["s1", "s2"])

    def test_match_outfit_requires_same_parent(self):
        assets = {
            "char_eve": {"kind": "character", "name": "Eve", "parent": None},
            "outfit_x": {"kind": "outfit", "name": "robe bleue", "parent": "char_eve"},
        }
        chars = {"eve": "char_eve"}
        el = {"kind": "outfit", "name": "Robe bleue", "parent_name": "Eve"}
        self.assertEqual(SRV._match_asset(assets, el, chars), "outfit_x")
        el["parent_name"] = "Adrien"
        self.assertIsNone(SRV._match_asset(assets, el, {"adrien": "char_adrien"}))

    def test_slug_is_ascii_and_safe(self):
        self.assertEqual(SRV._slug("Le Velvet, bar à cocktails!"), "le_velvet_bar_a_cocktails")


class LockTests(unittest.TestCase):
    def test_chapter_lock_locks_its_scenes(self):
        st = sample()
        ch = st["chapters"][0]
        self.assertFalse(S.is_locked(ch, ch["scenes"][0]))
        ch["locked"] = True
        self.assertTrue(S.is_locked(ch, ch["scenes"][0]))

    def test_scene_lock_is_local(self):
        st = sample()
        ch = st["chapters"][0]
        ch["scenes"][0]["locked"] = True
        self.assertTrue(S.is_locked(ch, ch["scenes"][0]))
        self.assertFalse(S.is_locked(ch, ch["scenes"][1]))

    def test_guard_refuses_edit_but_allows_unlock(self):
        ch = {"locked": True, "scenes": []}
        with self.assertRaises(ValueError):
            SRV._guard(ch, None, {"title": "nouveau"})
        SRV._guard(ch, None, {"locked": False})  # déverrouiller reste permis


if __name__ == "__main__":
    unittest.main()
