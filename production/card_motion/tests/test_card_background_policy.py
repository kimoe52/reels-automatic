"""Card-specific 9:16 backgrounds must follow the reviewed input card."""

from __future__ import annotations

import colorsys
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageChops


MOTION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MOTION))

from element_layers import Element, prepare_layers, prepare_vertical_stage  # noqa: E402
from hyperframes_renderer import create_project  # noqa: E402
from native_focus import Deck  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _card(path: Path, field: tuple[int, int, int], accent: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (400, 500), field)
    draw = ImageDraw.Draw(image)
    # These are real card pixels, used only to make an ordinary automated card
    # with a title layer and a card-specific cloud/gradient treatment.
    draw.ellipse((-40, 350, 250, 560), fill=tuple(min(255, value + 14) for value in field))
    draw.ellipse((170, 330, 470, 550), fill=tuple(max(0, value - 12) for value in field))
    draw.rounded_rectangle((36, 28, 364, 102), 25, fill=accent)
    draw.rectangle((72, 55, 328, 75), fill=(18, 15, 22))
    image.save(path)


class CardBackgroundPolicyTest(unittest.TestCase):
    def test_stage_uses_clean_plate_texture_not_a_shared_card_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "card.png"
            _card(source, (209, 181, 241), (211, 250, 126))
            layers = prepare_layers(source, (Element("title", (36, 28, 328, 74),
                                                     "foreground", 0),), root / "layers")
            stage_info = prepare_vertical_stage(source, root / "layers" / layers["clean_plate"],
                                                root / "stage")
            background = Image.open(root / "stage" / stage_info["background"]).convert("RGB")
            plate = Image.open(root / "stage" / stage_info["plate"]).convert("RGB")
            self.assertEqual(background.size, (1080, 1920))
            self.assertIsNone(ImageChops.difference(background, plate).getbbox())
            self.assertEqual(stage_info["background_provenance"]["source_card_sha256"], _sha(source))
            self.assertEqual(stage_info["background_provenance"]["source_background_sha256"],
                             _sha(root / "layers" / layers["clean_plate"]))
            self.assertEqual(stage_info["background_provenance"]["method"],
                             "clean_plate_edge_texture_v3")
            self.assertEqual(stage_info["background_provenance"]["policy_version"],
                             "card_background_policy_v3")
            self.assertNotEqual(stage_info["theme"]["progress_track"], "#6e3d9b")
            y = stage_info["card_y"]
            end = y + round(500 * stage_info["card_scale"])
            for x in (20, 540, 1060):
                self.assertEqual(background.getpixel((x, y - 1)), background.getpixel((x, y)))
                self.assertEqual(background.getpixel((x, end - 1)), background.getpixel((x, end)))

    def test_extension_blends_toward_each_seam_for_all_32_neighbouring_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            # Make edge texture deliberately unlike its nearby interior: the
            # regression checks the two rows touching each card boundary,
            # where the old direction reversed the 32px bottom blend.
            image = Image.new("RGB", (400, 500), (188, 160, 227))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 399, 25), fill=(63, 104, 188))
            draw.rectangle((0, 474, 399, 499), fill=(242, 194, 129))
            image.save(source)
            stage_info = prepare_vertical_stage(source, source, root / "stage")
            background = Image.open(root / "stage" / stage_info["background"]).convert("RGB")
            y = stage_info["card_y"]
            end = y + round(500 * stage_info["card_scale"])

            def average_delta(first: int, second: int) -> float:
                return sum(sum(abs(a - b) for a, b in zip(background.getpixel((x, first)),
                                                           background.getpixel((x, second))))
                           for x in range(background.width)) / (background.width * 3)

            # Adjacent rows at both seams have at most 1/31 of the difference
            # between the stretched texture and the literal source edge.
            self.assertLessEqual(average_delta(y - 1, y), 9)
            self.assertLessEqual(average_delta(end - 1, end), 9)
            self.assertLessEqual(average_delta(y - 2, y - 1), 9)
            self.assertLessEqual(average_delta(end, end + 1), 9)

    def test_progress_fallback_keeps_palette_hue_and_real_swatches_win(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lavender = root / "lavender.png"
            Image.new("RGB", (400, 500), (209, 181, 241)).save(lavender)
            lavender_info = prepare_vertical_stage(lavender, lavender, root / "lavender-stage")
            field = tuple(int(lavender_info["theme"]["field"][index:index + 2], 16) / 255
                          for index in (1, 3, 5))
            active = tuple(int(lavender_info["theme"]["progress_active"][index:index + 2], 16) / 255
                           for index in (1, 3, 5))
            field_hue, field_saturation, _ = colorsys.rgb_to_hsv(*field)
            active_hue, active_saturation, active_value = colorsys.rgb_to_hsv(*active)
            self.assertLess(min(abs(active_hue - field_hue), 1 - abs(active_hue - field_hue)), .01)
            self.assertGreaterEqual(active_saturation, .52)
            self.assertLessEqual(active_saturation, .88)
            self.assertAlmostEqual(active_value, .48, delta=.01)
            self.assertGreater(field_saturation, .12)

            neutral = root / "neutral.png"
            Image.new("RGB", (400, 500), (202, 202, 202)).save(neutral)
            neutral_info = prepare_vertical_stage(neutral, neutral, root / "neutral-stage")
            self.assertEqual(neutral_info["theme"]["progress_active"], neutral_info["theme"]["ink"])

            swatched = root / "swatched.png"
            image = Image.new("RGB", (400, 500), (209, 181, 241))
            ImageDraw.Draw(image).rectangle((0, 0, 44, 499), fill=(0, 204, 122))
            image.save(swatched)
            swatch_info = prepare_vertical_stage(swatched, swatched, root / "swatch-stage")
            self.assertEqual(swatch_info["theme"]["progress_active"], "#00cc7a")

    def test_project_records_page_backgrounds_and_changes_with_card_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            colors = [((209, 181, 241), (211, 250, 126)),
                      ((179, 222, 235), (255, 205, 104)),
                      ((243, 204, 208), (111, 200, 164)),
                      ((238, 216, 168), (121, 161, 246))]
            cards = []
            for index, (field, accent) in enumerate(colors, 1):
                path = root / f"card-{index}.png"
                _card(path, field, accent)
                cards.append({"file": path.name, "source_sha256": _sha(path),
                              "duration_ms": 2000 if index == 1 else 3000,
                              "hook": "", "takeaway": "",
                              "motion_elements": [{"name": "title", "box": [36, 28, 328, 74],
                                                   "mask": "foreground", "delay_ms": 0}]})
            manifest = root / "reel-production.json"
            manifest.write_text(json.dumps({"version": 4, "renderer": "hyperframes_element_story",
                                             "audio_decision": "sfx_only", "deck_title": "테스트",
                                             "cards": cards}, ensure_ascii=False), encoding="utf-8")
            deck = Deck(manifest)
            project = create_project(deck, root / "project")
            generated = json.loads((project.parent / "generated.json").read_text(encoding="utf-8"))
            self.assertEqual(generated["background_policy"], "page_clean_plate_edge_texture_v3")
            self.assertEqual(len(generated["page_backgrounds"]), 4)
            self.assertEqual([record["provenance"]["source_card_sha256"]
                              for record in generated["page_backgrounds"]],
                             [card["source_sha256"] for card in cards])
            self.assertEqual(len({record["theme"]["field"]
                                  for record in generated["page_backgrounds"]}), 4)
            document = project.read_text(encoding="utf-8")
            self.assertIn('class="scene-background"', document)
            self.assertNotIn("#d8fb84", document.lower())
            self.assertNotIn("#6e3d9b", document.lower())


if __name__ == "__main__":
    unittest.main()
