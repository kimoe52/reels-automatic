#!/usr/bin/env python3
"""Local, conservative motion planning for flattened 4:5 carousel cards.

This module deliberately analyses pixels only.  It never asks a model to
rewrite copy, and it writes small non-overlapping *meaning* regions instead of
animating arbitrary horizontal strips.  ``region`` is the preferred matte for
new plans: the renderer compares source pixels with the estimated clean plate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from element_layers import Element, _source_background
from source_layers import LayerRepairRequired, load_source_card
from motion_effects import choose_effect, duration_ms

CODE_VERSION = "auto-plan-2026-10-05.4"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

# This product uses a deliberately conservative 8.5 visible-characters-per-
# second design value, rather than a social-video length cap.  It gives viewers
# a settled, complete card before its reading window starts.
READING_CHARACTERS_PER_SECOND = 8.5
SETTLE_MS = 600
POST_READ_HOLD_MS = 1800
COVER_DEFAULT_MS = 2000


def _reading_units(texts: Iterable[str]) -> int:
    """Count visible, non-space characters without rewriting any source copy."""
    return sum(1 for text in texts for character in str(text) if not character.isspace())


def _content_paced_timing(
    reading_units: int,
    latest_reveal_ms: int,
    *,
    is_cover: bool = False,
    has_body_copy: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Return a duration only after the last element has settled and been read.

    There is deliberately no maximum duration.  A dense source card must stay
    on screen long enough to read; shortening source copy belongs in editorial
    review, not automatic motion planning.
    """
    reveal_complete_ms = max(0, int(latest_reveal_ms)) + SETTLE_MS
    # The two-second cover convention applies to a headline-only cover.  It
    # must never turn a first-page explainer into an unreadable two seconds.
    if (is_cover and not has_body_copy and reading_units <= 80
            and reveal_complete_ms <= COVER_DEFAULT_MS - 400):
        return COVER_DEFAULT_MS, {
            "policy": "cover_default_2s",
            "reading_units": reading_units,
            "reading_rate_characters_per_second": READING_CHARACTERS_PER_SECOND,
            "reading_ms": 0,
            "reveal_complete_ms": reveal_complete_ms,
            "settle_ms": SETTLE_MS,
            "hold_ms": COVER_DEFAULT_MS - reveal_complete_ms,
            "duration_explanation": "표지는 사용자 지정 기본값 2초",
        }
    reading_ms = math.ceil(max(0, reading_units) / READING_CHARACTERS_PER_SECOND * 1000)
    hold_ms = POST_READ_HOLD_MS if reading_units else max(1200, POST_READ_HOLD_MS - 400)
    duration_ms = max(3200, reveal_complete_ms + reading_ms + hold_ms)
    return duration_ms, {
        "policy": "content_reading_after_settle_v2",
        "reading_units": reading_units,
        "reading_rate_characters_per_second": READING_CHARACTERS_PER_SECOND,
        "reading_ms": reading_ms,
        "reveal_complete_ms": reveal_complete_ms,
        "settle_ms": SETTLE_MS,
        "hold_ms": hold_ms,
        "duration_explanation": "마지막 요소 정착 후 원문 읽기 시간과 홀드",
    }


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(box: list[int], width: int, height: int) -> bool:
    x, y, w, h = box
    return x >= 0 and y >= 0 and w >= 24 and h >= 24 and x + w <= width and y + h <= height


def _overlap(a: list[int], b: list[int], padding: int = 8) -> bool:
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    return ax < bx + bw + padding and ax + aw + padding > bx and ay < by + bh + padding and ay + ah + padding > by


def _components(mask: Image.Image, minimum: int) -> list[list[int]]:
    """Connected components on a small binary image, returned in source pixels."""
    pixels, width, height = mask.load(), mask.width, mask.height
    seen: set[tuple[int, int]] = set(); result: list[list[int]] = []
    for y in range(height):
        for x in range(width):
            if not pixels[x, y] or (x, y) in seen:
                continue
            queue = deque([(x, y)]); seen.add((x, y)); left = right = x; top = bottom = y; count = 0
            while queue:
                px, py = queue.popleft(); count += 1
                left = min(left, px); right = max(right, px); top = min(top, py); bottom = max(bottom, py)
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen and pixels[nx, ny]:
                        seen.add((nx, ny)); queue.append((nx, ny))
            if count >= minimum:
                result.append([left, top, right - left + 1, bottom - top + 1])
    return result


