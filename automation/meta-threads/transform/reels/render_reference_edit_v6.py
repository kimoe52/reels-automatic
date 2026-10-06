#!/usr/bin/env python3
"""Reference-led reel for the @sto.ckai 480p/upscale post.

The supplied landscape tutorial reference informs the edit grammar: a real
interface, numbered chapter cards, deliberate punch-ins, one highlighted
phrase, and a single caption band. The Higgsfield capture is visual context,
not evidence of a completed generation or a universal price claim.
"""

from __future__ import annotations

import argparse
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from render_source_full_v2 import Reel as SourceReel, W, H, clamp, ease


WHITE = (250, 252, 255)
YELLOW = (255, 215, 69)
CYAN = (92, 220, 240)
NAVY = (9, 25, 49)
PALE = (218, 235, 247)
BLUE = (26, 95, 158)

COPY = {
    "hook": (("AI 영상,", "720p부터 돌리면?"), "처음부터 720p로 뽑으면 토큰 아까움"),
    "repeat": (("한 번에 안 나와서", "여러 번 뽑게 됨"), "같은 프롬프트로 여러 번 생성하는 경우가 많음"),
    "cost": (("실패작까지", "고해상도로 생성"), "720p는 480p보다 영상 생성 토큰을 훨씬 많이 먹음"),
    "step1": (("480p로", "시안 여러 개"), "먼저 480p로 여러 번 생성"),
    "step2": (("마음에 드는", "하나만 고르기"), "마음에 드는 영상 하나를 선택"),
    "step3": (("그 영상만", "업스케일"), "선택한 영상만 720p 또는 1080p로 업스케일"),
    "different": (("업스케일", "≠ 다시 생성"), "720p로 다시 생성하는 것과는 다른 작업"),
    "regenerate": (("다시 생성하면", "장면이 달라질 수 있음"), "구도 · 움직임 · 얼굴 · 디테일이 바뀔 수 있음"),
    "preserve": (("고른 영상은 그대로", "화질만 후처리"), "업스케일은 해상도와 선명도를 높이는 후처리"),
    "summary": (("480p는 시안", "업스케일은 마감"), "480p는 주사위 굴리기, 업스케일은 당첨본 화질 마감"),
}


