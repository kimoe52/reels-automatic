from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[3]
CHAR_SNAKE = ROOT / "content/character/character-creature.png"
PHOTO = ROOT / "content/character/reel-human-reference/reference-03.png"

FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

INK = "#19151C"
PAPER = "#ECE8E4"
PAPER_LIGHT = "#F8F5F1"
WHITE = "#FFFDF9"
PURPLE = "#B06CE8"
PURPLE_DARK = "#2A1734"
LIME = "#D9F46A"
CORAL = "#FF776B"
BLUE = "#78CFF5"
MUTED = "#8C8581"
LINE = "#D2CBC5"
BLACK = "#0F0D12"


def fnt(size: int, mono: bool = False):
    return ImageFont.truetype(MONO if mono else FONT, size=size)


def txt(draw: ImageDraw.ImageDraw, xy, text: str, size: int, fill=INK, anchor=None, mono=False, spacing=6):
    draw.multiline_text(xy, text, font=fnt(size, mono), fill=fill, anchor=anchor, spacing=spacing)


def rounded(draw: ImageDraw.ImageDraw, box, radius=24, fill=WHITE, outline=None, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def fit_crop(src: Image.Image, size, centering=(0.5, 0.5)):
    return ImageOps.fit(src.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=centering)


def fit_contain(src: Image.Image, size, bg=BLACK):
    src = src.convert("RGB")
    w, h = size
    scale = min(w / src.width, h / src.height)
    rw, rh = max(1, int(src.width * scale)), max(1, int(src.height * scale))
    resized = src.resize((rw, rh), Image.Resampling.LANCZOS)
    out = Image.new("RGB", (w, h), bg)
    out.paste(resized, ((w - rw) // 2, (h - rh) // 2))
    return out


def shadow_panel(im: Image.Image, box, radius=24, fill=WHITE, outline=None, width=2, shadow=(0, 8, 24, 70)):
    x1, y1, x2, y2 = box
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    ox, oy, blur, alpha = shadow
    od.rounded_rectangle((x1 + ox, y1 + oy, x2 + ox, y2 + oy), radius=radius, fill=(0, 0, 0, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(blur))
    im.paste(overlay, (0, 0), overlay)
    d = ImageDraw.Draw(im)
    if isinstance(fill, Image.Image):
        panel = fill.convert("RGB").resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
        mask = Image.new("L", panel.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, panel.width - 1, panel.height - 1), radius=radius, fill=255)
        im.paste(panel, (x1, y1), mask)
        d.rounded_rectangle(box, radius=radius, outline=outline, width=width)
    else:
        rounded(d, box, radius, fill, outline, width)


def paper(size, dark=False):
    bg = BLACK if dark else PAPER
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    if dark:
        for y in range(0, size[1], 80):
            d.line((0, y, size[0], y), fill="#251E2B", width=1)
        for x in range(0, size[0], 80):
            d.line((x, 0, x, size[1]), fill="#251E2B", width=1)
    else:
        noise = Image.effect_noise(size, 10).convert("L")
        tint = Image.new("RGB", size, "#D8D0C9")
        im = Image.blend(im, tint, 0.05)
        im = Image.blend(im, Image.merge("RGB", (noise, noise, noise)), 0.025)
    return im


def top_label(d, text="JEV / SYSTEM ONE", right=None, dark=False):
    fill = "#D7C6DD" if dark else MUTED
    txt(d, (64, 54), text, 19, fill=fill, mono=True)
    if right:
        txt(d, (1016, 54), right, 18, fill=fill, anchor="ra", mono=True)
    d.line((64, 100, 1016, 100), fill="#4A3D50" if dark else LINE, width=2)


def browser_mock(size=(900, 700), variant="jev"):
    w, h = size
    im = Image.new("RGB", (w, h), PAPER_LIGHT)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, w, 48), fill="#E1DBD6")
    for i, c in enumerate(("#FF6D65", "#F6C34D", "#74C77A")):
        d.ellipse((22 + i * 24, 16, 36 + i * 24, 30), fill=c)
    d.rounded_rectangle((120, 12, w - 28, 36), radius=12, fill="#F4F0EC")
    txt(d, (w // 2, 24), "typesafe.ai / jev", 15, fill=MUTED, anchor="mm", mono=True)
    if variant == "jev":
        txt(d, (w // 2, 104), "Introducing Jev ........ Intelligence beyond chat", 17, fill=MUTED, anchor="mm", mono=True)
        txt(d, (w // 2, 190), "The First (Public)\nSystem One Model:", 47, fill=INK, anchor="mm", spacing=3)
        txt(d, (w // 2, 320), "Jev Gives AI The\nProperties Of Code", 45, fill=INK, anchor="mm", spacing=3)
        d.line((118, 420, w - 118, 420), fill="#D0C7C1", width=2)
        rounded(d, (135, 468, 380, 526), 12, fill="#DA83DC")
        txt(d, (258, 497), "Join Waitlist", 22, fill=WHITE, anchor="mm")
        rounded(d, (410, 468, 700, 526), 12, fill="#1B1620")
        txt(d, (555, 497), "Join Discord", 22, fill=WHITE, anchor="mm")
        txt(d, (w - 36, h - 28), "system one / code intelligence", 14, fill=MUTED, anchor="rs", mono=True)
    elif variant == "x":
        im = Image.new("RGB", (w, h), "#0D0E11")
        d = ImageDraw.Draw(im)
        txt(d, (48, 64), "Post", 20, fill=WHITE, mono=True)
        d.line((48, 92, w - 48, 92), fill="#34343A", width=2)
        txt(d, (52, 132), "Vercel Developers  ◈", 23, fill=WHITE)
        txt(d, (52, 190), "Jev by @typesafeai is\nfree on Vercel AI Gateway until Sept 25.", 32, fill=WHITE, spacing=4)
        txt(d, (52, 322), "Build with the fastest adopted model\non the Gateway at no cost.", 22, fill="#C4C4CB", spacing=4)
        rounded(d, (52, 430, w - 52, h - 92), 20, fill="#15171C", outline="#41434D", width=2)
        txt(d, (82, 475), "Jev was adopted faster than any other\nmodel in AI Gateway history.", 21, fill=WHITE, spacing=4)
        txt(d, (82, 570), "SHARE OF TEAMS, FIRST 24 HOURS", 14, fill="#A7A9B5", mono=True)
        d.line((100, 710, w - 100, 710), fill="#4A4C58", width=2)
        d.line((120, 710, 120, 650), fill=PURPLE, width=10)
        d.line((260, 710, 260, 540), fill=BLUE, width=10)
        d.line((400, 710, 400, 600), fill=LIME, width=10)
        txt(d, (w // 2, h - 38), "@vercel_dev / 17h", 14, fill="#9C9DA5", anchor="ms", mono=True)
    elif variant == "flow":
        im = Image.new("RGB", (w, h), "#111218")
        d = ImageDraw.Draw(im)
        txt(d, (w // 2, 72), "next action routing", 18, fill="#B7B1C6", anchor="mm", mono=True)
        # connectors first
        d.line((220, 310, 420, 310), fill=BLUE, width=5)
        d.line((480, 310, 700, 210), fill=PURPLE, width=5)
        d.line((480, 310, 700, 410), fill=CORAL, width=5)
        d.line((760, 210, 820, 210), fill=LIME, width=5)
        d.line((760, 410, 820, 410), fill=LIME, width=5)
        for x, y, label, color in [
            (110, 260, "build\nfailed", CORAL),
            (380, 260, "Jev\njudgment", BLUE),
            (660, 165, "retry", PURPLE),
            (660, 365, "other tool", LIME),
        ]:
            rounded(d, (x, y, x + 190, y + 100), 20, fill="#1E2029", outline=color, width=3)
            txt(d, (x + 95, y + 50), label, 24, fill=WHITE, anchor="mm", spacing=2)
        txt(d, (w // 2, h - 52), "Multi-Agent AI Workflow Automation", 16, fill="#AAAAB4", anchor="ms", mono=True)
    return im


def caption_bar(im, y, text, accent=PURPLE, height=150, size=44):
    d = ImageDraw.Draw(im)
    d.rectangle((56, y, 1024, y + height), fill="#151217")
    d.rectangle((56, y, 68, y + height), fill=accent)
    txt(d, (96, y + height // 2), text, size, fill=WHITE, anchor="lm", spacing=4)


def paste_round(dst, src, box, radius=22, border=None):
    x, y, w, h = box
    crop = fit_crop(src, (w, h))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    dst.paste(crop, (x, y), mask)
    if border:
        ImageDraw.Draw(dst).rounded_rectangle((x, y, x + w, y + h), radius=radius, outline=border, width=3)


def snake_sticker(dst, box, angle=0):
    src = Image.open(CHAR_SNAKE).convert("RGB")
    x, y, w, h = box
    sticker = fit_crop(src, (w, h))
    if angle:
        sticker = sticker.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    dst.paste(sticker, (x, y))


def render_cards(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    snake = Image.open(CHAR_SNAKE).convert("RGB")

    # 01 — screenshot-first cover, matching the Jev reference grammar.
    im = paper((1080, 1350))
    d = ImageDraw.Draw(im)
    top_label(d, right="01 / 05")
    txt(d, (64, 136), "JEV / A QUICK EXPLAINER", 18, fill=MUTED, mono=True)
    browser = browser_mock((900, 660), "jev")
    browser = browser.rotate(-1.3, expand=True, resample=Image.Resampling.BICUBIC)
    im.paste(browser, (92, 192))
    caption_bar(im, 790, "코딩 AI가 실패하면\n다음은 누가 정해?", accent=PURPLE, height=242, size=55)
    sticker = fit_crop(snake, (270, 270))
    im.paste(sticker, (748, 1040))
    txt(d, (64, 1112), "GPT · Claude · Codex", 22, fill=MUTED, mono=True)
    txt(d, (64, 1162), "일하는 AI  ≠  판단하는 AI", 34, fill=INK)
    txt(d, (64, 1270), "저장해두는 5장 요약", 18, fill=MUTED)
    im.save(out / "card-01.png", quality=95)

    # 02 — contrast between working AI and judgment layer.
    im = paper((1080, 1350))
    d = ImageDraw.Draw(im)
    top_label(d, right="02 / 05")
    txt(d, (64, 150), "일하는 AI는", 72, fill=INK)
    txt(d, (64, 240), "코드를 쓴다", 72, fill=PURPLE)
    terminal = Image.new("RGB", (880, 420), BLACK)
    td = ImageDraw.Draw(terminal)
    td.rectangle((0, 0, 880, 48), fill="#2B2730")
    for i, c in enumerate((CORAL, "#F6C34D", "#72C778")):
        td.ellipse((20 + i * 23, 17, 34 + i * 23, 31), fill=c)
    txt(td, (52, 100), "$ npm run build", 29, fill=BLUE, mono=True)
    txt(td, (52, 180), "✕ Module not found", 34, fill=CORAL, mono=True)
    txt(td, (52, 266), "build_status = failed", 26, fill="#C7C1CF", mono=True)
    txt(td, (52, 350), "what_next = ?", 29, fill=LIME, mono=True)
    shadow_panel(im, (100, 390, 980, 810), radius=22, fill=terminal, outline="#302735", width=2)
    txt(d, (64, 880), "Jev는", 72, fill=INK)
    txt(d, (64, 970), "다음 행동을 고른다", 72, fill=LIME)
    shadow_panel(im, (100, 1080, 980, 1230), radius=18, fill=WHITE, outline=LINE, width=2)
    txt(d, (132, 1155), "retry  /  other AI  /  other tool  /  human", 23, fill=INK, anchor="lm", mono=True)
    txt(d, (64, 1290), "판단을 실행 코드에 돌려준다", 18, fill=MUTED)
    im.save(out / "card-02.png", quality=95)

    # 03 — branches, with one claim per block.
    im = paper((1080, 1350))
    d = ImageDraw.Draw(im)
    top_label(d, right="03 / 05")
    txt(d, (64, 146), "실패 다음에 오는", 58, fill=INK)
    txt(d, (64, 222), "4가지 선택", 76, fill=PURPLE)
    rounded(d, (64, 374, 1016, 526), 22, fill=BLACK)
    txt(d, (104, 450), "build failed  →  next_action = ?", 28, fill=WHITE, anchor="lm", mono=True)
    branches = [
        ("01", "재시도", CORAL, "같은 툴로 한 번 더"),
        ("02", "다른 AI", BLUE, "모델을 바꿔보기"),
        ("03", "다른 툴", PURPLE, "실행 경로 바꾸기"),
        ("04", "사람 확인", LIME, "중요하면 멈추기"),
    ]
    y = 592
    for n, title, color, desc in branches:
        d.line((112, y - 34, 112, y), fill=LINE, width=2)
        rounded(d, (64, y, 1016, y + 124), 20, fill=WHITE, outline=LINE, width=2)
        d.ellipse((94, y + 28, 158, y + 92), fill=color)
        txt(d, (126, y + 60), n, 16, fill=INK, anchor="mm", mono=True)
        txt(d, (196, y + 30), title, 33, fill=INK)
        txt(d, (196, y + 80), desc, 18, fill=MUTED)
        txt(d, (962, y + 60), "→", 32, fill=color, anchor="mm")
        y += 146
    txt(d, (64, 1270), "사람이 매번 고르지 않게 만드는 레이어", 19, fill=MUTED)
    im.save(out / "card-03.png", quality=95)

    # 04 — evidence-like JSON judgment and routing.
    im = paper((1080, 1350))
    d = ImageDraw.Draw(im)
    top_label(d, right="04 / 05")
    txt(d, (64, 146), "Jev가 받는 것", 54, fill=INK)
    txt(d, (64, 214), "그리고 돌려주는 것", 54, fill=PURPLE)
    rounded(d, (64, 360, 1016, 1128), 28, fill="#1A1720")
    txt(d, (104, 416), "INPUT / CONTEXT", 18, fill=BLUE, mono=True)
    txt(d, (104, 466), "build failed + tools", 29, fill=WHITE, mono=True)
    d.line((104, 540, 976, 540), fill="#3D3644", width=2)
    txt(d, (104, 600), "JEV / JUDGMENT", 18, fill=LIME, mono=True)
    txt(d, (104, 652), '{"next_action": "use_other_tool",', 25, fill=WHITE, mono=True)
    txt(d, (104, 700), ' "confidence": 0.82}', 25, fill=PURPLE, mono=True)
    d.line((104, 770, 976, 770), fill="#3D3644", width=2)
    txt(d, (104, 830), "PROGRAM / EXECUTION", 18, fill=CORAL, mono=True)
    txt(d, (104, 882), "run_other_tool()", 33, fill=LIME, mono=True)
    txt(d, (104, 944), "log_result()", 27, fill=WHITE, mono=True)
    txt(d, (104, 1030), "판단은 짧고, 실행은 내 코드가 한다", 22, fill="#C6BECF")
    snake_sticker(im, (742, 1130, 240, 180), angle=0)
    txt(d, (64, 1238), "실제 API 응답이 아닌 구조 예시", 18, fill=MUTED)
    im.save(out / "card-04.png", quality=95)

    # 05 — save/share card, with a quieter finish.
    im = paper((1080, 1350), dark=True)
    d = ImageDraw.Draw(im)
    top_label(d, right="05 / 05", dark=True)
    txt(d, (64, 190), "GPT · Claude · Codex", 40, fill=WHITE)
    txt(d, (64, 270), "= 일을 한다", 76, fill=WHITE)
    d.line((64, 410, 1016, 410), fill="#4A3D50", width=2)
    txt(d, (64, 490), "Jev", 100, fill=LIME)
    txt(d, (64, 610), "= 다음 일을 고른다", 76, fill=PURPLE)
    rounded(d, (64, 820, 1016, 1010), 28, fill="#231B2B", outline="#5C4270", width=2)
    txt(d, (104, 880), "choose  /  route  /  stop", 32, fill=WHITE, mono=True)
    txt(d, (104, 946), "작업 사이의 판단 레이어", 24, fill="#D7C6DD")
    sticker = fit_crop(snake, (260, 260))
    im.paste(sticker, (760, 1040))
    txt(d, (64, 1114), "이 흐름 저장해두기", 42, fill=LIME)
    txt(d, (64, 1200), "TypeSafe · Jev · Early Access", 18, fill="#B8A6C1", mono=True)
    im.save(out / "card-05.png", quality=95)


def reel_bg():
    im = Image.new("RGB", (1080, 1920), "#130F18")
    d = ImageDraw.Draw(im)
    for y in range(0, 1920, 88):
        d.line((0, y, 1080, y), fill="#221A2A", width=1)
    d.rectangle((0, 0, 1080, 420), fill="#2C1242")
    d.rectangle((0, 1480, 1080, 1920), fill="#17101F")
    return im


def reel_header(d, t, duration):
    txt(d, (58, 56), "JEV / SYSTEM ONE", 20, fill="#E1C8E8", mono=True)
    txt(d, (1020, 56), "VIBE CODING", 18, fill="#A897AE", anchor="ra", mono=True)
    d.line((58, 112, 1022, 112), fill="#563A60", width=2)
    d.line((58, 124, 58 + int(964 * min(1, t / duration)), 124), fill=LIME, width=5)


def reel_scene_browser(im, t):
    d = ImageDraw.Draw(im)
    browser = browser_mock((900, 730), "jev")
    zoom = 1.0 + min(0.035, max(0, t) * 0.012)
    browser = browser.resize((int(900 * zoom), int(730 * zoom)), Image.Resampling.LANCZOS)
    im.paste(browser, ((1080 - browser.width) // 2, 188))
    caption_bar(im, 1120, "Jev?\n써보려고 했더니", accent=PURPLE, height=210, size=58)
    txt(d, (64, 1400), "The First System One Model", 20, fill="#C8BACA", mono=True)


def reel_scene_photo(im, t):
    d = ImageDraw.Draw(im)
    txt(d, (68, 190), "코딩 AI가", 66, fill=WHITE)
    txt(d, (68, 278), "또 실패했는데", 74, fill=CORAL)
    photo = Image.open(PHOTO).convert("RGB")
    # Keep the reference photo unwarped; only scale/crop to the panel.
    frame = fit_contain(photo, (520, 850), bg="#25202A")
    shadow_panel(im, (490, 450, 1010, 1300), radius=28, fill=frame, outline="#75607C", width=3)
    rounded(d, (68, 860, 470, 1010), 18, fill="#151217")
    txt(d, (100, 934), "내가 또 결정해?", 40, fill=WHITE, anchor="lm")
    caption_bar(im, 1390, "문제는 실패가 아니라\n그 다음 행동", accent=CORAL, height=220, size=49)


def reel_scene_x(im, t):
    d = ImageDraw.Draw(im)
    screen = browser_mock((900, 990), "x")
    im.paste(screen, (90, 170))
    caption_bar(im, 1200, "웨이트리스트 들어가야 됨;;", accent=CORAL, height=150, size=45)
    txt(d, (90, 1404), "그런데 이건 바로 쓸 수 있음", 30, fill=LIME)
    txt(d, (90, 1460), "Vercel AI Gateway · 9월 25일까지", 18, fill="#C9B9D0")


def reel_scene_flow(im, t):
    d = ImageDraw.Draw(im)
    txt(d, (68, 182), "실패 다음에", 62, fill=WHITE)
    txt(d, (68, 264), "뭘 하지?", 84, fill=LIME)
    flow = browser_mock((930, 760), "flow")
    im.paste(flow, (75, 440))
    caption_bar(im, 1280, "재시도 / 다른 AI / 다른 툴 / 사람 확인", accent=LIME, height=170, size=37)
    txt(d, (75, 1500), "Jev는 이 선택을 확률과 함께 판단한다", 26, fill="#D7C6DD")


def reel_scene_end(im, t):
    d = ImageDraw.Draw(im)
    txt(d, (70, 240), "일하는 AI", 70, fill=WHITE)
    txt(d, (70, 330), "≠", 48, fill="#A897AE")
    txt(d, (70, 430), "판단하는 AI", 70, fill=LIME)
    rounded(d, (70, 650, 1010, 840), 28, fill="#231B2B", outline="#5C4270", width=3)
    txt(d, (112, 724), "Jev = next action layer", 34, fill=WHITE, mono=True)
    txt(d, (112, 788), "choose / route / stop", 26, fill="#D7C6DD", mono=True)
    snake_sticker(im, (680, 940, 300, 300))
    caption_bar(im, 1360, "이 흐름 저장해두기", accent=LIME, height=150, size=47)
    txt(d, (70, 1600), "TypeSafe · Jev · Early Access", 20, fill="#B8A6C1", mono=True)


def render_frame(t, duration, out):
    im = reel_bg()
    d = ImageDraw.Draw(im)
    reel_header(d, t, duration)
    if t < 2.6:
        reel_scene_browser(im, t)
    elif t < 5.4:
        reel_scene_photo(im, t - 2.6)
    elif t < 8.3:
        reel_scene_x(im, t - 5.4)
    elif t < 12.3:
        reel_scene_flow(im, t - 8.3)
    else:
        reel_scene_end(im, t - 12.3)
    im.save(out, quality=93, subsampling=0)


def render_frames(out: Path, fps=15, duration=16.0):
    out.mkdir(parents=True, exist_ok=True)
    count = math.ceil(fps * duration)
    for i in range(count):
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
