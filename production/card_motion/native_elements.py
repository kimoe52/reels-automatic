#!/usr/bin/env python3
"""Layer-by-layer Tesseract motion for reviewed, flattened card-news art."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from element_layers import prepare_layers, prepare_vertical_stage
from native_focus import (CANVAS_W, FONT, LIME, MUTED, SFX, SOUNDS, Deck,
                          _text, keys, rect, run, transform)


def create_project(deck: Deck, output_root: Path, command: str) -> Path:
    if deck.renderer != "native_element_story":
        raise ValueError("요소별 제작에는 native_element_story가 필요합니다")
    project = output_root / "Element-story.tsrct"
    if output_root.exists():
        if project.is_file() and (output_root / "generated.json").is_file():
            return project
        raise ValueError(f"완성되지 않은 요소 프로젝트를 보존했습니다: {output_root}")
    build_root = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.build-",
                                       dir=output_root.parent))
    project = build_root / "Element-story.tsrct"
    work = build_root / ".tesseract-work"
    work.mkdir()
    run(command, "project", "create", "--project", str(project))
    prepared = []
    for index, page in enumerate(deck.pages, 1):
        page_dir = build_root / "Extracted" / f"page-{index:02d}"
        report = prepare_layers(page.path, page.elements, page_dir)
        stage = prepare_vertical_stage(page.path, page_dir / report["clean_plate"], page_dir)
        prepared.append((page_dir, report, stage))
        for asset_id, path in ((f"original-{index:02d}", page_dir / stage["original"]),
                               (f"plate-{index:02d}", page_dir / stage["plate"])):
            run(command, "project", "import-asset", "--project", str(project),
                "--file", str(path), "--asset-id", asset_id, "--kind", "image")
        for element_number, item in enumerate(report["elements"], 1):
            run(command, "project", "import-asset", "--project", str(project),
                "--file", str(page_dir / item["file"]),
                "--asset-id", f"element-{index:02d}-{element_number:02d}", "--kind", "image")
            if item["focus_file"]:
                run(command, "project", "import-asset", "--project", str(project),
                    "--file", str(page_dir / item["focus_file"]),
                    "--asset-id", f"focus-{index:02d}-{element_number:02d}", "--kind", "image")
    for kind, (filename, _) in SOUNDS.items():
        run(command, "project", "import-asset", "--project", str(project),
            "--file", str(SFX / filename), "--asset-id", f"sfx-{kind}", "--kind", "audio")
    body = run(command, "project", "import-font", "--project", str(project), "--file", str(FONT))
    font = (str(body["fontFamily"]), str(body["fontStyle"]))
    editable = work / "editable.json"
    run(command, "project", "checkout", "--project", str(project), "--output", str(editable))
    document = json.loads(editable.read_text(encoding="utf-8"))
    document["duration"] = deck.duration_ms / 1000
    layers = document["composition"]["layers"]
    ranges = deck.ranges()
    animation: list[dict[str, Any]] = []
    next_id = 100
    for index, (page, (start, end), (page_dir, report, stage)) in enumerate(
            zip(deck.pages, ranges, prepared), 1):
        y = stage["card_y"]
        scale = stage["card_scale"] * 100
        focuses: list[dict[str, Any]] = []
        elements: list[dict[str, Any]] = []
        full_id = next_id
        next_id += 1
        # The reading hold returns to the unchanged text/data pixels after the
        # element reveals.  Both assets share one full-frame source-matched field.
        full_start = start + 520
        original_layer = {
            "type": "Image", "id": full_id, "name": f"{index:02d} 완성 카드 원본",
            "blendMode": "normal", "activeRange": {"start": full_start, "duration": end - full_start},
            "transform": transform(0, 0),
            "source": {"assetId": f"original-{index:02d}", "fit": "contain"},
        }
        animation.append(keys(full_id, "opacity", [(0, 0), (120, 100)]))
        for element_number, item in enumerate(report["elements"], 1):
            px, py, source_w, source_h = item["box"]
            layer_x, layer_y = px * scale / 100, y + py * scale / 100
            ident = next_id
            next_id += 1
            elements.append({
                "type": "Image", "id": ident,
                "name": f"{index:02d} 요소 {element_number:02d} {item['name']}",
                "blendMode": "normal", "activeRange": {"start": start, "duration": end - start},
                "transform": transform(layer_x, layer_y, scale),
                "source": {"assetId": f"element-{index:02d}-{element_number:02d}", "fit": "contain"},
            })
            if item["repair"]:
                arrival = item["delay_ms"] + 180
                opacity = [(0, 0)]
                if item["delay_ms"]:
                    opacity.append((item["delay_ms"], 0))
                animation.append(keys(ident, "opacity", opacity + [(arrival, 100)]))
                animation.append(keys(ident, "positionY", [(0, layer_y + 9),
                                                             (arrival, layer_y)]))
            elif item["mask"] == "rounded":
                # The original panel remains visible.  Its own rounded contour
                # gets a short, sequential focus trace without hiding text.
                focus_id = next_id
                next_id += 1
                focuses.append({
                    "type": "Image", "id": focus_id,
                    "name": f"{index:02d} 정보 강조 {item['name']}",
                    "blendMode": "normal",
                    "activeRange": {"start": start, "duration": end - start},
                    "transform": transform(layer_x, layer_y, scale),
                    "source": {"assetId": f"focus-{index:02d}-{element_number:02d}",
                               "fit": "contain"},
                })
                focus_keys = [(0, 0)]
                if item["delay_ms"]:
                    focus_keys.append((item["delay_ms"], 0))
                focus_keys.extend([(item["delay_ms"] + 105, 100),
                                   (item["delay_ms"] + 460, 0)])
                animation.append(keys(focus_id, "opacity", focus_keys))
            else:
                # A graphic on textured art keeps its source pixels below;
                # only a restrained lift is safe without a hand-painted plate.
                arrival = item["delay_ms"] + 210
                opacity = [(0, 0)]
                if item["delay_ms"]:
                    opacity.append((item["delay_ms"], 0))
                animation.append(keys(ident, "opacity", opacity + [(arrival, 100)]))
                animation.append(keys(ident, "scaleX", [(0, scale * 1.025),
                                                         (arrival, scale)]))
                animation.append(keys(ident, "scaleY", [(0, scale * 1.025),
                                                         (arrival, scale)]))
        plate_layer = {
            "type": "Image", "id": next_id, "name": f"{index:02d} 분리된 배경",
            "blendMode": "normal", "activeRange": {"start": start, "duration": end - start},
            "transform": transform(0, 0),
            "source": {"assetId": f"plate-{index:02d}", "fit": "contain"},
        }
        next_id += 1
        layers.extend([*focuses, *elements, original_layer, plate_layer])
    cues = [(0, "impact", 2.1)]
    for index, (start, _) in enumerate(ranges):
        if index in {1, 3, 5, 7}:
            cues.append((start, "whoosh" if index in {1, 5} else "impact", 1.5))
    for number, (start, kind, gain) in enumerate(cues, 1):
        duration = SOUNDS[kind][1]
        layers.append({"type": "Audio", "id": next_id, "name": f"{number:02d} {kind} 효과음",
                       "playback": {"type": "windowed",
                                    "inputRange": {"start": start, "duration": duration},
                                    "mapping": {"type": "linear",
                                                "input": {"start": 0, "duration": duration},
                                                "output": {"start": 0, "duration": duration}},
                                    "inputOffsetMs": 0},
                       "sourceRange": {"start": 0, "duration": duration},
                       "sourceIntrinsicDuration": duration,
                       "source": {"assetId": f"sfx-{kind}"},
                       "volume": gain, "captionsEnabled": False})
        next_id += 1
    editable.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run(command, "project", "commit", "--project", str(project), "--file", str(editable))

    # A quiet index occupies the safe area.  The card already has its own
    # headline, so no second hook or bottom takeaway competes with the art.
    animation.append(_text(next_id, "시리즈 라벨", deck.title, 54, 94, 760, 50,
                           31, 0, deck.duration_ms, font))
    next_id += 1
    count = len(deck.pages)
    gap = 12
    bar_w = (CANVAS_W - 108 - (count - 1) * gap) / count
    for index in range(count):
        animation.append(rect(next_id, f"{index + 1:02d} 진행 배경",
                              54 + index * (bar_w + gap), 215, bar_w, 6,
                              MUTED, 0, deck.duration_ms, 3))
        next_id += 1
    for index, (start, end) in enumerate(ranges, 1):
        animation.append(_text(next_id, f"{index:02d} 페이지 번호", f"{index:02d} / {count:02d}",
                               860, 94, 170, 50, 31, start, end - start, font))
        next_id += 1
        animation.append(rect(next_id, f"{index:02d} 진행 채움",
                              54 + (index - 1) * (bar_w + gap), 215, bar_w, 6,
                              LIME, start, deck.duration_ms - start, 3))
        animation.append(keys(next_id, "scaleX", [(0, 0), (end - start - 80, 100)]))
        next_id += 1
    actions = work / "actions.json"
    actions.write_text(json.dumps(animation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run(command, "project", "apply", "--project", str(project), "--actions", str(actions))
    (build_root / "generated.json").write_text(json.dumps({
        "manifest": str(deck.manifest), "digest": deck.digest(),
        "cards": count, "duration_ms": deck.duration_ms,
        "source_images": [str(page.path) for page in deck.pages],
        "element_layers": sum(len(page.elements) for page in deck.pages),
        "clean_plates": count, "original_reading_holds": count,
        "panel_focuses": sum(item.mask == "rounded" for page in deck.pages for item in page.elements),
        "one_line_summaries": 0,
        "audio_layers": len(cues), "music_layers": 0,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(build_root, output_root)
    return output_root / "Element-story.tsrct"