def _pixel_regions(image: Image.Image) -> tuple[list[tuple[str, list[int]]], dict[str, Any]]:
    """Find only self-contained light panels; free-form ink is unsafe to crop."""
    width, height = image.size
    scale = min(1.0, 360 / width)
    small = image.resize((round(width * scale), round(height * scale)), Image.Resampling.BILINEAR).convert("RGB")
    # Whole-image means are pulled upward by white panels; use the card's
    # corners as a field-background sample instead.
    samples = []
    for cx, cy in ((8, 8), (small.width - 9, 8), (8, small.height - 9), (small.width - 9, small.height - 9)):
        samples.extend(small.crop((max(0, cx - 5), max(0, cy - 5), min(small.width, cx + 6), min(small.height, cy + 6))).getdata())
    base = tuple(sorted(pixel[channel] for pixel in samples)[len(samples) // 2] for channel in range(3))
    panel = Image.new("1", small.size)
    pp, source = panel.load(), small.load()
    for y in range(small.height):
        for x in range(small.width):
            r, g, b = source[x, y]; distance = max(abs(r - base[0]), abs(g - base[1]), abs(b - base[2]))
            # Use relative brightness as cards can have translucent white list
            # rows; an absolute >205 test misses those completely.
            pp[x, y] = (sum((r, g, b)) / 3 > sum(base) / 3 + 24
                        and max(r, g, b) - min(r, g, b) < 92 and distance > 18)
    factor = 1 / scale
    regions: list[tuple[str, list[int]]] = []
    # Do not use 17px dilation: it bridges a character, speech bubble and
    # nearby decoration into one destructive crop.  A tiny closing operation
    # only repairs holes caused by text inside an otherwise solid panel.
    joined_panel = panel.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))
    panel_components = _components(joined_panel, 24)
    for x, y, w, h in panel_components:
        box = [round(x * factor) - 5, round(y * factor) - 5, round(w * factor) + 10, round(h * factor) + 10]
        area = w * h
        # A panel must occupy most of its rectangular bound.  This rejects
        # faces, arrows and line art that happen to be light-colored.
        coverage = sum(1 for yy in range(y, y + h) for xx in range(x, x + w) if joined_panel.getpixel((xx, yy))) / max(1, area)
        aspect = box[2] / max(1, box[3])
        if (_inside(box, width, height) and box[2] >= width * .13 and box[3] >= height * .035 and box[3] <= height * .22
                and box[2] * box[3] > width * height * .012
                and (coverage >= .90 or (aspect > 1.7 and coverage >= .72))):
            regions.append(("panel", box))
    # Repeated light rows are often step/check-list panels.  Detect their
    # individual horizontal interiors before component grouping can merge them
    # through a nearby illustration.
    row_blocks: list[list[int]] = []
    active_rows = [y for y in range(joined_panel.height)
                   if sum(1 for x in range(joined_panel.width) if joined_panel.getpixel((x, y))) >= joined_panel.width * .20]
    for y in active_rows:
        if not row_blocks or y - row_blocks[-1][1] > 4:
            row_blocks.append([y, y])
        else: row_blocks[-1][1] = y
    precise_rows: list[list[int]] = []
    for top, bottom in row_blocks:
        xs = [x for y in range(top, bottom + 1) for x in range(joined_panel.width) if joined_panel.getpixel((x, y))]
        if xs:
            candidate = [min(xs), top, max(xs) - min(xs) + 1, bottom - top + 1]
            if candidate[2] >= joined_panel.width * .28 and candidate[3] >= 10:
                precise_rows.append(candidate)
    for index in range(len(precise_rows)):
        run = [precise_rows[index]]
        for following in precise_rows[index + 1:]:
            prior = run[-1]
            if 8 <= following[1] - (prior[1] + prior[3]) <= small.height * .15 and abs(following[0] - prior[0]) < small.width * .12 and abs(following[2] - prior[2]) < small.width * .16:
                run.append(following)
            else: break
        if len(run) >= 3:
            for x, y, w, h in run:
                box = [round(x * factor) - 8, round(y * factor) - 8, round(w * factor) + 16, round(h * factor) + 16]
                if _inside(box, width, height): regions.append(("step", box))
    return regions, {"background_rgb": base, "scale": scale, "panel_components": len(panel_components), "accepted_panels": len(regions)}


