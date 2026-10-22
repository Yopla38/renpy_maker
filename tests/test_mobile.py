"""Application pour enfants et adolescents : clés de l'appareil, mode enfants, lecture, texte Replicate.

Aucun appel réseau : les requêtes Replicate sont simulées, les fichiers d'appareil sont temporaires."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import facile as FA  # noqa: E402
import image_replicate as REP  # noqa: E402
import keys  # noqa: E402
import llm  # noqa: E402
import paths  # noqa: E402
from test_facile import Setup  # noqa: E402


class KeysTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "secrets.json"
        for patch in (mock.patch.object(paths, "SECRETS", self.tmp),
                      mock.patch.object(keys, "LEGACY", Path(tempfile.mkdtemp()) / "absent.txt"),
                      mock.patch.dict(os.environ, {}, clear=False)):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop("REPLICATE_API_TOKEN", None)

    def test_key_saved_on_device_and_never_shown_as_value(self):
        self.assertFalse(keys.present("REPLICATE_API_TOKEN"))
        keys.set("REPLICATE_API_TOKEN", "  r8_secret  ")
        self.assertEqual(keys.get("REPLICATE_API_TOKEN"), "r8_secret")
        self.assertTrue(keys.present("REPLICATE_API_TOKEN"))
        self.assertIn("r8_secret", self.tmp.read_text(encoding="utf-8"))  # sur l'appareil seulement

    def test_only_known_secret_names_are_accepted(self):
        with self.assertRaises(ValueError):
            FA.save_secret("AUTRE_CLE", "x")
        with self.assertRaises(ValueError):
            FA.save_secret("REPLICATE_API_TOKEN", "   ")


class KidsModeTests(Setup, unittest.TestCase):
    def test_explicit_content_is_refused_in_kids_mode(self):
        FA.set_style("aquarelle")
        with mock.patch.object(paths, "KIDS", True):
            self.wait(FA.write_story("", "Une histoire pour enfants", 3, True))
            self.assertFalse(FA.S.load()["settings"]["explicit_content"])
            self.assertFalse(FA.view()["explicit"])
            self.assertEqual(FA.S.load()["settings"]["providers"]["text"], "replicate")

    def _safety_sent(self, kids, requested):
        """Valeur réellement envoyée à Replicate pour le filtre de sécurité (retouche avec images)."""
        sent = {}

        def fake_req(method, url, body=None, **kw):
            if body:
                sent.update(body["input"])
            return {"status": "succeeded", "output": ["https://x/y.png"], "urls": {"get": "u"}}

        png = Path(tempfile.mkdtemp()) / "ref.png"
        png.write_bytes(b"\x89PNG")
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"image"
        with mock.patch.object(paths, "KIDS", kids), mock.patch.object(REP, "_req", side_effect=fake_req), \
                mock.patch.object(REP, "_token", return_value="t"), \
                mock.patch("urllib.request.urlopen", return_value=resp):
            REP.generate("a", Path(tempfile.mkdtemp()) / "o.png", images=[png], disable_safety_checker=requested)
        return sent["disable_safety_checker"]

    def test_image_safety_checker_is_forced_on_in_kids_mode(self):
        self.assertFalse(self._safety_sent(kids=True, requested=True))

    def test_image_safety_checker_follows_request_outside_kids_mode(self):
        self.assertTrue(self._safety_sent(kids=False, requested=True))
        self.assertFalse(self._safety_sent(kids=False, requested=False))

    def test_replicate_is_the_only_text_provider_for_kids(self):
        with mock.patch.object(paths, "KIDS", True):
            names = [c["name"] for c in FA.settings_view()["text"]["choices"]]
            self.assertEqual(names, ["replicate"])
            with self.assertRaises(ValueError):
                FA.save_settings({"text_provider": "anthropic"})


class PlayTests(Setup, unittest.TestCase):
    def test_play_view_gives_scenes_and_lines_in_order(self):
        FA.set_style("aquarelle")
        self.wait(FA.write_story("Le trésor", "Une histoire", 3, False))
        view = FA.play_view()
        self.assertEqual(view["title"], "Le trésor")
        self.assertEqual(len(view["scenes"]), 2)
        self.assertEqual(len(view["scenes"][0]["lines"]), 2)
        self.assertEqual(view["scenes"][0]["images"], [])  # pas encore d'image : le lecteur reste sur le fond sombre


class ReplicateTextTests(unittest.TestCase):
    def test_text_comes_from_replicate_prediction(self):
        answers = [{"status": "starting", "urls": {"get": "https://api/get"}},
                   {"status": "succeeded", "output": ["Bonjour ", "Léa"]}]
        with mock.patch.object(REP, "_req", side_effect=lambda *a, **k: answers.pop(0)), \
                mock.patch("time.sleep", return_value=None):
            text = llm._replicate_text({"model": "owner/model", "max_tokens": 10, "temperature": 0.5}, "sys", "user")
        self.assertEqual(text, "Bonjour Léa")

    def test_failed_prediction_raises_readable_error(self):
        with mock.patch.object(REP, "_req", return_value={"status": "failed", "error": "modèle indisponible"}):
            with self.assertRaises(llm.LLMError) as cm:
                llm._replicate_text({"model": "owner/model", "max_tokens": 10, "temperature": 0.5}, "s", "u")
        self.assertIn("modèle indisponible", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
