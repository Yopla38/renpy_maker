"""Parcours simple : style → idée → personnages → lieux → histoire → images.

Aucun appel réel : le LLM, Replicate et les fichiers du projet sont remplacés par des faux en mémoire.
"""

import copy
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assets as A  # noqa: E402
import facile as FA  # noqa: E402
import plan as P  # noqa: E402
import prompts as PR  # noqa: E402
import scenes as SC  # noqa: E402
import story as S  # noqa: E402

CHAPTER = {
    "id": "ch1", "title": "La carte", "summary": "Une carte au trésor.",
    "scenes": [
        {"id": "s1", "title": "Le grenier", "summary": "Léa trouve une carte.", "characters": ["Léa", "Noé"],
         "location": "Grenier", "outfits": {"Léa": "Jean et baskets"}},
        {"id": "s2", "title": "La cascade", "summary": "Elles partent.", "characters": ["Léa"],
         "location": "Forêt", "outfits": {}},
    ],
}


def fake_dialogue(st, sid, provider=None):
    return [{"speaker": "Léa", "text": f"Bonjour dans {sid}.", "expression": "joyeuse"},
            {"speaker": "Narration", "text": "Le vent passe.", "expression": ""}]


def fake_shots(st, sc, max_plans):
    return {"plans": [{"from_line": 1, "framing": "wide shot", "text": "Plan d'ensemble."},
                      {"from_line": 2, "framing": "close-up", "text": "Gros plan sur Léa."},
                      {"from_line": 3, "framing": "close-up", "text": "Gros plan sur Noé."},
                      {"from_line": 9, "framing": "close-up", "text": "Hors limite."}]}


def fake_generate(aid, refs, prompt, seed, backend="replicate", aspect=None, loras=None, on_progress=None, on_submit=None):
    data = A.load()
    a = data["assets"][aid]
    n = len(a["candidates"])
    a["candidates"].append({"file": f"assets/{aid}/cand_{n:02d}.png", "prompt": prompt, "refs": refs})
    A.save(data)
    return n


def fake_chapter(st, n, guidance="", provider=None):
    """Suite de l'histoire : numérotation qui continue, nouveau lieu, nouveau personnage."""
    first = len(S.all_scenes(st)) + 1
    scenes = [{"id": f"s{first + i}", "title": f"Suite {i + 1}", "summary": guidance or "La suite.",
               "characters": ["Léa", "Pierre"], "location": "Chapelle", "outfits": {"Pierre": "Veste grise"}}
              for i in range(n)]
    return {"id": f"ch{len(st['chapters']) + 1}", "title": "La suite", "summary": "Suite.", "scenes": scenes}


