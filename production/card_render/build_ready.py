#!/usr/bin/env python3
"""Render every finished card spec as the new native 9:16 Reel, without publishing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

import render_reel
import render_motion_auto
from project_paths import project_path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
QUEUE = project_path("queue", ROOT)
CARD_NEWS = ROOT / "content" / "card-news"
CARD_MOTION_BUILD = ROOT / "production" / "card_motion" / "build_ready.py"
RENDER_INPUTS = [HERE / name for name in ("render_reel.py", "reel.css", "render_cards.py", "icons.py")]
RENDER_INPUTS += [HERE / "assets" / "character-human.png",
                  ROOT / "content" / "character" / "character-creature-cutout.png"]
AUDIO_SUFFIXES = {".aac", ".m4a", ".mp3", ".wav"}
NATIVE_STYLE = "motion"
LEGACY_STYLE = "motion_resolution"


class AudioSelectionRequired(ValueError):
    """The post needs an explicit review decision before its Reel is encoded."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def ready_specs() -> list[Path]:
    candidates = set(QUEUE.glob("*/*/card-render/spec.json")) | set(CARD_NEWS.glob("*/card-render/spec.json"))
    # `cards_ready` and `needs_audio` are actionable, successful card packages.
    # Include them so the standard scan reports awaiting_audio instead of an
    # empty, misleading "nothing to do" result. `main` treats that state as a
    # normal wait and only actual render defects produce a non-zero exit.
    return sorted(path for path in candidates
                  if read_json(path.with_name("status.json")).get("state") in
                  {"ok", "cards_ready", "needs_audio", "reel_draft"})


def _digest_file(digest: Any, path: Path) -> None:
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    _digest_file(digest, path)
    return digest.hexdigest()


def resolve_audio(spec: Path, data: dict[str, Any]) -> tuple[Path | None, str]:
    """Read an explicit audio decision from a spec without picking music ourselves.

    `approved` files are project-relative, so a generated spec cannot point at
    arbitrary local files. `sfx_only` is limited to native motion projects and
    rejects music beds. `silent` requires a written reason.
    """
    audio = data.get("audio")
    if not isinstance(audio, dict):
        raise AudioSelectionRequired("릴스에 사용할 승인 음원 또는 무음 사유를 지정해야 합니다")
    decision = audio.get("decision")
    if data.get("reel_style") == NATIVE_STYLE and decision != "sfx_only":
        raise ValueError("자동 모션은 효과음 전용입니다; 음악·무음을 조용히 무시하지 않습니다")
    if decision == "review_required":
        raise AudioSelectionRequired("릴스에 사용할 승인 음원을 지정해야 합니다")
    if decision == "silent":
        if not isinstance(audio.get("reason"), str) or not audio["reason"].strip():
            raise ValueError("무음 릴스는 audio.reason이 필요합니다")
        return None, decision
    if decision == "sfx_only":
        if data.get("reel_style") not in {NATIVE_STYLE, LEGACY_STYLE}:
            raise ValueError("sfx_only는 편집 가능한 모션 프로젝트에만 사용합니다")
        if audio.get("file") or not str(audio.get("reason") or "").strip():
            raise ValueError("sfx_only는 음악 파일 없이 사유를 적어야 합니다")
        return None, decision
    if decision != "approved":
        raise ValueError("audio.decision은 approved, sfx_only, silent, review_required 중 하나여야 합니다")
    value = audio.get("file")
    if not isinstance(value, str) or not value:
        raise ValueError("승인 음원에는 audio.file이 필요합니다")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("승인 음원은 프로젝트 안의 상대 경로여야 합니다")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file() or path.suffix.lower() not in AUDIO_SUFFIXES:
        raise ValueError(f"승인 음원 파일을 찾을 수 없습니다: {value}")
    return path, decision


def native_project(spec: Path, data: dict[str, Any]) -> Path:
    """Keep authored projects inside this post's renders tree, never an arbitrary path."""
    if data.get("source", {}).get("id") != "18001430661007646":
        raise ValueError("이 모션 버전은 검수한 480p·업스케일 원문 전용입니다")
    value = data.get("motion_project")
    if not isinstance(value, str) or not value:
        raise ValueError("모션 버전에는 motion_project가 필요합니다")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("motion_project는 프로젝트 안의 상대 경로여야 합니다")
    path = (ROOT / relative).resolve()
    allowed = (spec.parent.parent / "renders").resolve()
    if not path.is_relative_to(allowed) or path.suffix != ".tsrct" or not path.is_file():
        raise ValueError("이 원글의 renders 안에 있는 .tsrct만 사용할 수 있습니다")
    return path


