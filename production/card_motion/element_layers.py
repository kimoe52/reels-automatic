"""Prepare editable motion layers from a flattened, reviewed card image.

The original artwork is never overwritten.  A reviewed element plan specifies
small, non-overlapping regions.  Each region becomes a transparent PNG and its
pixels are removed from a separate clean plate.  The exact original card is
still used for the reading hold, so its copy and figures cannot be regenerated.
"""

from __future__ import annotations

import json
import hashlib
import colorsys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from motion_effects import EFFECTS


@dataclass(frozen=True)
class Element:
    name: str
    box: tuple[int, int, int, int]
    mask: str
    delay_ms: int
    radius: int = 0
    repair: bool = True
    role: str = ""
    effect: str = ""


def parse_elements(raw: Any, size: tuple[int, int], page_number: int, *,
                   allow_source: bool = False) -> tuple[Element, ...]:
    limit = 128 if allow_source else 24
    if not isinstance(raw, list) or not 1 <= len(raw) <= limit:
        raise ValueError(f"{page_number}장에는 모션 요소 1~{limit}개가 필요합니다")
    result: list[Element] = []
    width, height = size
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"{page_number}장 {index}번 요소 설정이 올바르지 않습니다")
        name = str(item.get("name") or "").strip()
        box = item.get("box")
        mask = item.get("mask")
        delay = item.get("delay_ms")
        radius = item.get("radius", 0)
        repair = item.get("repair", mask == "foreground")
        if not name or len(name) > (80 if allow_source else 30) or any(item.name == name for item in result):
            raise ValueError(f"{page_number}장 {index}번 요소 이름이 필요합니다")
        if (not isinstance(box, list) or len(box) != 4
                or any(type(value) is not int for value in box)):
            raise ValueError(f"{page_number}장 {name}의 box는 [x,y,w,h]여야 합니다")
        x, y, w, h = box
        minimum = 1 if allow_source and mask == "source" else 24
        if x < 0 or y < 0 or w < minimum or h < minimum or x + w > width or y + h > height:
            raise ValueError(f"{page_number}장 {name}의 영역이 원본 밖입니다")
        if mask not in {"foreground", "rounded", "lime", "ink", "region", "source"}:
            raise ValueError(f"{page_number}장 {name}의 mask가 올바르지 않습니다")
        if mask == "source" and not allow_source:
            raise ValueError(f"{page_number}장 source mask에는 검증한 원본 레이어가 필요합니다")
        if type(delay) is not int or delay < 0 or delay > 5000:
            raise ValueError(f"{page_number}장 {name}의 등장 시점은 0~5000ms여야 합니다")
        if type(radius) is not int or radius < 0 or radius > min(w, h) // 2:
            raise ValueError(f"{page_number}장 {name}의 모서리 반경이 올바르지 않습니다")
        if type(repair) is not bool:
            raise ValueError(f"{page_number}장 {name}의 repair는 참/거짓이어야 합니다")
        role = str(item.get("role") or "")
        effect = str(item.get("effect") or "")
        if effect not in EFFECTS:
            raise ValueError(f"{page_number}장 {name}의 effect가 올바르지 않습니다")
        candidate = Element(name, (x, y, w, h), mask, delay, radius, repair, role, effect)
        for existing in result:
            a, b, c, d = existing.box
            if mask != "source" and existing.mask != "source" and x < a + c and x + w > a and y < b + d and y + h > b:
                raise ValueError(f"{page_number}장 요소 영역이 겹칩니다: {existing.name}, {name}")
        result.append(candidate)
    return tuple(result)


