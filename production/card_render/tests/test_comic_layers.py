from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import render_comic_cards as comic  # noqa: E402


class ComicNativeLayerExportTests(unittest.TestCase):
    def test_crop_uses_only_the_native_alpha_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "full.png"
            target = root / "crop.png"
            image = Image.new("RGBA", (12, 10), (0, 0, 0, 0))
            image.paste((20, 30, 40, 255), (3, 4, 8, 9))
            image.save(source)

            self.assertEqual(comic._write_crop(source, target), [3, 4, 5, 5])
            with Image.open(target) as cropped:
                self.assertEqual(cropped.mode, "RGBA")
                self.assertEqual(cropped.size, (5, 5))

    def test_native_export_has_ordered_transparent_layers_and_no_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".tesseract-work").mkdir()
            stem = "01-cover"
            source = root / f"{stem}.png"
            background = Image.new("RGBA", (comic.WIDTH, comic.HEIGHT), (240, 230, 255, 255))
            top = Image.new("RGBA", (comic.WIDTH, comic.HEIGHT), (0, 0, 0, 0))
            top.paste((10, 20, 30, 255), (40, 50, 120, 100))
            expected = Image.alpha_composite(background, top)
            expected.save(source)
            document = {"composition": {"layers": [
                {"id": 2, "type": "Text", "name": "페이지 번호", "transform": {"opacity": 100},
                 "sourceText": {"text": "1/4"}},
                {"id": 1, "type": "Image", "name": comic.BACKGROUND_LAYER_NAME,
                 "transform": {"opacity": 100}},
                {"id": 3, "type": "Text", "name": "빈 레이어", "transform": {"opacity": 100},
                 "sourceText": {"text": "보이지 않음"}},
            ]}}

            def native_preview(_command: str, _project: Path, _document: dict,
                               visible_id: int, _work: Path, output: Path) -> None:
                (background if visible_id == 1 else top if visible_id == 2
                 else Image.new("RGBA", (comic.WIDTH, comic.HEIGHT), (0, 0, 0, 0))).save(output)

            with mock.patch.object(comic, "_clone_for_layer_export", return_value=document), \
                    mock.patch.object(comic, "_preview_native_layer", side_effect=native_preview):
                manifest = comic.export_native_layers("tsrct", root, root / "source.tsrct",
                                                      source, stem, 1)

            self.assertEqual(manifest["provenance"], "tesseract_native")
            self.assertEqual(manifest["background"]["file"], "source-layers/page-01/background.png")
            self.assertEqual(manifest["layers"][0]["name"], "페이지 번호")
            self.assertEqual(manifest["layers"][0]["role"], "text")
            self.assertEqual(manifest["layers"][0]["text"], "1/4")
            self.assertFalse(manifest["layers"][0]["moving"])
            self.assertEqual(manifest["layers"][0]["box"], [40, 50, 80, 50])
            self.assertFalse((root / "source-layers/page-01/layer-001.png").exists())
            self.assertEqual(manifest["layers"][0]["file"], "source-layers/page-01/layer-002.png")
            with Image.open(root / manifest["layers"][0]["file"]) as layer:
                self.assertEqual(layer.mode, "RGBA")
            saved = json.loads((root / f"{stem}.layers.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["source_sha256"], comic._sha256(source))
            self.assertEqual(document["composition"]["layers"][0].get("isHidden"), None)

    def test_isolation_hides_every_other_native_layer_without_editing_source(self) -> None:
        document = {"composition": {"layers": [
            {"id": 1, "name": "front"}, {"id": 2, "name": "back"},
        ]}}
        isolated = comic._isolated_document(document, 2)
        self.assertTrue(isolated["composition"]["layers"][0]["isHidden"])
        self.assertFalse(isolated["composition"]["layers"][1]["isHidden"])
        self.assertNotIn("isHidden", document["composition"]["layers"][0])

    def test_motion_marks_every_semantic_layer_except_the_page_chip(self) -> None:
        self.assertTrue(comic._moving({"name": "큰 제목"}))
        self.assertTrue(comic._moving({"name": "비교 결론 말풍선"}))
        self.assertFalse(comic._moving({"name": "페이지 번호"}))
        self.assertFalse(comic._moving({"name": "페이지 번호 알약"}))

    def test_reconstruction_metrics_preserve_small_antialias_evidence(self) -> None:
        original = Image.new("RGBA", (10, 10), (20, 30, 40, 255))
        recomposed = original.copy()
        recomposed.putpixel((4, 4), (21, 30, 40, 255))
        metrics = comic._reconstruction_metrics(original, recomposed)
        self.assertEqual(metrics["max_error"], 1)
        self.assertEqual(metrics["significant_share"], 0)
        self.assertGreater(metrics["mean_error"], 0)

    def test_missing_panel_is_not_accepted_by_shared_reconstruction_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = root / "source-layers" / "page-01"
            page.mkdir(parents=True)
            source = root / "01-cover.png"
            background = page / "background.png"
            Image.new("RGBA", (80, 80), (245, 245, 245, 255)).save(background)
            card = Image.open(background).copy()
            card.paste((50, 20, 150, 255), (10, 10, 70, 70))
            card.save(source)

            with self.assertRaisesRegex(RuntimeError, "원본 카드와 일치하지 않습니다"):
                comic._verify_reconstruction(source, background, [], root)
            diagnostic = json.loads((page / "diagnostic.json").read_text(encoding="utf-8"))
            self.assertGreater(diagnostic["metrics"]["mean_error"], .2)
            self.assertGreater(diagnostic["metrics"]["significant_share"], .001)


if __name__ == "__main__":
    unittest.main()
