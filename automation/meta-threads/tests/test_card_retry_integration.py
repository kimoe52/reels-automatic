"""Exercise the widget's --only-cards route through the real retry state machine.

Browser/clipboard and final image rendering stay mocked; all queue, status and
handoff reads/writes use real temporary files. No user posts or outputs change.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "production" / "card_render"))
import make_cards  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "card_retry_daily", ROOT / "automation" / "meta-threads" / "run_daily.py")
assert SPEC and SPEC.loader
DAILY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DAILY)


class CardRetryIntegrationTests(unittest.TestCase):
    def test_only_cards_retries_failed_job_without_refetching_or_recopying(self) -> None:
        cards = [
            {"layout": "cover", "title": "제목", "visual": "human"},
            {"layout": "keyword", "text": "핵심"},
            {"layout": "memo", "title": "메모", "items": [
                {"title": "하나", "text": "설명"}, {"title": "둘", "text": "설명"}]},
            {"layout": "cta", "title": "저장", "points": ["하나", "둘"]},
        ]
        with tempfile.TemporaryDirectory(prefix="card-route-retry-") as temporary:
            queue = Path(temporary)
            for name in ("complete", "retry"):
                folder = queue / "2026-10-04" / name
                folder.mkdir(parents=True)
                (folder / "source.json").write_text(
                    json.dumps({"id": name, "text": "원문", "username": "fixture"}), encoding="utf-8")
            waiting = queue / ".chatgpt-waiting.json"
            original_pending = make_cards.pending
            calls: list[str] = []
            commands: list[list[str]] = []

            def finish(folder, _post, _cards, _series, reel, *_options):
                self.assertFalse(reel)
                calls.append(folder.name)
                if folder.name == "retry" and calls.count("retry") == 1:
                    raise OSError("fixture save failure")
                make_cards.write_status(folder, "cards_ready")
                return {"id": folder.name, "state": "cards_ready"}

            def run_card_stage(command, **_options):
                commands.append(command)
                self.assertEqual(command, [sys.executable, str(DAILY.MAKE_CARDS), "--collect", "--no-reel"])
                errors = io.StringIO()
                with patch.object(sys, "argv", command[1:]), redirect_stderr(errors):
                    code = make_cards.main()
                return subprocess.CompletedProcess(command, code, stderr=errors.getvalue())

            with patch.object(DAILY, "WAITING", waiting), \
                    patch.object(make_cards, "WAITING", waiting), \
                    patch.object(make_cards, "pending", side_effect=lambda limit, minimum, only=None:
                        original_pending(limit, minimum, only, queue=queue)), \
                    patch.object(make_cards, "finish", side_effect=finish), \
                    patch.object(make_cards.chatgpt_web, "ask") as browser, \
                    patch.object(make_cards.chatgpt_web, "wait_for_answer") as clipboard, \
                    patch.object(make_cards.chatgpt_web, "notify"), \
                    patch.object(DAILY, "run_stage", side_effect=lambda label, command: (run_card_stage(command).returncode, "")):
                make_cards.create_waiting("fixture prompt", ["complete", "retry"],
                    {"series": "fixture", "theme": None, "card_style": "classic",
                     "reel_style": None, "no_reel": True})
                record = json.loads(waiting.read_text(encoding="utf-8"))
                record["answers"] = {name: cards for name in ("complete", "retry")}
                make_cards.update_waiting(record)
                first_output, second_output = io.StringIO(), io.StringIO()
                with patch.object(sys, "argv", ["run_daily.py", "--only-cards"]), \
                        redirect_stdout(first_output), redirect_stderr(io.StringIO()):
                    self.assertEqual(DAILY.main(), 1)
                first = json.loads(first_output.getvalue())
                self.assertEqual(first["handoff_state"], "retry_processing")
                self.assertEqual(first["ok"], 1)
                self.assertEqual(json.loads(waiting.read_text(encoding="utf-8"))["post_ids"], ["retry"])
                with patch.object(sys, "argv", ["run_daily.py", "--only-cards"]), \
                        redirect_stdout(second_output), redirect_stderr(io.StringIO()):
                    self.assertEqual(DAILY.main(), 0)
                self.assertEqual(json.loads(second_output.getvalue())["handoff_state"], "complete")
                self.assertFalse(waiting.exists())
                self.assertEqual(calls.count("complete"), 1)
                self.assertEqual(calls.count("retry"), 2)
                self.assertEqual(len(commands), 2)
                browser.assert_not_called()
                clipboard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
