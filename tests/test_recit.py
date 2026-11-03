"""Mode récit : propositions du conteur (faux LLM), moments, choix, bifurcations, rencontres de lignes,
et consignes du metteur en scène. Tout se passe dans un dossier temporaire."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import appsettings, paths
from renpy_maker import assets as A
from renpy_maker import atelier as AT
from renpy_maker import recit as RC
from renpy_maker import story as S
from renpy_maker import story_graph as SG


def moment(voix="", speaker="", text="", present=None, location=None, keep=False, shot="", visible=None,
           framing="medium shot", viewpoint="", choices=None):
    return {"voix_off": voix, "speaker": speaker, "text": text, "present": present or [], "location": location,
            "image": {"keep": keep, "shot": shot, "framing": framing, "viewpoint": viewpoint,
                      "visible": visible or []},
            "choices": choices or []}


class RecitBase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(paths, "data_root", lambda: self.home),
                        mock.patch.object(appsettings, "load", return_value={})]
        for p in self.patches:
            p.start()
        st = S.new_story(title="Test", idea="Une enquête dans un train de nuit")
        st["settings"]["style"] = "aquarelle"
        S.save(st)
        AT.add_character("Léa", "Une détective", "young woman")
        AT.add_character("Tom", "Le contrôleur", "adult man")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def fake(self, payload):
        return mock.patch.object(RC.llm, "complete_task", return_value=json.dumps(payload))

    def start(self):
        """Premier moment : le compartiment, Léa parle, nouvelle image."""
        out = RC.commit_moment(None, moment(voix="Le train file dans la nuit.", speaker="Léa", text="Bonsoir.",
                                            present=["Léa"], location={"name": "Compartiment", "description": "x"},
                                            shot="Plan large du compartiment", visible=["Léa"]))
        return out["scene"]

    def scene(self, sid):
        return next(sc for sc in S.all_scenes(S.load()) if sc["id"] == sid)


class ProposalTests(RecitBase):
    def test_the_first_proposal_needs_a_place(self):
        with self.fake({"voix_off": "Il pleut.", "speaker": "", "text": "", "location": None}), \
                self.assertRaises(ValueError):
            RC.propose_next(None)

    def test_a_proposal_keeps_only_known_names_and_clean_choices(self):
        sid = self.start()
        payload = {"voix_off": "", "speaker": "Inconnu", "text": "Qui est là ?", "present": ["Léa", "Zorro"],
                   "location": None, "image": {"keep": True, "framing": "très près", "visible": ["Zorro"]},
                   "choices": ["Ouvrir la porte", "ouvrir la porte", "Attendre " + "longtemps " * 10]}
        with self.fake(payload):
            m = RC.propose_next(sid)
        self.assertEqual(m["speaker"], S.NARRATOR)        # locuteur inconnu : la narration le dit
        self.assertEqual(m["present"], ["Léa"])
        self.assertTrue(m["image"]["keep"])               # même lieu, une image est déjà à l'écran
        self.assertEqual(m["image"]["framing"], "medium shot")
        self.assertEqual(m["choices"][0], "Ouvrir la porte")
        self.assertEqual(len(m["choices"]), 2)
        self.assertLessEqual(len(m["choices"][1]), SG.MAX_LABEL)

    def test_a_new_place_never_keeps_the_previous_image(self):
        sid = self.start()
        with self.fake({"voix_off": "Elle descend.", "location": {"name": "Quai", "description": "y"},
                        "image": {"keep": True}}):
            m = RC.propose_next(sid)
        self.assertEqual(m["location"]["name"], "Quai")
        self.assertFalse(m["image"]["keep"])

    def test_the_storyteller_reads_what_happened_and_the_player_directions(self):
        sid = self.start()
        with S.LOCK:
            st = S.load()
            RC._remember(st, sid, "Tom cache quelque chose")
            S.save(st)
        with mock.patch.object(RC.llm, "complete_task", return_value=json.dumps({"voix_off": "x"})) as m:
            RC.propose_next(sid, "Tom entre")
        user = m.call_args[0][2]
        self.assertIn("Léa : Bonsoir.", user)
        self.assertIn("Tom cache quelque chose", user)
        self.assertIn("Tom entre", user)


class MomentTests(RecitBase):
    def test_the_first_moment_opens_a_scene_with_its_lines_and_image(self):
        sid = self.start()
        sc = self.scene(sid)
        self.assertEqual(sc["location"], "Compartiment")
        self.assertEqual([l["speaker"] for l in sc["dialogue"]], [S.NARRATOR, "Léa"])
        self.assertEqual(len(sc["plans"]), 1)
        self.assertEqual(sc["plans"][0]["from_line"], 0)
        self.assertEqual(sc["plans"][0]["shot"]["note"], "Plan large du compartiment")
        self.assertTrue(sc["open"])
        self.assertEqual(S.load()["recit"]["current"], sid)
        assets = A.load()["assets"]
        self.assertIn(sc["plans"][0]["asset"], assets)
        self.assertTrue(any(a["kind"] == "location" and a["name"] == "Compartiment" for a in assets.values()))

    def test_keeping_the_image_adds_lines_without_a_new_drawing(self):
        sid = self.start()
        out = RC.commit_moment(sid, moment(speaker="Tom", text="Billet, s'il vous plaît.", present=["Léa", "Tom"],
                                           keep=True))
        sc = self.scene(sid)
        self.assertFalse(out["draw"])
        self.assertEqual(len(sc["plans"]), 1)
        self.assertEqual(len(sc["dialogue"]), 3)
        self.assertIn("Tom", sc["characters"])            # Tom arrive dans la scène

    def test_a_new_image_starts_at_the_first_new_line(self):
        sid = self.start()
        RC.commit_moment(sid, moment(voix="Tom entre.", speaker="Tom", text="Bonsoir.", present=["Léa", "Tom"],
                                     shot="Tom dans l'encadrement", visible=["Tom"], framing="close-up"))
        plans = self.scene(sid)["plans"]
        self.assertEqual([p["from_line"] for p in plans], [0, 2])
        self.assertEqual(plans[1]["characters"], ["Tom"])
        self.assertEqual(plans[1]["shot"]["framing"], "close-up")

    def test_a_new_place_continues_the_line_in_a_new_scene(self):
        sid = self.start()
        out = RC.commit_moment(sid, moment(voix="Sur le quai.", present=["Léa"],
                                           location={"name": "Quai", "description": "Un quai."}))
        first, second = self.scene(sid), self.scene(out["scene"])
        self.assertEqual(first["next"], second["id"])
        self.assertFalse(first["open"])
        self.assertTrue(second["open"])
        g = SG.build(S.load())
        self.assertEqual(g["problems"], [])

    def test_undo_removes_the_last_moment_and_the_scene_it_opened(self):
        sid = self.start()
        out = RC.commit_moment(sid, moment(voix="Sur le quai.", present=["Léa"], location={"name": "Quai"}))
        RC.undo_last()
        ids = [sc["id"] for sc in S.all_scenes(S.load())]
        self.assertNotIn(out["scene"], ids)
        self.assertTrue(self.scene(sid)["open"])
        self.assertIsNone(self.scene(sid).get("next"))
        with self.assertRaises(ValueError):
            RC.undo_last()                                 # une seule annulation

    def test_a_closed_line_cannot_receive_a_moment(self):
        sid = self.start()
        RC.finish(sid)
        with self.assertRaises(ValueError):
            RC.commit_moment(sid, moment(voix="Encore."))


class ChoiceTests(RecitBase):
    def test_a_choice_opens_one_line_per_option_and_lives_the_picked_one(self):
        sid = self.start()
        out = RC.choose(sid, ["Fouiller la valise", "Interroger Tom"], 1)
        src = self.scene(sid)
        self.assertEqual([c["label"] for c in src["choices"]], ["Fouiller la valise", "Interroger Tom"])
        self.assertFalse(src["open"])
        self.assertEqual(S.load()["recit"]["current"], out["created"][1])
        st = S.load()
        g = SG.build(st)
        self.assertEqual(g["problems"], [])                 # deux lignes ouvertes : à vivre, pas des impasses
        self.assertTrue(all(n["open"] for n in g["nodes"] if n["id"] in out["created"]))
        path = RC.path_to(st, out["created"][1])
        self.assertEqual([p["scene"] for p in path], [sid, out["created"][1]])
        self.assertEqual(path[1]["label"], "Interroger Tom")

    def test_choices_proposed_with_a_moment_wait_for_the_player(self):
        sid = self.start()
        RC.commit_moment(sid, moment(voix="Un bruit.", keep=True, choices=["Ouvrir", "Attendre"]))
        self.assertEqual(RC.view()["recit"]["pending"], {"scene": sid, "options": ["Ouvrir", "Attendre"]})
        RC.set_options({"drop_pending": True})                # « Pas maintenant »
        self.assertIsNone(RC.view()["recit"]["pending"])
        RC.commit_moment(sid, moment(voix="Encore.", keep=True, choices=["A", "B"]))
        RC.choose(sid, ["A", "B"], 0)
        self.assertIsNone(RC.view()["recit"]["pending"])      # le choix est fait

    def test_the_first_moment_after_a_choice_can_keep_the_image(self):
        sid = self.start()
        branch = RC.choose(sid, ["A", "B"], 0)["scene"]
        RC.commit_moment(branch, moment(voix="Elle hésite.", keep=True))
        sc = self.scene(branch)
        source_plan = self.scene(sid)["plans"][0]
        self.assertEqual(sc["plans"][0]["asset"], source_plan["asset"])   # même image, rien à dessiner
        self.assertTrue(sc["plans"][0]["kept"])

    def test_living_differently_after_a_past_line_keeps_the_old_path_as_an_option(self):
        sid = self.start()
        RC.commit_moment(sid, moment(speaker="Tom", text="Billet ?", present=["Léa", "Tom"], keep=True))
        out = RC.branch_after(sid, 0, "Léa se tait")        # après la voix off, avant « Bonsoir »
        src = self.scene(sid)
        tail = self.scene(src["choices"][0]["target"])
        self.assertEqual(len(src["dialogue"]), 1)
        self.assertEqual([l["text"] for l in tail["dialogue"]], ["Bonsoir.", "Billet ?"])
        self.assertEqual(tail["plans"][0]["from_line"], 0)  # l'image en cours continue dans la suite
        self.assertEqual(tail["plans"][0]["asset"], src["plans"][0]["asset"])
        self.assertTrue(tail["open"])                       # la suite attendait toujours la sienne
        new = self.scene(out["scene"])
        self.assertEqual(new["return_to"], tail["id"])
        self.assertEqual(S.load()["recit"]["current"], new["id"])
        self.assertEqual(SG.build(S.load())["problems"], [])

    def test_at_the_end_of_an_open_line_one_just_says_what_happens(self):
        sid = self.start()
        with self.assertRaises(ValueError):
            RC.branch_after(sid, 1, "Autre chose")

    def test_a_detour_comes_back_to_the_main_line(self):
        sid = self.start()
        RC.commit_moment(sid, moment(speaker="Tom", text="Billet ?", present=["Léa", "Tom"], keep=True))
        detour = RC.branch_after(sid, 0, "Léa rêve")["scene"]
        RC.commit_moment(detour, moment(voix="Un rêve étrange.", keep=True))
        back_to = self.scene(detour)["return_to"]
        RC.rejoin(detour, back_to)
        st = S.load()
        self.assertEqual(self.scene(detour)["next"], back_to)
        self.assertEqual(st["recit"]["current"], back_to)   # la suite commune attend sa suite
        path = RC.path_to(st, back_to)
        self.assertIn(detour, [p["scene"] for p in path])  # le joueur arrive par le détour

    def test_two_lines_can_meet_at_a_moment_of_another_scene(self):
        sid = self.start()
        RC.commit_moment(sid, moment(speaker="Tom", text="Billet ?", present=["Léa", "Tom"], keep=True))
        a, b = RC.choose(sid, ["A", "B"], 0)["created"]
        RC.commit_moment(a, moment(voix="Un.", keep=True))
        RC.commit_moment(a, moment(voix="Deux.", shot="Autre plan"))
        RC.commit_moment(b, moment(voix="Trois.", keep=True))
        RC.rejoin(b, a, 1)                                    # B rejoint A à « Deux. »
        joined = self.scene(b)["next"]
        self.assertEqual([l["text"] for l in self.scene(joined)["dialogue"]], ["Deux."])
        self.assertEqual(self.scene(a)["next"], joined)
        self.assertEqual(SG.build(S.load())["problems"], [])

    def test_an_ended_line_can_be_reopened(self):
        sid = self.start()
        RC.finish(sid)
        self.assertTrue(self.scene(sid)["ending"])
        RC.reopen(sid)
        self.assertTrue(RC.is_open(S.load(), self.scene(sid)))


class DrawTests(RecitBase):
    def test_missing_images_are_drawn_in_order_character_before_outfit(self):
        sid = self.start()
        data = A.load()
        lea = next(k for k, a in data["assets"].items() if a["name"] == "Léa")
        A.add_asset(data, "outfit_robe", "outfit", "Robe", "", lea)
        A.save(data)
        RC.set_outfit(sid, "Léa", "Robe")
        sc = self.scene(sid)
        todo = RC.missing_refs(A.load()["assets"], sc, sc["plans"][0])
        self.assertLess(todo.index(lea), todo.index("outfit_robe"))
        self.assertTrue(any(A.load()["assets"][a]["kind"] == "location" for a in todo))

    def test_redrawing_a_kept_image_gives_the_moment_its_own_image(self):
        sid = self.start()
        branch = RC.choose(sid, ["A", "B"], 0)["scene"]
        RC.commit_moment(branch, moment(voix="Elle hésite.", keep=True))
        pid = self.scene(branch)["plans"][0]["id"]
        RC._own_image(branch, pid)
        plan = self.scene(branch)["plans"][0]
        self.assertNotEqual(plan["asset"], self.scene(sid)["plans"][0]["asset"])
        self.assertNotIn("kept", plan)
        self.assertIn(plan["asset"], A.load()["assets"])

    def test_adjusting_a_kept_image_by_hand_never_touches_the_earlier_moment(self):
        sid = self.start()
        source = self.scene(sid)["plans"][0]
        data = A.load()
        data["assets"][source["asset"]]["prompt"] = "wide shot of a train compartment"
        A.save(data)
        branch = RC.choose(sid, ["A", "B"], 0)["scene"]
        RC.commit_moment(branch, moment(voix="Elle hésite.", keep=True))
        pid = self.scene(branch)["plans"][0]["id"]
        out = RC.set_shot(branch, pid, note="Léa assise près de la fenêtre", framing="close-up")
        self.assertTrue(out["changed"])
        self.assertEqual(A.load()["assets"][source["asset"]]["prompt"], "wide shot of a train compartment")
        self.assertEqual(self.scene(sid)["plans"][0]["shot"]["note"], "Plan large du compartiment")
        shot = self.scene(branch)["plans"][0]["shot"]
        self.assertEqual((shot["note"], shot["framing"]), ("Léa assise près de la fenêtre", "close-up"))

    def test_adjusting_its_own_image_resets_its_prompt(self):
        sid = self.start()
        plan = self.scene(sid)["plans"][0]
        data = A.load()
        data["assets"][plan["asset"]]["prompt"] = "old prompt"
        A.save(data)
        RC.set_shot(sid, plan["id"], characters=["Léa"])          # rien ne change : le prompt reste
        self.assertEqual(A.load()["assets"][plan["asset"]]["prompt"], "old prompt")
        RC.set_shot(sid, plan["id"], note="Léa debout dans le couloir")
        self.assertEqual(A.load()["assets"][plan["asset"]]["prompt"], "")
        with self.assertRaises(ValueError):
            RC.set_shot(sid, plan["id"], characters=["Personne"])
        with self.assertRaises(ValueError):
            RC.set_shot(sid, plan["id"], viewpoint="inconnu")


class DirectorTests(RecitBase):
    def test_a_spoken_direction_rewrites_the_proposal_and_changes_an_outfit(self):
        sid = self.start()
        data = A.load()
        lea = next(k for k, a in data["assets"].items() if a["name"] == "Léa")
        A.add_asset(data, "outfit_robe", "outfit", "Robe rouge", "", lea)
        A.save(data)
        proposal = RC.normalize_moment(moment(voix="Elle attend.", present=["Léa"], keep=True),
                                       S.load(), A.load()["assets"], sid)
        answer = {**moment(voix="Elle attend, assise.", present=["Léa"], keep=True, shot="Léa assise"),
                  "outfits": {"lea": "robe ROUGE"}, "reply": "Léa est assise, en robe rouge.", "cap": "Il neige"}
        with self.fake(answer):
            out = RC.direct(sid, "elle est assise, avec sa robe rouge", proposal=proposal)
        m = out["proposal"]
        self.assertEqual(m["outfits"], {"Léa": "Robe rouge"})
        self.assertFalse(m["image"]["keep"])                 # la tenue change : nouvelle image
        self.assertIn("Robe rouge", m["image"]["shot"])
        self.assertIn("Il neige", self.scene(sid)["directions"])
        RC.commit_moment(sid, m)
        self.assertEqual(self.scene(sid)["outfits"]["Léa"], "Robe rouge")

    def test_a_requested_outfit_that_does_not_exist_is_added_to_the_wardrobe(self):
        sid = self.start()
        proposal = RC.normalize_moment(moment(voix="Elle attend.", present=["Léa"], keep=True),
                                       S.load(), A.load()["assets"], sid)
        answer = {**moment(voix="Elle attend.", present=["Léa"]),
                  "new_outfit": {"character": "Léa", "name": "Imperméable", "description": "Un trench beige"}}
        with self.fake(answer):
            out = RC.direct(sid, "mets-lui un imperméable", proposal=proposal)
        self.assertEqual(out["proposal"]["outfits"], {"Léa": "Imperméable"})
        self.assertTrue(any(a["kind"] == "outfit" and a["name"] == "Imperméable" for a in A.load()["assets"].values()))

    def test_a_direction_on_an_image_changes_its_description_and_rewrites_its_prompt(self):
        sid = self.start()
        plan = self.scene(sid)["plans"][0]
        data = A.load()
        data["assets"][plan["asset"]]["prompt"] = "The woman from image 2 stands in the compartment."
        A.save(data)
        answer = {"reply": "Elle est assise.", "shot": "Léa assise près de la fenêtre",
                  "prompt": "The woman from image 2 sits by the window.", "lines": [{"n": 2, "text": "Bonsoir..."}]}
        with self.fake(answer):
            out = RC.direct(sid, "elle doit être assise", pid=plan["id"])
        self.assertTrue(out["redraw"])
        sc = self.scene(sid)
        self.assertEqual(sc["plans"][0]["shot"]["note"], "Léa assise près de la fenêtre")
        self.assertEqual(sc["dialogue"][1]["text"], "Bonsoir...")
        self.assertTrue(A.load()["assets"][plan["asset"]]["prompt"].startswith("The woman from image 2 sits"))

    def test_without_anything_on_screen_a_direction_asks_for_the_next_moment(self):
        sid = self.start()
        with self.fake({"voix_off": "Tom arrive en courant.", "present": ["Léa", "Tom"]}) as m:
            out = RC.direct(sid, "Tom arrive en courant")
        self.assertEqual(out["proposal"]["voix_off"], "Tom arrive en courant.")
        self.assertIn("Tom arrive en courant", m.call_args[0][2])


class GraphTests(unittest.TestCase):
    def test_an_open_line_has_no_implicit_successor_and_is_not_a_dead_end(self):
        st = {"chapters": [{"id": "c1", "scenes": [
            {"id": "a", "title": "A", "choices": [{"target": "b", "label": "1"}, {"target": "c", "label": "2"}]},
            {"id": "b", "title": "B", "open": True},
            {"id": "c", "title": "C", "open": True}]}]}
        g = SG.build(st)
        self.assertEqual([e["kind"] for e in g["edges"]], ["choice", "choice"])
        self.assertEqual(g["problems"], [])
        self.assertTrue(all(n["open"] for n in g["nodes"] if n["id"] in ("b", "c")))


if __name__ == "__main__":
    unittest.main()
