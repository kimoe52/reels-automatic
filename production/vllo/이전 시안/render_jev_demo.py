from __future__ import annotations

import argparse
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[3]
CREATURE = ROOT / "content/character/character-creature.png"
HUMAN = ROOT / "content/character/reel-human-reference/reference-03.png"
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

BG = "#0b0f1a"
PANEL = "#121a29"
PANEL_2 = "#172236"
TEXT = "#f6f7fb"
MUTED = "#9da8bd"
GREEN = "#c9ff6a"
LAV = "#b99aff"
RED = "#ff6b77"
BLUE = "#77c7ff"


def font(size: int, bold: bool = False, mono: bool = False):
    path = MONO if mono else FONT
    # AppleSDGothicNeo's first face is the regular family; use the same face
    # for predictable Korean shaping and emulate bold with a small stroke.
    return ImageFont.truetype(path, size=size)


def text(draw: ImageDraw.ImageDraw, xy, s: str, size: int, fill=TEXT, anchor=None, mono=False, stroke=0):
    draw.text(xy, s, font=font(size, mono=mono), fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=fill)


def fit_text(draw, s: str, max_width: int, size: int, min_size: int = 18, mono=False):
    current = size
    while current > min_size and draw.textbbox((0, 0), s, font=font(current, mono=mono))[2] > max_width:
        current -= 2
    return font(current, mono=mono)


def rounded(im: Image.Image, xy, radius, fill, outline=None, width=1):
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def paste_rounded(dst: Image.Image, src: Image.Image, box, radius=28, alpha=255):
    x, y, w, h = box
    src = ImageOps.contain(src.convert("RGB"), (w, h))
    layer = Image.new("RGB", (w, h), "#000000")
    sx = (w - src.width) // 2
    sy = (h - src.height) // 2
    layer.paste(src, (sx, sy))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=radius, fill=alpha)
    dst.paste(layer, (x, y), mask)


