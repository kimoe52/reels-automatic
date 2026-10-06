#!/usr/bin/env python3
"""Render one local card-news set and a face-preserving reel preview.

The reel uses the user's original reference photo as a flat image. It does not
regenerate, retouch, lip-sync, or otherwise alter the face.
"""

from __future__ import annotations

import argparse
import shutil
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT = Path(__file__).resolve().parents[3]
DEMO = PROJECT / "automation" / "meta-threads" / "queue" / "2026-09-23" / "demo-72-rule"
CARDS_DIR = DEMO / "assets" / "cards"
FRAMES_DIR = Path("/private/tmp/jev-demo-reel-frames")
PHOTO = PROJECT / "content" / "character" / "reel-human-reference" / "reference-03.png"
MASCOT = PROJECT / "content" / "character" / "character-creature.png"
FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size=size, index=0)


def wrap_lines(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False) or [""]


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fnt: ImageFont.FreeTypeFont, *, width: int, fill: str, spacing: int = 12) -> int:
    x, y = xy
    line_height = fnt.size + spacing
    for line in wrap_lines(text, width):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += line_height
    return y


def rounded_paste(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int], radius: int = 28, border: str | None = None) -> None:
    x, y, w, h = box
    fitted = image.copy()
    fitted.thumbnail((w, h), Image.Resampling.LANCZOS)
    layer = Image.new("RGB", (w, h), "#FFFFFF")
    layer.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    canvas.paste(layer, (x, y), mask)
    if border:
        ImageDraw.Draw(canvas).rounded_rectangle((x, y, x + w, y + h), radius=radius, outline=border, width=5)


def make_card(index: int, output: Path, mascot: Image.Image) -> None:
    palettes = [("#F7F0E5", "#24533E"), ("#E8F2EC", "#24533E"), ("#EEEAF8", "#362D63"), ("#F8E8D6", "#6B3C20"), ("#E8EFF3", "#214459")]
    bg, accent = palettes[index - 1]
    image = Image.new("RGB", (1080, 1350), bg)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((48, 48, 1032, 1302), radius=42, outline="#FFFFFF", width=4)
    draw.text((84, 78), "@sto.ckai  ·  원문 기반", font=font(28), fill=accent)
    draw.text((930, 78), f"{index}/5", font=font(28), fill=accent, anchor="ra")

    if index == 1:
        draw_wrapped(draw, (84, 220), "내 돈이 2배가 되는 데\n얼마나 걸릴까?", font(72), width=12, fill="#111111", spacing=16)
        draw_wrapped(draw, (88, 520), "작은 공식 하나로 빠르게 가늠해볼 수 있어요.", font(38), width=18, fill=accent, spacing=14)
        rounded_paste(image, mascot, (650, 720, 300, 300), radius=36, border="#FFFFFF")
    elif index == 2:
        draw.text((84, 220), "‘72의 법칙’", font=font(68), fill="#111111")
        draw_wrapped(draw, (88, 360), "예상 연수익률로 72를 나누면\n돈이 2배가 되는 기간을\n빠르게 가늠할 수 있습니다.", font(44), width=17, fill=accent, spacing=18)
        draw.rounded_rectangle((84, 790, 996, 1010), radius=28, fill="#FFFFFF")
        draw.text((540, 875), "72 ÷ 예상 연수익률(%)", font=font(48), fill="#111111", anchor="ma")
    elif index == 3:
        draw.text((84, 220), "계산식", font=font(64), fill="#111111")
        draw.rounded_rectangle((84, 390, 996, 650), radius=30, fill="#FFFFFF")
        draw.text((540, 515), "(1 + 수익률)^기간 = 2", font=font(46), fill="#111111", anchor="mm")
        draw.text((540, 830), "72 ÷ 예상 연수익률(%)", font=font(52), fill=accent, anchor="mm")
        draw.text((540, 930), "≈ 2배까지 걸리는 기간", font=font(42), fill="#111111", anchor="mm")
    elif index == 4:
        draw.text((84, 220), "원문 예시", font=font(64), fill="#111111")
        rows = [("연 4%", "약 18년"), ("연 6%", "약 12년"), ("연 9%", "약 8년")]
        y = 420
        for rate, years in rows:
            draw.rounded_rectangle((84, y, 996, y + 150), radius=24, fill="#FFFFFF")
            draw.text((140, y + 75), rate, font=font(46), fill=accent, anchor="lm")
            draw.text((930, y + 75), years, font=font(46), fill="#111111", anchor="rm")
            y += 185
    else:
        draw.text((84, 220), "꼭 기억할 조건", font=font(60), fill="#111111")
        draw_wrapped(draw, (88, 390), "수익 재투자 + 비슷한 수익률이 이어진다고 가정한 근삿값입니다.", font(44), width=17, fill=accent, spacing=18)
        rounded_paste(image, mascot, (650, 760, 240, 240), radius=32, border="#FFFFFF")
        draw_wrapped(draw, (88, 1090), "출처: @sto.ckai Threads\n※ 투자 권유가 아닌 원문 개념 정리", font(27), width=35, fill="#333333", spacing=8)

    image.save(output, format="PNG", optimize=True)


