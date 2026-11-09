"""Appels aux fournisseurs : nouvelles tentatives, erreurs réseau, JSON entouré de texte."""

import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import image_replicate as REP  # noqa: E402
import llm  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b"overloaded"))


class PostRetryTests(unittest.TestCase):
    def test_overload_then_success(self):
        replies = [http_error(529), urllib.error.URLError("reset"), Resp(b'{"ok": 1}')]
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=replies), \
                mock.patch.object(llm.time, "sleep") as sleep:
            self.assertEqual(llm._post("http://x", {}, {}), {"ok": 1})
        self.assertEqual(sleep.call_count, 2)

    def test_network_error_becomes_llm_error(self):
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=TimeoutError("lent")), \
                mock.patch.object(llm.time, "sleep"):
            with self.assertRaises(llm.LLMError):
                llm._post("http://x", {}, {})

    def test_client_error_is_not_retried(self):
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=[http_error(400)]) as op:
            with self.assertRaises(llm.LLMError):
                llm._post("http://x", {}, {})
        self.assertEqual(op.call_count, 1)


class ExtractJsonTests(unittest.TestCase):
    def test_text_after_the_object(self):
        self.assertEqual(llm.extract_json('Voici : {"a": 1} (le champ {a} est requis)'), {"a": 1})

    def test_two_code_blocks(self):
        text = '```json\n{"a": 1}\n```\nautre :\n```json\n{"b": 2}\n```'
        self.assertEqual(llm.extract_json(text), {"a": 1})

    def test_nested_object(self):
        self.assertEqual(llm.extract_json('{"a": {"b": [1, {"c": 2}]}}'), {"a": {"b": [1, {"c": 2}]}})

    def test_no_json(self):
        with self.assertRaises(llm.LLMError):
            llm.extract_json("pas de JSON ici")


class ReplicateTests(unittest.TestCase):
    def test_create_is_not_resent_after_network_error(self):
        with mock.patch.object(REP, "_token", return_value="t"), \
                mock.patch.object(REP.urllib.request, "urlopen", side_effect=urllib.error.URLError("x")) as op:
            with self.assertRaises(urllib.error.URLError):
                REP._req("POST", REP.API + "/models/m/predictions", {})
        self.assertEqual(op.call_count, 1)  # pas de seconde prédiction payante

    def test_poll_retries_on_server_error(self):
        with mock.patch.object(REP, "_token", return_value="t"), mock.patch.object(REP.time, "sleep"), \
                mock.patch.object(REP.urllib.request, "urlopen", side_effect=[http_error(502), Resp(b'{"s": 1}')]):
            self.assertEqual(REP._req("GET", "https://x/p/1"), {"s": 1})

    def test_stop_cancels_the_prediction(self):
        calls = []

        def fake_req(method, url, body=None, **kw):
            calls.append((method, url))
            return {"id": "p", "status": "processing", "urls": {"get": "g", "cancel": "c"}}

        with mock.patch.object(REP, "_req", fake_req), \
                mock.patch("background.should_stop", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "arrêtée"):
                REP.generate("x", Path("/nonexistent/out.png"))
        self.assertIn(("POST", "c"), calls)


if __name__ == "__main__":
    unittest.main()
