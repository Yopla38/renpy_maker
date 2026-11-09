"""Carte de l'histoire : routes, scènes inatteignables et impasses, déduites des choix."""

import unittest

from renpy_maker import story_graph as G


def scene(sid, choices=(), ending=False, dialogue=True):
    return {"id": sid, "title": sid.upper(), "choices": [{"target": t, "label": lab} for t, lab in choices],
            "ending": ending, "dialogue": [{"speaker": "Narration", "text": "x"}] if dialogue else []}


def story(*scenes):
    return {"chapters": [{"id": "c1", "scenes": list(scenes)}]}


class StoryGraphTests(unittest.TestCase):
    def test_linear_story_is_one_route_without_choices(self):
        g = G.build(story(scene("a"), scene("b"), scene("c", ending=True)))
        self.assertEqual([e["kind"] for e in g["edges"]], ["next", "next"])
        self.assertEqual(g["routes"], [{"path": ["a", "b", "c"], "end": "c", "ending": True}])
        self.assertEqual(g["problems"], [])

    def test_a_crossroads_gives_one_route_per_branch(self):
        g = G.build(story(
            scene("a", choices=[("b", "Gauche"), ("c", "Droite")]),
            scene("b", ending=True), scene("c", ending=True)))
        self.assertEqual(sorted(r["path"][-1] for r in g["routes"]), ["b", "c"])
        self.assertTrue(all(r["ending"] for r in g["routes"]))
        self.assertEqual({e["label"] for e in g["edges"]}, {"Gauche", "Droite"})

    def test_unreachable_scene_is_reported(self):
        g = G.build(story(scene("a", ending=True), scene("b", ending=True)))
        self.assertFalse(next(n for n in g["nodes"] if n["id"] == "b")["reachable"])
        self.assertTrue(any("inatteignable" in p and "B" in p for p in g["problems"]))

    def test_last_scene_without_choice_is_the_end(self):
        g = G.build(story(scene("a"), scene("b")))
        self.assertTrue(next(n for n in g["nodes"] if n["id"] == "b")["ending"])
        self.assertEqual(g["problems"], [])

    def test_choice_to_a_missing_scene_is_a_dead_end(self):
        g = G.build(story(scene("a", choices=[("zzz", "Suivre")]), scene("b", ending=True)))
        self.assertTrue(any("Impasse" in p and "A" in p for p in g["problems"]))
        self.assertEqual(g["routes"][0]["ending"], False)

    def test_loops_do_not_hang(self):
        g = G.build(story(scene("a", choices=[("b", "Aller")]),
                          scene("b", choices=[("a", "Revenir"), ("c", "Partir")]), scene("c", ending=True)))
        self.assertIn(["a", "b", "c"], [r["path"] for r in g["routes"]])

    def test_empty_story(self):
        g = G.build({"chapters": []})
        self.assertIsNone(g["start"])
        self.assertEqual(g["routes"], [])


if __name__ == "__main__":
    unittest.main()


class SetChoicesTests(unittest.TestCase):
    def setUp(self):
        self.st = story(scene("s1"), scene("s2"), scene("s3", ending=True))
        self.st["chapters"][0]["scene_count"] = 3

    def test_choice_to_an_existing_scene(self):
        G.set_choices(self.st, "s1", [{"label": "Droite", "target": "s3"}])
        self.assertEqual(self.st["chapters"][0]["scenes"][0]["choices"], [{"target": "s3", "label": "Droite"}])
        self.assertIs(self.st["map_validated"], False)  # la carte a changé : à revalider

    def test_new_scene_is_created_right_after_the_source(self):
        created = G.set_choices(self.st, "s1", [{"label": "Vers la forêt", "new": {"title": "La forêt", "summary": "x"}}])
        ids = [s["id"] for s in self.st["chapters"][0]["scenes"]]
        self.assertEqual(ids, ["s1", created[0], "s2", "s3"])
        self.assertEqual(self.st["chapters"][0]["scene_count"], 4)

    def test_several_new_scenes_keep_their_order(self):
        created = G.set_choices(self.st, "s1", [{"label": "A", "new": {"title": "A"}}, {"label": "B", "new": {"title": "B"}}])
        ids = [s["id"] for s in self.st["chapters"][0]["scenes"]]
        self.assertEqual(ids[1:3], created)

    def test_refused_cases(self):
        with self.assertRaises(ValueError):
            G.set_choices(self.st, "s1", [{"label": "", "target": "s2"}])
        with self.assertRaises(ValueError):
            G.set_choices(self.st, "s1", [{"label": "Retour", "target": "s1"}])
        with self.assertRaises(ValueError):
            G.set_choices(self.st, "s1", [{"label": "X", "target": "nope"}])
        with self.assertRaises(ValueError):
            G.set_choices(self.st, "s1", [{"label": "X", "target": "s2"}, {"label": "Y", "target": "s2"}])
        with self.assertRaises(ValueError):
            G.set_choices(self.st, "s1", [{"label": str(i), "target": "s2"} for i in range(5)])

    def test_empty_list_restores_the_automatic_passage(self):
        G.set_choices(self.st, "s1", [{"label": "Droite", "target": "s3"}])
        G.set_choices(self.st, "s1", [])
        g = G.build(self.st)
        self.assertIn(("s1", "s2", "next"), [(e["source"], e["target"], e["kind"]) for e in g["edges"]])


