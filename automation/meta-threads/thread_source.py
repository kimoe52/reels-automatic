"""Author-only thread sources, with relationship evidence and immutable plans."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from media_store import write_json_atomic


def relation_id(value: Any) -> str:
    return str(value.get("id") or "") if isinstance(value, dict) else str(value or "")


def numbered_gap(text: str) -> dict[str, Any] | None:
    title = re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]
    advertised = re.search(r"\b(\d{1,3})\s*개", title)
    numbers = [int(n) for n in re.findall(r"(?m)^\s*(\d{1,3})[.)]\s+", text)]
    if not advertised or not numbers or numbers[0] != 1:
        return None
    expected = int(advertised.group(1))
    if not 2 <= expected <= 100:
        return None
    missing = sorted(set(range(1, expected + 1)) - set(numbers))
    return {"expected": expected, "present": len(set(numbers)), "missing": missing} if missing else None


def merge_author_thread(post: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Only attach the author's replies to the root or already attached self replies.

    A matching root alone is insufficient: an author answering another person's
    comment is a separate discussion branch. Missing parent evidence fails closed.
    Parent order wins over timestamps and numbering; sibling numbered sections
    use the author's section number, then creation time and stable API order.
    """
    root_id = str(post.get("id") or "")
    author = str(post.get("username") or "").lstrip("@").casefold()
    if not root_id or not author:
        raise ValueError("후속 원문의 게시글 ID·작성자를 확인할 수 없어요")
    candidates: dict[str, dict[str, Any]] = {}
    excluded = []
    for row in rows:
        identifier = str(row.get("id") or "")
        if not identifier or identifier == root_id or identifier in candidates:
            continue
        if str(row.get("username") or "").lstrip("@").casefold() != author:
            continue
        declared_root = relation_id(row.get("root_post"))
        if declared_root and declared_root != root_id:
            continue
        if not relation_id(row.get("replied_to")):
            excluded.append({"id": identifier, "reason": "missing_parent"})
            continue
        candidates[identifier] = row
    included = {root_id: post}
    pending = dict(candidates)
    while pending:
        linked = [identifier for identifier, row in pending.items()
                  if relation_id(row.get("replied_to")) in included]
        if not linked:
            break
        for identifier in linked:
            included[identifier] = pending.pop(identifier)
    excluded.extend({"id": identifier, "reason": "outside_author_chain"} for identifier in pending)
    children = defaultdict(list)
    positions = {identifier: i for i, identifier in enumerate(candidates)}
    for identifier, row in included.items():
        if identifier != root_id:
            children[relation_id(row.get("replied_to"))].append(row)

    def order(row):
        number = re.search(r"(?m)^\s*(\d{1,3})[.)]\s+", str(row.get("text") or ""))
        return (int(number.group(1)) if number else 1000,
                str(row.get("timestamp") or ""), positions[str(row["id"])])

    ordered = []
    # Iterative depth-first traversal keeps each self-reply chain together.
    stack = [post]
    while stack:
        row = stack.pop()
        ordered.append({key: row[key] for key in
                        ("id", "text", "timestamp", "permalink", "username", "root_post", "replied_to")
                        if key in row})
        stack.extend(reversed(sorted(children[str(row["id"])], key=order)))
    text = "\n\n".join(str(row.get("text") or "").strip() for row in ordered
                         if str(row.get("text") or "").strip())
    fingerprint = hashlib.sha256(json.dumps(ordered, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"version": 2, "root_id": root_id, "author": author, "posts": ordered,
            "reply_count": len(ordered) - 1, "text": text, "fingerprint": fingerprint,
            "numbered_gap": numbered_gap(text), "excluded": excluded, "verified": True}


def source_folder(plan_path: Path) -> Path:
    folder = plan_path.resolve().parent
    if folder.name.startswith("complete-thread-") and (folder.parent / "source.json").is_file():
        return folder.parent
    return folder


def effective_plan(path: Path) -> Path:
    folder = source_folder(path)
    marker = folder / "source-thread.json"
    if not marker.is_file():
        return path
    thread = json.loads(marker.read_text(encoding="utf-8"))
    if thread.get("version") != 2 or thread.get("verified") is not True:
        return path  # Legacy numbered-only recovery is refreshed before production.
    if thread.get("uses_user_override"):
        return folder / "card-plan.json"
    if any(item.get("reason") == "missing_parent" for item in thread.get("excluded", [])):
        raise ValueError("작성자 댓글의 연결 관계가 빠져 있어 제작 전에 확인이 필요해요")
    if thread.get("numbered_gap"):
        raise ValueError("번호 목록의 후속 원문이 아직 빠져 있어요")
    relative = thread.get("plan_file")
    if not relative:
        if thread.get("reply_count"):
            raise ValueError(thread.get("plan_error") or "후속 원문 카드 배분이 아직 완료되지 않았어요")
        return folder / "card-plan.json"
    target = (folder / relative).resolve()
    if not target.is_relative_to(folder) or not target.is_file():
        raise ValueError("후속 원문 카드 계획의 경로가 올바르지 않아요")
    return target


def _blocks(text: str, minimum: int) -> list[str]:
    blocks = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    while len(blocks) < minimum:
        choices = []
        for i, block in enumerate(blocks):
            parts = [part.strip() for part in block.splitlines() if part.strip()]
            if len(parts) < 2:
                parts = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", block) if part.strip()]
            if len(parts) < 2 and len(block.split()) >= 8:
                words = block.split(); mid = len(words) // 2
                parts = [" ".join(words[:mid]), " ".join(words[mid:])]
            if len(parts) >= 2:
                choices.append((len(block), i, parts))
        if not choices:
            break
        _, i, parts = max(choices)
        mid = len(parts) // 2
        blocks[i:i + 1] = ["\n".join(parts[:mid]), "\n".join(parts[mid:])]
    return blocks


def build_thread_plan(path: Path, data: dict[str, Any], thread: dict[str, Any]) -> Path:
    """Distribute prose or numbered continuations without rewriting the source."""
    source = thread["text"].strip()
    count = 4 if len(source) < 240 else 5 if len(source) < 700 else 6
    # Long lists previously supported up to 12 pages; keep that explicit bound.
    numbered = len(re.findall(r"(?m)^\s*\d+[.)]\s+", source))
    if numbered >= 20:
        count = min(12, max(count, 2 + (numbered + 4) // 5))
    blocks = _blocks(source, count)
    if len(blocks) < count:
        raise ValueError("후속 원문을 빈 장 없이 배분할 분량이 부족해요")
    cover = blocks.pop(0)
    for pages in range(count, 13):
        slots = pages - 1
        if len(blocks) < slots:
            break
        prefix = [0]
        for block in blocks: prefix.append(prefix[-1] + len(block) + 2)
        scores = {(0, 0): 0}; boundaries = {}
        for slot in range(1, slots + 1):
            for end in range(slot, len(blocks) + 1):
                choices = [(max(scores[(start, slot - 1)], prefix[end] - prefix[start] - 2), start)
                           for start in range(slot - 1, end) if (start, slot - 1) in scores]
                if choices:
                    score, start = min(choices)
                    scores[(end, slot)] = score; boundaries[(end, slot)] = start
        if scores.get((len(blocks), slots), 851) <= 850:
            ends = []; end = len(blocks)
            for slot in range(slots, 0, -1):
                start = boundaries[(end, slot)]; ends.append((start, end)); end = start
            groups = [cover] + ["\n\n".join(blocks[start:end]) for start, end in reversed(ends)]
            break
    else:
        raise ValueError("전체 원문이 길어 12장으로도 읽기 어려워요 여러 편으로 나눠야 해요")
    if 'groups' not in locals():
        raise ValueError("전체 원문이 길어 12장으로도 읽기 어려워요 여러 편으로 나눠야 해요")
    if re.sub(r"\s+", "", "".join(groups)) != re.sub(r"\s+", "", source):
        raise ValueError("후속 원문 배분에 누락·중복이 있어요")
    folder = source_folder(path)
    digest = hashlib.sha256((source + json.dumps(data, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]
    directory = folder / f"complete-thread-{digest}"
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    groups[-1] += f"\n\n출처: {data['permalink']}\n작성일: {data['timestamp']}"
    plan = {**data, "source_file": "source.json", "source_complete_thread": True,
            "source_fingerprint": thread.get("fingerprint"), "card_count": len(groups), "content_ready": True,
            "cards": [{"number": i, "role": "표지" if i == 1 else "마무리·출처" if i == len(groups) else f"본문 {i-1}",
                       "source_text": body} for i, body in enumerate(groups, 1)]}
    raw = thread.get("posts", [{}])[0] if thread.get("posts") else {"id": data["source_id"]}
    for name, value in (("source.json", {**raw, "text": source}),
                        ("provenance.json", thread), ("card-plan.json", plan)):
        if not (directory / name).exists():
            write_json_atomic(directory / name, value)
    return directory / "card-plan.json"


def save_thread_source(folder: Path, thread: dict[str, Any]) -> Path:
    """Update only the combined-source marker; original editorial files are untouched."""
    folder = folder.resolve()
    result = dict(thread)
    original = folder / "card-plan.json"
    data = json.loads(original.read_text(encoding="utf-8"))
    # User-supplied full text remains authoritative, not API-derived material.
    if data.get("source_file") == "source-full.txt":
        result["uses_user_override"] = True
    elif result.get("reply_count") and not result.get("numbered_gap"):
        try:
            plan = build_thread_plan(original, data, result)
            result["plan_file"] = str(plan.relative_to(folder))
        except ValueError as exc:
            result["plan_error"] = str(exc)
    write_json_atomic(folder / "source-thread.json", result)
    return folder / result["plan_file"] if result.get("plan_file") else original
