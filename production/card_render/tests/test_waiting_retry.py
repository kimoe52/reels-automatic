from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import make_cards  # noqa: E402


class WaitingRetryTests(unittest.TestCase):
    CARDS = [
        {"layout": "cover", "title": "제목", "visual": "human"},
        {"layout": "keyword", "text": "핵심"},
        {"layout": "memo", "title": "메모", "items": [
            {"title": "하나", "text": "설명"}, {"title": "둘", "text": "설명"}]},
        {"layout": "cta", "title": "저장", "points": ["하나", "둘"]},
    ]

    def test_unhashable_saved_options_block_without_changing_record(self) -> None:
        for key, value in (("theme", []), ("card_style", {}), ("reel_style", [])):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                waiting = Path(temporary) / ".chatgpt-waiting.json"
                record = {"prompt": "original", "post_ids": ["post-1"], "options": {key: value}}
                waiting.write_text(json.dumps(record), encoding="utf-8")
                code, result = self.invoke_collect(waiting, [])
                self.assertEqual(code, 1)
                self.assertEqual(result["handoff_state"], "blocked")
                self.assertEqual(json.loads(waiting.read_text(encoding="utf-8")), record)

    def test_checkpoint_keeps_other_temporary_files_and_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            waiting = Path(temporary) / ".chatgpt-waiting.json"
            old_temporary = waiting.with_name(f".{waiting.name}.{os.getpid()}.tmp")
            old_temporary.write_text("other checkpoint", encoding="utf-8")
            with mock.patch.object(make_cards, "WAITING", waiting):
                make_cards.update_waiting({"prompt": "original", "post_ids": ["post-1"]})
            self.assertEqual(old_temporary.read_text(encoding="utf-8"), "other checkpoint")
            self.assertEqual(waiting.stat().st_mode & 0o777, 0o600)

    def test_duplicate_or_invalid_post_ids_preserve_blocked_handoff(self) -> None:
        for ids in (["post-1", "post-1"], [None], [""]):
            with self.subTest(ids=ids), tempfile.TemporaryDirectory() as temporary:
                waiting = Path(temporary) / ".chatgpt-waiting.json"
                record = {"prompt": "original", "post_ids": ids}
                waiting.write_text(json.dumps(record), encoding="utf-8")
                code, result = self.invoke_collect(waiting, [])
                self.assertEqual(code, 1)
                self.assertEqual(result["handoff_state"], "blocked")
                self.assertEqual(json.loads(waiting.read_text(encoding="utf-8")), record)

    def post(self, root: Path, name: str, state: str | None = None) -> tuple[Path, dict]:
        folder = root / name
        folder.mkdir(parents=True)
        post = {"id": name, "text": "충분히 긴 원문", "username": "stockai"}
        if state:
            work = folder / "card-render"
            work.mkdir()
            (work / "status.json").write_text(json.dumps({"state": state}), encoding="utf-8")
        return folder, post

    def invoke_collect(self, waiting: Path, posts: list[tuple[Path, dict]], *, answer: str | None = None,
                       finish=None) -> tuple[int, dict]:
        output = io.StringIO()
        patches = [
            mock.patch.object(make_cards, "WAITING", waiting),
            mock.patch.object(make_cards, "pending", return_value=posts),
            mock.patch.object(sys, "argv", ["make_cards.py", "--collect"]),
            mock.patch("sys.stdout", output),
            mock.patch.object(make_cards.chatgpt_web, "notify"),
        ]
        if answer is not None:
            patches.append(mock.patch.object(make_cards.chatgpt_web, "wait_for_answer", return_value=answer))
        if finish is not None:
            if isinstance(finish, dict):
                patches.append(mock.patch.object(make_cards, "finish", return_value=finish))
            else:
                patches.append(mock.patch.object(make_cards, "finish", side_effect=finish))
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            code = make_cards.main()
        return code, json.loads(output.getvalue())

    def test_malformed_or_partial_answer_keeps_private_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original prompt", "post_ids": ["post-1"],
                                           "sent_at": "unchanged"}), encoding="utf-8")
            code, result = self.invoke_collect(waiting, [(folder, post)], answer="not JSON")
            saved = json.loads(waiting.read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertTrue(result["waiting"])
            self.assertEqual(result["handoff_state"], "partial_answer")
            self.assertEqual(saved["prompt"], "original prompt")
            self.assertEqual(saved["post_ids"], ["post-1"])

    def test_partial_answer_keeps_only_the_missing_post_for_a_new_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_folder, first_post = self.post(root, "first")
            missing_folder, missing_post = self.post(root, "missing")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["first", "missing"]}), encoding="utf-8")
            answer = json.dumps({"posts": [{"id": "first", "cards": self.CARDS}]}, ensure_ascii=False)
            finish = mock.Mock(return_value={"id": "first", "state": "ok"})
            code, result = self.invoke_collect(waiting, [(first_folder, first_post), (missing_folder, missing_post)],
                                               answer=answer, finish=finish)
            saved = json.loads(waiting.read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(result["handoff_state"], "partial_answer")
            self.assertEqual(saved["post_ids"], ["missing"])
            self.assertNotIn("answers", saved)

    def test_local_finish_errors_keep_cached_copy_for_retry(self) -> None:
        for error in (ValueError("bad layout"), OSError("status write failed")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                folder, post = self.post(root, "post-1")
                waiting = root / ".chatgpt-waiting.json"
                waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["post-1"],
                                               "answers": {"post-1": self.CARDS}}), encoding="utf-8")
                code, result = self.invoke_collect(waiting, [(folder, post)], finish=error)
                saved = json.loads(waiting.read_text(encoding="utf-8"))
                self.assertEqual(code, 1)
                self.assertEqual(result["handoff_state"], "retry_processing")
                self.assertIn("post-1", saved["answers"])

    def test_returned_copy_validation_failure_discards_cache_for_a_revised_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["post-1"],
                                           "answers": {"post-1": self.CARDS}}), encoding="utf-8")
            code, result = self.invoke_collect(
                waiting, [(folder, post)], finish={"id": "post-1", "state": "failed", "unknown_terms": ["새 사실"]})
            saved = json.loads(waiting.read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(result["handoff_state"], "partial_answer")
            self.assertEqual(saved["post_ids"], ["post-1"])
            self.assertNotIn("answers", saved)

    def test_motion_source_conflict_blocks_without_discarding_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["post-1"],
                                           "answers": {"post-1": self.CARDS}}), encoding="utf-8")
            code, result = self.invoke_collect(
                waiting, [(folder, post)], finish={"id": "post-1", "state": "motion_source_conflict"})
            saved = json.loads(waiting.read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(result["handoff_state"], "blocked")
            self.assertIn("post-1", saved["answers"])

    def test_parsed_copy_is_checkpointed_before_local_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["post-1"]}), encoding="utf-8")
            answer = json.dumps({"posts": [{"id": "post-1", "cards": self.CARDS}]}, ensure_ascii=False)

            def finish_after_checkpoint(*_args):
                saved = json.loads(waiting.read_text(encoding="utf-8"))
                self.assertEqual(saved["answers"]["post-1"][0]["title"], "제목")
                raise OSError("status write failed")

            code, result = self.invoke_collect(waiting, [(folder, post)], answer=answer,
                                               finish=finish_after_checkpoint)
            self.assertEqual(code, 1)
            self.assertEqual(result["handoff_state"], "retry_processing")

    def test_malformed_cached_copy_is_discarded_before_a_fresh_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["post-1"],
                                           "answers": {"post-1": [{"layout": "cover"}]}}), encoding="utf-8")
            answer = json.dumps({"posts": [{"id": "post-1", "cards": self.CARDS}]}, ensure_ascii=False)
            code, result = self.invoke_collect(waiting, [(folder, post)], answer=answer,
                                               finish={"id": "post-1", "state": "ok"})
            self.assertEqual(code, 0)
            self.assertEqual(result["handoff_state"], "complete")
            self.assertFalse(waiting.exists())

    def test_final_checkpoint_removes_successes_but_keeps_failed_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_folder, first_post = self.post(root, "first")
            retry_folder, retry_post = self.post(root, "retry")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["first", "retry"],
                                           "answers": {"first": self.CARDS, "retry": self.CARDS}}), encoding="utf-8")
            finish = mock.Mock(side_effect=[{"id": "first", "state": "cards_ready"}, OSError("disk")])
            code, result = self.invoke_collect(waiting, [(first_folder, first_post), (retry_folder, retry_post)],
                                               finish=finish)
            saved = json.loads(waiting.read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(result["handoff_state"], "retry_processing")
            self.assertEqual(saved["post_ids"], ["retry"])
            self.assertEqual(set(saved["answers"]), {"retry"})

    def test_checkpoint_failure_after_success_is_skipped_by_the_next_collect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1")
            retry_folder, retry_post = self.post(root, "retry")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["post-1", "retry"],
                                           "answers": {"post-1": self.CARDS, "retry": self.CARDS}}), encoding="utf-8")

            def finish_and_record(*_args):
                work = folder / "card-render"
                work.mkdir(exist_ok=True)
                (work / "status.json").write_text(json.dumps({"state": "cards_ready"}), encoding="utf-8")
                return {"id": "post-1", "state": "cards_ready"}

            def finish_one_then_fail(*args):
                if args[0] == folder:
                    return finish_and_record(*args)
                raise OSError("disk")

            output = io.StringIO()
            with mock.patch.object(make_cards, "WAITING", waiting), \
                    mock.patch.object(make_cards, "pending", return_value=[(folder, post), (retry_folder, retry_post)]), \
                    mock.patch.object(make_cards, "finish", side_effect=finish_one_then_fail), \
                    mock.patch.object(make_cards, "update_waiting", side_effect=OSError("full disk")), \
                    mock.patch.object(make_cards.chatgpt_web, "notify"), \
                    mock.patch.object(sys, "argv", ["make_cards.py", "--collect"]), \
                    mock.patch("sys.stdout", output):
                self.assertEqual(make_cards.main(), 1)
            self.assertEqual(json.loads(output.getvalue())["handoff_state"], "blocked")
            finish = mock.Mock(return_value={"id": "retry", "state": "ok"})
            code, result = self.invoke_collect(waiting, [(folder, post), (retry_folder, retry_post)], finish=finish)
            self.assertEqual(code, 0)
            self.assertEqual(result["handoff_state"], "complete")
            finish.assert_called_once()
            self.assertEqual(finish.call_args.args[0], retry_folder)
            self.assertFalse(waiting.exists())

    def test_collect_uses_original_render_options_from_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["post-1"],
                                           "answers": {"post-1": self.CARDS},
                                           "options": {"series": "원래 시리즈", "theme": "mint",
                                                       "card_style": "comic_lavender", "reel_style": "motion",
                                                       "no_reel": True}}), encoding="utf-8")
            finish = mock.Mock(return_value={"id": "post-1", "state": "cards_ready"})
            code, _ = self.invoke_collect(waiting, [(folder, post)], finish=finish)
            self.assertEqual(code, 0)
            self.assertEqual(finish.call_args.args[3:], ("원래 시리즈", False, "mint", "motion", "comic_lavender"))

    def test_invalid_saved_options_block_and_preserve_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1")
            waiting = root / ".chatgpt-waiting.json"
            original = {"prompt": "original", "post_ids": ["post-1"], "options": {"no_reel": "yes"}}
            waiting.write_text(json.dumps(original), encoding="utf-8")
            code, result = self.invoke_collect(waiting, [(folder, post)])
            self.assertEqual(code, 1)
            self.assertEqual(result["handoff_state"], "blocked")
            self.assertEqual(json.loads(waiting.read_text(encoding="utf-8")), original)

    def test_malformed_waiting_record_reports_it_is_still_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text("{", encoding="utf-8")
            code, result = self.invoke_collect(waiting, [])
            self.assertEqual(code, 1)
            self.assertTrue(result["waiting"])
            self.assertEqual(result["handoff_state"], "blocked")

    def test_retry_processes_only_unfinished_jobs_and_clears_when_done(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            done_folder, done_post = self.post(root, "done", "needs_audio")
            retry_folder, retry_post = self.post(root, "retry")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["done", "retry"],
                                           "answers": {"done": self.CARDS, "retry": self.CARDS}}), encoding="utf-8")
            finish = mock.Mock(return_value={"id": "retry", "state": "ok"})
            code, result = self.invoke_collect(waiting, [(done_folder, done_post), (retry_folder, retry_post)],
                                               finish=finish)
            self.assertEqual(code, 0)
            self.assertFalse(waiting.exists())
            finish.assert_called_once()
            self.assertEqual(finish.call_args.args[0], retry_folder)
            self.assertEqual(result["handoff_state"], "complete")

    def test_timeout_keeps_new_web_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1")
            waiting = root / ".chatgpt-waiting.json"
            output = io.StringIO()
            with mock.patch.object(make_cards, "WAITING", waiting), \
                    mock.patch.object(make_cards, "pending", return_value=[(folder, post)]), \
                    mock.patch.object(make_cards.chatgpt_web, "ask", side_effect=TimeoutError("late")), \
                    mock.patch.object(make_cards.chatgpt_web, "notify"), \
                    mock.patch.object(sys, "argv", ["make_cards.py", "--via", "web"]), \
                    mock.patch("sys.stdout", output):
                self.assertEqual(make_cards.main(), 1)
            self.assertTrue(waiting.exists())
            self.assertEqual(json.loads(output.getvalue())["handoff_state"], "awaiting_answer")

    def test_timeout_still_retries_cached_copy_while_another_post_waits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cached_folder, cached_post = self.post(root, "cached")
            missing_folder, missing_post = self.post(root, "missing")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["cached", "missing"],
                                           "answers": {"cached": self.CARDS}}), encoding="utf-8")
            output = io.StringIO()
            finish = mock.Mock(return_value={"id": "cached", "state": "ok"})
            with mock.patch.object(make_cards, "WAITING", waiting), \
                    mock.patch.object(make_cards, "pending", return_value=[(cached_folder, cached_post),
                                                                             (missing_folder, missing_post)]), \
                    mock.patch.object(make_cards.chatgpt_web, "wait_for_answer", side_effect=TimeoutError("late")), \
                    mock.patch.object(make_cards.chatgpt_web, "notify"), \
                    mock.patch.object(make_cards, "finish", finish), \
                    mock.patch.object(sys, "argv", ["make_cards.py", "--collect"]), \
                    mock.patch("sys.stdout", output):
                self.assertEqual(make_cards.main(), 1)
            saved = json.loads(waiting.read_text(encoding="utf-8"))
            finish.assert_called_once()
            self.assertEqual(finish.call_args.args[0], cached_folder)
            self.assertEqual(saved["post_ids"], ["missing"])
            self.assertEqual(json.loads(output.getvalue())["handoff_state"], "awaiting_answer")

    def test_stale_completed_handoff_is_removed_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, post = self.post(root, "post-1", "reel_failed")
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["post-1"]}), encoding="utf-8")
            code, result = self.invoke_collect(waiting, [(folder, post)])
            self.assertEqual(code, 0)
            self.assertFalse(waiting.exists())
            self.assertEqual(result["handoff_state"], "complete")

    def test_missing_source_handoff_is_retained_and_reported_as_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            waiting = root / ".chatgpt-waiting.json"
            waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["missing"]}), encoding="utf-8")
            code, result = self.invoke_collect(waiting, [])
            self.assertEqual(code, 1)
            self.assertTrue(waiting.exists())
            self.assertEqual(result["handoff_state"], "blocked")
            self.assertEqual(json.loads(waiting.read_text(encoding="utf-8"))["post_ids"], ["missing"])

    def test_all_copy_complete_states_are_not_collected_again(self) -> None:
        for state in make_cards.COPY_COMPLETE_STATES:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                folder, post = self.post(root, "post-1", state)
                waiting = root / ".chatgpt-waiting.json"
                waiting.write_text(json.dumps({"prompt": "original", "post_ids": ["post-1"]}), encoding="utf-8")
                code, result = self.invoke_collect(waiting, [(folder, post)])
                self.assertEqual(code, 0)
                self.assertFalse(waiting.exists())
                self.assertEqual(result["handoff_state"], "complete")

    def test_explicit_post_still_redoes_a_copy_complete_post(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary)
            folder = queue / "2026-10-04" / "post-1"
            folder.mkdir(parents=True)
            (folder / "source.json").write_text(json.dumps({"id": "post-1", "text": "원문"}), encoding="utf-8")
            work = folder / "card-render"
            work.mkdir()
            (work / "status.json").write_text(json.dumps({"state": "needs_layer_repair"}), encoding="utf-8")
            self.assertEqual([item[0] for item in make_cards.pending(1, 0, {"post-1"}, queue)], [folder])

    def test_file_and_codex_runs_leave_an_unrelated_web_handoff_untouched(self) -> None:
        for via in ("file", "codex"):
            with self.subTest(via=via), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                folder, post = self.post(root, "post-1")
                waiting = root / ".chatgpt-waiting.json"
                original = {"prompt": "web prompt", "post_ids": ["other"]}
                waiting.write_text(json.dumps(original), encoding="utf-8")
                output = io.StringIO()
                arguments = ["make_cards.py", "--via", via]
                if via == "file":
                    answer = root / "answer.json"
                    answer.write_text(json.dumps({"posts": [{"id": "post-1", "cards": self.CARDS}]}), encoding="utf-8")
                    arguments.extend(["--answer", str(answer)])
                with mock.patch.object(make_cards, "WAITING", waiting), \
                        mock.patch.object(make_cards, "pending", return_value=[(folder, post)]), \
                        mock.patch.object(make_cards, "finish", return_value={"id": "post-1", "state": "cards_ready"}), \
                        mock.patch.object(make_cards.write_copy, "ask_codex", return_value=json.dumps({"posts": [{"id": "post-1", "cards": self.CARDS}]})), \
                        mock.patch.object(sys, "argv", arguments + ["--no-reel"]), \
                        mock.patch("sys.stdout", output):
                    self.assertEqual(make_cards.main(), 0)
                self.assertEqual(json.loads(waiting.read_text(encoding="utf-8")), original)


if __name__ == "__main__":
    unittest.main()
