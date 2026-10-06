#!/usr/bin/env python3
"""Turn a Threads snapshot into review-only card-news and reel drafts.

This transformer is intentionally deterministic. It preserves source wording,
marks editorial placeholders, and never publishes or invents facts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "production"))
from project_paths import project_path  # noqa: E402

DEFAULT_SNAPSHOT_DIR = ROOT / "automation" / "meta-threads" / "fetch" / "snapshots"
DEFAULT_OUTPUT_DIR = project_path("queue", ROOT)
DEFAULT_SOURCE_OVERRIDES_DIR = Path(__file__).resolve().parent / "source-overrides"
DEFAULT_STATE_PATH = ROOT / "automation" / "meta-threads" / "state" / "transform_state.json"
META_ROOT = ROOT / "automation" / "meta-threads"
sys.path.insert(0, str(META_ROOT))

from media_store import public_source, read_manifest, sync_post_media, write_json_atomic  # noqa: E402
from thread_source import save_thread_source  # noqa: E402


def one_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def excerpt(value: str, limit: int = 180) -> str:
    text = one_line(value)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def reading_duration_ms(value: str, cover: bool = False) -> int:
    """Reserve a real reading hold after element entrances in a Reel draft."""
    if cover:
        return 3200
    without_links = re.sub(r"https?://\S+", "", value)
    characters = len(re.sub(r"\s+", "", without_links))
    return min(5000, max(3500, 3200 + characters * 8))


def sentences(value: str) -> list[str]:
    text = one_line(value)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    result = [part.strip() for part in parts if part.strip()]
    return result or [text]


def source_blocks(value: str, minimum: int) -> list[str]:
    """Keep the whole source in ordered, non-overlapping editorial blocks."""
    blocks = [part.strip() for part in re.split(r"\n\s*\n", value.strip()) if part.strip()]
    while len(blocks) < minimum and blocks:
        choices = []
        for index, original in enumerate(blocks):
            lines = [line.strip() for line in original.splitlines() if line.strip()]
            if len(lines) < 2:
                lines = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", original)
                         if part.strip()]
            if len(lines) < 2:
                words = original.split()
                if len(words) >= 8:
                    middle = len(words) // 2
                    lines = [" ".join(words[:middle]), " ".join(words[middle:])]
            if len(lines) >= 2:
                choices.append((len(original), index, lines))
        if not choices:
            break
        _, candidate, lines = max(choices)
        middle = len(lines) // 2
        blocks[candidate:candidate + 1] = ["\n".join(lines[:middle]),
                                           "\n".join(lines[middle:])]
    return blocks


def ordered_groups(blocks: list[str], count: int) -> list[str]:
    """Distribute source blocks without dropping or duplicating a section."""
    base, extra = divmod(len(blocks), count)
    groups = []
    cursor = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        groups.append("\n\n".join(blocks[cursor:cursor + size]))
        cursor += size
    return groups


def safe_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9가-힣._-]+", "-", value).strip("-._")
    return (name or fallback)[:80]


def parse_timestamp(value: str) -> tuple[str, str]:
    raw = str(value or "")
    try:
        normalized = raw.replace("Z", "+00:00")
        if re.search(r"[+-]\d{4}$", normalized):
            normalized = f"{normalized[:-5]}{normalized[-5:-2]}:{normalized[-2:]}"
        parsed = datetime.fromisoformat(normalized)
        return parsed.date().isoformat(), parsed.isoformat()
    except ValueError:
        now = datetime.now(timezone.utc)
        return now.date().isoformat(), raw or now.isoformat()


def choose_card_count(text: str, forced: int | None) -> int:
    if forced is not None:
        return forced
    length = len(one_line(text))
    count = 4 if length < 240 else 6 if length >= 700 else 5
    return max(4, min(6, count))


def source_link(post: dict[str, Any]) -> str:
    return str(post.get("permalink") or "출처 링크 없음")


def write_new(path: Path, value: str) -> None:
    """Keep any existing editorial work intact when a snapshot is reprocessed."""
    try:
        with path.open("x", encoding="utf-8") as target:
            target.write(value)
    except FileExistsError:
        pass


def make_cards(post: dict[str, Any], count: int) -> list[tuple[str, str]]:
    text = str(post.get("text") or "").strip()
    blocks = source_blocks(text, count)
    link = source_link(post)
    date = str(post.get("timestamp") or "작성일 미확인")
    if not blocks:
        return [("원문 확인", "원문 텍스트가 없어 문안을 만들 수 없습니다.")
                for _ in range(count)]
    middle = ordered_groups(blocks[1:-1], count - 2)
    cards = [("표지", blocks[0])]
    cards.extend((f"본문 {index + 1}", body or "원문 분량 부족 — 이 장은 제작 전 재구성 필요")
                 for index, body in enumerate(middle))
    final = blocks[-1] if len(blocks) > 1 else "원문 분량 부족 — 결론 확인 필요"
    cards.append(("마무리·출처", f"{final}\n\n출처: {link}\n작성일: {date}"))
    return cards


def post_folder(post: dict[str, Any], output_dir: Path) -> Path:
    date, _ = parse_timestamp(str(post.get("timestamp") or ""))
    return output_dir / date / safe_name(str(post.get("id") or "post"), "post")


def write_post(post: dict[str, Any], output_dir: Path, forced_count: int | None,
               overrides_dir: Path | None = DEFAULT_SOURCE_OVERRIDES_DIR) -> Path:
    post_id = str(post.get("id") or "post")
    _, normalized_timestamp = parse_timestamp(str(post.get("timestamp") or ""))
    folder = post_folder(post, output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    media_manifest = sync_post_media(post, folder)
    media_count = len(read_manifest(folder).get("items", [])) if media_manifest else 0

    raw_text = str(post.get("text") or "")
    override_path = (overrides_dir / f"{safe_name(post_id, 'post')}.txt"
                     if overrides_dir is not None else None)
    override_used = override_path is not None and override_path.is_file()
    text = override_path.read_text(encoding="utf-8") if override_used else raw_text
    editorial_post = {**post, "text": text}
    count = choose_card_count(text, forced_count)
    cards = make_cards(editorial_post, count)
    username = str(post.get("username") or "").strip().lstrip("@")
    author = f"@{username}" if username else "Threads"
    link = source_link(post)

    original_post = {key: value for key, value in post.items() if key != "_author_thread"}
    write_new(folder / "source.json", json.dumps(public_source(original_post), ensure_ascii=False, indent=2) + "\n")
    if override_used:
        write_new(folder / "source-full.txt", text.rstrip() + "\n")

    card_lines = [
        f"# {author} 카드뉴스 초안",
        "",
        f"> 카드 수: {count}장 (자동 선택, 검수 전 초안)",
        "",
    ]
    for index, (label, body) in enumerate(cards, start=1):
        card_lines.extend([f"## {index}장 — {label}", "", body, ""])
    source_note = ("source-full.txt는 사용자가 제공한 전체 글입니다. source.json은 API 수집 원문입니다."
                   if override_used else "source.json은 API 수집 원문입니다.")
    card_lines.extend(["## 편집 메모", "", f"- {source_note}",
                       "- 각 장의 본문은 원문 순서대로 한 번씩만 배분했습니다. 화면용 짧은 문구는 원문과 대조해 확정하세요.",
                       "- 원문에 없는 숫자·전망·매매 판단을 추가하지 마세요.",
                       "- 문구 확정 전 제작에 사용한 전체 글과 공식 출처를 대조하세요.", ""])
    write_new(folder / "card-copy.md", "\n".join(card_lines))

    card_plan = {
        "source_id": post_id,
        "author": author,
        "permalink": link,
        "timestamp": normalized_timestamp,
        "source_file": "source-full.txt" if override_used else "source.json",
        "card_count": count,
        "content_ready": bool(text.strip()) and all("원문 분량 부족" not in body for _, body in cards),
        "source_media": {"manifest": "source-media/manifest.json", "items": media_count} if media_manifest else None,
        "cards": [{"number": index, "role": label, "source_text": body}
                  for index, (label, body) in enumerate(cards, start=1)],
    }
    write_new(folder / "card-plan.json",
              json.dumps(card_plan, ensure_ascii=False, indent=2) + "\n")
    if isinstance(post.get("_author_thread"), dict):
        save_thread_source(folder, post["_author_thread"])

    visual_brief = [
        f"# {author} 카드 이미지 생성 요청 — {post_id}", "",
        "아래 카드마다 별도의 4:5 이미지 한 장을 만드세요. Jev 승인 카드의 정보 밀도와 선명한 위계를 품질 기준으로 삼되, 주제에 맞는 사진·도식·색을 선택하세요.",
        "표지는 큰 제목을 허용하고, 본문 장은 비교·흐름·근거·정리 중 내용에 맞는 서로 다른 레이아웃을 사용하세요. 모든 장을 표지처럼 만들지 마세요.",
        "실사 본인 사진은 사용하지 마세요. 캐릭터는 꼭 필요한 장면에 원본 컷아웃 하나만 사용하세요.",
        "정확한 한글·수치·출처는 아래 원문과 대조해야 합니다. 원문에 없는 UI, 성과, 수치, 결론은 그리지 마세요.",
        "생성 후 각 이미지의 한글·수치·4:5 비율을 확인하고, 승인된 카드만 릴스 제작에 사용하세요.", "",
    ]
    if media_count:
        visual_brief.extend([f"원글 미디어 {media_count}개는 source-media/에 URL 없이 보존했습니다. 실제 화면 증거로 우선 사용하고 내용을 추측하지 마세요.", ""])
    for index, (label, body) in enumerate(cards, start=1):
        visual_brief.extend([f"## {index}장 — {label}", "", "이미지에 담을 원문:", "", body, ""])
    write_new(folder / "image-prompts.md", "\n".join(visual_brief))

    draft_manifest = folder / "reel-production.draft.json"
    page_durations = [reading_duration_ms(body, index == 1)
                      for index, (_, body) in enumerate(cards, start=1)]
    if not draft_manifest.exists():
        draft_manifest.write_text(json.dumps({
            "version": 4, "renderer": "hyperframes_element_story",
            "title": f"{author} · {post_id}", "deck_title": author[:24],
            "reviewed": False,
            "source": link, "timing_policy": "reading_paced",
            "card_durations": [duration / 1000 for duration in page_durations],
            "fps": 30, "transition": .28,
            "palette": {"paper": "", "accent": ""},
            "audio": None, "audio_decision": "sfx_only",
            "hyperframes_panel_repair": False,
            "cards": [{"file": f"assets/cards/{index:02d}.png",
                       "duration_ms": page_durations[index - 1],
                       "motion_elements": []}
                      for index in range(1, count + 1)],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source_flow = "\n".join(f"### {index}장 · {label}\n\n{body}\n"
                            for index, (label, body) in enumerate(cards, start=1))
    reel = f"""# 릴스 대본 초안 ({author})

