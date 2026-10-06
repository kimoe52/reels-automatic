"""Self-reply identity, parent-chain, pagination and immutable-source regressions."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "automation/meta-threads"))
sys.path.insert(0, str(ROOT / "production/card_motion"))
from thread_source import merge_author_thread, effective_plan, save_thread_source
from web_image_workflow import _check_source_coverage, _prepare_source_plan


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


FETCH = module("thread_fetch_test", "automation/meta-threads/fetch/fetch_posts.py")
TRANSFORM = module("thread_transform_test", "automation/meta-threads/transform/transform_posts.py")


def root():
    return {"id": "123", "username": "owner", "timestamp": "2026-10-03T00:00:00+00:00",
            "permalink": "https://www.threads.com/@owner/post/abc",
            "text": "본문 제목\n\n본문 설명을 원문 그대로 보존하고 다른 문장으로 바꾸지 않습니다"}


def reply(identifier, parent="123", text="이어 쓴 설명", username="owner", root_id="123"):
    return {"id": identifier, "username": username, "text": text, "root_post": {"id": root_id},
            "replied_to": {"id": parent}, "timestamp": "2026-10-03T00:00:01+00:00"}


class ThreadSourceTest(unittest.TestCase):
    def test_prose_nested_chain_without_numbered_headline_is_complete(self):
        rows = [reply("3", "2", "마지막 설명"), reply("2", text="두 번째 설명")]
        result = merge_author_thread(root(), rows)
        self.assertEqual([p["id"] for p in result["posts"]], ["123", "2", "3"])
        self.assertEqual(result["text"], root()["text"] + "\n\n두 번째 설명\n\n마지막 설명")
        self.assertEqual(result["posts"][2]["replied_to"], {"id": "2"})

    def test_foreign_comment_author_answer_and_descendants_are_excluded(self):
        rows = [reply("other", username="other"), reply("answer", "other", "댓글 답변"),
                reply("answer2", "answer", "답변의 후속"), reply("own", text="실제 본문 후속"),
                reply("unrelated", root_id="999"), reply("own", text="실제 본문 후속")]
        result = merge_author_thread(root(), rows)
        self.assertEqual([p["id"] for p in result["posts"]], ["123", "own"])
        self.assertNotIn("댓글 답변", result["text"])
        self.assertEqual(len(result["excluded"]), 2)

    def test_missing_parent_and_cycles_are_not_guessed_into_source(self):
        missing = reply("missing"); missing.pop("replied_to")
        result = merge_author_thread(root(), [missing, reply("a", "b"), reply("b", "a")])
        self.assertEqual(result["reply_count"], 0)
        self.assertIn({"id": "missing", "reason": "missing_parent"}, result["excluded"])

    def test_parent_order_wins_over_numbers_and_timestamps(self):
        result = merge_author_thread(root(), [reply("child", "parent", "2. child"),
                                              reply("parent", text="3. parent")])
        self.assertEqual([p["id"] for p in result["posts"]], ["123", "parent", "child"])

    def test_existing_sources_and_editorial_files_survive_updated_reply_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary)
            folder = TRANSFORM.write_post(root(), queue, None, None)
            files = [folder / name for name in ("source.json", "card-plan.json", "card-copy.md", "reel-script.md")]
            before = {p: p.read_bytes() for p in files}
            rows = [reply("2", text="첫 후속 문장입니다\n\n두 번째 후속 문장입니다\n\n마지막 후속 설명도 빠짐없이 반영합니다")]
            thread = merge_author_thread(root(), rows)
            post = {**root(), "_author_thread": thread}
            TRANSFORM.write_post(post, queue, None, None)
            plan = effective_plan(folder / "card-plan.json")
            data = json.loads(plan.read_text())
            _check_source_coverage(data, thread["text"])
            self.assertTrue(data["content_ready"])
            for path in files: self.assertEqual(path.read_bytes(), before[path])
            self.assertEqual(json.loads((folder / "source.json").read_text())["text"], root()["text"])
            rows.append(reply("3", "2", "새로 추가한 마지막 설명은 기존 글에도 반영되어야 합니다"))
            TRANSFORM.write_post({**root(), "_author_thread": merge_author_thread(root(), rows)}, queue, None, None)
            self.assertNotEqual(effective_plan(folder / "card-plan.json"), plan)
            self.assertTrue(plan.is_file())

    def test_new_job_refreshes_ordinary_thread_but_user_override_is_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary)
            folder = TRANSFORM.write_post(root(), queue, None, None)
            thread = merge_author_thread(root(), [reply("2", text="첫 내용\n\n두 번째 내용\n\n마지막 내용")])
            with patch("web_image_workflow.fetch_author_continuation", return_value=thread) as fetch:
                plan = _prepare_source_plan(folder / "card-plan.json")
                self.assertIn("complete-thread-", str(plan)); fetch.assert_called_once()
            original = folder / "card-plan.json"
            data = json.loads(original.read_text()); data["source_file"] = "source-full.txt"
            original.write_text(json.dumps(data)); (folder / "source-full.txt").write_text("사용자 전체 원문")
            with patch("web_image_workflow.fetch_author_continuation") as fetch:
                self.assertEqual(_prepare_source_plan(original), original.resolve()); fetch.assert_not_called()
            save_thread_source(folder, thread)
            self.assertEqual(effective_plan(original), original.resolve())

    def test_late_reply_to_existing_root_is_collected_with_no_new_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary)
            folder = TRANSFORM.write_post(root(), queue, None, None)
            rows = [reply("2", text="늦게 붙은 후속 본문")]
            with patch.object(FETCH, "QUEUE_DIR", queue), patch.object(FETCH, "fetch_reply_rows", return_value=rows):
                posts, updates = FETCH.enrich_thread_sources([], "test-only", "https://graph.threads.net/v1.0")
            self.assertEqual(updates, 1)
            self.assertEqual(posts[0]["_author_thread"]["reply_count"], 1)
            thread = posts[0]["_author_thread"]
            (folder / "source-thread.json").write_text(json.dumps(thread))
            with patch.object(FETCH, "QUEUE_DIR", queue), patch.object(FETCH, "fetch_reply_rows", return_value=rows):
                self.assertEqual(FETCH.enrich_thread_sources([], "test-only", "https://graph.threads.net/v1.0"), ([], 0))

    def test_missing_root_is_recovered_only_through_known_parent_and_unknown_is_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary)
            TRANSFORM.write_post(root(), queue, None, None)
            linked = reply("2"); linked.pop("root_post")
            unknown = reply("unknown", "deleted"); unknown.pop("root_post")
            with patch.object(FETCH, "QUEUE_DIR", queue), patch.object(FETCH, "fetch_reply_rows", return_value=[unknown, linked]):
                posts, _ = FETCH.enrich_thread_sources([], "test-only", "https://graph.threads.net/v1.0")
            self.assertEqual(posts[0]["_author_thread"]["reply_count"], 1)
            cache = json.loads((queue / ".author-replies.json").read_text())
            self.assertTrue(cache["pagination_complete"])
            self.assertEqual(cache["unassigned_count"], 1)

    def test_reply_pagination_is_complete_and_tokens_are_not_persisted(self):
        api = "https://graph.threads.net/v1.0"
        pages = [{"data": [reply("2")], "paging": {"next": f"{api}/me/replies?after=x&access_token=private"}},
                 {"data": [reply("3", "2")]}]
        with patch.object(FETCH, "request_json", side_effect=pages) as request:
            rows = FETCH.fetch_reply_rows("test-only", api)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("access_token", request.call_args.args[0])
        for url in (f"{api}/999/conversation?after=x", "https://example.com/next"):
            with patch.object(FETCH, "request_json", side_effect=[{"data": [], "paging": {"next": url}}, {"id": "456"}]):
                with self.assertRaises(ValueError): FETCH.fetch_reply_rows("test-only", api)
        repeating = {"data": [], "paging": {"next": f"{api}/me/replies?after=x"}}
        with patch.object(FETCH, "request_json", return_value=repeating):
            with self.assertRaisesRegex(ValueError, "반복"): FETCH.fetch_reply_rows("test-only", api)

    def test_numeric_paging_alias_keeps_requests_on_authenticated_me(self):
        api = "https://graph.threads.net/v1.0"
        pages = [{"data": [reply("2")], "paging": {"next": f"{api}/456/replies?after=x"}},
                 {"data": [reply("3", "2")]}]
        with patch.object(FETCH, "request_json", side_effect=pages) as request:
            self.assertEqual(len(FETCH.fetch_reply_rows("test-only", api)), 2)
            self.assertEqual(request.call_args.args[0], f"{api}/me/replies?after=x")

    def test_incomplete_reply_scan_and_api_error_do_not_look_complete(self):
        api = "https://graph.threads.net/v1.0"
        with patch.object(FETCH, "MAX_PAGES", 1), patch.object(FETCH, "request_json", return_value={"data": [], "paging": {"next": f"{api}/me/replies?after=x"}}):
            with self.assertRaisesRegex(ValueError, "완전하지"): FETCH.fetch_reply_rows("test-only", api)
        with patch.object(FETCH, "request_json", side_effect=RuntimeError("HTTP 403 token=private")):
            with self.assertRaises(ValueError) as caught: FETCH.fetch_reply_rows("test-only", api)
            self.assertNotIn("private", str(caught.exception))

    def test_marker_cannot_escape_source_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = TRANSFORM.write_post(root(), Path(temporary), None, None)
            marker = merge_author_thread(root(), [reply("2")]); marker["plan_file"] = "../../../outside.json"
            (folder / "source-thread.json").write_text(json.dumps(marker))
            with self.assertRaisesRegex(ValueError, "경로"): effective_plan(folder / "card-plan.json")


if __name__ == "__main__": unittest.main()
