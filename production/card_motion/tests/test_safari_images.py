from __future__ import annotations
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safari_images import SafariBlocked, SafariImages, conversation_url, EVALUATE, DOM


class SafariAdapterTest(unittest.TestCase):
    def test_all_non_chatgpt_and_non_conversation_urls_are_rejected(self):
        for address in ("https://chatgpt.com.attacker.test/c/x", "https://chatgpt.com@attacker.test/c/x",
                        "http://chatgpt.com/", "https://chatgpt.com/settings", "https://chatgpt.com/c/x?token=secret"):
            with self.subTest(address=address), self.assertRaises(SafariBlocked): conversation_url(address)
        self.assertEqual(conversation_url(None), "https://chatgpt.com/")
        self.assertEqual(conversation_url("https://chatgpt.com/c/x"), "https://chatgpt.com/c/x")

    def test_js_is_private_file_not_a_large_or_executable_shell_argument(self):
        browser = SafariImages(references=[]); browser.window_id = 123
        captured = []
        def apple(script, *args):
            self.assertEqual(script, EVALUATE)
            script_path = Path(args[1])
            self.assertEqual(script_path.stat().st_mode & 0o777, 0o600)
            self.assertIn("location.origin !== 'https://chatgpt.com'", script_path.read_text())
            captured.append(script_path)
            return '{"ok":true}'
        with patch.object(browser, "_apple", side_effect=apple):
            self.assertEqual(browser._eval("return JSON.stringify({ok:true});"), {"ok":True})
        self.assertFalse(captured[0].exists())

    def test_submitted_request_cannot_be_declared_unsent_if_marker_missing(self):
        browser = SafariImages(references=[])
        browser.ledger["requests"]["r"] = {"stage":"before_send"}
        with patch.object(browser, "_eval", return_value={"ready":"complete","composer":True,"count":0,"found":False}):
            with self.assertRaisesRegex(SafariBlocked, "중복 전송"):
                browser.recover("r", image=True)

    def test_existing_conversation_absence_fails_closed(self):
        browser = SafariImages(references=[])
        with patch.object(browser, "_eval", side_effect=[{"ready":"complete","composer":True,"count":5,"found":False}, {"path":"/c/existing"}]):
            with self.assertRaises(SafariBlocked): browser.recover("r", image=False)

    def test_clean_empty_new_window_can_confirm_unsent_request(self):
        browser = SafariImages(references=[])
        with patch.object(browser, "_eval", side_effect=[{"ready":"complete","composer":True,"count":0,"found":False}, {"path":"/"}]):
            self.assertIsNone(browser.recover("r", image=True))

    def test_ledger_survives_process_restart_with_window_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = SafariImages(references=[]); first.bind_job(root)
            first.ledger.update(window_id=123, requests={"r":{"stage":"accepted"}}); first._checkpoint()
            second = SafariImages(references=[]); second.bind_job(root)
            self.assertEqual(second.window_id, 123)
            self.assertEqual(second.ledger["requests"]["r"]["stage"], "accepted")
            self.assertEqual((root/"safari.json").stat().st_mode & 0o777, 0o600)

    def test_additional_tabs_are_not_controlled(self):
        self.assertIn("count of tabs of targetWindow", EVALUATE)

    @unittest.skipUnless(shutil.which("node"), "Node is required for the pure DOM fixture")
    def test_accessible_heading_replies_stay_bound_when_earlier_history_disappears(self):
        # Pure local fixture: this does not open or control a browser.
        fixture = r'''
let headings = [];
const document = {querySelectorAll:s => s === 'main h4' ? headings : []};
const location = {origin:'https://chatgpt.com',pathname:'/c/fixture'};
function message(role, text, code, images=[]) {
  const content = {textContent:text,querySelector:s=>s==='pre code' && code ? {textContent:code} : null};
  const parent = {getAttribute:()=>null, querySelector:()=>content,
    querySelectorAll:s=>s==='img' ? images : []};
  return {textContent:role==='user'?'내가 한 말:':'ChatGPT 답변:',parentElement:parent,id:''};
}
const id = '1234567890abcdef1234567890abcdef';
const user = message('user','[CARD_REQUEST '+id+']\n원문');
const assistant = message('assistant','JSON 복사 버튼', '{"verdict":"pass"}',
  [{complete:true,naturalWidth:1122,naturalHeight:1402,alt:'생성된 이미지'}]);
headings = [message('user','이전 질문'), message('assistant','이전 답'), user, assistant];
'''
        script = fixture + DOM + r'''
const before = responseFor(id);
headings = [user,assistant];
const after = responseFor(id);
process.stdout.write(JSON.stringify({before,after}));
'''
        result = subprocess.run([shutil.which("node"), "-e", script], check=True,
                                capture_output=True, text=True)
        value = json.loads(result.stdout)
        self.assertEqual(value["before"]["message_id"], value["after"]["message_id"])
        self.assertEqual(value["after"]["message_id"], "request-1234567890abcdef1234567890abcdef-reply-0")
        self.assertEqual(value["after"]["text"], '{"verdict":"pass"}')
        self.assertEqual(value["after"]["images"], [{"id":value["after"]["message_id"]+":image-0"}])

    def test_existing_reference_chips_are_reused_without_duplicate_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "ref.png"; ref.write_bytes(b"reference")
            browser = SafariImages(references=[ref], poll=0)
            with patch.object(browser, "_eval", return_value={"present":1,"uploading":False}) as evaluate:
                browser._attachments()
            self.assertEqual(evaluate.call_count, 3)
            self.assertTrue(all("new DataTransfer" not in call.args[0] for call in evaluate.call_args_list))
            self.assertIn("getAttribute('alt')", evaluate.call_args.args[0])

    def test_partial_reference_set_stops_before_uploading(self):
        browser = SafariImages(references=[Path("one"), Path("two")])
        with patch.object(browser, "_eval", return_value={"present":1,"uploading":False}) as evaluate:
            with self.assertRaisesRegex(SafariBlocked, "일부만"):
                browser._attachments()
        self.assertEqual(evaluate.call_count, 1)

    def test_new_reference_set_uploads_once_and_waits_for_accessible_chips(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "ref.png"; ref.write_bytes(b"reference")
            browser = SafariImages(references=[ref], poll=0)
            states = [{"present":0,"uploading":False},{"attached":1},
                      {"present":1,"uploading":True},{"present":1,"uploading":False},
                      {"present":1,"uploading":False}]
            with patch.object(browser, "_eval", side_effect=states) as evaluate:
                browser._attachments()
            self.assertEqual(sum("new DataTransfer" in call.args[0] for call in evaluate.call_args_list), 1)
