"""Graphe ComfyUI : rôles par type de nœud, insertion de LoRA. Un petit graphe de référence, sans réseau."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import comfy_graph as CG  # noqa: E402


def flux_like() -> dict:
    """Structure d'un workflow FLUX : numéros de nœuds quelconques, volontairement non standard."""
    return {
        "40": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux.safetensors", "weight_dtype": "default"}},
        "41": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "t5.safetensors", "clip_name2": "clip_l.safetensors", "type": "flux"}},
        "42": {"class_type": "CLIPTextEncode", "inputs": {"text": "une femme", "clip": ["41", 0]}},
        "43": {"class_type": "CLIPTextEncode", "inputs": {"text": "flou", "clip": ["41", 0]}},
        "44": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 768, "batch_size": 1}},
        "45": {"class_type": "RandomNoise", "inputs": {"noise_seed": 42}},
        "46": {"class_type": "BasicScheduler", "inputs": {"scheduler": "simple", "steps": 20, "denoise": 1.0, "model": ["40", 0]}},
        "47": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "48": {"class_type": "CFGGuider", "inputs": {"model": ["40", 0], "positive": ["42", 0], "negative": ["43", 0], "cfg": 1.0}},
        "49": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["45", 0], "guider": ["48", 0], "sampler": ["47", 0], "sigmas": ["46", 0], "latent_image": ["44", 0]}},
        "50": {"class_type": "VAEDecode", "inputs": {"samples": ["49", 0], "vae": ["51", 0]}},
        "51": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "52": {"class_type": "SaveImage", "inputs": {"images": ["50", 0], "filename_prefix": "out"}},
    }


class RolesTests(unittest.TestCase):
    def test_roles_are_found_by_node_type_not_by_number(self):
        r = CG.roles(flux_like())
        self.assertEqual(r["positive_prompt"], ["42"])
        self.assertEqual(r["negative_prompt"], ["43"])
        self.assertEqual(r["model"], ["40"])
        self.assertEqual(r["clip"], ["41"])
        self.assertEqual(r["latent_size"], ["44"])
        self.assertEqual(r["seed"], ["45"])
        self.assertEqual(r["steps"], ["46"])
        self.assertEqual(r["outputs"], ["52"])

    def test_description_lists_roles_and_nodes(self):
        text = CG.describe(flux_like())
        self.assertIn("positive_prompt", text)
        self.assertIn("[40] UNETLoader", text)
        self.assertIn("steps=20", text)

    def test_check_reports_links_to_missing_nodes(self):
        g = flux_like()
        g["50"]["inputs"]["vae"] = ["999", 0]
        self.assertTrue(any("999" in p for p in CG.check(g)))
        self.assertEqual(CG.check(flux_like()), [])


class LoraTests(unittest.TestCase):
    def test_loras_are_chained_after_the_model_loader(self):
        g = flux_like()
        out = CG.insert_loras(g, [("style.safetensors", 0.8), ("skin.safetensors", 0.5)])
        new = [k for k in out if k not in g]
        self.assertEqual(len(new), 2)
        first, second = new
        self.assertEqual(out[first]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(out[first]["inputs"]["model"], ["40", 0])
        self.assertEqual(out[second]["inputs"]["model"], [first, 0])
        self.assertAlmostEqual(out[second]["inputs"]["strength_model"], 0.5)

    def test_every_model_consumer_uses_the_last_lora(self):
        out = CG.insert_loras(flux_like(), [("style.safetensors", 0.8)])
        last = [k for k in out if k not in flux_like()][0]
        self.assertEqual(out["46"]["inputs"]["model"], [last, 0])
        self.assertEqual(out["48"]["inputs"]["model"], [last, 0])
        self.assertEqual(CG.check(out), [])

    def test_original_graph_is_not_modified(self):
        g = flux_like()
        CG.insert_loras(g, [("style.safetensors", 0.8)])
        self.assertEqual(g, flux_like())

    def test_clip_variant_rewires_text_encoders(self):
        out = CG.insert_loras(flux_like(), [("style.safetensors", 0.8)], with_clip=True)
        new = [k for k in out if k not in flux_like()][0]
        self.assertEqual(out[new]["class_type"], "LoraLoader")
        self.assertEqual(out["42"]["inputs"]["clip"], [new, 1])
        self.assertEqual(out["43"]["inputs"]["clip"], [new, 1])

    def test_without_model_loader_is_an_error(self):
        g = {"1": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}}}
        with self.assertRaises(ValueError):
            CG.insert_loras(g, [("x.safetensors", 1.0)])


if __name__ == "__main__":
    unittest.main()


def with_reference_chain(slots: int = 3) -> dict:
    """Workflow de retouche : emplacements LoadImage → mise à l'échelle → VAEEncode → ReferenceLatent chaîné."""
    g = flux_like()
    prev = ["42", 0]
    for i in range(slots):
        load, scale, enc, ref = str(60 + i), str(63 + i), str(66 + i), str(70 + i)
        g[load] = {"class_type": "LoadImage", "inputs": {"image": "vide.png"}}
        g[scale] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [load, 0], "megapixels": 1.0}}
        g[enc] = {"class_type": "VAEEncode", "inputs": {"pixels": [scale, 0], "vae": ["51", 0]}}
        g[ref] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": prev, "latent": [enc, 0]}}
        prev = [ref, 0]
    g["48"]["inputs"]["positive"] = prev   # le guidage reçoit le prompt avec toutes les références
    return g


class PruneTests(unittest.TestCase):
    def test_unused_slots_and_their_nodes_are_removed(self):
        g = CG.prune_unused_references(with_reference_chain(3), keep=1)
        self.assertEqual(CG.roles(g)["reference_images"], ["60"])
        self.assertFalse(any(k in g for k in ("61", "62", "64", "65", "67", "68", "71", "72")))
        self.assertEqual(CG.check(g), [])

    def test_guidance_is_rewired_to_the_last_kept_reference(self):
        g = CG.prune_unused_references(with_reference_chain(3), keep=2)
        self.assertEqual(g["48"]["inputs"]["positive"], ["71", 0])   # 2e référence gardée
        self.assertEqual(g["71"]["inputs"]["conditioning"], ["70", 0])

    def test_no_reference_removes_the_whole_chain_and_keeps_the_prompt(self):
        g = CG.prune_unused_references(with_reference_chain(2), keep=0)
        self.assertEqual(g["48"]["inputs"]["positive"], ["42", 0])
        self.assertEqual(CG.roles(g)["reference_images"], [])
        self.assertEqual(CG.check(g), [])

    def test_all_slots_used_changes_nothing(self):
        original = with_reference_chain(2)
        self.assertEqual(CG.prune_unused_references(original, keep=2), original)
