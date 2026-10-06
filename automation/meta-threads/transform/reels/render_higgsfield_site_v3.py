#!/usr/bin/env python3
"""Render the source-complete reel with captures of Higgsfield's public UI.

The captures are editorial examples. No generated result, account session,
upload, or successful upscale is simulated.
"""

from __future__ import annotations

import argparse
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from render_source_full_v2 import Reel as SourceReel, W, H, clamp, ease


PAPER = (247, 247, 243)
INK = (24, 27, 29)
SUB = (78, 83, 81)
LIME = (215, 250, 72)
RULE = (202, 207, 199)


class Reel(SourceReel):
    @lru_cache(maxsize=4)
    def screen(self, name: str) -> Image.Image:
        files = {
            "480": "higgsfield-480p-site.jpg",
            "720": "higgsfield-720p-site.jpg",
            "upscale": "higgsfield-upscale-desktop-site.jpg",
            "menu": "higgsfield-resolution-site.jpg",
        }
        return Image.open(self.root / "assets" / files[name]).convert("RGB")

    def text(self, draw, value, xy, size, *, weight="SemiBold", fill=INK,
             max_width=970, opacity=255):
        while self.font(size, weight).getlength(value) > max_width and size > 25:
            size -= 2
        draw.text(xy, value, font=self.font(size, weight),
                  fill=(*fill, round(opacity)))

    def screen_card(self, canvas: Image.Image, name: str, crop, box, *,
                    local: float, delay: float = 0, border=True):
        progress = ease((local - delay) / .42)
        if progress <= 0:
            return
        x, y, w, h = box
        y += round((1 - progress) * 42)
        source = self.screen(name).crop(crop)
        # A restrained push-in keeps the actual UI as the subject.
        zoom = 1 + .012 * clamp((local - delay) / 3)
        cw, ch = source.size
        nw, nh = round(cw / zoom), round(ch / zoom)
        lx, ly = (cw - nw) // 2, (ch - nh) // 2
        source = source.crop((lx, ly, lx + nw, ly + nh))
        source = source.resize((w, h), Image.Resampling.LANCZOS)
        mask = Image.new("L", (w, h))
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle((0, 0, w - 1, h - 1), radius=26, fill=round(255 * progress))
        shadow = Image.new("RGBA", canvas.size)
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((x + 2, y + 13, x + w + 2, y + h + 13),
                             radius=28, fill=(24, 29, 26, round(37 * progress)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(20))
        canvas.alpha_composite(shadow)
        canvas.paste(source.convert("RGBA"), (x, y), mask)
        if border:
            d = ImageDraw.Draw(canvas)
            d.rounded_rectangle((x, y, x + w - 1, y + h - 1),
                                radius=26, outline=(211, 216, 210, round(255 * progress)), width=3)

    def base(self, beat: dict, index: int) -> Image.Image:
        return Image.new("RGBA", (W, H), (*PAPER, 255))

    def common(self, layer: Image.Image, beat: dict, index: int, t: float):
        d = ImageDraw.Draw(layer)
        d.rectangle((0, 0, W, 22), fill=LIME)
        self.text(d, "@sto.ckai", (60, 105), 34, weight="Bold")
        self.text(d, "THREADS 원문 기반", (60, 153), 28, fill=SUB)
        self.text(d, f"{index + 1:02d} / {len(self.beats):02d}", (880, 113), 28,
                  fill=SUB, max_width=150)
        d.line((60, 215, 1020, 215), fill=RULE, width=3)
        title = beat["title"]
        size = 72 if len(title) <= 2 else 68
        line_gap = 88 if len(title) <= 2 else 82
        for n, line in enumerate(title):
            appear = ease((t + .10 - n * .13) / .32)
            color = INK
            if n == len(title) - 1:
                color = (33, 73, 45)
            self.text(d, line, (60, 260 + n * line_gap + round((1-appear)*22)),
                      size, weight="Bold", fill=color, max_width=970,
                      opacity=appear*255)
        detail_y = 275 + len(title) * line_gap + 18
        for n, line in enumerate(beat["detail"]):
            appear = ease((t - .23 - n * .10) / .38)
            self.text(d, line, (63, detail_y + n * 48 + round((1-appear)*13)),
                      37, fill=SUB, max_width=960, opacity=appear*255)
        d.line((60, 1743, 1020, 1743), fill=RULE, width=3)
        self.text(d, "Higgsfield 공개 사이트 화면 예시", (60, 1770), 27,
                  fill=SUB, max_width=780)
        self.text(d, "sto.ckai", (892, 1770), 27, weight="Bold",
                  fill=SUB, max_width=140)
        for n in range(len(self.beats)):
            x = 60 + 96 * n
            d.rounded_rectangle((x, 1839, x + 76, 1847), radius=4,
                                fill=(55, 90, 53) if n <= index else RULE)

    def tag(self, layer: Image.Image, value: str, x: int, y: int, *, width=320):
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle((x, y, x + width, y + 56), radius=14, fill=LIME)
        self.text(d, value, (x + 17, y + 10), 31, weight="Bold",
                  max_width=width - 34)

    def graphics(self, layer: Image.Image, beat: dict, t: float, alpha: int):
        scene = beat["id"]
        # Source capture coordinates refer to 1280x720 browser screenshots.
        create = (15, 306, 335, 691)
        bottom = (18, 476, 334, 690)
        up = (370, 89, 909, 632)
        if scene in ("hook", "repeat", "step1", "step2"):
            source = "720" if (scene == "hook" and t < 1.15) or scene == "repeat" else "480"
            self.screen_card(layer, source, create, (148, 763, 784, 944),
                             local=t, delay=.10)
            self.tag(layer, "480p 설정" if source == "480" else "생성 화면",
                     150, 683, width=240)
        elif scene == "cost":
            self.tag(layer, "실제 사이트 설정 비교", 60, 756, width=382)
            self.screen_card(layer, "480", bottom, (60, 865, 460, 380),
                             local=t, delay=.10)
            self.screen_card(layer, "720", bottom, (560, 865, 460, 380),
                             local=t, delay=.32)
            d = ImageDraw.Draw(layer)
            self.text(d, "480p", (65, 1276), 44, weight="Bold")
            self.text(d, "720p", (565, 1276), 44, weight="Bold")
            d.line((60, 1390, 1020, 1390), fill=RULE, width=3)
            self.text(d, "표시 비용은 모델·시점에 따라 달라질 수 있음",
                      (60, 1430), 32, fill=SUB)
        elif scene in ("step3", "different", "preserve"):
            self.tag(layer, "업스케일 공개 화면", 61, 725, width=358)
            self.screen_card(layer, "upscale", up, (113, 808, 854, 856),
                             local=t, delay=.13)
        elif scene == "regenerate":
            self.tag(layer, "다시 생성", 60, 755, width=215)
            self.tag(layer, "업스케일", 561, 755, width=215)
            self.screen_card(layer, "720", bottom, (60, 837, 460, 380),
                             local=t, delay=.10)
            self.screen_card(layer, "upscale", (371, 377, 909, 632),
                             (560, 837, 460, 380), local=t, delay=.30)
            d = ImageDraw.Draw(layer)
            self.text(d, "새로 생성", (65, 1250), 43, weight="Bold")
            self.text(d, "선택본 후처리", (565, 1250), 43, weight="Bold")
        elif scene == "summary":
            self.tag(layer, "01 · 480p로 고르기", 60, 739, width=388)
            self.screen_card(layer, "480", bottom, (60, 825, 460, 380),
                             local=t, delay=.10)
            self.tag(layer, "02 · 선택본 업스케일", 560, 739, width=428)
            self.screen_card(layer, "upscale", (371, 377, 909, 632),
                             (560, 825, 460, 380), local=t, delay=.27)
            d = ImageDraw.Draw(layer)
            d.line((60, 1350, 1020, 1350), fill=RULE, width=3)
            self.text(d, "여러 번은 낮게, 최종본만 높게", (60, 1396), 53,
                      weight="Bold", max_width=950)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--preview-time", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    reel = Reel(root)
    if args.preview_time is not None:
        output = args.output or root / "Previews" / f"higgsfield-v3-{args.preview_time:.1f}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        reel.frame(args.preview_time).save(output)
        print(output)
        return
    output = args.output or root / "reel-480p-upscale-higgsfield-v3.mp4"
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
