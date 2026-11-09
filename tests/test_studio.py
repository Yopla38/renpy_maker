"""Studio : fichiers servis, titre et résumé d'une scène, style choisi après coup, export sans SDK,
erreurs du modèle de langage en message lisible."""

import http.client
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import appsettings, paths
from renpy_maker import facile as FA
from renpy_maker import recit as RC
from renpy_maker import renpy_export as RE
from renpy_maker import story as S
from renpy_maker.llm import LLMError
from renpy_maker.webapp import server as SRV

STUDIO = Path(SRV.__file__).with_name("studio")


class StudioFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = SRV.ThreadingHTTPServer(("127.0.0.1", 0), SRV.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r.status, r.getheader("Content-Type", ""), body

    def test_scripts_and_styles_are_served(self):
        for name, ctype in (("app.js", "javascript"), ("studio.css", "text/css"), ("views/carte.js", "javascript")):
            status, got, body = self.get(f"/studio/{name}")
            self.assertEqual(status, 200, name)
            self.assertIn(ctype, got)
            self.assertEqual(body, (STUDIO / name).read_bytes())

    def test_nothing_outside_the_studio_folder(self):
        for path in ("/studio/../server.py", "/studio/%2e%2e/server.py", "/studio/..%2fserver.py",
                     "/studio/views/../../server.py", "/studio/missing.js"):
            status, _, _ = self.get(path)
            self.assertEqual(status, 404, path)

    def test_every_module_imported_by_the_app_exists(self):
        import re
        for js in STUDIO.rglob("*.js"):
            for rel in re.findall(r'from "(\.{1,2}/[^"]+)"', js.read_text(encoding="utf-8")):
                self.assertTrue((js.parent / rel).resolve().is_file(), f"{js.name} importe {rel}")


class StudioBackendTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(paths, "data_root", lambda: self.home),
                        mock.patch.object(appsettings, "load", return_value={})]
        for p in self.patches:
            p.start()
        st = S.new_story(title="Test", idea="Une idée")
        ch = S.add_chapter(st, "ch1", "C", "r", 1)
        S.add_scene(ch, "s1", "Avant", "résumé", ["Léa"], "Gare", {})
        S.save(st)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def test_scene_title_and_summary(self):
        FA.set_scene_meta("s1", title="  Le   quai  ", summary="Léa attend.")
        sc = S.all_scenes(S.load())[0]
        self.assertEqual((sc["title"], sc["summary"]), ("Le quai", "Léa attend."))
        with self.assertRaises(ValueError):
            FA.set_scene_meta("s1", title="   ")
        with self.assertRaises(ValueError):
            FA.set_scene_meta("nulle-part", title="x")

    def test_a_missing_style_can_still_be_chosen_after_the_start(self):
        RC.set_frame("Test", "Une idée", "", "aquarelle")  # l'histoire a déjà un chapitre, mais pas de style
        self.assertEqual(S.load()["settings"]["style"], "aquarelle")
        with self.assertRaises(ValueError):  # ensuite, il ne change plus
            RC.set_frame("Test", "Une idée", "", "dessin")

    def test_export_without_sdk_skips_the_check(self):
        with mock.patch.object(RE, "renpy_sh", return_value=self.home / "absent" / "renpy.sh"), \
                mock.patch.object(RE, "export", return_value={"images": 0, "files": []}), \
                mock.patch.object(RE, "lint") as lint:
            res = FA.export_game()
        lint.assert_not_called()
        self.assertIsNone(res["lint"]["ok"])
        self.assertIn("SDK", res["lint"]["skipped"])
        with mock.patch.object(RE, "renpy_sh", return_value=self.home / "absent" / "renpy.sh"):
            with self.assertRaises(ValueError):
                FA.launch_game()


class LLMErrorTests(unittest.TestCase):
    def test_model_errors_reach_the_page_as_readable_messages(self):
        sent = {}

        class Fake:
            def _json(self, code, obj):
                sent.update(code=code, obj=obj)

        with mock.patch.object(SRV.FA, "route", side_effect=LLMError("Clé absente")):
            SRV.Handler._facile(Fake(), "POST", "/api/facile/x", {})
        self.assertEqual(sent, {"code": 502, "obj": {"error": "Clé absente"}})


if __name__ == "__main__":
    unittest.main()
