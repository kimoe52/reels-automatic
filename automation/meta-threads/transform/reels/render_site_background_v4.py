#!/usr/bin/env python3
"""Render the 480p/upscale Threads post over unobtrusive real site imagery.

Higgsfield is background texture only. The narrative, comparison, and labels
come exclusively from the user's Threads post, not from site-specific claims.
"""

from __future__ import annotations

import argparse
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from render_source_full_v2 import Reel as SourceReel, W, H, clamp, ease


PAPER = (248, 248, 244)
INK = (24, 28, 25)
GREEN = (34, 72, 42)
MUTED = (76, 84, 76)
RULE = (188, 196, 184)


class Reel(SourceReel):
    blur_radius = 3.2

    @lru_cache(maxsize=3)
    def source_screen(self, key: str) -> Image.Image:
        names = {
            "480": "higgsfield-480p-site.jpg",
            "720": "higgsfield-720p-site.jpg",
            "upscale": "higgsfield-upscale-desktop-site.jpg",
        }
        return Image.open(self.root / "assets" / names[key]).convert("RGB")

    def background(self, beat: dict, local: float) -> Image.Image:
        key = "480"
        if beat["id"] in ("repeat", "cost"):
            key = "720"
        original = self.source_screen(key)
        if key == "upscale":
            original = original.crop((371, 88, 909, 633))
        else:
            # Keep the creation panel's context, but exclude its
            # model-specific credit button from a service-agnostic post.
            original = original.crop((14, 86, 335, 620))
        large = ImageOps.fit(original, (1160, 2030), method=Image.Resampling.LANCZOS)
        shift_x = round(35 * clamp(local / max(.1, beat["end"] - beat["start"])))
        shift_y = round(25 * clamp(local / max(.1, beat["end"] - beat["start"])))
        site = large.crop((30 + shift_x, 45 + shift_y,
                           30 + shift_x + W, 45 + shift_y + H))
        site = ImageEnhance.Brightness(site).enhance(.64)
        if self.blur_radius:
            site = site.filter(ImageFilter.GaussianBlur(self.blur_radius))
        site = site.convert("RGBA")
        wash = Image.new("RGBA", (W, H))
        pixels = ImageDraw.Draw(wash)
        for y in range(H):
            # The interface stays perceptible low in the frame, while the
            # source post's words remain the only dominant information.
            opacity = (round(220 - 75 * y / H) if self.blur_radius
                       else round(175 - 45 * y / H))
            pixels.line((0, y, W, y), fill=(*PAPER, opacity), width=1)
        site.alpha_composite(wash)
        return site

    def text(self, draw, value, x, y, size, *, weight="SemiBold",
             fill=INK, alpha=255, width=960):
        while size > 27 and self.font(size, weight).getlength(value) > width:
            size -= 2
        draw.text((x, y), value, font=self.font(size, weight),
                  fill=(*fill, round(alpha)))

    def common(self, layer: Image.Image, beat: dict, index: int, local: float):
        d = ImageDraw.Draw(layer)
        d.rectangle((0, 0, W, 15), fill=GREEN)
        self.text(d, "@sto.ckai", 64, 102, 35, weight="Bold")
        self.text(d, "THREADS 원문 기반", 64, 157, 28, fill=MUTED)
        self.text(d, f"{index + 1:02d}/{len(self.beats):02d}", 890, 112, 28,
                  fill=MUTED, width=140)
        d.line((64, 220, 1016, 220), fill=RULE, width=3)
        title = beat["title"]
        start = 305 if len(title) >= 3 else 345
        gap = 98 if len(title) >= 3 else 110
        for n, line in enumerate(title):
            appearance = ease((local + .05 - n * .13) / .31)
            rise = round((1 - appearance) * 28)
            color = GREEN if n == len(title) - 1 else INK
            self.text(d, line, 64, start + n * gap + rise,
                      82 if len(title) <= 2 else 76,
                      weight="Bold", fill=color, alpha=255 * appearance)
        detail_start = start + len(title) * gap + 29
        for n, line in enumerate(beat["detail"]):
            appearance = ease((local - .28 - n * .10) / .34)
            self.text(d, line, 67, detail_start + n * 62 + round((1-appearance)*13),
                      42, fill=MUTED, alpha=255 * appearance)
        d.line((64, 1718, 1016, 1718), fill=RULE, width=3)
        self.text(d, "480p 시안 선택  →  선택본 업스케일", 64, 1750,
                  31, fill=MUTED)
        for n in range(len(self.beats)):
            x = 64 + 95*n
            d.rounded_rectangle((x, 1841, x+76, 1849), radius=4,
                                fill=GREEN if n <= index else RULE)

    def note(self, layer: Image.Image, lines: list[str], local: float,
             *, lead=""):
        d = ImageDraw.Draw(layer)
        reveal = ease((local - .35) / .42)
        if reveal <= 0:
            return
        y = 1130 + round((1-reveal)*35)
        d.rounded_rectangle((63, y-35, 1017, y + 340), radius=28,
                            fill=(255, 255, 253, round(219*reveal)))
        d.rectangle((63, y-35, 75, y+340),
                    fill=(*GREEN, round(255*reveal)))
        if lead:
            self.text(d, lead, 104, y+4, 35, weight="Bold",
                      fill=GREEN, alpha=255*reveal)
        start = y+73 if lead else y+35
        for n, line in enumerate(lines):
            self.text(d, line, 104, start+n*86, 60,
                      weight="Bold" if n == len(lines)-1 else "SemiBold",
                      fill=GREEN if n == len(lines)-1 else INK,
                      alpha=255*reveal, width=860)

    def graphics(self, layer: Image.Image, beat: dict, local: float, alpha: int):
        scene = beat["id"]
        if scene == "hook":
            self.note(layer, ["처음부터 720p로 반복 생성", "실패작에도 토큰 사용"], local)
        elif scene == "repeat":
            self.note(layer, ["같은 프롬프트", "다시 생성 · 다시 생성"], local)
        elif scene == "cost":
            self.note(layer, ["실패작까지 고해상도로 뽑으면", "토큰이 계속 듦"], local)
        elif scene == "step1":
            self.note(layer, ["480p로 여러 번", "먼저 시안 확인"], local, lead="01")
        elif scene == "step2":
            self.note(layer, ["마음에 드는 영상", "하나만 선택"], local, lead="02")
        elif scene == "step3":
            self.note(layer, ["고른 영상만", "720p·1080p 업스케일"], local, lead="03")
        elif scene == "different":
            self.note(layer, ["업스케일", "≠ 720p로 다시 생성"], local)
        elif scene == "regenerate":
            self.note(layer, ["다시 생성하면", "구도 · 움직임 · 얼굴 · 디테일"], local)
        elif scene == "preserve":
            self.note(layer, ["이미 고른 영상은 유지", "해상도·선명도만 후처리"], local)
        else:
            self.note(layer, ["480p = 주사위 굴리기", "업스케일 = 당첨본 마감"], local)

    def frame(self, time: float) -> Image.Image:
        for index, beat in enumerate(self.beats):
            if beat["start"] <= time < beat["end"]:
                local = time - beat["start"]
                base = self.background(beat, local)
                overlay = Image.new("RGBA", (W, H))
                self.common(overlay, beat, index, local)
                self.graphics(overlay, beat, local, 255)
                base.alpha_composite(overlay)
                return base.convert("RGB")
        return self.frame(self.duration - .001)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--preview-time", type=float)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-blur", action="store_true")
    args = parser.parse_args()
    root = args.project.resolve()
    reel = Reel(root)
    if args.no_blur:
        reel.blur_radius = 0
    if args.preview_time is not None:
        version = "v5-no-blur" if args.no_blur else "v4"
        path = args.output or root / "Previews" / f"site-background-{version}-{args.preview_time:.1f}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        reel.frame(args.preview_time).save(path)
        print(path)
        return
    default_name = ("reel-480p-upscale-site-background-v5.mp4" if args.no_blur
                    else "reel-480p-upscale-site-background-v4.mp4")
    path = args.output or root / default_name
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
        "-movflags", "+faststart", str(path),
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
    print(path)


if __name__ == "__main__":
    main()
