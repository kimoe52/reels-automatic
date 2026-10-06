from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

MOTION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MOTION))
from auto_plan import _content_paced_timing, analyse_card, plan_package  # noqa: E402
from source_layers import LayerRepairRequired  # noqa: E402


def card(path: Path, variant: int) -> None:
    image = Image.new("RGB", (800, 1000), (220, 190, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 70, 610 if variant == 1 else 430, 180), fill=(15, 12, 18))
    draw.rounded_rectangle((70, 270, 360, 440), 30, fill="white")
    if variant == 1: draw.rounded_rectangle((430, 270, 730, 440), 30, fill="white")
    image.save(path)


class AutoPlanTest(unittest.TestCase):
    def manifest(self, root: Path, reviewed: bool = False) -> Path:
        inputs = root / "Inputs"; inputs.mkdir(); card(inputs / "one.png", 1); card(inputs / "two.png", 2)
        path = root / "reel-production.json"
        path.write_text(json.dumps({"deck_title": "test", "reviewed": reviewed, "cards": [{"file": "Inputs/one.png"}, {"file": "Inputs/two.png"}]}), encoding="utf-8")
        return path

    def test_content_changes_change_counts_and_paced_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.manifest(Path(temporary))
            with self.assertRaises(LayerRepairRequired):
                plan_package(path)
            # Dense copy must get more time; sparse shape-only cards can both
            # legitimately land on the minimum readable duration.
            def reading_copy(source, size):
                text = "explanation " * (20 if source.name == "one.png" else 2)
                return [(text, [60, 70, 350, 110])], {"available": True}
            with patch("auto_plan._ocr", side_effect=reading_copy):
                first, one = analyse_card(path.parent / "Inputs" / "one.png", path)
                second, two = analyse_card(path.parent / "Inputs" / "two.png", path)
            self.assertGreater(one["duration_ms"], two["duration_ms"])

    def test_dense_copy_is_read_after_settle_without_a_fourteen_second_cap(self) -> None:
        duration, timing = _content_paced_timing(500, 900)
        self.assertGreater(duration, 14_000)
        self.assertEqual(timing["reveal_complete_ms"], 1_500)
        self.assertEqual(timing["reading_ms"], 58_824)
        self.assertEqual(duration, timing["reveal_complete_ms"] + timing["reading_ms"] + timing["hold_ms"])

    def test_headline_only_cover_uses_the_two_second_default(self) -> None:
        duration, timing = _content_paced_timing(34, 800, is_cover=True)
        self.assertEqual(duration, 2_000)
        self.assertEqual(timing["policy"], "cover_default_2s")

    def test_information_heavy_first_card_is_not_forced_to_cover_length(self) -> None:
        duration, timing = _content_paced_timing(500, 0, is_cover=True)
        self.assertGreater(duration, 14_000)
        self.assertEqual(timing["policy"], "content_reading_after_settle_v2")

    def test_short_first_page_explanation_still_gets_reading_time(self) -> None:
        duration, timing = _content_paced_timing(77, 850, is_cover=True, has_body_copy=True)
        self.assertGreater(duration, 2_000)
        self.assertGreater(timing["reading_ms"], 0)
        self.assertEqual(timing["policy"], "content_reading_after_settle_v2")

    def test_regions_do_not_overlap_and_detect_two_panels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.manifest(Path(temporary)); elements, _ = analyse_card(path.parent / "Inputs" / "one.png", path)
            self.assertGreaterEqual(len(elements), 3)
            self.assertTrue(all(item["mask"] == "region" for item in elements))
            for index, one in enumerate(elements):
                x, y, w, h = one["box"]
                for two in elements[index + 1:]:
                    a, b, c, d = two["box"]
                    self.assertFalse(x < a + c + 8 and x + w + 8 > a and y < b + d + 8 and y + h + 8 > b)

    def test_reviewed_manual_plan_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.manifest(Path(temporary), reviewed=True); original = json.loads(path.read_text())
            original["cards"][0]["motion_elements"] = [{"name": "manual", "box": [1, 1, 30, 30]}]
            path.write_text(json.dumps(original), encoding="utf-8")
            plan_package(path)
            self.assertEqual(json.loads(path.read_text())["cards"][0]["motion_elements"], original["cards"][0]["motion_elements"])

    def test_matching_dom_layout_boxes_are_named_and_scaled_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path = self.manifest(root)
            layout = root / "card-render" / "cards" / "layout.json"; layout.parent.mkdir(parents=True)
            layout.write_text(json.dumps({"cards": [{"file": "one.png", "boxes": [
                {"name": "comparison-left", "box": [54, 270, 486, 675], "radius": 20},
                {"name": "comparison-right", "box": [540, 270, 972, 675], "radius": 20}]}]}), encoding="utf-8")
            elements, _ = analyse_card(root / "Inputs" / "one.png", path)
            self.assertIn("comparison-left", [item["name"] for item in elements])
            left = next(item for item in elements if item["name"] == "comparison-left")
            self.assertEqual(left["box"][:2], [54, 270])


if __name__ == "__main__": unittest.main()
