from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[3]
CHAR_HUMAN = ROOT / "content/character/character-human.png"
CHAR_SNAKE = ROOT / "content/character/character-creature.png"
PHOTO = ROOT / "content/character/reel-human-reference/reference-03.png"

FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

INK = "#161616"
CREAM = "#F7F2E9"
PAPER = "#FFFDF8"
LIME = "#D7F36B"
LAV = "#BBA3FF"
BLUE = "#89D8F4"
CORAL = "#FF806A"
MUTED = "#7A756C"
LINE = "#D9D0C4"


def f(size: int, mono=False):
    return ImageFont.truetype(MONO if mono else FONT, size=size)


def txt(d, xy, s, size, fill=INK, anchor=None, mono=False, stroke=0):
    d.text(xy, s, font=f(size, mono), fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=fill)


def rounded(im, box, radius=28, fill=PAPER, outline=None, width=1):
    ImageDraw.Draw(im).rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def paste_fit(dst, src, box, radius=28):
    x, y, w, h = box
    src = ImageOps.fit(src.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
    dst.paste(src, (x, y), mask)


def header(im, d, index, total=5):
    txt(d, (72, 58), "JEV / NEXT ACTION", 22, fill=INK)
    txt(d, (1008, 58), f"{index:02d} / {total:02d}", 20, fill=MUTED, anchor="ra", mono=True)
    d.line((72, 108, 1008, 108), fill=LINE, width=2)


def badge(im, d, x, y, label, color):
    w = d.textbbox((0, 0), label, font=f(18))[2] + 28
    rounded(im, (x, y, x + w, y + 40), 20, fill=color)
    txt(d, (x + 14, y + 8), label, 18, fill=INK)


def card_shell(index, kicker):
    im = Image.new("RGB", (1080, 1350), CREAM)
    d = ImageDraw.Draw(im)
    header(im, d, index)
    txt(d, (72, 150), kicker.upper(), 18, fill=MUTED)
    return im, d


def render_cards(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    human = Image.open(CHAR_HUMAN)
    snake = Image.open(CHAR_SNAKE)

    im, d = card_shell(1, "THE HOOK")
    txt(d, (72, 240), "코딩 AI가", 78)
    txt(d, (72, 330), "실패했다.", 98, fill=CORAL)
    txt(d, (72, 462), "그다음은 누가 정하지?", 42)
    rounded(im, (72, 570, 1008, 860), 26, fill=INK)
    txt(d, (112, 612), "$ npm run build", 27, fill=BLUE, mono=True)
    txt(d, (112, 680), "✕  Module not found", 36, fill=CORAL, mono=True)
    txt(d, (112, 744), "next_action = ?", 31, fill=LIME, mono=True)
    paste_fit(im, snake, (660, 902, 348, 348), 28)
    badge(im, d, 72, 930, "예시 흐름", LIME)
    txt(d, (72, 1048), "실패를 고치는 AI와", 34)
    txt(d, (72, 1104), "다음 행동을 고르는 AI는 다르다", 34, fill=INK)
    txt(d, (72, 1244), "Jev 개념 카드 · 01", 18, fill=MUTED)
    im.save(out_dir / "card-01.png")

    im, d = card_shell(2, "FOUR CHOICES")
    txt(d, (72, 236), "실패 뒤에 남는", 58)
    txt(d, (72, 310), "네 가지 선택", 80, fill=INK)
    choices = [("01", "재시도", CORAL), ("02", "다른 AI", BLUE), ("03", "다른 툴", LAV), ("04", "사람 확인", LIME)]
    coords = [(72, 500), (552, 500), (72, 700), (552, 700)]
    for (n, name, color), (x, y) in zip(choices, coords):
        rounded(im, (x, y, x + 456, y + 148), 24, fill=PAPER, outline=LINE, width=2)
        rounded(im, (x + 24, y + 26, x + 86, y + 88), 31, fill=color)
        txt(d, (x + 55, y + 42), n, 17, fill=INK, anchor="mm", mono=True)
        txt(d, (x + 112, y + 47), name, 31)
        txt(d, (x + 416, y + 49), "→", 32, fill=color, anchor="mm")
    rounded(im, (72, 1006, 1008, 1158), 22, fill=INK)
    txt(d, (108, 1044), "매번 사람이 직접 고르지 않도록", 28, fill=PAPER)
    txt(d, (108, 1090), "판단 레이어를 둔다", 32, fill=LIME)
    txt(d, (72, 1244), "Jev 개념 카드 · 02", 18, fill=MUTED)
    im.save(out_dir / "card-02.png")

    im, d = card_shell(3, "WHAT JEV DOES")
    txt(d, (72, 238), "Jev는", 80)
    txt(d, (72, 338), "코딩하지 않는다", 68, fill=CORAL)
    txt(d, (72, 438), "다음 행동을 고른다", 45, fill=INK)
    rounded(im, (72, 580, 610, 1120), 30, fill=INK)
    txt(d, (112, 630), "context", 20, fill=BLUE, mono=True)
    txt(d, (112, 682), "build failed", 29, fill=PAPER, mono=True)
    txt(d, (112, 738), "+ available tools", 29, fill=PAPER, mono=True)
    d.line((112, 812, 570, 812), fill="#3D3D3D", width=2)
    txt(d, (112, 858), "judgment", 20, fill=LAV, mono=True)
    txt(d, (112, 910), "use_other_tool", 31, fill=LIME, mono=True)
    paste_fit(im, human, (658, 632, 350, 350), 28)
    badge(im, d, 658, 1024, "작업 AI 아님", LAV)
    txt(d, (72, 1244), "Jev 개념 카드 · 03", 18, fill=MUTED)
    im.save(out_dir / "card-03.png")

    im, d = card_shell(4, "THE LOOP")
    txt(d, (72, 240), "판단과 실행을", 62)
    txt(d, (72, 322), "분리하면 선명해진다", 58, fill=INK)
    nodes = [("상황 입력", BLUE), ("Jev 판단", LAV), ("프로그램 실행", LIME)]
    x0 = 72
    for i, (name, color) in enumerate(nodes):
        x = x0 + i * 312
        rounded(im, (x, 560, x + 270, 800), 26, fill=PAPER, outline=color, width=3)
        txt(d, (x + 28, 604), f"0{i+1}", 20, fill=color, mono=True)
        txt(d, (x + 28, 694), name, 30)
        if i < 2:
            txt(d, (x + 286, 680), "→", 42, fill=MUTED)
    rounded(im, (72, 900, 1008, 1110), 24, fill=INK)
    txt(d, (108, 946), "if judgment.next_action ==", 25, fill=BLUE, mono=True)
    txt(d, (108, 996), "'use_other_tool':", 29, fill=PAPER, mono=True)
    txt(d, (108, 1050), "    run_other_tool()", 29, fill=LIME, mono=True)
    txt(d, (72, 1244), "Jev 개념 카드 · 04", 18, fill=MUTED)
    im.save(out_dir / "card-04.png")

    im, d = card_shell(5, "SAVE THIS")
    txt(d, (72, 238), "일하는 AI", 70)
    txt(d, (72, 326), "vs", 34, fill=MUTED)
    txt(d, (72, 384), "일을 배분하는 AI", 63, fill=INK)
    rounded(im, (72, 570, 1008, 900), 26, fill=PAPER, outline=LINE, width=2)
    txt(d, (112, 620), "GPT · Claude · Codex", 31, fill=BLUE)
    txt(d, (112, 684), "write  /  code  /  execute", 26, mono=True)
    d.line((112, 758, 968, 758), fill=LINE, width=2)
    txt(d, (112, 800), "Jev", 35, fill=LAV)
    txt(d, (112, 852), "choose  /  route  /  stop", 26, mono=True)
    rounded(im, (72, 1000, 1008, 1134), 22, fill=LIME)
    txt(d, (108, 1038), "다음 오류 때 꺼내보려면 저장", 28, fill=INK)
    txt(d, (72, 1244), "TypeSafe · Jev · Early Access", 18, fill=MUTED)
    im.save(out_dir / "card-05.png")


def reel_base(t, duration):
    im = Image.new("RGB", (1080, 1920), CREAM)
    d = ImageDraw.Draw(im)
    txt(d, (64, 58), "JEV / NEXT ACTION", 22, fill=INK)
    txt(d, (1016, 58), "VIBE CODING", 18, fill=MUTED, anchor="ra")
    d.line((64, 108, 1016, 108), fill=LINE, width=2)
    d.line((64, 120, 64 + int(952 * min(t / duration, 1)), 120), fill=INK, width=5)
    return im, d


def reel_terminal(im, d):
    txt(d, (72, 280), "BUILD", 88, fill=INK, mono=True)
    txt(d, (72, 378), "FAILED", 120, fill=CORAL, mono=True)
    rounded(im, (72, 620, 1008, 1100), 30, fill=INK)
    txt(d, (112, 680), "$ npm run build", 30, fill=BLUE, mono=True)
    txt(d, (112, 760), "✕ Module not found", 43, fill=CORAL, mono=True)
    txt(d, (112, 834), "./src/next-action.ts", 28, fill=PAPER, mono=True)
    txt(d, (112, 950), "다음에 뭘 하지?", 60, fill=LIME)
    txt(d, (72, 1236), "실패 자체보다 어려운 건", 33, fill=INK)
    txt(d, (72, 1292), "그 다음 행동을 고르는 일", 33, fill=INK)


def reel_choices(im, d):
    txt(d, (72, 270), "실패 뒤 선택지는", 56, fill=INK)
    txt(d, (72, 350), "네 개", 100, fill=CORAL)
    choices = [("재시도", CORAL), ("다른 AI", BLUE), ("다른 툴", LAV), ("사람 확인", LIME)]
    y = 610
    for name, color in choices:
        rounded(im, (72, y, 1008, y + 150), 26, fill=PAPER, outline=LINE, width=2)
        rounded(im, (104, y + 38, 164, y + 98), 30, fill=color)
        txt(d, (198, y + 48), name, 34, fill=INK)
        txt(d, (944, y + 48), "→", 34, fill=color)
        y += 190


def reel_photo(im, d):
    src = Image.open(PHOTO).convert("RGB")
    crop = ImageOps.fit(src, (640, 820), method=Image.Resampling.LANCZOS, centering=(0.5, 0.42))
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, crop.width - 1, crop.height - 1), radius=34, fill=255)
    im.paste(crop, (360, 300), mask)
    rounded(im, (360, 300, 1000, 1120), 34, fill=None, outline=INK, width=4)
    txt(d, (72, 400), "이 순간,", 62, fill=INK)
    txt(d, (72, 480), "내가 매번 정해?", 56, fill=CORAL)
    rounded(im, (72, 1230, 1008, 1360), 22, fill=INK)
    txt(d, (108, 1268), "원본 사진 · 얼굴 변형 없음", 25, fill=PAPER)


