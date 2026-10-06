from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from render_jev_v4 import CHAR_SNAKE, PHOTO, fnt, txt

ROOT = Path(__file__).resolve().parents[3]
PAPER_TEXTURE = ROOT / "media/textures/editorial-paper-v1.png"
OUT = ROOT / "automation/meta-threads/queue/2026-09-23/jev-demo-v6/assets"

W, CARD_H = 1080, 1350
RW, RH = 1080, 1920
INK = "#191716"
SOFT = "#665F5A"
PAPER = "#F6F2EB"
RED = "#E85842"
YELLOW = "#E9D94A"
LAV = "#B88BEA"
GREEN = "#78A856"
BLUE = "#4E93B4"
WHITE = "#FFFEFB"
LINE = "#CFC7BC"
CODE = "#18161B"
MUTED = "#958C83"


def font(size: int, heavy: bool = False, mono: bool = False):
    path = "/System/Library/Fonts/Menlo.ttc" if mono else "/System/Library/Fonts/AppleSDGothicNeo.ttc"
    return ImageFont.truetype(path, size=size, index=(6 if heavy and not mono else 0))


def text(d: ImageDraw.ImageDraw, xy, s: str, size: int, color=INK, *, heavy=False, mono=False, anchor=None, spacing=6, stroke=0):
    d.multiline_text(xy, s, font=font(size, heavy, mono), fill=color, anchor=anchor, spacing=spacing, stroke_width=stroke, stroke_fill=color)


def paper(size, tint=PAPER):
    tex = Image.open(PAPER_TEXTURE).convert("RGB")
    tex = ImageOps.fit(tex, size, method=Image.Resampling.LANCZOS)
    wash = Image.new("RGB", size, tint)
    return Image.blend(tex, wash, 0.47)


def label(d, x, y, s, color=SOFT, size=18):
    text(d, (x, y), s.upper(), size, color, mono=True)


def small(d, x, y, s, color=SOFT, size=18):
    text(d, (x, y), s, size, color)


def marker(d, points, color=YELLOW, width=10):
    d.line(points, fill=color, width=width, joint="curve")
    x, y = points[-1]
    d.line((x-23, y-22, x, y, x+22, y-19), fill=color, width=width)


def rule(d, y, color=LINE, x0=64, x1=1016, width=2):
    d.line((x0, y, x1, y), fill=color, width=width)


