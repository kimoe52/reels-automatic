#!/usr/bin/env python3
"""Render a 4:5 illustrated card-news deck as editable Tesseract documents.

The comic treatment is visual only. All claims come from an approved card spec;
the supplied character cutouts are embedded as-is, never regenerated.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFont

import render_cards
from render_motion_auto import clean, color, command_run


HERE = Path(__file__).resolve().parent
CARD_MOTION = HERE.parent / "card_motion"
if str(CARD_MOTION) not in sys.path:
    sys.path.insert(0, str(CARD_MOTION))
from source_layers import reconstruction_metrics  # noqa: E402


ROOT = HERE.parents[1]
BACKGROUND = HERE / "assets" / "comic-lavender-bg-v1.png"
HUMAN = HERE / "assets" / "character-human.png"
CREATURE = ROOT / "content" / "character" / "character-creature-cutout.png"
FONT_DISPLAY = HERE / "fonts" / "BlackHanSans-Regular.ttf"
FONT_BODY = HERE / "fonts" / "PretendardVariable.ttf"
WIDTH, HEIGHT = 1080, 1350
INK = "#101014"
PURPLE = "#C986F1"
DEEP_PURPLE = "#55217D"
YELLOW = "#FFF18C"
CREAM = "#FFFBE2"
WHITE = "#FFFFFF"
PALE = "#F6EAFF"
BACKGROUND_LAYER_NAME = "라벤더 구름 배경"


def command() -> str:
    candidate = Path.home() / "Library/Application Support/Tesseract/bin/tsrct"
    if not candidate.is_file():
        raise ValueError("Tesseract CLI를 찾지 못했습니다")
    return str(candidate)


def _face(value: dict[str, Any], fallback: tuple[str, str]) -> tuple[str, str]:
    faces = value.get("faces")
    face = faces[0] if isinstance(faces, list) and faces else value
    return str(face.get("fontFamily") or fallback[0]), str(face.get("fontStyle") or fallback[1])


def _font_file(display: bool) -> Path:
    return FONT_DISPLAY if display else FONT_BODY


def fit(value: Any, width: int, height: int, size: int, *, display: bool = False,
        minimum: int = 29) -> tuple[str, int]:
    raw = clean(value)
    if not raw:
        return "", size
    for candidate in range(size, min(size, minimum) - 1, -2):
        font = ImageFont.truetype(str(_font_file(display)), candidate)
        lines: list[str] = []
        for paragraph in raw.splitlines():
            line = ""
            for char in paragraph:
                if line and font.getlength(line + char) > width - 12:
                    lines.append(line.rstrip())
                    line = char.lstrip()
                else:
                    line += char
            lines.append(line.rstrip())
        if len(lines) * candidate * (1.11 if display else 1.24) <= height:
            return "\n".join(lines), candidate
    raise ValueError(f"만화 카드 글자 영역을 넘습니다: {raw[:70]}")


def transform(x: float, y: float, *, scale: float = 100) -> dict[str, Any]:
    return {"anchorPoint": [0, 0], "position": [x, y], "scale": [scale, scale],
            "rotation": 0, "opacity": 100}


class Canvas:
    def __init__(self, body_font: tuple[str, str], display_font: tuple[str, str]):
        self.actions: list[dict[str, Any]] = []
        self.next_id = 1
        self.body_font = body_font
        self.display_font = display_font
        self.characters: list[tuple[str, float, float, float, bool]] = []

    def rect(self, name: str, x: float, y: float, width: float, height: float,
             fill: str, *, radius: float = 0, stroke: str | None = None,
             stroke_width: float = 0) -> None:
        shape: dict[str, Any] = {"size": [width, height], "fillColor": color(fill),
                                 "roundness": radius}
        if stroke:
            shape.update({"strokeEnabled": True, "strokeColor": color(stroke),
                          "strokeWidth": stroke_width})
        self.actions.append({"type": "createFxRectLayer", "compositionId": "main",
                             "layerId": self.next_id, "name": name, "insertIndex": 0,
                             "activeRange": {"start": 0, "duration": 3000},
                             "transform": transform(x, y), "rect": shape})
        self.next_id += 1

    def text(self, name: str, value: Any, x: float, y: float, width: int,
             height: int, size: int, *, fill: str = INK, display: bool = False,
             outline: float = 0, stroke_color: str = INK,
             align: str = "left", minimum: int = 29) -> None:
        content, actual = fit(value, width, height, size, display=display,
                              minimum=minimum)
        if not content:
            return
        family, style = self.display_font if display else self.body_font
        source: dict[str, Any] = {"text": content, "fontFamily": family,
                                  "fontStyle": style, "fontSize": actual,
                                  "fillColor": color(fill), "justification": align,
                                  "boxText": True, "boxPosition": [0, 0],
                                  "boxSize": [width, height],
                                  "leading": actual * (1.05 if display else 1.14),
                                  "strokeWidth": outline,
                                  "strokeColor": color(stroke_color),
                                  "applyStroke": outline > 0,
                                  "strokeOverFill": False}
        self.actions.append({"type": "createFxTextLayer", "compositionId": "main",
                             "layerId": self.next_id, "name": name, "insertIndex": 0,
                             "activeRange": {"start": 0, "duration": 3000},
                             "transform": transform(x, y), "sourceText": source})
        self.next_id += 1

    def character(self, which: str, x: float, y: float, scale: float,
                  *, foreground: bool = False) -> None:
        self.characters.append((which, x, y, scale, foreground))


def frame(canvas: Canvas, number: int, total: int) -> None:
    canvas.rect("페이지 번호 알약", 38, 27, 132, 69, WHITE,
                radius=34, stroke=INK, stroke_width=4)
    canvas.text("페이지 번호", f"{number}/{total}", 54, 40, 104, 48,
                40, display=True, align="center")


def title(canvas: Canvas, value: Any, *, y: int = 125,
          height: int = 190, size: int = 88, fill: str = INK) -> None:
    canvas.text("큰 제목", value, 58, y, 964, height, size, fill=fill,
                display=True, outline=12, stroke_color=WHITE,
                align="center", minimum=58)


def box(canvas: Canvas, name: str, x: float, y: float, width: float,
        height: float, fill: str = WHITE, radius: float = 34) -> None:
    canvas.rect(f"{name} 그림자", x + 5, y + 9, width, height,
                PALE, radius=radius, stroke=DEEP_PURPLE, stroke_width=2)
    canvas.rect(name, x, y, width, height, fill,
                radius=radius, stroke=INK, stroke_width=5)


def draw_cover(c: Canvas, card: dict[str, Any]) -> None:
    title(c, card["title"], y=112, height=385, size=121)
    if card.get("subtitle"):
        c.text("표지 근거", card["subtitle"], 70, 492, 940, 144,
               50, display=False, align="center", minimum=41)
    c.character("human", 3, 570, 57)
    c.character("creature", 518, 645, 51)
    box(c, "표지 결론", 58, 1040, 964, 246, CREAM, 46)
    c.text("표지 배지", card.get("badge", ""), 91, 1073, 898, 99,
           83, fill=PURPLE, display=True, outline=5, align="center")
    note = card.get("note") or {}
    c.text("표지 설명", "  ·  ".join(filter(None, (clean(note.get("title")),
                                                  clean(note.get("text"))))),
           91, 1178, 898, 82, 43, align="center", minimum=35)


def draw_compare(c: Canvas, card: dict[str, Any], *, second: bool = False) -> None:
    title(c, card["title"], y=131, height=164, size=89)
    c.text("비교 소개", card.get("body", ""), 72, 307, 936, 155,
           47, align="center", minimum=38)
    for index, side in enumerate(("left", "right")):
        value = card[side]
        x = 54 + index * 497
        box(c, f"{side} 비교 카드", x, 485, 475, 525, WHITE, 40)
        c.rect(f"{side} 제목 칩", x + 30, 520, 415, 112,
               YELLOW if index == 0 else PALE, radius=54)
        c.text(f"{side} 이름", value["name"], x + 35, 532, 405, 96,
               72, fill=INK, display=True, align="center", minimum=49)
        if index == 0:
            c.character("human", x + (112 if second else 94), 606,
                        20 if second else 23, foreground=True)
        else:
            c.character("creature", x + 10, 531, 34, foreground=True)
        c.text(f"{side} 설명", value["text"], x + 33, 866, 409, 120,
               52, align="center", minimum=38)
    box(c, "비교 결론 말풍선", 61, 1050, 958, 243, CREAM, 40)
    c.text("비교 연결어", card.get("connector", ""), 87, 1077,
           906, 75, 52, fill=DEEP_PURPLE, display=True,
           align="center", minimum=39)
    note = card.get("note") or {}
    verdict = card.get("verdict") or note.get("text") or ""
    c.text("비교 결론", verdict, 86, 1154, 908, 112,
           48, align="center", minimum=38)


def draw_steps(c: Canvas, card: dict[str, Any]) -> None:
    title(c, card["title"], y=130, height=190, size=92)
    steps = card["steps"]
    if not 2 <= len(steps) <= 4:
        raise ValueError("만화 카드 단계는 2~4개여야 합니다")
    top, gap = 355, 24
    panel_h = int((1058 - top - gap * (len(steps) - 1)) / len(steps))
    for index, step in enumerate(steps):
        y = top + index * (panel_h + gap)
        box(c, f"{index + 1}단계", 61, y, 958, panel_h,
            WHITE if index % 2 else CREAM, 36)
        c.rect(f"{index + 1}단계 번호칩", 87, y + 26, 132, panel_h - 52,
               YELLOW if index % 2 == 0 else PURPLE, radius=38,
               stroke=INK, stroke_width=4)
        c.text(f"{index + 1}단계 번호", f"{index + 1:02d}", 108, y + 43,
               90, panel_h - 70, 65, display=True, align="center")
        lead = clean(step.get("lead") or step.get("name"))
        key = clean(step.get("key") or step.get("text"))
        c.text(f"{index + 1}단계 말머리", lead, 251, y + 24, 701, 66,
               43, fill=DEEP_PURPLE, display=True, minimum=34)
        c.text(f"{index + 1}단계 내용", key, 251, y + 93, 701,
               panel_h - 110, 55, minimum=37)
    note = card.get("note") or {}
    note_text = note.get("text") if isinstance(note, dict) else note
    box(c, "단계 핵심", 61, 1100, 958, 174, PALE, 39)
    c.text("단계 핵심 문구", note_text, 92, 1135, 896, 108,
           54, fill=DEEP_PURPLE, display=True, align="center", minimum=40)


def draw_list(c: Canvas, card: dict[str, Any]) -> None:
    title(c, card["title"], y=126, height=158, size=91)
    entries = card.get("items", [])
    if not 2 <= len(entries) <= 4:
        raise ValueError("만화 요약 카드는 항목 2~4개가 필요합니다")
    top, gap = 307, 20
    panel_h = int((882 - top - gap * (len(entries) - 1)) / len(entries))
    for index, entry in enumerate(entries):
        y = top + index * (panel_h + gap)
        box(c, f"요약 항목 {index + 1}", 70, y, 940, panel_h,
            CREAM if index == 0 else WHITE, 33)
        c.rect(f"요약 칩 {index + 1}", 91, y + 28, 232, panel_h - 56,
               YELLOW if index == 0 else PALE, radius=30)
        c.text(f"요약 항목명 {index + 1}", entry["title"], 108,
               y + 42, 205, panel_h - 74, 55, display=True,
               align="center", minimum=40)
        c.text(f"요약 항목 내용 {index + 1}", entry["text"], 347,
               y + 34, 620, panel_h - 64, 46, minimum=36)
    c.character("human", 2, 739, 43)
    c.character("creature", 635, 823, 37)
    highlight = card.get("highlight") or {}
    box(c, "최종 결론", 57, 1077, 966, 214, CREAM, 40)
    c.text("최종 결론 제목", highlight.get("title"), 91, 1094, 898, 88,
           56, fill=DEEP_PURPLE, display=True, align="center", minimum=42)
    c.text("최종 결론 본문", highlight.get("text"), 91, 1190, 898, 79,
           43, align="center", minimum=35)


def draw_card(c: Canvas, card: dict[str, Any], number: int, total: int) -> None:
    frame(c, number, total)
    layout = card["layout"]
    if layout == "cover":
        draw_cover(c, card)
    elif layout == "compare":
        draw_compare(c, card, second=number > 2)
    elif layout == "steps":
        draw_steps(c, card)
    elif layout == "list":
        draw_list(c, card)
    else:
        raise ValueError(f"만화 카드에서 아직 조판하지 않은 레이아웃: {layout}")


def make_one(command_path: str, root: Path, card: dict[str, Any],
             number: int, total: int) -> Path:
    stem = f"{number:02d}-{card['layout']}"
    project = root / f"{stem}.tsrct"
    output = root / f"{stem}.png"
    work = root / ".tesseract-work"
    work.mkdir(exist_ok=True)
    command_run(command_path, "project", "create", "--project", str(project))
    body_face = _face(command_run(command_path, "project", "import-font", "--project",
                                  str(project), "--file", str(FONT_BODY)),
                      ("Pretendard Variable", "Bold"))
    display_face = _face(command_run(command_path, "project", "import-font", "--project",
                                     str(project), "--file", str(FONT_DISPLAY)),
                         ("Black Han Sans", "Regular"))
    for asset_id, source in (("bg", BACKGROUND), ("human", HUMAN), ("creature", CREATURE)):
        command_run(command_path, "project", "import-asset", "--project", str(project),
                    "--file", str(source), "--asset-id", asset_id, "--kind", "image")
    editable = work / f"{stem}-editable.json"
    command_run(command_path, "project", "checkout", "--project", str(project),
                "--output", str(editable))
    doc = json.loads(editable.read_text(encoding="utf-8"))
    doc["dimensions"] = {"width": WIDTH, "height": HEIGHT}
    doc["duration"] = 3
    bg_layer = {"type": "Image", "id": 5000, "name": BACKGROUND_LAYER_NAME,
                "activeRange": {"start": 0, "duration": 3000},
                "transform": transform(0, 0),
                "source": {"assetId": "bg", "fit": "cover"}}
    doc["composition"]["layers"].append(bg_layer)
    editable.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command_run(command_path, "project", "commit", "--project", str(project),
                "--file", str(editable))
    canvas = Canvas(body_face, display_face)
    draw_card(canvas, card, number, total)
    actions_file = work / f"{stem}-actions.json"
    actions_file.write_text(json.dumps(canvas.actions, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    command_run(command_path, "project", "apply", "--project", str(project),
                "--actions", str(actions_file))
    if canvas.characters:
        command_run(command_path, "project", "checkout", "--project", str(project),
                    "--output", str(editable))
        doc = json.loads(editable.read_text(encoding="utf-8"))
        layers = doc["composition"]["layers"]
        bg_index = next(index for index, layer in enumerate(layers)
                        if layer["name"] == "라벤더 구름 배경")
        for offset, (which, x, y, scale, foreground) in enumerate(canvas.characters):
            layer = {
                "type": "Image", "id": 6000 + offset, "name": f"원본 캐릭터 {which}",
                "activeRange": {"start": 0, "duration": 3000},
                "transform": transform(x, y, scale=scale),
                "source": {"assetId": which, "fit": "contain"}}
            layers.insert(0 if foreground else bg_index + offset, layer)
        editable.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        command_run(command_path, "project", "commit", "--project", str(project),
                    "--file", str(editable))
    command_run(command_path, "preview", "--project", str(project),
                "--time", "1", "--output", str(output))
    with Image.open(output) as image:
        if image.size != (WIDTH, HEIGHT):
            raise ValueError(f"{stem} 크기가 4:5가 아닙니다: {image.size}")
    return output


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _native_role(layer: dict[str, Any]) -> str:
    """Map this renderer's named native layers to the shared motion vocabulary."""
    name = str(layer.get("name") or "")
    if layer.get("type") == "Image":
        return "character" if "캐릭터" in name else "prop"
    if "제목" in name or "배지" in name or "말머리" in name:
        return "title"
    if "말풍선" in name:
        return "bubble"
    if any(token in name for token in ("카드", "단계", "항목", "결론", "그림자")):
        return "panel"
    if any(token in name for token in ("칩", "알약")):
        return "decoration"
    return "text" if layer.get("type") == "Text" else "decoration"


