from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "automation/meta-threads/queue/2026-09-23/jev-demo-v8/assets"
W, H = 1080, 1920
FPS, DURATION = 24, 18.0

FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

# Screen colors taken from an everyday editor palette: graphite, soft chrome,
# muted blue focus, amber caution and one restrained error red.
DESK = "#D9D8D4"
CHROME = "#EAE9E5"
SIDEBAR = "#F1F0EC"
EDITOR = "#20252C"
TERMINAL = "#191E24"
RULE = "#383E47"
TEXT = "#D9DDE2"
MUTED = "#929AA4"
BLUE = "#7F9FC6"
AMBER = "#D1A45D"
ERROR = "#D56C60"
GREEN = "#91AB96"
INK = "#252A30"


def font(size: int, mono: bool = False, bold: bool = False):
    return ImageFont.truetype(MONO if mono else FONT, size=size,
                              index=0 if mono else (6 if bold else 0))


def label(d, xy, text, size=18, color=MUTED, *, anchor=None):
    d.text(xy, text, font=font(size, mono=True), fill=color, anchor=anchor)


def ui_text(d, xy, text, size=24, color=TEXT, *, bold=False, anchor=None):
    d.text(xy, text, font=font(size, bold=bold), fill=color, anchor=anchor)


def mono_text(d, xy, text, size=23, color=TEXT, *, anchor=None):
    d.text(xy, text, font=font(size, mono=True), fill=color, anchor=anchor)


def draw_shell(scene_name: str, tab: str):
    im = Image.new("RGB", (W, H), DESK)
    d = ImageDraw.Draw(im)

    # The entire image is an editor screen: no photographed device, person,
    # generated office scene, gradients, glow, or floating infographic cards.
    d.rectangle((20, 22, 1060, 1898), fill=EDITOR, outline="#BABAB5", width=2)
    d.rectangle((22, 24, 1058, 98), fill=CHROME)
    for x, c in ((49, "#B66D64"), (77, "#C6A66A"), (105, "#83A68B")):
        d.ellipse((x - 8, 55 - 8, x + 8, 55 + 8), fill=c)
    ui_text(d, (143, 55), "recovery-demo", 22, INK, bold=True, anchor="lm")
    ui_text(d, (303, 55), "/", 20, "#8D8E8A", anchor="lm")
    ui_text(d, (329, 55), scene_name, 20, "#5C6269", anchor="lm")
    label(d, (1028, 55), "CONCEPT SCREEN · NOT LIVE", 14, "#666C73", anchor="rm")

    # Narrow activity rail and plain file explorer, modeled on a real editor.
    d.rectangle((22, 98, 82, 1848), fill="#292E35")
    for y, mark, active in ((151, "EX", True), (213, "SR", False), (275, "BR", False), (337, "T", False)):
        if active:
            d.rectangle((22, y - 24, 82, y + 24), fill="#353B44")
            d.rectangle((22, y - 24, 26, y + 24), fill=BLUE)
        label(d, (52, y), mark, 15, TEXT if active else MUTED, anchor="mm")

    d.rectangle((82, 98, 330, 1848), fill=SIDEBAR)
    label(d, (108, 133), "EXPLORER", 15, "#64696F")
    ui_text(d, (108, 187), "RECOVERY-DEMO", 16, "#64696F", bold=True)
    entries = (("⌄", "src", 236, False), ("  ◇", "agent.ts", 280, tab == "agent.ts"),
               ("  ◇", "routes.ts", 324, tab == "routes.ts"),
               ("⌄", "logs", 393, False), ("  ▤", "build.log", 437, tab == "build.log"),
               ("◇", "package.json", 506, tab == "package.json"))
    for mark, name, y, active in entries:
        if active:
            d.rectangle((94, y - 20, 319, y + 21), fill="#E1E4E7")
        color = "#42484E" if active else "#6C7277"
        ui_text(d, (111, y), mark, 17, BLUE if active else "#888D91", anchor="lm")
        ui_text(d, (147, y), name, 19, color, anchor="lm")
    d.line((82, 560, 330, 560), fill="#D6D5D0", width=1)
    label(d, (108, 590), "OPEN EDITORS", 14, "#777B7E")
    ui_text(d, (108, 628), tab, 18, "#42484E")

    # Main editor and terminal are stable across cuts, like a real screen capture.
    d.rectangle((330, 98, 1058, 1810), fill=EDITOR)
    d.rectangle((330, 98, 1058, 157), fill="#292E35")
    d.rectangle((331, 99, 560, 156), fill=EDITOR)
    label(d, (354, 128), "◇", 19, BLUE, anchor="lm")
    mono_text(d, (384, 128), tab, 19, TEXT, anchor="lm")
    ui_text(d, (592, 128), "×", 19, MUTED, anchor="lm")
    # Thin native-style section line; no broad decorative framing.
    d.line((330, 157, 1058, 157), fill=RULE, width=1)

    # Status strip.
    d.rectangle((22, 1848, 1058, 1896), fill="#343A42")
    label(d, (48, 1872), "LOCAL DEMO", 14, "#C3C7CA", anchor="lm")
    label(d, (1024, 1872), "UTF-8   TypeScript   100%", 14, "#C3C7CA", anchor="rm")
    return im, d


