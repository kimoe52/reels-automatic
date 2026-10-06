from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "automation/meta-threads/queue/2026-09-23/jev-demo-v9/assets"
W, H, FPS = 1080, 1920, 30
DURATION = 18.0
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

# Bright editorial paper with a compact ink palette. No gradients, stock scenes,
# simulated cursor typing, or fake product dashboard.
PAPER = "#F5F4EF"
WHITE = "#FFFFFF"
INK = "#202832"
MUTED = "#737A80"
RULE = "#D9D9D2"
LIME = "#C6E878"
CORAL = "#EA7168"
BLUE = "#8DABC9"
LAVENDER = "#B9A4D6"
SOFT_GREEN = "#E8EFD9"
PANEL = "#202832"
PANEL_2 = "#2C3540"

SCENES = ((0.0, 3.35), (3.35, 6.65), (6.65, 10.35), (10.35, 14.2), (14.2, 18.0))


def fnt(size: int, *, bold: bool = False, mono: bool = False):
    return ImageFont.truetype(MONO if mono else FONT, size=size, index=0 if mono else (6 if bold else 0))


def txt(d: ImageDraw.ImageDraw, xy, s: str, size: int, fill=INK, *, bold=False,
        mono=False, anchor=None, spacing=10):
    d.multiline_text(xy, s, font=fnt(size, bold=bold, mono=mono), fill=fill,
                     anchor=anchor, spacing=spacing)


def rr(d: ImageDraw.ImageDraw, box, radius: int, fill, outline=None, width=2):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def ease(v: float) -> float:
    v = max(0.0, min(1.0, v))
    return 1 - (1 - v) ** 3


def common(scene: int, t: float):
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    txt(d, (72, 72), "@sto.ckai  /  BUILD NOTES", 21, MUTED, mono=True)
    txt(d, (1008, 72), f"{scene:02d}  /  05", 21, MUTED, mono=True, anchor="ra")
    d.line((72, 126, 1008, 126), fill=RULE, width=2)
    # Progress line mirrors the carousel's numbered editorial system.
    d.line((72, 1842, 1008, 1842), fill=RULE, width=4)
    p = max(0.0, min(1.0, ((scene - 1) + min(1.0, t / 3.0)) / 5.0))
    d.line((72, 1842, 72 + int(936 * p), 1842), fill=INK, width=5)
    return im, d


def draw_hook(t: float):
    im, d = common(1, t)
    txt(d, (72, 220), "BUILD PAUSED  /  CONCEPT EXAMPLE", 18, CORAL, mono=True)
    txt(d, (72, 288), "코딩 AI가 멈춘 뒤,", 67, INK, bold=True)
    txt(d, (72, 374), "다음 수는 누가 정해?", 67, INK, bold=True)

    # A restrained, legible error panel: a visual example, not a fabricated IDE capture.
    top = 570
    rr(d, (72, top, 1008, top + 560), 30, PANEL)
    rr(d, (72, top, 1008, top + 75), 30, PANEL_2)
    d.rectangle((72, top + 45, 1008, top + 75), fill=PANEL_2)
    for i, color in enumerate((CORAL, "#E2BD72", "#93B78D")):
        x = 112 + i * 34
        d.ellipse((x - 8, top + 29, x + 8, top + 45), fill=color)
    txt(d, (220, top + 37), "build.log  ·  sample", 20, "#D5D9DC", mono=True, anchor="lm")
    pulse = ease(min(1, max(0, (t - 0.15) / 0.45)))
    rr(d, (112, top + 130, 112 + int(844 * pulse), top + 222), 18, "#3A2D33")
    txt(d, (145, top + 176), "ERROR", 23, CORAL, mono=True, anchor="lm")
    txt(d, (258, top + 176), "Build stopped", 34, WHITE, bold=True, anchor="lm")
    txt(d, (112, top + 282), "한 번 더 실행할까?", 38, WHITE, bold=True)
    txt(d, (112, top + 350), "도구를 바꿀까?  사람에게 넘길까?", 30, "#C9CDD0")
    txt(d, (112, top + 482), "개념 예시 화면 · 실제 실행 로그 아님", 18, "#AAB2B8")

    underline = ease(min(1, max(0, (t - 2.1) / 0.42)))
    d.rounded_rectangle((72, 1224, 72 + int(612 * underline), 1238), radius=7, fill=LIME)
    txt(d, (72, 1280), "실패 다음의 선택을", 48, INK, bold=True)
    txt(d, (72, 1342), "자동화할 수 있을까?", 48, INK, bold=True)
    return im