def _native_text(layer: dict[str, Any]) -> str | None:
    source = layer.get("sourceText")
    if isinstance(source, dict) and isinstance(source.get("text"), str):
        return source["text"]
    return None


def _moving(layer: dict[str, Any]) -> bool:
    """Cards are a motion source: only the page-number chip is deliberately static."""
    return not str(layer.get("name") or "").startswith("페이지 번호")


def _unique_layer_name(raw: Any, used: set[str]) -> str:
    base = " ".join(str(raw or "레이어").split())[:80] or "레이어"
    candidate = base
    number = 2
    while candidate in used:
        suffix = f"-{number}"
        candidate = f"{base[:80 - len(suffix)]}{suffix}"
        number += 1
    used.add(candidate)
    return candidate


def _write_crop(source: Path, target: Path) -> list[int]:
    """Mechanically crop an RGBA native render to its exact visible alpha bounds."""
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(target)
        return [0, 0, 0, 0]
    image.crop(bbox).save(target)
    left, top, right, bottom = bbox
    return [left, top, right - left, bottom - top]


def _write_full_rgba(source: Path, target: Path) -> None:
    with Image.open(source) as opened:
        opened.convert("RGBA").save(target)


def _clone_for_layer_export(command_path: str, source_project: Path, target_project: Path,
                            work: Path) -> dict[str, Any]:
    """Copy the authoritative document into a fresh project without touching it."""
    command_run(command_path, "project", "create", "--project", str(target_project))
    for asset_id, source in (("bg", BACKGROUND), ("human", HUMAN), ("creature", CREATURE)):
        command_run(command_path, "project", "import-asset", "--project", str(target_project),
                    "--file", str(source), "--asset-id", asset_id, "--kind", "image")
    for font in (FONT_BODY, FONT_DISPLAY):
        command_run(command_path, "project", "import-font", "--project", str(target_project),
                    "--file", str(font))
    source_json = work / "authoritative-source.json"
    command_run(command_path, "project", "checkout", "--project", str(source_project),
                "--output", str(source_json))
    document = json.loads(source_json.read_text(encoding="utf-8"))
    command_run(command_path, "project", "commit", "--project", str(target_project),
                "--file", str(source_json))
    return document


