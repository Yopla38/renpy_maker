"""Parcours simple : style → idée → personnages → lieux → histoire → images.

Aucun appel réel : le LLM, Replicate et les fichiers du projet sont remplacés par des faux en mémoire.
"""

import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import assets as A  # noqa: E402
from renpy_maker import llm  # noqa: E402
from renpy_maker import appsettings
from renpy_maker import paths  # noqa: E402
from renpy_maker import facile as FA  # noqa: E402
from renpy_maker import facile_base as FB  # noqa: E402
from renpy_maker import facile_elements as FE  # noqa: E402
from renpy_maker import facile_jobs as FJ  # noqa: E402
from renpy_maker import facile_plans as FP  # noqa: E402
from renpy_maker import facile_settings as FS  # noqa: E402
from renpy_maker import plan as P  # noqa: E402
from renpy_maker import prompts as PR  # noqa: E402
from renpy_maker import scenes as SC  # noqa: E402
from renpy_maker import story as S  # noqa: E402

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
        home = Path(tempfile.mkdtemp())  # réglages de test : jamais le vrai dossier de l'application
        patches = [
            mock.patch.object(paths, "data_root", lambda: home),
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
            mock.patch.object(FJ, "_ensure_token", lambda: None),
            mock.patch.object(FP, "_ask_outfit_change", return_value=False),
            mock.patch.object(FP, "_ask_shots", side_effect=fake_shots),
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
        self.wait(FA.write_dialogues())
        self.assertEqual(job["state"], "done", job.get("error"))
        v = FA.view()
        self.assertEqual(len(v["scenes"]), 2)
        self.assertEqual([c["name"] for c in v["characters"]], ["Léa", "Noé"])
        self.assertEqual([c["name"] for c in v["locations"]], ["Grenier", "Forêt"])
        self.assertTrue(all(sc["dialogue"] for sc in v["scenes"]))
        self.assertFalse(v["done"]["personnages"])  # rien n'est encore dessiné

        for c in v["characters"]:
            self.wait(FE.redo_card(c["aid"]))
        for loc in v["locations"]:
            self.wait(FE.redo_card(loc["aid"]))
        v = FA.view()
        self.assertTrue(v["done"]["personnages"] and v["done"]["lieux"])
        self.assertEqual([o["name"] for o in v["outfits"]], ["Jean et baskets"])
        self.assertFalse(v["done"]["tenues"])
        self.assertTrue(v["outfits"][0]["blocked"] is False)
        for o in v["outfits"]:
            job = self.wait(FE.redo_card(o["aid"]))
            self.assertEqual(job["state"], "done", job.get("error"))
        self.assertTrue(FA.view()["done"]["tenues"])

        for sc in FA.view()["scenes"]:
            self.wait(FP.propose_plans(sc["id"]))
        v = FA.view()
        self.assertTrue(all(sc["plans"] for sc in v["scenes"]))
        self.assertFalse(v["done"]["images"])
        job = self.wait(FP.make_all_plans())
        self.assertEqual(job["state"], "done", job.get("error"))
        v = FA.view()
        self.assertTrue(all(p["image"] for sc in v["scenes"] for p in sc["plans"]))
        self.assertTrue(v["done"]["images"])

    def test_outfit_waits_for_its_character_and_uses_it_as_reference(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        outfit = FA.view()["outfits"][0]
        self.assertTrue(outfit["blocked"])
        with self.assertRaises(ValueError):
            FE.redo_card(outfit["aid"])  # Léa n'a pas encore d'image
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        self.wait(FE.redo_card(lea["aid"]))
        self.wait(FE.redo_card(FA.view()["outfits"][0]["aid"]))
        data = A.load()
        generated = data["assets"][outfit["aid"]]["candidates"][-1]
        self.assertEqual(generated["refs"], [lea["aid"]])

    def test_prompt_can_be_edited_and_is_used_for_redraw(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        self.wait(FE.redo_card(lea["aid"], "Léa, watercolor, red scarf"))
        self.assertEqual(A.load()["assets"][lea["aid"]]["prompt"], "Léa, watercolor, red scarf")
        self.assertEqual(FE.suggest_prompt("card", lea["aid"]), {"prompt": f"prompt de {lea['aid']}"})
        with self.assertRaises(ValueError):
            FE.redo_card(lea["aid"], "   ")
        self.wait(FP.propose_plans("s1"))
        plan = FA.view()["scenes"][0]["plans"][0]
        self.assertEqual(FE.suggest_prompt("plan", plan["aid"]), {"prompt": "scene prompt"})

    def test_scene_image_refuses_missing_anchor(self):
        FA.set_style("dessin_anime")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        self.wait(FP.propose_plans("s1"))
        job = self.wait(FP.make_plan_image("s1", "p1"))
        self.assertEqual(job["state"], "error")
        self.assertIn("Il manque", job["error"])

    def test_style_cannot_change_once_written(self):
        FA.set_style("huile")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        with self.assertRaises(ValueError):
            FA.set_style("aquarelle")

    def test_unknown_scene_is_refused(self):
        FA.set_style("realiste")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        with self.assertRaises(ValueError):
            FA.redo_dialogue("s99")


class LineCandidatesTests(unittest.TestCase):
    def test_candidates_go_from_scene_to_chapter_to_story(self):
        from renpy_maker.facile_base import line_candidates
        st = {"chapters": [
            {"id": "c1", "scenes": [{"id": "s1", "characters": ["Léa", "Victor"]}]},
            {"id": "c2", "scenes": [{"id": "s2", "characters": ["Léa", "Camille"]},
                                    {"id": "s3", "characters": ["Homme"]}]}]}
        got = line_candidates(st, st["chapters"][1]["scenes"][0])
        self.assertEqual([(c["name"], c["group"]) for c in got],
                         [("Léa", "scene"), ("Camille", "scene"), ("Homme", "chapter"), ("Victor", "story")])

    def test_a_character_from_the_story_joins_the_scene_when_tagged(self):
        st = {"chapters": [{"id": "c1", "scenes": [
            {"id": "s1", "characters": ["Léa"], "dialogue": [{"speaker": "Léa", "text": "Bonjour."}]},
            {"id": "s2", "characters": ["Homme"], "dialogue": []}]}]}
        with mock.patch.object(FB, "_characters", return_value=["Léa", "Homme"]), \
                mock.patch.object(FP, "_locations", return_value=[]), \
                mock.patch.object(FP, "_outfits", return_value=[]), \
                mock.patch.object(S, "load", return_value=st), mock.patch.object(S, "save"):
            FP.set_line_tags("s1", 0, ["Léa", "Homme"], "", {})
        self.assertEqual(st["chapters"][0]["scenes"][0]["characters"], ["Léa", "Homme"])


if __name__ == "__main__":
    unittest.main()


class Plans(Setup, unittest.TestCase):
    def test_proposal_is_cleaned_and_limited(self):
        raw = fake_shots(None, None, 5)
        shots = FP.normalize_shots(raw, 2, 5)
        self.assertEqual([x["from_line"] for x in shots], [0, 1])  # ligne hors dialogue écartée
        self.assertEqual(shots[1]["framing"], "close-up")
        self.assertEqual(FP.normalize_shots({"plans": []}, 3, 5)[0]["from_line"], 0)
        self.assertEqual(len(FP.normalize_shots(raw, 2, 1)), 1)

    def test_hand_made_plans_have_no_limit(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        sid = FA.view()["scenes"][0]["id"]
        st = S.load(); target = FB._find_scene(st, sid)
        target["dialogue"] = [{"speaker": "Léa", "text": f"r{i}", "expression": ""} for i in range(10)]
        S.save(st)
        FS.set_max_plans(0)  # autant que l'on veut pour les propositions
        self.assertEqual(FA.view()["max_plans"], 0)
        FP.save_plans(sid, [{"id": None, "from_line": i, "text": f"plan {i}"} for i in range(10)])
        self.assertEqual(len(FB._find_scene(S.load(), sid)["plans"]), 10)

    def test_max_plans_is_editable_and_enforced(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        FS.set_max_plans(2)
        self.assertEqual(FA.view()["max_plans"], 2)
        with self.assertRaises(ValueError):
            FP.save_plans("s1", [{"from_line": 0, "text": "a"}, {"from_line": 1, "text": "b"},
                                 {"from_line": 2, "text": "c"}])
        with self.assertRaises(ValueError):
            FS.set_max_plans(99)

    def test_plan_characters_follow_the_text(self):
        sc = {"characters": ["Léa", "Tom"]}
        self.assertEqual(FB.shot_characters("Gros plan sur Lea, de face", sc, "close-up"), ["Léa"])
        self.assertEqual(FB.shot_characters("Tom et Léa dans la clairière", sc, "medium shot"), ["Léa", "Tom"])
        self.assertEqual(FB.shot_characters("Plan d'ensemble", sc, "wide shot"), ["Léa", "Tom"])
        self.assertEqual(FB.shot_characters("Détail : la carte", sc, "close-up"), [])

    def test_saved_text_sets_the_visible_character(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        FP.save_plans("s1", [{"from_line": 0, "text": "Plan d'ensemble"},
                             {"from_line": 1, "text": "Gros plan sur Léa en riant"}])
        plans = A.load() and S.all_scenes(S.load())[0]["plans"]
        self.assertEqual(plans[1]["characters"], ["Léa"])
        self.assertEqual(plans[0]["characters"], ["Léa", "Noé"])

    def test_chosen_characters_win_over_text_and_must_not_be_empty(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        FP.save_plans("s1", [{"from_line": 0, "text": "Plan", "characters": ["Léa"]},
                             {"from_line": 1, "text": "Gros plan sur Noé", "characters": None}])
        plans = S.all_scenes(S.load())[0]["plans"]
        self.assertEqual(plans[0]["characters"], ["Léa"])
        self.assertEqual(plans[1]["characters"], ["Noé"])  # sans choix explicite, le texte décide
        with self.assertRaises(ValueError):
            FP.save_plans("s1", [{"from_line": 0, "text": "Plan", "characters": []}])

    def test_prompt_does_not_mention_absent_speaker(self):
        from renpy_maker import scenes as SC_
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        FP.save_plans("s1", [{"from_line": 0, "text": "Plan", "characters": ["Léa"]}])
        st = S.load()
        sc = S.all_scenes(st)[0]
        system, user = SC_.build_request(st, A.load()["assets"], sc, 0)
        self.assertNotIn("Tom", user)
        self.assertIn("- Léa :", user)
        self.assertIn("Léa = the young woman", user)

    def test_dropped_image_is_a_copy_in_the_target_plan(self):
        import tempfile
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        self.wait(FP.propose_plans("s1"))
        plans = FA.view()["scenes"][0]["plans"]
        tmp = Path(tempfile.mkdtemp())
        src_file = tmp / "assets" / plans[0]["aid"] / "cand_00.png"
        src_file.parent.mkdir(parents=True)
        src_file.write_bytes(b"png-bytes")
        data = A.load()
        data["assets"][plans[0]["aid"]]["candidates"] = [{"file": f"assets/{plans[0]['aid']}/cand_00.png"}]
        data["assets"][plans[0]["aid"]]["validated_candidate"] = 0
        A.save(data)
        with mock.patch.object(paths, "data_root", lambda: tmp):
            FP.copy_plan_image("s1", plans[1]["id"], plans[0]["aid"], 0)
        after = FA.view()["scenes"][0]["plans"]
        self.assertNotEqual(after[1]["aid"], plans[1]["aid"])
        self.assertEqual(after[0]["aid"], plans[0]["aid"])  # le plan source ne change pas
        self.assertTrue((tmp / "assets" / after[1]["aid"] / "cand_00.png").read_bytes() == b"png-bytes")

    def test_changed_text_clears_stale_prompt_and_framing(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        self.wait(FP.propose_plans("s1"))
        v = FA.view()
        for c in v["characters"] + v["locations"]:
            self.wait(FE.redo_card(c["aid"]))
        for o in FA.view()["outfits"]:
            self.wait(FE.redo_card(o["aid"]))
        plan = FA.view()["scenes"][0]["plans"][0]
        self.wait(FP.make_plan_image("s1", plan["id"]))
        self.assertEqual(A.load()["assets"][plan["aid"]]["prompt"], "scene prompt")
        FP.save_plans("s1", [{"id": plan["id"], "from_line": 0, "text": plan["text"]}])
        self.assertEqual(A.load()["assets"][plan["aid"]]["prompt"], "scene prompt")  # texte inchangé : prompt gardé
        FP.save_plans("s1", [{"id": plan["id"], "from_line": 0, "text": "Vue de dos des deux personnages"}])
        self.assertEqual(A.load()["assets"][plan["aid"]]["prompt"], "")
        self.assertEqual(S.all_scenes(S.load())[0]["plans"][0]["shot"]["framing"], "")

    def test_new_chapter_continues_and_lists_new_elements(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        job = self.wait(FA.add_chapter(3, "Ils trouvent la chapelle"))
        self.assertEqual(job["state"], "done", job.get("error"))
        v = FA.view()
        self.assertEqual(len(v["scenes"]), 5)
        self.assertEqual([c["title"] for c in v["chapters"]], ["La carte", "La suite"])
        self.assertEqual([s["chapter"] for s in v["scenes"]], [1, 1, 2, 2, 2])
        self.assertIn("Chapelle", [c["name"] for c in v["locations"]])
        self.assertFalse(v["done"]["lieux"])   # la chapelle reste à dessiner
        self.assertEqual([bool(s["dialogue"]) for s in v["scenes"]], [True, True, False, False, False])
        self.wait(FA.write_dialogues())  # les répliques des nouveaux chapitres viennent à l'étape Histoire
        self.assertTrue(all(s["dialogue"] for s in FA.view()["scenes"]))

    def test_last_chapter_can_be_removed_but_not_the_only_one(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        with self.assertRaises(ValueError):
            FA.delete_last_chapter()
        self.wait(FA.add_chapter(3))
        FA.delete_last_chapter()
        self.assertEqual(len(FA.view()["scenes"]), 2)

    def test_settings_change_text_provider_and_model_only(self):
        import tempfile
        from renpy_maker import llm as LLM
        tmp = Path(tempfile.mkdtemp()) / "llm_models.yaml"
        with mock.patch.object(paths, "llm_models_file", lambda: tmp):
            FS.save_settings({"text_provider": "openai", "text_model": "mon-modele", "image_provider": "replicate"})
            self.assertEqual(LLM.provider_settings("openai")["model"], "mon-modele")
            self.assertEqual(appsettings.provider("text"), "openai")
            with self.assertRaises(ValueError):
                FS.save_settings({"text_provider": "inconnu"})

    def test_inserted_plan_never_shares_an_image(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        self.wait(FP.propose_plans("s1"))
        before = FA.view()["scenes"][0]["plans"]  # p1 à la réplique 0, p2 à la réplique 1
        # Le plan p2 est gardé et passe en première position ; un nouveau plan prend la place suivante.
        FP.save_plans("s1", [{"id": before[1]["id"], "from_line": 0, "text": before[1]["text"]},
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
        self.wait(FA.write_dialogues())
        self.wait(FP.propose_plans("s1"))
        for c in FA.view()["characters"] + FA.view()["locations"]:
            self.wait(FE.redo_card(c["aid"]))
        for o in FA.view()["outfits"]:
            self.wait(FE.redo_card(o["aid"]))
        v = FA.view()
        plan = v["scenes"][0]["plans"][0]
        self.assertTrue(plan["refs"]["auto"])
        key = plan["refs"]["auto"][-1]["key"]
        FP.save_refs("s1", plan["id"], [key], [])
        after = FA.view()["scenes"][0]["plans"][0]["refs"]["auto"]
        self.assertTrue(next(a for a in after if a["key"] == key)["excluded"])
        lea = next(c for c in v["characters"] if c["name"] == "Léa")
        FP.save_refs("s1", plan["id"], [], [lea["aid"]])
        self.assertIn(lea["aid"], FA.view()["scenes"][0]["plans"][0]["refs"]["extra"])
        with self.assertRaises(ValueError):
            FP.save_refs("s1", plan["id"], [], ["scene_inconnue"])

    def test_continuity_uses_previous_plan_and_can_be_switched_off(self):
        sc = {"characters": ["Léa", "Noé"], "outfits": {"Léa": "Jean"},
              "plans": [{"id": "p1", "from_line": 0, "asset": "a1", "characters": ["Léa", "Noé"], "shot": {}},
                        {"id": "p2", "from_line": 1, "asset": "a2", "characters": ["Léa"], "shot": {}}]}
        assets = {"a1": {"validated_candidate": 0}, "a2": {"validated_candidate": 0}}
        self.assertTrue(FP.apply_continuity(sc, assets))
        p1, p2 = sc["plans"]
        self.assertEqual(p1.get("refs_extra", []), [])            # le premier plan garde la tenue de la scène
        self.assertEqual(p2["refs_extra"], ["a1"])                 # le second s'appuie sur le premier
        self.assertIn("tenue:léa", p2["refs_exclude"])             # sa tenue de référence est mise de côté
        p2["continuity"] = False                                   # « tenue d'origine »
        FP.apply_continuity(sc, assets)
        self.assertEqual(p2["refs_extra"], [])
        self.assertNotIn("tenue:léa", p2["refs_exclude"])

    def test_renaming_a_character_reaches_the_whole_story(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        FE.update_element(lea["aid"], name="Lisa")
        sc = S.all_scenes(S.load())[0]
        self.assertIn("Lisa", sc["characters"])
        self.assertNotIn("Léa", sc["characters"])
        self.assertIn("Lisa", sc["outfits"])
        self.assertTrue(all(l["speaker"] != "Léa" for l in sc["dialogue"]))
        self.assertEqual(A.load()["assets"][lea["aid"]]["name"], "Lisa")

    def test_renaming_an_outfit_updates_the_scene_text(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        outfit = FA.view()["outfits"][0]
        FE.update_element(outfit["aid"], name="Robe d'été")
        self.assertEqual(S.all_scenes(S.load())[0]["outfits"]["Léa"], "Robe d'été")

    def test_designer_refuses_duplicate_names_and_bad_descriptors(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        chars = FA.view()["characters"]
        with self.assertRaises(ValueError):
            FE.update_element(chars[0]["aid"], name=chars[1]["name"])
        with self.assertRaises(ValueError):
            FE.update_element(chars[0]["aid"], descriptor="i can't tell")
        FE.update_element(chars[0]["aid"], descriptor="young woman")
        self.assertEqual(A.load()["assets"][chars[0]["aid"]]["descriptor"], "young woman")

    def test_atelier_creates_an_outfit_worn_in_the_chosen_scenes(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        new = FE.create_outfit(lea["aid"], "Pull vert, jean brut, baskets blanches", "pull vert bouteille", ["s2"])
        self.assertEqual(A.load()["assets"][new["aid"]]["parent"], lea["aid"])
        worn = S.all_scenes(S.load())
        self.assertEqual(worn[1]["outfits"]["Léa"], "Pull vert, jean brut, baskets blanches")
        self.assertEqual(worn[0]["outfits"]["Léa"], "Jean et baskets")  # la scène non choisie ne change pas
        with self.assertRaises(ValueError):
            FE.create_outfit(lea["aid"], "pull vert, jean brut, baskets blanches", "", [])

    def test_character_mode_is_stored_and_checked(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.assertIsNone(FA.view()["character_mode"])
        FE.set_character_mode("designer")
        self.assertEqual(FA.view()["character_mode"], "designer")
        with self.assertRaises(ValueError):
            FE.set_character_mode("hasard")

    def test_identity_suggestion_comes_from_the_story(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        answer = '{"description": "Jeune femme rousse aux yeux verts.", "descriptor": "young woman"}'
        with mock.patch.object(llm, "complete_task", return_value=answer) as m:
            result = FE.suggest_identity(lea["aid"])
        self.assertEqual(result, {"description": "Jeune femme rousse aux yeux verts.", "descriptor": "young woman"})
        self.assertIn("Léa", m.call_args[0][2])

    def test_identity_suggestion_rejects_an_invalid_gender(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        with mock.patch.object(llm, "complete_task", return_value='{"description": "x", "descriptor": "je ne sais pas"}'):
            self.assertEqual(FE.suggest_identity(lea["aid"])["descriptor"], "")

    def test_editing_the_identity_clears_the_stale_prompt(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        A.load()["assets"][lea["aid"]]  # présent
        data = A.load(); data["assets"][lea["aid"]]["prompt"] = "ancien prompt"; A.save(data)
        FE.update_element(lea["aid"], description="rousse, yeux verts")
        self.assertEqual(A.load()["assets"][lea["aid"]]["prompt"], "")

    def test_outfit_is_refused_while_its_character_image_is_stale(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        outfit = next(o for o in FA.view()["outfits"] if o["parent"] == "Léa")
        data = A.load()
        data["assets"][lea["aid"]]["validated_candidate"] = 0
        data["assets"][lea["aid"]]["image_stale"] = True
        A.save(data)
        with self.assertRaises(ValueError):
            FE._refs_for(A.load()["assets"], outfit["aid"])

    def test_changing_the_gender_marks_the_character_image_stale(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        data = A.load(); data["assets"][lea["aid"]]["validated_candidate"] = 0; A.save(data)
        FE.update_element(lea["aid"], descriptor="adult man")
        self.assertTrue(A.load()["assets"][lea["aid"]].get("image_stale"))

    def test_outfit_prompt_naming_the_wrong_person_is_rejected(self):
        assets = {"c": {"kind": "character", "name": "Victor", "descriptor": "old man"},
                  "o": {"kind": "outfit", "name": "Chemise", "parent": "c"}}
        self.assertTrue(FE._wrong_person("Keep the woman from image 1 exactly as she is.", assets, "o"))
        self.assertTrue(FE._wrong_person("Keep the man from image 1. She wears a shirt.", assets, "o"))
        self.assertFalse(FE._wrong_person("Keep the man from image 1 exactly as they are.", assets, "o"))

    def test_element_refs_and_starting_outfit_are_validated(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        lea = next(c for c in FA.view()["characters"] if c["name"] == "Léa")
        first = FE.create_outfit(lea["aid"], "Chemise", "chemise sombre", [])["aid"]
        second = FE.create_outfit(lea["aid"], "Lunettes", "lunettes fines", [])["aid"]
        data = A.load()
        data["assets"][lea["aid"]]["validated_candidate"] = 0
        for aid in (first, second):
            data["assets"][aid]["validated_candidate"] = 0
        A.save(data)
        FE.set_element_refs(second, [], first)
        self.assertEqual(A.load()["assets"][second]["based_on"], first)
        with self.assertRaises(ValueError):
            FE.set_element_refs(second, [], second)          # pas sa propre tenue de départ
        with self.assertRaises(ValueError):
            FE.set_element_refs(lea["aid"], [], first)       # un personnage n'a pas de tenue de départ
        data = A.load(); data["assets"][first]["validated_candidate"] = None; A.save(data)
        with self.assertRaises(ValueError):
            FE.set_element_refs(second, [first])             # image non retenue

    def test_line_tags_are_checked_and_drive_plan_characters(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        sc = FA.view()["scenes"][0]
        sid = sc["id"]
        st = S.load(); target = FB._find_scene(st, sid)
        target["dialogue"] = [{"speaker": "Léa", "text": "a", "expression": ""}, {"speaker": "Léa", "text": "b", "expression": ""}]
        S.save(st)
        with self.assertRaises(ValueError):
            FP.set_line_tags(sid, 0, ["Personne inventée"], "", {})
        FP.set_line_tags(sid, 0, ["Léa"], "", {})
        FP.set_line_tags(sid, 1, ["Léa"], "", {})
        target = FB._find_scene(S.load(), sid)
        self.assertEqual(FP._chars_from_tags(target, 0, 1), ["Léa"])
        self.assertEqual(FP._chars_from_tags(target, 2, 3), [])

    def test_line_tags_are_preselected_by_default(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        sid = FA.view()["scenes"][0]["id"]
        st = S.load(); target = FB._find_scene(st, sid)
        target["characters"] = ["Léa"]
        target["location"] = "Studio"
        target["outfits"] = {"Léa": "Chemise"}
        target["dialogue"] = [{"speaker": "Léa", "text": "a", "expression": ""}, {"speaker": "Narration", "text": "b", "expression": ""}]
        target.pop("line_tags", None)
        S.save(st)
        tags = FA.view()["scenes"][0]["line_tags"]
        self.assertEqual(tags["0"], {"characters": ["Léa"], "location": "Studio", "outfits": {"Léa": "Chemise"}})
        self.assertEqual(tags["1"]["characters"], [])  # la narration n'ajoute personne

    def test_image_only_plan_sits_before_its_line_and_is_played_without_text(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        sid = FA.view()["scenes"][0]["id"]
        st = S.load(); target = FB._find_scene(st, sid)
        target["dialogue"] = [{"speaker": "Léa", "text": "a", "expression": ""}, {"speaker": "Léa", "text": "b", "expression": ""}]
        S.save(st)
        # deux plans sur la réplique 1 : le premier est une image seule, sans réplique
        FP.save_plans(sid, [{"id": None, "from_line": 0, "text": "ouverture"},
                            {"id": None, "from_line": 1, "text": "silence", "pause": True},
                            {"id": None, "from_line": 1, "text": "gros plan"}])
        plans = FB._find_scene(S.load(), sid)["plans"]
        self.assertEqual(sum(1 for p in plans if p.get("pause")), 1)
        with mock.patch.multiple("renpy_maker.facile_base", _url=lambda *a, **k: "img.png"), mock.patch.multiple("renpy_maker.facile_elements", _url=lambda *a, **k: "img.png"), mock.patch.multiple("renpy_maker.facile_plans", _url=lambda *a, **k: "img.png"), mock.patch.multiple("renpy_maker.facile", _url=lambda *a, **k: "img.png"):  # les plans n'ont pas encore d'image
            scene = next(s for s in FA.play_view()["scenes"] if s["id"] == sid)
            self.assertEqual([l.get("pause", False) for l in scene["lines"]], [False, True, False])
            starts = [i["from_line"] for i in scene["images"]]
        self.assertEqual(starts, [0, 1, 2])  # l'image seule est à l'index 1, puis la réplique 1 à l'index 2

    def test_several_image_only_plans_can_follow_each_other(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        sid = FA.view()["scenes"][0]["id"]
        st = S.load(); target = FB._find_scene(st, sid)
        target["dialogue"] = [{"speaker": "Léa", "text": "a", "expression": ""}, {"speaker": "Léa", "text": "b", "expression": ""}]
        S.save(st)
        FP.save_plans(sid, [{"id": None, "from_line": 0, "text": "ouverture"},
                            {"id": None, "from_line": 1, "text": "silence 1", "pause": True},
                            {"id": None, "from_line": 1, "text": "silence 2", "pause": True},
                            {"id": None, "from_line": 1, "text": "réplique"}])
        self.assertEqual(len(FB._find_scene(S.load(), sid)["plans"]), 4)

    def test_image_only_plan_can_follow_the_last_line(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        sid = FA.view()["scenes"][0]["id"]
        st = S.load(); target = FB._find_scene(st, sid)
        target["dialogue"] = [{"speaker": "Léa", "text": "a", "expression": ""}, {"speaker": "Léa", "text": "b", "expression": ""}]
        S.save(st)
        FP.save_plans(sid, [{"id": None, "from_line": 0, "text": "ouverture"},
                            {"id": None, "from_line": 2, "text": "fin", "pause": True}])
        with mock.patch.multiple("renpy_maker.facile_base", _url=lambda *a, **k: "img.png"), mock.patch.multiple("renpy_maker.facile_elements", _url=lambda *a, **k: "img.png"), mock.patch.multiple("renpy_maker.facile_plans", _url=lambda *a, **k: "img.png"), mock.patch.multiple("renpy_maker.facile", _url=lambda *a, **k: "img.png"):
            scene = next(s for s in FA.play_view()["scenes"] if s["id"] == sid)
        self.assertEqual([l.get("pause", False) for l in scene["lines"]], [False, False, True])
        self.assertEqual([i["from_line"] for i in scene["images"]], [0, 2])
        with self.assertRaises(ValueError):  # un plan normal ne peut pas commencer après la fin
            FP.save_plans(sid, [{"id": None, "from_line": 0, "text": "x"}, {"id": None, "from_line": 2, "text": "y"}])

    def test_image_only_plan_can_carry_a_typed_line(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        sid = FA.view()["scenes"][0]["id"]
        st = S.load(); target = FB._find_scene(st, sid)
        target["dialogue"] = [{"speaker": "Léa", "text": "a", "expression": ""}, {"speaker": "Léa", "text": "b", "expression": ""}]
        S.save(st)
        FP.save_plans(sid, [{"id": None, "from_line": 0, "text": "ouverture"},
                            {"id": None, "from_line": 1, "text": "silence", "pause": True,
                             "speaker": "Léa", "speech": "Je ne sais pas."},
                            {"id": None, "from_line": 1, "text": "réplique"}])
        with mock.patch.multiple("renpy_maker.facile_base", _url=lambda *a, **k: "img.png"), mock.patch.multiple("renpy_maker.facile_elements", _url=lambda *a, **k: "img.png"), mock.patch.multiple("renpy_maker.facile_plans", _url=lambda *a, **k: "img.png"), mock.patch.multiple("renpy_maker.facile", _url=lambda *a, **k: "img.png"):
            scene = next(s for s in FA.play_view()["scenes"] if s["id"] == sid)
        self.assertEqual(scene["lines"][1], {"speaker": "Léa", "text": "Je ne sais pas."})
        self.assertFalse(scene["lines"][1].get("pause", False))
        with self.assertRaises(ValueError):
            FP.save_plans(sid, [{"id": None, "from_line": 0, "text": "x", "pause": True, "speaker": "Inconnu", "speech": "a"},
                                {"id": None, "from_line": 1, "text": "y"}])

    def test_existing_line_can_be_corrected_but_not_emptied_or_given_a_stranger(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        sid = FA.view()["scenes"][0]["id"]
        st = S.load(); target = FB._find_scene(st, sid)
        target["dialogue"] = [{"speaker": "Léa", "text": "a", "expression": "joyeuse"}]
        S.save(st)
        FP.update_line(sid, 0, "Narration", "Le vent se lève.")
        line = FB._find_scene(S.load(), sid)["dialogue"][0]
        self.assertEqual((line["speaker"], line["text"], line["expression"]), ("Narration", "Le vent se lève.", "joyeuse"))
        with self.assertRaises(ValueError):
            FP.update_line(sid, 0, "Léa", "   ")
        with self.assertRaises(ValueError):
            FP.update_line(sid, 0, "Personne", "bonjour")

    def test_two_plans_cannot_share_a_line_without_an_image_only_plan(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        sid = FA.view()["scenes"][0]["id"]
        st = S.load(); target = FB._find_scene(st, sid)
        target["dialogue"] = [{"speaker": "Léa", "text": "a", "expression": ""}, {"speaker": "Léa", "text": "b", "expression": ""}]
        S.save(st)
        with self.assertRaises(ValueError):
            FP.save_plans(sid, [{"id": None, "from_line": 0, "text": "x"}, {"id": None, "from_line": 1, "text": "y"},
                                {"id": None, "from_line": 1, "text": "z"}])

    def test_text_edit_keeps_existing_image(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("", "Une histoire", 3, False))
        self.wait(FA.write_dialogues())
        self.wait(FP.propose_plans("s1"))
        first = FA.view()["scenes"][0]["plans"][0]
        FP.save_plans("s1", [{"id": first["id"], "from_line": 0, "text": "Plan large, texte modifié"}])
        plan = FA.view()["scenes"][0]["plans"][0]
        self.assertEqual(plan["text"], "Plan large, texte modifié")
        self.assertEqual(plan["aid"], first["aid"])
        self.assertEqual(len(FA.view()["scenes"][0]["plans"]), 1)
