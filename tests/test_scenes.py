"""Images de scène : références, plans, préparation, prompt (aucun appel réel au LLM)."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import appsettings
import paths
import llm  # noqa: E402
import scenes as SC  # noqa: E402
import story as S  # noqa: E402


def asset(kind, name, status="validated", parent=None, prompt="x"):
    return {"kind": kind, "name": name, "description": "", "prompt": prompt, "parent": parent,
            "status": status, "validated_candidate": 0 if status == "validated" else None,
            "candidates": [{"index": 0, "file": "f.png"}] if status == "validated" else []}


def make(chars=("Eve", "Adrien")):
    st = S.new_story("t", "i", total_scenes=1)
    ch = S.add_chapter(st, "ch1", "C", "r", 1)
    sc = S.add_scene(ch, "s1", "Table", "Ils dînent.", list(chars), "Le Velvet",
                     {"Eve": "robe bleue"})
    sc["ending"] = True
    sc["dialogue"] = [{"speaker": "Eve", "text": "Bonsoir.", "expression": "sourire"},
                      {"speaker": "Adrien", "text": "Vous êtes en retard.", "expression": "amusé"},
                      {"speaker": "Eve", "text": "Pas tant que ça.", "expression": "défi"}]
    sc["plans"] = [{"id": "p1", "from_line": 0, "characters": [], "asset": "scene_s1_p1"}]
    assets = {
        "loc_velvet": asset("location", "Le Velvet"),
        "char_eve": {**asset("character", "Eve"), "descriptor": "young woman"},
        "char_adrien": {**asset("character", "Adrien"), "descriptor": "young man"},
        "outfit_robe": asset("outfit", "robe bleue", parent="char_eve"),
        "scene_s1_p1": asset("scene", "Table · image 1", status="draft", prompt=""),
    }
    return st, sc, {"assets": assets}


class SceneTests(unittest.TestCase):
    def test_refs_use_location_and_outfits_of_validated_images(self):
        st, sc, data = make()
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertEqual(info["missing"], [])
        self.assertEqual(info["refs"], ["loc_velvet", "outfit_robe", "char_adrien"])

    def test_missing_retained_image_blocks(self):
        st, sc, data = make()
        data["assets"]["outfit_robe"]["status"] = "draft"
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertTrue(any("robe bleue" in m for m in info["missing"]))

    def test_more_than_five_refs_is_flagged(self):
        st, sc, data = make(chars=("Eve", "Adrien", "Léa", "Marc", "Zoé"))
        for n in ("Léa", "Marc", "Zoé"):
            data["assets"][f"char_{n}"] = asset("character", n)
        sc["dialogue"] += [{"speaker": n, "text": "Bonjour.", "expression": "neutre"} for n in ("Léa", "Marc", "Zoé")]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertTrue(info["too_many"])
        status = SC.plan_status(data["assets"], sc, 0)
        self.assertTrue(any("5 au plus" in i for i in status["issues"]))

    def test_plan_ready_only_when_its_image_is_retained(self):
        st, sc, data = make()
        self.assertFalse(SC.plan_status(data["assets"], sc, 0)["ready"])
        data["assets"]["scene_s1_p1"]["status"] = "validated"
        self.assertTrue(SC.plan_status(data["assets"], sc, 0)["ready"])

    def test_plan_lines_split_dialogue(self):
        st, sc, data = make()
        sc["plans"].append({"id": "p2", "from_line": 2, "characters": ["Eve"], "asset": "scene_s1_p2"})
        self.assertEqual(len(SC.plan_lines(sc, 0)), 2)
        self.assertEqual([l["text"] for l in SC.plan_lines(sc, 1)], ["Pas tant que ça."])
        self.assertEqual(SC.plan_characters(sc, sc["plans"][1]), ["Eve"])

    def test_scene_status_lists_what_is_missing(self):
        st, sc, data = make()
        sc["plans"] = []
        rows = SC.scene_status(st, data["assets"])
        self.assertFalse(rows[0]["ready"])
        self.assertIn("aucune image de scène", rows[0]["issues"])

    def test_prompt_request_names_references_in_order(self):
        st, sc, data = make()
        system, user = SC.build_request(st, data["assets"], sc, 0)
        self.assertIn("image 1 = décor : Le Velvet", system)
        self.assertIn("by its position", system)
        self.assertIn("never more than 100", system)
        self.assertIn("young woman : défi", user)  # dernière expression du plan
        self.assertIn("- young woman : Bonsoir.", user)

    @mock.patch.object(paths, "app_settings_file", lambda p=Path(tempfile.mkdtemp()) / "app_settings.yaml": p)
    def test_suggest_with_mocked_llm(self):
        st, sc, data = make()
        with mock.patch.object(llm, "complete", return_value="A candlelit table, two people.") as m:
            text = SC.suggest(st, data, sc, 0)
        self.assertTrue(text.startswith("A candlelit table, two people."))
        self.assertTrue(text.endswith(SC.PR.llm_style()))  # le style du projet termine toujours le prompt
        self.assertEqual(m.call_args[0][0], appsettings.provider("text"))

    def test_several_images_can_share_a_line(self):
        st, sc, data = make()
        sc["plans"].append({"id": "p2", "from_line": 0, "characters": [], "asset": "scene_s1_p2"})
        sc["plans"].append({"id": "p3", "from_line": 1, "characters": [], "asset": "scene_s1_p3"})
        self.assertEqual(S.validate(st, data), [])

    def test_plan_validation_first_plan_must_start_at_zero(self):
        st, sc, data = make()
        sc["plans"][0]["from_line"] = 1
        self.assertTrue(any("au début" in e for e in S.validate(st, data)))


class RefChoiceTests(unittest.TestCase):
    def test_auto_ref_can_be_unchecked(self):
        st, sc, data = make()
        sc["plans"][0]["refs_exclude"] = ["char_adrien"]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertNotIn("char_adrien", info["refs"])
        auto = {a["id"]: a["excluded"] for a in info["auto"]}
        self.assertTrue(auto["char_adrien"])
        # Adrien reste dans l'image sans référence : c'est signalé
        self.assertTrue(any("Adrien" in m for m in info["missing"]))

    def test_removing_character_from_image_clears_warning(self):
        st, sc, data = make()
        sc["plans"][0]["refs_exclude"] = ["char_adrien"]
        sc["plans"][0]["characters"] = ["Eve"]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertEqual(info["missing"], [])

    def test_added_reference_still_maps_to_its_person(self):
        st, sc, data = make()
        sc["plans"][0]["refs_exclude"] = []
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        sc["plans"][0]["refs_extra"] = []
        data["assets"]["char_eve"]["status"] = "validated"
        line = SC._people_line(sc["plans"][0], sc, {"labels": ["décor : Le Velvet", "Eve (ajoutée)"]}, data["assets"])
        self.assertIn("young woman (image 2)", line)
        self.assertNotIn("Eve", line)

    def test_default_people_are_the_speakers_of_the_image(self):
        st, sc, data = make()
        sc["characters"] = ["Eve", "Adrien", "Léa"]  # Léa ne parle pas
        sc["dialogue"] = [{"speaker": "Eve", "text": "a", "expression": "neutre"},
                          {"speaker": "Adrien", "text": "b", "expression": "neutre"}]
        sc["plans"] = [{"id": "p1", "from_line": 0, "characters": [], "asset": "scene_s1_p1"}]
        self.assertEqual(SC.plan_characters(sc, sc["plans"][0]), ["Eve", "Adrien"])

    def test_people_line_maps_names_to_reference_numbers(self):
        st, sc, data = make()
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        line = SC._people_line(sc["plans"][0], sc, info, data["assets"])
        self.assertIn("young man (image", line)
        self.assertIn("young woman (image", line)
        self.assertNotIn("Adrien", line)

    def test_extra_ref_adds_previous_image_for_continuity(self):
        st, sc, data = make()
        data["assets"]["scene_s0_p1"] = asset("scene", "Image précédente", prompt="previous shot")
        sc["plans"][0]["refs_extra"] = ["scene_s0_p1"]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertIn("scene_s0_p1", info["refs"])
        self.assertEqual(info["extra"][0]["id"], "scene_s0_p1")

    def test_unvalidated_extra_blocks(self):
        st, sc, data = make()
        data["assets"]["scene_s0_p1"] = asset("scene", "Image précédente", status="draft")
        sc["plans"][0]["refs_extra"] = ["scene_s0_p1"]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertTrue(any("Image précédente" in m for m in info["missing"]))

    def test_plan_cannot_reference_itself(self):
        st, sc, data = make()
        sc["plans"][0]["refs_extra"] = ["scene_s1_p1"]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertNotIn("scene_s1_p1", info["refs"])


class StableExclusionTests(unittest.TestCase):
    def test_excluding_a_role_works_whatever_the_outfit_entry(self):
        st, sc, data = make()
        data["assets"]["outfit_robe_2"] = asset("outfit", "robe bleue", parent="char_eve")
        sc["plans"][0]["refs_exclude"] = ["tenue:eve"]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertFalse(any("en tenue" in l for l in info["labels"]))


class CandidateRefTests(unittest.TestCase):
    def test_reference_can_designate_a_non_retained_candidate(self):
        st, sc, data = make()
        data["assets"]["scene_s0_p1"] = {"kind": "scene", "name": "Image précédente", "description": "", "prompt": "",
                                          "parent": None, "status": "validated", "validated_candidate": 5,
                                          "candidates": [{"index": i, "file": "f.png"} for i in range(6)]}
        sc["plans"][0]["refs_extra"] = ["scene_s0_p1@4"]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertIn("scene_s0_p1@4", info["refs"])
        self.assertTrue(any("#4" in l for l in info["labels"]))

    def test_prompt_request_accepts_candidate_reference(self):
        st, sc, data = make()
        data["assets"]["scene_s0_p1"] = {"kind": "scene", "name": "Image précédente", "description": "deux personnes",
                                          "prompt": "two people in a field", "parent": None, "status": "validated",
                                          "validated_candidate": 5,
                                          "candidates": [{"index": i, "file": "f.png"} for i in range(6)]}
        sc["plans"][0]["refs_extra"] = ["scene_s0_p1@4"]
        _, user = SC.build_request(st, data["assets"], sc, 0)
        self.assertNotIn("two people in a field", user)  # l'élément ne décrit pas l'image précise
        self.assertIn("(Image précédente #4 (ajoutée))", user)

    def test_reference_to_unknown_candidate_is_reported(self):
        st, sc, data = make()
        data["assets"]["scene_s0_p1"] = {"kind": "scene", "name": "x", "description": "", "prompt": "",
                                          "parent": None, "status": "validated", "validated_candidate": 0,
                                          "candidates": [{"index": 0, "file": "f.png"}]}
        sc["plans"][0]["refs_extra"] = ["scene_s0_p1@9"]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertNotIn("scene_s0_p1@9", info["refs"])
        self.assertTrue(info["missing"])


class ContinuityTests(unittest.TestCase):
    def test_added_previous_image_means_edit_not_new_shot(self):
        st, sc, data = make()
        data["assets"]["scene_s0_p1"] = asset("scene", "Image précédente", prompt="previous shot")
        sc["plans"][0]["refs_extra"] = ["scene_s0_p1"]
        system, user = SC.build_request(st, data["assets"], sc, 0)
        self.assertIn("This is an EDIT of image", system)
        self.assertIn("keep its framing", system)
        self.assertNotIn("composition is new", system)
        self.assertNotIn("Choose a framing", user)

    def test_continuity_does_not_block_people_without_outfit_ref(self):
        st, sc, data = make()
        data["assets"]["scene_s0_p1"] = asset("scene", "Image précédente", prompt="previous shot")
        sc["plans"][0]["refs_exclude"] = ["outfit_robe"]
        sc["plans"][0]["refs_extra"] = ["scene_s0_p1"]
        info = SC.plan_refs(data["assets"], sc, sc["plans"][0])
        self.assertFalse(any("sans image de référence" in m for m in info["missing"]))

    def test_explicit_shot_still_asks_for_new_composition(self):
        st, sc, data = make()
        data["assets"]["scene_s0_p1"] = asset("scene", "Image précédente", prompt="previous shot")
        sc["plans"][0]["refs_extra"] = ["scene_s0_p1"]
        sc["plans"][0]["shot"] = {"framing": "close-up", "angle": "", "note": ""}
        system, _ = SC.build_request(st, data["assets"], sc, 0)
        self.assertIn("composition is new", system)


class ShotTests(unittest.TestCase):
    def test_requested_shot_is_in_the_request(self):
        st, sc, data = make()
        sc["plans"][0]["shot"] = {"framing": "close-up", "angle": "from behind", "note": "her hand on the rail"}
        system, user = SC.build_request(st, data["assets"], sc, 0)
        self.assertIn("framing close-up, camera from behind", user)
        self.assertIn("composition is new", system)

    def test_next_image_must_differ_from_previous_shot(self):
        st, sc, data = make()
        sc["plans"][0]["shot"] = {"framing": "wide shot", "angle": "eye level", "note": ""}
        sc["plans"].append({"id": "p2", "from_line": 1, "characters": [], "asset": "scene_s1_p2"})
        _, user = SC.build_request(st, data["assets"], sc, 1)
        self.assertIn("Previous image shot : framing wide shot", user)
        self.assertIn("Do not reuse its composition", user)


class ReuseTests(unittest.TestCase):
    def test_placed_scene_image_keeps_its_chosen_candidate(self):
        st, sc, data = make()
        data["assets"]["scene_s1_p2"] = {"kind": "scene", "name": "autre", "description": "", "prompt": "",
                                          "parent": None, "status": "validated", "validated_candidate": 5,
                                          "candidates": [{"index": i, "file": "f.png"} for i in range(6)]}
        sc["plans"] = [{"id": "p1", "from_line": 0, "characters": [], "asset": "scene_s1_p2", "candidate": 4}]
        status = SC.plan_status(data["assets"], sc, 0)
        self.assertEqual(status["image_index"], 4)
        self.assertFalse(status["ready"])  # le candidat 4 n'est pas celui retenu

    def test_own_generated_scene_image_uses_retained_candidate(self):
        st, sc, data = make()
        data["assets"]["scene_s1_p1"]["validated_candidate"] = 2
        status = SC.plan_status(data["assets"], sc, 0)
        self.assertFalse(status["reused"])
        self.assertEqual(status["image_index"], 2)

    def test_reused_retained_image_is_ready_without_refs(self):
        st, sc, data = make()
        data["assets"]["loc_velvet"]["kind"] = "location"
        sc["plans"] = [{"id": "p1", "from_line": 0, "characters": [], "asset": "loc_velvet"}]
        status = SC.plan_status(data["assets"], sc, 0)
        self.assertTrue(status["reused"])
        self.assertTrue(status["ready"])

    def test_reused_unretained_image_blocks(self):
        st, sc, data = make()
        data["assets"]["char_eve"]["status"] = "draft"
        data["assets"]["char_eve"]["validated_candidate"] = None
        sc["plans"] = [{"id": "p1", "from_line": 0, "characters": [], "asset": "char_eve"}]
        status = SC.plan_status(data["assets"], sc, 0)
        self.assertFalse(status["ready"])


if __name__ == "__main__":
    unittest.main()


class ManualOutfitPriorityTests(unittest.TestCase):
    def test_manual_outfit_replaces_the_scene_outfit_of_the_same_person(self):
        import scenes as SC
        assets = {
            "c": {"kind": "character", "name": "Léa", "status": "validated", "validated_candidate": 0,
                  "descriptor": "young woman", "candidates": [{}]},
            "culotte": {"kind": "outfit", "name": "petite culotte", "parent": "c", "status": "validated",
                        "validated_candidate": 0, "candidates": [{}]},
            "jupe": {"kind": "outfit", "name": "Jupe courte", "parent": "c", "status": "validated",
                     "validated_candidate": 0, "candidates": [{}]},
        }
        sc = {"id": "s2", "title": "T", "location": "", "characters": ["Léa"], "outfits": {"Léa": "petite culotte"},
              "dialogue": [{"speaker": "Léa", "text": "x"}], "plans": []}
        plan = {"id": "p1", "from_line": 0, "asset": "scene_x", "characters": ["Léa"], "refs_extra": ["jupe"]}
        info = SC.plan_refs(assets, sc, plan)
        self.assertIn("jupe", info["refs"])
        self.assertNotIn("culotte", info["refs"])
