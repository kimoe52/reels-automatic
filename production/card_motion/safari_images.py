"""Safari adapter used by the standalone content widget, not an API client.

Only a dedicated ChatGPT window is controlled. DOM access uses Safari's public
Apple Events interface; this module never enables that permission, reads cookies,
calls a model endpoint, or inspects an unrelated tab. Images are saved with the
page's download control, not screenshots or scraped thumbnails.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image
from storage import project_path

ROOT = Path(__file__).resolve().parents[2]
CHATGPT = "https://chatgpt.com/"
MAX_IMAGE_BYTES = 30 * 1024 * 1024


class SafariBlocked(RuntimeError):
    pass


def conversation_url(value: str | None) -> str:
    if not value:
        return CHATGPT
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.netloc != "chatgpt.com"
            or parsed.query or parsed.fragment
            or not (parsed.path == "/" or parsed.path.startswith("/c/"))):
        raise SafariBlocked("전용 ChatGPT 주소가 아니어서 브라우저 제어를 중단했어요")
    return value


OPEN_WINDOW = '''on run argv
    tell application "Safari"
        activate
        make new document with properties {URL:item 1 of argv}
        return id of front window
    end tell
end run'''

NAVIGATE = '''on run argv
    tell application "Safari"
        set targetWindow to first window whose id is (item 1 of argv as integer)
        if (count of tabs of targetWindow) is not 1 then error "전용 창에 다른 탭이 추가되었습니다"
        set URL of current tab of targetWindow to item 2 of argv
    end tell
end run'''

EVALUATE = '''on run argv
    tell application "Safari"
        set targetWindow to first window whose id is (item 1 of argv as integer)
        if (count of tabs of targetWindow) is not 1 then error "전용 창에 다른 탭이 추가되었습니다"
        set targetTab to current tab of targetWindow
        set pageURL to URL of targetTab
        if pageURL is not "https://chatgpt.com/" and pageURL does not start with "https://chatgpt.com/c/" then
            error "전용 ChatGPT 탭의 주소가 바뀌었습니다"
        end if
        set sourceText to read POSIX file (item 2 of argv) as «class utf8»
        return do JavaScript sourceText in targetTab
    end tell
end run'''

# The small JS contract is kept in one file so selector failures stop visibly
# instead of silently falling back to clipboard polling or hidden web endpoints.
DOM = r'''
const visible = e => !!e && e.getClientRects().length > 0;
const label = e => ((e.getAttribute('aria-label') || '') + ' ' +
  (e.getAttribute('title') || '') + ' ' + (e.textContent || '')).trim();
const composer = () => document.querySelector('#prompt-textarea[contenteditable="true"]') ||
  document.querySelector('textarea#prompt-textarea') || document.querySelector('main [contenteditable="true"][role="textbox"]');
const busy = () => Array.from(document.querySelectorAll('button')).some(e =>
  visible(e) && /^(stop|중지)|stop generating|생성 중지|응답 중지|생성 멈추기/i.test(label(e)));
const turns = () => {
  let nodes = Array.from(document.querySelectorAll('[data-message-author-role]'));
  if (nodes.length) return nodes.map((e, index) => {
    const turn = e.closest('article') || e;
    const message = e.getAttribute('data-message-id') || turn.getAttribute('data-message-id') ||
      turn.getAttribute('data-testid') || '';
    return {e, turn, role:e.getAttribute('data-message-author-role'),
      id:message || 'turn-' + index, text:e.innerText || ''};
  });
  // The current ChatGPT web app exposes accessible message headings instead
  // of the classic article/data-message-author-role wrappers.
  const messages = Array.from(document.querySelectorAll('main h4')).filter(h =>
    /^(내가 한 말:|ChatGPT 답변:|You said:|ChatGPT said:)$/i.test((h.textContent || '').trim()))
    .map((h,index) => {
      const turn=h.parentElement;
      const role=/내가 한 말|You said/i.test(h.textContent) ? 'user' : 'assistant';
      const e=turn.querySelector(':scope > div') || turn;
      const code=e.querySelector('pre code');
      return {e,turn,role,id:turn.getAttribute('data-message-id') || h.id || 'turn-' + index,
        text:role==='assistant' && code ? code.textContent : (e.textContent || '')};
    });
  // Accessible headings have no durable message id. Index-only ids change
  // when earlier history is virtualized. Anchor a reply to its own request.
  let request = null, answer = 0;
  for (const t of messages) {
    if (t.role === 'user') {
      const match = t.text.match(/\[CARD_REQUEST ([0-9a-f]{32})\]/);
      request = match ? match[1] : null; answer = 0;
    } else if (request) t.id = 'request-' + request + '-reply-' + answer++;
  }
  return messages;
};
const imageNodes = t => Array.from(t.turn.querySelectorAll('img')).filter(e =>
  e.complete && e.naturalWidth >= 300 && e.naturalHeight >= 300 &&
  !/avatar|profile|아바타|프로필/i.test(e.alt || ''));
const responseFor = id => {
  const ts = turns();
  const marker = '[CARD_REQUEST ' + id + ']';
  const at = ts.findIndex(t => t.role === 'user' && t.text.includes(marker));
  if (at < 0) {
    const more=ts.filter(t=>t.role==='user').flatMap(t=>Array.from(t.turn.querySelectorAll('button')))
      .find(e=>visible(e) && /^(더 보기|Show more)$/i.test(label(e)));
    if(more) {more.click(); return {found:false,expanding:true};}
    return {found:false};
  }
  const subsequent = ts.slice(at + 1);
  const nextUser = subsequent.findIndex(t => t.role === 'user');
  const own = nextUser < 0 ? subsequent : subsequent.slice(0, nextUser);
  const answers = own.filter(t => t.role === 'assistant');
  const reply = answers[answers.length - 1];
  if (!reply) return {found:true, busy:true};
  const imgs = imageNodes(reply);
  return {found:true, busy:busy(), message_id:reply.id, text:reply.text,
    images:imgs.map((_, i) => ({id:reply.id + ':image-' + i})),
    conversation_url:location.origin + location.pathname};
};
'''


class SafariImages:
    def __init__(self, *, timeout: float = 900, poll: float = 2,
                 downloads: Path | None = None, references: list[Path] | None = None,
                 reference_caption: str | None = None):
        self.timeout = timeout
        self.poll = poll
        self.downloads = downloads or Path.home() / "Downloads"
        self.references = references if references is not None else [
            project_path("cards_references", ROOT) / "01.png",
            project_path("cards_references", ROOT) / "04.png",
            ROOT / "content/character/character-human-cutout.png",
            ROOT / "content/character/character-creature-cutout.png",
        ]
        self.reference_caption = reference_caption if reference_caption is not None else (
            "첨부 1·2는 사용자 소유 카드의 디자인 참고이며 거기에 적힌 주제·숫자·문장은 내용 자료가 아니야 "
            "첨부 3·4는 원본 캐릭터 컷아웃이야 필요할 때 원형을 유지해서 사용하고 다른 캐릭터로 바꾸지 마"
        )
        self.window_id: int | None = None
        self.ledger_path: Path | None = None
        self.ledger: dict[str, Any] = {"requests": {}}

    def bind_job(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True); directory.chmod(0o700)
        self.ledger_path = directory / "safari.json"
        if self.ledger_path.is_file():
            self.ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            self.window_id = self.ledger.get("window_id")

    def _checkpoint(self) -> None:
        if self.ledger_path is None: return
        descriptor, name = tempfile.mkstemp(prefix=".safari-", dir=self.ledger_path.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(self.ledger, handle, ensure_ascii=False)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(name, self.ledger_path)

    def _apple(self, script: str, *args: str) -> str:
        if sys.platform != "darwin":
            raise SafariBlocked("이 웹 이미지 제작은 macOS Safari에서 실행해요")
        try:
            result = subprocess.run(["/usr/bin/osascript", "-e", script, *args],
                capture_output=True, text=True, timeout=35, check=False)
        except subprocess.TimeoutExpired as exc:
            raise SafariBlocked("Safari 응답이 멈췄어요 전용 탭을 확인한 뒤 다시 실행해 주세요") from exc
        if result.returncode:
            error = result.stderr.lower()
            if "javascript" in error and any(word in error for word in ("apple event", "applescript", "disabled", "turned off", "허용")):
                raise SafariBlocked("Safari 설정 필요 · 개발자 기능 → Apple Events의 JavaScript 허용")
            if "-1743" in error or "not authorized" in error or "권한" in error:
                raise SafariBlocked("macOS에서 위젯의 Safari 제어가 허용되지 않았어요")
            raise SafariBlocked("전용 Safari 탭을 제어하지 못했어요 탭을 닫거나 다른 사이트로 바꾸지 마세요")
        return result.stdout.strip()

    def _eval(self, body: str) -> Any:
        if self.window_id is None:
            raise SafariBlocked("전용 Safari 창이 없어요")
        wrapped = "(() => { if (location.origin !== 'https://chatgpt.com') return JSON.stringify({error:'origin'}); " + DOM + body + "})()"
        descriptor, name = tempfile.mkstemp(prefix=".safari-js-", suffix=".js",
            dir=self._temporary_directory())
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(wrapped)
            raw = self._apple(EVALUATE, str(self.window_id), name)
        finally:
            Path(name).unlink(missing_ok=True)
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SafariBlocked("Safari 페이지 응답 형식을 확인하지 못했어요") from exc
        if isinstance(value, dict) and value.get("error"):
            raise SafariBlocked("ChatGPT 화면 구조가 달라 해당 단계에서 멈췄어요: " + str(value["error"]))
        return value

    def open(self, conversation: str | None) -> None:
        target = conversation_url(conversation)
        if self.window_id is None:
            self.window_id = int(self._apple(OPEN_WINDOW, target))
            self.ledger["window_id"] = self.window_id; self._checkpoint()
        elif conversation:
            current = self._eval("return JSON.stringify({url:location.origin + location.pathname});")
            if current.get("url") != target:
                self._apple(NAVIGATE, str(self.window_id), target)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                state = self._eval("return JSON.stringify({composer:!!composer(), ready:document.readyState, busy:busy()});")
            except SafariBlocked as exc:
                if "설정 필요" in str(exc) or "허용되지" in str(exc): raise
                time.sleep(self.poll); continue
            if state.get("composer") and state.get("ready") == "complete":
                self.ledger["conversation_url"] = self._eval("return JSON.stringify({url:location.origin + location.pathname});")["url"]
                self._checkpoint()
                return
            time.sleep(self.poll)
        raise SafariBlocked("Safari ChatGPT 로그인 또는 입력창이 필요해요 로그인 화면을 프로그램이 대신 통과하지 않아요")

    def preflight(self) -> None:
        self.open(None)
        if not self.downloads.is_dir():
            raise SafariBlocked("Safari 다운로드 폴더를 찾지 못했어요")
        # Missing refs are a configuration failure, never replaced with a
        # newly invented character or a real-person reference photo.
        for path in self.references:
            if not path.is_file():
                raise SafariBlocked("카드 디자인 참고 이미지가 없어요 제작 설정을 확인해 주세요")

    def diagnostics(self) -> dict[str, Any]:
        """Read only DOM shape in this job's dedicated chat, never its sidebar."""
        return self._eval(r'''
const scope = document.querySelector('main') || composer()?.closest('form') || document.body;
return JSON.stringify({
  accessible_turns:turns().length,
  request_bound_replies:turns().filter(t=>t.role==='assistant' && t.id.startsWith('request-')).length,
  message_roles:Array.from(scope.querySelectorAll('[data-message-author-role]')).map(e => e.getAttribute('data-message-author-role')),
  articles:Array.from(scope.querySelectorAll('article')).map(e => ({testid:e.getAttribute('data-testid'), role:e.getAttribute('data-message-author-role'), textMarker:(e.textContent || '').includes('[CARD_REQUEST '), visibleMarker:(e.innerText || '').includes('[CARD_REQUEST ')})),
  testids:Array.from(new Set(Array.from(scope.querySelectorAll('[data-testid]')).map(e => e.getAttribute('data-testid')))).slice(0,50),
  headings:Array.from(scope.querySelectorAll('h3,h4')).map(e => {
    let node=e; const ancestry=[];
    for(let i=0; node && i<5; i++,node=node.parentElement) ancestry.push({tag:node.tagName,cls:node.className,testid:node.getAttribute('data-testid'),headings:node.querySelectorAll('h4').length,childTags:Array.from(node.children).map(c=>c.tagName).slice(0,12)});
    return {label:(e.textContent || '').slice(0,50), ancestry};
  }),
  image_count:scope.querySelectorAll('img').length
});
''')

    def _attachments(self) -> None:
        if not self.references:
            return
        names = json.dumps([p.name for p in self.references])
        probe = r'''
const c = composer();
const scope = (c && (c.closest('form') || c.closest('main'))) || document.body;
const labels = Array.from(scope.querySelectorAll('[aria-label],[title],img'))
  .filter(visible).map(e => label(e) + ' ' + (e.getAttribute('alt') || ''));
const names = ''' + names + r''';
// ChatGPT's library adds (1), (2), ... before the extension on repeated
// reference uploads. Those chips still represent this job's uploaded files.
const canonical = s => s.replace(/\(\d+\)(?=\.[A-Za-z0-9]+\b)/g, '');
const present = names.filter(n => labels.some(s => canonical(s).includes(n)) || canonical(scope.innerText).includes(n)).length;
const uploading = Array.from(scope.querySelectorAll('[data-testid="file-upload-progress"], [aria-label="Uploading"], [aria-busy="true"], [role="progressbar"]')).some(visible);
return JSON.stringify({present, uploading});
'''
        initial = self._eval(probe)
        # The file chips expose filenames as accessibility labels, not always
        # visible body text. Reuse an already uploaded complete set on resume;
        # never blindly add four duplicate attachments after an interrupted wait.
        if initial.get("present") not in (0, len(self.references)):
            raise SafariBlocked("참고 이미지 일부만 있어 중복 업로드하지 않고 멈췄어요")
        files = []
        for path in self.references:
            payload = path.read_bytes()
            if len(payload) > 5 * 1024 * 1024:
                raise SafariBlocked("참고 이미지가 너무 커요 원본을 바꾸지 않고 제작을 중단했어요")
            files.append({"name": path.name, "bytes": base64.b64encode(payload).decode("ascii")})
        encoded = json.dumps(files)
        if initial.get("present") == 0:
            self._eval(r'''
const input = document.querySelector('input[type="file"][accept*="image"]') || document.querySelector('input[type="file"]');
if (!input) return JSON.stringify({error:'reference_upload_control_missing'});
const transfer = new DataTransfer();
for (const f of ''' + encoded + r''') {
  const bytes = Uint8Array.from(atob(f.bytes), c => c.charCodeAt(0));
  transfer.items.add(new File([bytes], f.name, {type:'image/png'}));
}
input.files = transfer.files;
input.dispatchEvent(new Event('change', {bubbles:true}));
return JSON.stringify({attached:transfer.files.length});
''')
        deadline = time.monotonic() + 60
        # Wait for upload chips, and for their uploading spinner to disappear.
        stable = 0
        while time.monotonic() < deadline:
            state = self._eval(probe)
            stable = stable + 1 if state.get("present") == len(self.references) and not state.get("uploading") else 0
            if stable >= 2:
                return
            time.sleep(self.poll)
        raise SafariBlocked("참고 이미지 업로드 완료를 확인하지 못했어요 프롬프트는 보내지 않았어요")

    def attach_images(self, paths: list[Path]) -> None:
        """Attach a saved program output for review, not a stale generated reply."""
        original = self.references
        try:
            self.references = paths
            self._attachments()
        finally:
            self.references = original

    def _wait(self, request_id: str, *, image: bool) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        stable = 0
        last_signature = None
        while time.monotonic() < deadline:
            value = self._eval("return JSON.stringify(responseFor(" + json.dumps(request_id) + "));")
            if not value.get("found"):
                if value.get("expanding"):
                    time.sleep(self.poll); continue
                raise SafariBlocked("전송된 요청이 전용 대화에 보이지 않아요 중복 전송하지 않고 멈췄어요")
            signature = json.dumps({k: value.get(k) for k in ("message_id", "text", "images")}, sort_keys=True)
            ready = (bool(value.get("images")) if image else bool(value.get("text"))) and not value.get("busy")
            stable = stable + 1 if ready and signature == last_signature else 0
            if stable >= 2:
                value.pop("found", None)
                value.pop("busy", None)
                value["request_id"] = request_id
                return value
            last_signature = signature
            time.sleep(self.poll)
        raise SafariBlocked("ChatGPT 생성 대기 시간이 끝났어요 같은 요청을 다시 보내지 않고 이어받기 상태로 남겨요")

    def recover(self, request_id: str, *, image: bool) -> dict[str, Any] | None:
        value = self._eval("return JSON.stringify({ready:document.readyState, composer:!!composer(), count:turns().length, ...responseFor(" + json.dumps(request_id) + ")});")
        if value.get("expanding"):
            time.sleep(self.poll)
            value = self._eval("return JSON.stringify({ready:document.readyState, composer:!!composer(), count:turns().length, ...responseFor(" + json.dumps(request_id) + ")});")
        if value.get("ready") != "complete" or not value.get("composer"):
            raise SafariBlocked("대화가 아직 준비되지 않아 요청 존재 여부를 판단할 수 없어요")
        if value.get("found"):
            return self._wait(request_id, image=image)
        if request_id in self.ledger.get("requests", {}):
            raise SafariBlocked("전송 시도 기록은 있지만 대화에서 요청을 찾지 못했어요 중복 전송하지 않고 멈췄어요")
        # A paginated /c/ history could hide a submitted request. Absence there
        # is not evidence of 'unsent'; fail closed rather than duplicate it.
        url = self._eval("return JSON.stringify({path:location.pathname});")
        if url.get("path", "").startswith("/c/"):
            raise SafariBlocked("기존 대화에서 요청을 찾지 못했어요 중복 전송 위험 때문에 멈췄어요")
        if value.get("count") != 0:
            raise SafariBlocked("새 작업 대화가 비어 있지 않아요")
        return None

    def request(self, prompt: str, request_id: str, *, image: bool) -> dict[str, Any]:
        # Calls for newly checkpointed requests can safely use the current
        # known conversation, unlike recovery of an uncertain old send.
        prior = self._eval("return JSON.stringify({count:turns().length, ...responseFor(" + json.dumps(request_id) + ")});")
        if prior.get("found"):
            return self._wait(request_id, image=image)
        if image and prior.get("count") == 0:
            self._attachments()
            prompt = self.reference_caption + "\n" + prompt
        # Put the marker before long source data so a collapsed prompt still
        # identifies its request without expanding an arbitrary old message.
        text = "[CARD_REQUEST " + request_id + "]\n" + prompt
        inserted = self._eval(r'''
const c = composer();
if (!c || busy()) return JSON.stringify({error:'composer_unavailable_or_busy'});
if ((c.value || c.innerText || '').trim()) return JSON.stringify({error:'composer_not_empty'});
c.focus();
if (c.tagName === 'TEXTAREA') {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  setter.call(c, ''' + json.dumps(text) + r''');
} else {
  document.execCommand('insertText', false, ''' + json.dumps(text) + r''');
}
c.dispatchEvent(new Event('input', {bubbles:true}));
return JSON.stringify({matches:(c.value || c.innerText || '').trim() === ''' + json.dumps(text.strip()) + r'''});
''')
        if not inserted.get("matches"):
            raise SafariBlocked("입력된 프롬프트가 원문과 달라 전송하지 않았어요")
        self.ledger.setdefault("requests", {})[request_id] = {"stage":"before_send"}
        self._checkpoint()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            sent = self._eval(r'''
const c = composer();
const b = document.querySelector('button[data-testid="send-button"], button[data-testid="composer-submit-button"]') ||
  Array.from(document.querySelectorAll('button')).find(e => visible(e) && /send prompt|send message|프롬프트 보내기|메시지 보내기|^보내기$/i.test(label(e)));
if (!c || (c.value || c.innerText || '').trim() !== ''' + json.dumps(text.strip()) + r''') return JSON.stringify({error:'prompt_changed_before_send'});
if (!b || b.disabled) return JSON.stringify({sent:false});
b.click(); return JSON.stringify({sent:true});
''')
            if sent.get("sent"):
                break
            time.sleep(self.poll)
        else:
            raise SafariBlocked("ChatGPT 전송 버튼을 확인하지 못했어요 프롬프트를 중복 전송하지 않아요")
        # Observe acceptance before waiting for generation, since a click alone
        # does not prove that React/network accepted this request.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            accepted = self._eval("return JSON.stringify(responseFor(" + json.dumps(request_id) + "));")
            if accepted.get("found"):
                self.ledger["requests"][request_id] = {"stage":"accepted"}
                self.ledger["conversation_url"] = accepted.get("conversation_url") or self._eval("return JSON.stringify({url:location.origin + location.pathname});")["url"]
                self._checkpoint()
                return self._wait(request_id, image=image)
            time.sleep(self.poll)
        raise SafariBlocked("ChatGPT가 요청을 받은 기록을 확인하지 못했어요")

    def _download_snapshot(self) -> dict[Path, tuple[int, int]]:
        snapshot = {}
        for path in self.downloads.iterdir():
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                stat = path.stat()
                snapshot[path] = (stat.st_size, stat.st_mtime_ns)
        return snapshot

    def _temporary_directory(self) -> Path:
        directory = self.ledger_path.parent if self.ledger_path else project_path("scratch", ROOT) / "safari"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _store_download(self, path: Path, destination: Path,
                        baseline: dict[Path, tuple[int, int]]) -> None:
        # Safari still uses its existing download setting; do not change the
        # user's browser globally. Adopt only this request's new, verified file.
        if not destination.resolve().is_relative_to(ROOT.resolve()):
            raise SafariBlocked("생성 이미지는 이 프로젝트 폴더 안에만 저장해요")
        stat = path.stat()
        before = (stat.st_size, stat.st_mtime_ns)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name("." + destination.name + ".download")
        shutil.copyfile(path, temporary)
        temporary.chmod(0o600)
        current = path.stat()
        if (current.st_size, current.st_mtime_ns) != before or temporary.read_bytes() != path.read_bytes():
            temporary.unlink(missing_ok=True)
            raise SafariBlocked("다운로드가 저장 중 바뀌어 원본 정리를 중단했어요")
        os.replace(temporary, destination)
        if path in baseline or path.resolve() == destination.resolve():
            return  # Never move a pre-existing/user-owned download.
        archive = destination.parent / ".downloads"
        archive.mkdir(exist_ok=True)
        stored = archive / path.name
        number = 1
        while stored.exists():
            stored = archive / f"{path.stem}-{number}{path.suffix}"
            number += 1
        shutil.move(str(path), str(stored))
        self.ledger.setdefault("saved_downloads", []).append({
            "file": str(destination), "original_download": str(stored)})
        self._checkpoint()

    def save_image(self, image_id: str, destination: Path) -> None:
        if not image_id or ":image-" not in image_id:
            raise SafariBlocked("저장할 생성 이미지 식별자가 없어요")
        message_id, raw_index = image_id.rsplit(":image-", 1)
        index = int(raw_index)
        baseline = self._download_snapshot()
        opened = self._eval(r'''
const t = turns().find(t => t.role === 'assistant' && t.id === ''' + json.dumps(message_id) + r''');
if (!t) return JSON.stringify({error:'generated_message_not_found'});
const imgs = imageNodes(t); const img = imgs[''' + str(index) + r'''];
if (!img) return JSON.stringify({error:'generated_image_not_found'});
img.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
let scope = img.parentElement;
let b = null;
while (scope && t.turn.contains(scope)) {
  b = Array.from(scope.querySelectorAll('button,a')).find(e => /download|다운로드|이미지 저장|save image/i.test(label(e)));
  if (b) break;
  scope = scope.parentElement;
}
if (b) {b.click(); return JSON.stringify({download_clicked:true});}
const preview = img.closest('button,[role="button"]');
if (!preview) return JSON.stringify({error:'original_image_download_control_missing'});
preview.click(); return JSON.stringify({viewer_opening:true});
''')
        # Current web images place the original download in the expanded viewer.
        # This opens the specific generated image, not a sidebar/library asset.
        deadline = time.monotonic() + 15
        while opened.get("viewer_opening") and time.monotonic() < deadline:
            viewer = self._eval(r'''
const close=Array.from(document.querySelectorAll('button')).find(e=>visible(e) && /^(뷰어 닫기|Close viewer)$/i.test(label(e)));
if(!close) return JSON.stringify({viewer:false});
const b=Array.from(document.querySelectorAll('button,a')).find(e=>visible(e) && /^(다운로드|Download)$/i.test(label(e)));
if(!b) return JSON.stringify({error:'viewer_download_control_missing'});
b.click(); return JSON.stringify({viewer:true,download_clicked:true});
''')
            if viewer.get("download_clicked"): break
            time.sleep(self.poll)
        else:
            if opened.get("viewer_opening"):
                raise SafariBlocked("생성 이미지 뷰어의 원본 다운로드 버튼을 확인하지 못했어요")
        deadline = time.monotonic() + 90
        stable_path = None
        stable_size = None
        stable = 0
        while time.monotonic() < deadline:
            snapshot = self._download_snapshot()
            candidates = [p for p, info in snapshot.items() if baseline.get(p) != info]
            if len(candidates) > 1:
                raise SafariBlocked("다운로드가 여러 개라 생성 이미지 원본을 확정하지 못했어요")
            if len(candidates) == 1:
                path = candidates[0]
                size = snapshot[path][0]
                if size > MAX_IMAGE_BYTES:
                    raise SafariBlocked("생성 이미지 용량 제한을 넘었어요")
                stable = stable + 1 if path == stable_path and size == stable_size and size > 0 else 0
                stable_path, stable_size = path, size
                if stable >= 2:
                    with Image.open(path) as picture:
                        if picture.format not in {"PNG", "JPEG", "WEBP"}:
                            raise SafariBlocked("다운로드가 지원하는 이미지 형식이 아니에요")
                        picture.verify()
                    self._store_download(path, destination, baseline)
                    self._eval(r'''
const close=Array.from(document.querySelectorAll('button')).find(e=>visible(e) && /^(뷰어 닫기|Close viewer)$/i.test(label(e)));
if(close) close.click(); return JSON.stringify({viewer_closed:!!close});
''')
                    return
            time.sleep(self.poll)
        raise SafariBlocked("ChatGPT 원본 이미지 다운로드를 확인하지 못했어요 스크린샷으로 대체하지 않아요")
