from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from project_paths import DEFAULTS, project_path, scratch_directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import reel_manifests


class ProjectPathsTest(unittest.TestCase):
    def configure(self, root, paths):
        (root/"project-paths.json").write_text(json.dumps({"version":1,"paths":paths}),encoding="utf-8")

    def test_defaults_are_relative_to_the_actual_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for key in DEFAULTS:
                self.assertTrue(project_path(key,root).is_relative_to(root))

    def test_supported_configuration_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.configure(root,{"reels_videos":"output/영상"})
            self.assertEqual(project_path("reels_videos",root),root/"output/영상")

    def test_manifest_scan_uses_configured_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root, {"reels_root": "output/reels/archive",
                                  "reels_work": "output/제작 자료"})
            manifest = project_path("reels_work", root) / "example/reel-production.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}", encoding="utf-8")
            self.assertEqual(reel_manifests(project_path("reels_root", root), root), [manifest])

    def test_absolute_parent_and_empty_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for bad in ("/tmp/outside","../outside","","."):
                with self.subTest(path=bad):
                    self.configure(root,{"reels_videos":bad})
                    with self.assertRaises(ValueError): project_path("reels_videos",root)

    def test_outside_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp); root=parent/"project"; root.mkdir()
            (root/"escape").symlink_to(parent,target_is_directory=True)
            self.configure(root,{"reels_videos":"escape/output"})
            with self.assertRaises(ValueError): project_path("reels_videos",root)

    def test_scratch_is_inside_project_and_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); work=scratch_directory("card-render",root)
            self.assertEqual(work,root/".work/card-render")
            self.assertTrue(work.is_dir())
            with self.assertRaises(ValueError): scratch_directory("../outside",root)

    def test_unsupported_configuration_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"project-paths.json").write_text('{"version":9,"paths":{}}')
            with self.assertRaises(ValueError): project_path("reels_videos",root)


if __name__ == "__main__":
    unittest.main()
