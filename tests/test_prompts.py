"""Suggestion de prompt image : requête, nettoyage, appel LLM simulé (aucun appel réel)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
        self.assertIn("young woman entre au Velvet.", user)
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