상태: 검수 전 / 아래 발췌는 사실 확인용, 최종 화면 문구 아님 / 자동 게시 안 함
화면: 9:16 · 표지 3.2초 + 본문은 글 양에 따라 장당 3.5~5초 = {sum(page_durations) / 1000:g}초. 원글 미디어가 있으면 사실 확인 자료로 우선 보고, 카드 내용과 관련 없는 장면은 넣지 않음
자료: {source_note} / 로컬 원글 미디어: {media_count}개

## 원문 전체의 화면 배분

{source_flow}

위 문안은 원문을 순서대로 배분한 제작 재료입니다. 각 장의 화면 문구는 짧게 편집하되, 원문의 중요한 주장·근거·조건을 빠뜨리지 않았는지 대조하세요.

## 제작 메모

- 첨부 레퍼런스는 먼저 **게시글 본문과 프롬프트의 제작 지시**를 읽고, 이미지 한 장면과 구분하세요. 공식 자료 조사·짧고 명료한 전개·의미 있는 움직임·리듬 전환을 주제에 맞게 적용합니다. 레퍼런스의 그래프·수치·색·구도를 복사하지 않습니다.
- 위에 배분된 긴 문장을 그대로 자막으로 쓰지 않습니다. 한 컷에 한 가지 뜻만 남겨 짧은 구어체로 고치되, `원문 문장 → 최종 화면 문구` 대조표를 남기고 원문에 없는 사실을 넣지 않습니다. 같은 제목·본문·페이지 번호가 반복되는 정적 슬라이드로 릴스를 채우지 않습니다.
- 밝고 읽기 쉬운 화면을 기본으로 하되 색과 질감은 원문 주제에 맞춰 정합니다. 긴 글은 읽을 수 있는 속도에 맞춰 구성하고, 한 문장만 되풀이하지 않습니다.
- 보라색 글로우·반복 그리드·유리 패널·떠다니는 카드를 자동으로 덧붙여 일반적인 'AI 영상'처럼 만들지 않습니다. 배경을 깨끗하게 두고 주제를 설명하는 시각 요소만 씁니다.
- 실재하는 앱 화면은 공식 서비스에서 직접 얻습니다. 원문에 없는 사용 장면을 생성 화면이나 목업으로 채우지 않습니다. 꼭 필요한 설명용 그림을 생성할 때는 실제 서비스/라이브 응답과 구분하고, 생성 이미지의 한글·숫자를 사실 자막으로 쓰지 않습니다.
- 공식 사이트 캡처를 쓸 때는 URL·캡처 시점·화면의 실제 내용을 기록합니다. 공식 데모가 본문의 예시와 다른 사례라면 영상 안에서도 구분합니다. 화면을 보여주는 동안에는 읽어야 할 지점을 확대하거나 움직임으로 짚고, 긴 웹페이지를 정지한 채 방치하지 않습니다.
- 화면에 쓰는 주장·사례·숫자는 원문 문장에 대응시켜 검수합니다. 문장을 짧게 잘라도 원문에 없는 실패 횟수·계산 조건·결과값을 보태지 않습니다.
- 얼굴 사진은 인물이 실제로 말하거나 반응할 때만 사용합니다. 말하지 않는 정지 사진·손 사진·기본 PIP는 넣지 않습니다. 얼굴 변형은 금지합니다.
- 음성·ASMR·효과음·배경음악은 이 게시물에 필요한지 먼저 판단합니다. 타자음·클릭음·AI 음성을 자동으로 추가하지 않습니다.
- 원문에 없는 확률·성과·전망은 만들지 않습니다. Jev 확률·선택 결과는 성공한 실제 API 응답에서만 가져오고, 공식 문서 예시나 목업은 화면에 분명히 표시합니다.
- 검수 전 자동 게시하지 않습니다. 인코딩 후 프레임의 글자·도형 경계와 안전 영역을 확인합니다.
"""
    write_new(folder / "reel-script.md", reel)

    caption_body = text.strip() or "본문을 확인하세요."
    if len(caption_body) > 1800:
        caption_body = caption_body[:1799].rstrip() + "…"
    caption = f"{author} 원문 기반 초안\n\n{caption_body}\n\n출처: {link}\n작성일: {normalized_timestamp}\n\n※ 게시 전 원문·날짜·수치·면책 문구를 확인하세요."
    write_new(folder / "caption.txt", caption + "\n")

    review = f"""# 검수표

