"""Suggestion de prompt image : requête, nettoyage, appel LLM simulé (aucun appel réel)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import appsettings
from renpy_maker import paths
from renpy_maker import llm  # noqa: E402
from renpy_maker import prompts as PR  # noqa: E402
from renpy_maker import story as S  # noqa: E402


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
    @mock.patch("renpy_maker.assets.reference_style", return_value={"name": "3D réaliste", "positive_suffix": "photorealistic 3D render, realistic CGI character, soft cinematic lighting, detailed skin texture"})
    def test_request_contains_context_and_framing(self, _style):
        st, data = sample()
        system, user = PR.build_request(st, data["assets"], "outfit_robe")
        self.assertIn("Dress the woman from image 1", system)  # une tenue est une retouche de la personne
        self.assertIn("Image 1 : the young woman", user)
        self.assertNotIn("entre au Velvet", user)  # une tenue n'envoie pas de résumé de scène
        self.assertNotIn("Eve", user)  # aucun prénom dans ce que lit le modèle image
        self.assertIn("no style words", system)  # le style est ajouté par le programme (suggest)

    def test_location_requests_no_people(self):
        st, data = sample()
        data["assets"]["loc_velvet"] = {"kind": "location", "name": "Le Velvet", "description": "bar",
                                        "prompt": "", "parent": None, "status": "draft", "candidates": []}
        system, _ = PR.build_request(st, data["assets"], "loc_velvet")
        self.assertIn("empty, deserted place", system)     # formulé positivement pour le modèle d'image
        self.assertIn("never mention a person", system)    # consigne à l'IA d'écriture

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
        self.assertEqual(provider, appsettings.provider("text"))

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
        self.assertIn("Dress the woman from image 1", system)
        self.assertIn("Image 1 : the young woman", user)
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


class CharacterPersonTests(unittest.TestCase):
    """Le prompt d'un personnage doit représenter la personne choisie, même si l'histoire parle d'une femme."""

    def test_the_chosen_gender_is_stated_for_a_character(self):
        st = {"idea": "Une jeune femme fait un casting.", "synopsis": "", "settings": {}, "chapters": []}
        assets = {"c": {"kind": "character", "name": "Homme inconnu", "descriptor": "adult man",
                        "description": "", "candidates": [], "validated_candidate": None}}
        _, user = PR.build_request(st, assets, "c")
        self.assertIn("Person to depict : the man described by the descriptor 'adult man'", user)

    def test_character_is_built_on_a_neutral_backdrop_without_scene_context(self):
        st = {"idea": "Une jeune femme fait un casting.", "synopsis": "", "settings": {}, "chapters": [{
            "id": "ch1", "title": "C1", "summary": "", "scenes": [{
                "id": "s1", "title": "Train", "summary": "Un train de nuit.", "characters": ["Homme"],
                "dialogue": [], "plans": []}]}]}
        assets = {"c": {"kind": "character", "name": "Homme", "descriptor": "adult man",
                        "description": "", "candidates": [], "validated_candidate": None}}
        system, user = PR.build_request(st, assets, "c")
        self.assertIn("plain neutral studio backdrop", system)
        self.assertNotIn("Story context", user)
        self.assertNotIn("train", user.lower())

    def test_no_guess_when_the_gender_is_not_chosen(self):
        st = {"idea": "Une jeune femme fait un casting.", "synopsis": "", "settings": {}, "chapters": []}
        assets = {"c": {"kind": "character", "name": "Inconnu", "descriptor": "",
                        "description": "", "candidates": [], "validated_candidate": None}}
        _, user = PR.build_request(st, assets, "c")
        self.assertIn("gender and age not chosen yet", user)


class LocationEmptyTests(unittest.TestCase):
    """Un lieu reste vide : ni ses notes (résumé de scène), ni les personnages dans le prompt."""

    def setUp(self):
        self.st = {"idea": "x", "synopsis": "", "settings": {}, "chapters": [{
            "id": "ch1", "title": "C1", "summary": "", "scenes": [{
                "id": "s1", "title": "Un voisin encombrant", "summary": "Un homme s'assied près de Léa.",
                "characters": ["Léa"], "location": "loc_train", "dialogue": [], "plans": []}]}]}
        self.assets = {"loc_train": {"kind": "location", "name": "Compartiment du train",
                                     "description": "Un homme s'assied à côté de Léa.", "candidates": [],
                                     "validated_candidate": None}}

    def test_location_request_has_no_notes_and_no_scene_context(self):
        _, user = PR.build_request(self.st, self.assets, "loc_train")
        self.assertNotIn("Notes", user)
        self.assertNotIn("Scene where", user)
        self.assertNotIn("Un voisin", user)

    def test_person_words_are_detected(self):
        self.assertTrue(PR.shows_person("An old man sits opposite a young woman."))
        self.assertFalse(PR.shows_person("An empty compartment with worn red seats and dust motes."))

    def test_person_in_a_location_prompt_is_asked_again_then_refused(self):
        assets_data = {"assets": self.assets}
        answers = ["An old man sits in the compartment.", "A woman sits by the window."]
        with mock.patch.object(PR.llm, "complete_task", side_effect=answers) as m:
            with self.assertRaises(ValueError):
                PR.suggest(self.st, assets_data, "loc_train", provider="anthropic")
        self.assertEqual(m.call_count, 2)
        self.assertIn("EMPTY", m.call_args_list[1][0][1])

    def test_empty_location_prompt_is_kept(self):
        assets_data = {"assets": self.assets}
        with mock.patch.object(PR.llm, "complete_task", return_value="An empty compartment with red seats."):
            text = PR.suggest(self.st, assets_data, "loc_train", provider="anthropic")
        self.assertIn("empty compartment", text)