class StartRouteTests(unittest.TestCase):
    def setUp(self):
        self.st = {"chapters": [{"id": "c1", "scene_count": 1, "scenes": [{
            "id": "s1", "title": "Devant", "summary": "", "characters": ["Léa"], "location": "Studio",
            "outfits": {}, "choices": [], "ending": False, "locked": False,
            "dialogue": [{"speaker": f"L{i}", "text": str(i)} for i in range(4)],
            "plans": [{"id": "p1", "from_line": 0, "asset": "a1"}, {"id": "p2", "from_line": 1, "asset": "a2"},
                      {"id": "p3", "from_line": 2, "asset": "a3"}, {"id": "p4", "from_line": 3, "asset": "a4",
                                                                    "pause": True}],
            "line_tags": {"0": {"characters": ["Léa"]}, "2": {"characters": ["Léa"]}, "3": {}},
        }]}]}

    def test_the_tail_moves_into_the_route_and_the_source_stops_at_the_choice(self):
        new_id = G.start_route(self.st, "s1", "p3", "Accepter", "Accepter")
        src, route = self.st["chapters"][0]["scenes"]
        self.assertEqual([l["text"] for l in src["dialogue"]], ["0", "1"])
        self.assertEqual([p["id"] for p in src["plans"]], ["p1", "p2"])
        self.assertEqual(src["choices"], [{"target": new_id, "label": "Accepter"}])
        self.assertEqual([l["text"] for l in route["dialogue"]], ["2", "3"])
        self.assertEqual([(p["id"], p["from_line"]) for p in route["plans"]], [("p3", 0), ("p4", 1)])
        self.assertEqual(sorted(route["line_tags"]), ["0", "1"])
        self.assertEqual(sorted(src["line_tags"]), ["0"])

    def test_scene_choices_follow_the_route(self):
        self.st["chapters"][0]["scenes"][0]["choices"] = [{"target": "zzz", "label": "Fin"}]
        G.start_route(self.st, "s1", "p3", "A", "A")
        src, route = self.st["chapters"][0]["scenes"]
        self.assertEqual(route["choices"], [{"target": "zzz", "label": "Fin"}])

    def test_first_image_cannot_start_a_route(self):
        with self.assertRaises(ValueError):
            G.start_route(self.st, "s1", "p1", "A", "A")

    def test_route_is_playable_in_the_graph(self):
        G.start_route(self.st, "s1", "p2", "Suivre", "La suite")
        g = G.build(self.st)
        self.assertTrue(any(e["kind"] == "choice" and e["label"] == "Suivre" for e in g["edges"]))
        self.assertEqual(g["problems"], [])


class UndoRouteTests(unittest.TestCase):
    def setUp(self):
        t = StartRouteTests()
        t.setUp()
        self.st = t.st
        self.original = [l["text"] for l in self.st["chapters"][0]["scenes"][0]["dialogue"]]

    def test_undo_brings_the_content_back_and_removes_the_route(self):
        new_id = G.start_route(self.st, "s1", "p3", "Accepter", "Accepter")
        self.assertEqual(G.route_from(self.st, new_id), "s1")
        G.undo_route(self.st, new_id)
        src = self.st["chapters"][0]["scenes"]
        self.assertEqual(len(src), 1)
        self.assertEqual([l["text"] for l in src[0]["dialogue"]], self.original)
        self.assertEqual([p["id"] for p in src[0]["plans"]], ["p1", "p2", "p3", "p4"])
        self.assertEqual(src[0]["choices"], [])
        self.assertEqual(sorted(src[0]["line_tags"]), ["0", "2", "3"])

    def test_undo_keeps_the_route_choices(self):
        new_id = G.start_route(self.st, "s1", "p3", "Accepter", "Accepter")
        route = self.st["chapters"][0]["scenes"][1]
        route["choices"] = [{"target": "zzz", "label": "Fin"}]
        G.undo_route(self.st, new_id)
        self.assertEqual(self.st["chapters"][0]["scenes"][0]["choices"], [{"target": "zzz", "label": "Fin"}])

    def test_a_scene_that_is_not_a_route_cannot_be_undone(self):
        with self.assertRaises(ValueError):
            G.undo_route(self.st, "s1")

    def test_undo_restores_the_content_of_a_route_with_a_new_scene_in_the_middle(self):
        # Une image ajoutée à la scène d'origine après la coupe peut prendre l'identifiant d'une image de la route.
        new_id = G.start_route(self.st, "s1", "p3", "Accepter", "Accepter")
        src = self.st["chapters"][0]["scenes"][0]
        src["plans"].append({"id": "p3", "from_line": len(src["dialogue"]), "asset": "a9"})  # id libre après la coupe
        G.undo_route(self.st, new_id)
        ids = [p["id"] for p in self.st["chapters"][0]["scenes"][0]["plans"]]
        self.assertEqual(len(ids), len(set(ids)))


