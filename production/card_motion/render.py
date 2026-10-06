#!/usr/bin/env python3
"""Render reviewed 4:5 carousel artwork as an element-led 9:16 Reel.

The source cards supply every visible word and illustration. A per-post
manifest selects bounded regions to lift and settle back into those cards.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
import io
import json
import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter


WIDTH, HEIGHT = 1080, 1920
CARD_WIDTH, CARD_HEIGHT = 1080, 1350
CARD_Y = (HEIGHT - CARD_HEIGHT) // 2


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def ease(value: float) -> float:
    progress = clamp(value)
    return 1 - (1 - progress) ** 4


def color(value: str) -> tuple[int, int, int]:
    return ImageColor.getrgb(value)


def numbers(value: Any, length: int, label: str) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{label} must contain {length} numbers")
    try:
        return tuple(int(part) for part in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain numbers") from exc


@dataclass(frozen=True)
class MaskShape:
    kind: str
    box: tuple[int, int, int, int]
    radius: int = 0
    subtract: bool = False


@dataclass(frozen=True)
class MotionTile:
    crop: tuple[int, int, int, int]
    shapes: tuple[MaskShape, ...]
    start: float
    duration: float
    offset: tuple[int, int]
    initial_scale: float = .965


@dataclass(frozen=True)
class Card:
    path: Path
    tiles: tuple[MotionTile, ...]
    accents: tuple[dict[str, Any], ...]


class CarouselReel:
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path.resolve()
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("reel-production.json version must be 1")
        self.data = data
        self.seconds_per_card = float(data.get("seconds_per_card", 6))
        self.fps = int(data.get("fps", 30))
        self.transition = float(data.get("transition", .28))
        if not 12 <= self.fps <= 60:
            raise ValueError("Frame rate is out of range")
        if not 0 <= self.transition <= .6:
            raise ValueError("Transition must be 0 to 0.6 seconds")

        palette = data.get("palette", {})
        if not isinstance(palette, dict) or not palette.get("paper") or not palette.get("accent"):
            raise ValueError("Choose paper and accent colors from the approved artwork")
        self.paper = color(palette["paper"])
        self.accent = color(palette["accent"])
        raw_cards = data.get("cards", [])
        if not isinstance(raw_cards, list) or not 4 <= len(raw_cards) <= 6:
            raise ValueError("A Reel needs 4 to 6 approved carousel cards")
        selected_durations = data.get("card_durations")
        if selected_durations is None:
            if not 3 <= self.seconds_per_card <= 12:
                raise ValueError("Legacy card length is out of range")
            self.card_durations = (self.seconds_per_card,) * len(raw_cards)
        else:
            if (not isinstance(selected_durations, list)
                    or len(selected_durations) != len(raw_cards)
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           for value in selected_durations)):
                raise ValueError("card_durations must contain one number per card")
            self.card_durations = tuple(float(value) for value in selected_durations)
            if any(not 1 <= value <= 12 for value in self.card_durations):
                raise ValueError("Card length is out of range")
        if data.get("timing_policy") == "cover2_inner1_5":
            expected = (2.0,) + (1.5,) * (len(raw_cards) - 1)
            if self.card_durations != expected:
                raise ValueError("Card-news timing must be 2s for the cover and 1.5s afterward")
        starts = [0.0]
        for length in self.card_durations:
            starts.append(starts[-1] + length)
        self.card_starts = tuple(starts)
        self.duration = starts[-1]
        self.cards = tuple(self._parse_card(item, index) for index, item in enumerate(raw_cards))

        audio = data.get("audio")
        self.audio = self._relative_path(audio) if audio else None
        if self.audio and not self.audio.is_file():
            raise FileNotFoundError(f"Audio missing: {self.audio}")
        self._source_cache: dict[int, Image.Image] = {}
        self._layer_cache: dict[int, tuple[Image.Image, tuple[tuple[Image.Image, MotionTile], ...]]] = {}
        self._validate_cards()

    def _relative_path(self, value: str) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else self.manifest_path.parent / path).resolve()

    def _parse_card(self, value: dict[str, Any], index: int) -> Card:
        if not isinstance(value, dict) or not isinstance(value.get("file"), str):
            raise ValueError(f"Card {index + 1} needs a file")
        path = self._relative_path(value["file"])
        tiles = []
        for tile in value.get("tiles", []):
            crop = numbers(tile.get("crop"), 4, "crop")
            shapes = tuple(MaskShape(
                kind=shape.get("kind", "round"),
                box=numbers(shape.get("box"), 4, "mask box"),
                radius=int(shape.get("radius", 0)),
                subtract=bool(shape.get("subtract", False)),
            ) for shape in tile.get("shapes", []))
            offset = numbers(tile.get("offset", [0, 0]), 2, "offset")
            motion = MotionTile(crop, shapes, float(tile.get("start", 0)),
                                float(tile.get("duration", .45)), offset,
                                float(tile.get("initial_scale", .965)))
            if not shapes or motion.duration <= 0 or motion.start < 0:
                raise ValueError(f"Card {index + 1} has an invalid motion tile")
            if motion.start + motion.duration > self.card_durations[index] - self.transition:
                raise ValueError(f"Card {index + 1} tile settles too late")
            if not .9 <= motion.initial_scale <= 1.0:
                raise ValueError("Initial scale must be between 0.9 and 1.0")
            tiles.append(motion)
        return Card(path, tuple(tiles), tuple(value.get("accents", [])))

    def _validate_cards(self) -> None:
        for index, card in enumerate(self.cards):
            if not card.path.is_file():
                raise FileNotFoundError(f"Card missing: {card.path}")
            with Image.open(card.path) as image:
                if abs(image.width / image.height - .8) > .012:
                    raise ValueError(f"Card {index + 1} must be 4:5: {image.size}")
                for tile in card.tiles:
                    x1, y1, x2, y2 = tile.crop
                    if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
                        raise ValueError(f"Card {index + 1} has a crop outside the image")
                    for shape in tile.shapes:
                        if shape.kind not in {"round", "ellipse"}:
                            raise ValueError(f"Card {index + 1} has an unknown mask shape")

    def source_card(self, index: int) -> Image.Image:
        if index not in self._source_cache:
            self._source_cache[index] = Image.open(self.cards[index].path).convert("RGBA")
        return self._source_cache[index]

    def layered_page(self, index: int) -> tuple[Image.Image, tuple[tuple[Image.Image, MotionTile], ...]]:
        if index in self._layer_cache:
            return self._layer_cache[index]
        source = self.source_card(index)
        base = source.copy()
        prepared = []
        for spec in self.cards[index].tiles:
            x1, y1, x2, y2 = spec.crop
            mask = Image.new("L", (x2 - x1, y2 - y1), 0)
            draw = ImageDraw.Draw(mask)
            for shape in spec.shapes:
                sx1, sy1, sx2, sy2 = shape.box
                box = (sx1 - x1, sy1 - y1, sx2 - x1, sy2 - y1)
                fill = 0 if shape.subtract else 255
                if shape.kind == "ellipse":
                    draw.ellipse(box, fill=fill)
                else:
                    draw.rounded_rectangle(box, radius=shape.radius, fill=fill)
            tile = source.crop(spec.crop)
            tile.putalpha(mask)
            source_mask = Image.new("L", source.size, 0)
            source_mask.paste(mask, (x1, y1))
            paper = Image.new("RGBA", source.size, (*self.paper, 255))
            base.paste(paper, (0, 0), source_mask)
            prepared.append((tile, spec))
        result = base, tuple(prepared)
        self._layer_cache[index] = result
        return result

    @staticmethod
    def _draw_tile(canvas: Image.Image, tile: Image.Image, spec: MotionTile, local: float) -> None:
        progress = ease((local - spec.start) / spec.duration)
        if progress <= 0:
            return
        width, height = tile.size
        scale = spec.initial_scale + (1 - spec.initial_scale) * progress
        scaled = tile.resize((max(1, round(width * scale)), max(1, round(height * scale))),
                             Image.Resampling.LANCZOS)
        sx, sy = scaled.size
        x1, y1, x2, y2 = spec.crop
        x = round((x1 + x2 - sx) / 2 + spec.offset[0] * (1 - progress))
        y = round((y1 + y2 - sy) / 2 + spec.offset[1] * (1 - progress))
        if progress < .96:
            alpha = scaled.getchannel("A").filter(ImageFilter.GaussianBlur(10))
            strength = round(20 * (1 - progress) ** 1.5)
            alpha = alpha.point(lambda value: value * strength // 255)
            shadow = Image.new("RGBA", scaled.size, (16, 28, 48, 0))
            shadow.putalpha(alpha)
            canvas.alpha_composite(shadow, (x, y + 6))
        canvas.alpha_composite(scaled, (x, y))

    def element_card(self, index: int, local: float) -> Image.Image:
        base, prepared = self.layered_page(index)
        result = base.copy()
        for tile, spec in prepared:
            self._draw_tile(result, tile, spec, local)
        return result

    def verify_settled_cards(self) -> None:
        """A landed animation must reproduce the approved source pixels."""
        for index in range(len(self.cards)):
            actual = self.element_card(index, self.card_durations[index] - .1).convert("RGB")
            source = self.source_card(index).convert("RGB")
            if ImageChops.difference(actual, source).getbbox() is not None:
                raise ValueError(f"Card {index + 1} does not reconstruct its approved artwork")

    def _accent_overlay(self, index: int, local: float) -> Image.Image:
        source = self.source_card(index)
        overlay = Image.new("RGBA", source.size)
        draw = ImageDraw.Draw(overlay)
        for event in self.cards[index].accents:
            kind = event.get("type")
            start = float(event.get("start", 0))
            duration = float(event.get("duration", .5))
            if duration <= 0 or not start < local < start + duration:
                continue
            progress = (local - start) / duration
            event_color = color(event.get("color", "#0f52ff"))
            if kind == "line_sweep":
                x1, y1, x2, y2 = numbers(event.get("box"), 4, "line sweep box")
                radius = int(event.get("radius", 7))
                x = round(x1 + (x2 - x1) * ease(progress))
                draw.ellipse((x - radius, y1 - radius, x + radius, y2 + radius),
                             fill=(*event_color, 175))
            elif kind == "ring_pulse":
                x, y = numbers(event.get("center"), 2, "ring center")
                pulse = math.sin(progress * math.pi)
                radius = int(event.get("radius", 88)) + int(event.get("spread", 10)) * pulse
                alpha = round(int(event.get("alpha", 165)) * pulse)
                thickness = int(event.get("width", 6))
                draw.ellipse((round(x - radius), round(y - radius),
                              round(x + radius), round(y + radius)),
                             outline=(*event_color, alpha), width=thickness)
            else:
                raise ValueError(f"Unknown accent type: {kind}")
        return overlay

    def compose_card(self, index: int, local: float) -> Image.Image:
        artwork = self.element_card(index, local)
        artwork.alpha_composite(self._accent_overlay(index, local))
        card = artwork.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (WIDTH, HEIGHT), (*self.paper, 255))
        shadow = Image.new("RGBA", (WIDTH, HEIGHT))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (18, CARD_Y + 11, WIDTH - 18, CARD_Y + CARD_HEIGHT + 20),
            radius=8, fill=(25, 34, 51, 34))
        canvas.alpha_composite(shadow)
        canvas.alpha_composite(card, (0, CARD_Y))

        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((74, 179, 1006, 190), radius=6, fill=(219, 220, 216))
        fraction = (self.card_starts[index] + local) / self.duration
        draw.rounded_rectangle((74, 179, 74 + round(932 * fraction), 190),
                               radius=6, fill=self.accent)
        for n in range(len(self.cards)):
            x = WIDTH // 2 + 18 * (n - (len(self.cards) - 1) / 2)
            radius = 5 if n == index else 4
            dot_color = self.accent if n == index else (210, 213, 214)
            draw.ellipse((round(x - radius), 174 - radius,
                          round(x + radius), 174 + radius), fill=dot_color)
        return canvas.convert("RGB")

    def frame(self, time: float) -> Image.Image:
        time = max(0.0, min(self.duration - .001, time))
        index = min(len(self.cards) - 1, bisect_right(self.card_starts, time) - 1)
        local = time - self.card_starts[index]
        current = self.compose_card(index, local)
        if index == 0 or local >= self.transition or self.transition == 0:
            return current
        progress = ease(local / self.transition)
        previous = self.compose_card(index - 1, self.card_durations[index - 1] - .001)
        offset = round(WIDTH * progress)
        out = Image.new("RGB", (WIDTH, HEIGHT), self.paper)
        out.paste(previous, (-offset, 0))
        out.paste(current, (WIDTH - offset, 0))
        return out

    def _encoded_still(self, video: Path, moment: float) -> Image.Image:
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(moment),
                   "-i", str(video), "-frames:v", "1", "-f", "image2pipe",
                   "-vcodec", "png", "pipe:1"]
        result = subprocess.run(command, capture_output=True, check=True)
        return Image.open(io.BytesIO(result.stdout)).convert("RGB")

    def proof_sheet(self, path: Path, video: Path | None = None) -> None:
        columns = min(3, len(self.cards))
        rows = math.ceil(len(self.cards) / columns)
        thumb_width, thumb_height, gap = 270, 480, 14
        sheet = Image.new("RGB", (columns * (thumb_width + gap) + gap,
                                  rows * (thumb_height + gap) + gap), self.paper)
        for index in range(len(self.cards)):
            moment = self.card_starts[index] + .58 * self.card_durations[index]
            still = self._encoded_still(video, moment) if video else self.frame(moment)
            thumb = still.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
            x = gap + (index % columns) * (thumb_width + gap)
            y = gap + (index // columns) * (thumb_height + gap)
            sheet.paste(thumb, (x, y))
        path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(path)

    def motion_sheet(self, video: Path, path: Path) -> None:
        """Inspect early/late element animation in the encoded output."""
        thumb_width, thumb_height, gap = 216, 384, 12
        sheet = Image.new("RGB", (len(self.cards) * (thumb_width + gap) + gap,
                                  2 * (thumb_height + gap) + gap), self.paper)
        for row in range(2):
            for index in range(len(self.cards)):
                length = self.card_durations[index]
                local = min(.25, length * .2) if row == 0 else length - .15
                moment = self.card_starts[index] + local
                still = self._encoded_still(video, moment)
                thumb = still.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
                sheet.paste(thumb, (gap + index * (thumb_width + gap),
                                    gap + row * (thumb_height + gap)))
        path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(path)

    def _check_audio_length(self) -> None:
        if not self.audio:
            return
        command = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1:nokey=1", str(self.audio)]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        if float(result.stdout.strip()) < self.duration - .1:
            raise ValueError(f"Audio is shorter than the {self.duration:.1f}s Reel")

    def render(self, output: Path) -> Path:
        self.verify_settled_cards()
        self._check_audio_length()
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.stem}.partial-{os.getpid()}.mp4")
        command = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
                   "-f", "rawvideo", "-pixel_format", "rgb24",
                   "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(self.fps),
                   "-i", "pipe:0"]
        if self.audio:
            command.extend(["-i", str(self.audio), "-map", "0:v:0", "-map", "1:a:0"])
        command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-pix_fmt", "yuv420p"])
        if self.audio:
            command.extend(["-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2"])
        command.extend(["-t", str(self.duration), "-movflags", "+faststart", str(temporary)])
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
        try:
            assert process.stdin is not None
            for number in range(round(self.duration * self.fps)):
                process.stdin.write(self.frame(number / self.fps).tobytes())
        except BrokenPipeError:
            pass
        finally:
            if process.stdin:
                process.stdin.close()
        if process.wait() != 0:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg could not render the Reel")
        os.replace(temporary, output)
        return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Render reviewed 4:5 carousel cards as a Reel")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preview-time", type=float)
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    reel = CarouselReel(args.manifest)
    reel.verify_settled_cards()
    if args.check_only:
        print(json.dumps({"cards": len(reel.cards), "duration": reel.duration,
                          "audio": bool(reel.audio)}, ensure_ascii=False))
        return
    if args.preview_time is not None:
        output = args.output or args.manifest.with_name("reel-preview.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        reel.frame(args.preview_time).save(output)
        print(output)
        return
    output = args.output or args.manifest.with_name("reel.mp4")
    if output.exists():
        raise SystemExit(f"Output already exists: {output}")
    print(reel.render(output))
    if args.proof:
        reel.proof_sheet(args.proof, video=output)
        print(args.proof)


if __name__ == "__main__":
    main()
