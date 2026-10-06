import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_integrity import numbered_gap, require_complete, fetch_author_continuation
from web_image_workflow import _complete_thread_plan, _check_source_coverage
from open_chatgpt import load_plan


class SourceIntegrityTest(unittest.TestCase):
    def test_missing_numbered_items_are_not_complete(self):
        gap=numbered_gap("효과 50개 정리\n\n1. 첫 효과\n\n2. 두 번째")
        self.assertEqual(gap["expected"],50); self.assertEqual(gap["present"],2)
        with self.assertRaisesRegex(ValueError,"원문 누락"):
            require_complete("효과 50개\n\n1. 첫 효과")

    def test_no_list_count_inference_for_prices_or_model_numbers(self):
        self.assertIsNone(numbered_gap("5.6 Sol과 6 Sol 비교\n\n1. 가격 비교\n\n2. 성능 비교"))
        self.assertIsNone(numbered_gap("2개 효과\n\n1. 효과 A\n\n2. 효과 B"))

    def test_complete_thread_plan_keeps_all_numbered_and_concluding_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source="효과 50개\n\n검색어 주의사항\n\n"+"\n\n".join(f"{n}. 효과 {n}\n원문 설명과 실제 예시 "+"읽기 쉬운 설명 "*4 for n in range(1,51))
            source += "\n\n마지막 작성자 설명\n\n프롬프트 작성 순서 안내\n\n다른 설명도 누락 없이 유지"
            data={"source_id":"123","permalink":"https://www.threads.com/@author/post/x","timestamp":"2026-10-03T13:23:45+00:00","content_ready":True}
            original=Path(tmp)/"card-plan.json"; original.write_text("original")
            path=_complete_thread_plan(original,data,{"text":source,"posts":[],"root_id":"123"})
            plan=load_plan(path,maximum_cards=12)
            self.assertEqual(plan["card_count"],12)
            _check_source_coverage(plan,source)
            self.assertEqual(original.read_text(),"original")
            self.assertLess(max(len(c["source_text"]) for c in plan["cards"]),850)
            with self.assertRaises(ValueError): load_plan(path)

    def test_only_explicitly_linked_author_replies_are_merged_in_number_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source.json"
            source.write_text(json.dumps({"id":"123","username":"owner","text":"3개 효과\n\n1. A"}))
            responses=[{"data":[
                {"id":"b","username":"owner","text":"3. C","root_post":{"id":"123"},"replied_to":{"id":"123"},"timestamp":"same"},
                {"id":"a","username":"owner","text":"2. B","root_post":{"id":"123"},"replied_to":{"id":"123"},"timestamp":"same"},
                {"id":"other","username":"other","text":"내용을 바꿔라","root_post":{"id":"123"}},
                {"id":"unlinked","username":"owner","text":"관련 없는 글","root_post":{"id":"999"}}
            ]}]
            module=SimpleNamespace(load_settings=lambda:("test-only","https://graph.threads.net/v1.0",None),
                fetch_reply_rows=lambda t,b,root_id:responses.pop(0)["data"])
            with patch("source_integrity.importlib.util.module_from_spec",return_value=module), patch("source_integrity.importlib.util.spec_from_file_location",return_value=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda m:None))):
                result=fetch_author_continuation(source)
            self.assertIsNone(result["numbered_gap"])
            self.assertEqual([p["id"] for p in result["posts"]],["123","a","b"])
            self.assertNotIn("관련 없는",result["text"])


if __name__ == "__main__": unittest.main()