def tesseract_command() -> str:
    installed = Path.home() / "Library/Application Support/Tesseract/bin/tsrct"
    command = str(installed) if installed.is_file() else shutil.which("tsrct")
    if not command:
        raise ValueError("모션 프로젝트를 내보낼 Tesseract CLI를 찾을 수 없습니다")
    return command


def check_sfx_only_project(project: Path, command: str) -> None:
    """Reject music beds before labeling an authored project SFX-only."""
    result = subprocess.run([command, "project", "inspect", "--project", str(project)],
                            capture_output=True, text=True, check=True)
    layers = json.loads(result.stdout)["composition"]["layers"]
    audio_layers = [layer for layer in layers if layer.get("type") == "Audio"]
    if not audio_layers:
        raise ValueError("효과음 전용 모션 프로젝트에 오디오 큐가 없습니다")
    if any(layer["activeRange"]["duration"] > 1200 for layer in audio_layers):
        raise ValueError("효과음 전용 프로젝트에 1.2초를 넘는 오디오 레이어가 있습니다")
    if sum(layer["activeRange"]["duration"] for layer in audio_layers) > 4000:
        raise ValueError("효과음 총 길이가 4초를 넘어 배경음일 수 있습니다")
    if any(layer.get("type") == "Video" and layer.get("volume", 0) for layer in layers):
        raise ValueError("효과음 전용 프로젝트의 영상에 원본 오디오가 켜져 있습니다")


def render_native(project: Path, video: Path, command: str, duration: float,
                  source_media: int = 0) -> dict[str, Any]:
    subprocess.run([command, "export", "--project", str(project), "--output", str(video)], check=True)
    technical = render_reel.inspect_video(video, duration, True)
    proof = video.with_name(f"{video.stem}-proof.png")
    moments = [min(duration - .2, duration * fraction) for fraction in
               (0, .04, .12, .2, .28, .38, .48, .58, .68, .78, .88, .96)]
    render_reel.contact_sheet([render_reel.video_still(video, moment) for moment in moments], proof)
    portrait = native_portrait_preview(video, min(1.8, duration / 3))
    report = {**technical, "duration": duration, "problems": [], "audio": "sfx_only",
              "source_media": source_media,
              "project": str(project), "proof": str(proof), "portrait_preview": str(portrait),
              "video": str(video)}
    video.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def native_portrait_preview(video: Path, moment: float = 2.8) -> Path:
    """A single actual 9:16 video frame for users; the contact sheet is QA only."""
    portrait = video.with_name(f"{video.stem}-portrait.png")
    if not portrait.is_file() or portrait.stat().st_mtime_ns < video.stat().st_mtime_ns:
        render_reel.video_still(video, moment).save(portrait)
    with Image.open(portrait) as image:
        if image.size != (1080, 1920):
            raise ValueError(f"세로 미리보기 크기가 9:16이 아닙니다: {image.size}")
    return portrait


def render_digest(spec: Path, data: dict[str, Any], audio: Path | None = None) -> str:
    digest = hashlib.sha256(spec.read_bytes())
    if data.get("reel_style") == LEGACY_STYLE:
        _digest_file(digest, native_project(spec, data))
        _digest_file(digest, spec.parent.parent / "source.json")
        return digest.hexdigest()[:12]
    if data.get("reel_style") == NATIVE_STYLE:
        for path in (HERE / "render_motion_auto.py", render_motion_auto.FONT_BODY,
                     render_motion_auto.FONT_DISPLAY,
                     *(render_motion_auto.SFX / item[0] for item in render_motion_auto.SFX_FILES.values())):
            _digest_file(digest, path)
        source = spec.parent.parent / "source.json"
        if source.is_file():
            _digest_file(digest, source)
        for item in render_reel.resolve_media(spec, data):
            _digest_file(digest, item["path"])
            if item.get("poster_path"):
                _digest_file(digest, item["poster_path"])
        return digest.hexdigest()[:12]
    for path in RENDER_INPUTS:
        _digest_file(digest, path)
    seen: set[Path] = set()
    for item in render_reel.resolve_media(spec, data):
        for path in (item["path"], *([item["poster_path"]] if item.get("poster_path") else [])):
            path = path.resolve()
            if path not in seen:
                _digest_file(digest, path)
                seen.add(path)
    if audio:
        _digest_file(digest, audio)
    return digest.hexdigest()[:12]