def _corners(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[tuple[int, int, int], ...]:
    x, y, w, h = box
    source = image.load()

    def field_color(color: tuple[int, int, int]) -> bool:
        # These reviewed cards use a lavender field. Black type, white panels,
        # saturated decoration and characters must never become inpaint samples.
        red, green, blue = color
        return (red >= 145 and green >= 95 and blue >= 165
                and blue >= red + 6 and blue >= green + 12
                and red >= green and red - green <= 100)

    def sample(cx: int, cy: int, radius: int) -> list[tuple[int, int, int]]:
        colors = []
        for py in range(max(0, cy - radius), min(image.height, cy + radius + 1), 4):
            for px in range(max(0, cx - radius), min(image.width, cx + radius + 1), 4):
                if x <= px < x + w and y <= py < y + h:
                    continue
                color = source[px, py]
                if field_color(color):
                    colors.append(color)
        return colors

    # When a box borders a face or another panel, a tiny edge patch samples
    # black/white instead of the actual background. Expand into intact field.
    locations = ((x - 12, y - 12), (x + w + 11, y - 12),
                 (x - 12, y + h + 11), (x + w + 11, y + h + 11))
    global_field = sample(image.width // 2, image.height // 2,
                          max(image.width, image.height))
    if not global_field:
        raise ValueError("배경 재생성용 원본 배경 픽셀을 찾지 못했습니다")

    def median(colors: list[tuple[int, int, int]]) -> tuple[int, int, int]:
        return tuple(sorted(color[channel] for color in colors)[len(colors) // 2]
                     for channel in range(3))

    samples = []
    for cx, cy in locations:
        colors = sample(cx, cy, 42)
        if len(colors) < 18:
            colors = sample(cx, cy, 110)
        samples.append(median(colors if colors else global_field))
    return tuple(samples)


def _field_reference(image: Image.Image) -> tuple[int, int, int]:
    """Estimate the deck's field from its margins, not its text/panel interiors."""
    small = image.resize((120, 150), Image.Resampling.BILINEAR)
    samples = [small.getpixel((x, y)) for y in range(150) for x in range(120)
               if y < 5 or x < 3 or x >= 117]
    bins = Counter(tuple(channel // 24 for channel in color) for color in samples)
    dominant = max(bins, key=bins.get)
    field = [color for color in samples
             if max(abs(color[channel] // 24 - dominant[channel]) for channel in range(3)) <= 1]
    return tuple(sorted(color[channel] for color in field)[len(field) // 2]
                 for channel in range(3))


def _region_background(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Color-agnostic clean field for automatic regions on illustrated cards.

    This is deliberately a smooth reconstruction, not generative inpainting of
    facts, faces, or figures. Detailed/photo backgrounds require source layers.
    """
    x, y, w, h = box
    reference = _field_reference(image)
    source = image.load()
    colors = []
    for cx, cy in ((x - 8, y - 8), (x + w + 8, y - 8),
                   (x - 8, y + h + 8), (x + w + 8, y + h + 8)):
        nearby = []
        for radius in (35, 100, 180):
            for sy in range(max(0, cy - radius), min(image.height, cy + radius + 1), 8):
                for sx in range(max(0, cx - radius), min(image.width, cx + radius + 1), 8):
                    if x <= sx < x + w and y <= sy < y + h:
                        continue
                    color = source[sx, sy]
                    if max(abs(color[channel] - reference[channel]) for channel in range(3)) <= 55:
                        nearby.append(color)
            if len(nearby) >= 20:
                break
        colors.append(tuple(sorted(color[channel] for color in nearby)[len(nearby) // 2]
                            for channel in range(3)) if nearby else reference)
    return _background(tuple(colors), w, h)


def _source_background(source: Path, element: Element) -> Image.Image | None:
    """Use an exact renderer-recorded patch only when its source hash matches."""
    metadata = source.parent / "layout.json"
    if not metadata.is_file():
        return None
    data = json.loads(metadata.read_text(encoding="utf-8"))
    matching = next((card for card in data.get("cards", [])
                     if card.get("file") == source.name), None)
    if not matching:
        return None
    digest = None
    for record in matching.get("boxes", []):
        if record.get("name") != element.name:
            continue
        x, y, w, h = element.box
        recorded = record.get("box")
        if (not isinstance(recorded, list) or len(recorded) != 4
                or not record.get("background_file")):
            continue
        left, top, right, bottom = recorded
        # A precise node may contain large transparent margins. The planner
        # can trim those margins without losing the original background patch.
        if not (left <= x and top <= y and x + w <= right and y + h <= bottom):
            continue
        relative = Path(record["background_file"])
        path = (source.parent / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(source.parent.resolve()):
            raise ValueError("정밀 배경판 경로가 카드 폴더 밖입니다")
        if not path.is_file():
            raise ValueError(f"정밀 배경판이 없습니다: {relative}")
        if digest is None:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if record.get("source_sha256") != digest:
            raise ValueError("정밀 배경판과 원본 카드 해시가 다릅니다")
        if record.get("background_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("정밀 배경판 파일 해시가 다릅니다")
        patch = Image.open(path).convert("RGB")
        if patch.size != (right - left, bottom - top):
            raise ValueError("정밀 배경판과 요소 크기가 다릅니다")
        return patch.crop((x - left, y - top, x + w - left, y + h - top))
    return None


def _background(corners: tuple[tuple[int, int, int], ...], w: int, h: int) -> Image.Image:
    result = Image.new("RGB", (w, h))
    pixels = result.load()
    top_left, top_right, bottom_left, bottom_right = corners
    for py in range(h):
        ty = py / max(1, h - 1)
        left = [top_left[channel] * (1 - ty) + bottom_left[channel] * ty for channel in range(3)]
        right = [top_right[channel] * (1 - ty) + bottom_right[channel] * ty for channel in range(3)]
        for px in range(w):
            tx = px / max(1, w - 1)
            pixels[px, py] = tuple(round(left[channel] * (1 - tx) + right[channel] * tx)
                                   for channel in range(3))
    return result


def _paper_background(crop: Image.Image) -> Image.Image:
    """Rebuild a speech bubble's light paper from untouched interior pixels."""
    colors = [color for color in list(crop.getdata())[::9]
              if min(color) >= 230 and max(color) - min(color) <= 25]
    if not colors:
        raise ValueError("말풍선 글자 분리용 밝은 내부 배경을 찾지 못했습니다")
    median = tuple(sorted(color[channel] for color in colors)[len(colors) // 2]
                   for channel in range(3))
    return Image.new("RGB", crop.size, median)


def _horizontal_background(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Rebuild a smooth headline band from intact pixels at both sides."""
    x, y, w, h = box
    output = Image.new("RGB", (w, h))
    source, target = image.load(), output.load()
    def side_color(column: int, row: int) -> tuple[int, int, int]:
        pixels = []
        for dy in range(-7, 8, 2):
            sy = max(0, min(image.height - 1, row + dy))
            for dx in range(-24, 25, 4):
                sx = max(0, min(image.width - 1, column + dx))
                color = source[sx, sy]
                # In the reviewed cards the headline is on a light gradient;
                # reject black letters and violet decoration at the sampling edge.
                if min(color) >= 145 and max(color) - min(color) <= 105:
                    pixels.append(color)
        if not pixels:
            pixels = [source[max(0, min(image.width - 1, column)), row]]
        return tuple(sorted(pixel[channel] for pixel in pixels)[len(pixels) // 2]
                     for channel in range(3))

    left_x, right_x = max(0, x - 18), min(image.width - 1, x + w + 17)
    for py in range(h):
        row = y + py
        left, right = side_color(left_x, row), side_color(right_x, row)
        for px in range(w):
            t = px / max(1, w - 1)
            target[px, py] = tuple(round(left[channel] * (1 - t) + right[channel] * t)
                                    for channel in range(3))
    return output


def _mask(crop: Image.Image, background: Image.Image, element: Element) -> Image.Image:
    w, h = crop.size
    if element.mask == "rounded":
        # Antialiased shape matte, not a rectangular crop with visible corners.
        supersample = 3
        shape = Image.new("L", (w * supersample, h * supersample))
        draw = ImageDraw.Draw(shape)
        draw.rounded_rectangle((0, 0, w * supersample - 1, h * supersample - 1),
                               radius=element.radius * supersample, fill=255)
        return shape.resize((w, h), Image.Resampling.LANCZOS)
    if element.mask == "lime":
        matte = Image.new("L", (w, h))
        source, out = crop.load(), matte.load()
        for py in range(h):
            for px in range(w):
                red, green, blue = source[px, py]
                if green > red + 16 and green > blue + 40 and green > 130:
                    out[px, py] = 255
        return matte.filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.GaussianBlur(.5))
    if element.mask == "ink":
        matte = Image.new("L", (w, h))
        source, out = crop.load(), matte.load()
        for py in range(h):
            for px in range(w):
                color = source[px, py]
                low, high = min(color), max(color)
                # The lavender artwork outside the white speech bubble is not ink.
                # Keep dark colored glyphs and neutral antialiasing, not the field.
                out[px, py] = (255 if low < 145 else
                               max(0, min(255, (245 - low) * 12))
                               if high - low < 20 else 0)
        return matte.filter(ImageFilter.GaussianBlur(.3))
    source, plate = crop.load(), background.load()
    matte = Image.new("L", (w, h))
    out = matte.load()
    for py in range(h):
        for px in range(w):
            delta = max(abs(source[px, py][channel] - plate[px, py][channel])
                        for channel in range(3))
            # Letters, strokes and their light antialiasing remain original pixels.
            out[px, py] = max(0, min(255, round((delta - 7) * 255 / 17)))
    return matte.filter(ImageFilter.GaussianBlur(0.35))


def _closed_matte(alpha: Image.Image) -> Image.Image:
    """Leave any border-clipped decoration/outline on the original clean plate."""
    keep = alpha.point(lambda value: 255 if value >= 96 else 0)
    width, height = keep.size
    edges = ([(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
             + [(0, y) for y in range(height)] + [(width - 1, y) for y in range(height)])
    for position in edges:
        if keep.getpixel(position):
            ImageDraw.floodfill(keep, position, 0)
    return ImageChops.multiply(alpha, keep.filter(ImageFilter.MaxFilter(3)))


def prepare_layers(source: Path, elements: tuple[Element, ...], output: Path) -> dict[str, Any]:
    """Create one clean card and transparent cutouts; return reproducible asset paths."""
    if output.exists():
        metadata = output / "elements.json"
        if metadata.is_file():
            return json.loads(metadata.read_text(encoding="utf-8"))
        raise ValueError(f"완성되지 않은 요소 폴더를 보존했습니다: {output}")
    output.mkdir(parents=True)
    original = Image.open(source).convert("RGB")
    clean = original.copy()
    records = []
    for number, element in enumerate(elements, 1):
        x, y, w, h = element.box
        crop = original.crop((x, y, x + w, y + h))
        precise = _source_background(source, element) if element.mask == "region" else None
        background = (precise if precise is not None else _paper_background(crop)
                      if element.mask == "ink" else
                      _region_background(original, element.box)
                      if element.mask == "region" else
                      _horizontal_background(original, element.box)
                      if element.mask == "foreground" else
                      _background(_corners(original, element.box), w, h)
                      if element.repair else Image.new("RGB", (w, h)))
        alpha = _mask(crop, background, element)
        if element.mask == "region" and precise is None:
            alpha = _closed_matte(alpha)
        if precise is not None:
            # Exact source differencing includes the real panel/figure outline
            # and excludes its background, without hue assumptions.
            a, b = crop.load(), precise.load()
            alpha = Image.new("L", crop.size)
            matte = alpha.load()
            for py in range(h):
                for px in range(w):
                    matte[px, py] = 255 if max(abs(a[px, py][c] - b[px, py][c])
                                              for c in range(3)) > 2 else 0
        layer = crop.convert("RGBA")
        layer.putalpha(alpha)
        name = f"element-{number:02d}.png"
        layer.save(output / name)
        if element.repair:
            # A headline sits on an uninterrupted gradient; reconstruct its
            # entire band so the hidden text cannot leave a colored ghost.
            repair_alpha = (Image.new("L", (w, h), 255)
                            if element.mask in {"foreground", "ink"} else alpha)
            clean.paste(Image.composite(background, clean.crop((x, y, x + w, y + h)),
                                        repair_alpha), (x, y))
        focus_file = None
        if element.mask == "rounded":
            # A thin source-aligned focus trace leaves every letter and figure
            # readable throughout the cut.  It replaces the blank-panel wipe.
            focus = Image.new("RGBA", (w, h))
            stroke = max(5, min(9, min(w, h) // 30))
            ImageDraw.Draw(focus).rounded_rectangle(
                (stroke, stroke, w - stroke - 1, h - stroke - 1),
                radius=max(8, element.radius), outline=(110, 61, 183, 178), width=stroke)
            focus_file = f"focus-{number:02d}.png"
            focus.save(output / focus_file)
        records.append({"name": element.name, "file": name, "box": list(element.box),
                        "mask": element.mask, "delay_ms": element.delay_ms,
                        "repair": element.repair, "focus_file": focus_file,
                        "role": element.role, "effect": element.effect,
                        "background_method": "source_layers" if precise is not None else "smooth_field"})
    clean_name = "clean-plate.png"
    clean.save(output / clean_name)
    report = {"source": str(source), "clean_plate": clean_name, "elements": records}
    (output / "elements.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return report


def prepare_vertical_stage(source: Path, clean_plate: Path, output: Path,
                           canvas: tuple[int, int] = (1080, 1920), *,
                           fade_bottom: bool = True) -> dict[str, Any]:
    """Build a card-specific 9:16 background from its verified clean plate.

    The old implementation enlarged one edge row above and below the card.
    That made a new card appear inside an old shared Reel shell.  Here every
    page gets a full-frame source-bound background: its clean plate remains
    intact at card scale, while its own top/bottom texture is extended only
    into the extra 9:16 area.  No facts, text, people, or decoration are
    synthesized.
    """
    output.mkdir(parents=True, exist_ok=True)
    width, height = canvas
    original = Image.open(source).convert("RGB")
    plate = Image.open(clean_plate).convert("RGB")
    if original.size != plate.size:
        raise ValueError("원본과 분리 배경판의 크기가 다릅니다")
    scaled_height = round(original.height * width / original.width)
    if scaled_height >= height:
        raise ValueError("9:16 배경에는 카드 위아래 여백이 필요합니다")
    y = (height - scaled_height) // 2
    resampling = Image.Resampling.LANCZOS
    image = original.resize((width, scaled_height), resampling)
    clean = plate.resize((width, scaled_height), resampling)

    def _extension(edge: Image.Image, target_height: int, seam: Image.Image,
                   *, top: bool) -> Image.Image:
        """Stretch an actual clean-plate edge texture and make the seam exact."""
        if target_height <= 0:
            return Image.new("RGB", (width, 0))
        result = edge.resize((width, target_height), resampling)
        # ``distance`` is measured from the card seam for both branches.  The
        # seam is exact, then its neighbouring rows blend most strongly back
        # to the verified clean-plate edge.  This prevents a 32px direction
        # reversal/band beneath the card.
        blend = min(32, target_height)
        pixels, seam_pixels = result.load(), seam.load()
        for distance in range(blend):
            weight = 1 if blend == 1 else 1 - distance / (blend - 1)
            target_y = target_height - 1 - distance if top else distance
            edge_y = 0 if top else seam.height - 1
            for x in range(width):
                base, target = pixels[x, target_y], seam_pixels[x, edge_y]
                pixels[x, target_y] = tuple(round(base[c] * (1 - weight) + target[c] * weight)
                                            for c in range(3))
        # The touching row itself must be byte-identical to the source plate.
        source_y = 0 if top else seam.height - 1
        result.paste(seam.crop((0, source_y, width, source_y + 1)),
                     (0, target_height - 1 if top else 0))
        return result

    texture_depth = max(24, min(scaled_height // 5, 220))
    top_texture = clean.crop((0, 0, width, texture_depth))
    bottom_texture = clean.crop((0, scaled_height - texture_depth, width, scaled_height))
    top = _extension(top_texture, y, clean, top=True)
    bottom_height = height - (y + scaled_height)
    bottom = _extension(bottom_texture, bottom_height, clean, top=False)
    stage = Image.new("RGB", canvas)
    stage.paste(top, (0, 0))
    stage.paste(clean, (0, y))
    stage.paste(bottom, (0, y + scaled_height))

    def _hex(color: tuple[int, int, int]) -> str:
        return "#" + "".join(f"{channel:02x}" for channel in color)

    def _theme() -> dict[str, str]:
        # Do not sample the flattened composite here: that would let a title,
        # character, or panel become a "background" colour.  Side/top/bottom
        # clean-plate pixels are the only source for the page theme.
        field = _field_reference(clean)
        # Sample the *unscaled* verified plate.  LANCZOS can invent a nearby
        # colour at a saturated edge (for example #00cc7a -> #00ce71), which
        # is not an actual source accent and weakens provenance.
        margin_x = max(1, round(plate.width * 7 / 120))
        margin_y = max(1, round(plate.height * 6 / 150))
        swatches = [plate.getpixel((x, y)) for y in range(plate.height)
                    for x in range(plate.width)
                    if (x < margin_x or x >= plate.width - margin_x
                        or y < margin_y or y >= plate.height - margin_y)]
        luminance = (field[0] * 299 + field[1] * 587 + field[2] * 114) / 255000
        ink = tuple(max(10, round(channel * .18)) for channel in field) if luminance > .5 else \
            tuple(min(245, round(210 + channel * .18)) for channel in field)
        candidates: list[tuple[float, tuple[int, int, int]]] = []
        for color in swatches:
            red, green, blue = (channel / 255 for channel in color)
            hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
            if saturation >= .35 and .48 <= value <= .98:
                # Prefer a visibly different but still readable accent.
                distance = max(abs(color[c] - field[c]) for c in range(3))
                if distance >= 45:
                    candidates.append((saturation * value, color))
        if candidates:
            # A real, source-bound edge accent always wins over a calculated
            # fallback.  It is still sourced only from the clean background.
            active = max(candidates)[1]
        else:
            red, green, blue = (channel / 255 for channel in field)
            hue, saturation, _ = colorsys.rgb_to_hsv(red, green, blue)
            if saturation < .12:
                active = ink
            else:
                active_saturation = min(.88, max(.52, saturation * 2.2))
                active_value = .48 if luminance > .65 else .93
                active = tuple(round(channel * 255) for channel in
                               colorsys.hsv_to_rgb(hue, active_saturation, active_value))
        track = tuple(round(field[c] * .72 + ink[c] * .28) for c in range(3))
        return {"field": _hex(field), "ink": _hex(ink), "progress_track": _hex(track),
                "progress_active": _hex(active)}

    background_sha = hashlib.sha256(clean_plate.read_bytes()).hexdigest()
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    stage_background = "stage-background.png"
    stage.save(output / stage_background)

    def place(card: Image.Image, name: str) -> None:
        result = stage.copy()
        # Feather the illustration's cropped feet/body, not the informational
        # content above it; the bottom extension begins at the same color.
        fade = min(64, scaled_height // 16) if fade_bottom else 0
        if not fade:
            result.paste(card, (0, y))
            result.save(output / name)
            return
        result.paste(card.crop((0, 0, width, scaled_height - fade)), (0, y))
        tail = card.crop((0, scaled_height - fade, width, scaled_height))
        field = stage.crop((0, y + scaled_height - fade, width, y + scaled_height))
        mask = Image.new("L", (1, fade))
        mask.putdata([round(255 * (1 - row / max(1, fade - 1))) for row in range(fade)])
        result.paste(Image.composite(tail, field, mask.resize((width, fade))),
                     (0, y + scaled_height - fade))
        result.save(output / name)

    place(image, "stage-original.png")
    # The motion clean plate and the scene's static backdrop are the same
    # pixels.  A separate fade here used to expose a thin field change just
    # before the original-card reading hold.
    stage.save(output / "stage-plate.png")
    return {"original": "stage-original.png", "plate": "stage-plate.png",
            "background": stage_background,
            "card_y": y, "card_scale": width / original.width,
            "canvas": [width, height], "theme": _theme(),
            "background_provenance": {
                "method": "clean_plate_edge_texture_v3",
                "policy_version": "card_background_policy_v3",
                "source_card_sha256": source_sha,
                "source_background_sha256": background_sha,
                "texture_depth_px": texture_depth,
                "source_background": str(clean_plate),
            }}
