#!/usr/bin/env python3
"""Render a screen-led, photo-free 72-rule Reel draft."""

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
FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
WIDTH, HEIGHT = 1080, 1920
FPS, DURATION = 24, 17
PAPER = "#F5F4EF"
INK = "#141916"
GREEN = "#216348"
MUTED = "#777D76"
RULE = "#DADBD4"
MINT = "#DDE9DF"


def font(size: int, *, heavy: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size=size, index=6 if heavy else 0)


def ease_out(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return 1.0 - (1.0 - value) ** 3


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
    draw.text(
        xy,
        text,
        font=font(size, heavy=heavy),
        fill=fill,
        anchor=anchor,
        stroke_width=0,
        stroke_fill=fill,
    )


def draw_header(draw: ImageDraw.ImageDraw, t: float) -> None:
    draw_text(draw, (72, 74), "@sto.ckai", 30, fill=GREEN)
    draw.line((72, 132, WIDTH - 72, 132), fill=RULE, width=2)
    progress = min(1.0, t / DURATION)
    draw.line(
        (72, 132, 72 + int((WIDTH - 144) * progress), 132),
        fill=GREEN,
        width=5,
    )


def draw_kicker(draw: ImageDraw.ImageDraw, text: str, y: int = 238) -> None:
    draw.rounded_rectangle((72, y, 84, y + 43), radius=6, fill=GREEN)
    draw_text(draw, (108, y - 2), text, 34, fill=GREEN)


def draw_growth_graph(draw: ImageDraw.ImageDraw, reveal: float) -> None:
    left, right = 184, 930
    top, bottom = 1240, 1480

    def point(year: float) -> tuple[int, int]:
        value = 1.06**year
        x = left + round((right - left) * year / 12)
        y = bottom - round((bottom - top) * (value - 1) / (2.0122 - 1))
        return x, y

    for multiple, label in ((1.0, "1×"), (1.5, "1.5×"), (2.0, "2×")):
        y = bottom - round((bottom - top) * (multiple - 1) / (2.0122 - 1))
        draw.line((left, y, right, y), fill=RULE, width=2)
        draw_text(draw, (72, y - 22), label, 28, fill=MUTED)

    draw.line((left, top - 8, left, bottom), fill=INK, width=2)
    draw.line((left, bottom, right, bottom), fill=INK, width=2)
    for year in (0, 6, 12):
        x, _ = point(float(year))
        draw.line((x, bottom, x, bottom + 10), fill=INK, width=2)
        draw_text(draw, (x, bottom + 20), f"{year}년", 26, fill=MUTED, anchor="ma")

    last_year = 12 * min(1.0, max(0.0, reveal))
    samples = max(2, round(last_year * 8))
    curve = [point(last_year * n / (samples - 1)) for n in range(samples)]
    if len(curve) > 1:
        draw.polygon([(left, bottom), *curve, (curve[-1][0], bottom)], fill=MINT)
        draw.line(curve, fill=GREEN, width=9, joint="curve")
    x, y = curve[-1]
    radius = 12
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=GREEN)


