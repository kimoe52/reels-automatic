"""Changed inputs must not revive stale plans or overwrite authored edits."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auto_plan


class AutoPlanSafetyTest(unittest.TestCase):
    def package(self, root):
        image = root / "card.png"
        background = root / "background.png"; Image.new("RGBA", (200, 250), "#dcefdc").save(background)
        layer = root / "title.png"; Image.new("RGBA", (120, 40), (20, 40, 80, 255)).save(layer)
        canvas = Image.open(background).copy(); canvas.alpha_composite(Image.open(layer), (20, 30)); canvas.convert("RGB").save(image)
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        metadata = root / "card.layers.json"
        metadata.write_text(json.dumps({"version": 1, "source_file": image.name,
            "source_sha256": digest(image), "size": [200, 250],
            "background": {"file": background.name, "sha256": digest(background)},
            "layers": [{"name": "title", "role": "title", "file": layer.name,
                        "sha256": digest(layer), "box": [20, 30, 120, 40], "z_index": 0,
                        "moving": True, "text": "짧은 제목"}], "provenance": "test"}))
        manifest = root / "reel-production.json"
        manifest.write_text(json.dumps({"cards": [{"file": image.name, "layers_file": metadata.name,
            "source_sha256": digest(image), "source_layers_sha256": digest(metadata)}]}))
        return manifest, image

    def analysis(self, elements=None):
        elements = elements if elements is not None else [{
            "name": "title", "box": [20, 30, 140, 50], "mask": "region",
            "delay_ms": 0, "repair": True, "role": "title", "effect": "settle_fade"}]
        return elements, {"duration_ms": 3200, "timing": {"settle_ms": 480, "hold_ms": 2720}}

    def test_changed_image_without_safe_regions_clears_old_auto_elements(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest, image = self.package(Path(temporary))
            with patch.object(auto_plan, "analyse_card", return_value=self.analysis()):
                auto_plan.plan_package(manifest)
            Image.new("RGB", (200, 250), "white").save(image)
            with self.assertRaisesRegex(ValueError, "승인된 원본|레이어"):
                auto_plan.plan_package(manifest)

    def test_manual_edit_to_auto_plan_survives_force(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest, _ = self.package(Path(temporary))
            with patch.object(auto_plan, "analyse_card", return_value=self.analysis()):
                auto_plan.plan_package(manifest)
            data = json.loads(manifest.read_text())
            data["cards"][0]["duration_ms"] = 9000
            manifest.write_text(json.dumps(data))
            original = manifest.read_bytes()
            with patch.object(auto_plan, "analyse_card") as analyse:
                auto_plan.plan_package(manifest, force=True)
                analyse.assert_not_called()
            self.assertEqual(manifest.read_bytes(), original)

    def test_fallback_layout_change_replans_even_when_image_does_not_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, _ = self.package(root)
            layout = root / "card-render" / "cards" / "layout.json"
            layout.parent.mkdir(parents=True)
            layout.write_text('{"cards": []}')
            with patch.object(auto_plan, "analyse_card", return_value=self.analysis()):
                auto_plan.plan_package(manifest)
                first = json.loads(manifest.read_text())["motion_plan"]["input_signature"]
                layout.write_text('{"cards": [], "changed": true}')
                auto_plan.plan_package(manifest)
            self.assertNotEqual(json.loads(manifest.read_text())["motion_plan"]["input_signature"], first)

    def test_previous_auto_timing_policy_is_replanned(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest, _ = self.package(Path(temporary))
            auto_plan.plan_package(manifest)
            data = json.loads(manifest.read_text())
            data["motion_plan"]["code_version"] = "auto-plan-previous"
            manifest.write_text(json.dumps(data))
            auto_plan.plan_package(manifest)
            refreshed = json.loads(manifest.read_text())
            self.assertEqual(refreshed["motion_plan"]["code_version"], auto_plan.CODE_VERSION)
            self.assertEqual(refreshed["cards"][0]["motion_timing"]["policy"], "cover_default_2s")

    def test_unsafe_external_image_is_never_hashed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.png"
            Image.new("RGB", (200, 250), "white").save(outside)
            package = root / "package"
            package.mkdir()
            manifest = package / "reel-production.json"
            with patch.object(auto_plan, "_sha", return_value="safe") as digest:
                auto_plan._input_signature(manifest, [{"file": "../outside.png"}])
            self.assertNotIn(outside, [call.args[0] for call in digest.call_args_list])

    def test_source_hash_mismatch_stops_without_writing_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest, _ = self.package(Path(temporary))
            data = json.loads(manifest.read_text())
            data["cards"][0]["source_sha256"] = "outdated"
            manifest.write_text(json.dumps(data))
            original = manifest.read_bytes()
            with self.assertRaisesRegex(ValueError, "승인된 원본"):
                auto_plan.plan_package(manifest)
            self.assertEqual(manifest.read_bytes(), original)

    def test_supplied_dom_boxes_require_matching_source_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest, image = self.package(Path(temporary))
            boxes = [{"name": "title", "box": [20, 30, 160, 80], "source_sha256": "old"}]
            self.assertEqual(auto_plan._layout_regions(manifest, image, (200, 250), boxes), [])
            boxes[0]["source_sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
            self.assertEqual(auto_plan._layout_regions(manifest, image, (200, 250), boxes),
                             [("title", [20, 30, 140, 50])])

    def test_small_body_words_count_toward_reading_time(self):
        result = type("Result", (), {"returncode": 0, "stdout":
            "header\n5\t1\t1\t1\t1\t1\t10\t20\t18\t16\t90\tbody\n"})()
        with patch.object(auto_plan.subprocess, "run", return_value=result):
            lines, metadata = auto_plan._ocr(Path("small-body.png"), (200, 250))
        self.assertEqual(lines[0][0], "body")
        self.assertEqual(metadata["words"], 1)


if __name__ == "__main__":
    unittest.main()
