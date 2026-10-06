"""Hand a prompt to ChatGPT in the browser and pick the answer up from the clipboard.

The program opens ChatGPT, pastes the prompt and presses Return, the way a
keyboard shortcut would. It does not inspect or scrape the page. The answer
arrives when the user clicks ChatGPT's copy button, and the copied text is then
read from the clipboard.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Callable

CHATGPT_URL = "https://chatgpt.com/"
BROWSER = os.environ.get("CHATGPT_BROWSER", "Safari")
UTF8 = {**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
# Key codes work under any keyboard input source, including Korean:
# 18 = 1 (Control-1 switches ChatGPT to Chat instead of Work), 9 = V, 36 = Return.
# Before each keystroke the script checks that Safari is in front on a chatgpt.com tab,
# so a prompt is never pasted or sent into another app.
PASTE_AND_SEND = """on frontIsChatGPT()
    tell application "System Events"
        set frontName to name of (first application process whose frontmost is true)
    end tell
    if frontName is not "Safari" then return false
    tell application "Safari" to set pageURL to URL of current tab of front window
    return pageURL starts with "https://chatgpt.com"
end frontIsChatGPT

on run argv
    delay (item 1 of argv as number)
    tell application "Safari" to activate
    delay 0.6
    if not frontIsChatGPT() then error "ChatGPT 탭이 앞에 없습니다" number 1
    tell application "System Events" to key code 18 using control down
    delay 1.5
    tell application "Safari" to activate
    delay 0.4
    if not frontIsChatGPT() then error "ChatGPT 탭이 앞에 없습니다" number 1
    tell application "System Events" to key code 9 using command down
    delay 1
    if not frontIsChatGPT() then error "ChatGPT 탭이 앞에 없습니다" number 1
    tell application "System Events" to key code 36
end run"""
NOTIFY = """on run argv
    display notification (item 1 of argv) with title (item 2 of argv)
end run"""


def copy_text(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True, env=UTF8, check=True)


def clipboard() -> str:
    return subprocess.run(["pbpaste"], capture_output=True, text=True, env=UTF8).stdout


def notify(message: str, title: str = "김오이 카드뉴스") -> None:
    subprocess.run(["osascript", "-e", NOTIFY, message, title], capture_output=True, text=True)


def paste_and_send(load_seconds: float) -> bool:
    """Needs Accessibility permission for the app that started this program."""
    result = subprocess.run(["osascript", "-e", PASTE_AND_SEND, str(load_seconds)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"자동 붙여넣기 중단: {result.stderr.strip()[-160:]}", file=sys.stderr, flush=True)
    return result.returncode == 0


def send(prompt: str, load_seconds: float = 6) -> bool:
    """Open ChatGPT in Safari (Chat mode) and paste the prompt; False means the user has to paste it."""
    copy_text(prompt)
    subprocess.run(["open", "-a", BROWSER, CHATGPT_URL], check=True)
    pasted = paste_and_send(load_seconds)
    if pasted:
        notify("ChatGPT Chat에 질문을 넣었어요. 입력창이 비어 있으면 ⌘V로 붙여넣어 주세요. 답이 끝나면 코드블록의 복사 버튼을 눌러 주세요.")
    else:
        notify("질문이 복사돼 있어요. 사파리 ChatGPT의 Chat에 붙여넣고 보낸 뒤, 답의 복사 버튼을 눌러 주세요.")
    print("ChatGPT 자동 붙여넣기: " + ("보냄" if pasted else "실패, 직접 붙여넣기 필요"), file=sys.stderr, flush=True)
    return pasted


def ask(prompt: str, is_answer: Callable[[str], bool], *, wait_minutes: float = 10,
        load_seconds: float = 6, poll_seconds: float = 1.5,
        read_clipboard: Callable[[], str] = clipboard) -> str:
    send(prompt, load_seconds)
    return wait_for_answer(prompt, is_answer, wait_minutes=wait_minutes, poll_seconds=poll_seconds,
                           read_clipboard=read_clipboard)


def wait_for_answer(prompt: str, is_answer: Callable[[str], bool], *, wait_minutes: float = 10,
                    poll_seconds: float = 1.5, read_clipboard: Callable[[], str] = clipboard) -> str:
    """Wait until the user copies an answer; the prompt itself and other copies are ignored."""
    print(f"복사된 답을 기다리는 중 (최대 {wait_minutes:g}분)", file=sys.stderr, flush=True)
    deadline = time.monotonic() + wait_minutes * 60
    while time.monotonic() < deadline:
        text = read_clipboard()
        if text.strip() and text != prompt and is_answer(text):
            return text
        time.sleep(poll_seconds)
    raise TimeoutError(f"ChatGPT 답을 {wait_minutes:g}분 동안 받지 못했습니다")
