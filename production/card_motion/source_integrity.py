"""Read-only author continuation recovery; discussion branches are not source."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation/meta-threads"))
from thread_source import merge_author_thread, numbered_gap  # noqa: E402


def require_complete(text: str) -> None:
    gap = numbered_gap(text)
    if gap:
        raise ValueError(f"원문 누락 · 제목은 {gap['expected']}개인데 본문은 {gap['present']}개예요 후속 글 확인 전에는 제작하지 않아요")


def fetch_author_continuation(source: Path) -> dict[str, Any]:
    post = json.loads(source.read_text(encoding="utf-8"))
    identifier = str(post.get("id") or "")
    if not identifier.isdigit() or not post.get("username"):
        raise ValueError("후속 원문을 확인할 게시글 ID·작성자가 없어요")
    file = ROOT / "automation/meta-threads/fetch/fetch_posts.py"
    spec = importlib.util.spec_from_file_location("content_thread_fetch", file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    token, base, _ = module.load_settings()
    if not token:
        raise ValueError("Threads 후속 글을 조회할 기존 연결이 없어요")
    rows = module.fetch_reply_rows(token, base, root_id=identifier)
    return merge_author_thread(post, rows)