- [ ] 카드가 {count}장인지 확인 (허용 범위: 4~6장)
- [ ] card-plan.json의 모든 원문 단락이 카드에 빠짐없이 한 번씩 반영됐는지 확인
- [ ] 카드·릴스 문구가 제작에 사용한 원문과 일치하거나 편집 메모로 표시되어 있는지 확인 ({source_note})
- [ ] 승인 카드 PNG마다 한글·수치·비율·설명 밀도와 레이아웃 차이를 확인
- [ ] 요소별 모션과 음악을 주제에 맞게 정해 reel-production.json을 확정
- [ ] 숫자·전망·매매 판단이 원문에 실제로 있는지 확인
- [ ] 작성일과 출처 링크 확인: {link}
- [ ] 실제 화면과 예시 화면을 구분하는 자막 확인
- [ ] 참고 게시물이 있으면 본문/프롬프트를 확인했고, 첨부 이미지의 룩·수치·구도를 무심코 복제하지 않았는지 검수
- [ ] 가짜 앱 화면·장식용 인물/PIP·자동 삽입 타자음이 없는지 검수
- [ ] 인코딩 후 모든 주요 화면의 글자/도형이 9:16 안전 영역 안에 있는지 확인
- [ ] 투자·금융 내용이면 필요한 면책 문구 확인
- [ ] 검수 전 자동 게시하지 않기
"""
    write_new(folder / "review.md", review)
    return folder


def scrub_snapshot(path: Path) -> None:
    """Remove expiring CDN URLs only after every post in the snapshot was safely transformed."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    write_json_atomic(path, public_source(payload))