def frame(t: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    draw_header(draw, t)

    if t < 3.0:
        draw_kicker(draw, "72의 법칙 · 연 6% 가정")
        draw_text(draw, (72, 420), "내 돈, 2배까지?", 78, heavy=True)
        reveal = ease_out((t - 0.12) / 0.78)
        number_size = int(210 + reveal * 46)
        draw_text(draw, (72, 584), "약", 46, fill=MUTED)
        draw_text(draw, (68, 680), "12년", number_size, fill=INK, heavy=True)
        draw_text(draw, (72, 972), "72 ÷ 6 ≈ 12", 66, fill=GREEN, heavy=True)
        draw_text(draw, (74, 1050), "연 수익률(%)으로 나눈 근삿값", 31, fill=MUTED)
        draw_growth_graph(draw, ease_out((t - 0.25) / 2.4))
        draw_text(draw, (72, 1576), "수익을 매년 재투자한다고 가정", 30, fill=MUTED)

    elif t < 6.5:
        draw_kicker(draw, "계산은 한 줄")
        draw_text(draw, (72, 390), "72", 240, heavy=True)
        draw_text(draw, (350, 498), "÷", 108, fill=GREEN)
        draw_text(draw, (500, 445), "연수익률", 68, heavy=True)
        draw.text((500, 548), "(%)", font=font(48), fill=MUTED)
        draw.line((72, 710, 1008, 710), fill=RULE, width=2)
        draw_text(draw, (72, 850), "≈ 2배까지 걸리는 해", 66, fill=GREEN, heavy=True)
        draw_text(draw, (72, 1080), "연 6%라면", 44, fill=MUTED)
        draw_text(draw, (72, 1210), "72 ÷ 6 = 12년", 78, fill=INK, heavy=True)
        draw.line((72, 1320, 1008, 1320), fill=GREEN, width=7)
        draw_text(draw, (72, 1395), "가정한 수익률로 빠르게 어림해요.", 36, fill=MUTED)

    elif t < 10.5:
        draw_kicker(draw, "수익률을 바꿔 보면")
        draw_text(draw, (72, 378), "가정 수익률", 34, fill=MUTED)
        draw_text(draw, (1008, 378), "2배까지", 34, fill=MUTED, anchor="ra")
        rows = [("4%", "약 18년"), ("6%", "약 12년"), ("9%", "약 8년")]
        top = 520
        for index, (rate, years) in enumerate(rows):
            entrance = ease_out((t - 6.65 - index * 0.20) / 0.42)
            y = top + index * 255 + int((1 - entrance) * 24)
            color = GREEN if rate == "6%" else INK
            draw_text(draw, (72, y), rate, 104, fill=color, heavy=True)
            draw_text(draw, (1008, y + 27), years, 66, fill=color, anchor="ra", heavy=True)
            draw.line((72, y + 142, 1008, y + 142), fill=RULE, width=2)
        draw_text(draw, (72, 1370), "가정 수익률이 높을수록", 40, fill=MUTED)
        draw_text(draw, (72, 1430), "계산상 기간은 짧아져요.", 48, fill=INK, heavy=True)

    elif t < 14.1:
        draw_kicker(draw, "이 계산이 두는 가정")
        draw_text(draw, (72, 475), "수익 재투자", 82, heavy=True)
        draw_text(draw, (72, 575), "수익을 다시 투자한다고 보고", 36, fill=MUTED)
        draw.line((72, 700, 1008, 700), fill=RULE, width=2)
        draw_text(draw, (72, 800), "+", 74, fill=GREEN, heavy=True)
        draw_text(draw, (170, 812), "비슷한 수익률 유지", 72, heavy=True)
        draw_text(draw, (170, 914), "그 수익률이 이어진다고 보고", 36, fill=MUTED)
        draw.line((72, 1055, 1008, 1055), fill=GREEN, width=7)
        draw_text(draw, (72, 1165), "계산 결과는", 42, fill=MUTED)
        draw_text(draw, (72, 1275), "빠른 어림값", 88, fill=GREEN, heavy=True)

    else:
        draw_kicker(draw, "한눈에 정리")
        draw_text(draw, (72, 405), "연 6% 가정", 42, fill=MUTED)
        draw_text(draw, (72, 685), "약 12년", 172, fill=INK, heavy=True)
        draw.line((72, 900, 1008, 900), fill=RULE, width=2)
        draw_text(draw, (72, 1000), "72 ÷ 6 ≈ 12", 76, fill=GREEN, heavy=True)
        draw_text(draw, (72, 1105), "수익 재투자 · 비슷한 수익률 유지 가정", 34, fill=MUTED)
        draw_text(draw, (72, 1165), "실제 수익을 보장하지 않아요.", 34, fill=MUTED)
        draw.line((72, 1300, 1008, 1300), fill=RULE, width=2)
        draw_text(draw, (72, 1380), "출처  @sto.ckai Threads", 34, fill=GREEN)
        draw_text(draw, (72, 1436), "투자 권유가 아닌 개념 설명", 31, fill=MUTED)

    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ASSETS / "72-rule-reel-v2.mp4",
    )
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not Path(ffmpeg).is_file():
        raise RuntimeError("ffmpeg를 찾지 못해 MP4를 만들 수 없습니다.")

    with tempfile.TemporaryDirectory(prefix="72-rule-reel-v2-") as scratch:
        scratch_dir = Path(scratch)
        for frame_index in range(FPS * DURATION):
            t = frame_index / FPS
            frame(t).save(
                scratch_dir / f"frame-{frame_index:04d}.png",
                format="PNG",
            )
        frame(2.65).save(ASSETS / "72-rule-reel-v2-cover.png", format="PNG", optimize=True)
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-framerate",
                str(FPS),
                "-i",
                str(scratch_dir / "frame-%04d.png"),
                "-vf",
                "format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "19",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
        )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
