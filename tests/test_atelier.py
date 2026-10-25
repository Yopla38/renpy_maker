"""Atelier pas à pas : propositions (faux LLM) et ajouts, dans un dossier temporaire."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import atelier as AT, paths, story as S, assets as A, appsettings


class AtelierTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(paths, "data_root", lambda: self.home),
                        mock.patch.object(appsettings, "load", return_value={})]
        for p in self.patches:
            p.start()
        S.save(S.new_story(title="Test", idea="Une femme au train"))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def fake(self, payload):
        return mock.patch.object(AT.llm, "complete_task", return_value=json.dumps(payload))

    def test_characters_are_proposed_without_existing_ones_and_without_guessing_gender(self):
        payload = {"characters": [
            {"name": "Léa", "description": "x", "descriptor": "young woman"},
            {"name": "Victor", "description": "y", "descriptor": ""},
            {"name": "Julien", "description": "z", "descriptor": "un ami"}]}
        with self.fake(payload):
            out = AT.propose_characters("idée", existing=["Léa"], count=3)
        self.assertEqual([c["name"] for c in out], ["Victor", "Julien"])
        self.assertEqual(out[0]["descriptor"], "")
        self.assertEqual(out[1]["descriptor"], "")  # « un ami » ne dit ni genre ni âge

    def test_adding_a_character_creates_one_asset_only(self):
        a = AT.add_character("Victor", "Un directeur", "adult man")
        b = AT.add_character("victor", "autre", "")
        self.assertEqual(a, b)
        data = A.load()
        self.assertEqual(data["assets"][a]["descriptor"], "adult man")
        self.assertEqual(data["assets"][a]["kind"], "character")

    def test_an_accepted_character_is_listed_even_before_any_scene(self):
        from renpy_maker import facile as FA
        AT.add_character("Sofie", "Une jeune femme.", "young woman")
        names = [c["name"] for c in FA.view()["characters"]]
        self.assertIn("Sofie", names)

    def test_a_new_location_starts_a_new_scene(self):
        sid = AT.start_scene("Le train", "Compartiment du train", ["Léa"], "Léa monte.")
        st = S.load()
        sc = S.all_scenes(st)[0]
        self.assertEqual((sc["id"], sc["location"], sc["characters"]), (sid, "Compartiment du train", ["Léa"]))
        self.assertEqual(st["chapters"][0]["scene_count"], 1)

    def test_a_line_is_proposed_with_an_allowed_speaker_only(self):
        sid = AT.start_scene("T", "Gare", ["Léa"])
        with self.fake({"speaker": "Inconnu", "text": "Bonjour."}):
            line = AT.propose_line(sid)
        self.assertEqual(line, {"speaker": S.NARRATOR, "text": "Bonjour."})

    def test_a_moment_adds_one_line_and_its_image(self):
        sid = AT.start_scene("T", "Gare", ["Léa"])
        pid = AT.add_moment(sid, "Léa", "Bonjour.")
        sc = S.all_scenes(S.load())[0]
        self.assertEqual(len(sc["dialogue"]), 1)
        self.assertEqual(sc["plans"][0]["id"], pid)
        self.assertEqual(sc["plans"][0]["from_line"], 0)
        self.assertEqual(sc["plans"][0]["characters"], ["Léa"])
        self.assertIn(sc["plans"][0]["asset"], A.load()["assets"])

    def test_the_next_moment_comes_after_the_previous_one(self):
        sid = AT.start_scene("T", "Gare", ["Léa"])
        AT.add_moment(sid, "Léa", "Un.")
        p2 = AT.add_moment(sid, S.NARRATOR, "Deux.")
        sc = S.all_scenes(S.load())[0]
        self.assertEqual([p["from_line"] for p in sc["plans"]], [0, 1])
        self.assertEqual(p2, "p2")

    def test_a_location_is_registered_once_so_it_can_get_an_image(self):
        AT.start_scene("T1", "Gare", ["Léa"])
        AT.start_scene("T2", "gare", ["Léa"])
        locations = [a for a in A.load()["assets"].values() if a["kind"] == "location"]
        self.assertEqual([a["name"] for a in locations], ["Gare"])

    def test_outfits_are_proposed_without_repeating_existing_ones(self):
        payload = {"outfits": [{"name": "Robe du soir", "description": "x"}, {"name": "Tailleur", "description": "y"},
                               {"name": "tailleur", "description": "z"}, {"name": "Jean", "description": "w"}]}
        with self.fake(payload):
            out = AT.propose_outfits("Sofie", "une femme", "idée", existing=["Robe du soir"], count=3)
        self.assertEqual([o["name"] for o in out], ["Tailleur", "Jean"])

    def test_a_speaker_not_in_the_scene_is_refused(self):
        sid = AT.start_scene("T", "Gare", ["Léa"])
        with self.assertRaises(ValueError):
            AT.add_moment(sid, "Victor", "Bonsoir.")


if __name__ == "__main__":
    unittest.main()


class DefaultOutfitTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(paths, "data_root", lambda: self.home),
                        mock.patch.object(appsettings, "load", return_value={})]
        for p in self.patches:
            p.start()
        S.save(S.new_story(title="Test", idea="x"))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def test_default_outfit_is_the_starting_reference_of_other_outfits(self):
        from renpy_maker import prompts as PR
        char = AT.add_character("Sofie", "x", "young woman")
        data = A.load()
        A.add_asset(data, "outfit_a", "outfit", "Robe", "", char)
        A.add_asset(data, "outfit_b", "outfit", "Tailleur", "", char)
        for aid in ("outfit_a",):
            data["assets"][aid]["validated_candidate"] = 0
            data["assets"][aid]["candidates"] = [{"index": 0, "file": "x.png"}]
        data["assets"][char]["validated_candidate"] = 0
        data["assets"][char]["candidates"] = [{"index": 0, "file": "c.png"}]
        A.save(data)
        AT.set_default_outfit(char, "outfit_a")
        order = PR.ref_order(A.load()["assets"], "outfit_b")
        self.assertEqual(order[0], "outfit_a")

    def test_a_default_outfit_must_belong_to_the_character(self):
        char = AT.add_character("Sofie", "x", "young woman")
        other = AT.add_character("Clara", "y", "young woman")
        data = A.load()
        A.add_asset(data, "outfit_x", "outfit", "Robe", "", other)
        A.save(data)
        with self.assertRaises(ValueError):
            AT.set_default_outfit(char, "outfit_x")


class OutfitEditTests(unittest.TestCase):
    def setUp(self):
        self.assets = {
            "char_a": {"kind": "character", "name": "A", "descriptor": "young woman", "validated_candidate": 0,
                       "candidates": [{"index": 0, "file": "a.png"}]},
            "outfit_r": {"kind": "outfit", "name": "Robe", "parent": "char_a", "validated_candidate": 0,
                         "candidates": [{"index": 0, "file": "r.png"}]},
            "shoes": {"kind": "object", "name": "Chaussures", "validated_candidate": 0,
                      "candidates": [{"index": 0, "file": "s.png"}]},
        }

    def run_edit(self, mode, text, ref=None):
        from renpy_maker import facile_elements as FE
        data = {"assets": self.assets}
        with mock.patch.object(FE.A, "load", return_value=data), \
                mock.patch.object(FE, "_english", side_effect=lambda t: t.lower()), \
                mock.patch.object(FE, "_card_work") as card:
            FE._edit_work("job", "outfit_r", mode, text, ref or "")
        return card.call_args

    def test_add_with_a_reference_image_names_it(self):
        args = self.run_edit("add", "Chaussures", ref="shoes")
        prompt, extra, store = args[0][2], args[0][3], args[0][4]
        self.assertIn("Add the chaussures to the outfit", prompt)
        self.assertIn("reference image 2", prompt)  # personnage = image 1, chaussures = image 2
        self.assertEqual(extra, ["shoes"])
        self.assertFalse(store)  # le prompt de la tenue n'est pas remplacé

    def test_remove_needs_no_reference(self):
        args = self.run_edit("remove", "Collier")
        self.assertIn("Remove the collier from the outfit", args[0][2])
        self.assertEqual(args[0][3], [])
