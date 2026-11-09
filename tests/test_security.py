"""Sécurité du serveur local : CSRF, DNS rebinding, corps de requête, identifiants, secrets."""

import http.client
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import assets as A  # noqa: E402
from renpy_maker import keys  # noqa: E402
from renpy_maker import paths  # noqa: E402
from renpy_maker.webapp import server as SRV  # noqa: E402


class ServerGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = SRV.ThreadingHTTPServer(("127.0.0.1", 0), SRV.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, data

    def test_post_without_custom_header_is_refused(self):
        # Une page web d'un autre site peut envoyer ce POST « simple » sans pré-vérification CORS.
        status, _ = self.request("POST", "/api/asset", b'{"id":"x","kind":"character"}',
                                 {"Content-Type": "text/plain"})
        self.assertEqual(status, 403)

    def test_foreign_host_is_refused(self):  # DNS rebinding
        status, _ = self.request("GET", "/api/assets", headers={"Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403)

    def test_foreign_origin_is_refused(self):
        status, _ = self.request("POST", "/api/asset", b"{}", {
            "Origin": "https://evil.example", SRV.CSRF_HEADER: "1"})
        self.assertEqual(status, 403)

    def test_local_names_are_accepted(self):
        for host in (f"localhost:{self.port}", f"127.0.0.1:{self.port}", f"[::1]:{self.port}"):
            status, _ = self.request("GET", "/nope", headers={"Host": host})
            self.assertEqual(status, 404, host)

    def test_bad_json_gets_400(self):
        h = {SRV.CSRF_HEADER: "1"}
        for body in (b"{bad", b"[1, 2]", b'"texte"'):
            status, _ = self.request("POST", "/api/facile/nothing", body, h)
            self.assertEqual(status, 400, body)

    def test_negative_content_length_gets_400(self):
        status, _ = self.request("POST", "/api/asset", None, {SRV.CSRF_HEADER: "1", "Content-Length": "-1"})
        self.assertEqual(status, 400)


class AssetIdTests(unittest.TestCase):
    def test_traversal_ids_are_rejected(self):
        data = {"version": 1, "assets": {}}
        for bad in ("../../evil", "a/b", "", "x'y", "é" * 3, None, 3):
            with self.assertRaises(ValueError, msg=repr(bad)):
                A.add_asset(data, bad, "character", "n", "d")
        self.assertEqual(data["assets"], {})

    def test_normal_ids_are_accepted(self):
        data = {"version": 1, "assets": {}}
        A.add_asset(data, "char_eve", "character", "Eve", "")
        A.add_asset(data, "scene_s1_ab12cd", "scene", "S", "")
        self.assertEqual(len(data["assets"]), 2)


class SecretFileTests(unittest.TestCase):
    def test_secrets_are_private(self):
        home = Path(tempfile.mkdtemp())
        with mock.patch.object(paths, "SECRETS", home / "secrets.json"), mock.patch.dict(os.environ):
            keys.set("TEST_KEY", "abc")
            mode = stat.S_IMODE((home / "secrets.json").stat().st_mode)
            self.assertEqual(mode, 0o600)
            self.assertEqual(json.loads((home / "secrets.json").read_text())["TEST_KEY"], "abc")
            self.assertEqual(list(home.iterdir()), [home / "secrets.json"])  # pas de fichier temporaire


if __name__ == "__main__":
    unittest.main()
