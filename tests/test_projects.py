"""Histoires multiples : création, ouverture, renommage, suppression (sur un dossier temporaire)."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import paths  # noqa: E402
from renpy_maker import projects as PJ  # noqa: E402
from renpy_maker import story as S  # noqa: E402


class ProjectsTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.patches = [
            mock.patch.object(paths, "HOME", self.home),
            mock.patch.object(paths, "PROJECTS", self.home / "projects"),
        ]
        for p in self.patches:
            p.start()
        paths.activate(None)
        paths._chosen = False

    def tearDown(self):
        for p in self.patches:
            p.stop()
        paths._active = None
        paths._chosen = False
        shutil.rmtree(self.home, ignore_errors=True)

    def test_create_makes_an_empty_story_folder(self):
        pid = PJ.create("Le manoir du lac", "Une nuit d'orage")
        folder = paths.PROJECTS / pid
        self.assertEqual(pid, "le-manoir-du-lac")
        self.assertTrue((folder / "game_spec" / "story.yaml").exists())
        self.assertTrue((folder / "game_spec" / "assets.yaml").exists())
        self.assertTrue((folder / "assets").is_dir())
        self.assertTrue((folder / "work").is_dir())
        st = S.load(folder / "game_spec" / "story.yaml")
        self.assertEqual((st["title"], st["idea"]), ("Le manoir du lac", "Une nuit d'orage"))

    def test_same_name_gets_a_new_identifier(self):
        first = PJ.create("Titre")
        second = PJ.create("Titre")
        self.assertEqual((first, second), ("titre", "titre-2"))

    def test_empty_name_is_refused(self):
        with self.assertRaises(ValueError):
            PJ.create("   ")

    def test_nothing_is_open_until_a_choice_is_made(self):
        PJ.create("Une histoire")
        self.assertFalse(paths.chosen())
        self.assertIsNone(PJ.current())

    def test_opening_a_project_switches_its_data(self):
        a = PJ.create("Alpha")
        b = PJ.create("Beta")
        PJ.open_project(a, busy=False)
        self.assertEqual(paths.story_file(), paths.PROJECTS / a / "game_spec" / "story.yaml")
        self.assertEqual(PJ.current()["name"], "Alpha")
        PJ.open_project(b, busy=False)
        self.assertEqual(paths.story_file(), paths.PROJECTS / b / "game_spec" / "story.yaml")
        self.assertEqual(PJ.current()["name"], "Beta")

    def test_opening_is_refused_while_a_generation_runs(self):
        pid = PJ.create("Alpha")
        with self.assertRaises(ValueError):
            PJ.open_project(pid, busy=True)
        self.assertFalse(paths.chosen())

    def test_origin_story_is_listed_only_when_it_exists(self):
        self.assertEqual([p["id"] for p in PJ.list_projects()], [])
        (self.home / "game_spec").mkdir()
        S.save(S.new_story(title="Ancienne"), self.home / "game_spec" / "story.yaml")
        origin = [p for p in PJ.list_projects() if p["id"] == PJ.ORIGIN]
        self.assertEqual(origin[0]["name"], "Ancienne")
        with self.assertRaises(ValueError):
            PJ.rename(PJ.ORIGIN, "Autre")
        with self.assertRaises(ValueError):
            PJ.delete(PJ.ORIGIN)

    def test_rename_changes_the_name_only(self):
        pid = PJ.create("Ancien")
        PJ.rename(pid, "  Nouveau   titre ")
        self.assertEqual(PJ.list_projects()[0]["name"], "Nouveau titre")
        st = S.load(paths.PROJECTS / pid / "game_spec" / "story.yaml")
        self.assertEqual(st["title"], "Ancien")

    def test_delete_moves_to_trash_and_refuses_the_open_one(self):
        keep = PJ.create("Garder")
        gone = PJ.create("Supprimer")
        PJ.open_project(keep, busy=False)
        with self.assertRaises(ValueError):
            PJ.delete(keep)
        result = PJ.delete(gone)
        self.assertFalse((paths.PROJECTS / gone).exists())
        self.assertTrue(Path(result["trash"]).joinpath("game_spec", "story.yaml").exists())

    def test_unknown_or_bad_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            PJ.open_project("../../etc", busy=False)
        with self.assertRaises(ValueError):
            PJ.open_project("inexistant", busy=False)

    def test_file_urls_depend_on_the_open_project(self):
        pid = PJ.create("Alpha")
        self.assertEqual(paths.file_url("assets/x/c.png"), "/files/assets/x/c.png")
        PJ.open_project(pid, busy=False)
        self.assertEqual(paths.file_url("assets/x/c.png"), f"/files/p/{pid}/assets/x/c.png")


    def test_last_opened_project_is_restored_at_startup(self):
        pid = PJ.create("Alpha")
        PJ.open_project(pid, busy=False)
        paths.activate(None)
        paths._chosen = False
        self.assertEqual(PJ.restore_last()["id"], pid)
        self.assertTrue(paths.chosen())
        self.assertEqual(PJ.current()["name"], "Alpha")

    def test_restore_does_nothing_when_the_project_is_gone(self):
        pid = PJ.create("Alpha")
        PJ.open_project(pid, busy=False)
        shutil.rmtree(paths.PROJECTS / pid)
        paths.activate(None)
        paths._chosen = False
        self.assertIsNone(PJ.restore_last())
        self.assertFalse(paths.chosen())

    def test_each_project_exports_to_its_own_renpy_folder(self):
        from renpy_maker import renpy_export as RE
        pid = PJ.create("Alpha")
        self.assertNotEqual(RE.project_dir(), paths.PROJECTS / pid / "renpy")
        PJ.open_project(pid, busy=False)
        self.assertEqual(RE.project_dir(), paths.PROJECTS / pid / "renpy")

    def test_new_story_does_not_inherit_the_open_story_choices(self):
        first = PJ.create("Premiere")
        (paths.PROJECTS / first / "game_spec" / "app_settings.yaml").write_text(
            "image_engines:\n  base: {engine: comfyui, workflow: null}\n", encoding="utf-8")
        PJ.open_project(first, busy=False)
        second = PJ.create("Seconde")
        self.assertFalse((paths.PROJECTS / second / "game_spec" / "app_settings.yaml").exists())
        self.assertFalse((paths.PROJECTS / second / "game_spec" / "llm_models.yaml").exists())


if __name__ == "__main__":
    unittest.main()