def frame_crop(src: Image.Image, size):
    return ImageOps.fit(src.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def paper_header(im, index, slug="JEV / NEXT ACTION"):
    d = ImageDraw.Draw(im)
    label(d, 64, 44, slug, SOFT, 17)
    text(d, (1016, 44), f"{index:02d} / 05", 17, SOFT, mono=True, anchor="ra")
    rule(d, 88)
    return d


def slide_1(out: Path):
    im = paper((W, CARD_H))
    d = paper_header(im, 1, "BUILD LOG / OPEN QUESTION")
    # Cropped terminal-like line is a labeled scenario, not a claimed product screenshot.
    small(d, 64, 146, "예시 상황 · 빌드가 멈춤", RED, 18)
    d.rectangle((64, 190, 1016, 475), fill=CODE)
    d.rectangle((64, 190, 76, 475), fill=RED)
    text(d, (112, 238), "$ npm run build", 31, "#F6F2EB", mono=True)
    text(d, (112, 304), "× Module not found", 36, RED, mono=True)
    text(d, (112, 382), "exit code 1", 24, "#B7B1AA", mono=True)
    text(d, (64, 560), "다시 시켜?", 75, INK, heavy=True)
    text(d, (64, 660), "다른 AI를 불러?", 73, INK, heavy=True)
    text(d, (64, 760), "아니면 사람 확인?", 73, RED, heavy=True)
    marker(d, [(680, 855), (798, 825), (902, 839)], YELLOW, 9)
    # A single oversized question acts as the visual hook.
    text(d, (930, 560), "?", 256, RED, heavy=True, anchor="mm", stroke=2)
    rule(d, 1000, INK, width=3)
    small(d, 64, 1048, "이 네 번째 AI는 직접 일하지 않는다", INK, 17)
    text(d, (64, 1104), "다음 행동을\n판단하는 AI", 64, INK, heavy=True, spacing=0)
    text(d, (64, 1280), "Jev를 20초 만에 이해하기", 22, SOFT)
    im.save(out / "card-01.png")


def slide_2(out: Path):
    im = paper((W, CARD_H), "#F3EEE7")
    d = paper_header(im, 2, "WORK ≠ JUDGMENT")
    text(d, (64, 144), "일하는 쪽", 56, INK, heavy=True)
    label(d, 64, 222, "GPT · Claude · Codex", BLUE, 19)
    text(d, (64, 286), "글을 쓰고\n코드를 만든다", 60, INK, heavy=True, spacing=0)
    text(d, (850, 380), "01", 88, BLUE, mono=True, anchor="mm")
    rule(d, 530, INK, width=3)
    # Hand-drawn divider intentionally breaks the rigid card grid.
    d.line((72, 530, 1007, 530), fill=YELLOW, width=6)
    text(d, (64, 604), "판단하는 쪽", 56, INK, heavy=True)
    label(d, 64, 682, "Jev / System One", LAV, 19)
    text(d, (64, 748), "정해둔 질문과\n답 후보를 평가한다", 55, INK, heavy=True, spacing=0)
    # Exact capability terms from the official model page, not invented output values.
    chips = [("choices", RED, 170), ("scores", BLUE, 165), ("boolean probabilities", GREEN, 445)]
    x = 64
    for word, color, width in chips:
        d.rounded_rectangle((x, 1005, x+width, 1066), radius=30, fill=WHITE, outline=color, width=3)
        text(d, (x+width/2, 1035), word, 19, INK, mono=True, anchor="mm")
        x += width + 18
    text(d, (64, 1147), "Jev가 직접 코드를 고치거나 툴을 누르는 건 아님.", 26, SOFT)
    text(d, (64, 1200), "실행은 연결한 프로그램이 맡는다.", 31, INK, heavy=True)
    small(d, 64, 1290, "Vercel AI Gateway 공식 모델 설명", MUTED, 15)
    im.save(out / "card-02.png")


def slide_3(out: Path):
    im = paper((W, CARD_H), "#F7F2E8")
    d = paper_header(im, 3, "AFTER THE ERROR")
    small(d, 64, 142, "빌드 실패 뒤에", RED, 18)
    text(d, (64, 186), "열리는 네 갈래", 75, INK, heavy=True)
    # One source node branching to four distinct decisions; no repetitive option cards.
    d.ellipse((62, 418, 275, 632), fill=CODE)
    text(d, (168, 511), "FAIL", 34, WHITE, mono=True, anchor="mm")
    paths = [
        ((266, 470, 526, 525), "같은 AI로 재시도", RED),
        ((266, 565, 810, 620), "다른 모델로 전환", BLUE),
        ((266, 660, 525, 715), "다른 툴로 우회", LAV),
        ((266, 755, 526, 810), "사람이 확인", GREEN),
    ]
    # Start and branch lines extend into type; avoid boxed-list monotony.
    d.line((275, 525, 320, 525, 320, 782), fill=INK, width=4)
    for idx, (box, s, c) in enumerate(paths):
        x0, y0, x1, y1 = box
        y = (y0+y1)//2
        d.line((320, y, x0, y), fill=c, width=5)
        d.ellipse((x0-10, y-10, x0+10, y+10), fill=c)
        text(d, (x0+28, y+2), s, 31, INK, heavy=True, anchor="lm")
        label(d, 916, y-12, f"0{idx+1}", c, 16)
    marker(d, [(332, 862), (416, 888), (502, 863)], YELLOW, 8)
    text(d, (64, 972), "Jev는 질문·선택 기준을 보고\n이런 판단을 구조화하는 데 쓰인다.", 39, INK, heavy=True, spacing=8)
    rule(d, 1130, INK, width=3)
    text(d, (64, 1170), "모든 작은 분기마다 큰 모델을 부르지 않아도 되게.", 26, SOFT)
    text(d, (64, 1234), "판단 결과를 쓸지는 내 앱이 정한다.", 29, RED, heavy=True)
    im.save(out / "card-03.png")


def slide_4(out: Path):
    im = paper((W, CARD_H), "#F2EEE8")
    d = paper_header(im, 4, "HOW IT FITS")
    small(d, 64, 142, "개념 흐름 · 실제 API 응답 아님", RED, 18)
    text(d, (64, 194), "판단은 Jev,\n실행은 내 코드", 69, INK, heavy=True, spacing=0)
    # A compact field-notebook schema based only on documented fields/semantics.
    d.rectangle((64, 402, 1016, 830), fill=CODE)
    small(d, 102, 448, "INPUT / 앱이 전달", "#B8DB8D", 16)
    text(d, (102, 501), 'state: "build failed + logs"', 26, WHITE, mono=True)
    text(d, (102, 558), "typed_question:", 26, WHITE, mono=True)
    text(d, (377, 558), "다음에 할 행동은?", 26, WHITE)
    text(d, (102, 615), 'choices: retry | other model | human', 24, WHITE, mono=True)
    d.line((102, 686, 978, 686), fill="#5F5A61", width=2)
    small(d, 102, 720, "JEV / 평가", "#B8DB8D", 16)
    text(d, (102, 770), "choices · scores · boolean probabilities", 24, WHITE, mono=True)
    # Emphasize control boundary rather than falsely imply automatic action.
    marker(d, [(781, 880), (850, 902), (937, 876)], YELLOW, 8)
    text(d, (64, 936), "판정값을 받은 앱 코드가", 43, INK, heavy=True)
    text(d, (64, 995), "재시도하거나, 도구를 바꾸거나, 멈춘다.", 35, RED, heavy=True)
    rule(d, 1090, INK, width=3)
    text(d, (64, 1130), "핵심은 ‘Jev가 에이전트를 직접 조종’이 아니라", 27, SOFT)
    text(d, (64, 1190), "‘내 앱이 Jev의 구조화된 판단을 사용’", 34, INK, heavy=True)
    small(d, 64, 1290, "화면의 예시는 개념 설명용 · 실제 호출/결과 아님", MUTED, 15)
    im.save(out / "card-04.png")


def slide_5(out: Path):
    im = paper((W, CARD_H), "#EFECE7")
    d = paper_header(im, 5, "SAVE THIS")
    # The supplied horned snake appears as one cropped-in editorial sticker only here.
    src = Image.open(CHAR_SNAKE).convert("RGB")
    sticker = frame_crop(src, (310, 310))
    im.paste(sticker, (706, 128))
    d = ImageDraw.Draw(im)
    small(d, 64, 158, "한 줄로 다시", RED, 18)
    text(d, (64, 212), "작업 AI는\n만들고", 68, INK, heavy=True, spacing=0)
    text(d, (64, 380), "Jev는\n판단하고", 68, INK, heavy=True, spacing=0)
    text(d, (64, 548), "내 앱은\n실행한다", 68, INK, heavy=True, spacing=0)
    marker(d, [(64, 732), (356, 750), (614, 727)], YELLOW, 9)
    rule(d, 810, INK, width=3)
    small(d, 64, 862, "구현할 때 보낼 것", SOFT, 16)
    text(d, (64, 915), "실패 상태  +  질문  +  허용할 선택지", 31, INK, heavy=True)
    text(d, (64, 1000), "판단 결과를 어떤 행동으로 연결할지는\n프로그램에서 직접 통제.", 28, SOFT, spacing=8)
    d.rounded_rectangle((64, 1084, 1016, 1170), radius=8, fill=WHITE, outline=RED, width=3)
    text(d, (92, 1127), "Vercel Gateway: Free*  ·  promo ends Sep 25", 22, INK, mono=True, anchor="lm")
    text(d, (64, 1184), "* 2026.09.23 확인 · 가격/프로모션은 바뀔 수 있음", 16, MUTED)
    d.rectangle((64, 1215, 1016, 1280), fill=CODE)
    text(d, (94, 1248), "저장 · 다음 실패 때 구조만 참고", 24, WHITE, heavy=True, anchor="lm")
    label(d, 64, 1281, "SOURCE: VERCEL.COM/AI-GATEWAY/MODELS/JEV", MUTED, 15)
    im.save(out / "card-05.png")


def reel_base(t):
    im = paper((RW, RH), "#F4F0E9")
    d = ImageDraw.Draw(im)
    # Tight, editorial safe zone instead of a permanent top/bottom UI frame.
    d.rectangle((0, 0, RW, 146), fill=CODE)
    label(d, 58, 55, "BUILD LOG / JEV", "#E1DAD0", 17)
    boundaries = (0.0, 3.0, 6.5, 11.0)
    step = max(i for i, edge in enumerate(boundaries) if t >= edge)
    text(d, (1022, 55), f"{step+1:02d}", 19, YELLOW, mono=True, anchor="ra")
    d.rectangle((0, 142, int(RW * max(0, min(t / 15.0, 1))), 151), fill=YELLOW)
    return im, d


def reel_terminal(im, t, photo):
    d = ImageDraw.Draw(im)
    small(d, 62, 212, "예시 상황 · 빌드 실패", RED, 18)
    d.rectangle((62, 258, 1018, 706), fill=CODE)
    d.ellipse((98, 294, 117, 313), fill=RED)
    d.ellipse((132, 294, 151, 313), fill=YELLOW)
    d.ellipse((166, 294, 185, 313), fill=GREEN)
    text(d, (108, 380), "$ npm run build", 37, WHITE, mono=True)
    text(d, (108, 474), "× Module not found", 42, RED, mono=True)
    text(d, (108, 565), "exit code 1", 28, "#B7B1AA", mono=True)
    # Use the user's untouched original photo as a short PiP reaction only.
    pw, ph = 300, 650
    pic = ImageOps.contain(photo.convert("RGB"), (pw, ph), method=Image.Resampling.LANCZOS)
    px, py = 710, 832
    im.paste(pic, (px, py))
    d.rectangle((px-4, py-4, px+pic.width+4, py+pic.height+4), outline=INK, width=4)
    small(d, px-2, 1504, "원본 사진 · PIP", SOFT, 16)
    text(d, (64, 792), "다음 선택은?", 64, INK, heavy=True)
    if t >= 0.32:
        text(d, (64, 896), "다시 돌려?", 54, INK, heavy=True)
    if t >= 0.83:
        text(d, (64, 990), "다른 모델?", 54, BLUE, heavy=True)
    if t >= 1.34:
        text(d, (64, 1084), "사람 확인?", 54, RED, heavy=True)
        marker(d, [(64, 1192), (246, 1214), (453, 1190)], YELLOW, 9)
    if t >= 1.72:
        text(d, (64, 1310), "코딩 AI가 실패하면,", 42, SOFT)
        text(d, (64, 1370), "그다음은 누가 고를까?", 48, RED, heavy=True)


def reel_fact(im, t):
    d = ImageDraw.Draw(im)
    small(d, 64, 210, "공식 모델 설명 · Vercel AI Gateway", SOFT, 16)
    text(d, (64, 284), "Jev가 보는 건", 70, INK, heavy=True)
    text(d, (64, 372), "상태 + 질문", 88, RED, heavy=True)
    text(d, (64, 500), "답은 구조화해서", 52, INK, heavy=True)
    words = [("choices", RED, 205), ("scores", BLUE, 190), ("boolean\nprobabilities", GREEN, 400)]
    x = 64
    show_count = min(3, max(0, int((t - 0.55) / 0.62) + 1))
    for word, col, width in words[:show_count]:
        d.rectangle((x, 624, x+width, 786), fill=WHITE, outline=col, width=4)
        text(d, (x+width/2, 700), word, 24, INK, mono=True, anchor="mm", spacing=0)
        x += width+18
    if t >= 1.15:
        marker(d, [(671, 863), (771, 881), (885, 856)], YELLOW, 9)
        text(d, (64, 957), "선택 · 점수 · 불리언 확률", 44, INK, heavy=True)
        text(d, (64, 1041), "코드가 읽을 수 있는 판단값으로.", 38, SOFT)
        rule(d, 1180, INK, width=3)
        text(d, (64, 1230), "※ 임의의 실제 점수/확률 화면은 넣지 않았어요.", 23, MUTED)
    if t >= 2.25:
        d.rectangle((64, 1370, 1016, 1504), fill=CODE)
        text(d, (96, 1413), "NOW  /  Free* on Vercel AI Gateway", 25, WHITE, mono=True)
        text(d, (96, 1460), "* promo ends 09.25.2026 · checked 09.23", 19, YELLOW, mono=True)


def reel_routes(im, t):
    d = ImageDraw.Draw(im)
    small(d, 64, 210, "개념 흐름 · 실제 Jev 호출 아님", RED, 17)
    text(d, (64, 276), "앱이 보내고", 75, INK, heavy=True)
    text(d, (64, 366), "Jev가 판단하고", 75, RED, heavy=True)
    text(d, (64, 456), "앱이 실행한다", 75, INK, heavy=True)
    # Draw a decision tree with one branch briefly highlighted by time.
    d.ellipse((74, 656, 252, 834), fill=CODE)
    text(d, (163, 746), "STATE", 23, WHITE, mono=True, anchor="mm")
    if t >= 0.55:
        d.line((252, 745, 354, 745), fill=INK, width=6)
        d.rectangle((354, 654, 575, 836), fill=WHITE, outline=BLUE, width=5)
        text(d, (464, 730), "Jev\njudgment", 30, INK, mono=True, anchor="mm", spacing=0)
    if t >= 1.0:
        d.line((575, 745, 680, 745), fill=INK, width=6)
        d.line((680, 745, 680, 538, 764, 538), fill=RED, width=5)
    if t >= 2.0:
        d.line((680, 745, 764, 745), fill=BLUE, width=5)
    if t >= 2.8:
        d.line((680, 745, 680, 950, 764, 950), fill=GREEN, width=5)
    choices = [("다시 시도", RED, 538), ("다른 툴", BLUE, 745), ("사람 확인", GREEN, 950)]
    show_count = int(t >= 1.0) + int(t >= 2.0) + int(t >= 2.8)
    for name, col, y in choices[:show_count]:
        d.ellipse((752, y-11, 774, y+11), fill=col)
        text(d, (800, y), name, 31, INK, heavy=True, anchor="lm")
    if t >= 3.25:
        text(d, (64, 1390), "어느 갈래로 갈지는", 42, SOFT)
        text(d, (64, 1450), "네 프로그램이 정한 규칙대로.", 46, INK, heavy=True)
        small(d, 64, 1620, "Jev는 모델 · 자동 실행기는 네 코드", MUTED, 16)


def reel_end(im, t):
    d = ImageDraw.Draw(im)
    small(d, 64, 224, "한 줄 요약", SOFT, 18)
    text(d, (64, 312), "GPT / Claude / Codex", 44, INK, mono=True)
    if t >= 0.25:
        text(d, (64, 380), "일을 하고", 73, INK, heavy=True)
    if t >= 0.8:
        d.rectangle((64, 503, 1016, 692), fill=CODE)
        text(d, (104, 566), "Jev", 72, YELLOW, mono=True, heavy=True)
        text(d, (344, 588), "판단하고", 58, WHITE, heavy=True)
    if t >= 1.45:
        text(d, (64, 760), "내 프로그램이 실행한다.", 68, RED, heavy=True)
        marker(d, [(64, 892), (314, 916), (604, 888)], YELLOW, 9)
    if t >= 2.05:
        text(d, (64, 1020), "다음 실패 때 꺼내보게 저장.", 34, INK, heavy=True)
        d.rectangle((64, 1110, 1016, 1246), fill=CODE)
        text(d, (96, 1152), "NOW  /  Free* on Vercel AI Gateway", 25, WHITE, mono=True)
        text(d, (96, 1200), "* promo ends 09.25.2026 · checked 09.23", 19, YELLOW, mono=True)
        small(d, 64, 1320, "출처 · Vercel AI Gateway / models/jev", SOFT, 16)
        text(d, (64, 1430), "선택은 모델, 실행은 네 앱.", 44, RED, heavy=True)
        marker(d, [(64, 1514), (322, 1538), (598, 1512)], YELLOW, 9)


def scene_for(t, photo):
    im, d = reel_base(t)
    if t < 3.0:
        reel_terminal(im, t, photo)
    elif t < 6.5:
        reel_fact(im, t-3.0)
    elif t < 11.0:
        reel_routes(im, t-6.5)
    else:
        reel_end(im, t-11.0)
    return im


def render_cards(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    slide_1(out); slide_2(out); slide_3(out); slide_4(out); slide_5(out)


def render_frames(out: Path, fps=24, duration=15.0):
    out.mkdir(parents=True, exist_ok=True)
    photo = Image.open(PHOTO).convert("RGB")
    count = math.ceil(fps * duration)
    for i in range(count):
        t = i / fps
        scene_for(t, photo).save(out / f"frame-{i:05d}.jpg", quality=94, subsampling=0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cards", type=Path, default=OUT / "cards")
    p.add_argument("--frames", type=Path, default=OUT / "reel-frames-final")
    args = p.parse_args()
    render_cards(args.cards)
    render_frames(args.frames)


if __name__ == "__main__":
    main()