class Setup:
    """Préparation commune : faux LLM, faux registre en mémoire."""

    def setUp(self):
        self.story = {"story": S.new_story()}
        self.registry = {"data": {"version": 1, "assets": {}}}
        patches = [
            mock.patch.object(S, "load", side_effect=lambda *a, **k: copy.deepcopy(self.story["story"])),
            mock.patch.object(S, "save", side_effect=lambda st, *a, **k: self.story.update(story=copy.deepcopy(st))),
            mock.patch.object(A, "load", side_effect=lambda *a, **k: copy.deepcopy(self.registry["data"])),
            mock.patch.object(A, "save", side_effect=lambda d, *a, **k: self.registry.update(data=copy.deepcopy(d))),
            mock.patch.object(A, "generate_candidate", side_effect=fake_generate),
            mock.patch.object(P, "generate_chapter", side_effect=lambda st, n, g, p: (
                copy.deepcopy(CHAPTER) if not st["chapters"] else fake_chapter(st, n, g))),
            mock.patch.object(P, "generate_dialogue", side_effect=fake_dialogue),
            mock.patch.object(PR, "suggest", side_effect=lambda st, data, aid, provider=None: f"prompt de {aid}"),
            mock.patch.object(SC, "suggest", side_effect=lambda st, data, sc, k, provider=None: "scene prompt"),
            mock.patch.object(FA, "_ensure_token", lambda: None),
            mock.patch.object(FA, "_ask_outfit_change", return_value=False),
            mock.patch.object(FA, "_ask_shots", side_effect=fake_shots),
            mock.patch.object(PR, "describe_person", side_effect=lambda st, name, desc="", provider=None:
                              "young woman" if name == "Léa" else "young man"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def wait(self, result):
        job_id = result["job"]
        for _ in range(500):
            job = FA.JOBS[job_id]
            if job["state"] != "running":
                return job
            time.sleep(0.01)
        self.fail("tâche trop longue")

    pass


class FacileFlow(Setup, unittest.TestCase):
    def test_full_flow_builds_story_elements_and_scene_images(self):
        with self.assertRaises(ValueError):
            FA.write_story("", "Une histoire", 3, False)  # style pas encore choisi
        FA.set_style("aquarelle")
        self.assertEqual(FA.view()["style"]["name"], "Aquarelle")
        self.assertIn("watercolor", A.reference_style()["positive_suffix"])

        job = self.wait(FA.write_story("", "Léa et Noé trouvent une carte.", 3, False))
        self.assertEqual(job["state"], "done", job.get("error"))
        v = FA.view()
        self.assertEqual(len(v["scenes"]), 2)
        self.assertEqual([c["name"] for c in v["characters"]], ["Léa", "Noé"])
        self.assertEqual([c["name"] for c in v["locations"]], ["Grenier", "Forêt"])
        self.assertTrue(all(sc["dialogue"] for sc in v["scenes"]))
        self.assertFalse(v["done"]["personnages"])  # rien n'est encore dessiné

        for c in v["characters"]:
            self.wait(FA.redo_card(c["aid"]))
        for loc in v["locations"]:
            self.wait(FA.redo_card(loc["aid"]))
        v = FA.view()
        self.assertTrue(v["done"]["personnages"] and v["done"]["lieux"])
        self.assertEqual([o["name"] for o in v["outfits"]], ["Jean et baskets"])
        self.assertFalse(v["done"]["tenues"])
        self.assertTrue(v["outfits"][0]["blocked"] is False)
        for o in v["outfits"]:
            job = self.wait(FA.redo_card(o["aid"]))
            self.assertEqual(job["state"], "done", job.get("error"))
        self.assertTrue(FA.view()["done"]["tenues"])

        for sc in FA.view()["scenes"]:
            self.wait(FA.propose_plans(sc["id"]))
        v = FA.view()
        self.assertTrue(all(sc["plans"] for sc in v["scenes"]))
        self.assertFalse(v["done"]["images"])
        job = self.wait(FA.make_all_plans())
        self.assertEqual(job["state"], "done", job.get("error"))
        v = FA.view()
        self.assertTrue(all(p["image"] for sc in v["scenes"] for p in sc["plans"]))
        self.assertTrue(v["done"]["images"])

    def test_outfit_waits_for_its_character_and_uses_it_as_reference(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        outfit = FA.view()["outfits"][0]
        self.assertTrue(outfit["blocked"])
        with self.assertRaises(ValueError):
            FA.redo_card(outfit["aid"])  # Léa n'a pas encore d'image
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        self.wait(FA.redo_card(lea["aid"]))
        self.wait(FA.redo_card(FA.view()["outfits"][0]["aid"]))
        data = A.load()
        generated = data["assets"][outfit["aid"]]["candidates"][-1]
        self.assertEqual(generated["refs"], [lea["aid"]])

    def test_prompt_can_be_edited_and_is_used_for_redraw(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        self.wait(FA.redo_card(lea["aid"], "Léa, watercolor, red scarf"))
        self.assertEqual(A.load()["assets"][lea["aid"]]["prompt"], "Léa, watercolor, red scarf")
        self.assertEqual(FA.suggest_prompt("card", lea["aid"]), {"prompt": f"prompt de {lea['aid']}"})
        with self.assertRaises(ValueError):
            FA.redo_card(lea["aid"], "   ")
        self.wait(FA.propose_plans("s1"))
        plan = FA.view()["scenes"][0]["plans"][0]
        self.assertEqual(FA.suggest_prompt("plan", plan["aid"]), {"prompt": "scene prompt"})

    def test_scene_image_refuses_missing_anchor(self):
        FA.set_style("dessin_anime")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.propose_plans("s1"))
        job = self.wait(FA.make_plan_image("s1", "p1"))
        self.assertEqual(job["state"], "error")
        self.assertIn("Il manque", job["error"])

    def test_style_cannot_change_once_written(self):
        FA.set_style("huile")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        with self.assertRaises(ValueError):
            FA.set_style("aquarelle")

    def test_unknown_scene_is_refused(self):
        FA.set_style("realiste")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        with self.assertRaises(ValueError):
            FA.redo_dialogue("s99")


if __name__ == "__main__":
    unittest.main()


class Plans(Setup, unittest.TestCase):
    def test_proposal_is_cleaned_and_limited(self):
        raw = fake_shots(None, None, 5)
        shots = FA.normalize_shots(raw, 2, 5)
        self.assertEqual([x["from_line"] for x in shots], [0, 1])  # ligne hors dialogue écartée
        self.assertEqual(shots[1]["framing"], "close-up")
        self.assertEqual(FA.normalize_shots({"plans": []}, 3, 5)[0]["from_line"], 0)
        self.assertEqual(len(FA.normalize_shots(raw, 2, 1)), 1)

    def test_max_plans_is_editable_and_enforced(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        FA.set_max_plans(2)
        self.assertEqual(FA.view()["max_plans"], 2)
        with self.assertRaises(ValueError):
            FA.save_plans("s1", [{"from_line": 0, "text": "a"}, {"from_line": 1, "text": "b"},
                                 {"from_line": 2, "text": "c"}])
        with self.assertRaises(ValueError):
            FA.set_max_plans(99)

    def test_plan_characters_follow_the_text(self):
        sc = {"characters": ["Léa", "Tom"]}
        self.assertEqual(FA.shot_characters("Gros plan sur Lea, de face", sc, "close-up"), ["Léa"])
        self.assertEqual(FA.shot_characters("Tom et Léa dans la clairière", sc, "medium shot"), ["Léa", "Tom"])
        self.assertEqual(FA.shot_characters("Plan d'ensemble", sc, "wide shot"), ["Léa", "Tom"])
        self.assertEqual(FA.shot_characters("Détail : la carte", sc, "close-up"), [])

    def test_saved_text_sets_the_visible_character(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        FA.save_plans("s1", [{"from_line": 0, "text": "Plan d'ensemble"},
                             {"from_line": 1, "text": "Gros plan sur Léa en riant"}])
        plans = A.load() and S.all_scenes(S.load())[0]["plans"]
        self.assertEqual(plans[1]["characters"], ["Léa"])
        self.assertEqual(plans[0]["characters"], ["Léa", "Noé"])

    def test_chosen_characters_win_over_text_and_must_not_be_empty(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        FA.save_plans("s1", [{"from_line": 0, "text": "Plan", "characters": ["Léa"]},
                             {"from_line": 1, "text": "Gros plan sur Noé", "characters": None}])
        plans = S.all_scenes(S.load())[0]["plans"]
        self.assertEqual(plans[0]["characters"], ["Léa"])
        self.assertEqual(plans[1]["characters"], ["Noé"])  # sans choix explicite, le texte décide
        with self.assertRaises(ValueError):
            FA.save_plans("s1", [{"from_line": 0, "text": "Plan", "characters": []}])

    def test_prompt_does_not_mention_absent_speaker(self):
        import scenes as SC_
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        FA.save_plans("s1", [{"from_line": 0, "text": "Plan", "characters": ["Léa"]}])
        st = S.load()
        sc = S.all_scenes(st)[0]
        system, user = SC_.build_request(st, A.load()["assets"], sc, 0)
        self.assertNotIn("Tom", user)
        self.assertIn("- young woman :", user)

    def test_dropped_image_is_a_copy_in_the_target_plan(self):
        import tempfile
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.propose_plans("s1"))
        plans = FA.view()["scenes"][0]["plans"]
        tmp = Path(tempfile.mkdtemp())
        src_file = tmp / "assets" / plans[0]["aid"] / "cand_00.png"
        src_file.parent.mkdir(parents=True)
        src_file.write_bytes(b"png-bytes")
        data = A.load()
        data["assets"][plans[0]["aid"]]["candidates"] = [{"file": f"assets/{plans[0]['aid']}/cand_00.png"}]
        data["assets"][plans[0]["aid"]]["validated_candidate"] = 0
        A.save(data)
        with mock.patch.object(FA, "ROOT", tmp):
            FA.copy_plan_image("s1", plans[1]["id"], plans[0]["aid"], 0)
        after = FA.view()["scenes"][0]["plans"]
        self.assertNotEqual(after[1]["aid"], plans[1]["aid"])
        self.assertEqual(after[0]["aid"], plans[0]["aid"])  # le plan source ne change pas
        self.assertTrue((tmp / "assets" / after[1]["aid"] / "cand_00.png").read_bytes() == b"png-bytes")

    def test_changed_text_clears_stale_prompt_and_framing(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.propose_plans("s1"))
        v = FA.view()
        for c in v["characters"] + v["locations"]:
            self.wait(FA.redo_card(c["aid"]))
        for o in FA.view()["outfits"]:
            self.wait(FA.redo_card(o["aid"]))
        plan = FA.view()["scenes"][0]["plans"][0]
        self.wait(FA.make_plan_image("s1", plan["id"]))
        self.assertEqual(A.load()["assets"][plan["aid"]]["prompt"], "scene prompt")
        FA.save_plans("s1", [{"id": plan["id"], "from_line": 0, "text": plan["text"]}])
        self.assertEqual(A.load()["assets"][plan["aid"]]["prompt"], "scene prompt")  # texte inchangé : prompt gardé
        FA.save_plans("s1", [{"id": plan["id"], "from_line": 0, "text": "Vue de dos des deux personnages"}])
        self.assertEqual(A.load()["assets"][plan["aid"]]["prompt"], "")
        self.assertEqual(S.all_scenes(S.load())[0]["plans"][0]["shot"]["framing"], "")

    def test_new_chapter_continues_and_lists_new_elements(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        job = self.wait(FA.add_chapter(3, "Ils trouvent la chapelle"))
        self.assertEqual(job["state"], "done", job.get("error"))
        v = FA.view()
        self.assertEqual(len(v["scenes"]), 5)
        self.assertEqual([c["title"] for c in v["chapters"]], ["La carte", "La suite"])
        self.assertEqual([s["chapter"] for s in v["scenes"]], [1, 1, 2, 2, 2])
        self.assertIn("Chapelle", [c["name"] for c in v["locations"]])
        self.assertFalse(v["done"]["lieux"])   # la chapelle reste à dessiner
        self.assertTrue(all(s["dialogue"] for s in v["scenes"]))  # répliques écrites automatiquement

    def test_last_chapter_can_be_removed_but_not_the_only_one(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        with self.assertRaises(ValueError):
            FA.delete_last_chapter()
        self.wait(FA.add_chapter(3))
        FA.delete_last_chapter()
        self.assertEqual(len(FA.view()["scenes"]), 2)

    def test_settings_change_text_provider_and_model_only(self):
        import tempfile
        import llm as LLM
        tmp = Path(tempfile.mkdtemp()) / "llm_models.yaml"
        with mock.patch.object(LLM, "MODELS_FILE", tmp):
            FA.save_settings({"text_provider": "openai", "text_model": "mon-modele", "image_provider": "replicate"})
            self.assertEqual(LLM.provider_settings("openai")["model"], "mon-modele")
            self.assertEqual(S.load()["settings"]["providers"]["text"], "openai")
            with self.assertRaises(ValueError):
                FA.save_settings({"text_provider": "inconnu"})

    def test_inserted_plan_never_shares_an_image(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.propose_plans("s1"))
        before = FA.view()["scenes"][0]["plans"]  # p1 à la réplique 0, p2 à la réplique 1
        # Le plan p2 est gardé et passe en première position ; un nouveau plan prend la place suivante.
        FA.save_plans("s1", [{"id": before[1]["id"], "from_line": 0, "text": before[1]["text"]},
                             {"id": None, "from_line": 1, "text": "Nouveau plan"}])
        after = FA.view()["scenes"][0]["plans"]
        ids = [p["id"] for p in after]
        self.assertEqual(len(ids), len(set(ids)))
        assets = [p["aid"] for p in after]
        self.assertEqual(len(assets), len(set(assets)))
        self.assertEqual(after[0]["aid"], before[1]["aid"])  # le plan gardé garde son image

    def test_fine_tuning_excludes_and_adds_references(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.propose_plans("s1"))
        for c in FA.view()["characters"] + FA.view()["locations"]:
            self.wait(FA.redo_card(c["aid"]))
        for o in FA.view()["outfits"]:
            self.wait(FA.redo_card(o["aid"]))
        v = FA.view()
        plan = v["scenes"][0]["plans"][0]
        self.assertTrue(plan["refs"]["auto"])
        key = plan["refs"]["auto"][-1]["key"]
        FA.save_refs("s1", plan["id"], [key], [])
        after = FA.view()["scenes"][0]["plans"][0]["refs"]["auto"]
        self.assertTrue(next(a for a in after if a["key"] == key)["excluded"])
        lea = next(c for c in v["characters"] if c["name"] == "Léa")
        FA.save_refs("s1", plan["id"], [], [lea["aid"]])
        self.assertIn(lea["aid"], FA.view()["scenes"][0]["plans"][0]["refs"]["extra"])
        with self.assertRaises(ValueError):
            FA.save_refs("s1", plan["id"], [], ["scene_inconnue"])

    def test_continuity_uses_previous_plan_and_can_be_switched_off(self):
        sc = {"characters": ["Léa", "Noé"], "outfits": {"Léa": "Jean"},
              "plans": [{"id": "p1", "from_line": 0, "asset": "a1", "characters": ["Léa", "Noé"], "shot": {}},
                        {"id": "p2", "from_line": 1, "asset": "a2", "characters": ["Léa"], "shot": {}}]}
        assets = {"a1": {"validated_candidate": 0}, "a2": {"validated_candidate": 0}}
        self.assertTrue(FA.apply_continuity(sc, assets))
        p1, p2 = sc["plans"]
        self.assertEqual(p1.get("refs_extra", []), [])            # le premier plan garde la tenue de la scène
        self.assertEqual(p2["refs_extra"], ["a1"])                 # le second s'appuie sur le premier
        self.assertIn("tenue:léa", p2["refs_exclude"])             # sa tenue de référence est mise de côté
        p2["continuity"] = False                                   # « tenue d'origine »
        FA.apply_continuity(sc, assets)
        self.assertEqual(p2["refs_extra"], [])
        self.assertNotIn("tenue:léa", p2["refs_exclude"])

    def test_text_edit_keeps_existing_image(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.propose_plans("s1"))
        first = FA.view()["scenes"][0]["plans"][0]
        FA.save_plans("s1", [{"id": first["id"], "from_line": 0, "text": "Plan large, texte modifié"}])
        plan = FA.view()["scenes"][0]["plans"][0]
        self.assertEqual(plan["text"], "Plan large, texte modifié")
        self.assertEqual(plan["aid"], first["aid"])
        self.assertEqual(len(FA.view()["scenes"][0]["plans"]), 1)
