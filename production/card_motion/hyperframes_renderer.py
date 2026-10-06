#!/usr/bin/env python3
"""Generate a reusable HyperFrames composition from reviewed card-news art."""

from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from element_layers import prepare_layers, prepare_vertical_stage
from source_layers import prepare_source_layers
from motion_effects import duration_ms
from PIL import Image
from native_focus import CANVAS_H, CANVAS_W, FONT, SFX, SOUNDS, Deck


HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "hyperframes_runtime"
CLI = RUNTIME / "node_modules" / ".bin" / "hyperframes"
GSAP = RUNTIME / "node_modules" / "gsap" / "dist" / "gsap.min.js"
TEMPLATE = HERE / "hyperframes_template.html"


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def _image(asset: str, identifier: str, class_name: str, style: str = "") -> str:
    return (f'<img id="{identifier}" class="{class_name}" '
            f'src="{html.escape(asset, quote=True)}" alt="" '
            f'style="{html.escape(style, quote=True)}">')


def _effect(item: dict, width: int) -> str:
    """Purposeful, geometry-safe motion; authored legacy plans remain unchanged."""
    if item["mask"] != "region":
        return item.get("effect") or ""
    role = item.get("role")
    x, _, w, _ = item["box"]
    name = item["name"].lower()
    if role == "title":
        return "settle_fade"
    if any(word in name for word in ("arrow", "화살", "graph", "그래프")):
        return "reveal"
    if role == "panel" and w < width * .58:
        return "slide_left" if x + w / 2 < width / 2 else "slide_right"
    if role in {"illustration", "art"}:
        return "scale_pop"
    return item.get("effect") or "rise_fade"


