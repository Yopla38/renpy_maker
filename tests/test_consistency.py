"""Écritures atomiques, verrous et changement d'histoire pendant une tâche de fond."""

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assets as A  # noqa: E402
import background  # noqa: E402
import paths  # noqa: E402
import pipeline as PL  # noqa: E402


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_failed_write_keeps_previous_content(self):
        f = self.dir / "story.yaml"
        paths.atomic_write(f, "ancien")

        with mock.patch("os.fsync", side_effect=OSError("disque plein")):
            with self.assertRaises(OSError):
                paths.atomic_write(f, "nouveau")
        self.assertEqual(f.read_text(), "ancien")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["story.yaml"])  # pas de reste

    def test_existing_permissions_are_kept(self):
        f = self.dir / "a.yaml"
        f.write_text("x")
        os.chmod(f, 0o640)
        paths.atomic_write(f, "y")
        self.assertEqual(f.stat().st_mode & 0o777, 0o640)


class CreatedAssetsMergeTests(unittest.TestCase):
    def test_snapshot_does_not_erase_concurrent_candidates(self):
        file = Path(tempfile.mkdtemp()) / "assets.yaml"
        with mock.patch.object(paths, "assets_file", return_value=file):
            data = {"version": 1, "assets": {}}
            A.add_asset(data, "char_eve", "character", "Eve", "")
            A.save(data)
            snapshot = A.load()
            before = set(snapshot["assets"])
            # pendant les appels au LLM, une image est générée pour Eve…
            cur = A.load()
            A.add_candidate(cur, "char_eve", "assets/char_eve/cand_00.png", {})
            A.save(cur)
            # …et le pipeline crée un nouvel élément sur son instantané
            A.add_asset(snapshot, "loc_ferme", "location", "Ferme", "")
            PL.save_created_assets(snapshot, before)
            final = A.load()["assets"]
        self.assertEqual(len(final["char_eve"]["candidates"]), 1)
        self.assertIn("loc_ferme", final)


class SwitchWhileBusyTests(unittest.TestCase):
    def test_background_job_blocks_story_switch(self):
        import facile as FA
        gate = threading.Event()
        background.start(gate.wait)
        try:
            with self.assertRaisesRegex(ValueError, "génération est en cours"):
                FA.route("POST", "/api/facile/projects/open", {"id": "x"})
        finally:
            gate.set()
        for _ in range(100):
            if background.running() == 0:
                break
            threading.Event().wait(0.01)
        self.assertEqual(background.running(), 0)


if __name__ == "__main__":
    unittest.main()
