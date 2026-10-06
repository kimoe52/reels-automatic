"""Regression coverage for Threads history pagination and cursor safety."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
FETCH_SPEC = importlib.util.spec_from_file_location(
    "fetch_history", ROOT / "automation" / "meta-threads" / "fetch" / "fetch_posts.py")
assert FETCH_SPEC and FETCH_SPEC.loader
FETCH = importlib.util.module_from_spec(FETCH_SPEC)
FETCH_SPEC.loader.exec_module(FETCH)

DAILY_SPEC = importlib.util.spec_from_file_location(
    "daily_history", ROOT / "automation" / "meta-threads" / "run_daily.py")
assert DAILY_SPEC and DAILY_SPEC.loader
DAILY = importlib.util.module_from_spec(DAILY_SPEC)
DAILY_SPEC.loader.exec_module(DAILY)


def page(post_id: str, timestamp: str, next_url: str = "") -> dict[str, object]:
    paging: dict[str, object] = {"next": next_url} if next_url else {}
    return {"data": [{"id": post_id, "timestamp": timestamp}], "paging": paging}


class FetchHistoryTest(unittest.TestCase):
    api = "https://graph.threads.net/v1.0"

    def test_missing_cursor_reads_every_page(self) -> None:
        initial = page("new", "2026-01-03T00:00:00+00:00", f"{self.api}/me/threads?after=one")
        older = page("old", "2026-01-02T00:00:00+00:00")
        with patch.object(FETCH, "fetch_page", return_value=initial), \
                patch.object(FETCH, "request_json", return_value=older) as request:
            posts, _, truncated = FETCH.fetch_posts("token", self.api, since="", limit=50, seen=set())
        self.assertFalse(truncated)
        self.assertEqual([post["id"] for post in posts], ["new", "old"])
        request.assert_called_once_with(f"{self.api}/me/threads?after=one", "token")

    def test_explicit_history_ignores_seen_and_cursor(self) -> None:
        initial = page("new", "2026-01-03T00:00:00+00:00", f"{self.api}/me/threads?after=one")
        older = page("seen-old", "2025-01-01T00:00:00+00:00")
        with patch.object(FETCH, "fetch_page", return_value=initial) as fetch_page, \
                patch.object(FETCH, "request_json", return_value=older):
            posts, _, truncated = FETCH.fetch_posts(
                "token", self.api, since="2026-01-02T00:00:00+00:00", limit=50,
                seen={"seen-old"}, backfill_history=True)
        self.assertFalse(truncated)
        self.assertEqual([post["id"] for post in posts], ["new", "seen-old"])
        self.assertEqual(fetch_page.call_args.kwargs["since"], "")

    def test_incremental_stops_at_saved_window_without_requesting_old_page(self) -> None:
        initial = page("known", "2026-01-01T00:00:00+00:00", f"{self.api}/me/threads?after=one")
        with patch.object(FETCH, "fetch_page", return_value=initial), \
                patch.object(FETCH, "request_json") as request:
            posts, _, truncated = FETCH.fetch_posts(
                "token", self.api, since="2026-01-02T00:00:00+00:00", limit=50, seen={"known"})
        self.assertFalse(truncated)
        self.assertEqual([post["id"] for post in posts], ["known"])
        request.assert_not_called()

    def test_next_link_strips_token_and_rejects_bad_origin(self) -> None:
        safe = FETCH.next_page_url(
            {"paging": {"next": f"{self.api}/me/threads?after=x&access_token=secret"}}, self.api)
        self.assertEqual(safe, f"{self.api}/me/threads?after=x")
        self.assertIsNone(FETCH.next_page_url(
            {"paging": {"next": "https://example.invalid/me/threads?after=x"}}, self.api))

    def test_repeated_next_and_page_limit_are_truncated(self) -> None:
        bad_origin = page("one", "2026-01-03T00:00:00+00:00", "https://example.invalid/next")
        with patch.object(FETCH, "fetch_page", return_value=bad_origin):
            _, _, truncated = FETCH.fetch_posts("token", self.api, since="", limit=50, seen=set())
        self.assertTrue(truncated)

        repeated = page("one", "2026-01-03T00:00:00+00:00", f"{self.api}/me/threads?after=again")
        with patch.object(FETCH, "fetch_page", return_value=repeated), \
                patch.object(FETCH, "request_json", return_value=repeated):
            _, _, truncated = FETCH.fetch_posts("token", self.api, since="", limit=50, seen=set())
        self.assertTrue(truncated)

        pages = [page(str(index), "2026-01-03T00:00:00+00:00",
                      f"{self.api}/me/threads?after={index}") for index in range(FETCH.MAX_PAGES + 1)]
        with patch.object(FETCH, "fetch_page", return_value=pages[0]), \
                patch.object(FETCH, "request_json", side_effect=pages[1:]):
            _, _, truncated = FETCH.fetch_posts("token", self.api, since="", limit=50, seen=set())
        self.assertTrue(truncated)

    def test_main_deduplicates_state_queue_and_page_rows_without_hydration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "state.json"
            state_path.write_text(json.dumps({"seen_ids": ["seen"], "last_timestamp": "2026-01-03T00:00:00+00:00",
                                              "history_complete": True}), encoding="utf-8")
            source = root / "queue" / "2026-01-01" / "queued" / "source.json"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({"id": "queued"}), encoding="utf-8")
            posts = [
                {"id": "seen", "timestamp": "2026-01-04T00:00:00+00:00"},
                {"id": "queued", "timestamp": "2026-01-04T00:00:00+00:00"},
                {"id": "fresh", "timestamp": "2026-01-04T00:00:00+00:00"},
                {"id": "fresh", "timestamp": "2026-01-04T00:00:00+00:00"},
            ]
            with patch.object(FETCH, "STATE_PATH", state_path), \
                    patch.object(FETCH, "QUEUE_DIR", root / "queue"), \
                    patch.object(FETCH, "SNAPSHOT_DIR", root / "snapshots"), \
                    patch.object(FETCH, "load_settings", return_value=("token", self.api, root / ".env")), \
                    patch.object(FETCH, "fetch_posts", return_value=(posts, {"paging": {}}, False)), \
                    patch.object(FETCH, "hydrate_media", side_effect=lambda values, *_: values) as hydrate, \
                    patch.object(sys, "argv", ["fetch_posts.py"]), redirect_stdout(io.StringIO()):
                self.assertEqual(FETCH.main(), 0)
            self.assertEqual([post["id"] for post in hydrate.call_args.args[0]], ["fresh"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["last_timestamp"], "2026-01-04T00:00:00+00:00")
            self.assertTrue(state["history_complete"])

    def test_history_success_never_moves_last_timestamp_backward(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "state.json"
            state_path.write_text(json.dumps({"seen_ids": ["newer"],
                                              "last_timestamp": "2026-01-05T00:00:00+00:00"}), encoding="utf-8")
            historical = [{"id": "old", "timestamp": "2025-01-01T00:00:00+00:00"}]
            with patch.object(FETCH, "STATE_PATH", state_path), \
                    patch.object(FETCH, "QUEUE_DIR", root / "queue"), \
                    patch.object(FETCH, "SNAPSHOT_DIR", root / "snapshots"), \
                    patch.object(FETCH, "load_settings", return_value=("token", self.api, root / ".env")), \
                    patch.object(FETCH, "fetch_posts", return_value=(historical, {"paging": {}}, False)), \
                    patch.object(FETCH, "hydrate_media", side_effect=lambda values, *_: values), \
                    patch.object(sys, "argv", ["fetch_posts.py", "--backfill-history"]), redirect_stdout(io.StringIO()):
                self.assertEqual(FETCH.main(), 0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["last_timestamp"], "2026-01-05T00:00:00+00:00")
            self.assertTrue(state["history_complete"])

    def test_incremental_keeps_existing_false_history_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "state.json"
            state_path.write_text(json.dumps({"seen_ids": [], "last_timestamp": "2026-01-03T00:00:00+00:00",
                                              "history_complete": False}), encoding="utf-8")
            with patch.object(FETCH, "STATE_PATH", state_path), \
                    patch.object(FETCH, "QUEUE_DIR", root / "queue"), \
                    patch.object(FETCH, "SNAPSHOT_DIR", root / "snapshots"), \
                    patch.object(FETCH, "load_settings", return_value=("token", self.api, root / ".env")), \
                    patch.object(FETCH, "fetch_posts", return_value=([], {"paging": {}}, False)), \
                    patch.object(FETCH, "hydrate_media", side_effect=lambda values, *_: values), \
                    patch.object(sys, "argv", ["fetch_posts.py"]), redirect_stdout(io.StringIO()):
                self.assertEqual(FETCH.main(), 0)
            self.assertFalse(json.loads(state_path.read_text(encoding="utf-8"))["history_complete"])

    def test_queue_source_ids_skips_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary) / "queue"
            valid = queue / "2026-01-01" / "valid" / "source.json"
            invalid = queue / "2026-01-01" / "invalid" / "source.json"
            valid.parent.mkdir(parents=True)
            invalid.parent.mkdir(parents=True)
            valid.write_text(json.dumps({"id": "kept"}), encoding="utf-8")
            invalid.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            with patch.object(FETCH, "QUEUE_DIR", queue):
                self.assertEqual(FETCH.queue_source_ids(), {"kept"})

    def test_truncation_does_not_advance_cursor_or_mark_history_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "state.json"
            original = {"seen_ids": ["old"], "last_timestamp": "2026-01-03T00:00:00+00:00"}
            state_path.write_text(json.dumps(original), encoding="utf-8")
            with patch.object(FETCH, "STATE_PATH", state_path), \
                    patch.object(FETCH, "QUEUE_DIR", root / "queue"), \
                    patch.object(FETCH, "SNAPSHOT_DIR", root / "snapshots"), \
                    patch.object(FETCH, "load_settings", return_value=("token", self.api, root / ".env")), \
                    patch.object(FETCH, "fetch_posts", return_value=([{"id": "new", "timestamp": "2026-01-04T00:00:00+00:00"}], {"paging": {}}, True)), \
                    patch.object(FETCH, "hydrate_media", side_effect=lambda values, *_: values), \
                    patch.object(sys, "argv", ["fetch_posts.py", "--backfill-history"]), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(FETCH.main(), 1)
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), original)


class DailyHistoryTest(unittest.TestCase):
    def test_skip_cards_and_render_passes_history_flag_to_fetch_only(self) -> None:
        commands: list[list[str]] = []

        def successful_run(command: list[str], **_: object):
            commands.append(command)
            from subprocess import CompletedProcess
            return CompletedProcess(command, 0, stderr="")

        with patch.object(DAILY, "run_stage", side_effect=lambda label, command: (successful_run(command).returncode, "")), \
                patch.object(sys, "argv", ["run_daily.py", "--skip-cards", "--skip-render", "--backfill-history"]):
            self.assertEqual(DAILY.main(), 0)
        self.assertEqual(commands, [
            [sys.executable, str(DAILY.FETCH), "--limit", "50", "--backfill-history"],
            [sys.executable, str(DAILY.TRANSFORM)],
        ])

    def test_history_rejects_independent_workflows(self) -> None:
        for args in (["--only-cards"], ["--only-render"], ["--from-images", "card.png"], ["--only-chatgpt"]):
            with self.subTest(args=args), patch.object(sys, "argv", ["run_daily.py", "--backfill-history", *args]):
                with self.assertRaises(SystemExit) as error, redirect_stderr(io.StringIO()):
                    DAILY.main()
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
