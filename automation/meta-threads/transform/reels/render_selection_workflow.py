#!/usr/bin/env python3
"""Render a source-mapped generate → choose → refine workflow reel.

The storyboard owns copy, timing, source quotes, and audio. This renderer owns
only the reusable scene grammar. Its abstract thumbnails are explanatory art,
never a capture or a claim about any video model's output.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


W, H = 1080, 1920
PAPER = (249, 251, 253)
INK = (25, 39, 50)
BLUE = (38, 91, 218)
PALE = (224, 235, 253)
DEEP = (27, 57, 105)
ORANGE = (237, 143, 102)
MUTED = (105, 119, 134)
RULE = (197, 210, 222)
WHITE = (255, 255, 255)


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def ease(value: float) -> float:
    x = clamp(value)
    return 1 - (1 - x) ** 3


def smooth(value: float) -> float:
    x = clamp(value)
    return x * x * (3 - 2 * x)


def between(a: float, b: float, p: float) -> float:
    return a + (b - a) * p


def color_rgba(rgb: tuple[int, int, int], opacity: float) -> tuple[int, int, int, int]:
    return (*rgb, round(255 * clamp(opacity)))


def visible(t: float, start: float, duration: float = .32) -> float:
    return ease((t - start) / duration)


class Reel:
    def __init__(self, root: Path, plan: dict, source: dict):
        self.root = root
        self.plan = plan
        self.source = source
        self.fps = int(plan["fps"])
        self.duration = float(plan["duration_seconds"])
        self.beats = plan["beats"]
        self._validate()

    def _validate(self) -> None:
        if (int(self.plan["width"]), int(self.plan["height"])) != (W, H):
            raise ValueError("This renderer requires a 1080×1920 canvas")
        if self.plan["post_id"] != self.source["id"]:
            raise ValueError("Storyboard and source post IDs differ")
        if self.plan["format"] != "instagram_reel":
            raise ValueError("Expected an Instagram reel storyboard")
        exact = ["hook", "variants", "select", "upscale", "contrast", "takeaway"]
        if [beat["id"] for beat in self.beats] != exact:
            raise ValueError("This scene grammar requires generate/select/refine beats")
        if abs(float(self.beats[0]["start"])) > 1e-6:
            raise ValueError("Timeline does not start at zero")
        for first, second in zip(self.beats, self.beats[1:]):
            if abs(float(first["end"]) - float(second["start"])) > 1e-6:
                raise ValueError("Timeline has a gap or overlap")
        if abs(float(self.beats[-1]["end"]) - self.duration) > 1e-6:
            raise ValueError("Timeline does not reach duration")
        source_text = re.sub(r"\s+", " ", self.source["text"]).strip()
        for beat in self.beats:
            quote = re.sub(r"\s+", " ", beat["source_quote"]).strip()
            if quote not in source_text:
                raise ValueError(f"Unmatched source quote for {beat['id']}: {quote}")
            if not beat["copy"]:
                raise ValueError(f"Missing copy for {beat['id']}")

    @lru_cache(maxsize=20)
    def font(self, size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(
            self.root / "assets" / "fonts" / f"Pretendard-{weight}.otf", size
        )

    def text(self, im: Image.Image, value: str, x: int, y: int, size: int,
             *, weight="Regular", fill=INK, opacity=1.0,
             width=956, anchor="left", rise=0) -> None:
        if opacity <= 0:
            return
        face = self.font(size, weight)
        length = round(face.getlength(value))
        if length > width:
            raise ValueError(f"Text overflow {length}>{width}: {value}")
        if anchor == "center":
            x -= length // 2
        if x < 35 or x + length > W - 35:
            raise ValueError(f"Unsafe text x: {value} at {x}")
        layer = Image.new("RGBA", (W, H))
        ImageDraw.Draw(layer).text((x, y + round(rise * (1 - opacity))), value,
                                   font=face, fill=color_rgba(fill, opacity))
        im.paste(layer, (0, 0), layer.getchannel("A"))

    @lru_cache(maxsize=8)
    def art(self, variant: int) -> Image.Image:
        """Four generated conceptual movie frames, never a real app capture."""
        sheet = Image.open(self.root / "assets" / "rainy-crosswalk-four-frames.png")
        sheet = sheet.convert("RGB")
        mid_x, mid_y = sheet.width // 2, sheet.height // 2
        margin = 3
        boxes = (
            (0, 0, mid_x - margin, mid_y - margin),
            (mid_x + margin, 0, sheet.width, mid_y - margin),
            (0, mid_y + margin, mid_x - margin, sheet.height),
            (mid_x + margin, mid_y + margin, sheet.width, sheet.height),
        )
        return sheet.crop(boxes[variant % 4])

    def tile(self, im: Image.Image, variant: int, x: int, y: int,
             width: int, height: int, *, opacity: float = 1.0,
             mode="low", selected=False, label="") -> None:
        if opacity <= 0 or width <= 0 or height <= 0:
            return
        source = ImageOps.fit(self.art(variant), (width, height),
                              method=Image.Resampling.LANCZOS)
        if mode == "low":
            source = source.resize((max(1, width // 3), max(1, height // 3)),
                                   Image.Resampling.BILINEAR)
            source = source.resize((width, height), Image.Resampling.NEAREST)
        mask = Image.new("L", (width, height))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1),
                                               radius=min(22, width // 12), fill=round(255 * clamp(opacity)))
        im.paste(source, (x, y), mask)
        border = Image.new("RGBA", (W, H))
        ImageDraw.Draw(border).rounded_rectangle(
            (x, y, x + width - 1, y + height - 1), radius=min(22, width // 12),
            outline=color_rgba(BLUE if selected else (188, 207, 221), opacity),
            width=7 if selected else 3
        )
        im.paste(border, (0, 0), border.getchannel("A"))
        if label:
            self.text(im, label, x + 4, y + height + 22, 34,
                      weight="SemiBold", fill=BLUE if selected else MUTED,
                      opacity=opacity, width=width - 10)

    def hook(self, t: float, copy: list[str]) -> Image.Image:
        im = Image.new("RGB", (W, H), PAPER)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, W, 20), fill=BLUE)
        self.text(im, "@sto.ckai  /  AI VIDEO", 69, 130, 33,
                  weight="SemiBold", fill=BLUE)
        self.text(im, copy[0], 65, 330, 77, weight="SemiBold",
                  opacity=visible(t, .02), rise=45)
        self.text(im, copy[1], 60, 445, 99, weight="Bold",
                  opacity=visible(t, .15), rise=60)
        p = visible(t, .28, .55)
        self.tile(im, 0, 70, 775 + round((1 - p) * 120), 940, 626,
                  opacity=p, mode="low")
        for i in range(3):
            p = visible(t, .59 + .16 * i, .28)
            self.tile(im, i + 1, 70 + i * 320, 1450 + round((1 - p) * 80),
                      300, 169, opacity=p, mode="low")
        self.text(im, "실패작까지 고해상도로?", 72, 1675, 46,
                  weight="SemiBold", fill=MUTED, opacity=visible(t, 1.03))
        return im

    def variants(self, t: float, copy: list[str]) -> Image.Image:
        im = Image.new("RGB", (W, H), PAPER)
        d = ImageDraw.Draw(im)
        self.text(im, copy[0], 68, 160, 76, weight="Bold",
                  opacity=visible(t, .03), rise=45)
        self.text(im, copy[1], 70, 275, 46, fill=MUTED,
                  opacity=visible(t, .28))
        positions = ((70, 575), (570, 575), (70, 1055), (570, 1055))
        for i, (x, y) in enumerate(positions):
            p = visible(t, .35 + .27 * i, .48)
            self.tile(im, i, x, y + round((1 - p) * 85), 440, 248,
                      opacity=p, mode="low", label=f"시안 {i + 1:02d}")
        d.line((71, 1480, 1009, 1480), fill=RULE, width=3)
        self.text(im, "마음에 드는 장면을 먼저 찾기", 71, 1530, 43,
                  fill=DEEP, opacity=visible(t, 2.1))
        self.text(im, "개념 그림 · 실제 AI 결과 아님", 72, 1745, 30, fill=MUTED)
        return im

    def select(self, t: float, copy: list[str]) -> Image.Image:
        im = Image.new("RGB", (W, H), PAPER)
        self.text(im, copy[0], 66, 208, 82, weight="Bold",
                  opacity=visible(t, .05), rise=45)
        positions = ((70, 575), (570, 575), (70, 1055), (570, 1055))
        move = smooth((t - .2) / 1.32)
        for i, (x, y) in enumerate(positions):
            if i == 0:
                continue
            self.tile(im, i, x, y, 440, 248,
                      opacity=1 - ease((t - .16) / .65), mode="low")
        x0, y0 = positions[0]
        x = round(between(x0, 70, move))
        y = round(between(y0, 670, move))
        width = round(between(440, 940, move))
        height = round(between(248, 529, move))
        self.tile(im, 0, x, y, width, height, mode="low", selected=move > .2)
        self.text(im, "이 한 장면만", 73, 1410, 51,
                  fill=BLUE, weight="SemiBold", opacity=visible(t, 1.05))
        self.text(im, "개념 그림 · 실제 AI 결과 아님", 72, 1745, 30, fill=MUTED)
        return im

    def upscale(self, t: float, copy: list[str]) -> Image.Image:
        im = Image.new("RGB", (W, H), PAPER)
        self.text(im, copy[0], 68, 170, 72, weight="SemiBold",
                  opacity=visible(t, .04))
        self.text(im, copy[1], 62, 285, 97, weight="Bold", fill=BLUE,
                  opacity=visible(t, .16), rise=55)
        x, y, width, height = 70, 645, 940, 529
        self.tile(im, 0, x, y, width, height, mode="low")
        sharp = ImageOps.fit(self.art(0), (width, height),
                             method=Image.Resampling.LANCZOS)
        reveal = smooth((t - .7) / 2.1)
        if reveal > 0:
            cutoff = round(width * reveal)
            im.paste(sharp.crop((width - cutoff, 0, width, height)),
                     (x + width - cutoff, y))
            d = ImageDraw.Draw(im)
            d.line((x + width - cutoff, y - 16,
                    x + width - cutoff, y + height + 16),
                   fill=BLUE, width=7)
            d.ellipse((x + width - cutoff - 15, y + height // 2 - 15,
                       x + width - cutoff + 15, y + height // 2 + 15),
                      fill=BLUE)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((x, y, x + width, y + height), radius=22,
                            outline=BLUE, width=4)
        self.text(im, "480p", 76, 1234, 47, weight="Bold", fill=MUTED)
        self.text(im, "→", 494, 1217, 72, weight="Bold", fill=BLUE)
        self.text(im, "720p / 1080p", 681, 1234, 43,
                  weight="Bold", fill=BLUE, width=330)
        self.text(im, "새로 생성하는 게 아님", 73, 1450, 50,
                  weight="SemiBold", opacity=visible(t, 2.3))
        self.text(im, "개념 그림 · 실제 업스케일 결과 아님", 72, 1745, 30,
                  fill=MUTED)
        return im

    def contrast(self, t: float, copy: list[str]) -> Image.Image:
        im = Image.new("RGB", (W, H), PAPER)
        self.text(im, "같은 프롬프트여도", 68, 155, 60,
                  weight="SemiBold", opacity=visible(t, .02))
        self.text(im, "다시 생성 ≠ 업스케일", 64, 260, 79,
                  weight="Bold", fill=DEEP, opacity=visible(t, .13))
        self.tile(im, 0, 340, 510, 400, 225, mode="low",
                  opacity=visible(t, .12))
        d = ImageDraw.Draw(im)
        branch = visible(t, .48, .65)
        if branch:
            d.line((540, 760, 540, 855), fill=RULE, width=5)
            d.line((305, 855, 775, 855), fill=RULE, width=5)
            d.line((305, 855, 305, 975), fill=ORANGE, width=6)
            d.line((775, 855, 775, 975), fill=BLUE, width=6)
        self.tile(im, 1, 64, 1000, 440, 248,
                  mode="sharp", opacity=visible(t, .75, .35))
        self.tile(im, 0, 576, 1000, 440, 248,
                  mode="sharp", opacity=visible(t, .98, .35), selected=True)
        self.text(im, copy[0], 66, 1290, 45,
                  weight="Bold", fill=ORANGE, opacity=visible(t, 1.1))
        self.text(im, copy[2], 576, 1290, 45,
                  weight="Bold", fill=BLUE, opacity=visible(t, 1.28))
        self.text(im, copy[1], 66, 1365, 38,
                  fill=MUTED, opacity=visible(t, 1.35), width=455)
        self.text(im, copy[3], 576, 1365, 38,
                  fill=MUTED, opacity=visible(t, 1.5), width=440)
        self.text(im, "개념 그림 · 실제 AI 결과 아님", 72, 1745, 30, fill=MUTED)
        return im

    def takeaway(self, t: float, copy: list[str]) -> Image.Image:
        im = Image.new("RGB", (W, H), PALE)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, W, 19), fill=BLUE)
        self.text(im, "한 줄 정리", 70, 174, 41,
                  weight="SemiBold", fill=BLUE)
        self.text(im, copy[0], 68, 435, 84,
                  weight="Bold", opacity=visible(t, .02), rise=44)
        line_progress = visible(t, .27, .52)
        d.line((70, 687, 70 + round(940 * line_progress), 687),
               fill=BLUE, width=7)
        self.text(im, copy[1], 68, 827, 84,
                  weight="Bold", fill=BLUE,
                  opacity=visible(t, .4), rise=44)
        self.text(im, "사용 도구의 해상도·비용 확인", 70, 1445, 41,
                  fill=MUTED, opacity=visible(t, 1.35))
        self.text(im, "@sto.ckai  ·  Threads 원문 기반", 70, 1725, 32,
                  fill=MUTED)
        return im

    def frame(self, t: float) -> Image.Image:
        for beat in self.beats:
            if float(beat["start"]) <= t < float(beat["end"]):
                scene = getattr(self, beat["id"])
                return scene(t - float(beat["start"]), beat["copy"])
        return self.takeaway(self.duration - float(self.beats[-1]["start"]) - .001,
                             self.beats[-1]["copy"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--preview-time", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    plan = json.loads((root / "storyboard.json").read_text(encoding="utf-8"))
    source = json.loads((root / plan["source_file"]).read_text(encoding="utf-8"))
    reel = Reel(root, plan, source)

    if args.preview_time is not None:
        out = args.output or root / "Previews" / f"frame-{args.preview_time:.1f}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        reel.frame(args.preview_time).save(out)
        print(out)
        return

    out = args.output or root / "reel-480p-upscale-pilot.mp4"
    music = root / plan["audio_file"]
    duration = reel.duration
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
           "-f", "rawvideo", "-pixel_format", "rgb24",
           "-video_size", f"{W}x{H}", "-framerate", str(reel.fps),
           "-i", "pipe:0", "-i", str(music),
           "-filter_complex",
           f"[1:a]atrim=0:{duration},loudnorm=I=-15:TP=-1.5:LRA=8,volume=-2dB,"
           f"afade=t=in:st=0:d=0.18,afade=t=out:st={duration-0.8}:d=0.8[a]",
           "-map", "0:v:0", "-map", "[a]", "-c:v", "libx264",
           "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
           "-t", str(duration), "-movflags", "+faststart", str(out)]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for index in range(round(duration * reel.fps)):
            process.stdin.write(reel.frame(index / reel.fps).tobytes())
    except BrokenPipeError:
        pass
    finally:
        if process.stdin:
            process.stdin.close()
    if process.wait():
        raise SystemExit("FFmpeg render failed")
    report = root / ".tesseract-work" / "render-report.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps({
        "output": str(out), "source_post": source["permalink"],
        "source_quotes_validated": True,
        "duration": duration, "fps": reel.fps,
        "concept_art_not_actual_ai_output": True,
        "music": plan["audio_file"], "renderer": "Pillow + FFmpeg"
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
