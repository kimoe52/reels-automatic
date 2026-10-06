#!/usr/bin/env python3
"""Render a bright, music-backed 72-rule Reel using the owner's unchanged images."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT = Path(__file__).resolve().parents[3]
DEMO = PROJECT / "automation" / "meta-threads" / "queue" / "2026-09-23" / "demo-72-rule"
ASSETS = DEMO / "assets"
PHOTO = PROJECT / "content" / "character" / "reel-human-reference" / "reference-03.png"
SNAKE = PROJECT / "content" / "character" / "character-creature.png"
MUSIC = ASSETS / "audio" / "mixkit-gimme-that-groove-872.mp3"
FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
WIDTH, HEIGHT = 1080, 1920
FPS, DURATION = 24, 17

INK = "#17202B"
WHITE = "#FFFDF8"
LAVENDER = "#CBAEFF"
LIME = "#C8F36B"
YELLOW = "#FFDB58"
CORAL = "#FF8E86"
MINT = "#A9E7D2"
BLUE = "#9DDCFF"
PURPLE = "#8660D4"
GRAY = "#4F5964"

PERSON = Image.open(PHOTO).convert("RGB")
SNAKE_IMAGE = Image.open(SNAKE).convert("RGB")


def font(size: int, *, heavy: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size=size, index=6 if heavy else 0)


def ease_out(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return 1 - (1 - value) ** 3


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    size: int,
    *,
    fill: str = INK,
    anchor: str | None = None,
    heavy: bool = False,
) -> None:
    draw.text(xy, text, font=font(size, heavy=heavy), fill=fill, anchor=anchor)


def rounded_label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    text: str,
    *,
    fill: str,
    text_fill: str = INK,
    size: int = 30,
) -> None:
    draw.rounded_rectangle(xy, radius=24, fill=fill)
    draw_text(draw, ((xy[0] + xy[2]) // 2, (xy[1] + xy[3]) // 2), text, size,
              fill=text_fill, anchor="mm", heavy=True)


def header(draw: ImageDraw.ImageDraw, label: str, page: str, *, fill: str = INK) -> None:
    draw_text(draw, (72, 66), "@sto.ckai", 29, fill=fill, heavy=True)
    draw_text(draw, (1008, 70), page, 25, fill=fill, anchor="ra")
    draw.line((72, 126, 1008, 126), fill=fill, width=3)
    draw_text(draw, (72, 178), label, 32, fill=fill, heavy=True)


def original_portrait_frame() -> Image.Image:
    """Crop side fingertips; preserve the face pixels and image proportions exactly."""
    source_w, source_h = PERSON.size
    crop_w = round(source_h * 0.42)
    crop_h = round(crop_w * HEIGHT / WIDTH)
    left = max(0, min(source_w - crop_w, (source_w - crop_w) // 2))
    # Keep the full top of the hair; trim shirt at the bottom instead of fingers at the sides.
    crop = PERSON.crop((left, 0, left + crop_w, min(source_h, crop_h)))
    return crop.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


PORTRAIT_FRAME = original_portrait_frame()


def draw_opening(t: float) -> Image.Image:
    image = PORTRAIT_FRAME.copy()
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 176), fill=LIME)
    draw_text(draw, (72, 64), "72의 법칙", 52, heavy=True)
    draw_text(draw, (1008, 74), "돈 이야기", 28, anchor="ra", heavy=True)
    # The face is not retouched or generated; the title sits over the shirt only.
    y = 1450 + int((1 - ease_out(t / 0.35)) * 55)
    draw.rectangle((0, y, WIDTH, HEIGHT), fill=YELLOW)
    draw_text(draw, (72, y + 52), "내 돈이 두 배 되는 데", 46, heavy=True)
    draw_text(draw, (72, y + 120), "몇 년?", 100, heavy=True)
    draw.ellipse((870, y + 70, 1000, y + 200), fill=CORAL)
    draw_text(draw, (935, y + 135), "?", 78, fill=WHITE, anchor="mm", heavy=True)
    return image


def draw_formula(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), LAVENDER)
    draw = ImageDraw.Draw(image)
    draw.ellipse((680, 202, 1175, 697), fill=YELLOW)
    draw.ellipse((-200, 1280, 340, 1820), fill=CORAL)
    header(draw, "계산은 한 줄", "01 / 04")

    draw_text(draw, (72, 390), "72", 300, heavy=True)
    draw.rounded_rectangle((72, 735, 1008, 910), radius=34, fill=WHITE)
    draw_text(draw, (118, 823), "÷", 104, fill=PURPLE, anchor="lm", heavy=True)
    draw_text(draw, (255, 823), "연 수익률(%)", 64, anchor="lm", heavy=True)
    draw.line((72, 995, 1008, 995), fill=INK, width=4)
    draw_text(draw, (72, 1060), "≈ 2배까지 걸리는 해", 47, heavy=True)

    reveal = ease_out((t - 2.0) / 0.7)
    draw.rounded_rectangle((72, 1245, 1008, 1570), radius=44, fill=LIME)
    draw_text(draw, (120, 1310), "연 6%라고 가정하면", 36, fill=GRAY)
    draw_text(draw, (120, 1425), "72 ÷ 6", 78, heavy=True)
    draw_text(draw, (520, 1425), "=", 64, fill=PURPLE, anchor="mm", heavy=True)
    draw.rounded_rectangle((620, 1365, 940, 1495), radius=28, fill=CORAL)
    draw_text(draw, (780, 1430), "12년", int(56 + 16 * reveal),
              fill=WHITE, anchor="mm", heavy=True)
    draw_text(draw, (72, 1653), "복리 계산으로 빠르게 어림해요", 32, fill=INK)
    return image


def curve_point(progress: float) -> tuple[int, int]:
    left, right = 148, 850
    top, bottom = 570, 1355
    year = 12 * min(1.0, max(0.0, progress))
    value = 1.06**year
    y = bottom - round((bottom - top) * (value - 1) / (2.0122 - 1))
    x = left + round((right - left) * year / 12)
    return x, y


def draw_growth(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), YELLOW)
    draw = ImageDraw.Draw(image)
    draw.ellipse((748, 195, 1180, 625), fill=CORAL)
    header(draw, "숫자로 보면", "02 / 04")
    draw_text(draw, (72, 310), "12년 뒤", 72, heavy=True)
    draw_text(draw, (72, 405), "계산상 약", 40, fill=GRAY)
    draw.rounded_rectangle((620, 258, 1008, 510), radius=42, fill=LAVENDER)
    draw_text(draw, (814, 388), "2×", 130, anchor="mm", heavy=True)

    left, right, top, bottom = 148, 850, 570, 1355
    for y, text in ((bottom, "1×"), (top, "2×")):
        draw.line((left, y, right, y), fill="#D2B83E", width=3)
    draw_text(draw, (95, y), text, 31, fill=GRAY, anchor="rm")
    draw.line((left, top - 8, left, bottom), fill=INK, width=3)
    draw.line((left, bottom, right, bottom), fill=INK, width=3)

    reveal = ease_out((t - 5.15) / 3.5)
    steps = max(2, int(45 * reveal))
    curve = [curve_point(reveal * n / (steps - 1)) for n in range(steps)]
    if len(curve) > 1:
        draw.polygon([(left, bottom), *curve, (curve[-1][0], bottom)], fill=MINT)
        draw.line(curve, fill=PURPLE, width=13, joint="curve")
        px, py = curve[-1]
        draw.ellipse((px - 17, py - 17, px + 17, py + 17), fill=INK)

    draw_text(draw, (148, 1415), "처음", 28, fill=GRAY)
    draw_text(draw, (850, 1415), "12년", 28, fill=GRAY, anchor="ra")
    draw.rounded_rectangle((72, 1530, 1008, 1730), radius=36, fill=WHITE)
    draw_text(draw, (118, 1593), "연 6% 수익을 재투자한다고 가정", 37, heavy=True)
    draw_text(draw, (118, 1660), "실제 수익률을 예측하는 그래프는 아니에요", 31, fill=GRAY)
    return image


def draw_comparison(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), MINT)
    draw = ImageDraw.Draw(image)
    draw.ellipse((778, 1160, 1290, 1672), fill=LAVENDER)
    header(draw, "가정 수익률을 바꿔 보면", "03 / 04")
    draw_text(draw, (72, 335), "같은 공식,", 66, heavy=True)
    draw_text(draw, (72, 418), "다른 기간", 94, fill=PURPLE, heavy=True)
    rows = [("4%", "18년", 670, CORAL), ("6%", "12년", 490, YELLOW),
            ("9%", "8년", 330, LAVENDER)]
    start = 680
    for index, (rate, years, bar_w, accent) in enumerate(rows):
        reveal = ease_out((t - 9.05 - 0.17 * index) / 0.48)
        y = start + index * 280
        slide = int((1 - reveal) * 28)
        draw.rounded_rectangle((72 + slide, y, 1008, y + 218), radius=36, fill=WHITE)
        draw_text(draw, (112 + slide, y + 37), rate, 76, heavy=True)
        draw_text(draw, (945 + slide, y + 47), f"약 {years}", 51, anchor="ra", heavy=True)
        draw.rounded_rectangle((112 + slide, y + 132, 112 + slide + bar_w, y + 178),
                               radius=23, fill=accent)
    draw_text(draw, (72, 1595), "72 ÷ 수익률(%) ≈ 두 배까지 걸리는 해", 33, heavy=True)
    return image


def draw_caveat(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), CORAL)
    draw = ImageDraw.Draw(image)
    draw.ellipse((-180, 1360, 360, 1900), fill=YELLOW)
    header(draw, "이건 계산상의 어림값", "04 / 04")
    draw_text(draw, (72, 368), "두 가지를", 77, heavy=True)
    draw_text(draw, (72, 466), "가정해요", 110, fill=WHITE, heavy=True)

    reveal = ease_out((t - 12.7) / 0.6)
    for i, (number, title, detail, color) in enumerate([
        ("01", "수익 재투자", "얻은 수익을 다시 투자", LIME),
        ("02", "비슷한 수익률", "이 이어진다고 가정", LAVENDER),
    ]):
        y = 760 + i * 340 + int((1 - reveal) * 24)
        draw.rounded_rectangle((72, y, 1008, y + 270), radius=38, fill=color)
        draw_text(draw, (120, y + 49), number, 34, fill=PURPLE, heavy=True)
        draw_text(draw, (120, y + 95), title, 67, heavy=True)
        draw_text(draw, (120, y + 182), detail, 32, fill=GRAY)
    draw_text(draw, (72, 1515), "실제 투자 수익이나 기간을 보장하지 않아요.",
              34, fill=WHITE, heavy=True)
    draw_text(draw, (72, 1640), "개념을 빠르게 이해하는 도구예요.", 34, fill=INK)
    return image


def draw_close(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), LAVENDER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 170), fill=LIME)
    draw_text(draw, (72, 64), "@sto.ckai", 31, heavy=True)
    draw_text(draw, (1008, 72), "원문 기반", 27, anchor="ra")
    draw.rounded_rectangle((250, 260, 830, 840), radius=46, fill=WHITE)
    snake = SNAKE_IMAGE.resize((550, 550), Image.Resampling.LANCZOS)
    image.paste(snake, (265, 275))

    draw_text(draw, (72, 990), "기억할 공식", 42, fill=GRAY)
    draw.rounded_rectangle((72, 1080, 1008, 1305), radius=38, fill=YELLOW)
    draw_text(draw, (540, 1192), "72 ÷ 수익률(%)", 68, anchor="mm", heavy=True)
    draw_text(draw, (72, 1402), "≈ 두 배까지 걸리는 해", 43, heavy=True)
    draw.line((72, 1530, 1008, 1530), fill=INK, width=3)
    draw_text(draw, (72, 1600), "가정에 따른 근삿값 · 수익 보장 아님", 31, fill=INK)
    return image


def frame(t: float) -> Image.Image:
    if t < 1.8:
        return draw_opening(t)
    if t < 5.1:
        return draw_formula(t)
    if t < 9.0:
        return draw_growth(t)
    if t < 12.7:
        return draw_comparison(t)
    if t < 15.0:
        return draw_caveat(t)
    return draw_close(t)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ASSETS / "72-rule-reel-v3.mp4")
    parser.add_argument("--music", type=Path, default=MUSIC)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    music = args.music.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not Path(ffmpeg).is_file():
        raise RuntimeError("ffmpeg를 찾지 못해 MP4를 만들 수 없습니다.")
    if not music.is_file():
        raise RuntimeError(f"배경음악 파일이 없습니다: {music}")

    with tempfile.TemporaryDirectory(prefix="72-rule-reel-v3-") as scratch:
        scratch_dir = Path(scratch)
        for frame_index in range(FPS * DURATION):
            frame(frame_index / FPS).save(scratch_dir / f"frame-{frame_index:04d}.png", format="PNG")
        frame(1.2).save(ASSETS / "72-rule-reel-v3-cover.png", format="PNG", optimize=True)
        subprocess.run([
            ffmpeg, "-y", "-v", "error",
            "-framerate", str(FPS), "-i", str(scratch_dir / "frame-%04d.png"),
            "-i", str(music),
            "-filter_complex",
            "[1:a]atrim=0:17,afade=t=in:st=0:d=0.28,afade=t=out:st=16.2:d=0.8,volume=0.72[a]",
            "-map", "0:v:0", "-map", "[a]", "-vf", "format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
            str(output),
        ], check=True)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
