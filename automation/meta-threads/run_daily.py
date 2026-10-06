#!/usr/bin/env python3
"""Fetch Threads posts, prepare a ChatGPT-web handoff, and render reviewed media."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import unicodedata
from datetime import datetime
from uuid import uuid4
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "production" / "card_motion"))
from storage import reel_manifests, reel_package, project_path

FETCH = ROOT / "automation" / "meta-threads" / "fetch" / "fetch_posts.py"
TRANSFORM = ROOT / "automation" / "meta-threads" / "transform" / "transform_posts.py"
BUILD_READY = ROOT / "production" / "card_render" / "build_ready.py"
LEGACY_BUILD_READY = ROOT / "production" / "card_motion" / "build_ready.py"
OPEN_CHATGPT = ROOT / "production" / "card_motion" / "open_chatgpt.py"
MAKE_CARDS = ROOT / "production" / "card_render" / "make_cards.py"
AUTO_PLAN = ROOT / "production" / "card_motion" / "auto_plan.py"
WEB_IMAGES = ROOT / "production" / "card_motion" / "web_image_workflow.py"
QUEUE = project_path("queue", ROOT)
WAITING = QUEUE / ".chatgpt-waiting.json"
CARD_NEWS = ROOT / "content" / "card-news"
REELS = project_path("reels_root", ROOT)
_ACTIVE_STAGE: subprocess.Popen[str] | None = None


def stop_active_stage(signum: int, _frame: object) -> None:
    """Stop the current stage and all of its descendants when the widget cancels."""
    process = _ACTIVE_STAGE
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    raise SystemExit(128 + signum)


def compatible_python() -> Path | None:
    """Use the installed project runtime when the terminal resolves old system Python."""
    if sys.version_info >= (3, 12):
        return None
    for candidate in (Path("/opt/homebrew/bin/python3"), Path("/usr/local/bin/python3")):
        if not candidate.is_file():
            continue
        probe = subprocess.run(
            [str(candidate), "-c", "import sys; sys.exit(sys.version_info < (3, 12))"],
            capture_output=True, check=False)
        if probe.returncode == 0:
            return candidate
    raise RuntimeError("이 제작기는 Python 3.12 이상이 필요합니다")


def run_stage(label: str, command: list[str]) -> tuple[int, str]:
    """Run one step, pass its output through, and summarize a failure in one line."""
    global _ACTIVE_STAGE
    process = subprocess.Popen(command, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               errors="replace", start_new_session=True)
    _ACTIVE_STAGE = process
    try:
        _, stderr = process.communicate()
    finally:
        _ACTIVE_STAGE = None
    if stderr:
        sys.stderr.write(stderr)
        sys.stderr.flush()
    if process.returncode == 0:
        return 0, ""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    detail = lines[-1] if lines else f"종료 코드 {process.returncode}"
    detail = re.sub(r"^[A-Za-z_][\w.]*(?:Error|Exception):\s*", "", detail)
    return process.returncode or 1, f"{label} 실패: {detail}"


def legacy_manifests() -> list[Path]:
    """Keep standalone approved image packages available to card_motion.

    A package next to card-render/spec.json is rendered by card_render's scan,
    which delegates HyperFrames packages to this same CLI.  Excluding it here
    prevents two writers racing over one renders/latest.json.
    """
    candidates = set(QUEUE.glob("*/*/reel-production.json")) | set(
        CARD_NEWS.glob("*/reel-production.json")) | set(
        reel_manifests(REELS, ROOT))
    ready = []
    for path in sorted(candidates):
        # The card-render scan owns generated-card packages (and delegates the
        # HyperFrames variant); a direct --manifest below remains selectable.
        if (path.parent / "card-render" / "spec.json").is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("reviewed") is True:
            ready.append(path)
    return ready


def main() -> int:
    parser = argparse.ArgumentParser(description="Threads 수집 후 카드뉴스·릴스 초안 생성")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--cards", type=int, choices=(4, 5, 6))
    parser.add_argument("--only-render", action="store_true",
                        help="Render reviewed packages without contacting Threads")
    parser.add_argument("--manifest", type=Path, action="append",
                        help="Render selected approved image packages; requires --only-render")
    parser.add_argument("--from-images", type=Path, nargs="+",
                        help="Offline PNG/JPEG cards → extracted layers → motion → MP4")
    parser.add_argument("--output", type=Path, help="New import package directory (never overwrite)")
    parser.add_argument("--title", default="카드 영상", help="Imported deck title")
    parser.add_argument("--open-chatgpt", action="store_true",
                        help="Open ChatGPT web with the newest post's first card prompt copied")
    parser.add_argument("--only-chatgpt", action="store_true",
                        help="Open ChatGPT web for the latest existing card plan")
    parser.add_argument("--only-cards", action="store_true",
                        help="Use local card drafts to collect or create ChatGPT web cards without rendering")
    parser.add_argument("--web-images", action="store_true",
                        help="Safari ChatGPT image cards → review → one correction → motion reel")
    parser.add_argument("--web-images-check", action="store_true",
                        help="Check Safari connection only, without submitting a prompt")
    parser.add_argument("--plan", type=Path, help="Exact card-plan.json for --web-images")
    parser.add_argument("--no-reel", action="store_true",
                        help="Save reviewed web-generated cards without rendering a reel")
    parser.add_argument("--resume-chatgpt", action="store_true",
                        help="Collect the answer to a pending ChatGPT request, then render")
    parser.add_argument("--chatgpt-card", type=int, default=1,
                        help="Card number to prepare in ChatGPT web, default 1")
    parser.add_argument("--skip-render", action="store_true",
                        help="Skip MP4 rendering")
    parser.add_argument("--skip-cards", action="store_true",
                        help="Do not ask ChatGPT web for card copy or draw cards")
    parser.add_argument("--backfill-history", action="store_true",
                        help="Fetch the complete Threads history before transforming new posts")
    args = parser.parse_args()
    if args.no_reel and not args.web_images:
        parser.error("--no-reel requires --web-images")
    if args.plan and not (args.web_images or args.web_images_check):
        parser.error("--plan requires --web-images or --web-images-check")
    if args.web_images or args.web_images_check:
        if (args.web_images and args.web_images_check) or any((args.only_cards, args.only_render,
            args.from_images, args.manifest, args.only_chatgpt, args.open_chatgpt,
            args.resume_chatgpt, args.skip_cards, args.skip_render, args.backfill_history, args.output)):
            parser.error("--web-images is an independent Safari image workflow")
        command = [sys.executable, str(WEB_IMAGES)]
        if args.plan: command.extend(["--plan", str(args.plan)])
        if args.web_images_check: command.append("--check-only")
        if args.no_reel: command.append("--no-reel")
        code, message = run_stage("Safari 이미지 제작", command)
        if code: print(message, file=sys.stderr, flush=True)
        return code
    if not 1 <= args.chatgpt_card <= 6:
        parser.error("--chatgpt-card must be between 1 and 6")
    if args.only_render and (args.only_chatgpt or args.open_chatgpt or args.resume_chatgpt):
        parser.error("--only-render cannot open ChatGPT")
    if args.backfill_history and (args.only_render or args.from_images or args.only_chatgpt
                                  or args.open_chatgpt or args.resume_chatgpt or args.only_cards):
        parser.error("--backfill-history requires the Threads fetch workflow")
    if args.only_render and args.skip_render:
        parser.error("--only-render and --skip-render cannot be combined")
    if args.manifest and not args.only_render:
        parser.error("--manifest requires --only-render")
    if args.from_images and (args.only_render or args.manifest or args.only_chatgpt
                            or args.open_chatgpt or args.resume_chatgpt or args.skip_render):
        parser.error("--from-images is an independent offline render workflow")
    if args.output and not args.from_images:
        parser.error("--output requires --from-images")
    if args.output:
        output_path = Path(unicodedata.normalize("NFC", str(args.output.resolve())))
        project_boundary = Path(unicodedata.normalize("NFC", str(ROOT.resolve())))
        if not output_path.is_relative_to(project_boundary):
            parser.error("제작 결과는 이 프로젝트 폴더 안에만 저장할 수 있습니다")
    if args.resume_chatgpt and (args.only_chatgpt or args.skip_cards):
        parser.error("--resume-chatgpt cannot be combined with --only-chatgpt or --skip-cards")
    if args.only_cards and (args.only_render or args.manifest or args.from_images
                            or args.only_chatgpt or args.open_chatgpt
                            or args.resume_chatgpt or args.skip_render or args.skip_cards):
        parser.error("--only-cards is an independent ChatGPT card workflow")
    if args.resume_chatgpt and not WAITING.is_file():
        parser.error("이어받을 ChatGPT 질문이 없습니다")
    results: list[tuple[int, str]] = []
    imported_manifest = None
    resume = args.resume_chatgpt or (WAITING.is_file() and not args.from_images and not
                                     (args.only_render or args.only_chatgpt or args.skip_cards))
    if args.from_images:
        output = args.output or reel_package(f"cards-import-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}", ROOT)
        results.append(run_stage("카드 자동 분리", [sys.executable,str(AUTO_PLAN),"--import-images",
                        *(str(path) for path in args.from_images),"--output",str(output),"--title",args.title]))
        imported_manifest = output / "reel-production.json"
    elif args.only_cards:
        if WAITING.is_file():
            results.append(run_stage("ChatGPT 답변 이어받기", [sys.executable, str(MAKE_CARDS),
                                                            "--collect", "--no-reel"]))
        else:
            results.append(run_stage("카드", [sys.executable, str(MAKE_CARDS), "--no-reel"]))
    elif resume:
        results.append(run_stage("ChatGPT 답변 이어받기", [sys.executable, str(MAKE_CARDS),
                                                        "--collect", "--no-reel"]))
    elif not (args.only_render or args.only_chatgpt):
        fetch_command = [sys.executable, str(FETCH), "--limit", str(args.limit)]
        if args.backfill_history:
            fetch_command.append("--backfill-history")
        results.append(run_stage("수집", fetch_command))
        if not results[-1][0]:
            command = [sys.executable, str(TRANSFORM)]
            if args.cards is not None:
                command.extend(["--cards", str(args.cards)])
            results.append(run_stage("변환", command))
        if not results[-1][0] and not args.skip_cards:
            # ChatGPT web writes the copy; the Reel itself is rendered by the render step below.
            results.append(run_stage("카드", [sys.executable, str(MAKE_CARDS), "--no-reel"]))
    if (args.open_chatgpt or args.only_chatgpt) and not any(code for code, _ in results):
        results.append(run_stage("ChatGPT 열기", [sys.executable, str(OPEN_CHATGPT),
                                                 "--card", str(args.chatgpt_card)]))
    if not args.skip_render and not args.only_chatgpt and not args.only_cards and not any(code for code, _ in results):
        # An explicitly selected package goes directly to card_motion.  This
        # avoids scanning unrelated specs and guarantees --only-render never
        # opens Threads, ChatGPT, or a network API before planning/rendering.
        if not args.manifest and not imported_manifest:
            results.append(run_stage("렌더", [sys.executable, str(BUILD_READY)]))
        approved = [imported_manifest] if imported_manifest else args.manifest or legacy_manifests()
        if approved:
            command = [sys.executable, str(LEGACY_BUILD_READY)]
            for path in approved:
                command.extend(["--manifest", str(path)])
            results.append(run_stage("승인 이미지 릴스 렌더", command))
    failed = [(code, message) for code, message in results if code]
    if failed:
        # The widget shows the last output line, so name the failed step there.
        print(" / ".join(message for _, message in failed), file=sys.stderr, flush=True)
        return failed[0][0]
    return 0


def guarded_main() -> int:
    """Keep widget and terminal runs from racing over snapshots or ChatGPT state."""
    QUEUE.mkdir(parents=True, exist_ok=True)
    with (QUEUE / ".run-daily.lock").open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("이미 카드뉴스·릴스 작업이 실행 중입니다", file=sys.stderr)
            return 1
        return main()


if __name__ == "__main__":
    try:
        interpreter = compatible_python()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if interpreter is not None:
        os.execv(str(interpreter), [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]])
    signal.signal(signal.SIGTERM, stop_active_stage)
    raise SystemExit(guarded_main())
