"""Suivi en direct ComfyUI : trames WebSocket, pong, remontée de l'avancement. Sans réseau ni GPU."""

import json
import socket
import unittest
from unittest import mock

from renpy_maker import comfy_client as CC  # noqa: E402


def frame(opcode: int, payload: bytes) -> bytes:
    """Trame serveur : non masquée."""
    head = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        return head + bytes([n]) + payload
    return head + bytes([126]) + n.to_bytes(2, "big") + payload


class FrameTests(unittest.TestCase):
    def setUp(self):
        self.server, self.client = socket.socketpair()
        self.conn = CC.WebSocketConnection(self.client)
        self.addCleanup(self.server.close)
        self.addCleanup(self.client.close)

    def test_text_frame_is_read(self):
        message = json.dumps({"type": "progress", "data": {"value": 3, "max": 20}}).encode()
        self.server.sendall(frame(1, message))
        opcode, payload = self.conn.recv(timeout=2)
        self.assertEqual(opcode, 1)
        self.assertEqual(json.loads(payload)["data"]["value"], 3)

    def test_long_frame_with_extended_length_is_read(self):
        payload = b"x" * 300
        self.server.sendall(frame(1, payload))
        self.assertEqual(self.conn.recv(timeout=2), (1, payload))

    def test_no_message_returns_none(self):
        self.assertIsNone(self.conn.recv(timeout=0.1))

    def test_ping_gets_a_masked_pong(self):
        self.server.sendall(frame(9, b"ok") + frame(1, b"{}"))
        self.assertEqual(self.conn.recv(timeout=2), (1, b"{}"))
        self.server.settimeout(2)
        pong = self.server.recv(64)
        self.assertEqual(pong[0], 0x8A)     # pong
        self.assertTrue(pong[1] & 0x80)     # masqué, comme l'exige le protocole côté client


class RunProgressTests(unittest.TestCase):
    class FakeSocket:
        def __init__(self, messages):
            self.messages = list(messages)

        def recv(self, timeout):
            return self.messages.pop(0) if self.messages else None

        def close(self):
            pass

    def test_progress_is_reported_for_this_prompt_only(self):
        msgs = [(1, json.dumps({"type": "progress", "data": {"prompt_id": "p1", "value": 3, "max": 20}}).encode()),
                (1, json.dumps({"type": "progress", "data": {"prompt_id": "autre", "value": 9, "max": 20}}).encode()),
                (1, json.dumps({"type": "progress", "data": {"prompt_id": "p1", "value": 20, "max": 20}}).encode()),
                (2, b"\x00apercu")]  # aperçu binaire : ignoré
        fake = self.FakeSocket(msgs)
        history = {"p1": {"status": {"status_str": "success"},
                          "outputs": {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        seen = []
        with mock.patch.object(CC, "WebSocketConnection") as ws_cls, \
                mock.patch.object(CC, "_post", return_value={"prompt_id": "p1"}), \
                mock.patch.object(CC, "_get", side_effect=lambda url, base: history):
            ws_cls.open.return_value = mock.Mock(recv=fake.recv, close=fake.close)
            files = CC.run({}, "http://127.0.0.1:8188", 30, on_progress=lambda v, m: seen.append((v, m)))
        self.assertEqual(seen, [(3, 20), (20, 20)])
        self.assertEqual(files[0]["filename"], "a.png")

    def test_without_websocket_the_run_still_completes(self):
        history = {"p1": {"status": {"status_str": "success"},
                          "outputs": {"9": {"images": [{"filename": "b.png", "subfolder": "", "type": "output"}]}}}}
        with mock.patch.object(CC.WebSocketConnection, "open", side_effect=ConnectionRefusedError()), \
                mock.patch.object(CC, "_post", return_value={"prompt_id": "p1"}), \
                mock.patch.object(CC, "_get", side_effect=lambda url, base: history):
            files = CC.run({}, "http://127.0.0.1:8188", 30, on_progress=lambda v, m: self.fail("pas d'avancement"))
        self.assertEqual(files[0]["filename"], "b.png")


if __name__ == "__main__":
    unittest.main()