def load_snapshot(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    posts = payload.get("posts", []) if isinstance(payload, dict) else []
    if not isinstance(posts, list):
        raise ValueError("snapshot의 posts 형식이 올바르지 않습니다.")
    return [post for post in posts if isinstance(post, dict)]


def read_processed(state_path: Path) -> set[str] | None:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    names = payload.get("processed_snapshots") if isinstance(payload, dict) else None
    return {str(name) for name in names} if isinstance(names, list) else None


def write_processed(state_path: Path, processed: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(f".{state_path.name}.partial-{os.getpid()}")
    temporary.write_text(json.dumps({
        "processed_snapshots": sorted(processed),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, state_path)


def transformed_before(path: Path, output_dir: Path) -> bool:
    """Used once, before a state file exists: any existing draft folder means it was handled.

    Older runs filed drafts under the run date, so every date folder is searched by post ID.
    Checking for any draft rather than all of them keeps drafts the user deleted from coming back.
    """
    try:
        posts = load_snapshot(path)
    except (OSError, ValueError):
        return False
    return any(next(output_dir.glob(f"*/{safe_name(str(post.get('id') or 'post'), 'post')}/source.json"), None)
               for post in posts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Threads snapshot을 카드뉴스·릴스 검수 초안으로 변환")
    parser.add_argument("--snapshot", type=Path,
                        help="이 snapshot 하나만 변환하고 처리 기록은 바꾸지 않음. 생략하면 아직 변환하지 않은 snapshot을 모두 변환")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH,
                        help="변환을 마친 snapshot 목록 파일")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source-overrides-dir", type=Path, default=DEFAULT_SOURCE_OVERRIDES_DIR,
                        help="게시물 ID.txt로 저장한 사용자 제공 전체 글의 선택적 폴더")
    parser.add_argument("--cards", type=int, choices=(4, 5, 6), help="카드 수를 강제하지 않으면 원문 길이로 4~6장 선택")
    args = parser.parse_args()

    def convert(path: Path) -> list[Path]:
        folders = [write_post(post, args.output_dir, args.cards, args.source_overrides_dir)
                   for post in load_snapshot(path)]
        scrub_snapshot(path)
        return folders

    if args.snapshot is not None:
        if not args.snapshot.exists():
            raise SystemExit(f"snapshot이 없습니다: {args.snapshot}")
        try:
            folders = convert(args.snapshot)
        except (OSError, ValueError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({"snapshot": str(args.snapshot), "posts": len(folders),
                          "outputs": [str(path) for path in folders]}, ensure_ascii=False))
        return 0

    snapshots = sorted(args.snapshot_dir.glob("threads-*.json"))
    if not snapshots:
        raise SystemExit("Threads snapshot이 없습니다. 먼저 fetch_posts.py를 실행하세요.")
    processed = read_processed(args.state)
    if processed is None:
        processed = {path.name for path in snapshots if transformed_before(path, args.output_dir)}
        write_processed(args.state, processed)

    # A snapshot stays pending until all of its posts are written, so a failed run is retried.
    converted: list[str] = []
    folders: list[Path] = []
    failures: list[str] = []
    for path in snapshots:
        if path.name in processed:
            continue
        try:
            folders.extend(convert(path))
        except (OSError, ValueError, RuntimeError) as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        processed.add(path.name)
        converted.append(path.name)
        write_processed(args.state, processed)
    print(json.dumps({"snapshots": converted, "posts": len(folders),
                      "outputs": [str(path) for path in folders], "failures": failures},
                     ensure_ascii=False), flush=True)
    if failures:
        print(f"처리하지 못한 snapshot {len(failures)}개 · {failures[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
