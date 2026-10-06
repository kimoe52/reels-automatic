from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import brand_repair
from brand_repair import BrandRepairWorkflow, compose_characters
from native_focus import Deck
from web_image_workflow import WebImageWorkflow
from test_web_image_workflow import FakeBrowser
import test_web_image_workflow as fixtures


class RepairBrowser(FakeBrowser):
    def __init__(self):
        super().__init__(); self.uploaded = []
    def attach_images(self, paths): self.uploaded.extend(paths)


class BrandRepairTest(unittest.TestCase):
    def setUp(self) -> None:
        library = tempfile.TemporaryDirectory()
        self.addCleanup(library.cleanup)
        cards = patch("web_image_workflow.CARD_NEWS", Path(library.name) / "card-news")
        cards.start(); self.addCleanup(cards.stop)

    def assets(self, root):
        paths = [root / "human.png", root / "snake.png"]
        for index, path in enumerate(paths):
            asset = Image.new("RGBA", (120, 200), (0, 0, 0, 0))
            ImageDraw.Draw(asset).rectangle((20, 20, 100, 180), fill=(index * 100, 20, 40, 255))
            asset.save(path)
        return paths

    def base(self, root):
        helper = fixtures.WebImageWorkflowTest()
        flow = WebImageWorkflow(helper._plan(root), FakeBrowser(),
                                reel_builder=helper._builder, verifier=lambda _: True)
        self.assertEqual(flow.run()["web_image_state"], "complete")
        return flow.state_path

    def test_old_white_shirt_matte_hole_is_restored_from_original_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); assets=self.assets(root)
            with Image.open(assets[0]) as source:
                asset=source.copy()
            ImageDraw.Draw(asset).rectangle((40,173,60,179),fill=(255,255,255,0))
            asset.putpixel((41,175),(0,0,0,140))
            asset.putpixel((42,175),(70,70,70,250))
            asset.putpixel((50,55),(255,255,255,100)); asset.save(assets[0])
            reference=root/"content/character/character-human.png"
            reference.parent.mkdir(parents=True)
            Image.new("RGB",asset.size,"white").save(reference)
            with patch.object(brand_repair,"ROOT",root), patch.object(brand_repair,"ASSETS",assets):
                restored,proof=brand_repair._cutout_pixels(assets[0])
            self.assertEqual(restored.getpixel((50,175)),(255,255,255,255))
            self.assertEqual(restored.getpixel((41,175)),(255,255,255,255))
            self.assertEqual(restored.getpixel((42,175)),(255,255,255,255))
            self.assertEqual(restored.crop((0,0,120,168)).tobytes(),asset.crop((0,0,120,168)).tobytes())
            self.assertEqual(restored.getpixel((0,0)),asset.getpixel((0,0)))
            self.assertGreater(proof["restored_source_pixels"],0)

    def test_exact_original_assets_and_unchanged_top(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plate = root / "plate.png"; output = root / "final.png"
            Image.new("RGB", (800, 1000), (225, 209, 250)).save(plate)
            assets = self.assets(root)
            receipt = compose_characters(plate, output, assets)
            with Image.open(plate) as before, Image.open(output) as after:
                self.assertEqual(before.crop((0,0,800,680)).tobytes(), after.crop((0,0,800,680)).tobytes())
                for asset, record in zip(assets, receipt["characters"]):
                    x, y, w, h = record["box"]
                    with Image.open(asset) as source:
                        expected = source.crop(record["alpha_crop"]).resize((w,h), Image.Resampling.LANCZOS).convert("RGB")
                    self.assertEqual(after.crop((x,y,x+w,y+h)).tobytes(), expected.tobytes())
                    self.assertLess(abs(w/h - 81/161), .01)
                    self.assertFalse(record["generated_character"])

    def test_does_not_cover_reserved_text_or_existing_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plate = root / "plate.png"
            image = Image.new("RGB", (800, 1000), "white")
            ImageDraw.Draw(image).rectangle((100,800,200,960), fill="black"); image.save(plate)
            with self.assertRaisesRegex(ValueError, "덮지 않았"):
                compose_characters(plate, root/"final.png", self.assets(root))
            self.assertFalse((root/"final.png").exists())

    def test_repair_only_selected_card_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = self.base(root); baseline = base.read_bytes()
            browser = RepairBrowser()
            with patch.object(brand_repair, "ASSETS", self.assets(root)):
                flow = BrandRepairWorkflow(base, [2], browser, verifier=lambda _: True)
                before = {n:p.read_bytes() for n,p in flow.inputs.items()}
                result = flow.run(no_reel=True)
                self.assertEqual(result["web_image_state"], "images_ready")
                self.assertEqual(result["cards_saved"], 4)
                self.assertEqual(len(browser.sent), 2)
                self.assertEqual(len(browser.uploaded), 1)
                self.assertIn("original-cutouts", browser.uploaded[0].name)
                self.assertEqual(flow.run(no_reel=True)["web_image_state"], "images_ready")
                self.assertEqual(len(browser.sent), 2)
                self.assertEqual(base.read_bytes(), baseline)
                self.assertTrue(all(p.read_bytes() == before[n] for n,p in flow.inputs.items()))
                self.assertEqual(result["cards"][0]["image"], str(flow.inputs[1]))
                self.assertNotEqual(result["cards"][1]["image"], str(flow.inputs[2]))

    def test_adapts_to_actual_blank_boundary_without_covering_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); plate=root/"plate.png"; output=root/"final.png"
            image=Image.new("RGB",(800,1000),"white")
            ImageDraw.Draw(image).rectangle((50,500,750,720),outline="black",width=4)
            image.save(plate)
            receipt=compose_characters(plate,output,self.assets(root))
            self.assertGreater(receipt["reserved_top"],720)
            with Image.open(output) as final:
                self.assertEqual(final.crop((0,0,800,721)).tobytes(), image.crop((0,0,800,721)).tobytes())
            self.assertTrue(all(record["box"][1] > 720 for record in receipt["characters"]))

    def test_rejects_invalid_selection_and_changed_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = self.base(root)
            with patch.object(brand_repair, "ASSETS", self.assets(root)):
                for selected in ([], [0], [5], [2,2], [True]):
                    with self.subTest(selected=selected), self.assertRaises(ValueError):
                        BrandRepairWorkflow(base, selected, RepairBrowser())
                flow = BrandRepairWorkflow(base, [2], RepairBrowser())
                Image.new("RGB", (800,1000), "red").save(flow.inputs[1])
                with self.assertRaisesRegex(ValueError, "無|무결성"):
                    BrandRepairWorkflow(base, [2], RepairBrowser())

    def test_incomplete_source_review_cannot_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = self.base(root); calls=[]
            browser = RepairBrowser(); browser.verdicts=iter(["unknown"])
            with patch.object(brand_repair, "ASSETS", self.assets(root)):
                flow = BrandRepairWorkflow(base, [2], browser,
                    reel_builder=lambda *args:calls.append(args), verifier=lambda _:True)
                self.assertEqual(flow.run()["web_image_state"], "needs_review")
                self.assertEqual(calls, [])

    def test_cover_repair_chains_completed_job_preserving_repaired_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = self.base(root)
            helper = fixtures.WebImageWorkflowTest()
            with patch.object(brand_repair, "ASSETS", self.assets(root)):
                body = BrandRepairWorkflow(base, [2], RepairBrowser(),
                    reel_builder=helper._builder, verifier=lambda _: True)
                self.assertEqual(body.run()["web_image_state"], "complete")
                body_bytes = body.state_path.read_bytes()
                body_image = json.loads(body_bytes)["cards"]["2"]["attempts"][-1]["image"]
                cover = BrandRepairWorkflow(body.state_path, [1], RepairBrowser(),
                    reel_builder=helper._builder, verifier=lambda _: True)
                result = cover.run(no_reel=True)
                self.assertEqual(result["web_image_state"], "images_ready")
                self.assertEqual(result["cards"][1]["image"], body_image["path"])
                self.assertNotEqual(result["cards"][0]["image"], str(cover.inputs[1]))
                self.assertEqual(body.state_path.read_bytes(), body_bytes)
                self.assertIn(str(base), cover.fingerprint["lineage"])
                self.assertEqual(cover._load()["cards"]["2"]["attempts"][-1]["reused_from_sha256"],
                                 brand_repair._sha(body.state_path))
                changed = json.loads(base.read_text()); changed["note"] = "changed"
                base.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "무결성"):
                    BrandRepairWorkflow(body.state_path, [1], RepairBrowser())

    def test_reused_input_without_bound_lineage_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = self.base(root)
            state = json.loads(base.read_text())
            old = state["cards"]["1"]["attempts"][-1]
            outside = root / "outside.png"
            outside.write_bytes(Path(old["image"]["path"]).read_bytes())
            old["image"]["path"] = str(outside)
            base.write_text(json.dumps(state))
            with patch.object(brand_repair, "ASSETS", self.assets(root)):
                with self.assertRaisesRegex(ValueError, "무결성"):
                    BrandRepairWorkflow(base, [1], RepairBrowser())

    def test_dense_hyperframes_page_is_not_capped_at_fourteen_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); Image.new("RGB", (800,1000), "white").save(root/"card.png")
            manifest=root/"reel-production.json"
            manifest.write_text(json.dumps({"version":4,"renderer":"hyperframes_element_story",
                "deck_title":"읽기 시간", "audio_decision":"sfx_only","cards":[{"file":"card.png","duration_ms":62000,
                 "motion_elements":[{"name":"title","box":[10,10,200,80],"delay_ms":0,
                 "role":"title","effect":"scale_pop", "mask":"ink"}]} for _ in range(4)]}))
            deck=Deck(manifest)
            self.assertEqual(deck.duration_ms, 248000)


if __name__ == "__main__": unittest.main()
