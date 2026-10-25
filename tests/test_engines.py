"""Choix des modèles par tâche, moteur d'image par rôle, génération ComfyUI (client simulé)."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from renpy_maker import appsettings  # noqa: E402
from renpy_maker import assets as A  # noqa: E402
from renpy_maker import facile_elements as FE  # noqa: E402
from renpy_maker import facile_jobs as FJ  # noqa: E402
from renpy_maker import facile_plans as FP  # noqa: E402
from renpy_maker import facile_settings as FS  # noqa: E402
from renpy_maker import comfy_client as CC  # noqa: E402
from renpy_maker import comfy_image  # noqa: E402
from renpy_maker import llm  # noqa: E402
from renpy_maker import paths  # noqa: E402
from test_comfy_graph import flux_like, with_reference_chain  # noqa: E402


def graph_with_reference() -> dict:
    g = copy.deepcopy(flux_like())
    g["60"] = {"class_type": "LoadImage", "inputs": {"image": "vide.png"}}
    return g


class ChoicesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "app_settings.yaml"
        self.patch = mock.patch.object(paths, "app_settings_file", lambda: self.tmp)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_default_task_model_follows_the_project_provider(self):
        self.assertEqual(appsettings.llm_for("histoire", "anthropic"), ("anthropic", ""))

    def test_a_choice_in_the_settings_overrides_the_default(self):
        appsettings.save({"llm_tasks": {"dialogue": {"provider": "ollama", "model": "qwen3:14b"}}})
        self.assertEqual(appsettings.llm_for("dialogue", "anthropic"), ("ollama", "qwen3:14b"))
        self.assertEqual(appsettings.llm_for("histoire", "anthropic"), ("anthropic", ""))

    def test_unknown_task_is_refused(self):
        with self.assertRaises(ValueError):
            appsettings.llm_for("musique", "anthropic")

    def test_image_engine_defaults_to_replicate_and_kids_mode_forces_it(self):
        self.assertEqual(appsettings.image_for("base")["engine"], "replicate")
        appsettings.save({"image_engines": {"base": {"engine": "comfyui", "workflow": "wf/FLUX1.json"}}})
        self.assertEqual(appsettings.image_for("base")["engine"], "comfyui")
        with mock.patch.object(paths, "KIDS", True):
            self.assertEqual(appsettings.image_for("base")["engine"], "replicate")

    def test_relative_workflow_path_is_resolved_from_the_project(self):
        appsettings.save({"image_engines": {"edit": {"engine": "comfyui", "workflow": "comfy/FLUX2.json"}}})
        self.assertEqual(appsettings.image_for("edit")["workflow"], str(paths.CODE / "comfy/FLUX2.json"))


class SettingsValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "app_settings.yaml"
        self.patch = mock.patch.object(paths, "app_settings_file", lambda: self.tmp)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_tasks_and_engines_are_saved(self):
        FS.save_settings_tasks({
            "tasks": [{"task": "dialogue", "provider": "ollama", "model": "qwen3:14b"},
                      {"task": "histoire", "provider": "", "model": ""}],
            "images": [{"role": "base", "engine": "replicate", "workflow": ""}],
        })
        self.assertEqual(appsettings.llm_for("dialogue", "anthropic"), ("ollama", "qwen3:14b"))
        self.assertEqual(appsettings.image_for("base")["engine"], "replicate")

    def test_unknown_provider_or_task_is_refused(self):
        with self.assertRaises(ValueError):
            FS.save_settings_tasks({"tasks": [{"task": "dialogue", "provider": "inconnu"}]})
        with self.assertRaises(ValueError):
            FS.save_settings_tasks({"tasks": [{"task": "musique", "provider": "ollama"}]})

    def test_comfyui_needs_an_existing_workflow_file(self):
        with self.assertRaises(ValueError) as cm:
            FS.save_settings_tasks({"images": [{"role": "edit", "engine": "comfyui", "workflow": "absent.json"}]})
        self.assertIn("introuvable", str(cm.exception))
        FS.save_settings_tasks({"images": [{"role": "edit", "engine": "comfyui", "workflow": ""}]})
        self.assertEqual(appsettings.image_for("edit")["workflow"], str(paths.CODE / "comfy/workflows/FLUX_KLEIN3_EDIT_API.json"))

    def test_kids_mode_refuses_comfyui_and_other_providers(self):
        with mock.patch.object(paths, "KIDS", True):
            with self.assertRaises(ValueError):
                FS.save_settings_tasks({"images": [{"role": "base", "engine": "comfyui", "workflow": "x"}]})
            with self.assertRaises(ValueError):
                FS.save_settings_tasks({"tasks": [{"task": "dialogue", "provider": "ollama"}]})

    def test_lora_strength_is_bounded(self):
        with mock.patch.object(A, "load", return_value={"version": 1, "assets": {"a": {}}}), \
                mock.patch.object(A, "save"):
            with self.assertRaises(ValueError):
                FE.set_asset_loras("a", [{"name": "x.safetensors", "strength": 5}])
            result = FE.set_asset_loras("a", [{"name": "x.safetensors", "strength": 0.7}, {"name": ""}])
        self.assertEqual(result["loras"], [{"name": "x.safetensors", "strength": 0.7, "clip": False}])


class DefaultsAndMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "app_settings.yaml"
        self.patch = mock.patch.object(paths, "app_settings_file", lambda: self.tmp)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_default_comfy_workflows_are_shipped_with_the_project(self):
        for role in ("base", "edit"):
            path = appsettings.config()["comfy_workflows"][role]
            self.assertTrue((paths.CODE / path).is_file(), path)

    def test_memory_release_follows_the_machine_setting(self):
        self.assertFalse(appsettings.comfy_free_memory())  # défaut de config.yaml
        appsettings.save({"comfy_free_memory": True})
        self.assertTrue(appsettings.comfy_free_memory())

    def test_memory_is_released_before_generation_only_when_enabled(self):
        calls = []
        with mock.patch.object(comfy_image, "free_memory", side_effect=lambda base: calls.append(base)), \
                mock.patch.object(CC, "load_workflow", side_effect=ValueError("arrêt volontaire")):
            appsettings.save({"comfy_free_memory": False})
            with self.assertRaises(ValueError):
                comfy_image.generate("wf.json", "scène", [], [], "2:3", Path(tempfile.mkdtemp()) / "o.png")
            self.assertEqual(calls, [])
            appsettings.save({"comfy_free_memory": True})
            with self.assertRaises(ValueError):
                comfy_image.generate("wf.json", "scène", [], [], "2:3", Path(tempfile.mkdtemp()) / "o.png")
            self.assertEqual(len(calls), 1)


class CreationTests(unittest.TestCase):
    STORY = {"idea": "Une jeune femme rousse aux yeux verts se promène dans les bois.", "synopsis": "",
             "settings": {"providers": {"text": "anthropic"}}, "chapters": []}

    def test_valid_descriptor_needs_a_gender_word(self):
        from renpy_maker import prompts as PR
        self.assertTrue(PR.valid_descriptor("young woman"))
        self.assertTrue(PR.valid_descriptor("adult man"))
        self.assertFalse(PR.valid_descriptor("i can't tell from the"))
        self.assertFalse(PR.valid_descriptor(""))
        self.assertFalse(PR.valid_descriptor(None))

    def test_refusal_is_not_stored_as_descriptor(self):
        from renpy_maker import prompts as PR
        with mock.patch.object(llm, "complete_task", return_value="I can't tell from the story"):
            self.assertIsNone(PR.describe_person(self.STORY, "Mara", ""))

    def test_story_is_sent_when_describing_the_person(self):
        from renpy_maker import prompts as PR
        sent = []

        def fake(task, system, user, provider=None):
            sent.append(user)
            return "young woman"

        with mock.patch.object(llm, "complete_task", side_effect=fake):
            self.assertEqual(PR.describe_person(self.STORY, "Mara", ""), "young woman")
        self.assertIn("yeux verts", sent[0])

    def test_character_request_contains_the_story_looks(self):
        from renpy_maker import prompts as PR
        assets = {"char_mara": {"kind": "character", "name": "Mara", "description": "", "prompt": "",
                                "descriptor": "young woman", "parent": None}}
        _, user = PR.build_request(self.STORY, assets, "char_mara")
        self.assertIn("yeux verts", user)

    def test_invalid_descriptor_falls_back_to_person(self):
        from renpy_maker import prompts as PR
        assets = {"char_mara": {"kind": "character", "name": "Mara", "descriptor": "i can't tell from the"}}
        self.assertEqual(PR.person_word(assets, "Mara"), "person")


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")
    return path


class StepsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "app_settings.yaml"
        self.patch = mock.patch.object(paths, "app_settings_file", lambda: self.tmp)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_default_keeps_the_workflow_steps(self):
        self.assertIsNone(appsettings.steps_for("base"))

    def test_steps_from_config_are_written_into_the_sampler(self):
        sent = {}

        def fake_run(graph, base, timeout_s=0, on_progress=None, on_submit=None):
            sent["graph"] = copy.deepcopy(graph)
            return [{"filename": "o.png", "subfolder": "", "type": "output"}]

        with mock.patch.object(CC, "load_workflow", side_effect=lambda path, base: flux_like()), \
                mock.patch.object(CC, "run", side_effect=fake_run), \
                mock.patch.object(CC, "download", side_effect=lambda files, d, base: [_write(d / "o.png")]):
            out = Path(tempfile.mkdtemp()) / "c.png"
            comfy_image.generate("wf.json", "scène", [], [], "2:3", out, seed=1, steps=12)
        self.assertEqual(sent["graph"]["46"]["inputs"]["steps"], 12)

    def test_steps_are_saved_from_the_settings_panel(self):
        FS.save_settings_tasks({"images": [{"role": "edit", "engine": "replicate", "workflow": "", "steps": "20"},
                                           {"role": "base", "engine": "replicate", "workflow": "", "steps": ""}]})
        self.assertEqual(appsettings.steps_for("edit"), 20)
        self.assertIsNone(appsettings.steps_for("base"))
        with self.assertRaises(ValueError):
            FS.save_settings_tasks({"images": [{"role": "edit", "engine": "replicate", "workflow": "", "steps": "abc"}]})

    def test_out_of_range_steps_are_refused(self):
        appsettings.save({"comfy_steps": {"base": 500}})
        with self.assertRaises(ValueError):
            appsettings.steps_for("base")


class WorkflowChoiceTests(unittest.TestCase):
    def test_all_api_workflows_of_the_folder_are_offered(self):
        names = appsettings.available_workflows()
        self.assertIn("comfy/workflows/FLUX1_API.json", names)
        self.assertIn("comfy/workflows/FLUX_REDCRAFT_RAPIDE_API.json", names)

    def test_non_api_files_are_not_offered(self):
        import tempfile
        folder = Path(tempfile.mkdtemp())
        (folder / "ui.json").write_text('{"nodes": [], "links": []}', encoding="utf-8")
        with mock.patch.object(appsettings, "WORKFLOW_DIR", folder):
            self.assertEqual(appsettings.available_workflows(), [])


class StopTests(unittest.TestCase):
    def test_stop_interrupts_comfyui_and_marks_the_job_cancelled(self):
        from renpy_maker import facile as FA2
        calls = []
        job_id = "stop-test"
        FA2.JOBS[job_id] = {"state": "running", "label": "x", "message": "", "error": None, "progress": None,
                            "cancel_requested": False, "comfy_prompt": "pid-1"}
        with mock.patch.object(CC, "interrupt", side_effect=lambda base, pid=None: calls.append(pid)):
            self.assertEqual(FJ.cancel_job(job_id), {"ok": True})
        self.assertEqual(calls, ["pid-1"])
        self.assertTrue(FA2.JOBS[job_id]["cancel_requested"])

    def test_batch_stops_before_the_next_image(self):
        from renpy_maker import facile as FA2
        job_id = "batch-test"
        FA2.JOBS[job_id] = {"state": "running", "label": "x", "message": "", "error": None, "progress": None,
                            "cancel_requested": True, "comfy_prompt": None}
        with self.assertRaises(FJ.Cancelled):
            FJ._check_cancel(job_id)


class DialogueRetryTests(unittest.TestCase):
    def _story(self):
        from renpy_maker import plan as P2
        st = {"title": "T", "idea": "i", "synopsis": "", "settings": {"providers": {"text": "anthropic"}},
              "chapters": [{"id": "ch1", "title": "C", "summary": "s", "scene_count": 1, "locked": False,
                            "scenes": [{"id": "s1", "title": "S", "summary": "x", "characters": ["Lina"],
                                        "location": "L", "outfits": {}, "choices": [], "ending": False,
                                        "locked": False, "dialogue": [], "plans": [], "decor": []}]}]}
        return st, P2

    def test_wrong_speaker_is_refused_then_retried_with_the_allowed_list(self):
        st, P2 = self._story()
        answers = [{"lines": [{"speaker": "Orgrim", "text": "Bonjour"}]},
                   {"lines": [{"speaker": "Lina", "text": "Bonjour"}]}]
        prompts = []

        def fake(task, system, user, provider=None):
            prompts.append(user)
            return json.dumps(answers.pop(0))

        with mock.patch.object(llm, "complete_task", side_effect=fake):
            lines = P2.generate_dialogue(st, "s1")
        self.assertEqual(lines[0]["speaker"], "Lina")
        self.assertEqual(len(prompts), 2)
        self.assertIn("Orgrim", prompts[1])
        self.assertIn("Lina", prompts[1].split("Les seuls locuteurs")[1])

    def test_gives_up_with_a_clear_error_after_the_attempts(self):
        st, P2 = self._story()
        with mock.patch.object(llm, "complete_task", return_value=json.dumps({"lines": [{"speaker": "Tom", "text": "x"}]})):
            with self.assertRaises(llm.LLMError) as cm:
                P2.generate_dialogue(st, "s1")
        self.assertIn("tentatives", str(cm.exception))


class ContinuityChoiceTests(unittest.TestCase):
    def _plans(self, second_text="Gros plan sur Léa, sourire"):
        sc = {"characters": ["Léa"], "outfits": {"Léa": "Robe verte"},
              "plans": [{"id": "p1", "from_line": 0, "asset": "a1", "characters": ["Léa"], "shot": {"note": "Plan large"}},
                        {"id": "p2", "from_line": 1, "asset": "a2", "characters": ["Léa"],
                         "shot": {"note": second_text}}]}
        assets = {"a1": {"validated_candidate": 0}, "a2": {"validated_candidate": 0}}
        return sc, assets

    def test_manual_inclusion_beats_continuity(self):
        sc, assets = self._plans()
        sc["plans"][1]["manual_refs"] = {"tenue:léa": False}  # l'auteur a remis la tenue à la main
        FP.apply_continuity(sc, assets)
        self.assertNotIn("tenue:léa", sc["plans"][1].get("refs_exclude", []))

    def test_manual_exclusion_is_kept(self):
        sc, assets = self._plans()
        sc["plans"][1]["manual_refs"] = {"tenue:léa": True}
        sc["plans"][1]["refs_exclude"] = ["tenue:léa"]
        FP.apply_continuity(sc, assets)
        self.assertIn("tenue:léa", sc["plans"][1]["refs_exclude"])

    def test_outfit_change_decision_keeps_the_outfit_reference(self):
        sc, assets = self._plans("Léa retire sa veste, les manches retroussées")
        sc["plans"][1]["outfit_change"] = {"hash": FP._text_hash(sc["plans"][1]["shot"]["note"]), "change": True}
        FP.apply_continuity(sc, assets)
        self.assertNotIn("tenue:léa", sc["plans"][1].get("refs_exclude", []))
        self.assertEqual(sc["plans"][1]["refs_extra"], ["a1"])  # la continuité reste utile pour l'identité

    def test_stale_decision_is_ignored(self):
        sc, assets = self._plans("Léa retire sa veste")
        sc["plans"][1]["outfit_change"] = {"hash": "ancien-texte", "change": True}  # le texte a changé depuis
        FP.apply_continuity(sc, assets)
        self.assertIn("tenue:léa", sc["plans"][1].get("refs_exclude", []))

    def test_model_decision_is_parsed_and_cached(self):
        st = {"settings": {"providers": {"text": "anthropic"}}, "chapters": []}
        sc = {"characters": ["Léa"], "plans": []}
        plans = [{"shot": {"note": "Léa retire sa veste"}}]
        calls = []

        def fake(task, system, user, provider=None):
            calls.append(task)
            return '{"change": true}'

        with mock.patch.object(llm, "complete_task", side_effect=fake):
            FP.refresh_outfit_decisions(st, sc, plans)
            FP.refresh_outfit_decisions(st, sc, plans)  # même texte : pas de nouvel appel
        self.assertEqual(calls, ["decision"])
        self.assertTrue(FP._changes_outfit(plans[0]))

    def test_unclear_answer_is_not_cached(self):
        st = {"settings": {"providers": {"text": "anthropic"}}, "chapters": []}
        plans = [{"shot": {"note": "Léa sourit"}}]
        with mock.patch.object(llm, "complete_task", return_value="peut-être"):
            FP.refresh_outfit_decisions(st, {"characters": ["Léa"]}, plans)
        self.assertNotIn("outfit_change", plans[0])

    def test_decision_task_is_configurable(self):
        import tempfile
        with mock.patch.object(paths, "app_settings_file", lambda p=Path(tempfile.mkdtemp()) / "app_settings.yaml": p):
            appsettings.save({"llm_tasks": {"decision": {"provider": "ollama", "model": "qwen3:14b"}}})
            self.assertEqual(appsettings.llm_for("decision", "anthropic"), ("ollama", "qwen3:14b"))


class OllamaUnloadTests(unittest.TestCase):
    def test_running_ollama_models_are_unloaded_with_keep_alive_zero(self):
        import json as j
        from renpy_maker import llm as L
        sent = []

        class Resp:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return self.body

        def fake_urlopen(req, timeout=0):
            url = req if isinstance(req, str) else req.full_url
            if url.endswith("/api/ps"):
                return Resp(j.dumps({"models": [{"name": "cydonia:latest"}]}).encode())
            sent.append(j.loads(req.data))
            return Resp(b"{}")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.assertEqual(L.unload_ollama_models("http://localhost:11434"), ["cydonia:latest"])
        self.assertEqual(sent, [{"model": "cydonia:latest", "keep_alive": 0}])

    def test_no_ollama_is_not_an_error(self):
        from renpy_maker import llm as L
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refusé")):
            self.assertEqual(L.unload_ollama_models("http://localhost:11434"), [])


class MemorySharingTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.patch = mock.patch.object(paths, "app_settings_file", lambda p=Path(tempfile.mkdtemp()) / "app_settings.yaml": p)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_defaults_unload_ollama_but_do_not_free_comfy(self):
        self.assertTrue(appsettings.unload_ollama_before_comfy())
        self.assertFalse(appsettings.free_comfy_before_ollama())

    def test_setting_can_be_changed_in_the_panel(self):
        FS.save_settings_tasks({"unload_ollama_before_comfy": False, "free_comfy_before_ollama": True})
        self.assertFalse(appsettings.unload_ollama_before_comfy())
        self.assertTrue(appsettings.free_comfy_before_ollama())

    def test_ollama_call_frees_comfy_only_when_enabled(self):
        calls = []
        with mock.patch.object(comfy_image, "free_memory", side_effect=lambda base: calls.append(base)), \
                mock.patch("urllib.request.urlopen", side_effect=OSError("pas de réseau")):
            appsettings.save({"free_comfy_before_ollama": False})
            with self.assertRaises(Exception):
                llm.complete("ollama", "s", "u")
            self.assertEqual(calls, [])
            appsettings.save({"free_comfy_before_ollama": True})
            with self.assertRaises(Exception):
                llm.complete("ollama", "s", "u")
            self.assertEqual(len(calls), 1)

    def test_comfy_generation_unloads_ollama_only_when_enabled(self):
        calls = []
        with mock.patch("renpy_maker.llm.unload_ollama_models", side_effect=lambda *a, **k: calls.append(1) or []), \
                mock.patch.object(CC, "load_workflow", side_effect=ValueError("arrêt volontaire")):
            appsettings.save({"unload_ollama_before_comfy": False})
            with self.assertRaises(ValueError):
                comfy_image.generate("wf.json", "scène", [], [], "2:3", Path(tempfile.mkdtemp()) / "o.png")
            self.assertEqual(calls, [])
            appsettings.save({"unload_ollama_before_comfy": True})
            with self.assertRaises(ValueError):
                comfy_image.generate("wf.json", "scène", [], [], "2:3", Path(tempfile.mkdtemp()) / "o.png")
            self.assertEqual(calls, [1])


class AnchorLoraTests(unittest.TestCase):
    def test_anchor_cards_show_their_loras(self):
        assets = {"char_lea": {"kind": "character", "name": "Léa", "status": "validated", "validated_candidate": 0,
                               "candidates": [{"file": "assets/char_lea/cand_00.png"}],
                               "loras": [{"name": "style.safetensors", "strength": 0.6, "clip": False}]}}
        card = FE._element_card(assets, "character", "Léa")
        self.assertEqual(card["loras"], [{"name": "style.safetensors", "strength": 0.6, "clip": False}])


class ComfyImageTests(unittest.TestCase):
    def setUp(self):
        self.sent = {}

        def fake_run(graph, base, timeout_s=0, on_progress=None, on_submit=None):
            self.sent["graph"] = copy.deepcopy(graph)
            return [{"filename": "sortie_00001_.png", "subfolder": "", "type": "output"}]

        def fake_download(files, out_dir, base):
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / files[0]["filename"]
            p.write_bytes(b"png")
            return [p]

        self.patches = [
            mock.patch.object(CC, "load_workflow", side_effect=lambda path, base: graph_with_reference()),
            mock.patch.object(CC, "upload_image", side_effect=lambda path, base: "up_" + Path(path).name),
            mock.patch.object(CC, "run", side_effect=fake_run),
            mock.patch.object(CC, "download", side_effect=fake_download),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.out = Path(tempfile.mkdtemp()) / "cand.png"

    def test_prompt_size_seed_and_output_are_set_by_node_type(self):
        comfy_image.generate("wf.json", "une femme au soleil", [], [], "16:9", self.out, seed=7)
        g = self.sent["graph"]
        self.assertEqual(g["42"]["inputs"]["text"], "une femme au soleil")  # prompt positif
        self.assertEqual((g["44"]["inputs"]["width"], g["44"]["inputs"]["height"]), (1344, 768))  # taille
        self.assertEqual(g["45"]["inputs"]["noise_seed"], 7)  # graine
        self.assertTrue(self.out.exists())

    def test_reference_images_go_to_load_image_nodes_in_order(self):
        refs = [Path(tempfile.mkdtemp()) / "a.png"]
        refs[0].write_bytes(b"x")
        comfy_image.generate("wf.json", "scène", refs, [], "2:3", self.out, seed=1)
        self.assertTrue(self.sent["graph"]["60"]["inputs"]["image"].startswith("up_ref0_"))

    def test_references_with_the_same_file_name_get_distinct_uploads(self):
        """Régression : trois images « cand_00.png » d'éléments différents ne doivent pas s'écraser."""
        sent = []

        def record(path, base):
            sent.append(path.name)
            return path.name

        root = Path(tempfile.mkdtemp())
        refs = []
        for folder in ("lieu", "lea", "tom"):
            (root / folder).mkdir()
            (root / folder / "cand_00.png").write_bytes(folder.encode())
            refs.append(root / folder / "cand_00.png")
        with mock.patch.object(CC, "load_workflow", side_effect=lambda path, base: with_reference_chain(3)), \
                mock.patch.object(CC, "upload_image", side_effect=record):
            comfy_image.generate("wf.json", "scène", refs, [], "2:3", self.out, seed=1)
        self.assertEqual(len(set(sent)), 3)
        self.assertEqual(len(set(self.sent["graph"][n]["inputs"]["image"] for n in ("60", "61", "62"))), 3)

    def test_too_many_references_is_refused_with_a_clear_message(self):
        refs = [Path(tempfile.mkdtemp()) / f"{i}.png" for i in range(2)]
        for r in refs:
            r.write_bytes(b"x")
        with self.assertRaises(ValueError) as cm:
            comfy_image.generate("wf.json", "scène", refs, [], "2:3", self.out)
        self.assertIn("1 image(s) de référence", str(cm.exception))

    def test_loras_are_inserted_before_sending(self):
        comfy_image.generate("wf.json", "scène", [], [{"name": "style.safetensors", "strength": 0.6}],
                             "2:3", self.out, seed=1)
        classes = [n["class_type"] for n in self.sent["graph"].values()]
        self.assertIn("LoraLoaderModelOnly", classes)

    def test_missing_workflow_is_refused(self):
        with self.assertRaises(ValueError):
            comfy_image.generate(None, "scène", [], [], "2:3", self.out)


if __name__ == "__main__":
    unittest.main()