def draw_editor_lines(d, lines, *, first_row=0, y0=198, line_h=45,
                      reveal=99, cursor_row=None, cursor_col=None):
    x_num, x_code = 365, 419
    visible = min(len(lines), max(0, reveal))
    for idx, item in enumerate(lines[:visible]):
        y = y0 + idx * line_h
        if idx == cursor_row:
            d.rectangle((331, y - 8, 1057, y + line_h - 6), fill="#282E37")
        label(d, (x_num, y + 5), f"{first_row + idx + 1:02d}", 16, "#737C86", anchor="lm")
        text, color = item if isinstance(item, tuple) else (item, TEXT)
        mono_text(d, (x_code, y + 5), text, 21, color, anchor="lm")
        if idx == cursor_row:
            col = cursor_col if cursor_col is not None else len(text)
            caret_x = x_code + int(col * 12.65)
            d.rectangle((caret_x, y - 1, caret_x + 2, y + 27), fill=AMBER)


def terminal(d, entries, *, reveal=99, highlight=None):
    top = 1050
    d.rectangle((330, top, 1058, 1810), fill=TERMINAL)
    d.rectangle((330, top, 1058, top + 50), fill="#23282F")
    label(d, (360, top + 25), "PROBLEMS", 15, MUTED, anchor="lm")
    label(d, (480, top + 25), "OUTPUT", 15, MUTED, anchor="lm")
    label(d, (579, top + 25), "TERMINAL", 15, TEXT, anchor="lm")
    d.line((574, top + 48, 660, top + 48), fill=BLUE, width=2)
    label(d, (1026, top + 25), "zsh", 14, MUTED, anchor="rm")
    for idx, item in enumerate(entries[:reveal]):
        y = top + 94 + idx * 48
        if highlight == idx:
            d.rectangle((346, y - 12, 1042, y + 30), fill="#2A3038")
        if isinstance(item, tuple):
            text, color = item
        else:
            text, color = item, TEXT
        mono_text(d, (365, y), text, 19, color, anchor="lm")


def caption_bar(d, text, *, eyebrow=""):
    # Captions stay quiet and lower-third: one sentence, no giant poster headline.
    d.rectangle((82, 1630, 1058, 1848), fill="#252B32")
    if eyebrow:
        label(d, (114, 1670), eyebrow.upper(), 14, AMBER)
    ui_text(d, (114, 1740), text, 42, TEXT, bold=True, anchor="lm")


def scene_build(t: float):
    im, d = draw_shell("build.log", "build.log")
    code = [
        ("$ pnpm run build", BLUE),
        ("", MUTED),
        ("> typecheck", MUTED),
        ("src/agent.ts:18:26", TEXT),
        ("error TS2307: Cannot find module './routes'", ERROR),
        ("", MUTED),
        ("Found 1 error. Watching for file changes.", MUTED),
    ]
    terminal(d, code, reveal=min(len(code), int(max(0, t) * 4.2) + 1))
    caption_bar(d, "빌드가 멈췄다. 다음 수는?", eyebrow="BUILD FAILED · SAMPLE")
    return im


def scene_paths(t: float):
    im, d = draw_shell("build.log", "build.log")
    editor = [
        ("// Possible recovery paths · none selected", MUTED),
        ("const recoveryPaths = [", TEXT),
        ("  'retry',", AMBER),
        ("  'switch-model',", BLUE),
        ("  'route-to-tool',", TEXT),
        ("  'human-review',", TEXT),
        ("] as const;", TEXT),
        ("", MUTED),
        ("// The app defines these options", MUTED),
    ]
    draw_editor_lines(d, editor, reveal=len(editor))
    options = [
        ("$ recovery paths (sample)", BLUE),
        ("  retry", TEXT),
        ("  switch model", TEXT),
        ("  route to another tool", TEXT),
        ("  ask a person", TEXT),
        ("", MUTED),
        ("No route has been chosen.", AMBER),
    ]
    active = min(4, max(1, int(max(0, t) * 1.15) + 1))
    terminal(d, options, reveal=len(options), highlight=active)
    caption_bar(d, "가능한 선택지일 뿐, Jev가 직접 실행하진 않아.", eyebrow="APP POLICY · CONCEPT")
    return im


