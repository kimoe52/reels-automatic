#!/usr/bin/env python3
"""Build every reviewed carousel package without publishing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from render import CarouselReel
from native_focus import Deck as NativeDeck
from native_focus import create_project as create_native_project
from native_focus import encoded_still as native_still
from native_focus import inspect_video as inspect_native_video
from native_focus import proof_sheet as native_proof_sheet
from native_focus import tesseract_cli
from native_focus import verify_visual_content as verify_native_visuals
from native_elements import create_project as create_element_project
from hyperframes_renderer import create_project as create_hyperframes_project
from hyperframes_renderer import render_project as render_hyperframes_project
from auto_plan import plan_package
from source_layers import LayerRepairRequired
from storage import reel_manifests, export_render, project_path


ROOT = Path(__file__).resolve().parents[2]
QUEUE = project_path("queue", ROOT)
CARD_NEWS = ROOT / "content" / "card-news"
REELS = project_path("reels_root", ROOT)


def ready_manifests() -> list[Path]:
    return sorted(set(QUEUE.glob("*/*/reel-production.json")) |
                  set(CARD_NEWS.glob("*/reel-production.json")) |
                  set(reel_manifests(REELS, ROOT)))


def media_digest(reel: CarouselReel) -> str:
    digest = hashlib.sha256(reel.manifest_path.read_bytes())
    for card in reel.cards:
        digest.update(card.path.read_bytes())
    if reel.audio:
        digest.update(reel.audio.read_bytes())
    return digest.hexdigest()[:12]


def inspect_video(path: Path, reel: CarouselReel) -> dict:
    command = ["ffprobe", "-v", "error", "-show_entries",
               "format=duration:stream=codec_type,width,height,r_frame_rate",
               "-of", "json", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    streams = report.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video is None or video.get("width") != 1080 or video.get("height") != 1920:
        raise ValueError(f"Unexpected video dimensions: {path}")
    if abs(float(Fraction(video.get("r_frame_rate", "0/1"))) - reel.fps) > .01:
        raise ValueError(f"Unexpected video frame rate: {path}")
    if bool(audio) != bool(reel.audio):
        raise ValueError(f"Unexpected audio stream: {path}")
    duration = float(report.get("format", {}).get("duration", 0))
    if abs(duration - reel.duration) > .08:
        raise ValueError(f"Unexpected video duration: {path}")
    return {"duration": duration, "width": 1080, "height": 1920,
            "fps": reel.fps, "audio": bool(audio)}


def source_inputs(manifest: Path, deck: NativeDeck) -> list[dict[str, str]]:
    """Bind a review marker to every package-local source pixel and plan file."""
    root = manifest.parent.resolve()
    paths = [manifest.resolve()]
    if deck.data.get("source_kind") == "card_render":
        spec = root / "card-render" / "spec.json"
        if spec.is_file():
            paths.append(spec.resolve())
    for page in deck.pages:
        paths.append(page.path.resolve())
        if page.source_card:
            paths.extend([page.source_card.metadata.resolve(), page.source_card.background.resolve(),
                          *(layer["path"].resolve() for layer in page.source_card.layers)])
    result, seen = [], set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("검수 입력 파일이 패키지 밖에 있거나 없습니다")
        result.append({"file": path.relative_to(root).as_posix(),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return result


def build(manifest: Path) -> dict:
    manifest = manifest.resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("reviewed") is not True:
        return {"manifest": str(manifest), "status": "awaiting_review"}
    if data.get("renderer") == "hyperframes_element_story":
        return build_hyperframes(manifest)
    if data.get("renderer") in {"native_card_story", "native_element_story"}:
        return build_native(manifest)
    if data.get("audio_decision") not in {"file", "silent"}:
        raise ValueError("Choose an audio track or explicitly approve silence")
    if data["audio_decision"] == "file" and not data.get("audio"):
        raise ValueError("Approved audio track is missing")
    if data["audio_decision"] == "silent" and data.get("audio"):
        raise ValueError("Silent audio decision conflicts with an audio file")
    if any(not card.get("tiles") for card in data.get("cards", [])[1:]):
        raise ValueError("Each information card needs a reviewed element motion")
    reel = CarouselReel(manifest)
    reel.verify_settled_cards()
    reel._check_audio_length()
    digest = media_digest(reel)
    directory = manifest.parent / "renders"
    directory.mkdir(parents=True, exist_ok=True)
    video = directory / f"reel-{digest}.mp4"
    proof = directory / f"proof-encoded-{digest}.png"
    motion_proof = directory / f"motion-proof-encoded-{digest}.png"
    if not video.exists():
        reel.render(video)
    if not proof.exists():
        reel.proof_sheet(proof, video=video)
    if not motion_proof.exists():
        reel.motion_sheet(video, motion_proof)
    media = inspect_video(video, reel)
    status = {"manifest": str(manifest), "status": "ready_for_review",
              "video": str(video), "proof": str(proof),
              "motion_proof": str(motion_proof), "digest": digest, **media}
    marker = directory / "latest.json"
    temporary = marker.with_name(f".latest-{os.getpid()}.json")
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, marker)
    return export_render(status)


def build_native(manifest: Path) -> dict:
    """Render a reviewed card deck through the reusable card-story program."""
    deck = NativeDeck(manifest)
    digest = deck.digest()
    directory = manifest.parent / "renders"
    directory.mkdir(parents=True, exist_ok=True)
    command = tesseract_cli()
    element_mode = deck.renderer == "native_element_story"
    if element_mode:
        project = create_element_project(deck, directory / f"native-element-story-{digest}", command)
    else:
        project = create_native_project(deck, directory / f"native-card-story-{digest}", command)
    label = "element-story" if element_mode else "card-story"
    video = directory / f"reel-{label}-{digest}.mp4"
    if not video.is_file():
        subprocess.run([command, "export", "--project", str(project),
                        "--resolution", "1080p", "--fps", "30",
                        "--output", str(video)], check=True)
    technical = inspect_native_video(video, deck)
    visual_check = verify_native_visuals(deck, video)
    proof = directory / f"proof-{label}-{digest}.png"
    if not proof.is_file() or proof.stat().st_mtime_ns < video.stat().st_mtime_ns:
        native_proof_sheet(deck, video, proof)
    portrait = directory / f"portrait-{label}-{digest}.png"
    if not portrait.is_file() or portrait.stat().st_mtime_ns < video.stat().st_mtime_ns:
        native_still(video, min(1.8, deck.duration_ms / 3000)).save(portrait)
    status = {
        "manifest": str(manifest), "status": "ready_for_review",
        "renderer": deck.renderer, "project": str(project),
        "video": str(video), "proof": str(proof), "portrait_preview": str(portrait),
        "digest": digest, "cards": len(deck.pages), "source_inputs": source_inputs(manifest, deck),
        "generation_mode": "png_automatic" if deck.data.get("source_kind") == "flat_images" else "approved_layers",
        **technical, **visual_check,
    }
    marker = directory / "latest.json"
    temporary = marker.with_name(f".latest-{os.getpid()}.json")
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    os.replace(temporary, marker)
    return export_render(status)


def build_hyperframes(manifest: Path) -> dict:
    """Generate and render a reviewed deck using the pinned local HyperFrames CLI."""
    # Planning happens before Deck validates 2–8 elements.  auto_plan only
    # refreshes empty or content-paced automatic plans whose card SHA changed;
    # a hand-reviewed plan is deliberately left untouched.
    try:
        manifest = plan_package(manifest)
        deck = NativeDeck(manifest)
    except (LayerRepairRequired, ValueError) as exc:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(exc, LayerRepairRequired) and data.get("source_kind") != "card_render":
            raise
        repair_cards = [index for index, card in enumerate(data.get("cards", []), 1)
                        if isinstance(card, dict)]
        directory = manifest.parent / "renders"; directory.mkdir(parents=True, exist_ok=True)
        status = {"manifest": str(manifest), "status": "needs_layer_repair",
                  "error": str(exc), "repair_cards": repair_cards}
        temporary = directory / f".latest-{os.getpid()}.json"
        temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, directory / "latest.json")
        return status
    digest = deck.digest()
    directory = manifest.parent / "renders"
    directory.mkdir(parents=True, exist_ok=True)
    from matte_review import review as review_mattes
    matte_review = directory / f"cutout-review-{digest}"
    review_mattes(deck, matte_review)
    project = create_hyperframes_project(deck, directory / f"hyperframes-element-story-{digest}")
    video = directory / f"reel-hyperframes-{digest}.mp4"
    if not video.is_file():
        render_hyperframes_project(project, video)
    technical = inspect_native_video(video, deck)
    visual_check = verify_native_visuals(deck, video)
    proof = directory / f"proof-hyperframes-{digest}.png"
    if not proof.is_file() or proof.stat().st_mtime_ns < video.stat().st_mtime_ns:
        native_proof_sheet(deck, video, proof)
    portrait = directory / f"portrait-hyperframes-{digest}.png"
    if not portrait.is_file() or portrait.stat().st_mtime_ns < video.stat().st_mtime_ns:
        native_still(video, min(1.8, deck.duration_ms / 3000)).save(portrait)
    status = {
        "manifest": str(manifest), "status": "ready_for_review",
        "renderer": deck.renderer, "project": str(project),
        "video": str(video), "proof": str(proof), "portrait_preview": str(portrait),
        "digest": digest, "cards": len(deck.pages), "source_inputs": source_inputs(manifest, deck),
        "generation_mode": "png_automatic" if deck.data.get("source_kind") == "flat_images" else "approved_layers",
        "cutout_review": str(matte_review / "cutout-review.json"),
        **technical, **visual_check,
    }
    marker = directory / "latest.json"
    temporary = marker.with_name(f".latest-{os.getpid()}.json")
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    os.replace(temporary, marker)
    return export_render(status)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render reviewed Threads carousel packages")
    parser.add_argument("--manifest", type=Path, action="append",
                        help="Build one package; omit to scan the queue and card-news folders")
    args = parser.parse_args()
    manifests = args.manifest or ready_manifests()
    results = []
    failures = 0
    for path in manifests:
        try:
            result = build(path)
            results.append(result)
            if result.get("status") == "needs_layer_repair":
                failures += 1
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
            failures += 1
            results.append({"manifest": str(path), "status": "error", "error": str(exc)})
    print(json.dumps({"packages": results, "failures": failures}, ensure_ascii=False), flush=True)
    if failures:
        first = next(item for item in results if item["status"] in {"error", "needs_layer_repair"})
        print(f"오류 패키지 {failures}개 · {Path(first['manifest']).parent.name}: {first['error']}",
              file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
