"""Decompose supplied illustrated cards locally, without authored coordinates.

This is pixel extraction, not a claim to recover an illustrator's hidden layers.
OCR only locates/estimates reading time; every rendered glyph/figure is copied
from the supplied image. Smooth field reconstruction is deliberately limited to
light illustrated cards. Ambiguous/photo inputs fail rather than return a flat
slideshow or silently cut a face into pieces.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, deque
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from element_layers import _field_reference
from source_layers import LayerRepairRequired, file_sha, load_source_card

VERSION = "flat-pixels-3"


def _components(mask: Image.Image) -> list[tuple[list[int], list[tuple[int, int]]]]:
    width, height = mask.size; pixels = mask.load(); seen = bytearray(width * height)
    result = []
    for y in range(height):
        for x in range(width):
            offset = y * width + x
            if seen[offset] or not pixels[x, y]:
                continue
            seen[offset] = 1; queue = deque([(x, y)]); points = []
            left = right = x; top = bottom = y
            while queue:
                px, py = queue.popleft(); points.append((px, py))
                left = min(left, px); right = max(right, px)
                top = min(top, py); bottom = max(bottom, py)
                for nx, ny in ((px-1, py), (px+1, py), (px, py-1), (px, py+1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        index = ny * width + nx
                        if not seen[index] and pixels[nx, ny]:
                            seen[index] = 1; queue.append((nx, ny))
            result.append(([left, top, right-left+1, bottom-top+1], points))
    return result


def _field(image: Image.Image) -> Image.Image:
    """Fit the same light field across the frame, never use black/white objects."""
    reference = _field_reference(image)
    if min(reference) < 140:
        raise LayerRepairRequired("평면 자동 분리는 밝은 일러스트 카드만 지원합니다")
    small = image.resize((320, 400)).convert("RGB")
    width, height = small.size; samples = []
    for y in range(height):
        row = []
        for x in (*range(0, 16), *range(width-16, width)):
            color = small.getpixel((x, y))
            if max(abs(color[c]-reference[c]) for c in range(3)) < 46:
                row.append(color)
        samples.append(tuple(sorted(color[c] for color in row)[len(row)//2]
                             for c in range(3)) if row else reference)
    line = Image.new("RGB", (1, height)); line.putdata(samples)
    return line.resize((32, height)).filter(ImageFilter.GaussianBlur(16)).resize(image.size)


def _ink(image: Image.Image) -> Image.Image:
    output = Image.new("L", image.size)
    output.putdata([255 if min(color) < 140 or max(color)-min(color) > 110 else 0
                    for color in image.getdata()])
    return output


def _light_surface(image: Image.Image) -> Image.Image:
    """Include off-white/cream paper, not just strictly neutral white pixels."""
    output=Image.new("L",image.size)
    output.putdata([255 if min(color)>205 and max(color)-min(color)<55
                   and sum(color)>708 else 0 for color in image.getdata()])
    return output


def _union(masks: list[Image.Image], size: tuple[int, int]) -> Image.Image:
    result = Image.new("L", size)
    for mask in masks:
        result = ImageChops.lighter(result, mask)
    return result


def _refine_full_resolution(coarse: Image.Image, evidence: Image.Image) -> Image.Image:
    """Refit the silhouette to source-resolution paint, not enlarged thumbnails.

    A small support margin allows an enclosing stroke hidden by a neighboring
    panel to close again. Filling *that* stroke keeps the figure's interior,
    while at most one original pixel is retained beyond its source edge.
    """
    bounds = coarse.getbbox()
    result = Image.new("L", coarse.size)
    if bounds is None:
        return result
    # Read a tiny original-resolution margin too. A speech bubble may cover
    # the lower outline of a pig/figure; the neighboring occluder's stroke is
    # needed to close its VISIBLE contour, not to invent a hidden body.
    bounds = (max(0,bounds[0]-8),max(0,bounds[1]-8),
              min(coarse.width,bounds[2]+8),min(coarse.height,bounds[3]+8))
    support = coarse.crop(bounds)
    seed = evidence.crop(bounds)
    seed = seed.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    # An illustration cropped by the SOURCE canvas has no closing stroke
    # beyond that edge. Close only the supported interval on that exact
    # canvas edge, so its visible shaded interior is not punched out.
    edge_draw=ImageDraw.Draw(seed)
    support_box=support.getbbox()
    if support_box:
        edges=[]
        if bounds[1] == 0 and support_box[1] == 0:
            edges.append([(x,0) for x in range(seed.width)])
        if bounds[3] == coarse.height and support_box[3] == seed.height:
            edges.append([(x,seed.height-1) for x in range(seed.width)])
        if bounds[0] == 0 and support_box[0] == 0:
            edges.append([(0,y) for y in range(seed.height)])
        if bounds[2] == coarse.width and support_box[2] == seed.width:
            edges.append([(seed.width-1,y) for y in range(seed.height)])
        for edge in edges:
            supported=[point for point in edge if seed.getpixel(point) and support.getpixel(point)]
            if len(supported)>1:
                edge_draw.line((supported[0],supported[-1]),fill=255)
    enclosed = _filled(seed)
    silhouette = Image.new("L", enclosed.size)
    support_pixels = support.load(); selected_pixels = silhouette.load()
    for _, points in _components(enclosed):
        if any(support_pixels[point] for point in points):
            for point in points:
                selected_pixels[point] = 255
    silhouette = silhouette.filter(ImageFilter.MaxFilter(3))
    result.paste(silhouette, bounds[:2])
    return result


def _filled(mask: Image.Image) -> Image.Image:
    """Keep eyes/letter counters inside one enclosing figure, not new props."""
    padded = Image.new("L", (mask.width+2,mask.height+2))
    padded.paste(mask,(1,1)); ImageDraw.floodfill(padded,(0,0),128)
    return padded.point(lambda value: 0 if value == 128 else 255).crop((1,1,mask.width+1,mask.height+1))


def _couple_paint_ownership(masks: list[Image.Image], paint: Image.Image,
                            groups: list[int]) -> list[int]:
    """Keep a source contour or white interior from moving as cut fragments.

    Priority ownership can split a connected stroke or figure's white fill
    between neighboring detections. Reunite those owners, not nearby boxes,
    so extraction cannot expose the resulting artificial holes in motion.
    """
    owners=Image.new("I",paint.size)
    for index,mask in enumerate(masks,1):
        owners.paste(index,(0,0),mask)
    owner_pixels=owners.load()
    roots={group:group for group in groups}
    def root(group):
        while roots[group] != group:
            roots[group]=roots[roots[group]]; group=roots[group]
        return group
    for _,points in _components(paint):
        counts=Counter(owner_pixels[point] for point in points if owner_pixels[point])
        participants=[groups[index-1] for index,count in counts.items() if count >= 3]
        if len(participants)>1:
            anchor=root(participants[0])
            for group in participants[1:]:
                roots[root(group)]=anchor
    return [root(group) for group in groups]


def _role(box: list[int], size: tuple[int, int], text: str = "") -> str:
    x, y, w, h = box; width, height = size
    if text:
        return "title" if y < height*.23 and h > height*.035 else "text"
    if y > height*.52 and h > height*.25:
        return "character"
    if w/h > 1.5 and y > height*.28 and w > width*.27:
        return "bubble"
    if y < height*.25 and h < height*.22:
        return "title"
    if w > width*.34 and h > height*.10:
        return "panel" if y < height*.68 else "character"
    if y > height*.54 and h > height*.16:
        return "character"
    return "prop"


def _reading_lines(ocr: list[tuple[str,list[int]]], width: int) -> list[tuple[str,list[int]]]:
    lines: list[tuple[str,list[int]]] = []
    for text, box in sorted(ocr,key=lambda item:(item[1][1],item[1][0])):
        x,y,w,h = box
        for index,(prior,b) in enumerate(lines):
            bx,by,bw,bh = b
            overlap = min(y+h,by+bh)-max(y,by)
            gap = max(x,bx)-min(x+w,bx+bw)
            if overlap > min(h,bh)*.55 and gap < width*.035:
                left,top = min(x,bx),min(y,by)
                lines[index] = (prior+" "+text,[left,top,max(x+w,bx+bw)-left,max(y+h,by+bh)-top])
                break
        else:
            lines.append((text,box))
    return lines


def _publish_metadata(final: Path, metadata: Path, source: Path) -> None:
    """Validate a complete asset directory and atomically bind it to its source.

    Publishing can be retried after interruption without regenerating or
    overwriting an existing asset directory.
    """
    if not final.resolve().is_relative_to(source.parent):
        raise LayerRepairRequired("평면 분리 출력 경로가 원본 폴더 밖입니다")
    load_source_card(final / "card.layers.json", final / "original.png")
    document = json.loads((final / "card.layers.json").read_text(encoding="utf-8"))
    if document["source_sha256"] != file_sha(source):
        raise LayerRepairRequired("복구할 분리 이미지와 카드 원본이 일치하지 않습니다")
    prefix = final.relative_to(source.parent)
    bound = {**document, "source_file": source.name}
    bound["background"] = {**document["background"], "file": str(prefix / document["background"]["file"])}
    bound["layers"] = [{**record, "file": str(prefix / record["file"])} for record in document["layers"]]
    staged = metadata.with_name(f".{metadata.name}.{os.getpid()}.tmp")
    staged.write_text(json.dumps(bound, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(staged, metadata)
    load_source_card(metadata, source)


def export_flat_layers(source: Path, ocr: list[tuple[str, list[int]]],
                       ocr_meta: dict[str, Any]) -> Path:
    """Produce hash-bound RGBA assets and exact reconstruction from PNG only."""
    source = source.resolve()
    dependencies = [file_sha(source), file_sha(Path(__file__)),
                    file_sha(Path(__file__).with_name("element_layers.py")),
                    json.dumps([ocr, ocr_meta], ensure_ascii=False, sort_keys=True)]
    fingerprint = hashlib.sha256("\n".join(dependencies).encode()).hexdigest()[:12]
    final = source.parent / "extracted-layers" / f"{source.stem}-{fingerprint}"
    metadata = source.parent / f"{source.stem}.flat-{fingerprint}.layers.json"
    if not final.parent.resolve().is_relative_to(source.parent) or not metadata.resolve().is_relative_to(source.parent):
        raise LayerRepairRequired("평면 분리 출력 경로가 원본 폴더 밖입니다")
    if metadata.is_file():
        load_source_card(metadata, source)
        return metadata
    if final.exists():
        _publish_metadata(final, metadata, source)
        return metadata
    with Image.open(source) as opened:
        original = opened.convert("RGBA")
    width, height = original.size
    if abs(width/height-.8) > .02 or width < 320:
        raise LayerRepairRequired("평면 자동 분리에는 4:5 카드 이미지가 필요합니다")
    if original.getchannel("A").getextrema() != (255, 255):
        raise LayerRepairRequired("투명 카드에는 제작기의 원본 레이어를 사용하세요")
    rgb = original.convert("RGB"); field = _field(rgb)
    small_size = (384, round(height*384/width))
    small = rgb.resize(small_size); small_field = field.resize(small_size)
    white = _light_surface(small)
    # Lavender clouds are background, not foreground. Use closed line work
    # and paper shapes rather than treating every deviation from purple as an
    # object (which would join a cloud, pig, bubble and character together).
    mask = ImageChops.lighter(white, _ink(small))
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    small_ink = _ink(small)
    body_masks = []; paper_masks = []
    paper = Image.new("L",small_size)
    for box, points in _components(white):
        x,y,w,h = box
        if (w < small_size[0]*.26 or w/h < 1.3 or h > small_size[1]*.45
                or y+h >= small_size[1]-2):
            continue
        component = Image.new("L",small_size); cp = component.load()
        for point in points: cp[point]=255
        component = _filled(component.filter(ImageFilter.MaxFilter(5)))
        paper_masks.append(component); paper = ImageChops.lighter(paper,component)
    components = _components(ImageChops.subtract(mask,paper))
    # A light cloud has no ink. It stays in the original background instead of
    # becoming an invented animated element. Thin text/decoration is grouped
    # below, rather than emitting each disconnected Korean glyph separately.
    leftovers = Image.new("L", small_size)
    for box, points in components:
        x, y, w, h = box
        dark = sum(small_ink.getpixel(point) > 0 for point in points)
        if len(points) < 14 or not dark:
            continue
        component = Image.new("L", small_size); cp = component.load()
        for point in points:
            cp[point] = 255
        component = _filled(component)
        if h < small_size[1]*.115 and w < small_size[0]*.22:
            leftovers = ImageChops.lighter(leftovers, component)
        else:
            body_masks.append(component)
    # Combine lettering on the same baseline, not arbitrary full-width strips.
    rows = _components(leftovers.filter(ImageFilter.MaxFilter(9)))
    for _, points in rows:
        region = Image.new("L", small_size); rp = region.load()
        for point in points:
            rp[point] = 255
        actual = ImageChops.multiply(region, leftovers)
        if actual.getbbox():
            body_masks.append(actual)
    if not body_masks and not paper_masks:
        raise LayerRepairRequired("움직일 글·그림 요소를 검출하지 못했습니다")
    # Merge neighboring glyph components on a shared baseline. Large figures
    # and enclosing panels remain intact, including their original line work.
    grouped: list[Image.Image] = []
    for body in sorted(body_masks, key=lambda item: (item.getbbox()[1], item.getbbox()[0])):
        a = body.getbbox(); merged = False
        for index, previous in enumerate(grouped):
            b = previous.getbbox()
            overlap = min(a[3], b[3])-max(a[1], b[1])
            gap = max(a[0], b[0])-min(a[2], b[2])
            if (max(a[3]-a[1], b[3]-b[1]) < small_size[1]*.115
                    and overlap > min(a[3]-a[1], b[3]-b[1])*.45 and gap < 25):
                grouped[index] = ImageChops.lighter(previous, body); merged = True; break
        if not merged:
            grouped.append(body)
    # Eyes, clothing and limbs are often disconnected ink components. Keep
    # nested parts and vertically adjoining halves of one lower-frame figure
    # in a single rigid layer, never animate a face or an arm independently.
    stable = False
    while not stable:
        stable = True
        for index,a_mask in enumerate(grouped):
            a = a_mask.getbbox()
            for j in range(index+1,len(grouped)):
                b = grouped[j].getbbox()
                nested = (a[0]-3 <= b[0] and a[1]-3 <= b[1] and a[2]+3 >= b[2] and a[3]+3 >= b[3]) or (b[0]-3 <= a[0] and b[1]-3 <= a[1] and b[2]+3 >= a[2] and b[3]+3 >= a[3])
                horizontal = min(a[2],b[2])-max(a[0],b[0])
                vertical_gap = max(a[1],b[1])-min(a[3],b[3])
                figure = (min(a[1],b[1]) > small_size[1]*.55
                          and max(a[3]-a[1],b[3]-b[1]) > small_size[1]*.14
                          and horizontal > min(a[2]-a[0],b[2]-b[0])*.4
                          and vertical_gap < small_size[1]*.03)
                if nested or figure:
                    grouped[index] = ImageChops.lighter(a_mask,grouped[j]); grouped.pop(j)
                    stable = False; break
            if not stable: break
    # Paper layers take priority at actual occlusion boundaries (speech-bubble
    # tail on hair, for example), without inventing the hidden head beneath it.
    grouped = paper_masks + grouped
    if len(grouped) > 65:
        raise LayerRepairRequired("경계가 너무 복잡해 자동 분리 검수가 필요합니다")
    full_white = _light_surface(rgb)
    paint = ImageChops.lighter(full_white, _ink(rgb))
    masks = [_refine_full_resolution(
                body.resize(original.size, Image.Resampling.NEAREST).filter(ImageFilter.MaxFilter(7)), paint)
             for body in grouped]
    # A partly hidden head/body cannot be moved away from its occluder without
    # revealing missing artwork. Couple only source-ink overlap, not merely
    # neighboring bounding rectangles or a shared lavender field.
    roots = list(range(len(masks)))
    def root(index):
        while roots[index] != index:
            roots[index] = roots[roots[index]]; index = roots[index]
        return index
    source_ink = _ink(rgb)
    for left in range(len(masks)):
        for right in range(left+1,len(masks)):
            left_paper = left < len(paper_masks); right_paper = right < len(paper_masks)
            if left_paper == right_paper:
                continue
            body_index = right if left_paper else left
            bounds = masks[body_index].getbbox()
            if bounds is None:
                continue
            x,y,r,b = bounds; body_box = [x,y,r-x,b-y]
            role = _role(body_box,original.size)
            # Small chart strokes/labels cannot bridge two unrelated bubbles
            # into one giant scene-sized cluster. Only a figure or a sizable,
            # compact illustrated prop has a meaningful hidden silhouette.
            if role != "character" and not (role == "prop" and b-y > height*.10 and r-x < (b-y)*2):
                continue
            collision = ImageChops.multiply(ImageChops.multiply(masks[left],masks[right]),source_ink)
            if sum(collision.histogram()[128:]) >= 8:
                roots[root(right)] = root(left)
    # Full-resolution dilation can overlap adjacent components. Assign every
    # pixel to exactly one base layer, keeping exact source paint coverage.
    occupied = Image.new("L", original.size); disjoint = []; motion_groups = []
    for index, body in enumerate(masks):
        body = ImageChops.subtract(body, occupied)
        if body.getbbox():
            disjoint.append(body); occupied = ImageChops.lighter(occupied, body)
            motion_groups.append(root(index)+1)
    masks = disjoint
    motion_groups = _couple_paint_ownership(masks, paint, motion_groups)
    ink = _ink(rgb).filter(ImageFilter.MaxFilter(5))
    ink_total = sum(_ink(rgb).histogram()[128:]); covered = sum(ImageChops.multiply(_ink(rgb), occupied).histogram()[128:])
    coverage = covered/max(1, ink_total)
    if ink_total < width*height*.002 or coverage < .92:
        raise LayerRepairRequired(f"글·그림 분리 범위가 부족합니다 ({coverage:.1%})")
    # Large photographic/textured backgrounds must not be accepted merely
    # because their non-field pixels happen to form one giant component.
    if sum(occupied.histogram()[128:])/(width*height) > .94:
        raise LayerRepairRequired("사진·전체 화면 피사체는 원본 레이어 보정이 필요합니다")
    text_masks = []; claimed = Image.new("L", original.size)
    for reading_id, (text, box) in enumerate(_reading_lines(ocr,width), 1):
        x, y, w, h = box
        if not text.strip() or w < 32 or h < 12 or h > height*.16 or w/h < 1.2:
            continue
        rectangle = Image.new("L", original.size)
        ImageDraw.Draw(rectangle).rectangle((x,y,min(width-1,x+w),min(height-1,y+h)), fill=255)
        selection = ImageChops.multiply(ImageChops.multiply(rectangle, ink), occupied)
        selection = ImageChops.subtract(selection, claimed)
        if sum(selection.histogram()[128:]) < 24:
            continue
        bounds = selection.getbbox()
        if bounds is None:
            continue
        # Keep numbers/letters as pixels. OCR text is audit/timing metadata
        # only and is never typeset back into the card.
        # OCR may span several independent source objects. Never assign all
        # those pixels to whichever object happened to contain the most ink.
        # Each child stays with the exact parent from which it was extracted.
        for parent, body in enumerate(masks):
            child = ImageChops.multiply(selection, body)
            if child.getbbox():
                text_masks.append((text, child, parent, reading_id))
        claimed = ImageChops.lighter(claimed, selection)
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=final.parent))
    try:
        shutil.copy2(source, temporary / "original.png")
        # A punched-out original produces silhouettes wherever a cloud or
        # shadow used to run behind an object. Regenerate the *whole* entry
        # backdrop instead. Restore the visible original background only
        # after its foreground has settled; this is an explicit late layer,
        # not an original-card overlay concealing bad cutouts.
        background = field.convert("RGBA")
        background.save(temporary / "background.png")
        records = []; depth = 0
        for number, body in enumerate(masks, 1):
            bounds = body.getbbox()
            if not bounds:
                continue
            x,y,right,bottom = bounds; box = [x,y,right-x,bottom-y]
            pixels = original.copy()
            children = ImageChops.multiply(body, claimed)
            # Do not repaint the paper beneath OCR text with a median color.
            # Parent and child are disjoint original pixels composited inside
            # ONE rigid wrapper, so partial opacity cannot expose fake paint.
            parent_mask = ImageChops.subtract(body, children)
            if parent_mask.getbbox() is None:
                continue
            pixels.putalpha(parent_mask); pixels = pixels.crop(bounds)
            filename = f"object-{number:03d}.png"; pixels.save(temporary / filename)
            role = _role(box, original.size)
            records.append({"name":f"{role}-{number:03d}","role":role,"file":filename,
                            "sha256":file_sha(temporary/filename),"box":box,"z_index":depth,"moving":True,
                            "motion_group":f"object-{motion_groups[number-1]:03d}"})
            depth += 1
        for number, (text, selection, parent, reading_id) in enumerate(text_masks, 1):
            bounds = selection.getbbox(); x,y,right,bottom = bounds
            box = [x,y,right-x,bottom-y]; pixels = original.copy(); pixels.putalpha(selection)
            filename = f"text-{number:03d}.png"; pixels.crop(bounds).save(temporary / filename)
            records.append({"name":f"text-{number:03d}","role":_role(box,original.size,text),
                            "text":text,"file":filename,"sha256":file_sha(temporary/filename),
                            "reading_group":f"ocr-line-{reading_id:03d}",
                            "box":box,"z_index":depth,"moving":True,
                            "motion_group":f"object-{motion_groups[parent]:03d}"})
            depth += 1
        residual = original.copy()
        residual.putalpha(ImageChops.invert(occupied))
        if residual.getchannel("A").getbbox():
            residual.save(temporary / "visible-background.png")
            records.append({"name":"visible-background","role":"decoration",
                            "file":"visible-background.png",
                            "sha256":file_sha(temporary/"visible-background.png"),
                            "box":[0,0,width,height],"z_index":depth,"moving":False,
                            "reveal_after_motion":True})
        if len(records) > 128:
            raise LayerRepairRequired("한 장의 분리 요소가 128개를 초과했습니다")
        document = {"version":1,"source_file":"original.png","source_sha256":file_sha(source),
                    "size":[width,height],"provenance":VERSION,"input_sha256":file_sha(source),
                    "background":{"file":"background.png","sha256":file_sha(temporary/"background.png")},
                    "layers":records,"quality":{"ink_coverage":round(coverage,6),"ocr":ocr_meta,
                    "entry_background":"whole_frame_smooth_field",
                    "matte_resolution":[width,height],
                    "matte_method":"source_resolution_closed_paint",
                    "parent_text_compositing":"disjoint_original_pixels_in_rigid_group",
                    "occlusion_policy":"shared_source_ink_moves_as_one_rigid_group",
                    "background_dark_pixels":sum(_ink(background.convert("RGB")).histogram()[128:])},
                    "limitations":["Occluded artwork is not regenerated","OCR never rewrites source pixels",
                                   "Visible original background is restored after foreground entry"]}
        (temporary/"card.layers.json").write_text(json.dumps(document,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        check = load_source_card(temporary/"card.layers.json",temporary/"original.png")
        document["quality"]["reconstruction"] = check.reconstruction
        (temporary/"card.layers.json").write_text(json.dumps(document,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.rename(temporary,final)
        _publish_metadata(final, metadata, source)
    except Exception:
        # A diagnostic folder is intentionally preserved; never publish it as
        # a valid metadata file or return it as a ready source-card package.
        raise
    return metadata
