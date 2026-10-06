"""Regression coverage for the local-draft-only ChatGPT card route."""

from __future__ import annotations

import io
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "run_daily_only_cards", ROOT / "automation" / "meta-threads" / "run_daily.py")
assert SPEC and SPEC.loader
DAILY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DAILY)


class OnlyCardsRouteTest(unittest.TestCase):
    def test_web_images_is_independent_and_does_not_collect_old_clipboard(self):
        commands = []
        with tempfile.TemporaryDirectory() as temporary:
            waiting = Path(temporary) / ".chatgpt-waiting.json"; waiting.write_text("{}")
            def run(command, **kwargs):
                commands.append(command); return subprocess.CompletedProcess(command, 0, stderr="")
            with patch.object(DAILY,"WAITING",waiting), patch.object(DAILY,"run_stage",side_effect=lambda label, command: (run(command).returncode, "")), \
                 patch.object(sys,"argv",["run_daily.py","--web-images","--plan","selected-plan.json"]):
                self.assertEqual(DAILY.main(),0)
        self.assertEqual(commands,[[sys.executable,str(DAILY.WEB_IMAGES),"--plan","selected-plan.json"]])

    def test_safari_check_never_fetches_generates_or_renders(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command); return subprocess.CompletedProcess(command,0,stderr="")
        with patch.object(DAILY,"run_stage",side_effect=lambda label, command: (run(command).returncode, "")), \
             patch.object(sys,"argv",["run_daily.py","--web-images-check"]):
            self.assertEqual(DAILY.main(),0)
        self.assertEqual(commands,[[sys.executable,str(DAILY.WEB_IMAGES),"--check-only"]])

    def test_web_image_conflicts_are_rejected(self):
        for flags in (["--only-cards"],["--only-render"],["--skip-render"],["--open-chatgpt"],["--web-images-check"]):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), \
                 patch.object(sys,"argv",["run_daily.py","--web-images",*flags]):
                with self.assertRaises(SystemExit) as error: DAILY.main()
                self.assertEqual(error.exception.code,2)

    def run_only_cards(self, waiting: Path) -> list[list[str]]:
        commands: list[list[str]] = []

        def successful_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stderr="")

        with patch.object(DAILY, "WAITING", waiting), \
                patch.object(DAILY, "run_stage", side_effect=lambda label, command: (successful_run(command).returncode, "")), \
                patch.object(sys, "argv", ["run_daily.py", "--only-cards"]):
            self.assertEqual(DAILY.main(), 0)
        return commands

    def test_collects_pending_chatgpt_answer_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            waiting = Path(temporary) / ".chatgpt-waiting.json"
            waiting.write_text("{}", encoding="utf-8")
            commands = self.run_only_cards(waiting)
        self.assertEqual(commands, [[sys.executable, str(DAILY.MAKE_CARDS), "--collect", "--no-reel"]])

    def test_creates_cards_from_existing_drafts_without_collecting_or_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            commands = self.run_only_cards(Path(temporary) / ".chatgpt-waiting.json")
        self.assertEqual(commands, [[sys.executable, str(DAILY.MAKE_CARDS), "--no-reel"]])

    def test_rejects_conflicting_independent_workflows(self) -> None:
        for conflicting_args in (
            ["--only-render"],
            ["--from-images", "card.png"],
            ["--only-chatgpt"],
            ["--open-chatgpt"],
            ["--resume-chatgpt"],
            ["--skip-render"],
            ["--skip-cards"],
        ):
            with self.subTest(conflicting_args=conflicting_args):
                stderr = io.StringIO()
                with redirect_stderr(stderr), \
                        patch.object(sys, "argv", ["run_daily.py", "--only-cards", *conflicting_args]):
                    with self.assertRaises(SystemExit) as error:
                        DAILY.main()
                self.assertEqual(error.exception.code, 2)
                self.assertIn("error:", stderr.getvalue())

    def test_skip_cards_and_render_fetches_and_transforms_despite_waiting_answer(self) -> None:
        commands: list[list[str]] = []

        def successful_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            waiting = Path(temporary) / ".chatgpt-waiting.json"
            waiting.write_text("{}", encoding="utf-8")
            with patch.object(DAILY, "WAITING", waiting), \
                    patch.object(DAILY, "run_stage", side_effect=lambda label, command: (successful_run(command).returncode, "")), \
                    patch.object(sys, "argv", ["run_daily.py", "--skip-cards", "--skip-render"]):
                self.assertEqual(DAILY.main(), 0)
        self.assertEqual(commands, [
            [sys.executable, str(DAILY.FETCH), "--limit", "50"],
            [sys.executable, str(DAILY.TRANSFORM)],
        ])

    def test_only_render_with_manifest_invokes_only_selected_legacy_renderer(self) -> None:
        commands: list[list[str]] = []

        def successful_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "reel-production.json"
            with patch.object(DAILY, "run_stage", side_effect=lambda label, command: (successful_run(command).returncode, "")), \
                    patch.object(sys, "argv", ["run_daily.py", "--only-render", "--manifest", str(manifest)]):
                self.assertEqual(DAILY.main(), 0)
        self.assertEqual(commands, [[sys.executable, str(DAILY.LEGACY_BUILD_READY),
                                     "--manifest", str(manifest)]])

    def test_from_images_runs_only_import_planner_then_selected_legacy_renderer(self) -> None:
        commands: list[list[str]] = []

        def successful_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "imported"
            images = ["card-1.png", "card-2.png"]
            with patch.object(DAILY, "run_stage", side_effect=lambda label, command: (successful_run(command).returncode, "")), \
                    patch.object(DAILY, "ROOT", Path(temporary)), \
                    patch.object(sys, "argv", ["run_daily.py", "--from-images", *images,
                                                 "--output", str(output)]):
                self.assertEqual(DAILY.main(), 0)
        self.assertEqual(commands, [
            [sys.executable, str(DAILY.AUTO_PLAN), "--import-images", *images,
             "--output", str(output), "--title", "카드 영상"],
            [sys.executable, str(DAILY.LEGACY_BUILD_READY), "--manifest",
             str(output / "reel-production.json")],
        ])

    def test_from_images_rejects_output_outside_project(self) -> None:
        with patch.object(DAILY, "run_stage") as stage, \
                patch.object(sys, "argv", ["run_daily.py", "--from-images", "card.png",
                                           "--output", "/private/tmp/outside-reel"]), \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            DAILY.main()
        stage.assert_not_called()

    def test_failed_fetch_stops_transform_cards_and_render(self) -> None:
        commands: list[list[str]] = []

        def failed_fetch(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 1, stderr="fetch failed")

        with tempfile.TemporaryDirectory() as temporary:
            missing_waiting = Path(temporary) / ".chatgpt-waiting.json"
            with patch.object(DAILY, "WAITING", missing_waiting), \
                    patch.object(DAILY, "run_stage", side_effect=lambda label, command: (failed_fetch(command).returncode, "fetch failed")), \
                    patch.object(sys, "argv", ["run_daily.py"]), \
                    redirect_stderr(io.StringIO()):
                self.assertEqual(DAILY.main(), 1)
        self.assertEqual(commands, [[sys.executable, str(DAILY.FETCH), "--limit", "50"]])


if __name__ == "__main__":
    unittest.main()
