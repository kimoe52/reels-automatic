"""Small source-layer handoff checks; no renderer or browser required."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "production" / "card_motion"))
from source_layers import load_source_card, prepare_source_layers  # noqa: E402
from auto_plan import plan_package  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SourceLayerHandoffTest(unittest.TestCase):
    def test_auto_flat_import_requires_layer_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); image = root / "card.png"
            Image.new("RGB", (800, 1000), "white").save(image)
            manifest = root / "reel-production.json"
            manifest.write_text(json.dumps({"source_approved": True, "cards": [{"file": "card.png"}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "원본 레이어"):
                plan_package(manifest)

    def test_static_and_moving_overlap_keep_background_unbaked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            background = root / "bg.png"; Image.new("RGBA", (100, 100), "white").save(background)
            static = root / "static.png"; Image.new("RGBA", (50, 50), (255, 0, 0, 255)).save(static)
            moving = root / "moving.png"; Image.new("RGBA", (50, 50), (0, 0, 255, 255)).save(moving)
            original = Image.new("RGBA", (100, 100), "white")
            original.alpha_composite(Image.open(static), (10, 10)); original.alpha_composite(Image.open(moving), (30, 30))
            source = root / "card.png"; original.save(source)
            meta = {"version": 1, "source_file": source.name, "source_sha256": sha(source), "size": [100, 100],
                    "background": {"file": background.name, "sha256": sha(background)}, "provenance": "test",
                    "layers": [{"name": "static", "role": "panel", "file": static.name, "sha256": sha(static),
                                "box": [10, 10, 50, 50], "z_index": 0, "moving": False},
                               {"name": "moving", "role": "title", "file": moving.name, "sha256": sha(moving),
                                "box": [30, 30, 50, 50], "z_index": 1, "moving": True}]}
            metadata = root / "card.layers.json"; metadata.write_text(json.dumps(meta), encoding="utf-8")
            card = load_source_card(metadata, source)
            report = prepare_source_layers(card, card.elements(), root / "out")
            self.assertEqual(len(report["elements"]), 2)
            self.assertFalse(report["elements"][0]["moving"])
            self.assertEqual(Image.open(root / "out" / "clean-plate.png").getpixel((20, 20)), (255, 255, 255, 255))


if __name__ == "__main__":
    unittest.main()
