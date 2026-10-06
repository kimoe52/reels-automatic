from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "automation/meta-threads/queue/2026-09-23/jev-demo-v7/assets"
PHOTO = ROOT / "content/character/reel-human-reference/reference-03.png"
SNAKE = ROOT / "content/character/character-creature.png"
BROLL = OUT / "decision-moment-bg.png"

CW, CH = 1080, 1350
RW, RH = 1080, 1920

BG = "#0D111B"
PANEL = "#171D29"
PANEL_2 = "#202939"
WHITE = "#F4F6F3"
LIME = "#CBF266"
RED = "#FF5B68"
BLUE = "#86C5FF"
LAV = "#BC9CFF"
MUTED = "#A6AFBE"
OFF = "#E8EBE6"
INK = "#111722"
LINE = "#394253"

FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
MONO_PATH = "/System/Library/Fonts/Menlo.ttc"


def fnt(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(MONO_PATH if mono else FONT_PATH, size=size, index=0 if mono else (6 if bold else 0))


def txt(draw: ImageDraw.ImageDraw, xy, value: str, size: int, fill=WHITE, *, bold=False, mono=False, anchor=None, spacing=8, stroke=0):
    draw.multiline_text(xy, value, font=fnt(size, bold=bold, mono=mono), fill=fill, anchor=anchor,
                        spacing=spacing, stroke_width=stroke, stroke_fill=fill)


def rounded(draw: ImageDraw.ImageDraw, box, radius=22, fill=PANEL, outline=None, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def line(draw: ImageDraw.ImageDraw, points, fill=LINE, width=3):
    draw.line(points, fill=fill, width=width, joint="curve")


def arrow(draw: ImageDraw.ImageDraw, x1, y, x2, fill=LIME, width=5):
    draw.line((x1, y, x2, y), fill=fill, width=width)
    draw.polygon(((x2 - 13, y - 10), (x2, y), (x2 - 13, y + 10)), fill=fill)


def pill(draw: ImageDraw.ImageDraw, xy, label: str, fill, ink=INK, *, size=23, pad_x=20, pad_y=12):
    x, y = xy
    box = draw.textbbox((0, 0), label, font=fnt(size, mono=(label.isascii() and " " not in label)))
    w = box[2] - box[0] + pad_x * 2
    h = box[3] - box[1] + pad_y * 2
    rounded(draw, (x, y, x + w, y + h), h // 2, fill)
    draw.text((x + w // 2, y + h // 2 - 1), label,
              font=fnt(size, mono=(label.isascii() and " " not in label)), fill=ink, anchor="mm")
    return w, h


def base_card(color=BG):
    return Image.new("RGB", (CW, CH), color)


def card_header(im: Image.Image, section: str, number: int, *, light=False):
    d = ImageDraw.Draw(im)
    fg = MUTED if not light else "#566171"
    d.rectangle((0, 0, CW, 9), fill=LIME)
    txt(d, (58, 46), section.upper(), 17, fg, mono=True)
    txt(d, (1020, 46), f"{number:02d} / 05", 17, fg, mono=True, anchor="ra")
    line(d, ((58, 82), (1022, 82)), LINE if not light else "#B9C1CA", 2)
    return d


def photo_fit(src: Image.Image, size):
    return ImageOps.fit(src.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def draw_card_1(out: Path, broll: Image.Image):
    im = photo_fit(broll, (CW, CH)).convert("RGBA")
    overlay = Image.new("RGBA", im.size, (7, 10, 16, 128))
    im = Image.alpha_composite(im, overlay).convert("RGB")
    d = card_header(im, "BUILD FAILED / THE NEXT MOVE", 1)
    rounded(d, (58, 125, 1022, 188), 12, RED)
    txt(d, (88, 157), "ERROR  /  BUILD STOPPED", 23, INK, mono=True, anchor="lm")
    txt(d, (58, 737), "코딩 AI가 멈춘 뒤,", 51, WHITE, bold=True)
    txt(d, (58, 813), "다음 수는 누가 정해?", 66, LIME, bold=True)
    rounded(d, (58, 1128, 1022, 1280), 16, (13, 17, 27))
    txt(d, (88, 1162), "Jev", 46, LIME, bold=True)
    txt(d, (202, 1161), "상태를 평가해 구조화된 판단을 돌려주는 모델", 25, WHITE, anchor="lm")
    txt(d, (58, 1302), "DEMO VISUAL / NOT A LIVE BUILD LOG OR JEV CALL", 15, WHITE, mono=True)
    im.save(out / "card-01.png")


def draw_card_2(out: Path):
    im = base_card(OFF)
    d = card_header(im, "AFTER THE ERROR", 2, light=True)
    txt(d, (58, 133), "막힌 다음,", 68, INK, bold=True)
    txt(d, (58, 215), "선택지는 네 갈래", 68, INK, bold=True)
    rounded(d, (58, 340, 1022, 1184), 26, BG)
    # A single branching trace ties the options to the failure state.
    d.ellipse((116, 518, 280, 682), fill=RED)
    txt(d, (198, 600), "FAIL", 25, INK, mono=True, bold=True, anchor="mm")
    line(d, ((280, 600), (350, 600), (350, 445), (390, 445)), RED, 5)
    line(d, ((350, 600), (350, 615), (390, 615)), BLUE, 5)
    line(d, ((350, 600), (350, 785), (390, 785)), LAV, 5)
    line(d, ((350, 600), (350, 955), (390, 955)), LIME, 5)
    options = [
        ("다시 시도", "RETRY", RED, 445),
        ("모델 바꾸기", "SWITCH", BLUE, 615),
        ("다른 툴로 우회", "ROUTE", LAV, 785),
        ("사람에게 넘기기", "REVIEW", LIME, 955),
    ]
    for ko, en, color, y in options:
        d.ellipse((380, y - 9, 398, y + 9), fill=color)
        txt(d, (426, y - 19), ko, 31, WHITE, bold=True)
        txt(d, (426, y + 22), en, 15, MUTED, mono=True)
    txt(d, (58, 1224), "Jev가 선택지를 실행하는 게 아니라,", 26, INK)
    txt(d, (58, 1271), "앱이 판단 결과를 받아 다음 동작을 결정해.", 27, INK, bold=True)
    im.save(out / "card-02.png")


def draw_card_3(out: Path):
    im = base_card("#F4F6F3")
    d = card_header(im, "WHAT JEV EVALUATES", 3, light=True)
    txt(d, (58, 142), "Jev는", 48, INK, bold=True)
    txt(d, (58, 204), "상태 + 질문을 평가해", 64, INK, bold=True)
    txt(d, (58, 286), "코드 생성이 아니라, 구조화된 판단", 27, "#596475")
    rounded(d, (58, 388, 1022, 724), 22, BG)
    txt(d, (94, 430), "APP INPUT  /  EXAMPLE", 18, LIME, mono=True)
    line(d, ((94, 474), (986, 474)), LINE, 2)
    txt(d, (94, 514), "state", 22, BLUE, mono=True)
    txt(d, (286, 514), '"Module not found in build log"', 27, WHITE, mono=True)
    txt(d, (94, 594), "question", 22, LAV, mono=True)
    txt(d, (286, 594), '"Which recovery path fits?"', 27, WHITE, mono=True)
    txt(d, (94, 675), "개념 입력 예시 · 실제 API 요청 아님", 18, MUTED)
    txt(d, (58, 807), "Jev가 반환할 수 있는 구조", 31, INK, bold=True)
    tags = [("choices", RED, 210), ("scores", BLUE, 193), ("boolean probabilities", LAV, 437)]
    x = 58
    for label, color, width in tags:
        rounded(d, (x, 864, x + width, 942), 20, BG, outline=color, width=3)
        txt(d, (x + width / 2, 903), label, 20, WHITE, mono=True, anchor="mm")
        x += width + 18
    rounded(d, (58, 1010, 1022, 1204), 18, "#E1E8D6")
    txt(d, (88, 1057), "실제 출력값을 꾸며 넣지 않았어.", 28, INK, bold=True)
    txt(d, (88, 1115), "구조 설명용 예시이며, 실 API를 호출하지 않았어.", 21, "#596475")
    txt(d, (58, 1304), "Source: Vercel AI Gateway · Jev model card", 16, "#596475", mono=True)
    im.save(out / "card-03.png")


def draw_card_4(out: Path):
    im = base_card(BG)
    d = card_header(im, "THE CONTROL BOUNDARY", 4)
    txt(d, (58, 134), "Jev가 판단해도", 55, WHITE, bold=True)
    txt(d, (58, 202), "실행 권한은 앱에", 69, LIME, bold=True)
    txt(d, (58, 292), "AI 모델과 실제 동작 사이, 이 선이 핵심", 25, MUTED)
    nodes = [
        (58, 422, 334, 730, "APP", "state + typed\nquestion", BLUE),
        (376, 422, 704, 730, "JEV", "structured\njudgment", LIME),
        (746, 422, 1022, 730, "YOUR CODE", "policy →\naction", RED),
    ]
    for x1, y1, x2, y2, head, body, color in nodes:
        rounded(d, (x1, y1, x2, y2), 20, PANEL, outline=color, width=3)
        txt(d, (x1 + 24, y1 + 32), head, 17, color, mono=True)
        txt(d, (x1 + 24, y1 + 92), body, 31, WHITE, bold=True, spacing=10)
    arrow(d, 338, 568, 367, BLUE, 5)
    arrow(d, 708, 568, 737, LIME, 5)
    txt(d, (58, 798), "앱이 보내는 내용", 25, BLUE, bold=True)
    txt(d, (58, 846), "현재 상태 + 물어볼 typed question", 26, WHITE)
    line(d, ((58, 903), (1022, 903)), LINE, 2)
    txt(d, (58, 949), "Jev가 돌려주는 것", 25, LIME, bold=True)
    txt(d, (58, 997), "choices · scores · boolean probabilities", 24, WHITE, mono=True)
    line(d, ((58, 1058), (1022, 1058)), LINE, 2)
    txt(d, (58, 1104), "앱 코드가 정하는 것", 25, RED, bold=True)
    txt(d, (58, 1152), "retry / route / stop / ask a person", 24, WHITE, mono=True)
    rounded(d, (58, 1232, 1022, 1301), 14, "#252D3B")
    txt(d, (84, 1267), "CONCEPT ONLY / NO LIVE API REQUEST OR EXECUTION", 15, WHITE, mono=True, anchor="lm")
    im.save(out / "card-04.png")


def draw_card_5(out: Path, snake: Image.Image):
    im = base_card("#F4F6F3")
    d = card_header(im, "SAVE THIS / BUILD YOUR ROUTE", 5, light=True)
    # Keep the snake's source art intact inside its own small lavender square.
    sticker = ImageOps.fit(snake.convert("RGB"), (310, 310), method=Image.Resampling.LANCZOS)
    im.paste(sticker, (712, 118))
    d = ImageDraw.Draw(im)
    txt(d, (58, 151), "다음번엔", 49, INK, bold=True)
    txt(d, (58, 222), "이 세 줄부터", 67, INK, bold=True)
    txt(d, (58, 302), "정리해 봐", 67, INK, bold=True)
    rows = [
        ("01", "state", "무슨 일이 있었나", RED),
        ("02", "question", "무엇을 판단할까", BLUE),
        ("03", "result type", "선택 · 점수 · 확률", LAV),
    ]
    y = 524
    for no, token, desc, color in rows:
        line(d, ((58, y + 68), (1022, y + 68)), "#C5CCD2", 2)
        txt(d, (58, y), no, 18, color, mono=True)
        txt(d, (124, y - 4), token, 31, INK, mono=True, bold=True)
        txt(d, (440, y - 3), desc, 26, "#566171")
        y += 149
    rounded(d, (58, 1008, 1022, 1195), 20, BG)
    txt(d, (92, 1055), "Jev는 판단값을 반환", 33, LIME, bold=True)
    txt(d, (92, 1114), "앱은 정책에 따라 실행", 33, WHITE, bold=True)
    txt(d, (58, 1250), "저장해두고, 다음 자동화 설계 때 참고", 24, INK, bold=True)
    txt(d, (58, 1303), "공식 설명·가격은 캡션의 출처 링크에서 확인", 16, "#596475")
    im.save(out / "card-05.png")


def rounded_panel(im: Image.Image, box, *, fill=PANEL, outline=None, radius=20, width=2):
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def dark_reel(t: float, photo: Image.Image, broll: Image.Image) -> Image.Image:
    im = Image.new("RGB", (RW, RH), BG)
    if t < 2.8:
        bg = photo_fit(broll, (RW, RH)).convert("RGBA")
        bg.alpha_composite(Image.new("RGBA", bg.size, (5, 9, 15, 96)))
        im = bg.convert("RGB")
    elif t < 5.7:
        # The real branching motif travels into the next scene.
        im = Image.new("RGB", (RW, RH), BG)
        d0 = ImageDraw.Draw(im)
        for i in range(18):
            x = i * 80 + 20
            d0.line((x, 260, x + 170, 450, x + 30, 720, x + 210, 1010), fill="#151D2A", width=9)
    else:
        im = Image.new("RGB", (RW, RH), BG)
        d0 = ImageDraw.Draw(im)
        d0.rectangle((0, 0, RW, RH), fill=BG)
        d0.ellipse((770, 200, 1250, 680), fill="#111B26")
        d0.ellipse((-220, 1210, 350, 1780), fill="#151628")
    d = ImageDraw.Draw(im)
    # Consistent tiny progress rail, with generous room for platform chrome.
    d.rectangle((0, 0, RW, 10), fill="#303949")
    d.rectangle((0, 0, int(RW * min(t / 18.0, 1)), 10), fill=LIME)
    txt(d, (58, 56), "BUILD LOG   /   JEV", 17, MUTED, mono=True)
    txt(d, (1020, 56), "EXPLAINER", 16, MUTED, mono=True, anchor="ra")
    return im


def paste_photo(im: Image.Image, photo: Image.Image, t: float):
    # Only scale and move the unmodified source photo. No face retouch, warp, or generated motion.
    w, h = 294, 523
    progress = max(0.0, min(1.0, (t - 1.15) / 0.26))
    x = int(1100 - progress * 370)
    y = 270
    src = photo.convert("RGB").resize((w, h), Image.Resampling.LANCZOS)
    d = ImageDraw.Draw(im)
    rounded(d, (x - 9, y - 9, x + w + 9, y + h + 9), 12, WHITE)
    im.paste(src, (x, y))
    return x


def scene_open(t: float, photo: Image.Image, broll: Image.Image) -> Image.Image:
    im = dark_reel(t, photo, broll)
    d = ImageDraw.Draw(im)
    rounded(d, (58, 205, 433, 277), 14, RED)
    txt(d, (88, 240), "BUILD FAILED", 25, INK, mono=True, bold=True, anchor="lm")
    txt(d, (58, 990), "빌드 또 터졌는데", 64, WHITE, bold=True)
    txt(d, (58, 1074), "AI한테 또 맡겨?", 79, LIME, bold=True)
    if t > 1.14:
        paste_photo(im, photo, t)
        d = ImageDraw.Draw(im)
        txt(d, (58, 1233), "다시?   바꿔?   멈춰?", 31, WHITE, bold=True)
        txt(d, (58, 1290), "이 선택까지 직접 해야 하나", 24, MUTED)
    return im


def scene_options(t: float, photo: Image.Image, broll: Image.Image) -> Image.Image:
    im = dark_reel(t, photo, broll)
    d = ImageDraw.Draw(im)
    txt(d, (58, 212), "빌드 실패 뒤,", 58, WHITE, bold=True)
    txt(d, (58, 282), "갈림길은 네 개", 67, LIME, bold=True)
    options = [
        ("재시도", "RETRY", RED),
        ("모델 변경", "SWITCH", BLUE),
        ("다른 도구", "ROUTE", LAV),
        ("사람 확인", "REVIEW", LIME),
    ]
    elapsed = t - 2.8
    for i, (ko, en, color) in enumerate(options):
        y = 472 + i * 170
        reveal = max(0, min(1, (elapsed - i * 0.34) / 0.24))
        x = int(58 + (1 - reveal) * 130)
        rounded(d, (x, y, x + 900, y + 112), 18, PANEL_2)
        d.rectangle((x, y, x + 10, y + 112), fill=color)
        txt(d, (x + 38, y + 52), ko, 40, WHITE, bold=True, anchor="lm")
        txt(d, (x + 842, y + 54), en, 19, color, mono=True, anchor="rm")
    if t > 4.55:
        txt(d, (58, 1240), "그 ‘다음 수’를", 43, WHITE, bold=True)
        txt(d, (58, 1303), "앱 안에서 판단하게 하는 모델이 Jev.", 34, LIME, bold=True)
    return im


def scene_role(t: float, photo: Image.Image, broll: Image.Image) -> Image.Image:
    im = dark_reel(t, photo, broll)
    d = ImageDraw.Draw(im)
    txt(d, (58, 250), "Jev는 코드를", 56, WHITE, bold=True)
    txt(d, (58, 320), "대신 쓰는 게 아니라", 56, WHITE, bold=True)
    txt(d, (58, 402), "상태를 평가해", 75, LIME, bold=True)
    txt(d, (58, 500), "구조화된 판단을 돌려준다", 42, WHITE, bold=True)
    # Four branches converge on the evaluation boundary, not on a fictitious winner.
    cx, cy = 530, 1040
    d.ellipse((cx - 96, cy - 96, cx + 96, cy + 96), fill=LIME)
    txt(d, (cx, cy), "JEV", 35, INK, mono=True, bold=True, anchor="mm")
    branches = [(RED, -370, -318), (BLUE, 368, -318), (LAV, -370, 318), (WHITE, 368, 318)]
    for color, dx, dy in branches:
        line(d, ((cx + (-74 if dx < 0 else 74), cy + (-74 if dy < 0 else 74)),
                 (cx + dx, cy + dy)), color, 7)
        d.ellipse((cx + dx - 12, cy + dy - 12, cx + dx + 12, cy + dy + 12), fill=color)
    txt(d, (58, 1495), "Not a coding agent", 23, MUTED, mono=True)
    txt(d, (58, 1550), "빠르고 구조화된 판단을 위한 평가 모델", 29, WHITE)
    return im


def scene_example(t: float, photo: Image.Image, broll: Image.Image) -> Image.Image:
    im = dark_reel(t, photo, broll)
    d = ImageDraw.Draw(im)
    txt(d, (58, 186), "DEMO INPUT", 19, LIME, mono=True)
    txt(d, (58, 226), "실패 로그를", 54, WHITE, bold=True)
    txt(d, (58, 291), "질문으로 바꾸면", 54, WHITE, bold=True)
    rounded(d, (58, 402, 1022, 847), 18, PANEL)
    txt(d, (94, 438), "STATE", 18, BLUE, mono=True)
    txt(d, (94, 487), '"Module not found"', 30, WHITE, mono=True)
    txt(d, (94, 554), "TYPED QUESTION", 18, LAV, mono=True)
    txt(d, (94, 605), '"Which next step fits?"', 30, WHITE, mono=True)
    txt(d, (94, 736), "개념 입력 예시 · 실 API 요청은 하지 않음", 18, MUTED)
    if t > 9.7:
        rounded(d, (58, 1030, 1022, 1367), 18, "#242B39", outline=LIME, width=3)
        txt(d, (94, 1076), "JEV RETURNS", 19, LIME, mono=True)
        words = [("choices", RED, 220), ("scores", BLUE, 200), ("boolean probabilities", LAV, 450)]
        x = 94
        for label, color, width in words:
            rounded(d, (x, 1140, x + width, 1212), 18, BG, outline=color, width=2)
            txt(d, (x + width / 2, 1176), label, 17, WHITE, mono=True, anchor="mm")
            x += width + 16
        txt(d, (94, 1284), "출력값은 꾸며 넣지 않음", 21, WHITE, bold=True)
    return im


def scene_boundary(t: float, photo: Image.Image, broll: Image.Image) -> Image.Image:
    im = dark_reel(t, photo, broll)
    d = ImageDraw.Draw(im)
    txt(d, (58, 200), "중요한 건", 52, WHITE, bold=True)
    txt(d, (58, 263), "Jev와 네 앱 사이의 경계", 56, LIME, bold=True)
    y = 596
    nodes = [
        (74, 245, "APP", "상태 + 질문", BLUE),
        (417, 244, "JEV", "판단값", LIME),
        (760, 245, "YOUR CODE", "정책대로 실행", RED),
    ]
    for x, width, head, body, color in nodes:
        rounded(d, (x, y, x + width, y + 238), 18, PANEL, outline=color, width=3)
        txt(d, (x + 22, y + 34), head, 17, color, mono=True)
        txt(d, (x + 22, y + 103), body, 29, WHITE, bold=True)
    arrow(d, 326, y + 118, 405, BLUE, 6)
    arrow(d, 662, y + 118, 748, LIME, 6)
    if t > 13.0:
        # Branches are intentionally unselected: these are possible app policies, not a live Jev result.
        for i, (word, color) in enumerate((("retry", RED), ("switch", BLUE), ("ask", LAV))):
            px = 236 + i * 250
            pill(d, (px, 1030), word, color, size=21)
        txt(d, (58, 1178), "실행 동작은 연결한 프로그램이 정한다.", 32, WHITE, bold=True)
        txt(d, (58, 1240), "개념 예시 · 실제 호출/선택 결과 아님", 18, MUTED, mono=True)
    return im


def scene_end(t: float, photo: Image.Image, broll: Image.Image) -> Image.Image:
    im = dark_reel(t, photo, broll)
    d = ImageDraw.Draw(im)
    txt(d, (58, 324), "일하는 AI 옆에", 52, WHITE, bold=True)
    txt(d, (58, 394), "판단을 돌려주는 Jev", 63, LIME, bold=True)
    rounded(d, (58, 574, 1022, 903), 22, PANEL)
    txt(d, (98, 626), "Jev", 66, LIME, bold=True)
    txt(d, (98, 712), "evaluates state → returns structured judgments", 23, WHITE, mono=True)
    line(d, ((98, 791), (982, 791)), LINE, 2)
    txt(d, (98, 835), "your app", 27, RED, mono=True)
    txt(d, (297, 835), "decides what actually runs", 28, WHITE, bold=True)
    txt(d, (58, 1100), "저장해두기", 39, WHITE, bold=True)
    txt(d, (58, 1163), "상태  +  질문  +  결과 형식", 43, LIME, bold=True)
    txt(d, (58, 1310), "Vercel AI Gateway · 공식 모델 설명은 캡션 링크", 17, MUTED)
    return im


def scene_for(t: float, photo: Image.Image, broll: Image.Image) -> Image.Image:
    if t < 2.8:
        return scene_open(t, photo, broll)
    if t < 5.7:
        return scene_options(t, photo, broll)
    if t < 8.2:
        return scene_role(t, photo, broll)
    if t < 12.2:
        return scene_example(t, photo, broll)
    if t < 15.6:
        return scene_boundary(t, photo, broll)
    return scene_end(t, photo, broll)


def render_cards(cards: Path):
    cards.mkdir(parents=True, exist_ok=True)
    broll = Image.open(BROLL).convert("RGB")
    snake = Image.open(SNAKE).convert("RGB")
    draw_card_1(cards, broll)
    draw_card_2(cards)
    draw_card_3(cards)
    draw_card_4(cards)
    draw_card_5(cards, snake)


def render_frames(frames: Path, fps=24, duration=18.0):
    frames.mkdir(parents=True, exist_ok=True)
    photo = Image.open(PHOTO).convert("RGB")
    broll = Image.open(BROLL).convert("RGB")
    count = math.ceil(fps * duration)
    for i in range(count):
        t = i / fps
        scene_for(t, photo, broll).save(frames / f"frame-{i:05d}.jpg", quality=94, subsampling=0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cards", type=Path, default=OUT / "cards")
    p.add_argument("--frames", type=Path, default=OUT / "reel-frames")
    args = p.parse_args()
    render_cards(args.cards)
    render_frames(args.frames)


if __name__ == "__main__":
    main()
