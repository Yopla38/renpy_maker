"""Attente d'une génération ComfyUI : arrêt, disparition, fin sans image (serveur simulé)."""

import io
import sys
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import comfy_client as CC  # noqa: E402


class FakeComfy:
    def __init__(self, history=None, queue=None):
        self.history = history or {}
        self.queue = queue if queue is not None else {"queue_running": [], "queue_pending": []}
        self.posts = []

    def get(self, url, base):
        if url == "/queue":
            return self.queue
        return self.history

    def post(self, path, payload, base):
        self.posts.append((path, payload))
        return {"prompt_id": "P1"} if path == "/prompt" else {}


class RunTests(unittest.TestCase):
    def run_with(self, fake, **kw):
        with mock.patch.object(CC, "_get", fake.get), mock.patch.object(CC, "_post", fake.post), \
                mock.patch.object(CC.WebSocketConnection, "open", side_effect=OSError), \
                mock.patch.object(CC.time, "sleep"), mock.patch.object(CC, "QUEUE_CHECK_S", 0):
            return CC.run({}, "http://x", timeout_s=5, **kw)

    def test_returns_files(self):
        fake = FakeComfy(history={"P1": {"status": {"completed": True},
                                         "outputs": {"9": {"images": [{"filename": "a.png"}]}}}})
        self.assertEqual(self.run_with(fake), [{"filename": "a.png"}])

    def test_prompt_removed_from_queue_fails_fast(self):
        with self.assertRaisesRegex(RuntimeError, "disparu"):
            self.run_with(FakeComfy())

    def test_completed_without_image_fails_fast(self):
        fake = FakeComfy(history={"P1": {"status": {"completed": True}, "outputs": {}}})
        with self.assertRaisesRegex(RuntimeError, "sans produire"):
            self.run_with(fake)

    def test_stop_request_interrupts_this_prompt(self):
        fake = FakeComfy(queue={"queue_running": [[0, "P1"]], "queue_pending": []})
        with self.assertRaises(CC.Stopped):
            self.run_with(fake, should_stop=lambda: True)
        self.assertIn(("/queue", {"delete": ["P1"]}), fake.posts)
        self.assertIn(("/interrupt", {"prompt_id": "P1"}), fake.posts)


class EmptyReplyTests(unittest.TestCase):
    def test_post_accepts_empty_body(self):
        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(CC.urllib.request, "urlopen", return_value=Resp(b"")):
            self.assertEqual(CC._post("/interrupt", {}, "http://x"), {})


if __name__ == "__main__":
    unittest.main()