def scene_request(t: float):
    im, d = draw_shell("agent.ts", "agent.ts")
    code = [
        ("import { experimental_evaluate as evaluate }", BLUE),
        ("from 'ai';", BLUE),
        ("", MUTED),
        ("const result = await evaluate({", TEXT),
        ("  model: 'typesafe-ai/jev',", AMBER),
        ("  state: buildLog,", TEXT),
        ("  questions: {", TEXT),
        ("    route: {", TEXT),
        ("      type: 'choice',", GREEN),
        ("      instructions: 'Choose a recovery path',", TEXT),
        ("      criteria: { ...appDefinedOptions },", TEXT),
        ("    },", TEXT),
        ("  },", TEXT),
        ("});", TEXT),
    ]
    reveal = min(len(code), max(1, int(max(0, t) * 3.6) + 2))
    draw_editor_lines(d, code, reveal=reveal, cursor_row=min(reveal - 1, 12), cursor_col=17)
    log = [
        ("// SHAPE EXAMPLE · REQUEST NOT SENT", AMBER),
        ("state: buildLog", TEXT),
        ("question: route", TEXT),
        ("type: choice", GREEN),
        ("criteria: app-defined options", TEXT),
        ("", MUTED),
        ("No live model result in this video.", MUTED),
    ]
    terminal(d, log, reveal=len(log))
    caption_bar(d, "상태와 질문을 보낸다. 반환값은 구조화된 판단.", eyebrow="TYPESAFE AI SDK · EXAMPLE ONLY")
    return im


def scene_result(t: float):
    im, d = draw_shell("agent.ts", "agent.ts")
    code = [
        ("// Return shape only · no actual result", MUTED),
        ("result.answers.route", TEXT),
        ("  .type          // 'choice'", GREEN),
        ("  .choice        // <one option>", AMBER),
        ("  .probabilities // <per-option values>", BLUE),
        ("", MUTED),
        ("// Jev returns a judgment.", TEXT),
        ("// App code decides what happens next.", AMBER),
    ]
    reveal = min(len(code), max(1, int(max(0, t) * 3.0) + 2))
    draw_editor_lines(d, code, reveal=reveal, cursor_row=min(reveal - 1, 7), cursor_col=27)
    terminal(d, [
        ("ANSWER SHAPE · PLACEHOLDERS ONLY", AMBER),
        ("route: {", TEXT),
        ("  type: 'choice',", GREEN),
        ("  choice: <one option>,", TEXT),
        ("  probabilities: { ... },", BLUE),
        ("}", TEXT),
    ], reveal=6)
    caption_bar(d, "응답 숫자를 꾸며 넣지 않았어.", eyebrow="SCHEMA SHOWN · NO API CALL")
    return im


def scene_execute(t: float):
    im, d = draw_shell("routes.ts", "routes.ts")
    code = [
        ("const route = result.answers.route.choice;", BLUE),
        ("", MUTED),
        ("if (route === 'retry') {", TEXT),
        ("  await retryBuild();", GREEN),
        ("} else if (route === 'human-review') {", TEXT),
        ("  await requestReview();", GREEN),
        ("} else {", TEXT),
        ("  await routeToTool(route);", GREEN),
        ("}", TEXT),
        ("", MUTED),
        ("// Execution policy stays in our app.", AMBER),
    ]
    reveal = min(len(code), max(1, int(max(0, t) * 3.7) + 2))
    draw_editor_lines(d, code, reveal=reveal, cursor_row=min(reveal - 1, 10), cursor_col=23)
    terminal(d, [
        ("APP POLICY · EXAMPLE", AMBER),
        ("judgment -> checked by local rules", TEXT),
        ("local code -> performs chosen action", GREEN),
        ("", MUTED),
        ("Jev does not click tools or run commands.", TEXT),
    ], reveal=5)
    caption_bar(d, "Jev는 판단. 실행은 연결한 앱.", eyebrow="CONTROL STAYS IN YOUR CODE")
    return im


def scene_end(t: float):
    im, d = draw_shell("README.md", "README.md")
    code = [
        ("# Jev in one line", BLUE),
        ("", MUTED),
        ("Jev  = evaluate shared state", TEXT),
        ("     + return a typed judgment", TEXT),
        ("", MUTED),
        ("Your app = apply policy", AMBER),
        ("          + run the action", GREEN),
        ("", MUTED),
        ("// Save this for the next build error.", MUTED),
    ]
    draw_editor_lines(d, code, reveal=len(code))
    terminal(d, [
        ("OFFICIAL MODEL PAGE", BLUE),
        ("vercel.com/ai-gateway/models/jev", TEXT),
        ("", MUTED),
        ("Concept screen · not a live API demo", AMBER),
    ], reveal=4)
    caption_bar(d, "상태 → 판단 → 앱 코드의 실행", eyebrow="SAVE FOR LATER")
    return im


def scene_at(t: float):
    if t < 2.8:
        return scene_build(t)
    if t < 5.7:
        return scene_paths(t - 2.8)
    if t < 8.2:
        return scene_request(t - 5.7)
    if t < 12.2:
        return scene_result(t - 8.2)
    if t < 15.6:
        return scene_execute(t - 12.2)
    return scene_end(t - 15.6)


def render_frames():
    frames = OUT / "reel-frames"
    frames.mkdir(parents=True, exist_ok=True)
    count = int(FPS * DURATION)
    for i in range(count):
        scene_at(i / FPS).save(frames / f"frame-{i:05d}.jpg", quality=95, subsampling=0)


if __name__ == "__main__":
    render_frames()