def _chapter_story():
    """Trois scènes : s1 (4 répliques, 4 images), s2 (suite), s3 (fin)."""
    def sc(sid, n_lines, plans):
        return {"id": sid, "title": sid.upper(), "summary": "", "characters": ["Léa"], "location": "Studio",
                "outfits": {}, "choices": [], "ending": False, "locked": False,
                "dialogue": [{"speaker": "Léa", "text": str(i)} for i in range(n_lines)],
                "plans": plans, "line_tags": {}}
    plans = [{"id": f"p{i}", "from_line": i - 1, "asset": f"a{i}"} for i in range(1, 5)]
    return {"chapters": [{"id": "c1", "scene_count": 3, "scenes": [
        sc("s1", 4, plans), sc("s2", 2, []), sc("s3", 1, [])]}]}


class BranchTests(unittest.TestCase):
    def test_branch_keeps_the_trunk_and_creates_an_empty_route(self):
        st = _chapter_story()
        route_id = G.branch_at(st, "s1", "p3", "Accepter", "Accepter")
        ids = [s["id"] for s in st["chapters"][0]["scenes"]]
        head, common, route = st["chapters"][0]["scenes"][0], st["chapters"][0]["scenes"][1], st["chapters"][0]["scenes"][2]
        self.assertEqual(route["id"], route_id)
        self.assertEqual(ids[0], "s1")
        self.assertEqual([p["id"] for p in common["plans"]], ["p3", "p4"])
        self.assertEqual(route["plans"], [])
        self.assertEqual(common["next"], "s2")
        self.assertEqual(route["next"], "s2")
        self.assertEqual([(c["target"], c["label"]) for c in head["choices"]],
                         [(common["id"], "Continuer"), (route_id, "Accepter")])

    def test_route_can_rejoin_the_main_line(self):
        st = _chapter_story()
        route_id = G.branch_at(st, "s1", "p3", "Accepter", "Accepter")
        G.rejoin(st, route_id, "s3")
        g = G.build(st)
        self.assertIn((route_id, "s3", "next"), [(e["source"], e["target"], e["kind"]) for e in g["edges"]])
        self.assertEqual(g["problems"], [])

    def test_detach_moves_the_route_to_the_reserve_and_attach_brings_it_back(self):
        st = _chapter_story()
        route_id = G.branch_at(st, "s1", "p3", "Accepter", "Accepter")
        G.rejoin(st, route_id, "s3")
        block = G.detach(st, route_id)
        self.assertEqual(st["reserve"], [block])
        self.assertNotIn(route_id, [s["id"] for s in st["chapters"][0]["scenes"]])
        head = st["chapters"][0]["scenes"][0]
        common_id = head["next"]                      # le « Continuer » restant devient simplement la suite
        self.assertNotEqual(common_id, "s2")          # la partie commune est la suite de la scène d'origine
        self.assertEqual(head["choices"], [])
        new_id = G.attach(st, "s1", block["id"], "Revenir")
        self.assertEqual(st["reserve"], [])
        head = st["chapters"][0]["scenes"][0]
        self.assertIn(new_id, [c["target"] for c in head["choices"]])
        self.assertIn(common_id, [c["target"] for c in head["choices"]])

    def test_a_route_with_choices_cannot_be_detached(self):
        st = _chapter_story()
        route_id = G.branch_at(st, "s1", "p3", "Accepter", "Accepter")
        G.set_choices(st, route_id, [{"label": "Fin", "target": "s3"}])
        with self.assertRaises(ValueError):
            G.detach(st, route_id)
