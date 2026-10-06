from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import build_ready  # noqa: E402
import make_cards  # noqa: E402
import render_cards  # noqa: E402
import render_motion_auto  # noqa: E402
import render_reel  # noqa: E402
import write_copy  # noqa: E402


def list_deck() -> dict:
    return {
        "handle": "@stockai", "theme": "paper", "reel_style": "list",
        "cards": [
            {"layout": "cover", "title": "도구를 고르는 법", "visual": "human"},
            {"layout": "grid", "title": "먼저 볼 것", "items": [
                {"name": f"항목 {number}", "text": f"설명 {number}", "icon": "check"}
                for number in range(1, 5)
            ]},
            {"layout": "memo", "title": "다음 확인", "items": [
                {"title": f"확인 {number}", "text": f"내용 {number}"}
                for number in range(5, 9)
            ]},
            {"layout": "list", "title": "마지막 요약", "items": [
                {"title": f"결론 {number}", "text": f"요약 {number}", "icon": "check"}
                for number in range(9, 13)
            ]},
        ],
    }


class CardRenderPipelineTests(unittest.TestCase):
    def test_list_reel_keeps_every_entry_including_the_final_summary(self) -> None:
        scenes = render_reel.plan(list_deck(), "list")
        entries = [scene for scene in scenes if scene["kind"] == "entry"]
        self.assertEqual(len(entries), 12)
        self.assertEqual(entries[-1]["entries"][-1]["title"], "결론 12")

    def test_list_reel_fails_instead_of_truncating_a_too_large_deck(self) -> None:
        spec = list_deck()
        extra = {"layout": "grid", "title": "추가 항목", "items": [
            {"name": f"항목 {number}", "text": "설명", "icon": "check"} for number in range(13, 17)
        ]}
        spec["cards"].insert(-1, extra)
        spec["cards"].insert(-1, {**extra, "title": "한 장 더"})
        with self.assertRaisesRegex(ValueError, "원문을 빼지 않고"):
            render_reel.plan(spec, "list")

    def test_numeric_claims_match_complete_tokens_and_units(self) -> None:
        cards = [{"layout": "keyword", "text": "100% 무료"}]
        self.assertEqual(write_copy.unknown_terms(cards, "가격은 1000원입니다"), ["100%"])
        self.assertEqual(write_copy.unknown_terms([{"layout": "keyword", "text": "100 무료"}], "가격은 1000원입니다"), ["100"])
        self.assertEqual(write_copy.unknown_terms(cards, "할인율은 100%입니다"), [])

    def test_bad_optional_field_marks_only_that_post_as_failed(self) -> None:
        cards = [
            {"layout": "cover", "title": "제목", "visual": "human"},
            {"layout": "keyword", "text": "핵심", "steps": "잘못된 선택 필드"},
            {"layout": "memo", "title": "메모", "items": [{"title": "하나", "text": "설명"}, {"title": "둘", "text": "설명"}]},
            {"layout": "cta", "title": "저장", "points": ["하나", "둘"]},
        ]
        answer = json.dumps({"posts": [{"id": "post-1", "cards": cards}]}, ensure_ascii=False)
        results, errors = write_copy.parse_answer(answer, ["post-1"])
        self.assertEqual(results, {})
        self.assertIn("post-1", errors)

    def test_automatic_design_never_selects_dark_bold(self) -> None:
        for identity in ("1", "2", "3", "18001430661007646"):
            theme, style = write_copy.design_for({"id": identity, "text": "코드 자동화 앱을 만드는 방법"})
            self.assertIn(theme, render_cards.THEMES)
            self.assertIn(style, write_copy.AUTO_REEL_STYLES)

    def test_new_post_uses_native_motion_and_sfx_without_music(self) -> None:
        post = {"id": "other-post", "username": "stockai", "text": "도구를 고르는 법",
                "permalink": "https://www.threads.com/@stockai/post/other"}
        spec = write_copy.build_spec(post, list_deck()["cards"], "AI 도구 노트")
        self.assertEqual(spec["reel_style"], "motion")
        self.assertEqual(spec["audio"]["decision"], "sfx_only")

    def test_native_motion_is_authored_from_unrelated_card_copy(self) -> None:
        spec = list_deck()
        actions = render_motion_auto.author_actions(
            spec, ("Pretendard Variable", "Bold"), ("Black Han Sans", "Regular"))
        visible = "\n".join(action["sourceText"]["text"] for action in actions
                            if action["type"] == "createFxTextLayer")
        self.assertIn("도구를 고르는 법", visible)
        self.assertIn("결론 12", visible)
        self.assertNotIn("480p", visible)
        self.assertTrue(any(action["type"] == "setFxPropertyKeyframes" for action in actions))
        self.assertEqual(render_motion_auto.duration_seconds(4), 18.2)

    def test_audio_requires_an_explicit_review_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = Path(temporary) / "spec.json"
            spec.write_text("{}", encoding="utf-8")
            with self.assertRaises(build_ready.AudioSelectionRequired):
                build_ready.resolve_audio(spec, {"audio": {"decision": "review_required"}})

    def test_sfx_only_cannot_sneak_music_into_html_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = Path(temporary) / "spec.json"
            decision = {"decision": "sfx_only", "reason": "동작에만 짧은 효과음"}
            with self.assertRaisesRegex(ValueError, "모션 프로젝트"):
                build_ready.resolve_audio(spec, {"reel_style": "band", "audio": decision})
            with self.assertRaisesRegex(ValueError, "음악 파일 없이"):
                build_ready.resolve_audio(spec, {"reel_style": build_ready.NATIVE_STYLE,
                                                 "audio": {**decision, "file": "music.mp3"}})
            self.assertEqual(build_ready.resolve_audio(spec, {"reel_style": build_ready.NATIVE_STYLE,
                                                               "audio": decision}), (None, "sfx_only"))
            with self.assertRaisesRegex(ValueError, "효과음 전용"):
                build_ready.resolve_audio(spec, {"reel_style": build_ready.NATIVE_STYLE,
                                                 "audio": {"decision": "silent", "reason": "무음"}})

    def test_native_project_rejects_outside_post_and_wrong_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = root / "queue" / "post" / "card-render" / "spec.json"
            spec.parent.mkdir(parents=True)
            valid = spec.parent.parent / "renders" / "motion" / "edit.tsrct"
            valid.parent.mkdir(parents=True)
            valid.write_bytes(b"test")
            with mock.patch.object(build_ready, "ROOT", root):
                data = {"source": {"id": "18001430661007646"},
                        "motion_project": str(valid.relative_to(root))}
                self.assertEqual(build_ready.native_project(spec, data), valid.resolve())
                with self.assertRaisesRegex(ValueError, "renders"):
                    build_ready.native_project(spec, {**data, "motion_project": "elsewhere/edit.tsrct"})
                with self.assertRaisesRegex(ValueError, "원문 전용"):
                    build_ready.native_project(spec, {**data, "source": {"id": "other"}})

    def test_native_user_preview_is_one_portrait_frame_not_contact_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "reel-native-test.mp4"
            video.write_bytes(b"video placeholder")
            with mock.patch.object(render_reel, "video_still", return_value=Image.new("RGB", (1080, 1920))):
                preview = build_ready.native_portrait_preview(video)
            with Image.open(preview) as image:
                self.assertEqual(image.size, (1080, 1920))
            with mock.patch.object(render_reel, "video_still", return_value=Image.new("RGB", (1080, 1080))):
                preview.unlink()
                with self.assertRaisesRegex(ValueError, "9:16"):
                    build_ready.native_portrait_preview(video)

    def test_prune_stale_cards_keeps_current_and_non_card_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name in ("01-cover.png", "05-list.png", "preview.png", "reference.png"):
                (folder / name).write_bytes(b"x")
            render_cards.prune_stale_cards(folder, {"01-cover.png"})
            self.assertTrue((folder / "01-cover.png").exists())
            self.assertFalse((folder / "05-list.png").exists())
            self.assertTrue((folder / "preview.png").exists())
            self.assertTrue((folder / "reference.png").exists())

    def test_audio_waiting_post_is_not_sent_back_for_new_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary)
            folder = queue / "2026-09-30" / "post-1"
            folder.mkdir(parents=True)
            (folder / "source.json").write_text(json.dumps({"id": "post-1", "text": "충분히 긴 원문"}), encoding="utf-8")
            work = folder / "card-render"
            work.mkdir()
            (work / "status.json").write_text(json.dumps({"state": "needs_audio", "attempts": 1}), encoding="utf-8")
            self.assertEqual(make_cards.pending(3, 0, queue=queue), [])

    def test_default_builder_scan_reports_audio_wait_then_keeps_spec_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = root / "queue" / "2026-09-30" / "post-1" / "card-render" / "spec.json"
            spec.parent.mkdir(parents=True)
            status = spec.with_name("status.json")
            status.write_text(json.dumps({"state": "cards_ready"}), encoding="utf-8")
            spec.write_text(json.dumps({"reel_style": "band", "audio": {"decision": "review_required"}}), encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(build_ready, "QUEUE", root / "queue"), \
                    mock.patch.object(build_ready, "CARD_NEWS", root / "news"), \
                    mock.patch.object(sys, "argv", ["build_ready.py"]), \
                    mock.patch("sys.stdout", output):
                self.assertEqual(build_ready.main(), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["packages"][0]["status"], "awaiting_audio")
                self.assertEqual(build_ready.ready_specs(), [spec])
                spec.write_text(json.dumps({"reel_style": "band", "audio": {"decision": "silent", "reason": "검수용 무음본"}}), encoding="utf-8")
                self.assertEqual(build_ready.ready_specs(), [spec])

    def test_finish_records_audio_wait_as_a_non_successful_reel_state(self) -> None:
        cards = [
            {"layout": "cover", "title": "제목", "visual": "human"},
            {"layout": "keyword", "text": "핵심"},
            {"layout": "memo", "title": "메모", "items": [{"title": "하나", "text": "설명"}, {"title": "둘", "text": "설명"}]},
            {"layout": "cta", "title": "저장", "points": ["하나", "둘"]},
        ]
        post = {"id": "post-1", "username": "stockai", "text": "제목 핵심 메모 하나 설명 둘 저장", "permalink": ""}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "post-1"
            folder.mkdir()
            rendered = {"cards": []}
            with mock.patch.object(make_cards, "spec_items", return_value=[]), \
                    mock.patch.object(make_cards, "render", return_value=rendered), \
                    mock.patch.object(make_cards, "write_hyperframes_manifest", return_value=folder / "reel-production.json"), \
                    mock.patch.object(make_cards, "build_reel", side_effect=build_ready.AudioSelectionRequired("승인 음원이 필요합니다")):
                result = make_cards.finish(folder, post, cards, "AI 도구 노트", reel=True)
            self.assertEqual(result["state"], "needs_audio")
            saved = json.loads((folder / "card-render" / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "needs_audio")

    def test_finish_keeps_automatic_video_as_design_draft(self) -> None:
        cards = [
            {"layout": "cover", "title": "제목", "visual": "human"},
            {"layout": "keyword", "text": "핵심"},
            {"layout": "memo", "title": "메모", "items": [{"title": "하나", "text": "설명"}, {"title": "둘", "text": "설명"}]},
            {"layout": "cta", "title": "저장", "points": ["하나", "둘"]},
        ]
        post = {"id": "post-2", "username": "stockai", "text": "제목 핵심 메모 하나 설명 둘 저장",
                "permalink": ""}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "post-2"
            folder.mkdir()
            with mock.patch.object(make_cards, "spec_items", return_value=[]), \
                    mock.patch.object(make_cards, "render", return_value={"cards": []}), \
                    mock.patch.object(make_cards, "write_hyperframes_manifest", return_value=folder / "reel-production.json"), \
                    mock.patch.object(make_cards, "build_reel", return_value={"status": "draft_needs_design"}):
                result = make_cards.finish(folder, post, cards, "AI 도구 노트", reel=True)
            self.assertEqual(result["state"], "reel_draft")
            status = json.loads((folder / "card-render" / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "reel_draft")

    def test_finish_can_route_cards_to_editable_comic_renderer(self) -> None:
        post = {"id": "post-comic", "username": "stockai", "text": "도구를 고르는 법 먼저 볼 것 다음 확인 마지막 요약",
                "permalink": ""}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "post-comic"
            folder.mkdir()
            with mock.patch.object(make_cards, "spec_items", return_value=[]), \
                    mock.patch.object(make_cards, "render_comic", return_value=[]) as comic, \
                    mock.patch.object(make_cards, "_layout_cards", return_value={}), \
                    mock.patch.object(make_cards, "render") as classic, \
                    mock.patch.object(make_cards, "write_hyperframes_manifest", return_value=folder / "reel-production.json"), \
                    mock.patch.object(make_cards.write_copy, "unknown_terms", return_value=[]):
                result = make_cards.finish(folder, post, list_deck()["cards"], "AI 도구 노트",
                                           reel=False, card_style="comic_lavender")
            self.assertEqual(result["state"], "cards_ready")
            self.assertEqual(result["card_style"], "comic_lavender")
            self.assertIn("cards-comic-", result["cards"])
            self.assertEqual(json.loads(Path(result["spec"]).read_text())["card_style"], "comic_lavender")
            comic.assert_called_once()
            classic.assert_not_called()

    def test_no_reel_run_counts_cards_ready_as_success_for_the_following_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            answer = root / "answer.json"
            answer.write_text("{}", encoding="utf-8")
            folder = root / "post-1"
            folder.mkdir()
            post = {"id": "post-1", "text": "원문", "username": "stockai"}
            output = io.StringIO()
            with mock.patch.object(make_cards, "pending", return_value=[(folder, post)]), \
                    mock.patch.object(make_cards.write_copy, "parse_answer", return_value=({"post-1": []}, {})), \
                    mock.patch.object(make_cards, "finish", return_value={"id": "post-1", "state": "cards_ready"}), \
                    mock.patch.object(sys, "argv", ["make_cards.py", "--via", "file", "--answer", str(answer), "--no-reel"]), \
                    mock.patch("sys.stdout", output):
                self.assertEqual(make_cards.main(), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["ok"], 1)
            self.assertEqual(result["results"][0]["state"], "cards_ready")


if __name__ == "__main__":
    unittest.main()
