#!/usr/bin/env python3
"""Generate an editable Tesseract Reel from any approved 4–6 card spec.

The cards supply every visible claim. Layout and motion are deterministic so a
new Threads post does not silently inherit the hand-authored 480p storyboard.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from PIL import ImageFont

from render_cards import validate
from render_reel import resolve_media


HERE = Path(__file__).resolve().parent
FONT_BODY = HERE / "fonts" / "PretendardVariable.ttf"
FONT_DISPLAY = HERE / "fonts" / "BlackHanSans-Regular.ttf"
SFX = HERE / "assets" / "sfx"
SFX_FILES = {"impact": ("soft-impact.wav", 400), "whoosh": ("air-whoosh.wav", 450),
             "ping": ("clear-ping.wav", 480)}
PAPER = "#F8F8F5"
INK = "#18212B"
BLUE = "#245CE8"
SOFT_BLUE = "#E8EEFF"
SOFT_GREEN = "#E5F4EB"
SOFT_PEACH = "#FCEDE5"
WHITE = "#FFFFFF"
LINE = "#DDE2E7"
MUTED = "#66717B"


def clean(value: Any) -> str:
    """Remove card emphasis syntax, not content or punctuation within sentences."""
    return re.sub(r"[{}\[\]]", "", str(value or "")).strip().rstrip(".")


def color(value: str) -> list[float]:
    return [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)] + [1]


def transform(x: float, y: float, opacity: float = 100) -> dict[str, Any]:
    return {"anchorPoint": [0, 0], "position": [x, y], "scale": [100, 100],
            "rotation": 0, "opacity": opacity}


def scene_ranges(count: int) -> list[tuple[int, int]]:
    if not 4 <= count <= 6:
        raise ValueError("모션 릴스에는 카드 4~6장이 필요합니다")
    durations = [3600] + [5000] * (count - 2) + [4600]
    cursor = 0
    result = []
    for duration in durations:
        result.append((cursor, cursor + duration))
        cursor += duration
    return result


def duration_seconds(card_count: int) -> float:
    return scene_ranges(card_count)[-1][1] / 1000


def fitted(value: Any, width: int, height: int, desired: int, *, display: bool = False,
           minimum: int = 35) -> tuple[str, int]:
    """Fit all supplied words in a known box; fail rather than omit claims."""
    raw = clean(value)
    if not raw:
        return "", desired
    font_file = FONT_DISPLAY if display else FONT_BODY
    for size in range(desired, min(minimum, desired) - 1, -2):
        font = ImageFont.truetype(str(font_file), size)
        rows: list[str] = []
        for paragraph in raw.splitlines():
            if not paragraph:
                rows.append("")
                continue
            row = ""
            for char in paragraph:
                candidate = row + char
                if row and font.getlength(candidate) > width:
                    rows.append(row.rstrip())
                    row = char.lstrip()
                else:
                    row = candidate
            rows.append(row.rstrip())
        if len(rows) * size * 1.27 <= height:
            return "\n".join(rows), size
    raise ValueError(f"모션 글자 박스에 문안을 모두 넣을 수 없습니다: {raw[:60]}")


class Author:
    def __init__(self, body_font: tuple[str, str], display_font: tuple[str, str]):
        self.actions: list[dict[str, Any]] = []
        self.next_id = 1
        self.body_font = body_font
        self.display_font = display_font

    def rect(self, name: str, x: float, y: float, width: float, height: float,
             fill: str, start: int, end: int, *, roundness: float = 0,
             stroke: str | None = None, stroke_width: float = 0) -> int:
        ident = self.next_id
        self.next_id += 1
        shape: dict[str, Any] = {"size": [width, height], "fillColor": color(fill),
                                 "roundness": roundness}
        if stroke:
            shape.update({"strokeEnabled": True, "strokeColor": color(stroke),
                          "strokeWidth": stroke_width})
        self.actions.append({"type": "createFxRectLayer", "compositionId": "main", "layerId": ident,
                             "name": name, "insertIndex": 0,
                             "activeRange": {"start": start, "duration": end - start},
                             "transform": transform(x, y), "rect": shape})
        return ident

    def text(self, name: str, value: Any, x: float, y: float, width: int, height: int,
             size: int, fill: str, start: int, end: int, *, display: bool = False,
             minimum: int = 35) -> int | None:
        content, size = fitted(value, width, height, size, display=display, minimum=minimum)
        if not content:
            return None
        ident = self.next_id
        self.next_id += 1
        family, style = self.display_font if display else self.body_font
        self.actions.append({"type": "createFxTextLayer", "compositionId": "main", "layerId": ident,
                             "name": name, "insertIndex": 0,
                             "activeRange": {"start": start, "duration": end - start},
                             "transform": transform(x, y),
                             "sourceText": {"text": content, "fontFamily": family,
                                            "fontStyle": style, "fontSize": size,
                                            "fillColor": color(fill), "justification": "left",
                                            "boxText": True, "boxPosition": [0, 0],
                                            "boxSize": [width, height], "leading": size * 1.2}})
        return ident

    def keys(self, ident: int, property_type: str, pairs: list[tuple[int, float]]) -> None:
        self.actions.append({"type": "setFxPropertyKeyframes", "compositionId": "main",
                             "property": {"layerId": ident, "propertyType": property_type},
                             "keyframes": [{"id": f"auto-{ident}-{property_type}-{time}",
                                            "layerTime": time,
                                            "value": {"type": "float", "value": value},
                                            "easing": ({"type": "cubicBezier", "x1": .2, "y1": .8,
                                                        "x2": .25, "y2": 1} if index else {"type": "linear"})}
                                           for index, (time, value) in enumerate(pairs)]})

    def enter(self, ident: int | None, x: float, y: float, delay: int = 0,
              *, dx: float = 0, dy: float = 65, duration: int = 360) -> None:
        if ident is None:
            return
        if dx:
            self.keys(ident, "positionX", [(0, x + dx), (delay + duration, x)])
        if dy:
            self.keys(ident, "positionY", [(0, y + dy), (delay + duration, y)])
        self.keys(ident, "opacity", [(0, 0), (delay + 240, 100)])

    def draw(self, ident: int | None, delay: int = 0, duration: int = 350) -> None:
        if ident is not None:
            self.keys(ident, "scaleX", [(0, 0), (delay + duration, 100)])


def card_label(layout: str) -> str:
    return {"cover": "핵심 먼저", "cover_vs": "비교", "cover_band": "핵심 먼저",
            "compare": "차이 보기", "split": "차이 보기", "steps": "순서 보기",
            "flow": "흐름 보기", "grid": "한눈에 보기", "ranked": "핵심 포인트",
            "keyword": "핵심 문장", "memo": "메모", "prompt": "원문 문구",
            "list": "정리", "cta": "정리"}[layout]


def base(a: Author, index: int, total: int, handle: str, card: dict[str, Any],
         start: int, end: int) -> None:
    a.rect(f"{index + 1} 배경", 0, 0, 1080, 1920, PAPER, start, end)
    a.rect(f"{index + 1} 상단 강조", 70, 153, 14, 14, BLUE, start, end, roundness=7)
    a.text(f"{index + 1} 계정", handle, 101, 128, 600, 65, 32, INK, start, end)
    label = card.get("label") or card.get("kicker") or card_label(card["layout"])
    a.text(f"{index + 1} 분류", label, 70, 215, 860, 85, 42, MUTED, start, end)
    a.rect(f"{index + 1} 아래 선", 70, 1505, 940, 3, LINE, start, end)
    a.text(f"{index + 1} 장수", f"{index + 1:02d} / {total:02d}",
           70, 1534, 300, 62, 31, MUTED, start, end)
    for n in range(total):
        width = (940 - (total - 1) * 12) / total
        a.rect(f"{index + 1} 진행 {n + 1}", 70 + n * (width + 12), 1477,
               width, 8, BLUE if n <= index else LINE, start, end, roundness=4)


def heading(a: Author, value: Any, start: int, end: int, *, y: int = 343,
            height: int = 240, desired: int = 104) -> None:
    ident = a.text("장면 제목", value, 70, y, 940, height, desired, INK,
                   start, end, display=True, minimum=64)
    # The subject must be visible at the cut; only its small settle is animated.
    if ident is not None:
        a.keys(ident, "scaleX", [(0, 103), (260, 100)])
        a.keys(ident, "scaleY", [(0, 103), (260, 100)])
    line = a.rect("제목 아래 포인트", 72, y + height + 16, 166, 12, BLUE,
                  start, end, roundness=6)
    a.draw(line, 340, 290)


def render_cover(a: Author, card: dict[str, Any], start: int, end: int) -> None:
    heading(a, card["title"], start, end, height=380, desired=116)
    subtitle = clean(card.get("subtitle"))
    if subtitle:
        ident = a.text("표지 설명", subtitle, 74, 807, 925, 240, 65, INK, start, end)
        a.enter(ident, 74, 807, 440)
    badge = clean(card.get("badge") or card.get("number") or "")
    if badge:
        panel = a.rect("표지 핵심 배지", 70, 1090, 940, 186, BLUE,
                       start, end, roundness=30)
        a.enter(panel, 70, 1090, 810, dx=850, dy=0)
        ident = a.text("표지 핵심 문구", badge, 105, 1120, 870, 135, 83,
                       WHITE, start, end, display=True, minimum=55)
        a.enter(ident, 105, 1120, 870, dx=850, dy=0)
    note = card.get("note") or {}
    if isinstance(note, dict):
        value = "  ".join(filter(None, (clean(note.get("title")), clean(note.get("text")))))
        ident = a.text("표지 보충", value, 76, 1348, 930, 116, 40,
                       MUTED, start, end)
        a.enter(ident, 76, 1348, 1430, dy=35)


def render_compare(a: Author, card: dict[str, Any], start: int, end: int) -> None:
    heading(a, card["title"], start, end, height=205, desired=100)
    body = clean(card.get("body"))
    if body:
        ident = a.text("비교 설명", body, 75, 594, 935, 180, 50, INK, start, end)
        a.enter(ident, 75, 594, 280, dy=45)
    for index, key in enumerate(("left", "right")):
        value = card[key]
        x = 70 + index * 492
        fill = SOFT_BLUE if index == 0 else SOFT_PEACH
        panel = a.rect(f"{key} 비교 패널", x, 815, 448, 482, fill,
                       start, end, roundness=34)
        a.enter(panel, x, 815, 550 + index * 230,
                dx=-430 if index == 0 else 430, dy=0, duration=430)
        ident = a.text(f"{key} 이름", value["name"], x + 35, 868, 375, 125,
                       72, BLUE if index == 0 else INK, start, end,
                       display=True, minimum=50)
        a.enter(ident, x + 35, 868, 650 + index * 230,
                dx=-430 if index == 0 else 430, dy=0)
        ident = a.text(f"{key} 설명", value["text"], x + 37, 1035, 370, 228,
                       49, INK, start, end, minimum=38)
        a.enter(ident, x + 37, 1035, 970 + index * 230, dy=45)
    note = card.get("note")
    tail_parts = [clean(card.get("connector")), clean(card.get("verdict_label")),
                  clean(card.get("verdict"))]
    if isinstance(note, dict):
        tail_parts += [clean(note.get("title")), clean(note.get("text"))]
    else:
        tail_parts.append(clean(note))
    tail = "  ·  ".join(part for part in tail_parts if part)
    if tail:
        ident = a.text("비교 결론", tail, 74, 1322, 936, 145, 43,
                       BLUE, start, end, minimum=35)
        a.enter(ident, 74, 1322, 2050, dy=42)


def render_rows(a: Author, card: dict[str, Any], start: int, end: int) -> None:
    layout = card["layout"]
    title = card.get("title") or card.get("text") or card.get("name")
    heading(a, title, start, end, height=230, desired=98)
    if layout in {"steps", "flow"}:
        entries = [(clean(item.get("lead") or item.get("name")),
                    "  ·  ".join(filter(None, (clean(item.get("key") or item.get("text")),
                                                 *[clean(option) for option in item.get("options", [])]))))
                   for item in card["steps"]]
    elif layout in {"grid", "list", "memo"}:
        entries = [(clean(item.get("name") or item.get("title")), clean(item.get("text")))
                   for item in card["items"]]
    elif layout == "cta":
        entries = [(f"{n:02d}", clean(item)) for n, item in enumerate(card["points"], 1)]
    elif layout == "ranked":
        entries = [(clean(card["rank"]), clean(card["name"])),
                   (clean(card.get("tag")), clean(card["text"]))]
    else:
        raise ValueError(f"행 레이아웃을 알 수 없습니다: {layout}")
    top, bottom = 662, 1330
    gap = 24
    panel_h = int((bottom - top - (len(entries) - 1) * gap) / len(entries))
    for index, (lead, text) in enumerate(entries):
        y = top + index * (panel_h + gap)
        fill = (SOFT_BLUE, WHITE, SOFT_GREEN, WHITE)[index % 4]
        panel = a.rect(f"{index + 1}번 항목 배경", 70, y, 940, panel_h,
                       fill, start, end, roundness=27,
                       stroke=LINE if fill == WHITE else None, stroke_width=3)
        delay = 450 + index * 650
        a.enter(panel, 70, y, delay, dx=-1050 if index % 2 == 0 else 1050,
                dy=0, duration=440)
        ident = a.text(f"{index + 1}번 항목 라벨", lead, 103, y + 27, 220,
                       panel_h - 40, 54, BLUE, start, end, display=True, minimum=38)
        a.enter(ident, 103, y + 27, delay + 70, dy=38)
        ident = a.text(f"{index + 1}번 항목 내용", text, 326, y + 30, 636,
                       panel_h - 43, 55, INK, start, end, minimum=38)
        a.enter(ident, 326, y + 30, delay + 130, dy=38)
    note = card.get("note") or card.get("highlight")
    if isinstance(note, dict):
        note = "  ".join(filter(None, (clean(note.get("title")), clean(note.get("text")))))
    extra = "  ·  ".join(filter(None, (clean(card.get("body")), clean(note))))
    if extra:
        ident = a.text("행 정리", extra, 74, 1350, 930, 120, 39,
                       BLUE, start, end, minimum=33)
        a.enter(ident, 74, 1350, 2800, dy=32)


def render_keyword(a: Author, card: dict[str, Any], start: int, end: int) -> None:
    value = card.get("text") or card.get("title")
    heading(a, value, start, end, y=468, height=500, desired=124)
    sub = card.get("sub") or card.get("after")
    if sub:
        ident = a.text("핵심 부연", sub, 78, 1110, 925, 220, 57,
                       INK, start, end)
        a.enter(ident, 78, 1110, 760)


def render_prompt(a: Author, card: dict[str, Any], start: int, end: int) -> None:
    heading(a, card["title"], start, end, height=210, desired=98)
    panel = a.rect("원문 문구 패널", 70, 650, 940, 650, SOFT_BLUE,
                   start, end, roundness=28)
    a.enter(panel, 70, 650, 470, dy=80)
    if card.get("box_label"):
        ident = a.text("원문 문구 라벨", card["box_label"], 107, 682, 860, 64,
                       40, BLUE, start, end)
        a.enter(ident, 107, 682, 530, dy=30)
    ident = a.text("원문 문구", card["prompt"], 107, 756, 866, 490,
                   56, INK, start, end, minimum=38)
    a.enter(ident, 107, 756, 570, dy=55)
    note = card.get("note")
    note_text = clean(note.get("text")) if isinstance(note, dict) else clean(note)
    tail = "  ·  ".join(filter(None, (clean(card.get("after")), note_text)))
    if tail:
        ident = a.text("문구 다음", tail, 74, 1340, 930, 122,
                       46, BLUE, start, end)
        a.enter(ident, 74, 1340, 1650)


def author_actions(spec: dict[str, Any], body_font: tuple[str, str],
                   display_font: tuple[str, str]) -> list[dict[str, Any]]:
    cards = validate(spec)
    ranges = scene_ranges(len(cards))
    a = Author(body_font, display_font)
    for index, (card, (start, end)) in enumerate(zip(cards, ranges)):
        layout = card["layout"]
        base(a, index, len(cards), clean(spec["handle"]), card, start, end)
        if layout in {"cover", "cover_vs", "cover_band"}:
            if layout == "cover_vs":
                card = {**card, "title": card["title"],
                        "subtitle": f"{clean(card['left'])}  /  {clean(card['right'])}"}
            render_cover(a, card, start, end)
        elif layout in {"compare", "split"}:
            render_compare(a, card, start, end)
        elif layout in {"steps", "flow", "grid", "list", "memo", "cta", "ranked"}:
            render_rows(a, card, start, end)
        elif layout == "keyword":
            render_keyword(a, card, start, end)
        elif layout == "prompt":
            render_prompt(a, card, start, end)
    return a.actions


def command_run(command: str, *args: str) -> dict[str, Any]:
    result = subprocess.run([command, *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Tesseract {' '.join(args[:2])} 실패: {(result.stderr or result.stdout)[-700:]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _font_face(reply: dict[str, Any], fallback: tuple[str, str]) -> tuple[str, str]:
    face = reply.get("faces", [{}])[0] if reply.get("faces") else reply
    return str(face.get("fontFamily") or fallback[0]), str(face.get("fontStyle") or fallback[1])


def create_project(spec_path: Path, output_root: Path, command: str) -> Path:
    """Claim a new project directory and author the complete native timeline."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    cards = validate(spec)
    media = resolve_media(spec_path, spec)
    if len(media) > len(cards):
        raise ValueError("원글 미디어가 카드 수보다 많아 모션에서 일부가 빠질 수 있습니다")
    if output_root.exists():
        project = output_root / "Motion-auto.tsrct"
        if project.is_file() and (output_root / "generated.json").is_file():
            return project
        raise ValueError(f"완성되지 않은 모션 작업 폴더가 이미 있습니다: {output_root}")
    output_root.mkdir()
    work = output_root / ".tesseract-work"
    previews = output_root / "Previews"
    work.mkdir()
    previews.mkdir()
    project = output_root / "Motion-auto.tsrct"
    command_run(command, "project", "create", "--project", str(project))
    body = _font_face(command_run(command, "project", "import-font", "--project",
                                  str(project), "--file", str(FONT_BODY)),
                      ("Pretendard Variable", "Bold"))
    display = _font_face(command_run(command, "project", "import-font", "--project",
                                     str(project), "--file", str(FONT_DISPLAY)),
                         ("Black Han Sans", "Regular"))
    for kind, (filename, _) in SFX_FILES.items():
        cue = SFX / filename
        if not cue.is_file():
            raise ValueError(f"자동 모션 효과음이 없습니다: {cue}")
        command_run(command, "project", "import-asset", "--project", str(project),
                    "--file", str(cue), "--asset-id", f"auto-{kind}", "--kind", "audio")
    for index, item in enumerate(media, 1):
        if item["type"] == "IMAGE":
            command_run(command, "project", "import-asset", "--project", str(project),
                        "--file", str(item["path"]), "--asset-id", f"source-{index}",
                        "--kind", "image")
        else:
            command_run(command, "project", "import-video", "--project", str(project),
                        "--file", str(item["path"]), "--asset-id", f"source-{index}")
    editable = work / "editable.json"
    command_run(command, "project", "checkout", "--project", str(project),
                "--output", str(editable))
    document = json.loads(editable.read_text(encoding="utf-8"))
    document["duration"] = duration_seconds(len(cards))
    editable.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command_run(command, "project", "commit", "--project", str(project),
                "--file", str(editable))
    actions = author_actions(spec, body, display)
    actions_file = work / "actions.json"
    actions_file.write_text(json.dumps(actions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command_run(command, "project", "apply", "--project", str(project),
                "--actions", str(actions_file))
    command_run(command, "project", "checkout", "--project", str(project),
                "--output", str(editable))
    document = json.loads(editable.read_text(encoding="utf-8"))
    layers = document["composition"]["layers"]
    last_id = max(layer["id"] for layer in layers) + 1
    for index, item in enumerate(media):
        start, end = scene_ranges(len(cards))[index]
        source_id = f"source-{index + 1}"
        background = next(layer for layer in layers if layer["name"] == f"{index + 1} 배경")
        layer: dict[str, Any] = {
            "type": "Image" if item["type"] == "IMAGE" else "Video",
            "id": last_id + index, "name": f"{index + 1} 원글 {item['type'].lower()}",
            "activeRange": {"start": start, "duration": end - start},
            "transform": transform(0, 0, opacity=21),
            "source": {"assetId": source_id, "fit": "cover"}}
        if item["type"] == "VIDEO":
            available = max(1, int(item["duration"] * 1000))
            layer["activeRange"]["duration"] = min(end - start, available)
            layer["sourceRange"] = {"start": 0, "duration": layer["activeRange"]["duration"]}
            layer["sourceIntrinsicDuration"] = available
            layer["volume"] = 0
        layers.insert(layers.index(background), layer)
    last_id += len(media)
    cues: list[tuple[str, int]] = [("impact", 0)]
    cues += [("whoosh", max(0, start - 175)) for start, _ in scene_ranges(len(cards))[1:-1]]
    cues.append(("ping", scene_ranges(len(cards))[-1][0] + 550))
    for index, (kind, at) in enumerate(cues):
        length = SFX_FILES[kind][1]
        layers.append({"type": "Audio", "id": last_id + index,
                       "name": f"장면 {index + 1} {kind}",
                       "activeRange": {"start": at, "duration": length},
                       "sourceRange": {"start": 0, "duration": length},
                       "sourceIntrinsicDuration": length,
                       "source": {"assetId": f"auto-{kind}"},
                       "volume": 1.1 if kind == "impact" else .85,
                       "captionsEnabled": False})
    editable.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command_run(command, "project", "commit", "--project", str(project),
                "--file", str(editable))
    (output_root / "generated.json").write_text(json.dumps({
        "source": str(spec_path), "cards": len(cards), "duration": duration_seconds(len(cards)),
        "text_layers": sum(action["type"] == "createFxTextLayer" for action in actions),
        "shape_layers": sum(action["type"] == "createFxRectLayer" for action in actions),
        "sfx_layers": len(cues), "source_media": len(media)},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return project