class Reel(SourceReel):
    @lru_cache(maxsize=4)
    def site(self, name: str) -> Image.Image:
        return Image.open(self.root / "assets" / name).convert("RGB")

    @lru_cache(maxsize=300)
    def screen(self, name: str, beat_id: str, progress_step: int) -> Image.Image:
        source = self.site(name)
        base = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(base)
        for y in range(H):
            p = y / H
            color = (round(237 - 13 * p), round(244 - 4 * p), round(254 - 6 * p))
            d.line((0, y, W, y), fill=color)
        # Keep the original site screenshot at its native landscape ratio,
        # like the reference's real desktop recording.
        d.rounded_rectangle((57, 484, 1023, 1091), radius=30,
                            fill=(194, 207, 226))
        d.rounded_rectangle((67, 474, 1013, 1081), radius=26,
                            fill=(255, 255, 255))
        d.rounded_rectangle((67, 474, 1013, 521), radius=25,
                            fill=(242, 246, 252))
        for i, color in enumerate(((255, 125, 119), (255, 199, 79), (74, 207, 125))):
            x = 95 + 25 * i
            d.ellipse((x, 492, x + 12, 504), fill=color)
        drift = progress_step / 29
        overview_w = round(1280 - 55 * drift)
        overview_h = round(720 - 31 * drift)
        overview_x = round((1280 - overview_w) / 2)
        overview_y = round((720 - overview_h) / 2)
        overview = source.crop((overview_x, overview_y,
                                overview_x + overview_w,
                                overview_y + overview_h)).resize(
                                    (946, 532), Image.Resampling.LANCZOS)
        base.paste(overview, (67, 520))
        # A second punch-in behaves like the reference's UI close-up, while
        # avoiding any fabricated click, generated result, or price claim.
        if beat_id == "repeat":
            crop = (16, 315, 335, 495)
        elif name == "higgsfield-upscale-desktop-site.jpg":
            crop = (371, 318, 908, 633)
        else:
            crop = (12, 448, 335, 634)
        motion = round(5 * drift)
        x1, y1, x2, y2 = crop
        crop = (x1 + motion, y1 + motion, x2 - motion, y2 - motion)
        zoom = source.crop(crop).resize((860, 495), Image.Resampling.LANCZOS)
        d.rounded_rectangle((96, 1097, 984, 1619), radius=27,
                            fill=(194, 207, 226))
        d.rounded_rectangle((105, 1088, 975, 1609), radius=23,
                            fill=(255, 255, 255))
        base.paste(zoom, (110, 1094))
        d = ImageDraw.Draw(base)
        d.rounded_rectangle((114, 1110, 286, 1151), radius=11,
                            fill=(9, 27, 48))
        d.text((130, 1117), "ZOOM IN", font=self.font(22, "Bold"), fill=WHITE)
        return base

    def copy_fit(self, d: ImageDraw.ImageDraw, text: str, x: int, y: int,
                 size: int, *, fill=WHITE, max_width=940, weight="Bold"):
        while size > 34 and self.font(size, weight).getlength(text) > max_width:
            size -= 2
        d.text((x, y), text, font=self.font(size, weight), fill=fill)

    def caption(self, im: Image.Image, value: str, local: float):
        a = ease((local - .12) / .24)
        if a <= 0:
            return
        layer = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(layer)
        font = self.font(43, "SemiBold")
        words = value.split()
        lines = []
        line = ""
        for word in words:
            candidate = (line + " " + word).strip()
            if font.getlength(candidate) > 850 and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        lines = lines[:2]
        height = 73 + 57 * len(lines)
        y = 1672 - round((1 - a) * 20)
        d.rounded_rectangle((68, y, 1012, y + height), radius=20,
                            fill=(4, 11, 22, round(235 * a)))
        for i, text in enumerate(lines):
            width = font.getlength(text)
            d.text(((W - width) / 2, y + 34 + 57 * i), text, font=font,
                   fill=(*WHITE, round(255 * a)))
        im.alpha_composite(layer)

    def header(self, im: Image.Image, index: int):
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((62, 71, 407, 130), radius=17, fill=(8, 24, 43, 235))
        self.copy_fit(d, "STO.CKAI  /  AI VIDEO", 86, 84, 26,
                      fill=WHITE, weight="SemiBold", max_width=305)
        d.rounded_rectangle((891, 71, 1018, 130), radius=17,
                            fill=(8, 24, 43, 235))
        self.copy_fit(d, f"{index + 1:02d}/10", 914, 84, 28,
                      fill=PALE, weight="SemiBold", max_width=90)
        d.rounded_rectangle((62, 1868, 1018, 1876), radius=4,
                            fill=(198, 213, 228))
        d.rounded_rectangle((62, 1868, 62 + round(956 * (index + 1) / 10), 1876),
                            radius=4, fill=YELLOW)

    def title(self, im: Image.Image, lines: tuple[str, str], local: float):
        d = ImageDraw.Draw(im)
        for i, value in enumerate(lines):
            a = ease((local + .02 - i * .11) / .27)
            if a <= 0:
                continue
            title_layer = Image.new("RGBA", (W, H))
            td = ImageDraw.Draw(title_layer)
            size = 83
            max_width = 950
            while size > 48 and self.font(size, "Bold").getlength(value) > max_width:
                size -= 2
            td.text((64, 210 + 106 * i + round((1 - a) * 24)), value,
                    font=self.font(size, "Bold"),
                    fill=(*(BLUE if i == 1 else NAVY), round(255 * a)))
            im.alpha_composite(title_layer)
        if local > .25:
            d.rounded_rectangle((64, 431, 267, 440), radius=4, fill=YELLOW)

    def focus(self, im: Image.Image, beat_id: str, local: float):
        """Highlight real controls without claiming that we clicked them."""
        d = ImageDraw.Draw(im)
        pulse = 0.5 + 0.5 * ease((local - .35) / .35)
        if beat_id in ("hook", "step1", "step2"):
            box = (704, 1350, 951, 1472)
        elif beat_id == "cost":
            box = (704, 1350, 951, 1472)
        elif beat_id == "repeat":
            box = (160, 1193, 917, 1487)
        else:
            return
        d.rounded_rectangle(box, radius=21, outline=(*YELLOW, round(255 * pulse)),
                            width=8)
        corner_y = box[1] - 33
        d.rounded_rectangle((box[0], corner_y, box[0] + 230, corner_y + 39),
                            radius=11, fill=(12, 25, 43, 235))
        label = "같은 프롬프트" if beat_id == "repeat" else "화면 설정"
        self.copy_fit(d, label, box[0] + 14, corner_y + 4, 23,
                      fill=WHITE, weight="SemiBold", max_width=200)

    def chapter(self, im: Image.Image, number: str, lines: tuple[str, str], local: float):
        slide = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(slide)
        a = ease((local + .04) / .27)
        # This is the reference's large numbered intertitle, adapted to 9:16.
        d.rounded_rectangle((62, 231, 1018, 1551), radius=37,
                            fill=(10, 31, 68, round(255 * a)))
        d.rounded_rectangle((62, 231, 1018, 1551), radius=37,
                            outline=(124, 174, 231, round(130 * a)), width=3)
        d.text((104, 385), number, font=self.font(280, "Bold"),
               fill=(112, 188, 249, round(255 * a)))
        d.line((104, 785, 970, 785), fill=(164, 210, 246, round(255 * a)), width=3)
        for i, value in enumerate(lines):
            size = 73
            while size > 42 and self.font(size, "Bold").getlength(value) > 854:
                size -= 2
            d.text((104, 911 + 112 * i), value, font=self.font(size, "Bold"),
                   fill=(*(YELLOW if i else WHITE), round(255 * a)))
        d.rounded_rectangle((104, 1372, 560, 1383), radius=5,
                            fill=(*YELLOW, round(255 * a)))
        im.alpha_composite(slide)

    def comparison(self, im: Image.Image, local: float):
        a = ease((local - .25) / .33)
        if a <= 0:
            return
        layer = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle((65, 651, 1015, 1455), radius=31,
                            fill=(9, 25, 47, round(255 * a)))
        self.copy_fit(d, "다시 생성", 112, 732, 72, fill=WHITE, max_width=830)
        d.line((112, 845, 968, 845), fill=(*PALE, round(115 * a)), width=3)
        for i, term in enumerate(("구도", "움직임", "얼굴", "디테일")):
            x = 112 + (i % 2) * 430
            y = 906 + (i // 2) * 150
            d.rounded_rectangle((x, y, x + 360, y + 112), radius=16,
                                fill=(28, 65, 101, round(255 * a)))
            self.copy_fit(d, term, x + 36, y + 23, 52,
                          fill=YELLOW if i == 0 else WHITE, max_width=290)
        self.copy_fit(d, "같은 프롬프트여도 달라질 수 있음", 112, 1270, 38,
                      fill=PALE, weight="SemiBold", max_width=830)
        im.alpha_composite(layer)

    def ending(self, im: Image.Image, local: float):
        a = ease((local - .2) / .34)
        if a <= 0:
            return
        layer = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle((60, 287, 1020, 1543), radius=36,
                            fill=(9, 28, 54, round(255 * a)))
        for i, (big, small) in enumerate((
            ("480p", "여러 시안 중 하나를 고르는 단계"),
            ("업스케일", "당첨본 화질을 마감하는 단계"),
        )):
            y = 480 + 442 * i
            self.copy_fit(d, big, 110, y, 101,
                          fill=YELLOW if i else WHITE, max_width=850)
            self.copy_fit(d, small, 113, y + 132, 42,
                          fill=PALE, weight="SemiBold", max_width=820)
            if i == 0:
                d.line((110, 877, 968, 877), fill=(155, 195, 229, round(255 * a)), width=3)
        im.alpha_composite(layer)

    def frame(self, time: float) -> Image.Image:
        for index, beat in enumerate(self.beats):
            if beat["start"] <= time < beat["end"]:
                local = time - beat["start"]
                duration = beat["end"] - beat["start"]
                progress = min(29, round(29 * local / max(.01, duration)))
                name = "higgsfield-480p-site.jpg"
                if beat["id"] == "cost":
                    name = "higgsfield-720p-site.jpg"
                elif beat["id"] in ("step3", "preserve"):
                    name = "higgsfield-upscale-desktop-site.jpg"
                image = self.screen(name, beat["id"], progress).copy().convert("RGBA")
                self.header(image, index)
                headline, subtitle = COPY[beat["id"]]
                if beat["id"] not in ("step1", "different", "summary"):
                    self.title(image, headline, local)
                if beat["id"] in ("step1", "different"):
                    self.chapter(image, "01" if beat["id"] == "step1" else "02", headline, local)
                elif beat["id"] == "regenerate":
                    self.comparison(image, local)
                elif beat["id"] == "summary":
                    self.ending(image, local)
                else:
                    self.focus(image, beat["id"], local)
                self.caption(image, subtitle, local)
                d = ImageDraw.Draw(image)
                self.copy_fit(d, "공개 사이트 화면 예시  ·  @sto.ckai 원문", 66, 1618,
                              27, fill=NAVY, weight="SemiBold", max_width=860)
                return image.convert("RGB")
        return self.frame(self.duration - .001)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--preview-time", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reel = Reel(args.project.resolve())
    if args.preview_time is not None:
        path = args.output or reel.root / "Previews" / f"reference-v6-{args.preview_time:.1f}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        reel.frame(args.preview_time).save(path)
        print(path)
        return
    path = args.output or reel.root / "reel-480p-upscale-reference-v6.mp4"
    music = reel.root / reel.plan["audio_file"]
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{W}x{H}",
        "-framerate", str(reel.fps), "-i", "pipe:0", "-ss", "10", "-i", str(music),
        "-filter_complex",
        f"[1:a]atrim=0:{reel.duration},loudnorm=I=-21:TP=-2:LRA=8,"
        f"afade=t=in:st=0:d=0.18,afade=t=out:st={reel.duration-0.65}:d=0.65[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
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
