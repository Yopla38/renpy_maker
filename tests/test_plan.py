"""Tests de la génération de plan, sans appel LLM."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm  # noqa: E402
import plan as P  # noqa: E402
import story as S  # noqa: E402

RAW = {"title": "Le café", "summary": "Une rencontre.", "scenes": [
    {"title": "Arrivée", "summary": "Elle entre.", "characters": ["Eve"], "location": "Café", "outfits": {"Eve": "robe"}},
    {"title": "Table", "summary": "Ils parlent.", "characters": ["Eve", "Marc"], "location": "Café", "outfits": {}},
    {"title": "Sortie", "summary": "Ils partent.", "characters": ["Eve"], "location": None, "outfits": {}},
]}


class PlanTests(unittest.TestCase):
    def test_normalize_assigns_global_ids(self):
        ch = P.normalize(RAW, 3, first_scene_number=4)
        self.assertEqual([s["id"] for s in ch["scenes"]], ["s4", "s5", "s6"])
        self.assertEqual(ch["scenes"][0]["outfits"], {"Eve": "robe"})
        self.assertIsNone(ch["scenes"][2]["location"])

    def test_wrong_scene_count_is_rejected(self):
        with self.assertRaises(llm.LLMError):
            P.normalize(RAW, 2, 1)

    def test_extract_json_tolerates_code_fence(self):
        text = 'Voici :\n```json\n{"title": "T", "scenes": []}\n```'
        self.assertEqual(llm.extract_json(text)["title"], "T")

    def test_add_generated_gives_valid_chapter(self):
        st = S.new_story("T", "idée", total_scenes=3)
        ch = P.normalize(RAW, 3, 1)
        ch["id"] = "ch1"
        P.add_generated(st, ch)
        errs = [e for e in S.validate(st) if "sans suite" not in e]
        self.assertEqual(errs, [])
        self.assertEqual(st["chapters"][0]["scene_count"], 3)

    def test_prompt_states_explicit_flag(self):
        st = S.new_story("T", "idée")
        system, _ = P.build_prompt(st, 1, 3, "")
        self.assertIn("Contenu explicite autorisé : non", system)
        st["settings"]["explicit_content"] = True
        system, _ = P.build_prompt(st, 1, 3, "")
        self.assertIn("Contenu explicite autorisé : oui", system)


if __name__ == "__main__":
    unittest.main()


class ConcurrentChapterTests(unittest.TestCase):
    def test_two_chapters_generated_from_same_snapshot_get_unique_ids(self):
        st = S.new_story("t", "i", total_scenes=4)
        raw = {"title": "C", "summary": "r", "scenes": [{"title": "a", "summary": "b"}] * 2}
        first, second = P.normalize(raw, 2, 1), P.normalize(raw, 2, 1)
        first["id"] = second["id"] = "ch1"
        P.add_generated(st, first)
        P.add_generated(st, second)
        self.assertEqual([c["id"] for c in st["chapters"]], ["ch1", "ch2"])
        self.assertEqual([sc["id"] for sc in S.all_scenes(st)], ["s1", "s2", "s3", "s4"])
