"""Background recovery must be color-agnostic and source-verified."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from element_layers import Element, prepare_layers
from auto_plan import _tight_source_box


class SourceMatteTest(unittest.TestCase):
    def test_mint_field_is_not_replaced_by_lavender(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "card.png"
            image = Image.new("RGB", (200, 250), (219, 241, 226))
            ImageDraw.Draw(image).rectangle((70, 80, 120, 110), fill="black")
            image.save(source)
            report = prepare_layers(source, (
                Element("title", (50, 60, 95, 75), "region", 0, repair=True),
            ), root / "layers")
            plate = Image.open(root / "layers" / report["clean_plate"])
            self.assertEqual(plate.getpixel((90, 90)), (219, 241, 226))

    def test_precise_source_patch_preserves_a_patterned_background(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "01-cover.png"
            field = Image.new("RGB", (200, 250), "#faf1dc")
            draw = ImageDraw.Draw(field)
            for x in range(0, 200, 12):
                draw.line((x, 0, x, 249), fill="#c7e4d2", width=3)
            image = field.copy()
            ImageDraw.Draw(image).rounded_rectangle((62, 72, 117, 107), 9, fill="black")
            image.save(source)
            field.crop((50, 60, 140, 125)).save(root / "background.png")
            (root / "layout.json").write_text(json.dumps({"cards": [{
                "file": source.name, "boxes": [{"name": "title",
                "box": [50, 60, 140, 125], "background_file": "background.png",
                "background_sha256": hashlib.sha256((root / "background.png").read_bytes()).hexdigest(),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]
            }]}))
            report = prepare_layers(source, (
                Element("title", (50, 60, 90, 65), "region", 0, repair=True),
            ), root / "layers")
            layer = report["elements"][0]
            self.assertEqual(layer["background_method"], "source_layers")
            plate = Image.open(root / "layers" / report["clean_plate"])
            self.assertEqual(plate.tobytes(), field.tobytes())
            matte = Image.open(root / "layers" / layer["file"])
            self.assertEqual(matte.getpixel((5, 5))[3], 0)
            self.assertEqual(matte.getpixel((35, 30))[3], 255)
            trimmed = _tight_source_box(source, "title", [50, 60, 90, 65])
            self.assertEqual(trimmed, [60, 70, 60, 40])
            trimmed_report = prepare_layers(source, (
                Element("title", tuple(trimmed), "region", 0, repair=True),
            ), root / "trimmed")
            self.assertEqual(trimmed_report["elements"][0]["background_method"], "source_layers")
            self.assertEqual(Image.open(root / "trimmed" / trimmed_report["clean_plate"]).tobytes(), field.tobytes())

    def test_stale_precise_background_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "01-cover.png"
            Image.new("RGB", (200, 250), "white").save(source)
            Image.new("RGB", (90, 65), "white").save(root / "background.png")
            (root / "layout.json").write_text(json.dumps({"cards": [{
                "file": source.name, "boxes": [{"name": "title",
                "box": [50, 60, 140, 125], "background_file": "background.png",
                "source_sha256": "outdated"}]
            }]}))
            with self.assertRaisesRegex(ValueError, "해시"):
                prepare_layers(source, (
                    Element("title", (50, 60, 90, 65), "region", 0),
                ), root / "layers")

    def test_tampered_precise_background_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, background = root / "card.png", root / "background.png"
            Image.new("RGB", (200, 250), "white").save(source)
            Image.new("RGB", (90, 65), "white").save(background)
            (root / "layout.json").write_text(json.dumps({"cards": [{
                "file": source.name, "boxes": [{"name": "title",
                "box": [50, 60, 140, 125], "background_file": background.name,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "background_sha256": hashlib.sha256(background.read_bytes()).hexdigest()}]
            }]}))
            Image.new("RGB", (90, 65), "black").save(background)
            with self.assertRaisesRegex(ValueError, "파일 해시"):
                prepare_layers(source, (
                    Element("title", (50, 60, 90, 65), "region", 0),
                ), root / "layers")


if __name__ == "__main__":
    unittest.main()
