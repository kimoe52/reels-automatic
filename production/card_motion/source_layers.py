"""Validated layer-first card assets shared by card and Reel production.

These are either producer-exported pixels or explicitly identified local
flat-card extractions. Both must reconstruct the supplied original. Extraction
does not claim to recover artwork hidden behind another object.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

from element_layers import Element


class LayerRepairRequired(ValueError):
    pass


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained_file(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise LayerRepairRequired("레이어 파일 경로가 없습니다")
    value = Path(relative)
    target = (root / value).resolve()
    if value.is_absolute() or ".." in value.parts or not target.is_relative_to(root.resolve()):
        raise LayerRepairRequired("레이어 경로가 제작 폴더 밖입니다")
    if not target.is_file():
        raise LayerRepairRequired(f"레이어 파일이 없습니다: {value.name}")
    return target


def read_rgba(path: Path, sha: Any) -> Image.Image:
    if not isinstance(sha, str) or file_sha(path) != sha:
        raise LayerRepairRequired(f"레이어 원본 해시가 다릅니다: {path.name}")
    with Image.open(path) as image:
        if image.mode != "RGBA":
            raise LayerRepairRequired(f"투명 RGBA 레이어가 아닙니다: {path.name}")
        return image.copy()


def reconstruction_metrics(original: Image.Image, composite: Image.Image) -> dict[str, float]:
    difference = ImageChops.difference(original.convert("RGB"), composite.convert("RGB"))
    channels = difference.split()
    maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    histogram = maximum.histogram()
    pixels = original.width * original.height
    return {"mean_error": round(sum(ImageStat.Stat(difference).mean) / 3, 6),
            "significant_share": round(sum(histogram[9:]) / pixels, 6),
            "max_error": max(index for index, count in enumerate(histogram) if count)}


@dataclass
class SourceCard:
    metadata: Path
    original: Path
    size: tuple[int, int]
    background: Path
    layers: list[dict[str, Any]]
    reconstruction: dict[str, float]
    provenance: str = ""

    def elements(self) -> tuple[Element, ...]:
        moving = sorted((item for item in self.layers if item["moving"]),
                        key=lambda item: (item["box"][1], item["box"][0], item["z_index"]))
        delays = {item["name"]: min(5000, index * 100) for index, item in enumerate(moving)}
        return tuple(Element(item["name"], tuple(item["box"]), "source",
                             delays[item["name"]], repair=True,
                             role=item["role"], effect="settle_fade" if item["role"] == "title" else "rise_fade")
                     for item in self.layers if item["moving"])


def load_source_card(metadata: Path, original: Path, declared_sha: str | None = None) -> SourceCard:
    metadata, original = metadata.resolve(), original.resolve()
    try:
        if declared_sha and file_sha(metadata) != declared_sha:
            raise LayerRepairRequired("레이어 구성 파일의 승인 해시가 다릅니다")
        data = json.loads(metadata.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise LayerRepairRequired("레이어 구성 버전을 확인할 수 없습니다")
        source = contained_file(metadata.parent, data.get("source_file"))
        if source != original or file_sha(source) != data.get("source_sha256"):
            raise LayerRepairRequired("레이어와 카드 원본이 일치하지 않습니다")
        with Image.open(original) as opened:
            image = opened.convert("RGBA")
        size = image.size
        if data.get("size") != list(size):
            raise LayerRepairRequired("레이어 제작 규격과 카드 크기가 다릅니다")
        background_record = data.get("background")
        if not isinstance(background_record, dict):
            raise LayerRepairRequired("별도 배경 레이어가 없습니다")
        background = contained_file(metadata.parent, background_record.get("file"))
        composite = read_rgba(background, background_record.get("sha256"))
        if composite.size != size:
            raise LayerRepairRequired("배경 레이어 크기가 카드와 다릅니다")
        if str(data.get("provenance", "")).startswith("flat-pixels-"):
            rgb = composite.convert("RGB")
            field = rgb.crop((0,0,1,size[1])).resize(size)
            if ImageChops.difference(rgb,field).getbbox() or min(ImageStat.Stat(rgb).extrema[c][0] for c in range(3)) < 140:
                raise LayerRepairRequired("자동 재생성 배경에 요소 잔상이나 어두운 픽셀이 있습니다")
        raw = data.get("layers")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 128:
            raise LayerRepairRequired("카드 원본 레이어 1~128개가 필요합니다")
        layers, names, depths = [], set(), set()
        for record in raw:
            if not isinstance(record, dict):
                raise LayerRepairRequired("레이어 항목이 올바르지 않습니다")
            name, box, depth = record.get("name"), record.get("box"), record.get("z_index")
            if not isinstance(name, str) or not 1 <= len(name) <= 80 or name in names:
                raise LayerRepairRequired("레이어 이름이 없거나 중복됩니다")
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(value) is not int for value in box)):
                raise LayerRepairRequired(f"{name}의 레이어 좌표가 올바르지 않습니다")
            x, y, w, h = box
            if x < 0 or y < 0 or w < 1 or h < 1 or x + w > size[0] or y + h > size[1]:
                raise LayerRepairRequired(f"{name}의 레이어가 카드 밖입니다")
            if type(depth) is not int or depth in depths or type(record.get("moving")) is not bool:
                raise LayerRepairRequired(f"{name}의 순서 또는 모션 여부가 올바르지 않습니다")
            if "reveal_after_motion" in record and (type(record["reveal_after_motion"]) is not bool
                    or record["reveal_after_motion"] and record["moving"]):
                raise LayerRepairRequired(f"{name}의 배경 복원 순서가 올바르지 않습니다")
            if record.get("role") not in {"title", "text", "bubble", "character", "prop", "panel", "decoration"}:
                raise LayerRepairRequired(f"{name}의 역할이 올바르지 않습니다")
            for group_key in ("motion_group", "reading_group"):
                if group_key in record and (not isinstance(record[group_key], str)
                        or not record[group_key].strip() or len(record[group_key]) > 80):
                    raise LayerRepairRequired(f"{name}의 {group_key} 식별자가 올바르지 않습니다")
            path = contained_file(metadata.parent, record.get("file"))
            pixels = read_rgba(path, record.get("sha256"))
            if pixels.size != (w, h) or pixels.getchannel("A").getbbox() is None:
                raise LayerRepairRequired(f"{name}의 실제 투명 이미지와 좌표가 다릅니다")
            names.add(name); depths.add(depth)
            layers.append({**record, "path": path})
        layers.sort(key=lambda item: item["z_index"])
        for item in layers:
            pixels = read_rgba(item["path"], item["sha256"])
            composite.alpha_composite(pixels, tuple(item["box"][:2]))
        metrics = reconstruction_metrics(image, composite)
        if ImageChops.difference(image.getchannel("A"), composite.getchannel("A")).getbbox():
            raise LayerRepairRequired("레이어 재합성의 투명도가 카드 원본과 다릅니다")
        # Browser/native antialiasing can round edge colors differently. This
        # bounded allowance cannot conceal a missing panel, word, or figure.
        if metrics["mean_error"] > .2 or metrics["significant_share"] > .001:
            raise LayerRepairRequired(f"레이어 재합성이 원본과 다릅니다: {metrics}")
        if not any(item["moving"] for item in layers):
            raise LayerRepairRequired("움직일 원본 요소가 없습니다")
        return SourceCard(metadata, original, size, background, layers, metrics,
                          str(data.get("provenance") or "producer"))
    except LayerRepairRequired:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LayerRepairRequired(f"원본 레이어를 읽을 수 없습니다: {exc}") from exc


def prepare_source_layers(card: SourceCard, elements: tuple[Element, ...], output: Path) -> dict[str, Any]:
    """Copy authoritative RGBA assets, preserving paint order and overlap."""
    if output.exists():
        metadata = output / "elements.json"
        if metadata.is_file():
            return json.loads(metadata.read_text(encoding="utf-8"))
        raise LayerRepairRequired("미완성 레이어 출력 폴더를 보존했습니다")
    output.mkdir(parents=True)
    by_name = {item.name: item for item in elements}
    with Image.open(card.background) as image:
        clean = image.convert("RGBA")
    records = []
    for index, item in enumerate(card.layers, 1):
        element = by_name.get(item["name"])
        if item["moving"] and element is None:
            raise LayerRepairRequired(f"원본 요소가 모션 계획에서 누락됐습니다: {item['name']}")
        filename = f"element-{index:03d}.png"
        shutil.copy2(item["path"], output / filename)
        records.append({"name": item["name"], "file": filename, "box": item["box"],
                        "mask": "source", "delay_ms": element.delay_ms if element else 0,
                        "repair": bool(item["moving"]), "moving": item["moving"],
                        "focus_file": None, "role": item["role"],
                        "effect": element.effect if element else "", "z_index": item["z_index"],
                        "motion_group": item.get("motion_group", item["name"]),
                        "reveal_after_motion": bool(item.get("reveal_after_motion")),
                        "background_method": "flat_extracted_pixels" if card.provenance.startswith("flat-") else "authoritative_layers"})
    clean.save(output / "clean-plate.png")
    report = {"clean_plate": "clean-plate.png", "elements": records,
              "reconstruction": card.reconstruction, "source_layers": str(card.metadata)}
    (output / "elements.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
