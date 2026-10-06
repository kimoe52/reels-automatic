"""Real pixel fixtures for the source-layer contract; no GPU/network needed."""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_layers import LayerRepairRequired, load_source_card, prepare_source_layers
from auto_plan import plan_package
from native_focus import Deck
from element_layers import parse_elements
module_spec = importlib.util.spec_from_file_location("source_layer_build_ready", Path(__file__).resolve().parents[1] / "build_ready.py")
build_ready = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(build_ready)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root, text="제목"):
    background = root / "bg.png"
    Image.new("RGBA", (200, 250), "white").save(background)
    moving = root / "moving.png"
    Image.new("RGBA", (80, 70), "blue").save(moving)
    static = root / "static.png"
    Image.new("RGBA", (50, 50), "red").save(static)
    source = root / "card.png"
    composite = Image.open(background).copy()
    composite.alpha_composite(Image.open(moving), (20, 30))
    composite.alpha_composite(Image.open(static), (40, 50))
    composite.save(source)
    data = {"version": 1, "source_file": source.name, "source_sha256": sha(source), "size": [200, 250],
            "background": {"file": background.name, "sha256": sha(background)},
            "layers": [{"name": "moving", "file": moving.name, "sha256": sha(moving),
                        "box": [20, 30, 80, 70], "z_index": 0, "moving": True, "role": "title", "text": text},
                       {"name": "annotation", "file": static.name, "sha256": sha(static),
                        "box": [40, 50, 50, 50], "z_index": 1, "moving": False, "role": "text"}]}
    metadata = root / "card.layers.json"
    save(metadata, data)
    return source, metadata, data


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False))


def package(root, source, metadata):
    manifest = root / "reel-production.json"
    save(manifest, {"version": 4, "renderer": "hyperframes_element_story", "deck_title": "검증 카드",
                    "reviewed": True, "source_approved": True, "audio_decision": "sfx_only",
                    "cards": [{"file": source.name, "source_sha256": sha(source),
                               "layers_file": metadata.name, "source_layers_sha256": sha(metadata)} for _ in range(4)]})
    return manifest


class SourceContractTest(unittest.TestCase):
    def test_original_and_overlap_order_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, metadata, _ = fixture(root)
            card = load_source_card(metadata, source, sha(metadata))
            report = prepare_source_layers(card, card.elements(), root / "out")
            composite = Image.open(root / "out" / report["clean_plate"]).copy()
            for layer in report["elements"]:
                composite.alpha_composite(Image.open(root / "out" / layer["file"]), tuple(layer["box"][:2]))
            self.assertIsNone(ImageChops.difference(composite.convert("RGB"), Image.open(source).convert("RGB")).getbbox())
            self.assertFalse(report["elements"][-1]["moving"])

    def test_mutated_asset_cannot_reuse_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, metadata, _ = fixture(root)
            Image.new("RGBA", (80, 70), "green").save(root / "moving.png")
            with self.assertRaisesRegex(LayerRepairRequired, "해시"):
                load_source_card(metadata, source)

    def test_missing_or_wrong_order_layer_cannot_reconstruct(self):
        for mutation in ("missing", "order"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source, metadata, data = fixture(root)
                if mutation == "missing":
                    data["layers"].pop()
                else:
                    data["layers"][0]["z_index"], data["layers"][1]["z_index"] = 1, 0
                save(metadata, data)
                with self.assertRaisesRegex(LayerRepairRequired, "재합성"):
                    load_source_card(metadata, source)

    def test_opaque_rgb_is_not_a_transparent_source_layer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, metadata, data = fixture(root)
            Image.new("RGB", (80, 70), "blue").save(root / "moving.png")
            data["layers"][0]["sha256"] = sha(root / "moving.png"); save(metadata, data)
            with self.assertRaisesRegex(LayerRepairRequired, "RGBA"):
                load_source_card(metadata, source)

    def test_metadata_approval_and_external_paths_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, metadata, data = fixture(root)
            with self.assertRaisesRegex(LayerRepairRequired, "승인 해시"):
                load_source_card(metadata, source, "unapproved")
            data["layers"][0]["file"] = "../outside.png"; save(metadata, data)
            with self.assertRaisesRegex(LayerRepairRequired, "폴더 밖"):
                load_source_card(metadata, source)

    def test_transparent_holes_cannot_match_an_opaque_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, metadata, data = fixture(root)
            bg = Image.open(root / "bg.png").copy(); bg.putpixel((199, 249), (255, 255, 255, 0)); bg.save(root / "bg.png")
            data["background"]["sha256"] = sha(root / "bg.png"); save(metadata, data)
            with self.assertRaisesRegex(LayerRepairRequired, "투명도"):
                load_source_card(metadata, source)

    def test_source_masks_require_validated_assets(self):
        raw = [{"name": "line", "box": [0, 0, 50, 1], "mask": "source", "delay_ms": 0}]
        with self.assertRaises(ValueError):
            parse_elements(raw, (200, 250), 1)
        self.assertEqual(parse_elements(raw, (200, 250), 1, allow_source=True)[0].box, (0, 0, 50, 1))

    def test_plan_coverage_and_authored_timing_are_bound_to_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, metadata, _ = fixture(root)
            manifest = package(root, source, metadata); plan_package(manifest)
            data = json.loads(manifest.read_text())
            data["cards"][0]["motion_elements"][0]["delay_ms"] = 700
            data["cards"][0]["motion_elements"][0]["effect"] = "fade"
            save(manifest, data); before = manifest.read_bytes(); plan_package(manifest, force=True)
            self.assertEqual(manifest.read_bytes(), before)
            self.assertEqual(Deck(manifest).pages[0].elements[0].delay_ms, 700)
            data["cards"][0]["motion_elements"][0]["name"] = "not-the-original"
            save(manifest, data)
            with self.assertRaisesRegex(ValueError, "모든 이동 요소"):
                Deck(manifest)

    def test_longer_original_copy_gets_more_reading_time(self):
        times = []
        for text in ("제목", "읽어야 할 정보 " * 35):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source, metadata, _ = fixture(root, text)
                manifest = package(root, source, metadata); plan_package(manifest)
                times.append(json.loads(manifest.read_text())["cards"][0]["duration_ms"])
        self.assertGreater(times[1], times[0])
        self.assertGreater(times[1], 14000)

    def test_failed_separation_replaces_stale_success_without_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, metadata, _ = fixture(root)
            manifest = package(root, source, metadata)
            marker = root / "renders/latest.json"; marker.parent.mkdir()
            save(marker, {"status": "ready_for_review", "video": "old.mp4"})
            (root / "moving.png").unlink()
            with patch.object(build_ready, "create_hyperframes_project") as renderer:
                result = build_ready.build_hyperframes(manifest)
            renderer.assert_not_called()
            self.assertEqual(result["status"], "needs_layer_repair")
            self.assertEqual(json.loads(marker.read_text())["status"], "needs_layer_repair")
            self.assertNotIn("video", result)


if __name__ == "__main__":
    unittest.main()
