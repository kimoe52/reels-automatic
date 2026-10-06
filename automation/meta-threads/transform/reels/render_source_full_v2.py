#!/usr/bin/env python3
"""Render a source-complete Threads reel over relevant faded photography.

The source/storyboard owns every claim. The two generated desk photographs are
staged explanatory backgrounds, never represented as actual product screens.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


W, H = 1080, 1920
INK = (26, 38, 48)
BLUE = (35, 85, 170)
ORANGE = (197, 83, 51)
MUTED = (90, 101, 113)
LINE = (174, 186, 196)
WHITE = (255, 255, 255)


def clamp(n: float) -> float:
    return max(0.0, min(1.0, n))


def ease(n: float) -> float:
    n = clamp(n)
    return 1 - (1 - n) ** 3


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class Reel:
    def __init__(self, root: Path):
        self.root = root
        self.plan = json.loads((root / "storyboard-v2.json").read_text(encoding="utf-8"))
        self.source = json.loads((root / self.plan["source_file"]).read_text(encoding="utf-8"))
        self.beats = self.plan["beats"]
        self.fps = int(self.plan["fps"])
        self.duration = float(self.plan["duration_seconds"])
        self._validate()

    def _validate(self):
        if (self.plan["width"], self.plan["height"], self.fps) != (W, H, 30):
            raise ValueError("Expected 1080×1920 at 30 fps")
        if self.plan["post_id"] != self.source["id"]:
            raise ValueError("Post ID mismatch")
        if self.beats[0]["start"] != 0 or self.beats[-1]["end"] != self.duration:
            raise ValueError("Timeline endpoints mismatch")
        if any(a["end"] != b["start"] for a, b in zip(self.beats, self.beats[1:])):
            raise ValueError("Timeline contains a gap or overlap")
        source = norm(self.source["text"])
        for beat in self.beats:
            for quote in beat["source_quotes"]:
                if norm(quote) not in source:
                    raise ValueError(f"Unmatched source quote in {beat['id']}: {quote}")

    @lru_cache(maxsize=24)
    def font(self, size: int, weight: str = "Regular"):
        return ImageFont.truetype(self.root / "assets" / "fonts" / f"Pretendard-{weight}.otf", size)

    @lru_cache(maxsize=3)
    def photo(self, name: str) -> Image.Image:
        filename = {
            "workstation": "video-workstation-background-v2.png",
            "upscale": "video-upscale-background-v2.png",
        }[name]
        im = Image.open(self.root / "assets" / filename).convert("RGB")
        im = ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS)
        im = ImageEnhance.Brightness(im).enhance(1.17)
        visibility = float(self.plan["photo_visibility"])
        return Image.blend(Image.new("RGB", (W, H), WHITE), im, visibility)

    @lru_cache(maxsize=1)
    def sample(self) -> Image.Image:
        im = Image.open(self.root / "assets" / "video-upscale-background-v2.png").convert("RGB")
        w, h = im.size
        return im.crop((round(w * .13), round(h * .25), round(w * .97), round(h * .65)))

    def base(self, beat: dict, index: int) -> Image.Image:
        im = self.photo(beat["photo"]).copy().convert("RGBA")
        panel = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(panel)
        # Broad translucent paper field: the topical photograph stays full bleed.
        d.rectangle((38, 290, 1042, 894), fill=(255, 255, 255, 196))
        d.rectangle((38, 290, 48, 894), fill=(*BLUE, 225))
        d.rectangle((0, 0, W, 24), fill=(*BLUE, 255))
        im.alpha_composite(panel)
        return im

    def write(self, d: ImageDraw.ImageDraw, value: str, x: int, y: int, size: int,
              *, color=INK, weight="Regular", alpha=255, max_width=940):
        while size >= 24 and self.font(size, weight).getlength(value) > max_width:
            size -= 2
        if size < 24:
            raise ValueError(f"Cannot fit text: {value}")
        d.text((x, y), value, font=self.font(size, weight), fill=(*color, round(alpha)))

    def common(self, layer: Image.Image, beat: dict, index: int, t: float):
        d = ImageDraw.Draw(layer)
        alpha = round(255 * ease((beat["end"] - beat["start"] - t) / .25))
        self.write(d, "@sto.ckai  /  AI VIDEO", 69, 129, 34,
                   color=BLUE, weight="SemiBold", alpha=alpha)
        self.write(d, f"{index + 1:02d} / {len(self.beats):02d}", 862, 130, 32,
                   color=MUTED, alpha=alpha, max_width=150)
        d.line((70, 236, 1010, 236), fill=(*BLUE, alpha), width=3)
        lines = beat["title"]
        base_y = 342 if len(lines) >= 3 else 388
        for number, line in enumerate(lines):
            if number == 0 or (beat["id"] == "hook" and number == 1):
                appear = alpha / 255
            else:
                appear = min(ease((t - .05 - number * .13) / .31), alpha / 255)
            rise = round((1 - appear) * 35)
            if beat["id"] == "summary":
                color = INK if number == 0 else BLUE
            else:
                color = (ORANGE if beat["id"] in ("cost", "regenerate") else BLUE) if number == len(lines) - 1 else INK
            self.write(d, line, 70, base_y + number * 108 + rise,
                       86 if len(lines) <= 2 else 79, color=color,
                       weight="Bold", alpha=round(255 * appear))
        detail_y = base_y + len(lines) * 109 + 22
        for number, line in enumerate(beat["detail"]):
            appear = min(ease((t - .37 - number * .12) / .31), alpha / 255)
            self.write(d, line, 72, detail_y + number * 69 + round((1 - appear) * 22),
                       50, color=MUTED, weight="SemiBold", alpha=round(255 * appear))
        self.write(d, "Threads 원문 기반  ·  배경은 연출 사진", 70, 1679, 29,
                   color=MUTED, alpha=alpha)
        for n in range(len(self.beats)):
            x1 = 70 + n * 95
            d.rectangle((x1, 1770, x1 + 78, 1778),
                        fill=(*BLUE, alpha) if n <= index else (*LINE, alpha))
        return alpha

    def draw_sample(self, layer: Image.Image, box, *, pixelated=False, selected=False,
                    alpha=255, crop_shift=0):
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        source = self.sample()
        if crop_shift:
            dx = round(source.width * crop_shift)
            source = source.crop((max(0, dx), 0, min(source.width, source.width + dx), source.height))
        source = ImageOps.fit(source, (w, h), method=Image.Resampling.LANCZOS)
        if pixelated:
            source = source.resize((max(1, w // 5), max(1, h // 5)), Image.Resampling.BILINEAR)
            source = source.resize((w, h), Image.Resampling.NEAREST)
        mask = Image.new("L", (w, h), round(alpha))
        layer.paste(source.convert("RGBA"), (x1, y1), mask)
        d = ImageDraw.Draw(layer)
        edge_color = BLUE if selected else LINE
        d.rectangle((x1, y1, x2 - 1, y2 - 1),
                    outline=(*edge_color, round(alpha)),
                    width=7 if selected else 3)

    def graphics(self, layer: Image.Image, beat: dict, t: float, alpha: int):
        scene = beat["id"]
        d = ImageDraw.Draw(layer)
        if scene == "hook":
            a = round(alpha * ease((t - .35) / .45))
            d.rectangle((71, 1058, 1009, 1482), fill=(255, 255, 255, round(a * .50)))
            self.write(d, "720p  ×  여러 번", 111, 1190, 88, color=ORANGE,
                       weight="Bold", alpha=a)
            self.write(d, "처음부터 이렇게 뽑는다면", 111, 1320, 50,
                       color=INK, alpha=a)
        elif scene == "repeat":
            for i in range(3):
                a = round(alpha * ease((t - .42 - i * .25) / .35))
                self.draw_sample(layer, (69 + 317 * i, 1045, 359 + 317 * i, 1282),
                                 pixelated=True, alpha=a, crop_shift=.05 * i)
                self.write(d, f"시안 {i + 1:02d}", 76 + 317 * i, 1310, 42,
                           color=INK, weight="SemiBold", alpha=a, max_width=275)
            d.line((70, 1437, 1010, 1437), fill=(*LINE, alpha), width=3)
            self.write(d, "프롬프트는 같아도 다시 시도", 72, 1474, 43,
                       color=BLUE, weight="SemiBold", alpha=alpha)
        elif scene == "cost":
            a = round(alpha * ease((t - .3) / .4))
            d.rectangle((70, 1040, 1010, 1460), fill=(255, 255, 255, round(a * .58)))
            for i in range(3):
                x = 110 + i * 305
                d.rectangle((x, 1110, x + 245, 1270),
                            outline=(*ORANGE, a), width=5)
                self.write(d, "720p", x + 37, 1145, 60, color=ORANGE,
                           weight="Bold", alpha=a, max_width=200)
            self.write(d, "실패작도 고해상도로 생성", 111, 1330, 50,
                       color=INK, weight="SemiBold", alpha=a)
        elif scene in ("step1", "step2", "step3"):
            active = {"step1": 0, "step2": 1, "step3": 2}[scene]
            names = ("480p 생성", "1개 선택", "업스케일")
            d.line((125, 1230, 955, 1230), fill=(*LINE, alpha), width=6)
            for i, label in enumerate(names):
                x = 125 + i * 415
                a = round(alpha * ease((t - .28 - i * .1) / .35))
                dot_color = BLUE if i <= active else WHITE
                d.ellipse((x - 31, 1199, x + 31, 1261),
                          fill=(*dot_color, a),
                          outline=(*BLUE, a), width=5)
                self.write(d, label, x - 64 if i < 2 else x - 93, 1295, 43,
                           color=BLUE if i == active else MUTED,
                           weight="Bold" if i == active else "SemiBold",
                           alpha=a, max_width=240)
            if scene == "step2":
                self.draw_sample(layer, (280, 1016, 800, 1172),
                                 pixelated=True, selected=True, alpha=alpha)
            if scene == "step3":
                self.draw_sample(layer, (300, 1020, 780, 1170),
                                 selected=True, alpha=alpha)
        elif scene == "different":
            a = round(alpha * ease((t - .25) / .4))
            d.rectangle((70, 1053, 1010, 1445), fill=(255, 255, 255, round(a * .57)))
            self.write(d, "업스케일", 105, 1160, 74, color=BLUE, weight="Bold", alpha=a)
            self.write(d, "≠", 500, 1144, 98, color=ORANGE, weight="Bold", alpha=a)
            self.write(d, "다시 생성", 655, 1160, 72, color=INK,
                       weight="Bold", alpha=a, max_width=345)
        elif scene == "regenerate":
            terms = ("구도", "움직임", "얼굴", "디테일")
            for i, term in enumerate(terms):
                a = round(alpha * ease((t - .44 - i * .18) / .34))
                x = 72 + (i % 2) * 474
                y = 1054 + (i // 2) * 205
                d.rectangle((x, y, x + 429, y + 152),
                            fill=(255, 255, 255, round(a * .65)),
                            outline=(*ORANGE, a), width=4)
                self.write(d, term, x + 44, y + 37, 67, color=INK,
                           weight="Bold", alpha=a, max_width=360)
        elif scene == "preserve":
            a = round(alpha * ease((t - .36) / .38))
            left = (70, 1055, 540, 1370)
            right = (540, 1055, 1010, 1370)
            self.draw_sample(layer, left, pixelated=True, alpha=a)
            self.draw_sample(layer, right, alpha=a, selected=True)
            d.line((540, 1035, 540, 1390), fill=(*BLUE, a), width=7)
            self.write(d, "선택한 영상은 그대로", 72, 1445, 48,
                       color=BLUE, weight="SemiBold", alpha=a)
        elif scene == "summary":
            a = round(alpha * ease((t - .4) / .43))
            d.rectangle((70, 1060, 1010, 1400), fill=(255, 255, 255, round(a * .57)))
            self.write(d, "먼저 고르고", 110, 1125, 76,
                       color=INK, weight="Bold", alpha=a)
            self.write(d, "선택한 결과만 마감", 110, 1240, 76,
                       color=BLUE, weight="Bold", alpha=a)

    def frame(self, time: float) -> Image.Image:
        for index, beat in enumerate(self.beats):
            if beat["start"] <= time < beat["end"]:
                local = time - beat["start"]
                base = self.base(beat, index)
                overlay = Image.new("RGBA", (W, H))
                alpha = self.common(overlay, beat, index, local)
                self.graphics(overlay, beat, local, alpha)
                base.alpha_composite(overlay)
                return base.convert("RGB")
        return self.frame(self.duration - .001)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--preview-time", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    reel = Reel(root)
    if args.preview_time is not None:
        output = args.output or root / "Previews" / f"v2-{args.preview_time:.1f}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        reel.frame(args.preview_time).save(output)
        print(output)
        return
    output = args.output or root / "reel-480p-upscale-v2.mp4"
    music = root / reel.plan["audio_file"]
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{W}x{H}",
        "-framerate", str(reel.fps), "-i", "pipe:0", "-i", str(music),
        "-filter_complex",
        f"[1:a]atrim=0:{reel.duration},loudnorm=I=-15:TP=-1.5:LRA=8,volume=-2dB,"
        f"afade=t=in:st=0:d=0.18,afade=t=out:st={reel.duration-0.8}:d=0.8[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-ar", "44100", "-ac", "2", "-t", str(reel.duration),
        "-movflags", "+faststart", str(output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for number in range(round(reel.duration * reel.fps)):
            process.stdin.write(reel.frame(number / reel.fps).tobytes())
    except BrokenPipeError:
        pass
    finally:
        if process.stdin:
            process.stdin.close()
    if process.wait():
        raise SystemExit("FFmpeg render failed")
    print(output)


if __name__ == "__main__":
    main()
