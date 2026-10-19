"""Images de scène : références, plans, préparation, prompt (aucun appel réel au LLM)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
        "char_eve": asset("character", "Eve"),
        "char_adrien": asset("character", "Adrien"),
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
        self.assertIn("Eve : défi", user)  # dernière expression du plan
        self.assertIn("- Eve : Bonsoir.", user)

    def test_suggest_with_mocked_llm(self):
        st, sc, data = make()
        with mock.patch.object(llm, "complete", return_value="A candlelit table, two people.") as m:
            text = SC.suggest(st, data, sc, 0)
        self.assertEqual(text, "A candlelit table, two people.")
        self.assertEqual(m.call_args[0][0], st["settings"]["providers"]["text"])

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
        line = SC._people_line(sc["plans"][0], sc, {"labels": ["décor : Le Velvet", "Eve (ajoutée)"]})
        self.assertIn("Eve (image 2)", line)

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
        line = SC._people_line(sc["plans"][0], sc, info)
        self.assertIn("Adrien (image", line)
        self.assertIn("Eve (image", line)

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