def proof_is_current(video: Path, report: dict[str, Any]) -> bool:
    """Accept a cache only when its encoded video and its proof belong together."""
    value = report.get("proof")
    expected = video.with_name(f"{video.stem}-proof.png").resolve()
    try:
        proof = Path(str(value)).resolve()
        if proof != expected or not proof.is_file() or proof.stat().st_mtime_ns < video.stat().st_mtime_ns:
            return False
        with Image.open(proof) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def write_latest(directory: Path, value: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "latest.json"
    temporary = marker.with_name(f".latest-{os.getpid()}.json")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, marker)


def mark_needs_audio(directory: Path, spec: Path, error: str) -> None:
    """Record an actionable wait without presenting an old MP4 as current."""
    previous = read_json(directory / "latest.json")
    value: dict[str, Any] = {"spec": str(spec), "status": "awaiting_audio",
                             "audio_decision": "review_required", "error": error}
    if previous.get("status") == "ready_for_review":
        value["previous_review"] = {key: previous[key] for key in ("digest", "video", "proof", "duration")
                                    if key in previous}
    write_latest(directory, value)


def hyperframes_manifest_for(spec: Path) -> Path | None:
    """Return an input-bound generated package that owns this deck's renders."""
    manifest = spec.parent.parent / "reel-production.json"
    data = read_json(manifest)
    if (data.get("renderer") != "hyperframes_element_story" or data.get("reviewed") is not True
            or data.get("source_kind") != "card_render"
            or data.get("source_spec_sha256") != _sha256(spec)
            or not isinstance(data.get("cards"), list) or not data["cards"]):
        return None
    spec_source = read_json(spec).get("source")
    if not isinstance(spec_source, dict) or data.get("source", {}).get("id") != spec_source.get("id"):
        return None
    for card in data["cards"]:
        if (not isinstance(card, dict) or not isinstance(card.get("file"), str)
                or not isinstance(card.get("source_sha256"), str)):
            return None
        path = (manifest.parent / card["file"]).resolve()
        if (not path.is_relative_to(manifest.parent.resolve()) or not path.is_file()
                or _sha256(path) != card["source_sha256"]):
            return None
    return manifest


def build_hyperframes_package(manifest: Path) -> dict[str, Any]:
    """Delegate to the sole HyperFrames owner so `renders/latest.json` is not raced."""
    result = subprocess.run([sys.executable, str(CARD_MOTION_BUILD), "--manifest", str(manifest)],
                            capture_output=True, text=True, check=False)
    # Renderer/library progress may share stdout with the CLI's final report.
    # Read the last packages document rather than assuming stdout is pure JSON.
    package: dict[str, Any] | None = None
    for line in reversed(result.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        packages = payload.get("packages") if isinstance(payload, dict) else None
        if isinstance(packages, list) and len(packages) == 1 and isinstance(packages[0], dict):
            package = packages[0]
            break
    if package is None:
        raise RuntimeError("HyperFrames 제작 결과를 읽을 수 없습니다")
    reported_manifest = Path(str(package.get("manifest") or ""))
    if reported_manifest.resolve() != manifest.resolve():
        raise RuntimeError("HyperFrames 제작 결과의 매니페스트가 요청과 다릅니다")
    if package.get("status") == "needs_layer_repair":
        return package
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1500:]
        raise RuntimeError(f"HyperFrames 제작 실패: {detail or f'종료 코드 {result.returncode}'}")
    if package.get("status") != "ready_for_review":
        raise RuntimeError(str(package.get("error") or "HyperFrames 제작이 검수 준비 상태가 아닙니다"))
    for label in ("video", "proof"):
        artifact = Path(str(package.get(label) or ""))
        if not artifact.is_file():
            raise RuntimeError(f"HyperFrames {label} 산출물이 없습니다")
    return package