def photo_on_canvas(photo: Image.Image, size: tuple[int, int], *, zoom: float = 1.0) -> Image.Image:
    w, h = size
    scale = max(w / photo.width, h / photo.height) * zoom
    resized = photo.resize((int(photo.width * scale), int(photo.height * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - w) // 2)
    top = max(0, (resized.height - h) // 2)
    return resized.crop((left, top, left + w, top + h))


def make_reel_frame(photo: Image.Image, t: float) -> Image.Image:
    canvas = Image.new("RGB", (1080, 1920), "#F4F0EA")
    draw = ImageDraw.Draw(canvas)
    accent = "#24533E"
    if t < 3:
        draw.text((70, 90), "@sto.ckai  ·  원문 기반", font=font(28), fill=accent)
        crop = photo_on_canvas(photo, (760, 1350), zoom=1.0 + min(t, 3) * 0.012)
        rounded_paste(canvas, crop, (160, 250, 760, 1350), radius=44, border="#FFFFFF")
        draw.rounded_rectangle((70, 1530, 1010, 1830), radius=34, fill="#FFFFFF")
        draw_wrapped(draw, (110, 1585), "내 돈이 2배가 되는 데\n얼마나 걸릴까?", font(60), width=15, fill="#111111", spacing=12)
    elif t < 7:
        draw.text((70, 110), "72의 법칙", font=font(84), fill="#111111")
        draw_wrapped(draw, (70, 310), "빠르게 가늠하는\n방법이 있습니다.", font(56), width=14, fill=accent, spacing=14)
        rounded_paste(canvas, photo, (690, 940, 300, 540), radius=30, border="#FFFFFF")
        draw.text((70, 1360), "짧은 계산으로\n기간을 가늠해봅니다.", font=font(44), fill="#111111", spacing=18)
    elif t < 13:
        draw.text((70, 110), "계산은 이렇게", font=font(54), fill=accent)
        draw.rounded_rectangle((70, 350, 1010, 700), radius=34, fill="#FFFFFF")
        draw.text((540, 525), "72 ÷ 예상 연수익률(%)", font=font(56), fill="#111111", anchor="mm")
        draw.text((540, 850), "≈ 2배까지 걸리는 기간", font=font(46), fill=accent, anchor="mm")
        rounded_paste(canvas, photo, (690, 1140, 300, 540), radius=30, border="#FFFFFF")
    elif t < 20:
        draw.text((70, 110), "원문 예시", font=font(58), fill="#111111")
        rows = [("연 4%", "약 18년"), ("연 6%", "약 12년"), ("연 9%", "약 8년")]
        y = 340
        for rate, years in rows:
            draw.rounded_rectangle((70, y, 1010, y + 170), radius=26, fill="#FFFFFF")
            draw.text((120, y + 85), rate, font=font(48), fill=accent, anchor="lm")
            draw.text((950, y + 85), years, font=font(48), fill="#111111", anchor="rm")
            y += 205
        rounded_paste(canvas, photo, (690, 1160, 300, 540), radius=30, border="#FFFFFF")
    elif t < 26:
        draw.text((70, 110), "근삿값인 이유", font=font(58), fill="#111111")
        draw_wrapped(draw, (70, 380), "수익 재투자와\n비슷한 수익률이\n이어진다고 가정합니다.", font(56), width=13, fill=accent, spacing=16)
        rounded_paste(canvas, photo, (650, 1040, 330, 600), radius=30, border="#FFFFFF")
    else:
        draw.text((70, 120), "72의 법칙", font=font(70), fill="#111111")
        draw_wrapped(draw, (70, 390), "원문 기반\n개념 정리", font(60), width=13, fill=accent, spacing=16)
        draw_wrapped(draw, (70, 900), "출처: @sto.ckai Threads\n투자 권유가 아닌 정보 정리", font(38), width=22, fill="#333333", spacing=14)
        rounded_paste(canvas, photo, (690, 1080, 300, 540), radius=30, border="#FFFFFF")
    draw.text((70, 1845), "얼굴 변형 없음 · 원본 사진 기반", font=font(24), fill="#555555")
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--frame-rate", type=int, default=6)
    args = parser.parse_args()
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    cards = [
        "내 돈이 2배가 되는 데 얼마나 걸릴까?",
        "‘72의 법칙’",
        "계산식",
        "원문 예시",
        "꼭 기억할 조건",
    ]
    del cards  # labels are encoded in make_card to keep the render deterministic.
    mascot = Image.open(MASCOT).convert("RGB")
    photo = Image.open(PHOTO).convert("RGB")
    for index in range(1, 6):
        make_card(index, CARDS_DIR / f"card-{index:02d}.png", mascot)
    if FRAMES_DIR.exists():
        shutil.rmtree(FRAMES_DIR)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    total = args.seconds * args.frame_rate
    for frame_index in range(total):
        t = frame_index / args.frame_rate
        make_reel_frame(photo, t).save(FRAMES_DIR / f"frame-{frame_index:04d}.png", format="PNG", optimize=True)
    print({"cards": [str(p) for p in sorted(CARDS_DIR.glob("card-*.png"))], "frames": total, "frames_dir": str(FRAMES_DIR)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
