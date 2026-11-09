"""Fichier des prompts : valeurs par défaut, fichier de l'utilisateur, variables, erreurs, relecture."""

import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import paths
from renpy_maker import prompt_texts as T
from renpy_maker import story as S

SRC = Path(T.__file__).parent


class RenderTests(unittest.TestCase):
    def test_variables_and_fallbacks(self):
        self.assertEqual(T.render("a ${x} b", x=1), "a 1 b")
        self.assertEqual(T.render("${x|vide}", x=""), "vide")
        self.assertEqual(T.render("${x|vide}", x=None), "vide")
        self.assertEqual(T.render("${x|vide}", x="plein"), "plein")
        self.assertEqual(T.render("prix : 5 $$", ), "prix : 5 $")
        self.assertEqual(T.render('{"json": [1, 2]} ${x}', x="ok"), '{"json": [1, 2]} ok')

    def test_unknown_variable_names_the_prompt(self):
        with self.assertRaisesRegex(T.PromptError, r"« cle » : \$\{y\} inconnu"):
            T.render("${y}", "cle", x=1)

    def test_missing_key(self):
        with self.assertRaisesRegex(T.PromptError, "absent"):
            T.t("nulle.part")


class UserFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(paths, "REPO", self.dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_user_file_overrides_only_its_keys_and_is_reread(self):
        default = T.t("image.no_person")
        (self.dir / "prompts.yaml").write_text("image:\n  no_person: Personne à l'image.\n", encoding="utf-8")
        self.assertEqual(T.t("image.no_person"), "Personne à l'image.")
        self.assertNotEqual(T.t("image.no_names"), "")              # les autres clés restent celles par défaut
        time.sleep(0.01)
        (self.dir / "prompts.yaml").write_text("image:\n  no_person: Encore autre chose.\n", encoding="utf-8")
        self.assertEqual(T.t("image.no_person"), "Encore autre chose.")  # relu sans relancer
        (self.dir / "prompts.yaml").unlink()
        self.assertEqual(T.t("image.no_person"), default)

    def test_broken_user_file_gives_a_clear_error(self):
        (self.dir / "prompts.yaml").write_text("image: [pas fermé\n", encoding="utf-8")
        with self.assertRaisesRegex(T.PromptError, "YAML invalide"):
            T.t("image.no_person")

    def test_styles_come_from_the_file(self):
        (self.dir / "prompts.yaml").write_text(
            "styles:\n  aquarelle:\n    label: Aquarelle\n    desc: d\n    suffix: mon suffixe\n", encoding="utf-8")
        st = S.new_story()
        st["settings"]["style"] = "aquarelle"
        self.assertEqual(S.style_of(st)["positive_suffix"], "mon suffixe")
        self.assertIn("realiste", S.styles())


class EveryKeyExistsTests(unittest.TestCase):
    """Chaque clé lue par le code existe dans le fichier par défaut, et ses ${variables} sont fournies."""

    def test_keys_used_in_the_code_exist(self):
        used = set()
        for py in SRC.glob("*.py"):
            text = py.read_text(encoding="utf-8")
            used |= set(re.findall(r'\bt\("([a-z_]+(?:\.[a-z_]+)+)"', text))
            # t(u + "titre") : le préfixe est la dernière affectation de u au-dessus de l'appel.
            assigns = [(m.start(), m.group(1), m.group(2))
                       for m in re.finditer(r'^\s*(\w+) = "([a-z_]+(?:\.[a-z_]+)*\.)"$', text, re.M)]
            for m in re.finditer(r'\bt\((\w+) \+ "([a-z_]+)"', text):
                before = [p for pos, var, p in assigns if var == m.group(1) and pos < m.start()]
                self.assertTrue(before, f"{py.name} : préfixe {m.group(1)} introuvable")
                used.add(before[-1] + m.group(2))
        self.assertGreater(len(used), 100)
        for key in sorted(used):
            with self.subTest(key=key):
                self.assertIsInstance(T.get(key), str)

    def test_default_file_is_valid(self):
        data = T._read(T.DEFAULT_FILE)
        for top in ("chapter", "dialogue", "atelier", "recit", "shots", "image", "scene_image", "styles"):
            self.assertIn(top, data)


if __name__ == "__main__":
    unittest.main()
