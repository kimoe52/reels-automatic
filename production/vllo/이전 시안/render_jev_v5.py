from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from render_jev_v4 import (
    BLACK, BLUE, CORAL, INK, LINE, LIME, MUTED, PAPER, PAPER_LIGHT,
    PURPLE, WHITE, CHAR_SNAKE, PHOTO, fnt, paper, rounded, shadow_panel,
    top_label, txt,
)

ROOT = Path(__file__).resolve().parents[3]


def marker_arrow(d: ImageDraw.ImageDraw, points, color="#F2DE63", width=7):
    # Loose, hand-marked annotation used sparingly like the carousel reference.
    d.line(points, fill=color, width=width, joint="curve")
    x, y = points[-1]
    d.line((x - 16, y - 18, x, y, x + 18, y - 12), fill=color, width=width)


def tag(d, xy, label, fill="#F4EAA4", text_fill=INK, size=17, pad=9):
    x, y = xy
    box = d.textbbox((0, 0), label, font=fnt(size))
    w = box[2] - box[0] + pad * 2
    h = box[3] - box[1] + pad * 2
    d.rounded_rectangle((x, y, x + w, y + h), radius=7, fill=fill)
    txt(d, (x + pad, y + h // 2), label, size, fill=text_fill, anchor="lm")


def card_base(index, total=5, dark=False):
    if dark:
        im = Image.new("RGB", (1080, 1350), "#17131B")
    else:
        im = paper((1080, 1350), dark=False)
    d = ImageDraw.Draw(im)
    top_label(d, right=f"{index:02d} / {total:02d}", dark=dark)
    return im, d


def render_cards(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    snake = Image.open(CHAR_SNAKE).convert("RGB")

    # 1 — clear hook and one brand character; no pretend website screenshot.
    im, d = card_base(1)
    tag(d, (64, 145), "AI AGENT / NEXT MOVE", fill="#E9DCF1", size=17)
    txt(d, (64, 270), "코딩 AI가", 74, fill=INK)
    txt(d, (64, 358), "실패했다", 96, fill=PURPLE)
    d.rectangle((64, 520, 1016, 735), fill=BLACK)
    d.rectangle((64, 520, 78, 735), fill=PURPLE)
    txt(d, (112, 570), "그 다음 선택,", 46, fill=WHITE)
    txt(d, (112, 630), "누가 골라?", 56, fill=WHITE)
    # The square background belongs to the supplied character artwork.
    snake_thumb = ImageOps.fit(snake, (230, 230), method=Image.Resampling.LANCZOS)
    im.paste(snake_thumb, (786, 826))
    txt(d, (64, 846), "RETRY?", 28, fill=CORAL, mono=True)
    txt(d, (64, 900), "OTHER AI?", 28, fill=BLUE, mono=True)
    txt(d, (64, 954), "HUMAN?", 28, fill=PURPLE, mono=True)
    marker_arrow(d, [(230, 878), (348, 850), (438, 872)], color="#E3CE50", width=6)
    txt(d, (64, 1116), "Jev는 다음 행동을 판단하는 AI", 36, fill=INK)
    txt(d, (64, 1190), "저장해두는 5장 요약", 21, fill=MUTED)
    im.save(out / "card-01.png", quality=96)

    # 2 — role contrast with open space and marker note.
    im, d = card_base(2)
    txt(d, (64, 158), "일하는 AI", 70, fill=INK)
    txt(d, (64, 244), "GPT · Claude · Codex", 31, fill=PURPLE)
    d.line((64, 330, 1016, 330), fill=LINE, width=2)
    txt(d, (96, 374), "글쓰기  /  코딩  /  실행", 33, fill=INK)
    tag(d, (730, 366), "DO THE WORK", fill="#F4EAA4", size=16)
    txt(d, (64, 520), "Jev", 86, fill=PURPLE)
    d.line((64, 630, 1016, 630), fill=LINE, width=2)
    txt(d, (96, 676), "정해진 질문의 답을 고른다", 36, fill=INK)
    tag(d, (730, 758), "MAKE A JUDGMENT", fill="#DDF0C6", size=16)
    options = [("choice", CORAL), ("score", BLUE), ("yes / no", LIME)]
    x = 96
    for label, c in options:
        rounded(d, (x, 860, x + 250, 956), 18, fill=WHITE, outline=LINE, width=2)
        d.ellipse((x + 22, 891, x + 44, 913), fill=c)
        txt(d, (x + 61, 908), label, 24, fill=INK, anchor="lm")
        x += 290
    marker_arrow(d, [(355, 1024), (456, 1060), (558, 1026)], color="#E3CE50", width=6)
    txt(d, (64, 1120), "Jev가 고른 다음 단계는", 33, fill=INK)
    txt(d, (64, 1170), "앱의 코드가 실제로 실행한다", 33, fill=PURPLE)
    txt(d, (64, 1270), "Vercel AI Gateway · 공식 모델 설명 기준", 17, fill=MUTED)
    im.save(out / "card-02.png", quality=96)

    # 3 — four paths, visual scan order, one phrase each.
    im, d = card_base(3)
    txt(d, (64, 155), "실패 다음에", 61, fill=INK)
    txt(d, (64, 232), "고를 수 있는 길", 72, fill=PURPLE)
    routes = [
        ("01", "재시도", "같은 AI에 한 번 더", CORAL),
        ("02", "다른 AI", "모델을 바꿔서", BLUE),
        ("03", "다른 툴", "다른 경로로", PURPLE),
        ("04", "사람 확인", "멈추고 검토", LIME),
    ]
    y = 390
    for n, title, desc, color in routes:
        rounded(d, (64, y, 1016, y + 152), 14, fill=WHITE, outline=LINE, width=2)
        d.rectangle((64, y, 80, y + 152), fill=color)
        txt(d, (112, y + 30), n, 19, fill=color, mono=True)
        txt(d, (188, y + 22), title, 36, fill=INK)
        txt(d, (188, y + 82), desc, 22, fill=MUTED)
        txt(d, (950, y + 74), "→", 32, fill=color, anchor="mm")
        y += 177
    marker_arrow(d, [(828, 1152), (914, 1190), (988, 1150)], color="#E3CE50", width=6)
    txt(d, (64, 1246), "고정된 규칙이면 코드로, 판단이 필요하면 Jev로", 18, fill=MUTED)
    im.save(out / "card-03.png", quality=96)

    # 4 — actual conceptual flow, explicitly not a screenshot or API output.
    im, d = card_base(4)
    tag(d, (64, 145), "개념 예시 · 실제 Jev 응답 아님", fill="#F4EAA4", size=17)
    txt(d, (64, 242), "판단과 실행은", 62, fill=INK)
    txt(d, (64, 318), "두 단계", 82, fill=PURPLE)
    steps = [
        ("상태", "빌드 실패 + 로그", BLUE),
        ("질문", "다음에 무엇을 할까?", PURPLE),
        ("답 후보", "재시도 / 다른 툴 / 사람", CORAL),
    ]
    y = 500
    for i, (label, value, color) in enumerate(steps):
        rounded(d, (64, y, 1016, y + 144), 16, fill=WHITE, outline=LINE, width=2)
        tag(d, (92, y + 28), label, fill=color, text_fill=INK, size=20, pad=10)
        txt(d, (286, y + 72), value, 29, fill=INK, anchor="lm")
        if i < len(steps) - 1:
            txt(d, (520, y + 152), "↓", 31, fill=MUTED, anchor="mm")
        y += 190
    d.rectangle((64, 1094, 1016, 1210), fill=BLACK)
    txt(d, (96, 1152), "Jev 판단 → 내 프로그램이 실행", 31, fill=WHITE, anchor="lm")
    txt(d, (64, 1270), "결과를 어떻게 쓸지는 앱 코드가 정한다", 18, fill=MUTED)
    im.save(out / "card-04.png", quality=96)

    # 5 — durable summary plus a dated current availability note.
    im, d = card_base(5, dark=True)
    txt(d, (64, 170), "일하는 AI", 56, fill=WHITE)
    txt(d, (64, 244), "GPT · Claude · Codex", 33, fill="#E9DCF1")
    d.line((64, 326, 1016, 326), fill="#514455", width=2)
    txt(d, (64, 392), "판단하는 AI", 56, fill=LIME)
    txt(d, (64, 466), "Jev", 82, fill=PURPLE)
    rounded(d, (64, 660, 1016, 860), 16, fill="#231C27", outline="#514455", width=2)
    txt(d, (104, 718), "질문과 답 후보를 정하고", 30, fill=WHITE)
    txt(d, (104, 774), "Jev의 판단을 코드에서 사용", 30, fill=LIME)
    txt(d, (64, 960), "현재 Vercel AI Gateway에서 사용 가능", 25, fill=WHITE)
    txt(d, (64, 1012), "무료 프로모션 종료: 2026.09.25", 22, fill="#E9DCF1")
    txt(d, (64, 1178), "공식 모델 페이지 확인 · 2026.09.23", 17, fill="#B9A9BC")
    txt(d, (64, 1240), "다음 오류 전에 저장", 30, fill=LIME)
    im.save(out / "card-05.png", quality=96)


def base_reel(t, duration):
    im = Image.new("RGB", (1080, 1920), "#19131D")
    d = ImageDraw.Draw(im)
    # Full-bleed dark top field; pale paper panel echoes the actual Vercel page.
    d.rectangle((0, 0, 1080, 330), fill="#2B123D")
    d.rectangle((0, 1490, 1080, 1920), fill="#201728")
    txt(d, (62, 52), "JEV / NEXT ACTION", 19, fill="#E9DCF1", mono=True)
    txt(d, (1018, 52), "VIBE CODING", 17, fill="#C4B2CB", anchor="ra", mono=True)
    d.line((62, 106, 1018, 106), fill="#5B4266", width=2)
    d.line((62, 118, 62 + int(956 * min(t / duration, 1)), 118), fill=LIME, width=5)
    return im, d


def caption(im, y, line1, line2="", accent=PURPLE, size=54, height=205):
    d = ImageDraw.Draw(im)
    d.rectangle((48, y, 1032, y + height), fill="#110F13")
    d.rectangle((48, y, 62, y + height), fill=accent)
    txt(d, (100, y + 52), line1, size, fill=WHITE)
    if line2:
        txt(d, (100, y + 116), line2, size, fill=WHITE)


def round_photo(im, src, box):
    x, y, w, h = box
    fitted = ImageOps.contain(src.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS)
    panel = Image.new("RGB", (w, h), "#28212D")
    panel.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=18, fill=255)
    im.paste(panel, (x, y), mask)
    ImageDraw.Draw(im).rounded_rectangle((x, y, x + w, y + h), radius=18, outline="#E9DCF1", width=3)


def scene_hook(im, t):
    d = ImageDraw.Draw(im)
    txt(d, (66, 190), "BUILD FAILED", 32, fill=CORAL, mono=True)
    rounded(d, (66, 268, 1014, 758), 24, fill="#0C0B0F", outline="#6A556F", width=2)
    txt(d, (112, 342), "$ npm run build", 32, fill=BLUE, mono=True)
    txt(d, (112, 434), "✕ Module not found", 41, fill=CORAL, mono=True)
    txt(d, (112, 544), "what next?", 49, fill=LIME, mono=True)
    caption(im, 1080, "코딩 AI가 실패하면", "그 다음은 누가 골라?", accent=CORAL, size=51)
    txt(d, (66, 1330), "예시 오류 화면", 19, fill="#C4B2CB")


def scene_reaction(im, photo, t):
    d = ImageDraw.Draw(im)
    txt(d, (66, 190), "오류는 났고…", 61, fill=WHITE)
    txt(d, (66, 270), "내가 또 정해?", 71, fill=LIME)
    round_photo(im, photo, (650, 415, 340, 605))
    # Small options enter in sequence, making the visual a real edit rather than a static card.
    opts = [("다시 돌릴까?", CORAL), ("다른 AI?", BLUE), ("사람 확인?", PURPLE)]
    shown = min(3, int(t * 1.3) + 1)
    y = 545
    for i, (label, color) in enumerate(opts[:shown]):
        rounded(d, (66, y, 580, y + 98), 16, fill="#29222F", outline=color, width=3)
        txt(d, (104, y + 49), label, 34, fill=WHITE, anchor="lm")
        y += 126
    caption(im, 1200, "선택지가 늘수록", "작은 판단이 쌓인다", accent=PURPLE, size=47)


def scene_fact(im, t):
    d = ImageDraw.Draw(im)
    txt(d, (66, 188), "Vercel AI Gateway", 24, fill="#C4B2CB", mono=True)
    rounded(d, (66, 258, 1014, 904), 18, fill=PAPER_LIGHT, outline="#B7A9B7", width=2)
    txt(d, (112, 318), "Jev", 72, fill=INK)
    txt(d, (112, 410), "TypeSafe AI · System One", 29, fill=PURPLE)
    d.line((112, 484, 968, 484), fill=LINE, width=2)
    txt(d, (112, 536), "typed questions → choices / scores", 27, fill=INK)
    txt(d, (112, 590), "boolean probabilities · routing", 25, fill=INK)
    tag(d, (112, 710), "공식 모델 설명 요약", fill="#F4EAA4", size=17)
    caption(im, 1054, "문장을 길게 쓰는 대신", "정해진 답 중 판단", accent=BLUE, size=48)
    txt(d, (66, 1320), "출처: Vercel AI Gateway · models/jev", 17, fill="#C4B2CB")


def scene_flow(im, t):
    d = ImageDraw.Draw(im)
    txt(d, (66, 184), "상태 + 질문 + 답 후보", 53, fill=WHITE)
    labels = [("1", "빌드 실패", CORAL), ("2", "Jev 판단", BLUE), ("3", "앱 코드 실행", LIME)]
    x_positions = [66, 394, 722]
    for i, (num, label, color) in enumerate(labels):
        x = x_positions[i]
        rounded(d, (x, 515, x + 292, 780), 24, fill="#28212D", outline=color, width=4)
        txt(d, (x + 32, 566), num, 25, fill=color, mono=True)
        txt(d, (x + 32, 650), label, 31, fill=WHITE)
        if i < 2:
            txt(d, (x + 300, 640), "→", 36, fill="#E9DCF1", anchor="mm")
    tag(d, (66, 854), "개념도 · 실행 권한은 앱 코드에 있음", fill="#E9DCF1", size=18)
    opts = ["재시도", "다른 AI", "다른 툴", "사람 확인"]
    x = 66
    for i, word in enumerate(opts):
        w = 220 if i != 3 else 250
        rounded(d, (x, 1002, x + w, 1084), 14, fill="#17131B", outline="#57445E", width=2)
        txt(d, (x + w / 2, 1043), word, 24, fill=WHITE, anchor="mm")
        x += w + 18
    caption(im, 1215, "Jev는 고르고", "내 프로그램이 움직인다", accent=LIME, size=48)


def scene_end(im, t):
    d = ImageDraw.Draw(im)
    txt(d, (66, 245), "Jev", 112, fill=LIME)
    txt(d, (66, 392), "일하는 AI 옆에서", 55, fill=WHITE)
    txt(d, (66, 470), "다음 선택을 판단", 62, fill=PURPLE)
    rounded(d, (66, 700, 1014, 902), 22, fill="#28212D", outline="#65516D", width=3)
    txt(d, (112, 762), "현재 Vercel AI Gateway에서 사용 가능", 29, fill=WHITE)
    txt(d, (112, 822), "무료 프로모션은 2026.09.25까지", 24, fill="#E9DCF1")
    txt(d, (66, 1050), "이 구조 저장해두기", 38, fill=LIME)
    txt(d, (66, 1122), "공식 페이지 확인 · 2026.09.23", 18, fill="#C4B2CB")
    src = Image.open(CHAR_SNAKE).convert("RGB")
    sticker = ImageOps.fit(src, (220, 220), method=Image.Resampling.LANCZOS)
    im.paste(sticker, (790, 1088))


def render_frame(t, duration, out):
    im, d = base_reel(t, duration)
    if t < 2.6:
        scene_hook(im, t)
    elif t < 5.2:
        scene_reaction(im, Image.open(PHOTO), t - 2.6)
    elif t < 8.4:
        scene_fact(im, t - 5.2)
    elif t < 12.7:
        scene_flow(im, t - 8.4)
    else:
        scene_end(im, t - 12.7)
    im.save(out, quality=94, subsampling=0)


def render_frames(out: Path, fps=15, duration=16.0):
    out.mkdir(parents=True, exist_ok=True)
    for i in range(math.ceil(fps * duration)):
        render_frame(i / fps, duration, out / f"frame-{i:05d}.jpg")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cards", type=Path)
    p.add_argument("--frames", type=Path)
    args = p.parse_args()
    if args.cards:
        render_cards(args.cards)
    if args.frames:
        render_frames(args.frames)


if __name__ == "__main__":
    main()
