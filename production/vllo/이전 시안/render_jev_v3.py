from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[3]
CHAR_HUMAN = ROOT / "content/character/character-human.png"
CHAR_SNAKE = ROOT / "content/character/character-creature.png"
PHOTO = ROOT / "content/character/reel-human-reference/reference-03.png"

FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

BG = "#10131A"
PANEL = "#1B212D"
PAPER = "#F7F2E9"
INK = "#10131A"
WHITE = "#F7F8FB"
LIME = "#D8F66A"
LAV = "#B49AFF"
CYAN = "#7DDBF7"
CORAL = "#FF7667"
MUTED = "#8791A5"
GRID = "#2B3445"


def font(size, mono=False):
    return ImageFont.truetype(MONO if mono else FONT, size=size)


def txt(d, xy, s, size, fill=WHITE, anchor=None, mono=False, stroke=0):
    d.text(xy, s, font=font(size, mono), fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=fill)


def rounded(im, box, radius=24, fill=PANEL, outline=None, width=1):
    ImageDraw.Draw(im).rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def paste_fit(dst, src, box, radius=24):
    x, y, w, h = box
    crop = ImageOps.fit(src.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    dst.paste(crop, (x, y), mask)


def grid(im, step=72):
    d = ImageDraw.Draw(im)
    for x in range(0, im.width, step):
        d.line((x, 0, x, im.height), fill=GRID, width=1)
    for y in range(0, im.height, step):
        d.line((0, y, im.width, y), fill=GRID, width=1)


def topbar(im, d, index, total):
    txt(d, (72, 60), "JEV / NEXT ACTION", 20, fill=LIME)
    txt(d, (1008, 60), f"{index:02d} / {total:02d}", 18, fill=MUTED, anchor="ra", mono=True)
    d.line((72, 112, 1008, 112), fill=GRID, width=2)


def card(index, kicker):
    im = Image.new("RGB", (1080, 1350), BG)
    grid(im)
    d = ImageDraw.Draw(im)
    topbar(im, d, index, 4)
    txt(d, (72, 154), kicker.upper(), 18, fill=MUTED)
    return im, d


def render_cards(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    snake = Image.open(CHAR_SNAKE)
    human = Image.open(CHAR_HUMAN)

    im, d = card(1, "POV / BUILD FAILED")
    txt(d, (72, 240), "코딩 AI가", 76)
    txt(d, (72, 330), "또 실패했다", 100, fill=CORAL)
    txt(d, (72, 456), "근데 진짜 문제는", 38, fill=WHITE)
    txt(d, (72, 510), "그 다음 행동이다", 38, fill=LIME)
    rounded(im, (72, 660, 644, 1050), 28, fill="#0A0D12", outline=GRID, width=2)
    txt(d, (112, 720), "$ npm run build", 27, fill=CYAN, mono=True)
    txt(d, (112, 792), "✕ Module not found", 35, fill=CORAL, mono=True)
    txt(d, (112, 864), "next_action = ?", 31, fill=LIME, mono=True)
    paste_fit(im, snake, (704, 702, 304, 304), 26)
    txt(d, (72, 1164), "실패를 고치는 AI", 33)
    txt(d, (72, 1212), "다음 행동을 고르는 AI", 33, fill=LIME)
    txt(d, (72, 1270), "예시 화면 · 실제 Jev 응답 아님", 17, fill=MUTED)
    im.save(out / "card-01.png")

    im, d = card(2, "THE NEXT MOVE")
    txt(d, (72, 238), "다음에 뭘 해?", 86, fill=LIME)
    txt(d, (72, 350), "선택지는 네 개", 44)
    options = [("01", "재시도", CORAL), ("02", "다른 AI", CYAN), ("03", "다른 툴", LAV), ("04", "사람 확인", LIME)]
    y = 530
    for n, label, color in options:
        rounded(im, (72, y, 1008, y + 130), 22, fill=PANEL, outline=GRID, width=2)
        rounded(im, (106, y + 30, 168, y + 92), 31, fill=color)
        txt(d, (137, y + 45), n, 17, fill=INK, anchor="mm", mono=True)
        txt(d, (212, y + 38), label, 34)
        txt(d, (948, y + 40), "→", 36, fill=color)
        y += 160
    txt(d, (72, 1232), "이걸 매번 사람이 고르면 자동화가 멈춘다", 25, fill=MUTED)
    im.save(out / "card-02.png")

    im, d = card(3, "THE JUDGMENT LAYER")
    txt(d, (72, 236), "Jev는", 72)
    txt(d, (72, 322), "코딩하지 않는다", 66, fill=CORAL)
    txt(d, (72, 420), "다음 행동을 고른다", 42, fill=LIME)
    rounded(im, (72, 570, 1008, 1000), 28, fill=PANEL, outline=GRID, width=2)
    txt(d, (112, 624), "WORKING AI", 18, fill=CYAN, mono=True)
    txt(d, (112, 678), "GPT · Claude · Codex", 30)
    txt(d, (112, 734), "write / code / execute", 25, fill=MUTED, mono=True)
    d.line((112, 810, 968, 810), fill=GRID, width=2)
    txt(d, (112, 858), "JUDGMENT AI", 18, fill=LAV, mono=True)
    txt(d, (112, 910), "Jev → use_other_tool", 30, fill=LIME, mono=True)
    paste_fit(im, human, (694, 1032, 250, 250), 22)
    txt(d, (72, 1114), "상황을 읽고", 31)
    txt(d, (72, 1160), "선택지를 골라 프로그램에 돌려준다", 31, fill=LIME)
    txt(d, (72, 1270), "판단과 실행을 분리하는 레이어", 18, fill=MUTED)
    im.save(out / "card-03.png")

    im, d = card(4, "SAVE THIS")
    txt(d, (72, 236), "일하는 AI", 66)
    txt(d, (72, 316), "≠", 42, fill=MUTED)
    txt(d, (72, 378), "다음 행동을 정하는 AI", 58, fill=LIME)
    rounded(im, (72, 578, 1008, 900), 28, fill=PAPER)
    txt(d, (112, 634), "GPT · Claude · Codex", 30, fill=INK)
    txt(d, (112, 696), "write / code / execute", 25, fill="#3C536A", mono=True)
    d.line((112, 766, 968, 766), fill="#D8D2C8", width=2)
    txt(d, (112, 814), "Jev", 34, fill="#7A57C8")
    txt(d, (112, 866), "choose / route / stop", 25, fill=INK, mono=True)
    rounded(im, (72, 1012, 1008, 1140), 22, fill=LIME)
    txt(d, (112, 1054), "다음 오류 때 꺼내보려면 저장", 28, fill=INK)
    txt(d, (72, 1256), "TypeSafe · Jev · Early Access", 18, fill=MUTED)
    im.save(out / "card-04.png")


def reel_base(t, duration):
    im = Image.new("RGB", (1080, 1920), BG)
    d = ImageDraw.Draw(im)
    grid(im, 72)
    txt(d, (64, 58), "JEV / NEXT ACTION", 20, fill=LIME)
    txt(d, (1016, 58), "VIBE CODING", 17, fill=MUTED, anchor="ra")
    d.line((64, 108, 1016, 108), fill=GRID, width=2)
    d.line((64, 120, 64 + int(952 * min(t / duration, 1)), 120), fill=LIME, width=5)
    return im, d


def scene_hook(im, d):
    txt(d, (72, 264), "POV:", 64, fill=LIME, mono=True)
    txt(d, (72, 358), "코딩 AI가", 78)
    txt(d, (72, 452), "또 실패했을 때", 78, fill=CORAL)
    rounded(im, (72, 660, 1008, 1080), 28, fill="#0A0D12", outline=GRID, width=2)
    txt(d, (112, 720), "$ npm run build", 30, fill=CYAN, mono=True)
    txt(d, (112, 804), "✕ Module not found", 42, fill=CORAL, mono=True)
    txt(d, (112, 910), "다음에 뭘 하지?", 60, fill=LIME)
    txt(d, (72, 1220), "실패보다 어려운 건", 36)
    txt(d, (72, 1280), "그 다음 행동을 고르는 일", 36, fill=WHITE)


def scene_options(im, d, active=0):
    txt(d, (72, 280), "그 순간 선택지는", 56)
    txt(d, (72, 360), "딱 네 개", 96, fill=LIME)
    labels = [("재시도", CORAL), ("다른 AI", CYAN), ("다른 툴", LAV), ("사람 확인", LIME)]
    y = 630
    for i, (label, color) in enumerate(labels):
        fill = "#26333A" if i == active else PANEL
        rounded(im, (72, y, 1008, y + 140), 24, fill=fill, outline=color if i == active else GRID, width=3 if i == active else 2)
        txt(d, (112, y + 45), f"0{i+1}", 18, fill=color, mono=True)
        txt(d, (210, y + 42), label, 36)
        txt(d, (946, y + 44), "→", 36, fill=color)
        y += 170


def scene_photo(im, d):
    src = Image.open(PHOTO).convert("RGB")
    paste_fit(im, src, (420, 290, 580, 760), 30)
    rounded(im, (420, 290, 1000, 1050), 30, fill=None, outline=LIME, width=4)
    txt(d, (72, 420), "내가 또", 64)
    txt(d, (72, 500), "결정해?", 72, fill=CORAL)
    rounded(im, (72, 1230, 1008, 1360), 22, fill=PANEL, outline=GRID, width=2)
    txt(d, (110, 1272), "원본 사진 · 얼굴 변형 없음", 24, fill=WHITE)


def scene_judgment(im, d, pulse=0):
    txt(d, (72, 270), "Jev", 126, fill=LAV)
    txt(d, (72, 424), "코딩하지 않는다", 52)
    txt(d, (72, 500), "다음 행동을 고른다", 52, fill=LIME)
    rounded(im, (72, 720, 1008, 1010), 28, fill=PANEL, outline=GRID, width=2)
    txt(d, (112, 780), "context", 21, fill=CYAN, mono=True)
    txt(d, (112, 830), "build failed + tools", 29, fill=WHITE, mono=True)
    d.line((112, 888, 968, 888), fill=GRID, width=2)
    txt(d, (112, 930), "judgment", 21, fill=LAV, mono=True)
    txt(d, (112, 980), "use_other_tool", 34, fill=LIME, mono=True)
    rounded(im, (72, 1140, 1008, 1266), 22, fill="#22342A" if pulse else PANEL, outline=LIME, width=2)
    txt(d, (112, 1180), "예시 판단 · 실제 API 응답 아님", 23, fill=WHITE)


def scene_execute(im, d):
    txt(d, (72, 286), "판단은 Jev", 70)
    txt(d, (72, 380), "실행은 내 코드", 70, fill=CORAL)
    rounded(im, (72, 650, 1008, 1190), 28, fill="#0A0D12", outline=GRID, width=2)
    txt(d, (112, 724), "if judgment.next_action ==", 29, fill=CYAN, mono=True)
    txt(d, (112, 796), "'use_other_tool':", 34, fill=WHITE, mono=True)
    txt(d, (112, 904), "    run_other_tool()", 39, fill=LIME, mono=True)
    txt(d, (112, 980), "    log_result()", 39, fill=LAV, mono=True)
    rounded(im, (72, 1310, 1008, 1440), 22, fill=LIME)
    txt(d, (112, 1352), "✓ next step dispatched", 28, fill=INK, mono=True)


def scene_compare(im, d):
    txt(d, (72, 274), "일하는 AI", 66)
    txt(d, (72, 354), "vs", 34, fill=MUTED)
    txt(d, (72, 418), "판단하는 AI", 66, fill=LIME)
    rounded(im, (72, 680, 510, 1160), 26, fill=PANEL, outline=CYAN, width=3)
    txt(d, (112, 742), "GPT / Claude / Codex", 24, fill=CYAN)
    txt(d, (112, 860), "write", 40, mono=True)
    txt(d, (112, 932), "code", 40, mono=True)
    txt(d, (112, 1004), "execute", 40, mono=True)
    rounded(im, (570, 680, 1008, 1160), 26, fill=PANEL, outline=LAV, width=3)
    txt(d, (610, 742), "Jev", 38, fill=LAV)
    txt(d, (610, 860), "choose", 40, mono=True)
    txt(d, (610, 932), "route", 40, mono=True)
    txt(d, (610, 1004), "stop", 40, mono=True)


def scene_end(im, d):
    txt(d, (72, 330), "Jev", 148, fill=LIME)
    txt(d, (72, 520), "다음 행동을 고르는", 53)
    txt(d, (72, 600), "작은 판단 레이어", 53, fill=LAV)
    rounded(im, (72, 930, 1008, 1070), 22, fill=LIME)
    txt(d, (112, 972), "이 흐름 저장해두기", 31, fill=INK)
    txt(d, (72, 1270), "TypeSafe · Jev · Early Access", 22, fill=MUTED)


def render_frame(t, duration, out):
    im, d = reel_base(t, duration)
    if t < 2.0:
        scene_hook(im, d)
    elif t < 4.2:
        scene_options(im, d, active=int((t - 2.0) * 2.0) % 4)
    elif t < 6.0:
        scene_photo(im, d)
    elif t < 10.0:
        scene_judgment(im, d, pulse=int(t * 4) % 2)
    elif t < 13.5:
        scene_execute(im, d)
    elif t < 16.0:
        scene_compare(im, d)
    else:
        scene_end(im, d)
    im.save(out, quality=94, subsampling=0)


def render_frames(out: Path, fps=10, duration=18.0):
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