def create_project(deck: Deck, output_root: Path) -> Path:
    """Build a self-contained HTML project; never overwrite another render."""
    if deck.renderer != "hyperframes_element_story":
        raise ValueError("HyperFrames 제작에는 hyperframes_element_story가 필요합니다")
    project = output_root / "index.html"
    if output_root.exists():
        marker = output_root / "generated.json"
        if project.is_file() and marker.is_file():
            data = json.loads(marker.read_text(encoding="utf-8"))
            if data.get("digest") == deck.digest():
                return project
        raise ValueError(f"완성되지 않았거나 해시가 다른 HyperFrames 프로젝트를 보존했습니다: {output_root}")
    if not GSAP.is_file() or not CLI.is_file():
        raise RuntimeError(f"HyperFrames가 설치되지 않았습니다: {RUNTIME}")
    if not TEMPLATE.is_file():
        raise RuntimeError(f"HyperFrames 템플릿이 없습니다: {TEMPLATE}")
    panel_repair = deck.data.get("hyperframes_panel_repair", False)
    automatic = deck.data.get("motion_plan", {}).get("generator") == "auto_plan"
    flat_pixels = deck.data.get("source_kind") == "flat_images"
    if type(panel_repair) is not bool:
        raise ValueError("hyperframes_panel_repair는 참/거짓이어야 합니다")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    build_root = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.build-",
                                       dir=output_root.parent))
    try:
        assets = build_root / "assets"
        assets.mkdir()
        shutil.copy2(GSAP, assets / "gsap.min.js")
        shutil.copy2(HERE / "motion_effects.js", assets / "motion_effects.js")
        shutil.copy2(FONT, assets / "PretendardVariable.ttf")
        scenes = []
        plan = []
        page_backgrounds = []
        ranges = deck.ranges()
        for number, (page, (start_ms, end_ms)) in enumerate(zip(deck.pages, ranges), 1):
            page_dir = assets / f"page-{number:02d}"
            elements = (tuple(replace(item, repair=True) if panel_repair else item
                              for item in page.elements))
            report = (prepare_source_layers(page.source_card, elements, page_dir)
                      if page.source_card else prepare_layers(page.path, elements, page_dir))
            # Producer/flat layer packages can carry an authoritative blank
            # background.  Prefer it to the flattened card so foreground
            # pixels can never leak into the 9:16 background/theme profile.
            background_source = (page.source_card.background if page.source_card
                                 else page_dir / report["clean_plate"])
            stage = prepare_vertical_stage(page.path, background_source, page_dir,
                                           fade_bottom=not automatic)
            scale = stage["card_scale"]
            base = f"assets/page-{number:02d}"
            scene_id = f"scene-{number:02d}"
            theme = stage["theme"]
            start = max(0, start_ms - (80 if number > 1 else 0))
            duration = end_ms - start
            image_parts = [
                _image(f"{base}/{stage['plate']}", f"plate-{number:02d}", "stage-plate"),
            ]
            moving = []
            backdrops = []
            focuses = []
            focus_parts = []
            groups = {}
            if flat_pixels:
                for index, item in enumerate(report["elements"], 1):
                    if item.get("moving", item["repair"]) and item["repair"]:
                        groups.setdefault(item.get("motion_group", item["name"]), []).append((index, item))
            emitted = set()
            for index, item in enumerate(report["elements"], 1):
                group = item.get("motion_group", item["name"])
                if flat_pixels and group in groups:
                    if group in emitted:
                        continue
                    emitted.add(group)
                    members = groups[group]
                    schedules = {(child["delay_ms"], child.get("effect", "")) for _, child in members}
                    if len(schedules) != 1:
                        raise ValueError("같은 원본 요소의 그림·글자 모션이 서로 다릅니다")
                    left = min(child["box"][0] for _, child in members)
                    top = min(child["box"][1] for _, child in members)
                    right = max(child["box"][0]+child["box"][2] for _, child in members)
                    bottom = max(child["box"][1]+child["box"][3] for _, child in members)
                    # Compose disjoint original-pixel pieces BEFORE browser
                    # scaling. Independently resampled alpha edges can leave
                    # seams through a glyph/face even inside one rigid div.
                    raster=Image.new("RGBA",(right-left,bottom-top))
                    for _, child in sorted(members,key=lambda member:member[1]["z_index"]):
                        cx, cy, cw, ch = child["box"]
                        with Image.open(page_dir/child["file"]) as opened:
                            raster.alpha_composite(opened.convert("RGBA"),(cx-left,cy-top))
                    filename=f"rigid-group-{index:03d}.png"
                    raster.save(page_dir/filename)
                    piece=_image(f"{base}/{filename}",f"piece-{number:02d}-{index:02d}",
                                 "source-piece","left:0;top:0;width:100%;height:100%")
                    element_id = f"group-{number:02d}-{index:02d}"
                    style = (f"left:{left*scale:.2f}px;top:{stage['card_y']+top*scale:.2f}px;"
                             f"width:{(right-left)*scale:.2f}px;height:{(bottom-top)*scale:.2f}px")
                    image_parts.append(f'<div id="{element_id}" class="moving-element motion-group" '
                                       f'style="{style}">' + piece + '</div>')
                    effect = _effect(item, page.size[0])
                    moving.append({"id":element_id,"delay":item["delay_ms"]/1000,
                                   "mask":item["mask"],"role":item.get("role",""),
                                   "effect":effect,"duration_ms":duration_ms(effect)})
                    continue
                x, y, width, height = item["box"]
                style = (f"left:{x * scale:.2f}px;top:{stage['card_y'] + y * scale:.2f}px;"
                         f"width:{width * scale:.2f}px;height:{height * scale:.2f}px")
                if not item.get("moving", item["repair"]):
                    static_id = f"static-{number:02d}-{index:02d}"
                    image_parts.append(_image(f"{base}/{item['file']}", static_id,
                                              "moving-element static-source", style))
                    if item.get("reveal_after_motion"):
                        backdrops.append(static_id)
                elif item["repair"]:
                    element_id = f"element-{number:02d}-{index:02d}"
                    image_parts.append(_image(f"{base}/{item['file']}", element_id,
                                              "moving-element", style))
                    moving.append({"id": element_id, "delay": item["delay_ms"] / 1000,
                                   "mask": item["mask"], "role": item.get("role", ""),
                                   "effect": _effect(item, page.size[0]),
                                   "duration_ms": duration_ms(_effect(item, page.size[0]))})
                elif item["focus_file"]:
                    focus_id = f"focus-{number:02d}-{index:02d}"
                    focus_parts.append(_image(f"{base}/{item['focus_file']}", focus_id,
                                              "focus-ring", style))
                    focuses.append({"id": focus_id, "delay": item["delay_ms"] / 1000})
            original_hold_at = max(0.68, max((item["delay"]+item["duration_ms"]/1000
                                            for item in moving), default=0) + 0.06)
            minimum_hold = .4 if number == 1 and page.duration_ms == 2000 else .8
            if original_hold_at + minimum_hold > page.duration_ms / 1000:
                raise ValueError(f"{number}장 모션 뒤 원본을 읽을 시간이 부족합니다")
            if not flat_pixels:
                image_parts.append(_image(f"{base}/{stage['original']}",
                                          f"original-{number:02d}", "original-hold"))
            image_parts.extend(focus_parts)
            progress = "".join(
                f'<span class="progress-segment {"done" if tick < number else ""}">'
                f'{f"<i id=progress-{number:02d}></i>" if tick == number else ""}'
                "</span>"
                for tick in range(1, len(deck.pages) + 1)
            )
            scene = (
                f'<section id="{scene_id}" class="clip scene" '
                f'data-start="{_seconds(start)}" data-duration="{_seconds(duration)}" '
                f'data-track-index="0" style="--scene-field:{theme["field"]};'
                f'--header-ink:{theme["ink"]};--progress-track:{theme["progress_track"]};'
                f'--progress-active:{theme["progress_active"]}">'
                + _image(f"{base}/{stage['background']}", f"background-{number:02d}", "scene-background")
                + '<div class="camera">' + "".join(image_parts) + '</div>'
                + '<header class="series-header">'
                f'<span>{html.escape(deck.title)}</span>'
                f'<span>{number:02d} / {len(deck.pages):02d}</span>'
                '</header>'
                f'<div class="progress">{progress}</div>'
                '</section>'
            )
            scenes.append(scene)
            plan.append({"id": scene_id, "start": start / 1000,
                         "pageStart": start_ms / 1000, "duration": duration / 1000,
                         "pageDuration": page.duration_ms / 1000,
                         "originalHoldAt": original_hold_at,
                         "original": None if flat_pixels else f"original-{number:02d}",
                         "rigidCanvas": automatic or flat_pixels,
                         "backdrops": backdrops,
                         "progress": f"progress-{number:02d}",
                         "moving": moving, "focuses": focuses})
            page_backgrounds.append({
                "page": number, "file": f"{base}/{stage['background']}",
                "source_card": str(page.path), "theme": theme,
                "provenance": stage["background_provenance"],
            })

        sounds = []
        for index, (start_ms, _) in enumerate(ranges):
            if not automatic and index != 0 and index not in {1, 3, 5, 7}:
                continue
            kind = ("whoosh" if index > 0 and any(item.role in {"panel", "layout"}
                    for item in deck.pages[index].elements) else "impact") if automatic else (
                    "whoosh" if index in {1, 5} else "impact")
            filename, length_ms = SOUNDS[kind]
            target = assets / filename
            if not target.is_file():
                shutil.copy2(SFX / filename, target)
            sounds.append(
                f'<audio id="sfx-{index:02d}" src="assets/{filename}" '
                f'data-start="{_seconds(start_ms)}" '
                f'data-duration="{_seconds(length_ms)}" '
                'data-volume="0.55"></audio>'
            )
        template = TEMPLATE.read_text(encoding="utf-8")
        safe_plan = json.dumps(plan, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        replacements = {
            "__DURATION__": _seconds(deck.duration_ms),
            "__WIDTH__": str(CANVAS_W), "__HEIGHT__": str(CANVAS_H),
            "__SCENES__": "\n    ".join(scenes),
            "__SOUNDS__": "\n    ".join(sounds),
            "__PLAN__": safe_plan,
            "__FIELD__": page_backgrounds[0]["theme"]["field"],
        }
        for key, value in replacements.items():
            template = template.replace(key, value)
        (build_root / "index.html").write_text(template, encoding="utf-8")
        (build_root / "generated.json").write_text(json.dumps({
            "manifest": str(deck.manifest), "digest": deck.digest(),
            "renderer": deck.renderer, "cards": len(deck.pages),
            "duration_ms": deck.duration_ms,
            "source_images": [str(page.path) for page in deck.pages],
            "moving_elements": sum(len(item["moving"]) for item in plan),
            "focus_elements": sum(len(item["focuses"]) for item in plan),
            "one_line_summaries": 0, "audio_cues": len(sounds),
            "automatic_plan": automatic,
            "original_card_overlay": not flat_pixels,
            "elements_per_card": [len(page.elements) for page in deck.pages],
            "durations_ms": [page.duration_ms for page in deck.pages],
            "page_backgrounds": page_backgrounds,
            "background_policy": "page_clean_plate_edge_texture_v3",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(build_root, output_root)
        return output_root / "index.html"
    except BaseException:
        shutil.rmtree(build_root, ignore_errors=True)
        raise


def render_project(project: Path, output: Path) -> None:
    """The app's render button and daily workflow both use this CLI path."""
    if not CLI.is_file():
        raise RuntimeError(f"HyperFrames 실행 파일이 없습니다: {CLI}")
    environment = os.environ.copy()
    environment["HYPERFRAMES_NO_TELEMETRY"] = "1"
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if chrome.is_file():
        environment.setdefault("HYPERFRAMES_BROWSER_PATH", str(chrome))
    subprocess.run([str(CLI), "lint"], cwd=project.parent, env=environment, check=True)
    temporary = output.with_name(f".{output.stem}.{os.getpid()}.mp4")
    try:
        subprocess.run([str(CLI), "render", "--fps", "30", "--workers", "1",
                        "--quality", "looks", "--output", str(temporary)],
                       cwd=project.parent, env=environment, check=True)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