def draw_choices(t: float):
    im, d = common(2, t)
    txt(d, (72, 220), "AFTER THE ERROR", 18, CORAL, mono=True)
    txt(d, (72, 286), "막힌 다음,", 74, INK, bold=True)
    txt(d, (72, 378), "선택지는 네 갈래", 74, INK, bold=True)

    labels = (("01", "다시 시도", CORAL), ("02", "모델 바꾸기", BLUE),
              ("03", "다른 도구로 우회", LAVENDER), ("04", "사람에게 넘기기", "#8DA66F"))
    start_y, row_h, gap = 540, 174, 24
    for i, (num, label, color) in enumerate(labels):
        local = (t - (0.16 + i * 0.20)) / 0.42
        a = ease(local)
        y = start_y + i * (row_h + gap) + int((1 - a) * 28)
        x = 96 + int((1 - a) * 42)
        rr(d, (x, y, 1008, y + row_h), 26, WHITE, outline=RULE, width=2)
        rr(d, (x + 24, y + 25, x + 108, y + 149), 18, color)
        txt(d, (x + 66, y + 87), num, 24, INK, mono=True, anchor="mm")
        txt(d, (x + 144, y + 88), label, 38, INK, bold=True, anchor="lm")
        d.line((x + 817, y + 87, x + 862, y + 87), fill=color, width=4)
        d.polygon(((x + 852, y + 76), (x + 870, y + 87), (x + 852, y + 98)), fill=color)

    rr(d, (72, 1375, 1008, 1572), 26, SOFT_GREEN)
    txt(d, (108, 1432), "이 중 무엇을 고를지 판단하는 것.", 31, INK, bold=True)
    txt(d, (108, 1490), "선택지를 실행하는 건 앱의 몫.", 28, MUTED)
    return im


