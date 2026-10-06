#!/usr/bin/env python3
"""Editable 9:16 card-story Reel from reviewed flattened artwork.

Original card pixels remain intact. Motion lives in independently editable
image, takeaway, mascot, and progress layers rather than destructive slices.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageStat

from element_layers import Element, parse_elements, prepare_layers
from source_layers import LayerRepairRequired, SourceCard, contained_file, load_source_card


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FONT = ROOT / "production" / "card_render" / "fonts" / "PretendardVariable.ttf"
DISPLAY_FONT = ROOT / "production" / "card_render" / "fonts" / "BlackHanSans-Regular.ttf"
CHARACTER = ROOT / "content" / "character" / "character-creature-cutout.png"
SFX = ROOT / "production" / "card_render" / "assets" / "sfx"
SOUNDS = {
    "impact": ("soft-impact.wav", 400),
    "whoosh": ("air-whoosh.wav", 450),
    "ping": ("clear-ping.wav", 480),
}
CANVAS_W, CANVAS_H = 1080, 1920
TOP_H, BOTTOM_Y = 154, 1580
COVER_DURATION_MS, INNER_DURATION_MS = 2000, 1500
BACKGROUND = "#E5CEF7"
INK = "#16101E"
LIME = "#D7FC83"
MUTED = "#B996D7"


@dataclass(frozen=True)
class Page:
    path: Path
    size: tuple[int, int]
    duration_ms: int
    hook: str
    takeaway: str
    elements: tuple[Element, ...] = ()
    source_card: SourceCard | None = None


def _digest_file(hasher: Any, path: Path) -> None:
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)


def tesseract_cli() -> str:
    installed = Path.home() / "Library/Application Support/Tesseract/bin/tsrct"
    command = str(installed) if installed.is_file() else shutil.which("tsrct")
    if command is None:
        raise RuntimeError("Tesseract CLI가 없어 원본 보존 모션 프로젝트를 만들 수 없습니다")
    return command


def run(command: str, *args: str) -> dict[str, Any]:
    process = subprocess.run([command, *args], capture_output=True, text=True)
    if process.returncode:
        detail = (process.stderr or process.stdout).strip()[-1000:]
        raise RuntimeError(f"Tesseract {' '.join(args[:2])} 실패: {detail}")
    return json.loads(process.stdout) if process.stdout.strip() else {}


def rgb(value: str) -> list[float]:
    return [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)] + [1.0]


def transform(x: float, y: float, scale: float = 100) -> dict[str, Any]:
    return {"anchorPoint": [0, 0], "position": [x, y],
            "scale": [scale, scale], "rotation": 0, "opacity": 100}


def rect(ident: int, name: str, x: float, y: float, width: float, height: float,
         fill: str, start: int, duration: int, radius: float = 0) -> dict[str, Any]:
    return {
        "type": "createFxRectLayer", "compositionId": "main", "layerId": ident,
        "name": name, "insertIndex": 0,
        "activeRange": {"start": start, "duration": duration},
        "transform": transform(x, y),
        "rect": {"size": [width, height], "fillColor": rgb(fill), "roundness": radius},
    }


def keys(ident: int, field: str, values: list[tuple[int, float]]) -> dict[str, Any]:
    return {
        "type": "setFxPropertyKeyframes", "compositionId": "main",
        "property": {"layerId": ident, "propertyType": field},
        "keyframes": [
            {"id": f"focus-{ident}-{field}-{time}", "layerTime": time,
             "value": {"type": "float", "value": value},
             "easing": ({"type": "linear"} if index == 0 else
                        {"type": "cubicBezier", "x1": 0.22, "y1": 0.0,
                         "x2": 0.20, "y2": 1.0})}
            for index, (time, value) in enumerate(values)
        ],
    }


class Deck:
    def __init__(self, manifest: Path):
        self.manifest = manifest.resolve()
        self.data = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.renderer = self.data.get("renderer")
        if ((self.data.get("version"), self.renderer) not in
                {(3, "native_card_story"), (4, "native_element_story"),
                 (4, "hyperframes_element_story")}):
            raise ValueError("원본 카드 모션에는 version 3/native_card_story 또는 version 4 요소 렌더러가 필요합니다")
        if self.data.get("audio_decision") != "sfx_only":
            raise ValueError("이 원본 카드 모션은 배경음 없이 효과음만 허용합니다")
        self.title = str(self.data.get("deck_title") or "").strip()
        if not self.title or len(self.title) > 24:
            raise ValueError("deck_title은 1~24자로 지정해야 합니다")
        cards = self.data.get("cards")
        if not isinstance(cards, list) or not 4 <= len(cards) <= 12:
            raise ValueError("원본 카드 모션에는 4~12장 이미지가 필요합니다")
        self.pages = tuple(self._page(item, number) for number, item in enumerate(cards, 1))
        self.duration_ms = sum(page.duration_ms for page in self.pages)

    def _page(self, item: Any, number: int) -> Page:
        if not isinstance(item, dict):
            raise ValueError(f"{number}장 설정이 올바르지 않습니다")
        relative = Path(str(item.get("file") or ""))
        if (not relative.name or relative.is_absolute() or ".." in relative.parts
                or relative.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}):
            raise ValueError(f"{number}장 이미지 경로는 설정 파일 아래 상대 경로여야 합니다")
        path = (self.manifest.parent / relative).resolve()
        if not path.is_relative_to(self.manifest.parent) or not path.is_file():
            raise ValueError(f"{number}장 이미지를 찾을 수 없습니다: {relative}")
        approved_hash = item.get("source_sha256")
        if approved_hash and hashlib.sha256(path.read_bytes()).hexdigest() != approved_hash:
            raise ValueError(f"{number}장 이미지가 승인된 원본과 다릅니다")
        with Image.open(path) as image:
            width, height = image.size
            if abs(width / height - 0.8) > 0.015:
                raise ValueError(f"{number}장 원본은 4:5여야 합니다: {image.size}")
        duration = int(item.get("duration_ms", 0))
        if self.renderer == "hyperframes_element_story":
            # Reviewed image-heavy cards need time for the animation *and* reading.
            # Keep legacy renderers' fixed timing unchanged for compatibility.
            if duration < 1500:
                raise ValueError(f"{number}장 길이는 1500ms 이상이어야 합니다")
        else:
            expected_duration = COVER_DURATION_MS if number == 1 else INNER_DURATION_MS
            if duration != expected_duration:
                raise ValueError(f"{number}장 길이는 {expected_duration}ms여야 합니다")
        hook = str(item.get("hook") or "").strip()
        takeaway = str(item.get("takeaway") or "").strip()
        if self.renderer == "native_card_story":
            if not hook or len(hook) > 20 or "\n" in hook:
                raise ValueError(f"{number}장 화면 제목은 한 줄 20자 이내여야 합니다")
            if ImageFont.truetype(str(DISPLAY_FONT), 55).getlength(hook) > 790:
                raise ValueError(f"{number}장 화면 제목이 상단 공간을 넘습니다")
            lines = takeaway.split("\n")
            if (not takeaway or len(takeaway) > 56 or len(lines) > 2
                    or any(len(line) > 30 for line in lines)):
                raise ValueError(f"{number}장 요약은 1~2줄, 전체 56자 이내여야 합니다")
            body_font = ImageFont.truetype(str(FONT), 43)
            if any(body_font.getlength(line) > 740 for line in lines):
                raise ValueError(f"{number}장 요약이 하단 공간을 넘습니다")
        source_card = None
        layers_file = item.get("layers_file")
        if (self.data.get("motion_plan", {}).get("generator") == "auto_plan"
                and not layers_file):
            raise LayerRepairRequired(f"{number}장 자동 모션에 원본 레이어가 없습니다")
        if layers_file is not None:
            layer_path = contained_file(self.manifest.parent, layers_file)
            if not isinstance(item.get("source_layers_sha256"), str):
                raise LayerRepairRequired(f"{number}장 승인한 원본 레이어 해시가 없습니다")
            source_card = load_source_card(layer_path, path, item.get("source_layers_sha256"))
        static_preserved = (self.data.get("motion_plan", {}).get("generator") == "auto_plan"
                            and item.get("analysis_status") == "static_preserved"
                            and item.get("motion_elements") == [])
        elements = (parse_elements(item.get("motion_elements"), (width, height), number,
                                   allow_source=source_card is not None)
                    if self.renderer in {"native_element_story", "hyperframes_element_story"}
                    and not static_preserved else ())
        if source_card:
            expected = {layer["name"] for layer in source_card.layers if layer["moving"]}
            actual = {element.name for element in elements}
            if actual != expected or any(element.mask != "source" for element in elements):
                raise ValueError(f"{number}장 원본 레이어 모션 계획이 모든 이동 요소와 일치하지 않습니다")
            by_name = {layer["name"]: layer for layer in source_card.layers}
            if any(tuple(by_name[element.name]["box"]) != element.box
                   or by_name[element.name]["role"] != element.role or not element.repair for element in elements):
                raise LayerRepairRequired(f"{number}장 계획이 원본 레이어 좌표·역할과 다릅니다")
        return Page(path, (width, height), duration, hook, takeaway, elements, source_card)

    def digest(self) -> str:
        hasher = hashlib.sha256(self.manifest.read_bytes())
        for path in (Path(__file__), FONT, DISPLAY_FONT, CHARACTER,
                     *(SFX / value[0] for value in SOUNDS.values()),
                     *(page.path for page in self.pages)):
            _digest_file(hasher, path)
        for page in self.pages:
            if page.source_card:
                _digest_file(hasher, page.source_card.metadata)
                _digest_file(hasher, page.source_card.background)
                for layer in page.source_card.layers:
                    _digest_file(hasher, layer["path"])
        if any(page.source_card for page in self.pages):
            _digest_file(hasher, Path(__file__).with_name("source_layers.py"))
        if self.renderer == "native_element_story":
            _digest_file(hasher, Path(__file__).with_name("element_layers.py"))
            _digest_file(hasher, Path(__file__).with_name("native_elements.py"))
        if self.renderer == "hyperframes_element_story":
            for file in ("element_layers.py", "hyperframes_renderer.py",
                         "motion_effects.py", "motion_effects.js",
                         "hyperframes_template.html", "hyperframes_runtime/package-lock.json"):
                _digest_file(hasher, Path(__file__).parent / file)
            if self.data.get("motion_plan", {}).get("generator") == "auto_plan":
                _digest_file(hasher, Path(__file__).with_name("auto_plan.py"))
                for page in self.pages:
                    layout = page.path.parent / "layout.json"
                    if layout.is_file():
                        _digest_file(hasher, layout)
                        source_cards = json.loads(layout.read_text(encoding="utf-8")).get("cards", [])
                        for card in source_cards:
                            if card.get("file") != page.path.name:
                                continue
                            for record in card.get("boxes", []):
                                filename = record.get("background_file")
                                if filename:
                                    patch = (page.path.parent / filename).resolve()
                                    if not patch.is_relative_to(page.path.parent.resolve()):
                                        raise ValueError("정밀 배경판 경로가 카드 폴더 밖입니다")
                                    _digest_file(hasher, patch)
        return hasher.hexdigest()[:12]

    def ranges(self) -> list[tuple[int, int]]:
        result = []
        at = 0
        for page in self.pages:
            result.append((at, at + page.duration_ms))
            at += page.duration_ms
        return result


def camera(page: Page) -> tuple[float, float, float]:
    width, height = page.size
    base = min(CANVAS_W / width, (BOTTOM_Y - TOP_H - 40) / height)
    return ((CANVAS_W - width * base) / 2, TOP_H + 35, base * 100)


def poses(page: Page) -> list[tuple[int, tuple[float, float, float]]]:
    """Whole-card settle, with no clipping of the source headline or figures."""
    duration = page.duration_ms
    x, y, scale = camera(page)
    initial_scale = scale * 0.94
    initial_x = (CANVAS_W - page.size[0] * initial_scale / 100) / 2
    return [(0, (initial_x, y + 45, initial_scale)),
            (480, (x, y, scale)),
            (duration - 1, (x, y, scale))]


def _text(ident: int, name: str, value: str, x: int, y: int,
          w: int, h: int, size: int, start: int, duration: int,
          font: tuple[str, str]) -> dict[str, Any]:
    family, style = font
    return {
        "type": "createFxTextLayer", "compositionId": "main", "layerId": ident,
        "name": name, "insertIndex": 0,
        "activeRange": {"start": start, "duration": duration},
        "transform": transform(x, y),
        "sourceText": {"text": value, "fontFamily": family, "fontStyle": style,
                       "fontSize": size, "fillColor": rgb(INK),
                       "justification": "left", "boxText": True,
                       "boxPosition": [0, 0], "boxSize": [w, h]},
    }


def create_project(deck: Deck, output_root: Path, command: str) -> Path:
    project = output_root / "Card-story.tsrct"
    if output_root.exists():
        if project.is_file() and (output_root / "generated.json").is_file():
            return project
        raise ValueError(f"완성되지 않은 모션 프로젝트를 보존했습니다: {output_root}")
    build_root = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.build-",
                                       dir=output_root.parent))
    project = build_root / "Card-story.tsrct"
    work = build_root / ".tesseract-work"
    work.mkdir()
    run(command, "project", "create", "--project", str(project))
    for number, page in enumerate(deck.pages, 1):
        run(command, "project", "import-asset", "--project", str(project),
            "--file", str(page.path), "--asset-id", f"card-{number:02d}", "--kind", "image")
    for kind, (filename, _) in SOUNDS.items():
        path = SFX / filename
        if not path.is_file():
            raise ValueError(f"효과음 파일이 없습니다: {path}")
        run(command, "project", "import-asset", "--project", str(project),
            "--file", str(path), "--asset-id", f"sfx-{kind}", "--kind", "audio")
    run(command, "project", "import-asset", "--project", str(project),
        "--file", str(CHARACTER), "--asset-id", "character-creature", "--kind", "image")
    face = run(command, "project", "import-font", "--project",
               str(project), "--file", str(FONT))
    font = (str(face["fontFamily"]), str(face["fontStyle"]))
    display_face = run(command, "project", "import-font", "--project",
                       str(project), "--file", str(DISPLAY_FONT))
    display_font = (str(display_face["fontFamily"]), str(display_face["fontStyle"]))
    editable = work / "editable.json"
    run(command, "project", "checkout", "--project", str(project), "--output", str(editable))
    document = json.loads(editable.read_text(encoding="utf-8"))
    document["duration"] = deck.duration_ms / 1000
    layers = document["composition"]["layers"]
    ranges = deck.ranges()
    image_ids = []
    for index, (page, (start, end)) in enumerate(zip(deck.pages, ranges), 1):
        ident = 100 + index
        image_ids.append(ident)
        x, y, scale = camera(page)
        layers.append({
            "type": "Image", "id": ident, "name": f"{index:02d} 원본 카드 카메라",
            "blendMode": "normal",
            "activeRange": {"start": start, "duration": end - start},
            "transform": transform(x, y, scale),
            "source": {"assetId": f"card-{index:02d}", "fit": "contain"},
        })
    for index, (start, end) in enumerate(ranges, 1):
        layers.insert(0, {
            "type": "Image", "id": 180 + index,
            "name": f"{index:02d} 누끼 뱀 캐릭터",
            "blendMode": "normal",
            "activeRange": {"start": start, "duration": end - start},
            "transform": transform(-68, 1490, 35),
            "source": {"assetId": "character-creature", "fit": "contain"},
        })
    # Sibling index zero is frontmost. The full-frame fill sits behind every card,
    # so camera travel never exposes a black canvas at 9:16 edges.
    layers.append({
        "type": "Rect", "id": 190, "name": "전체 라벤더 배경",
        "activeRange": {"start": 0, "duration": deck.duration_ms},
        "transform": transform(0, 0),
        "rect": {"size": [CANVAS_W, CANVAS_H], "fillColor": rgb(BACKGROUND)},
    })
    # Structural sounds follow page changes and a few purposeful focus moves.
    cues = [(0, "impact", 0.75)]
    for index, (start, end) in enumerate(ranges):
        if index in {1, 3, 5, 7}:
            cues.append((start, "whoosh" if index in {1, 5} else "impact", 0.58))
    for number, (start, kind, gain) in enumerate(cues, 1):
        duration = SOUNDS[kind][1]
        layers.append({
            "type": "Audio", "id": 200 + number, "name": f"{number:02d} {kind} 전환 효과음",
            "activeRange": {"start": start, "duration": duration},
            "sourceRange": {"start": 0, "duration": duration},
            "sourceIntrinsicDuration": duration,
            "source": {"assetId": f"sfx-{kind}"},
            "volume": gain, "captionsEnabled": False,
        })
    editable.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    run(command, "project", "commit", "--project", str(project), "--file", str(editable))

    actions: list[dict[str, Any]] = []
    for page, ident in zip(deck.pages, image_ids):
        positions = poses(page)
        for offset, field in enumerate(("positionX", "positionY", "scaleX", "scaleY")):
            actions.append(keys(ident, field, [
                (at, values[(0, 1, 2, 2)[offset]]) for at, values in positions
            ]))
    for index, (start, end) in enumerate(ranges, 1):
        ident = 180 + index
        actions.append(keys(ident, "opacity", [(0, 0), (380, 100)]))
        actions.append(keys(ident, "positionY", [(0, 1560), (380, 1490), (540, 1495)]))
    next_id = 300
    actions.append(_text(next_id, "시리즈 라벨", deck.title, 54, 18, 760, 44,
                         27, 0, deck.duration_ms, font))
    next_id += 1
    count = len(deck.pages)
    gap = 12
    bar_w = (CANVAS_W - 108 - (count - 1) * gap) / count
    for index in range(count):
        x = 54 + index * (bar_w + gap)
        actions.append(rect(next_id, f"{index + 1:02d} 진행 배경",
                            x, 163, bar_w, 11, MUTED, 0, deck.duration_ms, 5.5))
        next_id += 1
    for index, (start, end) in enumerate(ranges, 1):
        page = deck.pages[index - 1]
        actions.append(_text(next_id, f"{index:02d} 독립 제목", page.hook,
                             54, 66, 790, 75, 55, start, end - start, display_font))
        actions.append(keys(next_id, "opacity", [(0, 0), (290, 100)]))
        actions.append(keys(next_id, "positionX", [(0, 32), (290, 54)]))
        next_id += 1
        actions.append(_text(next_id, f"{index:02d} 페이지 번호",
                             f"{index:02d} / {count:02d}", 860, 64, 170, 60,
                             37, start, end - start, font))
        next_id += 1
        x = 54 + (index - 1) * (bar_w + gap)
        actions.append(rect(next_id, f"{index:02d} 진행 채움", x, 163,
                            bar_w, 11, LIME, start, deck.duration_ms - start, 5.5))
        actions.append(keys(next_id, "scaleX", [(0, 0), (end - start - 100, 100)]))
        next_id += 1
        actions.append(_text(next_id, f"{index:02d} 한 줄 요약 라벨",
                             "한 줄 요약", 300, 1605, 400, 56,
                             36, start, end - start, display_font))
        actions.append(keys(next_id, "opacity", [(0, 0), (280, 100)]))
        next_id += 1
        actions.append(_text(next_id, f"{index:02d} 원문 기반 요약", page.takeaway,
                             300, 1674, 740, 155, 43, start, end - start, font))
        actions.append(keys(next_id, "opacity", [(0, 0), (380, 100)]))
        actions.append(keys(next_id, "positionY", [(0, 1698), (380, 1674)]))
        next_id += 1
    actions_path = work / "actions.json"
    actions_path.write_text(json.dumps(actions, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    run(command, "project", "apply", "--project", str(project),
        "--actions", str(actions_path))
    (build_root / "generated.json").write_text(json.dumps({
        "manifest": str(deck.manifest), "digest": deck.digest(),
        "cards": count, "duration_ms": deck.duration_ms,
        "source_images": [str(page.path) for page in deck.pages],
        "camera_keyframes": sum(len(poses(page)) for page in deck.pages),
        "audio_layers": len(cues), "music_layers": 0,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(build_root, output_root)
    return output_root / "Card-story.tsrct"


def inspect_video(path: Path, deck: Deck) -> dict[str, Any]:
    process = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of", "json", str(path),
    ], check=True, capture_output=True, text=True)
    report = json.loads(process.stdout)
    streams = report.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video or (video.get("width"), video.get("height")) != (1080, 1920):
        raise ValueError("렌더 영상이 릴스 9:16 규격이 아닙니다")
    if abs(float(Fraction(video.get("r_frame_rate", "0/1"))) - 30) > .01:
        raise ValueError("렌더 영상이 30fps가 아닙니다")
    if audio is None:
        raise ValueError("효과음 전용 영상의 오디오가 빠졌습니다")
    duration = float(report.get("format", {}).get("duration", 0))
    if abs(duration - deck.duration_ms / 1000) > .08:
        raise ValueError("렌더 영상의 길이가 모션 프로젝트와 다릅니다")
    return {"duration": duration, "width": 1080, "height": 1920,
            "fps": 30, "audio": "sfx_only"}


def encoded_still(path: Path, at_seconds: float) -> Image.Image:
    process = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(at_seconds),
        "-i", str(path), "-frames:v", "1", "-f", "image2pipe",
        "-vcodec", "png", "pipe:1",
    ], check=True, capture_output=True)
    return Image.open(io.BytesIO(process.stdout)).convert("RGB")


def verify_visual_content(deck: Deck, video: Path) -> dict[str, float]:
    """Reject missing artwork or large black canvas gaps at scene starts/holds."""
    minimum_detail = float("inf")
    maximum_black_share = 0.0
    for index, (start, end) in enumerate(deck.ranges(), 1):
        for when in (start + 100, (start + end) // 2):
            frame = encoded_still(video, when / 1000).crop((0, 190, 1080, 1550))
            sample = frame.resize((108, 136), Image.Resampling.BILINEAR)
            detail = max(ImageStat.Stat(sample).stddev)
            black_share = sum(1 for red, green, blue in sample.getdata()
                              if max(red, green, blue) < 15) / (108 * 136)
            minimum_detail = min(minimum_detail, detail)
            maximum_black_share = max(maximum_black_share, black_share)
            if detail < 12 or black_share > 0.28:
                raise ValueError(f"{index}장 {when}ms에 원본 누락 또는 검은 여백이 있습니다")
    return {"minimum_frame_detail": round(minimum_detail, 2),
            "maximum_black_share": round(maximum_black_share, 4)}


def proof_sheet(deck: Deck, video: Path, output: Path) -> None:
    if deck.data.get("source_kind") == "flat_images":
        motion_proof_sheet(deck,video,output)
        return
    width, height, gap, columns = 216, 384, 12, 4
    rows = (len(deck.pages) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * (width + gap) + gap,
                              rows * (height + gap) + gap), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    for index, (start, end) in enumerate(deck.ranges()):
        time = (start + (end - start) * 0.78) / 1000
        frame = encoded_still(video, time).resize((width, height), Image.Resampling.LANCZOS)
        x = gap + (index % columns) * (width + gap)
        y = gap + (index // columns) * (height + gap)
        sheet.paste(frame, (x, y))
        draw.text((x + 6, y + 5), f"{index + 1:02d}", fill="white",
                  stroke_width=2, stroke_fill="black")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def motion_proof_sheet(deck: Deck, video: Path, output: Path) -> None:
    """Show entry frames as well as holds; never inspect only a final overlay."""
    width,height,gap=216,384,12
    sheet=Image.new("RGB",(4*(width+gap)+gap,len(deck.pages)*(height+gap)+gap),BACKGROUND)
    draw=ImageDraw.Draw(sheet)
    for index,(start,end) in enumerate(deck.ranges()):
        for column,offset in enumerate((100,500,1100,round((end-start)*.78))):
            frame=encoded_still(video,(start+offset)/1000).resize((width,height),Image.Resampling.LANCZOS)
            x=gap+column*(width+gap); y=gap+index*(height+gap)
            sheet.paste(frame,(x,y))
            draw.text((x+6,y+5),f"{index+1:02d} / +{offset/1000:.2f}s",fill="white",stroke_width=2,stroke_fill="black")
    output.parent.mkdir(parents=True,exist_ok=True); sheet.save(output)
