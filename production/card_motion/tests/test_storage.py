from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import WORK, VIDEOS, PROOFS, export_render, organize, reel_manifests, reel_package, archive_fixture_cards
from safari_images import SafariImages, SafariBlocked


class StorageTest(unittest.TestCase):
    def fixture(self, root, name="chatgpt-cards-id", title="원문 제목"):
        package = root / "content/reels" / name
        package.mkdir(parents=True)
        manifest = package / "reel-production.json"
        manifest.write_text(json.dumps({"deck_title":title,"reviewed":True,"cards":[]}), encoding="utf-8")
        renders = package / "renders"; renders.mkdir()
        video = renders / "reel-hash.mp4"; video.write_bytes(b"immutable video")
        proof = renders / "proof-hash.png"; proof.write_bytes(b"immutable proof")
        status = {"manifest":str(manifest),"video":str(video),"proof":str(proof),
                  "status":"ready_for_review", "source_inputs":[{
                      "file":"reel-production.json","sha256":hashlib.sha256(manifest.read_bytes()).hexdigest()}]}
        (renders / "latest.json").write_text(json.dumps(status), encoding="utf-8")
        return package, status

    def test_migration_keeps_original_paths_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); package, status = self.fixture(root)
            before = Path(status["manifest"]).read_bytes()
            report = organize(root)
            self.assertEqual(len(report["moved_packages"]), 1)
            self.assertTrue(package.is_symlink())
            self.assertTrue((package.parent / WORK / package.name).is_dir())
            self.assertEqual(Path(status["manifest"]).read_bytes(), before)
            self.assertEqual(Path(status["video"]).read_bytes(), b"immutable video")
            self.assertEqual(len(reel_manifests(package.parent)), 1)

    def test_finder_exports_are_title_named_and_repeat_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); package, status=self.fixture(root, title="제목/원문: 그대로")
            first=export_render(status, root); second=export_render(status, root)
            self.assertEqual(first["finder_video"], second["finder_video"])
            video=Path(first["finder_video"])
            self.assertEqual(video.parent.name, VIDEOS)
            self.assertIn("제목 원문 그대로", video.name)
            self.assertNotIn("hash", video.name)
            self.assertIn("검수대기", video.name)
            self.assertEqual(Path(first["finder_proof"]).parent.name, PROOFS)
            self.assertEqual(video.read_bytes(), b"immutable video")

    def test_same_title_packages_get_distinct_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); _, first=self.fixture(root,"a"); _, second=self.fixture(root,"b")
            a=export_render(first,root); b=export_render(second,root)
            self.assertNotEqual(a["finder_video"], b["finder_video"])

    def test_unreviewed_and_stale_videos_are_not_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); package, status=self.fixture(root)
            self.assertNotIn("finder_video",export_render({**status,"status":"awaiting_review"},root))
            (package/"reel-production.json").write_text('{"deck_title":"changed"}')
            self.assertNotIn("finder_video",export_render(status,root))

    def test_package_paths_are_project_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertTrue(reel_package("new-job",root).is_relative_to(root))
            self.assertEqual(reel_package("new-job",root).parent.name,WORK)
            for name in ("../outside","/outside", "."):
                with self.assertRaises(ValueError): reel_package(name,root)

    def test_new_download_is_adopted_but_other_files_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); project=root/"project"; project.mkdir()
            downloads=root/"Downloads"; downloads.mkdir()
            personal=downloads/"personal.png"; personal.write_bytes(b"personal")
            generated=downloads/"generated.png"; generated.write_bytes(b"generated")
            browser=SafariImages(downloads=downloads,references=[])
            destination=project/"job/card.png"
            with patch("safari_images.ROOT",project):
                browser._store_download(generated,destination,{personal:(8,0)})
            self.assertFalse(generated.exists())
            self.assertEqual(destination.read_bytes(),b"generated")
            self.assertEqual((destination.parent/".downloads/generated.png").read_bytes(),b"generated")
            self.assertEqual(personal.read_bytes(),b"personal")

    def test_preexisting_download_is_never_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"existing.png"; source.write_bytes(b"existing")
            browser=SafariImages(references=[])
            with patch("safari_images.ROOT",root):
                browser._store_download(source,root/"job/card.png",{source:(8,0)})
            self.assertTrue(source.exists())

    def test_save_outside_project_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); project=root/"project"; project.mkdir()
            source=root/"generated.png"; source.write_bytes(b"generated")
            with patch("safari_images.ROOT",project), self.assertRaises(SafariBlocked):
                SafariImages(references=[])._store_download(source,root/"outside.png",{})
            self.assertTrue(source.exists())

    def test_fixture_archive_does_not_touch_a_real_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); library=root/"content/card-news/generated"
            fake=library/"fixture"; fake.mkdir(parents=True)
            actual=library/"actual"; actual.mkdir()
            metadata={"title":"테스트","source_id":"","plan":str(root/"card-plan.json"),"cards":[{}]*4}
            (fake/"cards.json").write_text(json.dumps(metadata))
            (actual/"cards.json").write_text(json.dumps({**metadata,"source_id":"real-thread-id"}))
            report=archive_fixture_cards(root)
            self.assertEqual(report["test_decks_archived"],1)
            self.assertTrue((actual/"cards.json").is_file())
            self.assertTrue((Path(report["archive"])/"fixture/cards.json").is_file())


if __name__ == "__main__":
    unittest.main()