def reel_jev(im, d):
    txt(d, (72, 270), "Jev", 130, fill=LAV)
    txt(d, (72, 430), "코딩하지 않는다.", 52, fill=INK)
    txt(d, (72, 506), "다음 행동을 고른다.", 52, fill=INK)
    rounded(im, (72, 720, 1008, 1000), 28, fill=INK)
    txt(d, (112, 776), "상황 입력", 30, fill=BLUE)
    txt(d, (425, 776), "→", 34, fill=PAPER)
    txt(d, (512, 776), "Jev 판단", 30, fill=LAV)
    txt(d, (816, 776), "→", 34, fill=PAPER)
    txt(d, (876, 776), "결과", 30, fill=LIME)
    rounded(im, (72, 1100, 1008, 1300), 24, fill=PAPER, outline=LINE, width=2)
    txt(d, (112, 1150), "next_action", 24, fill=MUTED, mono=True)
    txt(d, (112, 1200), "use_other_tool", 34, fill=INK, mono=True)
    txt(d, (72, 1430), "예시 흐름 · 실제 API 응답 아님", 22, fill=MUTED)


def reel_execute(im, d):
    txt(d, (72, 280), "판단은 Jev", 72, fill=INK)
    txt(d, (72, 382), "실행은 내 프로그램", 64, fill=CORAL)
    rounded(im, (72, 660, 1008, 1190), 28, fill=INK)
    txt(d, (112, 730), "if judgment.next_action ==", 29, fill=BLUE, mono=True)
    txt(d, (112, 800), "'use_other_tool':", 34, fill=PAPER, mono=True)
    txt(d, (112, 900), "    run_other_tool()", 37, fill=LIME, mono=True)
    txt(d, (112, 980), "    log_result()", 37, fill=LAV, mono=True)
    rounded(im, (72, 1320, 1008, 1450), 24, fill=LIME)
    txt(d, (112, 1360), "✓ next step dispatched", 28, fill=INK, mono=True)