def _ink_bands(image: Image.Image, x_start: int = 0, x_end: int | None = None) -> list[tuple[int, int, int, int, int]]:
    """Return whitespace-separated dark text bands without joining them in 2-D."""
    width, height = image.size; x_end = width if x_end is None else x_end; pixels = image.load(); dark = [[min(pixels[x, y]) < 100 for x in range(width)] for y in range(height)]
    # Closed panel borders and character outlines create uninterrupted vertical
    # ink columns.  Suppress those columns so text-row projection finds the
    # whitespace valleys between list items instead of one giant component.
    vertical: set[tuple[int, int]] = set()
    for x in range(width):
        start = None
        for y in range(height + 1):
            active = y < height and dark[y][x]
            if active and start is None: start = y
            if not active and start is not None:
                if y - start >= 48:
                    vertical.update((x, yy) for yy in range(start, y))
                start = None
    rows: list[list[int]] = []
    for y in range(height):
        xs = [x for x in range(x_start, x_end) if dark[y][x] and (x, y) not in vertical]
        rows.append(xs)
    active = [y for y, xs in enumerate(rows) if len(xs) >= max(4, width // 350)]
    bands: list[tuple[int, int, int, int, int]] = []
    for y in active:
        if not bands or y - bands[-1][1] > 12:
            bands.append((y, y, min(rows[y]), max(rows[y]), len(rows[y])))
        else:
            top, _, left, right, amount = bands[-1]
            bands[-1] = (top, y, min(left, min(rows[y])), max(right, max(rows[y])), amount + len(rows[y]))
    return bands


def _safe_ink_regions(image: Image.Image) -> list[tuple[str, list[int], str]]:
    """A complete title block and repeated list rows; never individual words."""
    width, height = image.size; bands = _ink_bands(image, round(width * .12), round(width * .88)); result: list[tuple[str, list[int], str]] = []
    # The headline area is a reliable semantic boundary.  Taking all dark ink
    # only inside it preserves multi-line lettering while excluding characters
    # and bubbles further down the illustration.
    # Find the first dark glyph band and stop at its first true whitespace
    # valley.  This is content-derived, unlike a fixed title height, and keeps
    # every title line while stopping before the first subtitle/panel.
    row_counts = [sum(min(image.getpixel((x, y))) < 100 for x in range(width)) for y in range(height)]
    start = next((y for y in range(12, height) if row_counts[y] >= 8), None)
    end = None
    if start is not None:
        quiet = 0
        for y in range(start, height):
            quiet = quiet + 1 if row_counts[y] == 0 else 0
            if quiet >= 7:
                end = y - quiet
                break
    headline = ([(x, y) for y in range(start or 0, (end or 0) + 1) for x in range(width)
                 if min(image.getpixel((x, y))) < 100] if start is not None and end is not None else [])
    if headline:
        left, right = min(x for x, _ in headline), max(x for x, _ in headline)
        top, bottom = min(y for _, y in headline), max(y for _, y in headline)
        if right - left > width * .18:
            x = max(0, left - 20); y = max(0, top - 18)
            result.append(("title", [x, y, min(width, right + 13) - x, min(height, bottom + 13) - y], ""))
    # Repeated horizontal text bands reliably mean step/check-list items.  Do
    # not animate a singleton bubble or illustration whose boundary is unclear.
    candidates = [band for band in bands if band[0] > height * .16 and 12 <= band[1] - band[0] <= height * .16 and band[3] - band[2] > width * .25]
    runs: list[list[tuple[int, int, int, int, int]]] = []
    for band in candidates:
        if runs and 8 <= band[0] - runs[-1][-1][1] <= height * .18 and abs(band[2] - runs[-1][-1][2]) < width * .20:
            runs[-1].append(band)
        else: runs.append([band])
    for run in runs:
        if len(run) < 3: continue
        for top, bottom, left, right, _ in run:
            x = max(0, left - 34); y = max(0, top - 18)
            result.append(("step", [x, y, min(width, right + 35) - x, min(height, bottom + 19) - y], ""))
    return result


def _ocr(image_path: Path, size: tuple[int, int]) -> tuple[list[tuple[str, list[int]]], dict[str, Any]]:
    binary = "/opt/homebrew/bin/tesseract"
    command = binary if Path(binary).is_file() else shutil.which("tesseract")
    if not command:
        return [], {"available": False, "reason": "tesseract_not_found"}
    try:
        completed = subprocess.run([command, str(image_path), "stdout", "-l", "kor+eng", "--psm", "11", "tsv"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], {"available": True, "reason": type(exc).__name__}
    if completed.returncode:
        return [], {"available": True, "reason": "ocr_failed"}
    lines: dict[tuple[str, str, str], list[tuple[str, list[int]]]] = {}
    for row in completed.stdout.splitlines()[1:]:
        fields = row.split("\t")
        if len(fields) < 12 or not fields[11].strip():
            continue
        try:
            x, y, w, h, confidence = map(float, (fields[6], fields[7], fields[8], fields[9], fields[10]))
        except ValueError:
            continue
        # OCR is reading-time evidence, not a crop proposal. Small body words
        # still count even though they are too small to animate independently.
        if (confidence >= 20 and x >= 0 and y >= 0 and w > 0 and h > 0
                and x + w <= size[0] and y + h <= size[1]):
            key = (fields[2], fields[3], fields[4])  # block, paragraph, line
            lines.setdefault(key, []).append((fields[11].strip(), [int(x), int(y), int(w), int(h)]))
    groups: list[tuple[str, list[int]]] = []
    for words in lines.values():
        words.sort(key=lambda item: item[1][0]); left = min(box[0] for _, box in words); top = min(box[1] for _, box in words)
        right = max(box[0] + box[2] for _, box in words); bottom = max(box[1] + box[3] for _, box in words)
        groups.append((" ".join(text for text, _ in words), [left, top, right - left, bottom - top]))
    padded = [(text, [max(0, x - 10), max(0, y - 10), min(size[0] - max(0, x - 10), w + 20), min(size[1] - max(0, y - 10), h + 20)]) for text, (x, y, w, h) in groups]
    return padded, {"available": True, "words": sum(len(value) for value in lines.values()), "groups": len(groups)}


def _tight_source_box(image_path: Path, name: str, box: list[int]) -> list[int]:
    """Trim only proven transparent margins, never estimate character pixels."""
    background = _source_background(image_path, Element(name, tuple(box), "region", 0))
    if background is None:
        return box
    x, y, w, h = box
    with Image.open(image_path) as opened:
        crop = opened.convert("RGB").crop((x, y, x + w, y + h))
    channels = ImageChops.difference(crop, background).split()
    difference = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    bounds = difference.point(lambda value: 255 if value > 2 else 0).getbbox()
    if bounds is None:
        return box
    left, top, right, bottom = bounds
    left, top = max(0, left - 2), max(0, top - 2)
    right, bottom = min(w, right + 2), min(h, bottom + 2)
    return [x + left, y + top, right - left, bottom - top]


def _layout_regions(manifest: Path, image_path: Path, size: tuple[int, int], supplied: Any = None, supplied_sha: str = "") -> list[tuple[str, list[int]]]:
    """Use card-render DOM boxes first when a co-located layout file exists."""
    if isinstance(supplied, list):
        direct = []
        image_sha = _sha(image_path)
        for item in supplied:
            box = item.get("box") if isinstance(item, dict) else None
            # Unbound boxes may belong to a previous render of the same file
            # name. Auto planning must never reuse them on changed pixels.
            item_sha = item.get("source_sha256") if isinstance(item, dict) else None
            if (item_sha or supplied_sha) != image_sha:
                continue
            if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                exact = [round(box[0]), round(box[1]), round(box[2] - box[0]), round(box[3] - box[1])]
                name = str(item.get("name") or "DOM 영역")
                if _inside(exact, *size):
                    direct.append((name, _tight_source_box(image_path, name, exact)))
        if direct: return direct
    candidates = [image_path.parent / "layout.json", manifest.parent / "card-render" / "cards" / "layout.json", manifest.parent / "cards" / "layout.json"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        found: list[tuple[str, list[int]]] = []; image_sha = _sha(image_path)
        # card-render/layout.json is a deck document.  Using every page's
        # boxes for one bitmap would produce duplicated, unrelated regions.
        document_cards = data.get("cards") if isinstance(data, dict) else None
        if isinstance(document_cards, list):
            image_number = re.match(r"(?:card[-_])?0*(\d+)", image_path.stem, re.I)
            matching = [item for item in document_cards if isinstance(item, dict)
                        and Path(str(item.get("file") or "")).name == image_path.name]
            if not matching and image_number:
                # Imported cards are commonly named card-01 while renderer
                # output is 01-cover.  Match that stable page ordinal only.
                ordinal = int(image_number.group(1))
                matching = [item for item in document_cards if isinstance(item, dict)
                            and (match := re.match(r"0*(\d+)", Path(str(item.get("file") or "")).stem))
                            and int(match.group(1)) == ordinal]
            if not matching:
                continue
            data = matching[0]
        if isinstance(data, dict) and data.get("source_sha256") and data["source_sha256"] != image_sha:
            continue
        def visit(value: Any, hint: str = "layout") -> None:
            if isinstance(value, dict):
                name = str(value.get("name") or value.get("id") or value.get("role") or hint)
                box = value.get("box")
                if value.get("source_sha256") and value["source_sha256"] != image_sha:
                    return
                if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                    left, top, right, bottom = box
                    # DOM coordinates are already the exact source-card pixels.
                    # Never pad, rename, or scale a trusted renderer box.
                    candidate = [round(left), round(top), round(right - left), round(bottom - top)]
                    if _inside(candidate, *size):
                        found.append((name, _tight_source_box(image_path, name, candidate)))
                for key, child in value.items(): visit(child, key)
            elif isinstance(value, list):
                for child in value: visit(child, hint)
        visit(data)
        if found: return found
    return []


def _label(kind: str, index: int, text: str = "") -> str:
    text = " ".join(text.split())[:24]
    return text or {"title": "제목", "panel": "비교 패널", "text": "문구", "layout": "구성 영역"}.get(kind, "의미 영역") + f" {index}"


def _proof(image_path: Path, elements: list[dict[str, Any]], destination: Path) -> None:
    with Image.open(image_path) as original:
        proof = original.convert("RGB")
    draw = ImageDraw.Draw(proof)
    for index, element in enumerate(elements, 1):
        x, y, w, h = element["box"]
        draw.rounded_rectangle((x, y, x + w, y + h), radius=8, outline=(255, 82, 112), width=4)
        draw.rectangle((x, max(0, y - 28), min(proof.width, x + 34), y), fill=(255, 82, 112))
        draw.text((x + 4, max(0, y - 26)), str(index), fill="white")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp.png")
    proof.save(temporary, "PNG"); os.replace(temporary, destination)


def _input_signature(manifest: Path, cards: list[Any]) -> str:
    digest = hashlib.sha256(_sha(Path(__file__)).encode())
    digest.update(_sha(Path(__file__).with_name("element_layers.py")).encode())
    digest.update(_sha(Path(__file__).with_name("source_layers.py")).encode())
    digest.update(_sha(Path(__file__).with_name("flat_layers.py")).encode())
    digest.update(_sha(Path(__file__).with_name("motion_effects.py")).encode())
    root = manifest.parent.resolve()
    for card in cards:
        if not isinstance(card, dict): continue
        relative = Path(str(card.get("file") or "")); source = (root / relative).resolve()
        try: contained = source.is_relative_to(root)
        except AttributeError: contained = str(source).startswith(str(root) + os.sep)
        if not relative.is_absolute() and ".." not in relative.parts and contained and source.is_file():
            digest.update(_sha(source).encode())
            layers_file = card.get("layers_file")
            if isinstance(layers_file, str):
                layers = (root / layers_file).resolve()
                if layers.is_relative_to(root) and layers.is_file():
                    digest.update(_sha(layers).encode())
                    try:
                        metadata = json.loads(layers.read_text(encoding="utf-8"))
                        background = metadata.get("background", {})
                        for record in [background, *metadata.get("layers", [])]:
                            if isinstance(record, dict) and isinstance(record.get("file"), str):
                                asset = (layers.parent / record["file"]).resolve()
                                if asset.is_relative_to(layers.parent.resolve()) and asset.is_file():
                                    digest.update(_sha(asset).encode())
                    except (OSError, json.JSONDecodeError, TypeError):
                        digest.update(b"invalid-source-layers")
            layout = source.parent / "layout.json"
            if layout.is_file(): digest.update(_sha(layout).encode())
        digest.update(json.dumps(card.get("boxes"), sort_keys=True).encode())
    for layout in (root / "card-render" / "cards" / "layout.json", root / "cards" / "layout.json"):
        if layout.is_file(): digest.update(_sha(layout).encode())
    return digest.hexdigest()


def plan_signature(cards: list[Any]) -> str:
    """Detect manual edits to an auto-authored plan before regenerating it."""
    values = [{key: card.get(key) for key in
               ("motion_elements", "duration_ms", "motion_timing")}
              for card in cards if isinstance(card, dict)]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _complete_boundary(image: Image.Image, box: list[int]) -> bool:
    """Reject a crop that intersects a dark stroke/face/glyph at its border."""
    x, y, w, h = box
    pixels = image.load()
    def dark(color: tuple[int, int, int]) -> bool:
        # Violet connectors can cross a panel's bounding rectangle without
        # cutting a face or glyph. Their boundary-connected pixels remain on
        # the clean plate rather than being moved with the panel.
        return max(color) < 145
    lines = (
        [dark(pixels[sx, y]) for sx in range(x, x + w)],
        [dark(pixels[sx, y + h - 1]) for sx in range(x, x + w)],
        [dark(pixels[x, sy]) for sy in range(y, y + h)],
        [dark(pixels[x + w - 1, sy]) for sy in range(y, y + h)],
    )
    for line in lines:
        run = 0
        for dark in line:
            run = run + 1 if dark else 0
            if run >= 3:
                return False
    return True


def analyse_card(image_path: Path, manifest: Path, supplied_boxes: Any = None, supplied_sha: str = "") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    if abs(width / height - .8) > .02:
        raise ValueError(f"카드 이미지가 4:5 비율이 아닙니다: {image_path.name} ({width}×{height})")
    layout = _layout_regions(manifest, image_path, image.size, supplied_boxes, supplied_sha)
    ocr, ocr_meta = _ocr(image_path, image.size)
    pixels, pixel_meta = _pixel_regions(image)
    safe_title = [item for item in _safe_ink_regions(image) if item[0] == "title"]
    candidates: list[tuple[str, list[int], str]] = []
    candidates += [("layout", box, name) for name, box in layout]
    # TSV is useful metadata, but inaccurate Korean OCR must not turn every
    # word into a moving crop.  Only whole line/block groups are considered.
    # OCR remains diagnostic metadata.  It may be used by a future renderer
    # review UI, but never produces an automatic crop on its own.
    # Repeated-row inference stays diagnostic until a panel outline confirms
    # it.  Moving an incomplete line is worse than keeping that line static.
    if not layout:
        candidates += safe_title
        candidates += [(kind, box, "") for kind, box in pixels if kind == "panel"]
    chosen: list[tuple[str, list[int], str]] = []
    # Give title, panels, and illustrations/ink clusters a chance before filling slots.
    for kind, box, text in sorted(candidates, key=lambda it: ({"layout": 0, "title": 1, "panel": 2, "step": 3, "ocr_line": 4}.get(it[0], 5), -it[1][2] * it[1][3])):
        if len(chosen) == 24 or not _inside(box, width, height) or any(_overlap(box, other[1], 0) for other in chosen):
            continue
        if kind != "layout" and not _complete_boundary(image, box):
            # Light-component bounds end inside the enclosing stroke. Expand
            # a few pixels to include its actual outline, never clip a glyph.
            complete = None
            if kind == "panel":
                x, y, w, h = box
                for pad in (4, 8, 12, 16):
                    expanded = [x - pad, y - pad, w + 2 * pad, h + 2 * pad]
                    if (_inside(expanded, width, height)
                            and _complete_boundary(image, expanded)
                            and not any(_overlap(expanded, other[1], 0) for other in chosen)):
                        complete = expanded
                        break
            if complete is None:
                continue
            box = complete
        # Reject the historical failure mode: a shallow full-card-width strip not tied to OCR/DOM.
        if kind not in {"title", "layout"} and box[2] > width * .91 and box[3] < height * .16:
            continue
        chosen.append((kind, box, text))
    elements: list[dict[str, Any]] = []
    for index, (kind, box, text) in enumerate(sorted(chosen, key=lambda item: (item[1][1], item[1][0])), 1):
        role = kind
        if kind == "layout":
            name = text.lower()
            role = ("title" if name == "title" else "illustration" if name == "art"
                    else "panel" if name.startswith(("step", "flow", "item", "panel", "grid"))
                    else "text")
        elements.append({"name": _label(kind, index, text), "box": box, "mask": "region", "delay_ms": min(5000, (index - 1) * 120), "radius": 0, "repair": True,
                         "role": role, "effect": "settle_fade" if role == "title" else "rise_fade"})
    reading_units = _reading_units(text for text, _ in ocr)
    latest = max((item["delay_ms"] for item in elements), default=0)
    duration, timing = _content_paced_timing(reading_units, latest)
    report = {"file": str(image_path), "sha256": _sha(image_path), "size": [width, height], "layout_regions": len(layout), "ocr": ocr_meta, "has_body_copy": any(text.strip() and box[1] >= height * .23 for text, box in ocr), "pixel": pixel_meta, "elements": len(elements), "remaining_static": ["Free-form illustration, speech bubbles, or OCR fragments without a closed boundary were intentionally preserved in the original card."], "diagnostics": ([] if elements else ["No reliable non-overlapping semantic regions; card kept unchanged."]), "duration_ms": duration, "timing": timing}
    return elements, report


def plan_package(manifest: Path, force: bool = False) -> Path:
    """Populate a source-approved auto plan and save its analysis beside it.

    ``force`` is intentionally limited to a prior auto plan.  A reviewed plan
    with authored elements is a human asset and is never changed.
    """
    manifest = manifest.resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    cards = data.get("cards")
    if not isinstance(cards, list): raise ValueError("manifest cards must be a list")
    manual = any(isinstance(card, dict) and card.get("motion_elements") for card in cards)
    auto = isinstance(data.get("motion_plan"), dict) and data["motion_plan"].get("generator") == "auto_plan"
    authored_signature = data.get("motion_plan", {}).get("plan_signature")
    if auto and authored_signature and authored_signature != plan_signature(cards):
        # A person changed the automatic plan. Keep those edits even when
        # source/layout/code inputs changed; --force must not erase them.
        return manifest
    signature = _input_signature(manifest, cards)
    if manual and not auto: return manifest
    if (manual and auto and not force
            and data["motion_plan"].get("input_signature") == signature
            and data["motion_plan"].get("code_version") == CODE_VERSION):
        return manifest
    if force and manual and not auto:
        raise ValueError("--force only regenerates a previous auto plan; manual plan preserved")
    reports = []; changed = False
    for number, card in enumerate(cards, 1):
        if not isinstance(card, dict): continue
        relative = Path(str(card.get("file") or ""))
        source = (manifest.parent / relative).resolve()
        try:
            source.relative_to(manifest.parent.resolve())
            contained = True
        except ValueError:
            contained = False
        if relative.is_absolute() or ".." in relative.parts or not contained or not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
            card["motion_elements"] = []
            card["analysis_status"] = "needs_review"
            changed = True
            reports.append({"card": number, "skipped": "missing_or_unsafe_source", "file": str(relative)})
            continue
        declared_sha = card.get("source_sha256")
        if declared_sha and declared_sha != _sha(source):
            raise ValueError(f"{number}장 이미지가 승인된 원본과 다릅니다")
        if data.get("source_approved") is True and not declared_sha:
            card["source_sha256"] = _sha(source)
        ocr_reading_units: int | None = None
        if data.get("source_kind") == "flat_images":
            from flat_layers import export_flat_layers
            with Image.open(source) as opened:
                ocr, ocr_meta = _ocr(source, opened.size)
            ocr_reading_units = _reading_units(text for text, _ in ocr)
            layer_path = export_flat_layers(source, ocr, ocr_meta)
            card["layers_file"] = str(layer_path.relative_to(manifest.parent))
            card["source_layers_sha256"] = _sha(layer_path)
        elif not card.get("layers_file"):
            raise LayerRepairRequired(f"{number}장 원본 레이어가 없어 복구가 필요합니다")
        if card.get("layers_file"):
            layer_relative = Path(str(card["layers_file"]))
            layer_path = (manifest.parent / layer_relative).resolve()
            if (layer_relative.is_absolute() or ".." in layer_relative.parts
                    or not layer_path.is_relative_to(manifest.parent.resolve())):
                raise ValueError(f"{number}장 원본 레이어 경로가 제작 폴더 밖입니다")
            source_card = load_source_card(layer_path, source,
                                           card.get("source_layers_sha256"))
            elements = [{"name": item.name, "box": list(item.box), "mask": "source", "delay_ms": item.delay_ms,
                         "radius": 0, "repair": True, "role": item.role, "effect": item.effect}
                        for item in source_card.elements()]
            # Do not copy the approved stock deck's coordinates/effect count.
            # Every object's own geometry/role determines a rigid-body effect.
            if data.get("source_kind") == "flat_images":
                groups = {}
                for layer in source_card.layers:
                    if layer["moving"]:
                        group = layer.get("motion_group",layer["name"])
                        if group not in groups or (layer["role"] == "character" and
                                                   groups[group]["role"] != "character"):
                            groups[group] = layer
                ordered = sorted(groups,key=lambda name:(groups[name]["box"][1],groups[name]["box"][0]))
                delays = {name:round(index*850/max(1,len(ordered)-1)) for index,name in enumerate(ordered)}
                by_name = {layer["name"]:layer for layer in source_card.layers}
                for item in elements:
                    layer = by_name[item["name"]]
                    group = layer.get("motion_group",layer["name"])
                    parent = groups[group]
                    role = parent["role"]
                    item["delay_ms"] = 0 if role == "title" else delays[group]
                    item["effect"] = choose_effect(role, parent["box"], source_card.size,
                                                   number, ordered.index(group))
            else:
                # Producer-exported layers can use the same safe catalog.
                # Existing hand-authored motion plans are preserved above.
                for index, item in enumerate(elements):
                    item["effect"] = choose_effect(item["role"], item["box"], source_card.size,
                                                   number, index)
            if ocr_reading_units is None:
                with Image.open(source) as opened:
                    source_ocr, _ = _ocr(source, opened.size)
                ocr_reading_units = _reading_units(text for text, _ in source_ocr)
            # OCR validates that every visible word gets time.  Source-layer
            # text is retained as a second, exact extraction path.  Choose
            # the fuller evidence rather than counting the same words twice.
            reading_groups = {}
            for layer in source_card.layers:
                reading_groups.setdefault(layer.get("reading_group",layer["name"]),
                                          str(layer.get("text") or ""))
            layer_reading_units = _reading_units(reading_groups.values())
            reading_units = max(ocr_reading_units, layer_reading_units)
            latest_delay = max((item["delay_ms"] for item in elements), default=0)
            duration, timing = _content_paced_timing(
                reading_units, latest_delay, is_cover=(number == 1),
                has_body_copy=any(str(layer.get("text") or "").strip()
                                  and layer["role"] in {"text", "bubble", "panel"}
                                  for layer in source_card.layers),
            )
            report = {"file": str(source), "sha256": _sha(source), "card": number,
                      "source_layers": True, "elements": len(elements), "duration_ms": duration,
                      "timing": timing}
        else:
            elements, report = analyse_card(source, manifest, card.get("boxes"), str(card.get("source_sha256") or "")); report["card"] = number
            if number == 1:
                latest_delay = max((item["delay_ms"] for item in elements), default=0)
                duration, timing = _content_paced_timing(
                    int(report["timing"].get("reading_units", 0)), latest_delay, is_cover=True,
                    has_body_copy=report["has_body_copy"],
                )
                report["duration_ms"] = duration
                report["timing"] = timing
        proof = manifest.parent / "motion-analysis-proofs" / f"card-{number:02d}.png"
        _proof(source, elements, proof)
        report["proof"] = str(proof.relative_to(manifest.parent))
        reports.append(report)
        if not elements:
            # Never leave an earlier auto plan alive when fresh analysis cannot
            # prove a safe region.  Renderers/pipelines can reject this state.
            card["motion_elements"] = []; card["analysis_status"] = "static_preserved"
            card["duration_ms"] = report["duration_ms"]
            card["motion_timing"] = report["timing"]
            changed = True
            continue
        card["motion_elements"] = elements; card["analysis_status"] = "auto_planned"; card["duration_ms"] = report["duration_ms"]; card["motion_timing"] = report["timing"]; changed = True
    report_doc = {"generator": "auto_plan", "code_version": CODE_VERSION, "manifest": str(manifest), "cards": reports, "diagnostics": ["OCR and pixel grouping are conservative; inspect cards with no detected regions before rendering."]}
    _atomic_json(manifest.parent / "motion-analysis.json", report_doc)
    if changed:
        data.setdefault("version", 4); data.setdefault("renderer", "hyperframes_element_story"); data.setdefault("audio_decision", "sfx_only")
        data["timing_policy"] = "auto_content_reading_after_settle_v2"; data["motion_analysis_status"] = ("needs_review" if any(card.get("analysis_status") == "needs_review" for card in cards if isinstance(card, dict)) else "auto_planned"); data["motion_plan"] = {"generator": "auto_plan", "code_version": CODE_VERSION, "input_signature": _input_signature(manifest, cards), "plan_signature": plan_signature(cards), "motion_review_required": True}
        # Preserve source review state. An import is explicitly user-supplied and can set it.
        _atomic_json(manifest, data)
    return manifest


def import_images(images: Iterable[Path], output: Path, title: str) -> Path:
    output = output.resolve(); image_list = [Path(item).resolve() for item in images]
    if not 4 <= len(image_list) <= 12: raise ValueError("4~12 images are required")
    if output.exists() and any(output.iterdir()): raise ValueError(f"output already exists: {output}")
    inputs = output / "Inputs"; inputs.mkdir(parents=True, exist_ok=True); cards = []
    for index, source in enumerate(image_list, 1):
        if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES: raise ValueError(f"invalid image: {source}")
        target = inputs / f"card-{index:02d}{source.suffix.lower()}"; shutil.copy2(source, target)
        cards.append({"file": str(target.relative_to(output)), "source_sha256": _sha(target)})
    manifest = output / "reel-production.json"
    _atomic_json(manifest, {"version": 4, "renderer": "hyperframes_element_story", "reviewed": True, "source_approved": True, "source_kind":"flat_images", "motion_review_required": True, "deck_title": title[:24] or "카드 영상", "audio_decision": "sfx_only", "cards": cards})
    return plan_package(manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan conservative local card motion")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--force", action="store_true")
    parser.add_argument("--import-images", type=Path, nargs="+"); parser.add_argument("--output", type=Path); parser.add_argument("--title", default="카드 영상")
    args = parser.parse_args()
    if args.import_images and not args.output:
        parser.error("--import-images requires --output")
    if not args.import_images and not args.manifest:
        parser.error("--manifest or --import-images is required")
    if args.import_images and args.manifest:
        parser.error("choose --manifest or --import-images, not both")
    result = import_images(args.import_images, args.output, args.title) if args.import_images else plan_package(args.manifest, args.force)
    print(result); return 0

if __name__ == "__main__": raise SystemExit(main())
