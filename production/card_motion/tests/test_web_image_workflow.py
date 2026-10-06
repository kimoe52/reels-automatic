from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

MOTION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MOTION))
from web_image_workflow import WebImageWorkflow, validate_review, generation_prompt, _sha  # noqa: E402


class FakeBrowser:
    def __init__(self, verdicts: list[str] | None = None) -> None:
        self.verdicts = iter(verdicts or ["pass"] * 8); self.sent: list[tuple[str, bool]] = []; self.replies = {}; self.preflight_error = False
    def preflight(self) -> None:
        if self.preflight_error: raise RuntimeError("unavailable")
    def open(self, conversation_url: str | None) -> None: pass
    def recover(self, request_id: str, *, image: bool): return self.replies.get(request_id)
    def request(self, prompt: str, request_id: str, *, image: bool):
        self.sent.append((request_id, image))
        if image:
            reply = {"request_id": request_id, "conversation_url": "https://chatgpt.com/c/x", "message_id": request_id, "images": [{"id": request_id}]}
        else:
            nonce = prompt.split('"nonce":"', 1)[1].split('"', 1)[0]
            card = int(prompt.split('"card":', 1)[1].split(',', 1)[0])
            verdict = next(self.verdicts)
            reply = {"request_id": request_id, "text": json.dumps({"nonce": nonce, "request_id": request_id, "card": card, "verdict": verdict, "issues": ["수정"] if verdict != "pass" else [], "checked": {k: True for k in ("numbers", "units", "sources", "unsupported_claims", "omissions", "korean_text")}}, ensure_ascii=False)}
        self.replies[request_id] = reply; return reply
    def save_image(self, image_id: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", (800, 1000), "white").save(destination)


class WebImageWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        library = tempfile.TemporaryDirectory()
        self.addCleanup(library.cleanup)
        cards = patch("web_image_workflow.CARD_NEWS", Path(library.name) / "card-news")
        cards.start(); self.addCleanup(cards.stop)

    def _plan(self, root: Path) -> Path:
        (root / "source.txt").write_text("\n\n".join(f"{i}장 근거" for i in range(1, 5)), encoding="utf-8")
        path = root / "card-plan.json"
        path.write_text(json.dumps({"card_count": 4, "content_ready": True, "source_file": "source.txt", "title": "테스트", "cards": [{"number": i, "role": "내용", "source_text": f"{i}장 근거"} for i in range(1, 5)]}, ensure_ascii=False), encoding="utf-8")
        return path
    def _builder(self, images, output, title):
        video = images[0].parent.parent / "ok.mp4"; video.parent.mkdir(parents=True, exist_ok=True); video.write_bytes(b"video")
        return {"status": "ready_for_review", "video": str(video)}

    def test_strict_review(self) -> None:
        good = {"nonce": "n", "request_id": "r", "card": 1, "verdict": "pass", "issues": [], "checked": {k: True for k in ("numbers", "units", "sources", "unsupported_claims", "omissions", "korean_text")}}
        self.assertIsNotNone(validate_review(json.dumps(good), nonce="n", request_id="r", card=1))
        good["checked"]["units"] = False
        self.assertIsNone(validate_review(json.dumps(good), nonce="n", request_id="r", card=1))

    def test_generation_asks_for_one_card_not_number_of_images(self) -> None:
        plan = {"card_count": 12, "cards": [{"source_text": "근거"}] * 12}
        prompt = generation_prompt(plan, "전체 원문", 12)
        self.assertIn("12번째 카드만", prompt)
        self.assertIn("이미지 수는 정확히 한 장", prompt)
        self.assertNotIn("카드뉴스 12장만", prompt)
        self.assertIn("정보는 card_evidence만", prompt)
        self.assertIn("이 장의 근거 문구를 빠짐없이", prompt)

    def test_one_deck_correction_then_complete_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowser(["revise", "pass", "pass", "pass", "pass"])
            flow = WebImageWorkflow(self._plan(Path(tmp)), browser, reel_builder=self._builder, verifier=lambda _: True)
            self.assertEqual(flow.run()["web_image_state"], "complete")
            self.assertEqual(flow.run()["web_image_state"], "complete")
            self.assertEqual(sum(image for _, image in browser.sent), 5)

    def test_unknown_after_correction_is_saved_not_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            called = []
            flow = WebImageWorkflow(self._plan(Path(tmp)), FakeBrowser(["unknown", "pass", "pass", "pass", "unknown"]), reel_builder=lambda *args: called.append(args), verifier=lambda _: True)
            result = flow.run()
            self.assertEqual(result["web_image_state"], "needs_review")
            self.assertEqual(result["revision_round"], 0)
            self.assertFalse(called)

    def test_resume_uses_saved_reply_without_duplicate_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowser(); plan = self._plan(Path(tmp)); flow = WebImageWorkflow(plan, browser, reel_builder=self._builder, verifier=lambda _: True)
            state = flow._new(); state["cards"]["1"]["attempts"].append({"number": 1, "generation": {"request_id": "old", "checkpoint": "before_send"}}); flow._save(state)
            browser.replies["old"] = {"request_id": "old", "images": [{"id": "old"}], "conversation_url": "x"}
            flow.run(no_reel=True)
            self.assertNotIn(("old", True), browser.sent)

    def test_source_drift_needs_attention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan = self._plan(root); flow = WebImageWorkflow(plan, FakeBrowser(), reel_builder=self._builder, verifier=lambda _: True); flow._save(flow._new())
            (root / "source.txt").write_text("바뀐 원문", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "원문과 다르"):
                WebImageWorkflow(plan, FakeBrowser()).run()

    def test_preflight_and_bad_ratio_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowser(); browser.preflight_error = True
            self.assertEqual(WebImageWorkflow(self._plan(Path(tmp)), browser).run()["web_image_state"], "browser_pending")
        class Wide(FakeBrowser):
            def save_image(self, image_id, destination):
                destination.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", (1000, 1000), "white").save(destination)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(WebImageWorkflow(self._plan(Path(tmp)), Wide()).run()["web_image_state"], "needs_review")

    def test_render_retry_does_not_regenerate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowser(); plan = self._plan(Path(tmp))
            failed = WebImageWorkflow(plan, browser, reel_builder=lambda *args: (_ for _ in ()).throw(RuntimeError("render")), verifier=lambda _: True)
            self.assertEqual(failed.run()["web_image_state"], "render_pending")
            sends = len(browser.sent)
            succeeded = WebImageWorkflow(plan, browser, reel_builder=self._builder, verifier=lambda _: True)
            self.assertEqual(succeeded.run()["web_image_state"], "complete")
            self.assertEqual(len(browser.sent), sends)

    def test_pass_with_issues_and_wrong_card_type_are_rejected(self) -> None:
        value = {"nonce":"n", "request_id":"r", "card":1, "verdict":"pass", "issues":["숫자 오류"],
            "checked":{k:True for k in ("numbers","units","sources","unsupported_claims","omissions","korean_text")}}
        self.assertIsNone(validate_review(json.dumps(value), nonce="n", request_id="r", card=1))
        value.update(issues=[], card=True)
        self.assertIsNone(validate_review(json.dumps(value), nonce="n", request_id="r", card=1))

    def test_ambiguous_review_stops_without_consuming_correction(self) -> None:
        class Interrupted(FakeBrowser):
            def request(self, prompt, request_id, *, image):
                if not image: raise RuntimeError("connection lost")
                return super().request(prompt, request_id, image=image)
        with tempfile.TemporaryDirectory() as tmp:
            browser = Interrupted()
            flow = WebImageWorkflow(self._plan(Path(tmp)), browser)
            result = flow.run()
            self.assertEqual(result["web_image_state"], "browser_pending")
            self.assertEqual(result["revision_round"], 0)
            self.assertEqual(len(browser.sent), 1)
            state = json.loads(flow.state_path.read_text())
            self.assertNotIn("review", state["cards"]["1"]["attempts"][0])

    def test_permission_retry_is_not_permanently_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowser(); browser.preflight_error = True
            flow = WebImageWorkflow(self._plan(Path(tmp)), browser, reel_builder=self._builder, verifier=lambda _:True)
            self.assertEqual(flow.run()["web_image_state"], "browser_pending")
            browser.preflight_error = False
            self.assertEqual(flow.run()["web_image_state"], "complete")

    def test_deleted_completed_card_does_not_reuse_completed_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowser()
            flow = WebImageWorkflow(self._plan(Path(tmp)), browser, reel_builder=self._builder, verifier=lambda _:True)
            flow.run()
            state = json.loads(flow.state_path.read_text())
            Path(state["cards"]["1"]["attempts"][0]["image"]["path"]).unlink()
            self.assertEqual(flow.run()["web_image_state"], "needs_attention")
            self.assertEqual(len(browser.sent), 8)

    def test_unapproved_renderer_status_never_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            flow = WebImageWorkflow(self._plan(Path(tmp)), FakeBrowser(),
                reel_builder=lambda *args:{"status":"needs_layer_repair","video":"fake.mp4"}, verifier=lambda _:True)
            self.assertEqual(flow.run()["web_image_state"], "render_pending")

    def test_changed_render_policy_rebuilds_only_video_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowser(); current_digest = ["v1"]; builds = []
            def builder(images, output, title):
                output.mkdir(parents=True, exist_ok=True)
                manifest = output / "reel-production.json"
                if not manifest.exists(): manifest.write_text("{}")
                video = output / f"{current_digest[0]}.mp4"; video.write_bytes(b"video")
                builds.append(current_digest[0])
                return {"status":"ready_for_review", "video":str(video),
                        "manifest":str(manifest), "renderer":"hyperframes_element_story",
                        "digest":current_digest[0],
                        "source_inputs":[{"file":manifest.name,"sha256":_sha(manifest)}]}
            flow = WebImageWorkflow(self._plan(Path(tmp)), browser, reel_builder=builder, verifier=lambda _:True)
            with patch("native_focus.Deck") as deck:
                deck.return_value.digest.side_effect = lambda:current_digest[0]
                self.assertEqual(flow.run()["web_image_state"], "complete")
                current_digest[0] = "v2"
                self.assertEqual(flow.run()["web_image_state"], "complete")
                self.assertEqual(flow.run()["web_image_state"], "complete")
            self.assertEqual(builds, ["v1", "v2"])
            self.assertEqual(len(browser.sent), 8)
            state = flow._load()
            self.assertEqual(len(state["previous_renders"]), 1)
            self.assertTrue(Path(state["previous_renders"][0]["video"]).is_file())
            self.assertEqual(state["render"]["digest"], "v2")

    def test_changed_render_artwork_is_not_treated_as_policy_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); calls = []; browser = FakeBrowser()
            def builder(images, output, title):
                output.mkdir(parents=True, exist_ok=True)
                manifest=output/"reel-production.json"; manifest.write_text("{}")
                video=output/"video.mp4"; video.write_bytes(b"video"); calls.append(True)
                return {"status":"ready_for_review", "video":str(video), "manifest":str(manifest),
                        "renderer":"hyperframes_element_story", "digest":"v1",
                        "source_inputs":[{"file":manifest.name,"sha256":_sha(manifest)}]}
            flow=WebImageWorkflow(self._plan(root),browser,reel_builder=builder,verifier=lambda _:True)
            self.assertEqual(flow.run()["web_image_state"], "complete")
            manifest=Path(flow._load()["render"]["manifest"]); manifest.write_text('{"unreviewed":true}')
            with patch("native_focus.Deck") as deck:
                self.assertEqual(flow.run()["web_image_state"], "needs_attention")
                deck.assert_not_called()
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(browser.sent), 8)

    def test_correction_round_schedules_all_failed_cards_before_first_send(self) -> None:
        class FailsCorrection(FakeBrowser):
            def request(self, prompt, request_id, *, image):
                if image and "이전 결과의" in prompt: raise RuntimeError("interrupted")
                return super().request(prompt, request_id, image=image)
        with tempfile.TemporaryDirectory() as tmp:
            flow = WebImageWorkflow(self._plan(Path(tmp)), FailsCorrection(["revise"]*4))
            self.assertEqual(flow.run()["web_image_state"], "browser_pending")
            state = json.loads(flow.state_path.read_text())
            self.assertEqual(state["revision_round"], 1)
            self.assertTrue(all(len(card["attempts"]) == 2 for card in state["cards"].values()))

    def test_plan_invention_is_rejected_before_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._plan(Path(tmp)); value = json.loads(path.read_text())
            value["cards"][0]["source_text"] = "원문에 없는 성과 200%"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "원문과 다르"):
                WebImageWorkflow(path, FakeBrowser())

    def test_incomplete_numbered_source_cannot_bypass_cli_precheck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self._plan(root)
            bodies = ["효과 50개\n\n1. 첫 효과", "2. 둘째 효과", "3. 셋째 효과", "4. 넷째 효과"]
            (root / "source.txt").write_text("\n\n".join(bodies), encoding="utf-8")
            data = json.loads(path.read_text())
            for card, body in zip(data["cards"], bodies): card["source_text"] = body
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            browser = FakeBrowser()
            with self.assertRaisesRegex(ValueError, "원문 누락"):
                WebImageWorkflow(path, browser)
            self.assertFalse(browser.sent)

    def test_job_state_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            flow = WebImageWorkflow(self._plan(Path(tmp)), FakeBrowser())
            flow.run(no_reel=True)
            self.assertEqual(flow.state_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(flow.root.stat().st_mode & 0o777, 0o700)