class PersonNounTests(unittest.TestCase):
    def test_outfit_edit_uses_the_real_gender_word(self):
        from renpy_maker.prompt_texts import t
        from renpy_maker.prompts import person_noun
        self.assertEqual(person_noun("Old man"), "man")
        self.assertEqual(person_noun("young woman"), "woman")
        self.assertEqual(person_noun(""), "person")
        system = t("image.outfit.system", style="s", noun="man")
        self.assertIn("the man from image 1", system)
        self.assertNotIn("woman", system)

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

    def test_outfit_starts_from_one_image_of_the_person(self):
        # La tenue de départ montre déjà la personne : pas de seconde image d'elle (dédoublement).
        self.assertEqual(PR.ref_order(self.assets(), "o2"), ["o1"])
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
        self.assertIn("Image 1 : the man wearing Chemise", user)
        self.assertNotIn("Image 2", user)


class NudeBaseTests(unittest.TestCase):
    """Corps de base nu : seulement avec ComfyUI, histoire explicite, hors application enfants."""

    def request(self, engine, explicit, kids=False):
        st = {"idea": "Une femme.", "synopsis": "", "settings": {"explicit_content": explicit}, "chapters": []}
        assets = {"c": {"kind": "character", "name": "Léa", "descriptor": "young woman", "description": "",
                        "candidates": [], "validated_candidate": None}}
        with mock.patch.object(PR.appsettings, "image_for", return_value={"engine": engine, "workflow": None}), \
                mock.patch.object(PR.paths, "KIDS", kids):
            return PR.build_request(st, assets, "c")[1]

    def test_comfyui_with_explicit_story_asks_for_a_nude_base(self):
        self.assertIn("nude", self.request("comfyui", True))

    def test_replicate_keeps_the_clothed_base(self):
        self.assertNotIn("nude", self.request("replicate", True))

    def test_without_explicit_content_the_base_stays_clothed(self):
        self.assertNotIn("nude", self.request("comfyui", False))

    def test_kids_never_get_a_nude_base(self):
        self.assertNotIn("nude", self.request("comfyui", True, kids=True))


class PhysicalOnlyBaseTests(unittest.TestCase):
    """Corps nu : la description ne donne que les traits physiques ; les vêtements vont aux tenues."""

    def setUp(self):
        self.st = {"idea": "Une femme.", "synopsis": "", "settings": {"explicit_content": True}, "chapters": []}
        self.assets = {"c": {"kind": "character", "name": "Clara", "descriptor": "young woman",
                             "description": "Cheveux blonds, yeux verts. Un pull trop grand.",
                             "candidates": [], "validated_candidate": None}}

    def test_clothing_in_the_notes_is_marked_as_to_ignore(self):
        with mock.patch.object(PR.appsettings, "image_for", return_value={"engine": "comfyui", "workflow": None}), \
                mock.patch.object(PR.paths, "KIDS", False):
            _, user = PR.build_request(self.st, self.assets, "c")
        self.assertIn("Physical traits only", user)
        self.assertIn("IGNORE any clothing", user)

    def test_a_prompt_that_still_describes_clothing_is_asked_again_then_refused(self):
        with mock.patch.object(PR.appsettings, "image_for", return_value={"engine": "comfyui", "workflow": None}), \
                mock.patch.object(PR.paths, "KIDS", False), \
                mock.patch.object(PR.llm, "complete_task", return_value="A woman in a sweater.") as m, \
                mock.patch.object(PR.appsettings, "provider", return_value="ollama"):
            with self.assertRaises(ValueError):
                PR.suggest(self.st, {"assets": self.assets}, "c")
        self.assertEqual(m.call_count, 2)

    def test_a_physical_prompt_is_kept(self):
        with mock.patch.object(PR.appsettings, "image_for", return_value={"engine": "comfyui", "workflow": None}), \
                mock.patch.object(PR.paths, "KIDS", False), \
                mock.patch.object(PR.llm, "complete_task", return_value="A woman with blonde hair and green eyes."), \
                mock.patch.object(PR.appsettings, "provider", return_value="ollama"):
            text = PR.suggest(self.st, {"assets": self.assets}, "c")
        self.assertIn("blonde hair", text)


class CharacterPromptFormTests(unittest.TestCase):
    def test_every_character_prompt_starts_with_full_body_shot(self):
        self.assertEqual(PR.character_prompt_rules("A young woman with green eyes.", False),
                         "full body shot, a young woman with green eyes.")

    def test_full_body_shot_is_not_repeated(self):
        self.assertEqual(PR.character_prompt_rules("full body shot, a man.", False), "full body shot, a man.")

    def test_nude_goes_right_before_the_gender_word(self):
        self.assertEqual(PR.character_prompt_rules("A young woman with green eyes.", True),
                         "full body shot, a young nude woman with green eyes.")

    def test_nude_is_not_added_twice(self):
        out = PR.character_prompt_rules("a young nude woman", True)
        self.assertEqual(out.lower().count("nude"), 1)
