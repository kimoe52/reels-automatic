"""Lightweight integration checks for generated cards → HyperFrames handoff."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
CARD_RENDER = ROOT / "production" / "card_render"
MOTION = ROOT / "production" / "card_motion"
sys.path[:0] = [str(CARD_RENDER), str(MOTION)]

from make_cards import has_existing_motion_elements, write_hyperframes_manifest  # noqa: E402
from storage import reel_package
import build_ready as CARD_RENDER_READY  # noqa: E402


DAILY_SPEC = importlib.util.spec_from_file_location(
    "run_daily_auto_motion", ROOT / "automation" / "meta-threads" / "run_daily.py")
assert DAILY_SPEC and DAILY_SPEC.loader
DAILY = importlib.util.module_from_spec(DAILY_SPEC)
DAILY_SPEC.loader.exec_module(DAILY)


def write_layers(cards: Path, rendered: list[dict[str, object]]) -> None:
    for item in rendered:
        image = cards / str(item["file"])
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        layers = image.with_suffix(".layers.json")
        layers.write_text(json.dumps({"version": 1, "source_file": image.name,
                                      "source_sha256": digest, "size": [1080, 1350],
                                      "background": {"file": "background.png", "sha256": "x"},
                                      "layers": [], "provenance": "test"}), encoding="utf-8")
        item["layers_file"] = layers.name
    (cards / "layout.json").write_text(json.dumps({"cards": rendered}), encoding="utf-8")


class GeneratedCardMotionIntegrationTest(unittest.TestCase):
    def test_generated_cards_make_a_reviewed_hyperframes_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "post"
            cards = folder / "card-render" / "cards"
            cards.mkdir(parents=True)
            report_cards = []
            for number in range(1, 5):
                name = f"{number:02d}-card.png"
                Image.new("RGB", (1080, 1350), "white").save(cards / name)
                report_cards.append({"file": name, "layout": "steps",
                                     "boxes": [{"name": "panel", "box": [48, 360, 984, 180], "radius": 44}],
                                     "problems": []})
            spec = {"series": "테스트 카드", "source": {"id": "source-1"},
                    "cards": [{"title": f"카드 {number}"} for number in range(1, 5)]}
            write_layers(cards, report_cards)
            manifest = write_hyperframes_manifest(folder, spec, {"cards": report_cards}, cards)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["renderer"], "hyperframes_element_story")
            self.assertTrue(data["reviewed"])
            self.assertTrue(data["motion_review_required"])
            self.assertEqual(data["audio_decision"], "sfx_only")
            self.assertTrue(all(card["file"].startswith("card-render/cards/") for card in data["cards"]))
            self.assertTrue(all(card["layers_file"].endswith(".layers.json") for card in data["cards"]))
            self.assertTrue(all(len(card["source_layers_sha256"]) == 64 for card in data["cards"]))
            self.assertTrue(all(card["motion_elements"] == [] for card in data["cards"]))

    def test_existing_manual_manifest_is_byte_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "post"; cards = folder / "card-render" / "cards"
            cards.mkdir(parents=True)
            manual = b'{"renderer":"native_card_story","audio_decision":"approved","cards":[{"motion_elements":[{"name":"manual"}]}]}\n'
            original = folder / "reel-production.json"; original.write_bytes(manual)
            Image.new("RGB", (1080, 1350), "white").save(cards / "01.png")
            self.assertTrue(has_existing_motion_elements(folder))
            returned = write_hyperframes_manifest(folder, {"cards": [{}]},
                                                  {"cards": [{"file": "01.png", "boxes": [], "layout": "comic"}]}, cards)
            self.assertEqual(returned, original)
            self.assertEqual(original.read_bytes(), manual)

    def test_changed_generated_spec_archives_old_auto_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "post"; cards = folder / "card-render" / "cards"
            cards.mkdir(parents=True)
            rendered = []
            for number in range(1, 5):
                name = f"{number}.png"; Image.new("RGB", (1080, 1350), "white").save(cards / name)
                rendered.append({"file": name, "layout": "steps", "boxes": []})
            write_layers(cards, rendered)
            spec = {"series": "첫 제목", "source": {"id": "source-a"}, "cards": [{"title": "a"}] * 4}
            spec_path = folder / "card-render" / "spec.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            write_hyperframes_manifest(folder, spec, {"cards": rendered}, cards)
            self.assertEqual(CARD_RENDER_READY.hyperframes_manifest_for(spec_path),
                             folder / "reel-production.json")
            original = (folder / "reel-production.json").read_bytes()
            spec["series"] = "바뀐 제목"; spec_path.write_text(json.dumps(spec), encoding="utf-8")
            self.assertIsNone(CARD_RENDER_READY.hyperframes_manifest_for(spec_path))
            write_hyperframes_manifest(folder, spec, {"cards": rendered}, cards)
            self.assertNotEqual((folder / "reel-production.json").read_bytes(), original)
            self.assertEqual(len(list((folder / "reel-production-history").glob("manifest-*.json"))), 1)

    def test_hyperframes_cli_accepts_progress_before_final_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); manifest = folder / "reel-production.json"
            video, proof = folder / "reel.mp4", folder / "proof.png"
            manifest.write_text("{}", encoding="utf-8"); video.write_bytes(b"video"); proof.write_bytes(b"proof")
            package = {"manifest": str(manifest), "status": "ready_for_review",
                       "video": str(video), "proof": str(proof)}
            completed = type("Result", (), {"returncode": 0, "stderr": "", "stdout":
                             "planning card 1\n" + json.dumps({"packages": [package]}) + "\n"})()
            with patch.object(CARD_RENDER_READY.subprocess, "run", return_value=completed):
                result = CARD_RENDER_READY.build_hyperframes_package(manifest)
            self.assertEqual(result["status"], "ready_for_review")

    def test_explicit_render_is_local_and_skips_fetch_and_card_spec_scan(self) -> None:
        manifest = reel_package("stock-basics-motion-2026-10-01", ROOT) / "reel-production.json"
        stages: list[tuple[str, list[str]]] = []
        with patch.object(DAILY, "run_stage", side_effect=lambda label, command: (stages.append((label, command)) or (0, ""))), \
                patch.object(sys, "argv", ["run_daily.py", "--only-render", "--manifest", str(manifest)]):
            self.assertEqual(DAILY.main(), 0)
        self.assertEqual([label for label, _ in stages], ["승인 이미지 릴스 렌더"])
        self.assertNotIn(str(DAILY.FETCH), stages[0][1])
        self.assertNotIn(str(DAILY.BUILD_READY), stages[0][1])
        self.assertEqual(stages[0][1][-2:], ["--manifest", str(manifest)])

    def test_widget_advertises_card_analysis_and_auto_motion_check(self) -> None:
        source = (ROOT / "widget" / "CinnamorollWidget" / "Sources" / "main.swift").read_text(encoding="utf-8")
        self.assertIn("최근 카드뉴스로 릴스 만들기", source)
        self.assertIn('result["autoMotion"]', source)
        self.assertIn('"hyperframes_element_story"', source)
        self.assertIn("카드 이미지로 릴스 만들기", source)
        self.assertIn('"--from-images"', source)

    def test_png_input_runs_extraction_and_render_without_network_or_authored_plan(self) -> None:
        stages = []; images = [f"card-{number}.png" for number in range(1,5)]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/"new"
            with patch.object(DAILY,"run_stage",side_effect=lambda label,command:(stages.append((label,command)) or (0,""))), \
                    patch.object(DAILY,"ROOT",Path(folder)), \
                    patch.object(sys,"argv",["run_daily.py","--from-images",*images,"--output",str(output)]):
                self.assertEqual(DAILY.main(),0)
        self.assertEqual(len(stages),2)
        self.assertIn(str(DAILY.AUTO_PLAN),stages[0][1])
        self.assertTrue(all(image in stages[0][1] for image in images))
        self.assertIn(str(DAILY.LEGACY_BUILD_READY),stages[1][1])
        self.assertNotIn(str(DAILY.FETCH),str(stages))
        self.assertNotIn(str(DAILY.MAKE_CARDS),str(stages))
        self.assertNotIn(str(DAILY.BUILD_READY),str(stages))


if __name__ == "__main__":
    unittest.main()