def reel_compare(im, d):
    txt(d, (72, 270), "역할을 나누면", 60, fill=INK)
    txt(d, (72, 350), "AI가 덜 꼬인다", 74, fill=CORAL)
    rounded(im, (72, 620, 510, 1120), 28, fill=PAPER, outline=BLUE, width=3)
    txt(d, (112, 690), "GPT · Claude · Codex", 26, fill=BLUE)
    txt(d, (112, 818), "write", 42, mono=True)
    txt(d, (112, 892), "code", 42, mono=True)
    txt(d, (112, 966), "execute", 42, mono=True)
    rounded(im, (570, 620, 1008, 1120), 28, fill=PAPER, outline=LAV, width=3)
    txt(d, (610, 690), "Jev", 40, fill=LAV)
    txt(d, (610, 818), "choose", 42, mono=True)
    txt(d, (610, 892), "route", 42, mono=True)
    txt(d, (610, 966), "stop", 42, mono=True)
    txt(d, (72, 1320), "일하는 AI ≠ 다음 행동을 정하는 AI", 31, fill=INK)


def reel_end(im, d):
    txt(d, (72, 330), "Jev", 150, fill=INK)
    txt(d, (72, 520), "다음 행동을 고르는", 52, fill=INK)
    txt(d, (72, 594), "작은 판단 레이어", 52, fill=LAV)
    rounded(im, (72, 900, 1008, 1060), 24, fill=LIME)
    txt(d, (108, 950), "이 흐름 저장해두기", 32, fill=INK)
    txt(d, (72, 1250), "TypeSafe · Jev · Early Access", 24, fill=MUTED)


def render_frame(t: float, duration: float, out: Path):
    im, d = reel_base(t, duration)
    if t < 2.0:
        reel_terminal(im, d)
    elif t < 5.0:
        reel_choices(im, d)
    elif t < 7.5:
        reel_photo(im, d)
    elif t < 12.0:
        reel_jev(im, d)
    elif t < 16.0:
        reel_execute(im, d)
    elif t < 19.0:
        reel_compare(im, d)
    else:
        reel_end(im, d)
    im.save(out, quality=94, subsampling=0)


def render_reel_frames(out_dir: Path, fps=8, duration=22.0):
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(math.ceil(fps * duration)):
        render_frame(i / fps, duration, out_dir / f"frame-{i:05d}.jpg")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=Path)
    ap.add_argument("--frames", type=Path)
    args = ap.parse_args()
    if args.cards:
        render_cards(args.cards)
    if args.frames:
        render_reel_frames(args.frames)


if __name__ == "__main__":
    main()
