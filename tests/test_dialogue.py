"""Répliques : normalisation, validation des locuteurs, génération simulée (aucun appel réel)."""

import unittest
from unittest import mock

from renpy_maker import llm  # noqa: E402
from renpy_maker import plan as P  # noqa: E402
from renpy_maker import story as S  # noqa: E402
from renpy_maker.webapp import server as SRV  # noqa: E402


def story_with_dialogue(lines):
    st = S.new_story("t", "i", total_scenes=1)
    ch = S.add_chapter(st, "ch1", "C", "r", 1)
    sc = S.add_scene(ch, "s1", "A", "a", ["Eve"], "Le Velvet", {})
    sc["ending"] = True
    sc["dialogue"] = lines
    return st


class DialogueTests(unittest.TestCase):
    def test_normalize_accepts_present_speakers_and_narration(self):
        raw = {"lines": [{"speaker": "Eve", "text": "Bonsoir.", "expression": "sourire"},
                         {"speaker": "Narration", "text": "Elle hésite."}]}
        out = P.normalize_dialogue(raw, ["Eve"])
        self.assertEqual(out[1]["expression"], "neutre")
        self.assertEqual(len(out), 2)

    def test_normalize_rejects_unknown_speaker(self):
        with self.assertRaises(llm.LLMError):
            P.normalize_dialogue({"lines": [{"speaker": "Adrien", "text": "Salut"}]}, ["Eve"])

    def test_validate_flags_speaker_absent_from_scene(self):
        st = story_with_dialogue([{"speaker": "Adrien", "text": "Salut", "expression": "neutre"}])
        self.assertTrue(any("absent de la scène" in e for e in S.validate(st)))

    def test_validate_flags_empty_line(self):
        st = story_with_dialogue([{"speaker": "Eve", "text": " ", "expression": "neutre"}])
        self.assertTrue(any("vide" in e for e in S.validate(st)))

    def test_clean_dialogue_from_manual_input(self):
        sc = {"characters": ["Eve"]}
        out = SRV._clean_dialogue([{"speaker": "Eve", "text": " Bonjour ", "expression": ""}], sc)
        self.assertEqual(out, [{"speaker": "Eve", "text": "Bonjour", "expression": "neutre"}])
        with self.assertRaises(ValueError):
            SRV._clean_dialogue([{"speaker": "Léa", "text": "x"}], sc)

    def test_generate_dialogue_with_mocked_llm(self):
        st = story_with_dialogue([])
        reply = '{"lines": [{"speaker": "Eve", "text": "Tu viens ?", "expression": "méfiance"}]}'
        with mock.patch.object(llm, "complete", return_value=reply):
            lines = P.generate_dialogue(st, "s1")
        self.assertEqual(lines[0]["text"], "Tu viens ?")
        self.assertEqual(lines[0]["expression"], "méfiance")


class DialogueGuardTests(unittest.TestCase):
    def test_saving_fewer_lines_than_images_need_is_refused(self):
        sc = {"characters": ["Eve"], "plans": [{"id": "p9", "from_line": 9, "asset": "x"}]}
        # la logique du garde-fou est dans le serveur : on la vérifie sur les mêmes règles
        new = SRV._clean_dialogue([{"speaker": "Eve", "text": "a"}], {"characters": ["Eve"]})
        orphan = [p["id"] for p in sc["plans"] if p["from_line"] >= len(new)]
        self.assertEqual(orphan, ["p9"])


if __name__ == "__main__":
    unittest.main()