def glow(im: Image.Image, box, color, blur=24, alpha=90):
    x1, y1, x2, y2 = box
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((x1, y1, x2, y2), radius=28, fill=tuple(int(color[i : i + 2], 16) for i in (1, 3, 5)) + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    im.paste(layer, (0, 0), layer)


def grid(im: Image.Image, step=54, alpha=28):
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x in range(0, im.width, step):
        d.line((x, 0, x, im.height), fill=(126, 148, 186, alpha), width=1)
    for y in range(0, im.height, step):
        d.line((0, y, im.width, y), fill=(126, 148, 186, alpha), width=1)
    im.paste(layer, (0, 0), layer)


def label(draw, x, y, s, color=GREEN, size=22):
    f = font(size)
    w = draw.textbbox((0, 0), s, font=f)[2] + 28
    rounded(draw._image, (x, y, x + w, y + size + 18), 14, color)
    text(draw, (x + 14, y + 7), s, size, BG)
    return w


def wrap_lines(draw, s: str, max_width: int, f):
    lines, line = [], ""
    for ch in s:
        candidate = line + ch
        if line and draw.textbbox((0, 0), candidate, font=f)[2] > max_width:
            lines.append(line)
            line = ch
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def card_base(index: int, kicker: str):
    im = Image.new("RGB", (1080, 1350), BG)
    grid(im, 72, 20)
    d = ImageDraw.Draw(im)
    text(d, (84, 64), "JEV / NEXT ACTION", 22, GREEN, stroke=0)
    text(d, (996, 64), f"0{index} / 05", 20, MUTED, anchor="ra")
    d.line((84, 116, 996, 116), fill="#243149", width=2)
    text(d, (84, 154), kicker.upper(), 18, LAV)
    return im, d


def render_cards(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    creature = Image.open(CREATURE).convert("RGB")

    # 1. Hook: show the failure before explaining anything.
    im, d = card_base(1, "THE PROBLEM")
    text(d, (84, 222), "코딩 AI가", 72, TEXT)
    text(d, (84, 310), "또 실패했다", 96, GREEN, stroke=1)
    rounded(im, (84, 492, 996, 860), 28, PANEL, outline="#2d3b55", width=2)
    text(d, (126, 536), "terminal / build.log", 20, MUTED, mono=True)
    text(d, (126, 598), "$ npm run build", 26, BLUE, mono=True)
    text(d, (126, 660), "✕  Module not found", 31, RED, mono=True)
    text(d, (126, 716), "   ./src/next-action.ts", 24, TEXT, mono=True)
    text(d, (126, 784), "exit code 1", 22, MUTED, mono=True)
    glow(im, (770, 910, 982, 1122), RED, 24, 80)
    paste_rounded(im, creature, (720, 865, 300, 300), 34)
    text(d, (84, 1016), "문제는 실패 자체보다", 35, TEXT)
    text(d, (84, 1068), "그 다음 행동을 고르는 일", 35, LAV)
    text(d, (84, 1195), "예시 화면 · 실제 Jev 응답 아님", 18, MUTED)
    im.save(out_dir / "card-01.png")

    # 2. Four actions as a visual decision tray.
    im, d = card_base(2, "FOUR CHOICES")
    text(d, (84, 214), "재시도?", 84, TEXT)
    text(d, (84, 312), "아니면 다른 길?", 68, GREEN)
    choices = [("01", "재시도", RED), ("02", "다른 AI", BLUE), ("03", "다른 툴", LAV), ("04", "사람 확인", GREEN)]
    y = 520
    for n, name, c in choices:
        rounded(im, (84, y, 996, y + 125), 24, PANEL, outline="#2d3b55", width=2)
        d.ellipse((116, y + 34, 166, y + 84), fill=c)
        text(d, (141, y + 59), n, 17, BG, anchor="mm", mono=True)
        text(d, (204, y + 34), name, 34, TEXT)
        text(d, (945, y + 42), "→", 34, c, anchor="ra")
        y += 150
    text(d, (84, 1174), "이 선택을 매번 사람이 직접 정해야 할까?", 26, MUTED)
    im.save(out_dir / "card-02.png")

    # 3. Jev's role: typed judgment, not a second coder.
    im, d = card_base(3, "WHAT JEV DOES")
    text(d, (84, 216), "Jev는", 78, TEXT)
    text(d, (84, 306), "코딩하지 않는다", 74, GREEN)
    text(d, (84, 412), "다음 행동을 고른다", 52, LAV)
    rounded(im, (84, 568, 996, 872), 28, PANEL, outline="#2d3b55", width=2)
    text(d, (130, 616), "context", 20, MUTED, mono=True)
    text(d, (130, 658), "build failed + available tools", 25, TEXT, mono=True)
    d.line((130, 728, 930, 728), fill="#2d3b55", width=2)
    text(d, (130, 766), "judgment", 20, MUTED, mono=True)
    text(d, (130, 806), "next_action: use_other_tool", 25, GREEN, mono=True)
    glow(im, (650, 956, 978, 1250), LAV, 28, 90)
    paste_rounded(im, creature, (662, 942, 300, 300), 30)
    text(d, (84, 1014), "짧은 상황 설명을 받아", 33, TEXT)
    text(d, (84, 1065), "선택지를 점수화·분류하고", 33, TEXT)
    text(d, (84, 1116), "결과를 프로그램에 돌려준다", 33, GREEN)
    text(d, (84, 1220), "확률은 실제 응답이 있을 때만 표시", 18, MUTED)
    im.save(out_dir / "card-03.png")

    # 4. The actual loop.
    im, d = card_base(4, "THE LOOP")
    text(d, (84, 216), "판단은 Jev", 66, GREEN)
    text(d, (84, 300), "실행은 내 프로그램", 58, TEXT)
    nodes = [("01", "상황 입력", BLUE), ("02", "Jev 판단", LAV), ("03", "프로그램 실행", GREEN)]
    x = 84
    for i, (n, name, c) in enumerate(nodes):
        rounded(im, (x, 548, x + 260, 790), 26, PANEL, outline=c, width=3)
        text(d, (x + 26, 584), n, 18, c, mono=True)
        text(d, (x + 26, 668), name, 32, TEXT)
        if i < 2:
            text(d, (x + 282, 660), "→", 40, MUTED)
        x += 304
    rounded(im, (84, 900, 996, 1115), 26, "#16251d", outline="#37583c", width=2)
    text(d, (124, 944), "내 앱", 20, MUTED)
    text(d, (124, 990), "if judgment.next_action == 'retry':", 23, TEXT, mono=True)
    text(d, (124, 1035), "    run_retry()", 23, GREEN, mono=True)
    text(d, (84, 1192), "AI를 하나 더 붙이는 게 아니라", 28, MUTED)
    text(d, (84, 1234), "오케스트레이션 레이어를 붙이는 것", 28, LAV)
    im.save(out_dir / "card-04.png")

    # 5. Role split and clear source label.
    im, d = card_base(5, "ONE-LINE SUMMARY")
    text(d, (84, 216), "일하는 AI", 78, TEXT)
    text(d, (84, 310), "vs", 38, MUTED)
    text(d, (84, 372), "일을 배분하는 AI", 66, GREEN)
    rounded(im, (84, 560, 996, 902), 28, PANEL, outline="#2d3b55", width=2)
    text(d, (126, 612), "GPT / Claude / Codex", 34, BLUE)
    text(d, (126, 672), "write · code · execute", 26, TEXT, mono=True)
    d.line((126, 750, 954, 750), fill="#2d3b55", width=2)
    text(d, (126, 790), "Jev", 34, LAV)
    text(d, (126, 850), "choose · route · stop", 26, TEXT, mono=True)
    text(d, (84, 1012), "TypeSafe · Jev", 38, GREEN)
    text(d, (84, 1072), "이 영상은 개념을 보여주는 예시 흐름입니다.", 24, TEXT)
    text(d, (84, 1132), "실제 판단 결과·가격·성공률을 꾸며내지 않았습니다.", 20, MUTED)
    text(d, (84, 1230), "source: typesafe.ai · Early Access", 18, MUTED)
    im.save(out_dir / "card-05.png")


def draw_header(d, t):
    text(d, (64, 54), "JEV / NEXT ACTION", 24, GREEN)
    text(d, (1016, 54), "VIBE CODING", 18, MUTED, anchor="ra")
    d.line((64, 104, 1016, 104), fill="#26344c", width=2)
    # progress line
    d.line((64, 112, 64 + int(952 * min(t / 28.4, 1.0)), 112), fill=GREEN, width=4)


def terminal_panel(im, d, t):
    rounded(im, (64, 220, 1016, 770), 34, PANEL, outline="#2d3b55", width=2)
    # terminal dots
    for i, c in enumerate((RED, "#ffcc66", GREEN)):
        d.ellipse((98 + i * 30, 255, 114 + i * 30, 271), fill=c)
    text(d, (160, 248), "terminal / build.log", 19, MUTED, mono=True)
    text(d, (110, 350), "$ npm run build", 28, BLUE, mono=True)
    text(d, (110, 430), "✕  Module not found", 42, RED, mono=True)
    text(d, (110, 495), "   ./src/next-action.ts", 27, TEXT, mono=True)
    text(d, (110, 590), "exit code 1", 23, MUTED, mono=True)
    text(d, (110, 676), "다음엔 뭘 하지?", 62, TEXT)
    # red pulse around failure
    if t > 1.0:
        a = int(70 + 35 * (0.5 + 0.5 * math.sin(t * 8)))
        glow(im, (74, 404, 1006, 554), RED, 28, a)


def choices_panel(im, d, t):
    rounded(im, (64, 240, 1016, 1100), 34, PANEL, outline="#2d3b55", width=2)
    text(d, (106, 286), "다음 행동 후보", 32, TEXT)
    text(d, (106, 338), "이 선택부터 매번 고민하게 된다", 23, MUTED)
    opts = [("RETRY", "재시도", RED), ("OTHER AI", "다른 AI", BLUE), ("OTHER TOOL", "다른 툴", LAV), ("HUMAN", "사람 확인", GREEN)]
    y = 470
    active = int((t - 3.0) * 2.0) % 4
    for i, (code, name, c) in enumerate(opts):
        is_active = i == active and t < 6.5
        fill = "#1f2c40" if not is_active else "#273e2a"
        outline = c if is_active else "#33435c"
        rounded(im, (106, y, 974, y + 122), 24, fill, outline=outline, width=3 if is_active else 2)
        text(d, (138, y + 28), code, 18, c, mono=True)
        text(d, (138, y + 62), name, 30, TEXT)
        text(d, (928, y + 49), "→", 32, c, anchor="ra")
        y += 146


def human_reaction(im, d, t):
    # The exact user photo is used as a short, unmodified reaction insert.
    # Only a crop/scale is applied; no face generation or retouching.
    w = 390
    h = 620
    src = Image.open(HUMAN).convert("RGB")
    # Keep a stable crop around the face and shoulders.
    crop = ImageOps.fit(src, (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    layer = Image.new("RGB", (w, h), BG)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=32, fill=255)
    im.paste(crop, (620, 300), mask)
    rounded(im, (620, 300, 1010, 920), 32, None, outline=GREEN, width=4)
    text(d, (86, 342), "이 선택을", 60, TEXT)
    text(d, (86, 420), "누가 정하지?", 60, GREEN)
    text(d, (86, 566), "작업을 하는 AI와", 28, MUTED)
    text(d, (86, 614), "다음 행동을 정하는 AI는", 28, MUTED)
    text(d, (86, 662), "역할이 다르다", 28, LAV)
    rounded(im, (86, 1002, 1010, 1118), 22, PANEL, outline="#2d3b55", width=2)
    text(d, (116, 1038), "원본 사진 · 릴스 리액션 컷", 21, MUTED)


def jev_panel(im, d, t):
    rounded(im, (64, 230, 1016, 1128), 34, PANEL, outline="#2d3b55", width=2)
    text(d, (106, 278), "Jev", 70, LAV)
    text(d, (106, 370), "코딩하지 않는다.", 42, TEXT)
    text(d, (106, 430), "다음 행동을 고른다.", 42, GREEN)
    # flow chips
    rounded(im, (106, 570, 936, 694), 24, "#192235", outline=BLUE, width=2)
    text(d, (140, 608), "상황 입력", 28, BLUE)
    text(d, (486, 608), "→", 30, MUTED)
    text(d, (558, 608), "Jev 판단", 28, LAV)
    text(d, (820, 608), "→", 30, MUTED)
    text(d, (862, 608), "결과", 28, GREEN)
    rounded(im, (106, 760, 936, 1008), 24, "#16251d", outline="#37583c", width=2)
    text(d, (140, 808), "next_action", 22, MUTED, mono=True)
    text(d, (140, 860), "use_other_tool", 33, GREEN, mono=True)
    text(d, (140, 932), "예시 흐름 · 실제 API 응답 아님", 20, MUTED)
    paste_rounded(im, Image.open(CREATURE), (752, 1120, 210, 210), 28)


def execute_panel(im, d, t):
    rounded(im, (64, 230, 1016, 1140), 34, PANEL, outline="#2d3b55", width=2)
    text(d, (106, 278), "프로그램이 이어받는다", 48, TEXT)
    text(d, (106, 342), "판단은 Jev · 실행은 내 코드", 28, GREEN)
    rounded(im, (106, 470, 974, 910), 26, "#101821", outline="#31425f", width=2)
    code = [
        ("if judgment.next_action", BLUE),
        ("    == 'use_other_tool':", BLUE),
        ("    run_other_tool()", GREEN),
        ("    log_result()", LAV),
    ]
    y = 532
    for line, c in code:
        text(d, (146, y), line, 31, c, mono=True)
        y += 76
    rounded(im, (106, 984, 974, 1096), 22, "#172c22", outline=GREEN, width=2)
    text(d, (140, 1018), "✓ next step dispatched", 24, GREEN, mono=True)


def compare_panel(im, d, t):
    rounded(im, (64, 226, 1016, 1240), 34, PANEL, outline="#2d3b55", width=2)
    text(d, (106, 276), "역할을 나누면 선명해진다", 38, TEXT)
    rounded(im, (106, 410, 510, 842), 26, "#132238", outline=BLUE, width=2)
    text(d, (138, 456), "GPT / Claude / Codex", 25, BLUE)
    text(d, (138, 554), "write", 38, TEXT, mono=True)
    text(d, (138, 620), "code", 38, TEXT, mono=True)
    text(d, (138, 686), "execute", 38, TEXT, mono=True)
    rounded(im, (570, 410, 974, 842), 26, "#211b35", outline=LAV, width=2)
    text(d, (602, 456), "Jev", 34, LAV)
    text(d, (602, 554), "choose", 38, TEXT, mono=True)
    text(d, (602, 620), "route", 38, TEXT, mono=True)
    text(d, (602, 686), "stop", 38, TEXT, mono=True)
    text(d, (106, 954), "일하는 AI", 62, TEXT)
    text(d, (106, 1036), "일을 배분하는 AI", 62, GREEN)
    text(d, (106, 1150), "TypeSafe · Jev · Early Access", 22, MUTED)


def end_panel(im, d, t):
    text(d, (84, 320), "Jev", 130, GREEN)
    text(d, (84, 486), "다음 행동을 고르는", 54, TEXT)
    text(d, (84, 560), "작은 판단 레이어", 54, LAV)
    rounded(im, (84, 760, 996, 958), 30, PANEL, outline="#2d3b55", width=2)
    text(d, (126, 812), "GPT / Claude / Codex", 29, BLUE)
    text(d, (126, 870), "= 실제 작업", 29, TEXT)
    text(d, (600, 812), "Jev", 29, LAV)
    text(d, (600, 870), "= 다음 행동", 29, GREEN)
    text(d, (84, 1100), "concept reel · example flow", 23, MUTED, mono=True)
    text(d, (84, 1162), "source: typesafe.ai", 21, MUTED)


def render_frame(t: float, out: Path):
    im = Image.new("RGB", (1080, 1920), BG)
    grid(im, 72, 17)
    d = ImageDraw.Draw(im)
    draw_header(d, t)
    if t < 3.0:
        terminal_panel(im, d, t)
    elif t < 7.0:
        choices_panel(im, d, t)
    elif t < 12.0:
        human_reaction(im, d, t)
    elif t < 18.0:
        jev_panel(im, d, t)
    elif t < 24.0:
        execute_panel(im, d, t)
    elif t < 27.0:
        compare_panel(im, d, t)
    else:
        end_panel(im, d, t)
    im.save(out, quality=94, subsampling=0)


def render_reel_frames(out_dir: Path, fps=6, duration=28.4):
    out_dir.mkdir(parents=True, exist_ok=True)
    total = math.ceil(duration * fps)
    for i in range(total):
        render_frame(i / fps, out_dir / f"frame-{i:05d}.jpg")


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
