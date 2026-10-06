#!/usr/bin/env python3
"""Make card news and the Reel for new Threads posts without hand edits.

For each long post in the queue that has no finished cards yet:
ask for card copy (ChatGPT web by default) → check it against the post →
draw the cards → attach locally archived source media → render the native 9:16 Reel.
A post whose check fails is retried on the next run, at most twice.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "production"))
from project_paths import project_path  # noqa: E402

QUEUE = project_path("queue", ROOT)
MEDIA_ROOT = ROOT / "automation" / "meta-threads"
sys.path.insert(0, str(MEDIA_ROOT))

from media_store import read_manifest, spec_items  # noqa: E402

import chatgpt_web  # noqa: E402
import write_copy  # noqa: E402
from build_ready import AudioSelectionRequired, build as build_reel  # noqa: E402
from render_cards import render  # noqa: E402
from render_comic_cards import render as render_comic  # noqa: E402

MAX_ATTEMPTS = 2
# The last question sent to ChatGPT web, so its answer can still be collected later.
WAITING = QUEUE / ".chatgpt-waiting.json"
# These states have a reviewed copy/spec package already.  A later Reel repair
# must never send that source back through ChatGPT just because the video route
# was not successful yet.
COPY_COMPLETE_STATES = {"ok", "cards_ready", "needs_audio", "reel_failed", "reel_draft",
                        "needs_layer_repair"}


def _relative_card_path(folder: Path, card_path: Path) -> str:
    """Keep generated-card references package-local and reject path escapes."""
    relative = Path(os.path.relpath(card_path, folder))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("생성 카드 경로가 게시물 폴더 밖입니다")
    return relative.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _card_duration_ms(card: dict[str, Any], number: int) -> int:
    """Give dense generated cards enough reading time without a deck-wide constant."""
    if number == 1:
        return 3200
    content = " ".join(str(value) for value in card.values() if isinstance(value, str))
    return min(6000, max(3500, 2800 + len(re.sub(r"\s+", "", content)) * 24))


def _layout_cards(cards_path: Path) -> dict[str, dict[str, Any]]:
    layout_path = cards_path / "layout.json"
    try:
        cards = json.loads(layout_path.read_text(encoding="utf-8")).get("cards")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise ValueError("생성 카드의 layout.json을 찾을 수 없습니다") from exc
    if not isinstance(cards, list):
        raise ValueError("생성 카드 layout.json 형식이 올바르지 않습니다")
    return {str(item.get("file")): item for item in cards if isinstance(item, dict) and item.get("file")}


def _safe_source_layers(cards_path: Path, image: Path, layout: dict[str, Any]) -> tuple[str, str]:
    value = layout.get("layers_file")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{image.name}의 원본 레이어가 없습니다")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{image.name}의 레이어 경로가 안전하지 않습니다")
    layers = (cards_path / relative).resolve()
    if not layers.is_relative_to(cards_path.resolve()) or not layers.is_file():
        raise ValueError(f"{image.name}의 원본 레이어 파일이 없습니다")
    try:
        data = json.loads(layers.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{image.name}의 원본 레이어를 읽을 수 없습니다") from exc
    if (data.get("version") != 1 or data.get("source_file") != image.name
            or data.get("source_sha256") != _sha256(image)
            or not isinstance(data.get("layers"), list) or not isinstance(data.get("background"), dict)):
        raise ValueError(f"{image.name}의 원본 레이어 결속이 맞지 않습니다")
    return relative.as_posix(), _sha256(layers)


def write_hyperframes_manifest(folder: Path, spec: dict[str, Any], report: dict[str, Any],
                               cards_path: Path) -> Path:
    """Create the auto-plannable element-story package for program-rendered cards.

    The card PNGs and the renderer's measured layout are input evidence.  This
    function only writes a new package manifest; it never alters the source
    post, copy spec, or card pixels.
    """
    path = folder / "reel-production.json"
    existing: dict[str, Any] | None = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # An unreadable human-owned package is safer to preserve than replace.
            return path
        if existing.get("source_kind") != "card_render":
            return path
        old_cards = existing.get("cards")
        auto_owner = (isinstance(old_cards, list)
                      and all(isinstance(item, dict) and not item.get("motion_elements")
                              for item in old_cards))
        # A person may edit the generated package after planning.  Their plan
        # stays active; source changes must be resolved explicitly, not hidden
        # behind an automatic replacement.
        if not auto_owner:
            return path
    rendered = report.get("cards")
    if not isinstance(rendered, list) or not 4 <= len(rendered) <= 6:
        raise ValueError("요소 모션용 카드 4~6장이 필요합니다")
    recorded_layouts = _layout_cards(cards_path)
    layouts: list[dict[str, Any]] = []
    for number, item in enumerate(rendered, 1):
        if not isinstance(item, dict) or not isinstance(item.get("file"), str):
            raise ValueError(f"{number}장 카드 레이아웃이 없습니다")
        image = cards_path / item["file"]
        if not image.is_file():
            raise ValueError(f"{number}장 렌더 카드가 없습니다: {image.name}")
        layout = recorded_layouts.get(image.name, item)
        boxes = layout.get("boxes")
        if not isinstance(boxes, list):
            raise ValueError(f"{number}장 박스 좌표가 없습니다")
        layers_file, layers_sha = _safe_source_layers(cards_path, image, layout)
        layouts.append({"file": _relative_card_path(folder, image),
                        "layout": str(layout.get("layout") or ""),
                        "boxes": boxes,
                        "duration_ms": _card_duration_ms(spec.get("cards", [{}])[number - 1], number),
                        "motion_elements": [], "source_sha256": _sha256(image),
                        "layers_file": _relative_card_path(folder, cards_path / layers_file),
                        "source_layers_sha256": layers_sha})
    source = spec.get("source") if isinstance(spec.get("source"), dict) else {}
    source_id = str(source.get("id") or "")
    spec_path = folder / "card-render" / "spec.json"
    spec_sha = _sha256(spec_path) if spec_path.is_file() else ""
    if existing is not None:
        same = (existing.get("source_spec_sha256") == spec_sha
                and existing.get("source", {}).get("id") == source_id
                and len(existing.get("cards", [])) == len(layouts)
                and [item.get("source_sha256") for item in existing.get("cards", [])]
                    == [item["source_sha256"] for item in layouts])
        if same:
            return path
        history = folder / "reel-production-history"
        history.mkdir(exist_ok=True)
        previous = history / f"manifest-{_sha256(path)[:16]}.json"
        if not previous.exists():
            previous.write_bytes(path.read_bytes())
    title = str(spec.get("series") or spec.get("handle") or folder.name).strip()[:24] or folder.name
    manifest = {
        "version": 4,
        "renderer": "hyperframes_element_story",
        "deck_title": title,
        # Card validation and unknown-term checks complete before this call.
        "reviewed": True,
        "motion_review_required": True,
        "source_kind": "card_render",
        "source_spec_sha256": spec_sha,
        "source": dict(source),
        "timing_policy": "auto_content_paced",
        "fps": 30,
        "transition": .28,
        "palette": {"paper": "", "accent": ""},
        "audio": {"decision": "sfx_only", "reason": "카드 요소 전환 효과음만 사용"},
        "audio_decision": "sfx_only",
        "cards": layouts,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def post_text(folder: Path, post: dict[str, Any]) -> str:
    full = folder / "source-full.txt"
    if full.is_file():
        return full.read_text(encoding="utf-8")
    thread_file = folder / "source-thread.json"
    if thread_file.is_file():
        thread = json.loads(thread_file.read_text(encoding="utf-8"))
        if thread.get("version") == 2 and thread.get("verified") is True:
            if thread.get("numbered_gap") or any(item.get("reason") == "missing_parent" for item in thread.get("excluded", [])):
                raise ValueError("후속 원문이 완전하지 않아 카드 제작을 보류해요")
            return str(thread.get("text") or "")
    return str(post.get("text") or "")


def read_status(folder: Path) -> dict[str, Any]:
    try:
        return json.loads((folder / "card-render" / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_status(folder: Path, state: str, **details: Any) -> None:
    work = folder / "card-render"
    work.mkdir(exist_ok=True)
    status = {"state": state, "attempts": read_status(folder).get("attempts", 0) + 1,
              "updated_at": datetime.now(timezone.utc).isoformat(), **details}
    (work / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def has_existing_motion_elements(folder: Path) -> bool:
    """Do not replace card pixels while any existing package depends on them."""
    manifest = folder / "reel-production.json"
    if not manifest.exists():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    cards = data.get("cards")
    return isinstance(cards, list) and any(isinstance(card, dict) and card.get("motion_elements")
                                            for card in cards)


def render_options(args: argparse.Namespace) -> dict[str, Any]:
    return {key: getattr(args, key) for key in ("series", "theme", "card_style", "reel_style", "no_reel")}


def create_waiting(prompt: str, post_ids: list[str], options: dict[str, Any]) -> None:
    """Record one web handoff atomically so a second run cannot replace it."""
    WAITING.parent.mkdir(parents=True, exist_ok=True)
    payload = {"prompt": prompt, "post_ids": post_ids, "sent_at": datetime.now(timezone.utc).isoformat(),
               "options": options}
    try:
        # The prompt and copied answer cache are private working data.  Opening
        # with an explicit mode avoids relying on a permissive umask.
        descriptor = os.open(WAITING, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise RuntimeError("이전 ChatGPT 답변을 기다리고 있습니다. --collect로 먼저 이어 받아야 합니다") from exc


def update_waiting(waiting: dict[str, Any]) -> None:
    """Atomically replace our handoff record without dropping its prompt metadata."""
    WAITING.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{WAITING.name}.", suffix=".tmp", dir=WAITING.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(waiting, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, WAITING)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def waiting_posts(waiting: dict[str, Any]) -> tuple[list[tuple[Path, dict[str, Any]]], list[str], list[str]]:
    """Return only unresolved, still-available posts from an old web handoff.

    ``pending(..., only=...)`` intentionally supports an explicit --post redo,
    so collect must do the extra completion check itself.
    """
    ids = [str(post_id) for post_id in waiting.get("post_ids", []) if str(post_id)]
    candidates = pending(len(ids), 0, set(ids)) if ids else []
    by_id = {folder.name: (folder, post) for folder, post in candidates}
    unresolved: list[tuple[Path, dict[str, Any]]] = []
    unavailable: list[str] = []
    for post_id in ids:
        item = by_id.get(post_id)
        if item is None:
            unavailable.append(post_id)
        elif read_status(item[0]).get("state") not in COPY_COMPLETE_STATES:
            unresolved.append(item)
    # Complete entries are stale handoff work, but a missing queue entry is an
    # operator-visible problem: retain it rather than silently losing a prompt.
    return unresolved, [folder.name for folder, _ in unresolved], unavailable


def _cache_answers(waiting: dict[str, Any], results: dict[str, list[dict[str, Any]]]) -> None:
    cached = waiting.get("answers")
    if not isinstance(cached, dict):
        cached = {}
    cached.update(results)
    waiting["answers"] = cached


def _cached_answers(waiting: dict[str, Any], post_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    cached = waiting.get("answers")
    if not isinstance(cached, dict):
        return {}
    # Cached values were checked before being written, but old or manually
    # damaged records still exist.  Recheck a copy because check_cards adds
    # harmless defaults and must not mutate the on-disk handoff in place.
    valid: dict[str, list[dict[str, Any]]] = {}
    for post_id in post_ids:
        cards = cached.get(post_id)
        if not isinstance(cards, list):
            cached.pop(post_id, None)
            continue
        try:
            valid[post_id] = write_copy.check_cards(copy.deepcopy(cards))
        except (ValueError, TypeError, AttributeError, IndexError, KeyError):
            cached.pop(post_id, None)
    return valid


def restore_waiting_options(waiting: dict[str, Any], args: argparse.Namespace) -> bool:
    """Restore only valid original render choices; old records have no options."""
    saved = waiting.get("options")
    if saved is None:
        return True
    if not isinstance(saved, dict):
        return False
    series = saved.get("series", args.series)
    theme = saved.get("theme", args.theme)
    card_style = saved.get("card_style", args.card_style)
    reel_style = saved.get("reel_style", args.reel_style)
    no_reel = saved.get("no_reel", args.no_reel)
    if (not isinstance(series, str) or not series.strip()
            or not (theme is None or isinstance(theme, str) and theme in write_copy.THEMES)
            or not isinstance(card_style, str) or card_style not in {"classic", "comic_lavender"}
            or not (reel_style is None or isinstance(reel_style, str) and reel_style in write_copy.REEL_STYLES)
            or not isinstance(no_reel, bool)):
        return False
    args.series, args.theme, args.card_style = series, theme, card_style
    args.reel_style, args.no_reel = reel_style, no_reel
    return True


def _safe_failed_status(folder: Path, error: str) -> None:
    try:
        write_status(folder, "failed", error=error)
    except OSError:
        pass


def finish_safely(folder: Path, post: dict[str, Any], cards: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    """A bad post must not discard the remaining copied answers in this batch."""
    try:
        return finish(folder, post, cards, args.series, not args.no_reel,
                      args.theme, args.reel_style, args.card_style)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        message = str(exc)
        _safe_failed_status(folder, message)
        return {"id": folder.name, "state": "failed", "error": message, "retry_processing": True}


def pending(limit: int, minimum: int, only: set[str] | None = None,
            queue: Path = QUEUE) -> list[tuple[Path, dict[str, Any]]]:
    """Newest long posts without finished cards. Hand-made version folders are ignored."""
    found = []
    for source in queue.glob("*/*/source.json"):
        folder = source.parent
        try:
            post = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(post.get("id")) != folder.name or (only and folder.name not in only):
            continue
        status = read_status(folder)
        # Naming a post with --post redoes it even if it already finished or ran out of retries.
        # Cards that are waiting for audio or a Reel repair already have a
        # reviewed source/copy package. Do not send their source back through
        # ChatGPT and overwrite it on the next daily run.
        if not only and (status.get("state") in COPY_COMPLETE_STATES
                         or status.get("attempts", 0) >= MAX_ATTEMPTS):
            continue
        try:
            text = post_text(folder, post)
        except ValueError:
            # Incomplete source stays visible in the widget, but cannot become
            # part of a batch prompt or block otherwise complete source posts.
            continue
        if len(re.sub(r"\s+", "", text)) < minimum:
            continue
        manifest = read_manifest(folder)
        media_types = [str(item.get("type")) for item in manifest.get("items", [])] if manifest else []
        found.append((str(post.get("timestamp") or ""), folder,
                      {**post, "id": folder.name, "text": text, "_media_types": media_types}))
    found.sort(key=lambda item: item[0], reverse=True)
    return [(folder, post) for _, folder, post in found[:limit]]


def finish(folder: Path, post: dict[str, Any], cards: list[dict[str, Any]], series: str,
           reel: bool, theme: str | None = None, reel_style: str | None = None,
           card_style: str = "classic") -> dict[str, Any]:
    work = folder / "card-render"
    work.mkdir(exist_ok=True)
    # A manifest with elements is tied to the exact existing PNG pixels.
    # Rendering into card-render/cards first would irreversibly invalidate its
    # crops, even if the JSON itself was preserved.  Stop before any card/spec
    # write; callers can explicitly resolve the package rather than losing it.
    if has_existing_motion_elements(folder):
        message = "기존 요소 모션 패키지가 카드 원본을 사용 중이어서 새 카드 렌더를 중단했습니다"
        write_status(folder, "motion_source_conflict", error=message)
        return {"id": folder.name, "state": "motion_source_conflict", "error": message}
    flags = write_copy.unknown_terms(cards, post["text"])
    media = spec_items(folder)
    spec = write_copy.build_spec(post, cards, series, theme=theme, reel_style=reel_style, media=media)
    if card_style == "comic_lavender":
        spec["card_style"] = card_style
    spec_path = work / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if card_style == "comic_lavender":
        cards_path = work / ("cards-comic-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        comic_files = render_comic(spec_path, cards_path)
        try:
            actual = _layout_cards(cards_path)
            files = [path for path in comic_files if path.suffix.lower() == ".png"]
            if len(actual) != len(files) or any(path.name not in actual for path in files):
                raise ValueError("만화 카드 layout.json이 실제 카드와 일치하지 않습니다")
            report = {"cards": [actual[path.name] for path in files]}
            problems = {}
        except ValueError as exc:
            report = {"cards": []}
            problems = {"layout.json": [str(exc)]}
    else:
        cards_path = work / "cards"
        report = render(spec_path, cards_path)
        problems = {card["file"]: card["problems"] for card in report["cards"] if card["problems"]}
    result: dict[str, Any] = {"id": folder.name, "spec": str(spec_path), "cards": str(cards_path),
                              "card_style": card_style,
                              "theme": spec["theme"], "reel_style": spec["reel_style"], "source_media": len(media),
                              "problems": problems, "unknown_terms": flags}
    if problems or flags:
        write_status(folder, "failed", problems=problems, unknown_terms=flags)
        result["state"] = "failed"
        return result
    # Both producers export authoritative backgrounds and transparent layers.
    # Plans are derived from those assets, not guessed from a flattened card.
    result["motion_manifest"] = str(write_hyperframes_manifest(folder, spec, report, cards_path))
    if reel:
        try:
            result["reel"] = build_reel(spec_path)
            if result["reel"].get("status") == "needs_layer_repair":
                result["state"] = "needs_layer_repair"
                write_status(folder, "needs_layer_repair", reel_error=result["reel"].get("error"),
                             repair_cards=result["reel"].get("repair_cards", []))
                return result
        except AudioSelectionRequired as exc:
            result["reel_error"] = str(exc)
            result["state"] = "needs_audio"
            write_status(folder, "needs_audio", theme=spec["theme"], reel_style=spec["reel_style"],
                         source_media=len(media), audio_decision="review_required", reel_error=str(exc))
            return result
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
            result["reel_error"] = str(exc)
            result["state"] = "reel_failed"
            write_status(folder, "reel_failed", theme=spec["theme"], reel_style=spec["reel_style"],
                         source_media=len(media), reel_error=str(exc))
            return result
    result["state"] = ("reel_draft" if reel and result.get("reel", {}).get("status") == "draft_needs_design"
                       else "ok" if reel else "cards_ready")
    write_status(folder, result["state"], theme=spec["theme"], reel_style=spec["reel_style"],
                 source_media=len(media))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="새 Threads 글로 카드뉴스와 릴스 만들기")
    parser.add_argument("--via", choices=("web", "codex", "file"), default="web",
                        help="web: ChatGPT 웹에 자동 붙여넣기, codex: Codex CLI, file: --answer 파일 사용")
    parser.add_argument("--answer", type=Path, help="--via file일 때 읽을 답 JSON")
    parser.add_argument("--post", action="append", help="특정 글 ID만 (여러 번 지정 가능)")
    parser.add_argument("--limit", type=int, default=3, help="한 번에 처리할 글 수")
    parser.add_argument("--min-chars", type=int, default=300, help="카드로 만들 최소 글자 수(공백 제외)")
    parser.add_argument("--wait", type=float, default=10, help="ChatGPT 답을 기다릴 분")
    parser.add_argument("--model", default=write_copy.DEFAULT_MODEL)
    parser.add_argument("--series", default="AI 도구 노트")
    parser.add_argument("--theme", choices=tuple(write_copy.THEMES), help="생략하면 글 ID 순환값")
    parser.add_argument("--card-style", choices=("classic", "comic_lavender"), default="classic",
                        help="comic_lavender: 4:5 만화형 편집 가능 카드 (현재 표지·비교·순서·목록 지원)")
    parser.add_argument("--reel-style", choices=write_copy.REEL_STYLES, help="생략하면 글 ID 순환값")
    parser.add_argument("--no-reel", action="store_true", help="카드와 스펙만 만들고 MP4는 build_ready.py에 맡기기")
    parser.add_argument("--collect", action="store_true",
                        help="새 질문 없이, 지난번에 보낸 질문의 답이 복사되기를 기다리기")
    args = parser.parse_args()
    if args.via == "file" and not args.answer:
        parser.error("--via file에는 --answer가 필요합니다")

    uses_waiting = args.collect or args.via == "web"
    waiting: dict[str, Any] | None = None
    if args.collect:
        try:
            waiting = json.loads(WAITING.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(json.dumps({"posts": 0, "ok": 0, "waiting": WAITING.is_file(), "handoff_state": "blocked",
                              "note": "이어 받을 ChatGPT 작업 기록을 읽을 수 없습니다"}, ensure_ascii=False))
            return 1
        if not isinstance(waiting, dict) or not isinstance(waiting.get("prompt"), str) \
                or not isinstance(waiting.get("post_ids"), list) \
                or not all(isinstance(post_id, str) and post_id for post_id in waiting["post_ids"]) \
                or len(set(waiting["post_ids"])) != len(waiting["post_ids"]):
            print(json.dumps({"posts": 0, "ok": 0, "waiting": WAITING.is_file(), "handoff_state": "blocked",
                              "note": "ChatGPT 작업 기록 형식이 올바르지 않습니다"}, ensure_ascii=False))
            return 1
        if not restore_waiting_options(waiting, args):
            print(json.dumps({"posts": 0, "ok": 0, "waiting": True, "handoff_state": "blocked",
                              "note": "ChatGPT 작업의 렌더 옵션 형식이 올바르지 않습니다"}, ensure_ascii=False))
            return 1
        posts, unresolved_ids, unavailable_ids = waiting_posts(waiting)
        # Drop stale completed jobs immediately.  Missing source jobs remain
        # visible as blocked instead of silently losing their handoff.
        waiting["post_ids"] = unresolved_ids + unavailable_ids
        cached = waiting.get("answers")
        if isinstance(cached, dict):
            waiting["answers"] = {post_id: cards for post_id, cards in cached.items()
                                  if post_id in waiting["post_ids"]}
        if unavailable_ids:
            try:
                update_waiting(waiting)
            except OSError as exc:
                print(f"대기 기록 저장 실패: {exc}", file=sys.stderr)
            print(json.dumps({"posts": 0, "ok": 0, "waiting": True, "handoff_state": "blocked",
                              "note": "원문을 찾을 수 없어 ChatGPT 작업을 이어 받을 수 없습니다"}, ensure_ascii=False))
            return 1
        if not posts:
            try:
                WAITING.unlink(missing_ok=True)
            except OSError as exc:
                print(f"대기 기록 정리 실패: {exc}", file=sys.stderr)
                print(json.dumps({"posts": 0, "ok": 0, "waiting": True, "handoff_state": "blocked",
                                  "note": "ChatGPT 작업 기록을 저장할 수 없습니다"}, ensure_ascii=False))
                return 1
            print(json.dumps({"posts": 0, "ok": 0, "waiting": False, "handoff_state": "complete",
                              "note": "이전 ChatGPT 작업은 이미 처리되었습니다"}, ensure_ascii=False))
            return 0
        prompt = waiting["prompt"]
    else:
        posts = pending(args.limit, args.min_chars, set(args.post) if args.post else None)
        prompt = write_copy.build_prompt([post for _, post in posts]) if posts else ""
    if not posts:
        print(json.dumps({"posts": 0, "ok": 0, "waiting": False, "handoff_state": "complete",
                          "note": "카드로 만들 새 글이 없습니다"}, ensure_ascii=False))
        return 0
    post_ids = [folder.name for folder, _ in posts]
    results = _cached_answers(waiting, post_ids) if waiting is not None else {}
    answer_ids = [post_id for post_id in post_ids if post_id not in results]
    timed_out = False
    if waiting is not None and answer_ids:
        # Persist removal of a malformed old cache before waiting on the
        # clipboard, otherwise every timeout would resurrect it on retry.
        try:
            update_waiting(waiting)
        except OSError as exc:
            print(f"대기 기록 저장 실패: {exc}", file=sys.stderr)
            print(json.dumps({"posts": len(posts), "ok": 0, "waiting": True, "handoff_state": "blocked",
                              "note": "ChatGPT 작업 기록을 저장할 수 없습니다"}, ensure_ascii=False))
            return 1
    try:
        if answer_ids and args.collect:
            answer = chatgpt_web.wait_for_answer(prompt, write_copy.looks_like_answer, wait_minutes=args.wait)
        elif answer_ids and args.via == "file":
            answer = args.answer.read_text(encoding="utf-8")
        elif answer_ids and args.via == "codex":
            answer = write_copy.ask_codex(prompt, args.model)
        elif answer_ids:
            create_waiting(prompt, post_ids, render_options(args))
            waiting = json.loads(WAITING.read_text(encoding="utf-8"))
            answer = chatgpt_web.ask(prompt, write_copy.looks_like_answer, wait_minutes=args.wait)
        else:
            answer = ""
    except TimeoutError as exc:
        # The question stays on record, so a later --collect can still pick up the copied answer.
        chatgpt_web.notify("답을 아직 못 받았어요. 복사 버튼을 누른 뒤 make_cards.py --collect로 이어 받을 수 있어요.")
        print(f"대기 시간 초과: {exc}", file=sys.stderr)
        # A batch may also contain a previously checkpointed copy whose local
        # save failed.  Retry that work now; only the missing IDs need another
        # clipboard answer.
        if not results:
            print(json.dumps({"posts": len(posts), "ok": 0, "waiting": True, "handoff_state": "awaiting_answer",
                              "note": "ChatGPT 답변을 기다리는 중입니다"}, ensure_ascii=False))
            return 1
        answer = ""
        timed_out = True
    except (RuntimeError, OSError) as exc:
        print(json.dumps({"posts": len(posts), "ok": 0, "waiting": WAITING.is_file(), "handoff_state": "blocked",
                          "note": "ChatGPT 작업을 이어 받을 수 없습니다"}, ensure_ascii=False))
        print(str(exc), file=sys.stderr)
        return 1
    if answer_ids:
        parsed, errors = write_copy.parse_answer(answer, answer_ids)
        results.update(parsed)
        if waiting is not None:
            _cache_answers(waiting, parsed)
            # Save a valid partial result before any local render/status write.
            # A local failure can then retry without relying on the clipboard.
            try:
                update_waiting(waiting)
            except OSError as exc:
                print(f"대기 기록 저장 실패: {exc}", file=sys.stderr)
                print(json.dumps({"posts": len(posts), "ok": 0, "waiting": True, "handoff_state": "blocked",
                                  "note": "ChatGPT 작업 기록을 저장할 수 없습니다"}, ensure_ascii=False))
                return 1
    else:
        errors = {}

    outputs = []
    for folder, post in posts:
        if folder.name in results:
            item = finish_safely(folder, post, results[folder.name], args)
            if uses_waiting and item["state"] == "failed" and not item.get("retry_processing"):
                # The copied JSON was structurally valid, but the card checker
                # rejected its claims/layout.  Do not loop forever rendering
                # the same bad copy; retain the handoff and wait for a revised
                # answer instead.
                cached = waiting.get("answers") if waiting is not None else None
                if isinstance(cached, dict):
                    cached.pop(folder.name, None)
                item["state"] = "waiting"
            outputs.append(item)
        else:
            error = errors.get(folder.name, "답에 이 글이 없습니다")
            if not uses_waiting:
                _safe_failed_status(folder, error)
            outputs.append({"id": folder.name, "state": "waiting" if uses_waiting else "failed", "error": error})
    cards_ok = sum(item["state"] in COPY_COMPLETE_STATES for item in outputs)
    successful_states = {"ok", "cards_ready"} if args.no_reel else {"ok", "reel_draft"}
    done = sum(item["state"] in successful_states for item in outputs)
    unresolved = [item["id"] for item in outputs if item["state"] not in COPY_COMPLETE_STATES]
    if waiting is not None:
        waiting["post_ids"] = unresolved
        cached = _cached_answers(waiting, unresolved)
        if cached:
            waiting["answers"] = cached
        else:
            waiting.pop("answers", None)
        try:
            if unresolved:
                update_waiting(waiting)
            else:
                WAITING.unlink(missing_ok=True)
        except OSError as exc:
            print(f"대기 기록 저장 실패: {exc}", file=sys.stderr)
            print(json.dumps({"posts": len(outputs), "ok": done, "waiting": True, "handoff_state": "blocked",
                              "note": "ChatGPT 작업 기록을 저장할 수 없습니다", "results": outputs},
                             ensure_ascii=False))
            return 1
    if uses_waiting:
        finish_note = " · 릴스는 음원 결정 뒤 제작" if args.no_reel and done else ""
        chatgpt_web.notify(f"카드뉴스 {done}개 완성{finish_note}" +
                           (f", {len(outputs) - done}개는 다음에 다시 시도" if done < len(outputs) else ""))
    if unresolved:
        if any(item["state"] == "motion_source_conflict" for item in outputs):
            state, note = "blocked", "기존 모션 카드 원본을 사용 중이라 카드 처리를 이어 받을 수 없습니다"
        elif timed_out:
            state, note = "awaiting_answer", "ChatGPT 답변을 기다리는 중입니다"
        elif any(item["state"] == "waiting" for item in outputs):
            state, note = "partial_answer", "일부 카드 문구가 없거나 형식이 올바르지 않습니다"
        else:
            state, note = "retry_processing", "카드 저장 처리 중 실패하여 다시 시도합니다"
    elif done != len(outputs):
        state, note = "complete", "카드 처리 완료, 릴스 후속 처리가 필요합니다"
    else:
        state, note = "complete", "카드 처리 완료"
    print(json.dumps({"posts": len(outputs), "ok": done, "cards_ok": cards_ok, "waiting": bool(unresolved),
                      "handoff_state": state, "note": note, "results": outputs}, ensure_ascii=False))
    return 0 if done == len(outputs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