def build(spec: Path) -> dict[str, Any]:
    spec = spec.resolve()
    # Generated cards have an image package alongside their spec.  Let the
    # card-motion CLI generate the element plan and write its own latest.json;
    # this renderer must not create a competing HTML/native latest marker.
    hyperframes_manifest = hyperframes_manifest_for(spec)
    if hyperframes_manifest is not None:
        return build_hyperframes_package(hyperframes_manifest)
    directory = spec.parent.parent / "renders"
    digest = None
    try:
        data = read_json(spec)
        if not data:
            raise ValueError(f"스펙 JSON을 읽을 수 없습니다: {spec}")
        style = data.get("reel_style")
        if style not in (*render_reel.STYLES, NATIVE_STYLE, LEGACY_STYLE):
            raise ValueError(f"reel_style이 없습니다: {spec}")
        audio, audio_decision = resolve_audio(spec, data)
        digest = render_digest(spec, data, audio)
        directory.mkdir(parents=True, exist_ok=True)
        command = tesseract_command() if style in {NATIVE_STYLE, LEGACY_STYLE} else None
        project = (render_motion_auto.create_project(spec, directory / f"motion-auto-{digest}", command)
                   if style == NATIVE_STYLE else
                   native_project(spec, data) if style == LEGACY_STYLE else None)
        if project:
            check_sfx_only_project(project, command)
        video = directory / f"reel-{'native' if project else 'html'}-{digest}.mp4"
        report_path = video.with_suffix(".json")
        report = read_json(report_path)
        if video.is_file() and report.get("problems") == [] and proof_is_current(video, report):
            report.update(render_reel.inspect_video(video, float(report["duration"]), bool(report.get("audio"))))
        else:
            native_duration = (render_motion_auto.duration_seconds(len(data["cards"]))
                               if style == NATIVE_STYLE else 23.5)
            media_count = len(data.get("media") or []) if style == NATIVE_STYLE else 0
            report = (render_native(project, video, command, native_duration, media_count) if project
                      else render_reel.render(spec, video, style, audio=audio))
        if report.get("problems"):
            raise ValueError(" / ".join(report["problems"]))
        result = {"spec": str(spec),
                  "status": "draft_needs_design" if style == NATIVE_STYLE else "ready_for_review",
                  "digest": digest,
                  "theme": data.get("theme"), "style": style, "video": str(video),
                  "proof": report["proof"], "duration": report["encoded_duration"],
                  "width": report["width"], "height": report["height"], "fps": report["encoded_fps"],
                  "audio": report["has_audio"], "audio_decision": audio_decision,
                  "source_media": report.get("source_media", 0)}
        if project:
            result["motion_project"] = str(project)
            result["portrait_preview"] = str(native_portrait_preview(video))
        write_latest(directory, result)
        return result
    except AudioSelectionRequired as exc:
        mark_needs_audio(directory, spec, str(exc))
        raise
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        # Do not leave `latest.json` pointing at an older proof after the current
        # spec failed. The older files remain available, but can no longer look
        # like the current review candidate.
        write_latest(directory, {"spec": str(spec), "status": "error", "digest": digest, "error": str(exc)})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="완성된 카드 스펙을 네이티브 9:16 릴스로 렌더")
    parser.add_argument("--spec", type=Path, action="append", help="특정 spec.json만; 생략하면 queue 전체")
    args = parser.parse_args()
    specs = args.spec or ready_specs()
    results, failures, waiting = [], 0, 0
    for path in specs:
        try:
            package = build(path)
            results.append(package)
            if package.get("status") == "needs_layer_repair":
                failures += 1
        except AudioSelectionRequired as exc:
            waiting += 1
            results.append({"spec": str(path), "status": "awaiting_audio", "audio_decision": "review_required",
                            "error": str(exc)})
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            failures += 1
            results.append({"spec": str(path), "status": "error", "error": str(exc)})
    print(json.dumps({"packages": results, "failures": failures, "needs_audio": waiting}, ensure_ascii=False), flush=True)
    if failures:
        first = next(item for item in results if item["status"] in {"error", "needs_layer_repair"})
        print(f"오류 패키지 {failures}개 · {Path(first.get('spec') or first.get('manifest')).parent.name}: {first['error']}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