def _isolated_document(document: dict[str, Any], visible_id: int) -> dict[str, Any]:
    isolated = copy.deepcopy(document)
    for layer in isolated["composition"]["layers"]:
        layer["isHidden"] = layer.get("id") != visible_id
    return isolated


def _preview_native_layer(command_path: str, project: Path, document: dict[str, Any],
                          visible_id: int, work: Path, output: Path) -> None:
    """Render one native layer in a disposable export project, never the source project."""
    isolated = _isolated_document(document, visible_id)
    checkpoint = work / f"layer-{visible_id}.json"
    checkpoint.write_text(json.dumps(isolated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command_run(command_path, "project", "commit", "--project", str(project), "--file", str(checkpoint))
    command_run(command_path, "preview", "--project", str(project), "--time", "1", "--output", str(output))


def _reconstruction_metrics(source: Image.Image, composite: Image.Image) -> dict[str, float]:
    """Use the motion pipeline's single reconstruction metric definition."""
    return reconstruction_metrics(source, composite)


def _write_reconstruction_diagnostic(source: Path, composite: Image.Image, layers: list[dict[str, Any]],
                                     root: Path, metrics: dict[str, float]) -> Path:
    """Keep inspectable native evidence when strict source reconstruction fails."""
    diagnostic_root = root / "source-layers" / f"page-{int(source.name[:2]):02d}"
    original_path = diagnostic_root / "original.png"
    composite_path = diagnostic_root / "recomposed.png"
    difference_path = diagnostic_root / "difference.png"
    with Image.open(source) as source_image:
        original = source_image.convert("RGBA")
    original.save(original_path)
    composite.convert("RGBA").save(composite_path)
    ImageChops.difference(original.convert("RGB"), composite.convert("RGB")).convert("RGBA").save(difference_path)
    diagnostic_path = diagnostic_root / "diagnostic.json"
    diagnostic_path.write_text(json.dumps({
        "version": 1,
        "source_file": source.name,
        "source_sha256": _sha256(source),
        "records": layers,
        "metrics": metrics,
        "original": original_path.name,
        "recomposed": composite_path.name,
        "difference": difference_path.name,
        "status": "reconstruction_failed",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return diagnostic_path


def _verify_reconstruction(source: Path, background: Path, layers: list[dict[str, Any]], root: Path) -> None:
    """Fail closed if exported native RGBA layers cannot reproduce the source card pixels."""
    with Image.open(background) as background_image:
        composite = background_image.convert("RGBA")
    for item in sorted(layers, key=lambda layer: int(layer["z_index"])):
        x, y, _, _ = item["box"]
        with Image.open(root / item["file"]) as layer_image:
            composite.alpha_composite(layer_image.convert("RGBA"), (x, y))
    with Image.open(source) as source_image:
        expected = source_image.convert("RGBA")
    metrics = _reconstruction_metrics(expected, composite)
    # This is the same bounded anti-alias allowance enforced by the consuming
    # loader. It cannot conceal a missing panel, word, or character layer.
    if metrics["mean_error"] > .2 or metrics["significant_share"] > .001:
        diagnostic = _write_reconstruction_diagnostic(source, composite, layers, root, metrics)
        raise RuntimeError(f"네이티브 레이어가 원본 카드와 일치하지 않습니다: {source.name}; "
                           f"metrics={metrics}; diagnostic={diagnostic}")


def export_native_layers(command_path: str, root: Path, source_project: Path, source_png: Path,
                         stem: str, page: int) -> dict[str, Any]:
    """Export each actual Tesseract layer as a transparent PNG and an authoritative manifest."""
    export_root = root / "source-layers" / f"page-{page:02d}"
    export_root.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix=f"{stem}-native-layer-", dir=root / ".tesseract-work") as temporary:
        work = Path(temporary)
        project = work / "layer-export.tsrct"
        document = _clone_for_layer_export(command_path, source_project, project, work)
        layers = document["composition"]["layers"]
        backgrounds = [layer for layer in layers if layer.get("name") == BACKGROUND_LAYER_NAME]
        if len(backgrounds) != 1:
            raise RuntimeError(f"{stem}의 네이티브 배경 레이어를 하나로 확인하지 못했습니다")
        background = backgrounds[0]
        scratch = work / "native.png"
        background_path = export_root / "background.png"
        _preview_native_layer(command_path, project, document, int(background["id"]), work, scratch)
        _write_full_rgba(scratch, background_path)
        used_names: set[str] = set()
        records: list[dict[str, Any]] = []
        # Tesseract layers[0] is frontmost. Reverse it so z_index grows bottom-to-front.
        nonbackground = [layer for layer in reversed(layers) if layer is not background]
        for index, layer in enumerate(nonbackground, start=1):
            layer_path = export_root / f"layer-{index:03d}.png"
            _preview_native_layer(command_path, project, document, int(layer["id"]), work, scratch)
            box = _write_crop(scratch, layer_path)
            if box[2] == 0 or box[3] == 0:
                # A hidden/off-canvas native layer has no drawable pixels and
                # therefore must not become a fake zero-size animation target.
                layer_path.unlink()
                continue
            record: dict[str, Any] = {
                "name": _unique_layer_name(layer.get("name"), used_names),
                "role": _native_role(layer),
                "file": layer_path.relative_to(root).as_posix(),
                "sha256": _sha256(layer_path),
                "box": box,
                "z_index": len(records),
                "moving": _moving(layer),
            }
            text = _native_text(layer)
            if text is not None:
                record["text"] = text
            records.append(record)
    manifest = {
        "version": 1,
        "source_file": source_png.name,
        "source_sha256": _sha256(source_png),
        "size": [WIDTH, HEIGHT],
        "background": {"file": background_path.relative_to(root).as_posix(),
                       "sha256": _sha256(background_path)},
        "layers": records,
        "provenance": "tesseract_native",
    }
    _verify_reconstruction(source_png, background_path, records, root)
    manifest_path = root / f"{stem}.layers.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def render(spec_path: Path, root: Path) -> list[Path]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    cards = render_cards.validate(spec)
    if root.exists():
        raise ValueError(f"이미 있는 만화 카드 출력 폴더는 덮어쓰지 않습니다: {root}")
    if not BACKGROUND.is_file():
        raise ValueError(f"카드 배경이 없습니다: {BACKGROUND}")
    root.mkdir(parents=True)
    command_path = command()
    outputs: list[Path] = []
    layout_cards: list[dict[str, Any]] = []
    for number, card in enumerate(cards, 1):
        output = make_one(command_path, root, card, number, len(cards))
        stem = output.stem
        export_native_layers(command_path, root, root / f"{stem}.tsrct", output, stem, number)
        outputs.append(output)
        layout_cards.append({"file": output.name, "layout": card["layout"], "boxes": [],
                             "layers_file": f"{stem}.layers.json", "problems": []})
    preview = render_cards.contact_sheet(root, [path.name for path in outputs])
    (root / "layout.json").write_text(json.dumps({"cards": layout_cards}, ensure_ascii=False,
                                                    indent=2) + "\n", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "spec": str(spec_path.resolve()), "size": [WIDTH, HEIGHT],
        "cards": [str(path) for path in outputs],
        "preview": str(preview),
        "background": str(BACKGROUND),
        "characters": [str(HUMAN), str(CREATURE)]},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps([str(path) for path in render(args.spec.resolve(), args.output.resolve())],
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