def draw_evaluate(t: float):
    im, d = common(3, t)
    txt(d, (72, 220), "WHAT JEV EVALUATES", 18, CORAL, mono=True)
    txt(d, (72, 286), "상태 + 질문 → 판단", 72, INK, bold=True)
    txt(d, (72, 376), "Jev는 다음 행동을 직접 실행하지 않아.", 31, MUTED)

    # State and typed question are the two inputs described by the official model card.
    inputs = ((72, 520, 514, 770, "STATE", "빌드가 실패함\n사용 가능한 도구들", BLUE),
              (566, 520, 1008, 770, "TYPED QUESTION", "어떤 복구 경로가\n조건에 맞을까?", LAVENDER))
    for x1, y1, x2, y2, label, body, color in inputs:
        rr(d, (x1, y1, x2, y2), 24, WHITE, outline=RULE, width=2)
        d.rounded_rectangle((x1, y1, x1 + 11, y2), radius=5, fill=color)
        txt(d, (x1 + 36, y1 + 38), label, 17, color, mono=True)
        txt(d, (x1 + 36, y1 + 102), body, 27, INK, bold=True, spacing=13)

    # The arrow travels toward the model without showing a made-up answer.
    y = 838
    d.line((540, 790, 540, y + 35), fill=INK, width=4)
    d.polygon(((528, y + 24), (540, y + 40), (552, y + 24)), fill=INK)
    jev_y = 915 + int((1 - ease((t - 0.18) / 0.42)) * 18)
    rr(d, (356, jev_y, 724, jev_y + 124), 30, INK)
    txt(d, (540, jev_y + 62), "Jev", 58, LIME, bold=True, anchor="mm")
    txt(d, (540, 1080), "구조화된 반환 형식", 26, MUTED, bold=True, anchor="mm")

    types = ((72, 1142, 340, 1254, "choices", CORAL),
             (372, 1142, 634, 1254, "scores", BLUE),
             (666, 1142, 1008, 1254, "boolean probabilities", LAVENDER))
    for x1, y1, x2, y2, label, color in types:
        rr(d, (x1, y1, x2, y2), 24, WHITE, outline=color, width=3)
        txt(d, ((x1 + x2) // 2, (y1 + y2) // 2), label, 19, INK, mono=True, anchor="mm")
    rr(d, (72, 1340, 1008, 1516), 23, "#EBE8F1")
    txt(d, (108, 1393), "개념 입력 예시", 22, INK, bold=True)
    txt(d, (108, 1450), "실제 API 요청이나 Jev 응답값을 보여주는 장면은 아님", 21, MUTED)
    txt(d, (72, 1588), "공식 설명: shared state + typed questions → typed judgments", 18, MUTED)
    return im


def draw_boundary(t: float):
    im, d = common(4, t)
    txt(d, (72, 220), "WHO TAKES THE ACTION?", 18, CORAL, mono=True)
    txt(d, (72, 286), "판단을 실제 동작으로", 66, INK, bold=True)
    txt(d, (72, 370), "옮기는 건 앱의 코드", 66, INK, bold=True)

    rows = [
        ("APP", "현재 상태 + typed question", BLUE),
        ("JEV", "구조화된 판단 반환", "#8DA66F"),
        ("APP CODE", "정책을 확인하고 동작 실행", CORAL),
    ]
    y0, h, gap = 520, 190, 56
    for i, (head, body, color) in enumerate(rows):
        p = ease((t - (0.18 + i * 0.24)) / 0.48)
        x = 92 + int((1 - p) * 34)
        y = y0 + i * (h + gap)
        rr(d, (x, y, 988, y + h), 28, WHITE, outline=RULE, width=2)
        rr(d, (x + 28, y + 28, x + 224, y + h - 28), 20, color)
        txt(d, (x + 126, y + h // 2), head, 22, INK, mono=True, anchor="mm")
        txt(d, (x + 260, y + h // 2), body, 31, INK, bold=True, anchor="lm")
        if i < 2:
            end = y + h + int(42 * ease((t - (0.56 + i * 0.23)) / 0.36))
            d.line((540, y + h + 6, 540, end), fill=INK, width=4)
            if end > y + h + 34:
                d.polygon(((528, end - 12), (540, end + 4), (552, end - 12)), fill=INK)

    rr(d, (72, 1310, 1008, 1496), 24, SOFT_GREEN)
    txt(d, (108, 1364), "retry  ·  switch model  ·  route  ·  review", 21, INK, mono=True)
    txt(d, (108, 1422), "앱이 자기 정책에 맞는 다음 동작을 정해.", 26, INK, bold=True)
    txt(d, (72, 1570), "Jev의 판단값 자체가 명령 실행은 아니야.", 22, MUTED)
    return im


def draw_summary(t: float):
    im, d = common(5, t)
    txt(d, (72, 220), "ONE-LINE SUMMARY", 18, CORAL, mono=True)
    txt(d, (72, 304), "일하는 AI가 있다면,", 55, INK, bold=True)
    txt(d, (72, 382), "Jev는 다음 수를 판단해.", 61, INK, bold=True)

    rr(d, (72, 560, 1008, 796), 28, WHITE, outline=RULE, width=2)
    rr(d, (98, 590, 278, 766), 22, BLUE)
    txt(d, (188, 648), "GPT\nClaude\nCodex", 24, INK, bold=True, anchor="mm", spacing=7)
    txt(d, (322, 632), "글·코드·작업을 만든다", 34, INK, bold=True)
    txt(d, (322, 694), "생성하고 실제 작업을 수행", 23, MUTED)

    rr(d, (72, 840, 1008, 1076), 28, INK)
    rr(d, (98, 870, 278, 1046), 22, LIME)
    txt(d, (188, 958), "Jev", 46, INK, bold=True, anchor="mm")
    txt(d, (322, 912), "상태를 평가해 다음 행동을 판단", 31, WHITE, bold=True)
    txt(d, (322, 976), "실행은 연결한 앱 코드가 담당", 23, "#CBD1D5")

    d.line((72, 1164, 1008, 1164), fill=RULE, width=2)
    txt(d, (72, 1222), "한 줄로 기억하면", 25, MUTED, bold=True)
    txt(d, (72, 1284), "Jev는 판단.", 66, INK, bold=True)
    txt(d, (72, 1364), "실행은 연결한 앱.", 66, INK, bold=True)
    rr(d, (72, 1510, 1008, 1650), 24, LIME)
    txt(d, (108, 1580), "다음 자동화 설계할 때 저장해두기", 29, INK, bold=True, anchor="lm")
    txt(d, (72, 1728), "출처  Vercel AI Gateway · Jev model card", 18, MUTED)
    txt(d, (72, 1762), "vercel.com/ai-gateway/models/jev", 17, MUTED, mono=True)
    return im


def scene_at(t: float):
    for idx, (start, end) in enumerate(SCENES):
        if start <= t < end or idx == len(SCENES) - 1:
            local = (t - start) / (end - start)
            return (draw_hook, draw_choices, draw_evaluate, draw_boundary, draw_summary)[idx](local * 3.0)
    return draw_summary(1.0)


def render_frames():
    OUT.mkdir(parents=True, exist_ok=True)
    frames = OUT / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    for i in range(int(FPS * DURATION)):
        t = i / FPS
        frame = scene_at(t)
        # A short, soft swipe at every section boundary keeps motion editorial.
        for boundary in (3.35, 6.65, 10.35, 14.2):
            delta = t - boundary
            if 0 <= delta < 0.11:
                x = int((delta / 0.11) * W)
                dr = ImageDraw.Draw(frame)
                dr.rectangle((x - 22, 0, x + 22, H), fill=LIME)
        frame.save(frames / f"frame-{i:05d}.jpg", quality=96, subsampling=0)

    # Vertical cover and a five-beat review sheet for quick visual inspection.
    cover = scene_at(2.9)
    cover.save(OUT / "jev-reel-v9-cover.png")
    samples = [scene_at((start + end) / 2) for start, end in SCENES]
    tw, th = 216, 384
    sheet = Image.new("RGB", (tw * 5 + 48 * 6, th + 112), PAPER)
    sd = ImageDraw.Draw(sheet)
    for i, sample in enumerate(samples):
        x = 48 + i * (tw + 48)
        thumb = sample.resize((tw, th), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x, 24))
        txt(sd, (x, 432), f"CUT 0{i + 1}", 16, MUTED, mono=True)
    sheet.save(OUT / "storyboard-v9.png")
    print(f"frames: {frames}")
    print(f"cover: {OUT / 'jev-reel-v9-cover.png'}")
    print(f"storyboard: {OUT / 'storyboard-v9.png'}")


if __name__ == "__main__":
    render_frames()
