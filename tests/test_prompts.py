"""Suggestion de prompt image : requête, nettoyage, appel LLM simulé (aucun appel réel)."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import appsettings
import paths
import llm  # noqa: E402
import prompts as PR  # noqa: E402
import story as S  # noqa: E402


def sample():
    st = S.new_story("t", "i", total_scenes=1)
    ch = S.add_chapter(st, "ch1", "C", "r", 1)
    S.add_scene(ch, "s1", "Arrivée", "Eve entre au Velvet.", ["Eve"], "Le Velvet", {"Eve": "robe bleue"})
    ch["scenes"][0]["ending"] = True
    assets = {
        "char_eve": {"kind": "character", "name": "Eve", "descriptor": "young woman", "description": "femme de 21 ans, blonde",
                     "prompt": "adult woman, 21, blonde hair, blue eyes", "parent": None,
                     "status": "draft", "candidates": []},
        "outfit_robe": {"kind": "outfit", "name": "robe bleue", "description": "robe courte bleu nuit",
                        "prompt": "", "parent": "char_eve", "status": "draft", "candidates": []},
    }
    return st, {"assets": assets}


class PromptTests(unittest.TestCase):
    # Style figé : sans style choisi dans l'histoire, c'est celui de config.yaml qui s'applique.
    @mock.patch("assets.reference_style", return_value={"name": "3D réaliste", "positive_suffix": "photorealistic 3D render, realistic CGI character, soft cinematic lighting, detailed skin texture"})
    def test_request_contains_context_and_framing(self, _style):
        st, data = sample()
        system, user = PR.build_request(st, data["assets"], "outfit_robe")
        self.assertIn("Keep the woman from image 1", system)  # une tenue est une retouche de la personne
        self.assertIn("Reference image 1 : the young woman", user)
        self.assertNotIn("entre au Velvet", user)  # une tenue n'envoie pas de résumé de scène
        self.assertNotIn("Eve", user)  # aucun prénom dans ce que lit le modèle image
        self.assertIn("photorealistic 3D render", system)  # style de référence, lu dans config.yaml

    def test_location_requests_no_people(self):
        st, data = sample()
        data["assets"]["loc_velvet"] = {"kind": "location", "name": "Le Velvet", "description": "bar",
                                        "prompt": "", "parent": None, "status": "draft", "candidates": []}
        system, _ = PR.build_request(st, data["assets"], "loc_velvet")
        self.assertIn("no people", system)

    def test_clean_keeps_first_paragraph_only(self):
        self.assertEqual(PR.clean('"A woman in a blue dress."\n\nNote: ok'), "A woman in a blue dress.")
        with self.assertRaises(llm.LLMError):
            PR.clean("   ")

    @mock.patch.object(paths, "app_settings_file", lambda p=Path(tempfile.mkdtemp()) / "app_settings.yaml": p)
    def test_suggest_uses_text_provider_and_returns_cleaned_prompt(self):
        st, data = sample()
        with mock.patch.object(llm, "complete", return_value="A young woman in a short dark blue dress.") as m:
            text = PR.suggest(st, data, "outfit_robe")
        self.assertTrue(text.startswith("A young woman in a short dark blue dress."))
        self.assertTrue(text.endswith(PR.llm_style()))
        provider = m.call_args[0][0]
        self.assertEqual(provider, st["settings"]["providers"]["text"])

    def test_match_asset_links_story_element_to_registry(self):
        st, data = sample()
        chars = {"eve": "char_eve"}
        el = {"kind": "outfit", "name": "Robe bleue", "parent_name": "eve"}
        self.assertEqual(PR.match_asset(data["assets"], el, chars), "outfit_robe")


class EditPromptTests(unittest.TestCase):
    def test_outfit_prompt_is_an_edit_of_the_character(self):
        st, data = sample()
        system, user = PR.build_request(st, data["assets"], "outfit_robe")
        self.assertIn("EDIT", system)
        self.assertIn("Keep the woman from image 1", system)
        self.assertIn("Reference image 1 : the young woman", user)
        self.assertNotIn("Eve", user)


if __name__ == "__main__":
    unittest.main()


class StyleEndingTests(unittest.TestCase):
    def test_style_is_added_once_at_the_end(self):
        style = "watercolor painting, soft wet edges"
        self.assertEqual(PR.with_style("A woman in blue.", style), "A woman in blue. watercolor painting, soft wet edges")
        already = "A woman in blue. watercolor painting, soft wet edges"
        self.assertEqual(PR.with_style(already, style), already)
        self.assertEqual(PR.with_style("A woman.", ""), "A woman.")


class PersonNounTests(unittest.TestCase):
    def test_outfit_edit_uses_the_real_gender_word(self):
        from prompts import EDIT_SYSTEM, person_noun
        self.assertEqual(person_noun("Old man"), "man")
        self.assertEqual(person_noun("young woman"), "woman")
        self.assertEqual(person_noun(""), "person")
        self.assertIn("the man from image 1", EDIT_SYSTEM.format(style="s", noun="man"))
        self.assertNotIn("woman", EDIT_SYSTEM.format(style="s", noun="man"))

    def test_outfit_request_has_no_scene_summary_that_could_mislead_the_gender(self):
        st = {"settings": {"style": "aquarelle"}, "idea": "", "synopsis": "",
              "chapters": [{"id": "c1", "title": "C", "summary": "", "scenes": [
                  {"id": "s1", "title": "Studio", "summary": "Léa fait face à Victor, qui la regarde.",
                   "characters": ["Léa", "Victor"], "outfits": {"Victor": "Chemise sombre"}, "dialogue": [],
                   "plans": [], "location": ""}]}]}
        assets = {
            "char_victor": {"kind": "character", "name": "Victor", "descriptor": "old man", "description": ""},
            "outfit_v": {"kind": "outfit", "name": "Chemise sombre", "parent": "char_victor", "description": ""},
        }
        _, user = PR.build_request(st, assets, "outfit_v")
        self.assertNotIn("Léa", user)
        self.assertIn("old man", user)


class ReferenceOrderTests(unittest.TestCase):
    def assets(self):
        return {
            "c": {"kind": "character", "name": "Victor", "descriptor": "old man", "validated_candidate": 0},
            "o1": {"kind": "outfit", "name": "Chemise", "parent": "c", "validated_candidate": 0},
            "o2": {"kind": "outfit", "name": "Lunettes", "parent": "c", "validated_candidate": 0,
                   "based_on": "o1"},
            "loc": {"kind": "location", "name": "Bureau", "validated_candidate": 0, "refs": []},
        }

    def test_outfit_starts_from_its_base_then_the_character(self):
        self.assertEqual(PR.ref_order(self.assets(), "o2"), ["o1", "c"])
        self.assertEqual(PR.ref_order(self.assets(), "o1"), ["c"])

    def test_chosen_references_come_after_and_unretained_ones_are_dropped(self):
        a = self.assets()
        a["loc"]["refs"] = ["o1", "missing"]
        a["o1"]["refs"] = ["loc"]
        a["loc"]["validated_candidate"] = None
        self.assertEqual(PR.ref_order(a, "o1"), ["c"])
        a["loc"]["validated_candidate"] = 0
        self.assertEqual(PR.ref_order(a, "o1"), ["c", "loc"])

    def test_outfit_request_names_the_base_outfit_as_image_one(self):
        st = {"settings": {"style": "aquarelle"}, "idea": "", "synopsis": "", "chapters": []}
        _, user = PR.build_request(st, self.assets(), "o2")
        self.assertIn("Reference image 1 : the man wearing Chemise", user)
        self.assertIn("Reference image 2 : the old man", user)
