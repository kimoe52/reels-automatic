"""Checks for source coverage and the reviewed Reel's pixel reconstruction."""

from __future__ import annotations

import importlib.util
import fcntl
import json
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MOTION = ROOT / "production" / "card_motion"
sys.path.insert(0, str(MOTION))

from render import CarouselReel  # noqa: E402
from native_focus import Deck as CardStoryDeck  # noqa: E402
from element_layers import Element, parse_elements, prepare_layers, prepare_vertical_stage  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from open_chatgpt import latest_plan, open_handoff, prepare  # noqa: E402
from storage import reel_package


SPEC = importlib.util.spec_from_file_location(
    "transform_posts", ROOT / "automation" / "meta-threads" / "transform" / "transform_posts.py")
assert SPEC and SPEC.loader
TRANSFORM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSFORM)

DAILY_SPEC = importlib.util.spec_from_file_location(
    "run_daily", ROOT / "automation" / "meta-threads" / "run_daily.py")
assert DAILY_SPEC and DAILY_SPEC.loader
DAILY = importlib.util.module_from_spec(DAILY_SPEC)
DAILY_SPEC.loader.exec_module(DAILY)


class PipelineTest(unittest.TestCase):
    def test_daily_does_not_overlap_an_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (root / ".run-daily.lock").open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(DAILY, "QUEUE", root), patch.object(DAILY, "main") as main:
                    self.assertEqual(DAILY.guarded_main(), 1)
                    main.assert_not_called()

    def test_daily_resumes_pending_chatgpt_before_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            waiting = Path(temporary) / ".chatgpt-waiting.json"
            waiting.write_text("{}", encoding="utf-8")
            commands = []
            def run_stage(label: str, command: list[str]) -> tuple[int, str]:
                commands.append((label, command))
                return 0, ""
            with patch.object(DAILY, "WAITING", waiting), \
                    patch.object(DAILY, "legacy_manifests", return_value=[]), \
                    patch.object(DAILY, "run_stage", side_effect=run_stage), \
                    patch.object(sys, "argv", ["run_daily.py"]):
                self.assertEqual(DAILY.main(), 0)
            self.assertEqual([label for label, _ in commands],
                             ["ChatGPT 답변 이어받기", "렌더"])
            self.assertIn("--collect", commands[0][1])

    def test_approved_image_manifest_remains_renderable(self) -> None:
        approved = ROOT / "content" / "card-news" / "jev-2026-09-25" / "reel-production.json"
        self.assertIn(approved, DAILY.legacy_manifests())
        commands = []
        with patch.object(DAILY, "run_stage",
                          side_effect=lambda label, command: (commands.append(command) or (0, ""))), \
                patch.object(sys, "argv", ["run_daily.py", "--only-render"]):
            self.assertEqual(DAILY.main(), 0)
        self.assertTrue(any(str(approved) in command for command in commands))

    def test_user_card_story_is_wired_to_daily_render(self) -> None:
        manifest = reel_package("stock-basics-motion-2026-10-01", ROOT) / "reel-production.json"
        self.assertIn(manifest, DAILY.legacy_manifests())
        deck = CardStoryDeck(manifest)
        self.assertEqual(len(deck.pages), 9)
        self.assertEqual(deck.duration_ms, 36600)
        self.assertEqual([page.duration_ms for page in deck.pages],
                         [3200, 4200, 4000, 4200, 4500, 4000, 3800, 4200, 4500])
        self.assertEqual(deck.data["audio_decision"], "sfx_only")
        self.assertEqual(deck.renderer, "hyperframes_element_story")
        self.assertEqual(sum(len(page.elements) for page in deck.pages), 42)
        self.assertTrue(all(2 <= len(page.elements) <= 8 for page in deck.pages))
        self.assertEqual([item.name for item in deck.pages[1].elements[1:]],
                         ["증권사 선택", "계좌 개설", "투자금 입금", "주식 ETF 검색", "가격 확인 후 매수"])
        self.assertEqual(len(deck.pages[7].elements[1:]), 5)
        self.assertIn("실제 추이 그래프", [item.name for item in deck.pages[8].elements])
        for page in deck.pages:
            self.assertTrue(page.hook)
            self.assertEqual(page.takeaway, "")

    def test_widget_can_render_one_approved_deck_without_fetching(self) -> None:
        manifest = reel_package("stock-basics-motion-2026-10-01", ROOT) / "reel-production.json"
        with patch.object(DAILY, "run_stage", return_value=(0, "")) as stage, \
                patch.object(sys, "argv", ["run_daily.py", "--only-render", "--manifest", str(manifest)]):
            self.assertEqual(DAILY.main(), 0)
        stage.assert_called_once_with(
            "승인 이미지 릴스 렌더",
            [sys.executable, str(DAILY.LEGACY_BUILD_READY), "--manifest", str(manifest)])

    def test_vertical_stage_matches_card_edges_without_summary_band(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            image = Image.new("RGB", (800, 1000), (219, 193, 237))
            source, plate = folder / "card.png", folder / "plate.png"
            image.save(source)
            image.save(plate)
            report = prepare_vertical_stage(source, plate, folder / "stage")
            stage = Image.open(folder / "stage" / report["original"])
            self.assertEqual(stage.size, (1080, 1920))
            y = report["card_y"]
            end = y + round(1000 * report["card_scale"])
            for x in (100, 540, 980):
                self.assertEqual(stage.getpixel((x, y - 1)), stage.getpixel((x, y)))
                self.assertEqual(stage.getpixel((x, end - 1)), stage.getpixel((x, end)))

    def test_element_extraction_keeps_original_and_separates_background(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "card.png"
            image = Image.new("RGB", (100, 100), (220, 190, 240))
            ImageDraw.Draw(image).rectangle((36, 35, 64, 63), fill="black")
            image.save(source)
            report = prepare_layers(source, (Element("keyword", (28, 27, 45, 45),
                                                     "foreground", 0),), folder / "layers")
            cutout = Image.open(folder / "layers" / report["elements"][0]["file"])
            plate = Image.open(folder / "layers" / report["clean_plate"])
            self.assertEqual(cutout.getpixel((22, 22))[3], 255)
            self.assertEqual(cutout.getpixel((2, 2))[3], 0)
            self.assertNotEqual(plate.getpixel((50, 50)), (0, 0, 0))
            self.assertEqual(Image.open(source).getpixel((50, 50)), (0, 0, 0))

    def test_element_plan_rejects_overlaps(self) -> None:
        with self.assertRaisesRegex(ValueError, "겹칩니다"):
            parse_elements([{"name": "a", "box": [0, 0, 40, 40], "mask": "rounded",
                             "delay_ms": 0, "radius": 4},
                            {"name": "b", "box": [30, 30, 40, 40], "mask": "rounded",
                             "delay_ms": 100, "radius": 4}], (100, 100), 1)

    def test_rebuilt_panel_background_rejects_dark_character_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "card.png"
            image = Image.new("RGB", (260, 200), (204, 170, 236))
            draw = ImageDraw.Draw(image)
            draw.rectangle((12, 70, 90, 198), fill=(8, 6, 12))
            draw.rounded_rectangle((95, 80, 235, 155), 14, fill="white")
            image.save(source)
            report = prepare_layers(source, (Element("panel", (95, 80, 140, 75),
                                                     "rounded", 0, 14, True),),
                                    folder / "layers")
            plate = Image.open(folder / "layers" / report["clean_plate"])
            red, green, blue = plate.getpixel((125, 110))
            self.assertGreater(red, 145)
            self.assertGreater(blue - red, 6)
            self.assertGreater(blue - green, 12)

    def test_textured_panel_keeps_source_background_until_original_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "card.png"
            image = Image.new("RGB", (100, 100), (180, 120, 225))
            ImageDraw.Draw(image).rounded_rectangle((25, 25, 75, 75), 12, fill="white")
            image.save(source)
            element = parse_elements([
                {"name": "panel", "box": [25, 25, 50, 50], "mask": "rounded",
                 "radius": 12, "delay_ms": 0},
                {"name": "title", "box": [0, 0, 24, 24], "mask": "foreground",
                 "delay_ms": 100}], image.size, 1)
            self.assertFalse(element[0].repair)
            report = prepare_layers(source, element, folder / "layers")
            plate = Image.open(folder / "layers" / report["clean_plate"])
            self.assertEqual(plate.getpixel((50, 50)), (255, 255, 255))

    def test_chatgpt_handoff_skips_too_short_latest_post(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for identifier, timestamp, length in (("long", "2026-09-26T00:00:00+00:00", 260),
                                                  ("short", "2026-09-27T00:00:00+00:00", 70)):
                folder = root / timestamp[:10] / identifier
                folder.mkdir(parents=True)
                (folder / "source.json").write_text(json.dumps({"text": "가" * length}), encoding="utf-8")
                (folder / "card-plan.json").write_text(
                    json.dumps({"timestamp": timestamp, "source_file": "source.json",
                                "content_ready": True, "card_count": 4,
                                "cards": [{"number": index, "role": "본문",
                                           "source_text": "원문"} for index in range(1, 5)]}), encoding="utf-8")
            with patch("open_chatgpt.QUEUE", root):
                selected = latest_plan()
            self.assertEqual(selected.parent.name, "long")

    def test_chatgpt_web_handoff_uses_source_and_no_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = Path(temporary) / "card-plan.json"
            plan.write_text(json.dumps({"card_count": 4, "content_ready": True,
                                        "cards": [{"number": index, "role": "본문",
                                                   "source_text": f"원문 {index}"}
                                                  for index in range(1, 5)]}), encoding="utf-8")
            handoff = prepare(plan)
            self.assertEqual(handoff["card_count"], 4)
            self.assertFalse(handoff["reviewed"])
            first = Path(handoff["prompts"][0]).read_text(encoding="utf-8")
            self.assertIn("원문 1", first)
            self.assertIn("원문 4", first)
            with patch("open_chatgpt.subprocess.run") as run:
                opened = open_handoff(handoff, 2)
            self.assertEqual(opened["selected_card"], 2)
            self.assertEqual(run.call_args_list[0].args[0], ["pbcopy"])
            self.assertEqual(run.call_args_list[1].args[0], ["open", "https://chatgpt.com/"])

    def test_reprocessing_does_not_overwrite_edited_card_copy(self) -> None:
        post = {"id": "existing-post", "text": "원문 첫째\n\n원문 둘째\n\n원문 셋째\n\n원문 넷째",
                "timestamp": "2026-09-25T02:28:38+0000", "permalink": "https://example.test/post"}
        with tempfile.TemporaryDirectory() as temporary:
            folder = TRANSFORM.write_post(post, Path(temporary), 4, overrides_dir=None)
            copy = folder / "card-copy.md"
            copy.write_text("수정한 문안", encoding="utf-8")
            TRANSFORM.write_post(post, Path(temporary), 4, overrides_dir=None)
            self.assertEqual(copy.read_text(encoding="utf-8"), "수정한 문안")
            draft = json.loads((folder / "reel-production.draft.json").read_text(encoding="utf-8"))
            self.assertEqual(draft["renderer"], "hyperframes_element_story")
            self.assertFalse(draft["reviewed"])
            self.assertEqual(draft["timing_policy"], "reading_paced")
            self.assertEqual(draft["card_durations"][0], 3.2)
            self.assertTrue(all(3.5 <= duration <= 5 for duration in
                                draft["card_durations"][1:]))
            self.assertEqual([card["duration_ms"] for card in draft["cards"]],
                             [round(duration * 1000) for duration in draft["card_durations"]])
            self.assertTrue(all(card["motion_elements"] == [] for card in draft["cards"]))

    def test_threads_timestamp_with_unseparated_utc_offset(self) -> None:
        day, normalized = TRANSFORM.parse_timestamp("2026-09-25T02:28:38+0000")
        self.assertEqual(day, "2026-09-25")
        self.assertEqual(normalized, "2026-09-25T02:28:38+00:00")

    def test_card_plan_covers_each_source_block_once(self) -> None:
        source = ("첫 질문과 주제\n\n둘째 설명과 첫 근거\n\n셋째 수치와 조건\n\n"
                  "넷째 비교 설명\n\n다섯째 예시\n\n여섯째 결론")
        post = {"text": source, "permalink": "https://example.test/post", "timestamp": "2026-09-25"}
        cards = TRANSFORM.make_cards(post, 5)
        self.assertEqual(len(cards), 5)
        bodies = [body for _, body in cards]
        bodies[-1] = bodies[-1].split("\n\n출처:", 1)[0]
        flattened = re.sub(r"\s+", " ", " ".join(bodies)).strip()
        self.assertEqual(flattened, re.sub(r"\s+", " ", source).strip())

    def test_jev_motion_lands_on_the_approved_card_pixels(self) -> None:
        manifest = ROOT / "content" / "card-news" / "jev-2026-09-25" / "reel-production.json"
        reel = CarouselReel(manifest)
        self.assertEqual(len(reel.cards), 5)
        reel.verify_settled_cards()

    def test_renderer_accepts_four_or_six_cards(self) -> None:
        original = ROOT / "content" / "card-news" / "jev-2026-09-25" / "reel-production.json"
        payload = json.loads(original.read_text(encoding="utf-8"))
        for card in payload["cards"]:
            card["file"] = str(original.parent / card["file"])
        payload["audio"] = None
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "reel-production.json"
            for count in (4, 6):
                payload["cards"] = payload["cards"][:5]
                if count == 4:
                    selected = payload["cards"][:4]
                else:
                    selected = [*payload["cards"], payload["cards"][-1]]
                manifest.write_text(json.dumps({**payload, "cards": selected}), encoding="utf-8")
                reel = CarouselReel(manifest)
                self.assertEqual(reel.frame(reel.duration - .1).size, (1080, 1920))

    def test_legacy_renderer_supports_cover_two_then_one_point_five(self) -> None:
        original = ROOT / "content" / "card-news" / "jev-2026-09-25" / "reel-production.json"
        payload = json.loads(original.read_text(encoding="utf-8"))
        payload.pop("seconds_per_card", None)
        payload["timing_policy"] = "cover2_inner1_5"
        payload["card_durations"] = [2.0] + [1.5] * (len(payload["cards"]) - 1)
        payload["audio"] = None
        for card in payload["cards"]:
            card["file"] = str(original.parent / card["file"])
            card["tiles"] = []
            card["accents"] = []
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "reel-production.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            reel = CarouselReel(manifest)
            self.assertEqual(reel.card_starts[:3], (0, 2.0, 3.5))
            self.assertEqual(reel.duration, 2.0 + 1.5 * (len(reel.cards) - 1))
            self.assertEqual(reel.frame(2.5).size, (1080, 1920))
            payload["card_durations"][0] = 3.0
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Card-news timing"):
                CarouselReel(manifest)


if __name__ == "__main__":
    unittest.main()
