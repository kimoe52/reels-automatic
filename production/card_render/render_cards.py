#!/usr/bin/env python3
"""Render 4:5 card-news PNGs from a card spec with exact Korean text.

Cards are laid out in HTML/CSS and captured with headless Chrome, so text is
typeset from fonts instead of being painted by an image model. The renderer
also records where each panel landed, which lets the Reel step animate those
panels without hand-written crop coordinates.
"""

from __future__ import annotations

import argparse
import base64
import functools
import hashlib
import html
import io
import json
import os
import re
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image, ImageStat

import icons


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "production"))
from project_paths import scratch_directory
CHROME = Path(os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
WIDTH, HEIGHT = 1080, 1350
# One palette per deck keeps every slide in the same visual system; decks rotate palettes for variety.
THEMES: dict[str, dict[str, str]] = {
    "paper": {"paper": "#f8f6ee", "ink": "#111317", "dark": "#111317", "accent": "#0f52ff", "on-accent": "#ffffff",
              "marker": "#93e22b", "marker-soft": "#d8f5a2", "panel": "#e3ebfc", "panel-strong": "#d2dff9",
              "panel-line": "#a9c3fb", "panel-alt": "#eaf6da", "grain": ".07"},
    "mono": {"paper": "#ffffff", "ink": "#0e0e0e", "dark": "#141414", "accent": "#ff4f0f", "on-accent": "#ffffff",
             "marker": "#ffd400", "marker-soft": "#fff0a3", "panel": "#f1f1f1", "panel-strong": "#e2e2e2",
             "panel-line": "#cfcfcf", "panel-alt": "#fff6c7", "grain": ".03"},
    "kraft": {"paper": "#f2eadb", "ink": "#2b211a", "dark": "#2b211a", "accent": "#c2410c", "on-accent": "#fff8ef",
              "marker": "#ffd54a", "marker-soft": "#ffe9a6", "panel": "#fffaf0", "panel-strong": "#eadcc2",
              "panel-line": "#d6c2a0", "panel-alt": "#fff1c9", "grain": ".13"},
    "gray": {"paper": "#ececec", "ink": "#121212", "dark": "#161616", "accent": "#e53935", "on-accent": "#ffffff",
             "marker": "#ffc400", "marker-soft": "#ffe99a", "panel": "#ffffff", "panel-strong": "#dedede",
             "panel-line": "#c9c9c9", "panel-alt": "#fff4d9", "grain": ".05"},
    "mint": {"paper": "#edf6f0", "ink": "#0f1f17", "dark": "#123326", "accent": "#0b8a57", "on-accent": "#ffffff",
             "marker": "#ffc93c", "marker-soft": "#ffe8a8", "panel": "#dcefe4", "panel-strong": "#c9e6d6",
             "panel-line": "#93cdb0", "panel-alt": "#fff4d6", "grain": ".06"},
}
DEFAULT_THEME = "paper"
HEADER_STYLES = {
    "paper": "rule",       # classic editorial rule
    "mono": "chip",        # compact black label
    "kraft": "stamp",      # taped/stamped paper label
    "gray": "editorial",   # thin magazine masthead
    "mint": "soft",        # quiet outlined navigation
}
TYPE_STYLES = {"paper": "poster", "mono": "grotesk", "kraft": "poster", "gray": "grotesk", "mint": "poster"}
# Black Han Sans draws only Hangul; Latin letters and digits fall back to Pretendard Black.
HANGUL = "U+1100-11FF, U+3130-318F, U+A960-A97F, U+AC00-D7A3, U+D7B0-D7FF"
FONTS = {
    "Pretendard": (HERE / "fonts" / "PretendardVariable.ttf", "45 920", None),
    "Black Han Sans": (HERE / "fonts" / "BlackHanSans-Regular.ttf", "100 900", HANGUL),
}
CHARACTERS = {
    # Repaired copy of content/character/character-human-cutout.png (see clean_character.py).
    "human": HERE / "assets" / "character-human.png",
    "creature": ROOT / "content" / "character" / "character-creature-cutout.png",
}
CHROME_FLAGS = [
    "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--use-mock-keychain", "--password-store=basic",
    "--disable-background-networking", "--disable-component-update", "--disable-sync", "--disable-default-apps",
    "--metrics-recording-only", "--disable-breakpad", "--force-color-profile=srgb",
    "--allow-file-access-from-files", "--force-device-scale-factor=1", f"--window-size={WIDTH},{HEIGHT}",
]
GRAIN = ("<svg xmlns='http://www.w3.org/2000/svg' width='260' height='260'>"
         "<filter id='g'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/>"
         "<feColorMatrix values='0 0 0 0 .32 0 0 0 0 .30 0 0 0 0 .24 0 0 0 {grain} 0'/></filter>"
         "<rect width='100%' height='100%' filter='url(#g)'/></svg>")
BRUSH = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 30' preserveAspectRatio='none'>"
         "<path d='M3 15 C40 7 90 11 140 9 C210 6 280 10 330 8 C360 7 385 9 397 12 L395 23 C350 26 300 21 240 23 "
         "C170 25 100 22 60 24 C35 25 15 26 5 24 Z' fill='{marker}'/></svg>")
# Page helpers shared by the card and Reel pages.
PAGE_JS = """
// Load both faces explicitly: a page without Hangul headings would otherwise never request Black Han Sans.
const loadAssets = async () => {
  await Promise.all([document.fonts.load('900 40px "Black Han Sans"', '가'),
                     document.fonts.load('900 40px "Pretendard"', 'A가')]);
  await document.fonts.ready;
  await Promise.all([...document.images].map(image => image.decode().catch(() => null)));
  return document.fonts.check('900 40px "Black Han Sans"', '가') && document.fonts.check('900 40px "Pretendard"', 'A가');
};
// data-fit = the number of lines a text may take; shrink it (down to data-min px) until it fits.
const lineCount = el => {
  const style = getComputedStyle(el);
  const frame = ['paddingTop', 'paddingBottom', 'borderTopWidth', 'borderBottomWidth']
    .reduce((sum, key) => sum + parseFloat(style[key]), 0);
  return Math.round((el.getBoundingClientRect().height - frame) / parseFloat(style.lineHeight));
};
const tooBig = el => lineCount(el) > (Number(el.dataset.fit) || 1) || el.scrollWidth > el.clientWidth + 1;
const fitText = root => {
  for (const el of root.querySelectorAll('[data-fit]')) {
    const min = Number(el.dataset.min) || 20;
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (tooBig(el) && size > min) { size -= 1; el.style.fontSize = size + 'px'; }
  }
};
const snippet = el => el.textContent.trim().slice(0, 30);
// Decorations must not sit on text. Icons and props count by their box; characters only by
// the grid cells their drawing covers (data-solid), after object-fit and overflow clipping.
const coveredTexts = (root, decorSelector) => {
  const edges = r => ({left: r.left, top: r.top, right: r.right, bottom: r.bottom});
  const clip = (a, b) => ({left: Math.max(a.left, b.left), top: Math.max(a.top, b.top),
                           right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom)});
  const cells = img => {
    let area = clip(edges(root.getBoundingClientRect()), edges(img.getBoundingClientRect()));
    for (let node = img.parentElement; node && node !== root; node = node.parentElement)
      if (getComputedStyle(node).overflow !== 'visible') area = clip(area, edges(node.getBoundingClientRect()));
    const box = img.getBoundingClientRect(), style = getComputedStyle(img);
    let [x, y, w, h] = [box.left, box.top, box.width, box.height];
    if (style.objectFit === 'cover') {
      const scale = Math.max(box.width / img.naturalWidth, box.height / img.naturalHeight);
      const [px, py] = style.objectPosition.split(' ').map(value => parseFloat(value) / 100);
      [w, h] = [img.naturalWidth * scale, img.naturalHeight * scale];
      [x, y] = [box.left + (box.width - w) * px, box.top + (box.height - h) * py];
    }
    const grid = img.dataset.solid, n = Math.round(Math.sqrt(grid.length));
    return [...grid].flatMap((cell, i) => cell !== '1' ? [] : [clip(area, {
      left: x + (i % n) * w / n, top: y + Math.floor(i / n) * h / n,
      right: x + (i % n + 1) * w / n, bottom: y + (Math.floor(i / n) + 1) * h / n})]);
  };
  const decor = [...root.querySelectorAll('img[data-solid]')].flatMap(cells)
    .concat([...root.querySelectorAll(decorSelector)].map(el => edges(el.getBoundingClientRect())))
    .filter(r => r.right > r.left && r.bottom > r.top);
  const hits = (a, b) => a.left < b.right - 2 && b.left < a.right - 2 && a.top < b.bottom - 2 && b.top < a.bottom - 2;
  // A line box is taller than its letters (ascent + descent), so trim 15% off the top and bottom.
  const lineBoxes = el => {
    const range = document.createRange();
    range.selectNodeContents(el);
    return [...range.getClientRects()].map(r => {
      const trim = (r.bottom - r.top) * .15;
      return {left: r.left, right: r.right, top: r.top + trim, bottom: r.bottom - trim};
    });
  };
  return [...root.querySelectorAll('[data-fit]')].filter(el => !el.closest('.note, .sources'))
    .filter(el => lineBoxes(el).some(line => decor.some(box => hits(line, box)))).map(snippet);
};
"""
LAYOUT_SCRIPT = PAGE_JS + """
window.__layout = (async () => {
  const fonts = await loadAssets();
  fitText(document);
  const card = document.querySelector('.card');
  const collisions = [];
  const note = document.querySelector('.note, .sources');
  const content = [...document.querySelectorAll('[data-motion]')].filter(el => !el.closest('.note') && el !== note);
  if (note) {
    const limit = note.getBoundingClientRect().top;
    for (const el of content) if (!el.dataset.overlap && el.getBoundingClientRect().bottom > limit + 1) collisions.push(el.dataset.motion);
  }
  const covered = coveredTexts(card, '.float, .cover-prop');
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  return {
    fonts,
    overflow: [...document.querySelectorAll('[data-fit]')].filter(tooBig).map(el => el.textContent.trim().slice(0, 40)),
    collisions,
    covered,
    scroll: [card.scrollWidth, card.scrollHeight],
    boxes: [...document.querySelectorAll('[data-motion]')].map(el => {
      const r = el.getBoundingClientRect();
      return {name: el.dataset.motion, box: [r.left, r.top, r.right, r.bottom].map(Math.round),
              radius: Math.round(parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0)};
    }),
  };
})();
"""
TOKEN = re.compile(r"\{([^{}]+)\}|\[([^\[\]]+)\]")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def rich(text: str) -> str:
    """{word} → blue accent, [word] → lime underline, newline → line break."""
    parts, cursor = [], 0
    for match in TOKEN.finditer(text):
        parts.append(esc(text[cursor:match.start()]))
        accent, underline = match.groups()
        parts.append(f'<span class="accent">{esc(accent)}</span>' if accent is not None
                     else f'<span class="u">{esc(underline)}</span>')
        cursor = match.end()
    parts.append(esc(text[cursor:]))
    return "".join(parts).replace("\n", "<br>")


def line_count(text: str) -> int:
    return text.count("\n") + 1


def title_html(text: str, *, marks_line: int | None = -1, minimum: int = 64, css: str = "title",
               marks_color: str = icons.BLUE, motion: str | None = None) -> str:
    lines = text.split("\n")
    marked = None if marks_line is None else marks_line % len(lines)
    body = "<br>".join(rich(line) + (icons.marks(marks_color) if index == marked else "")
                       for index, line in enumerate(lines))
    moving = f' data-motion="{motion or "title"}"'
    return f'<h1 class="display {css}" data-fit="{len(lines)}" data-min="{minimum}"{moving}>{body}</h1>'


def emblem(name: str) -> str:
    """Pictograms sit on an accent circle; outline drawings stand on their own."""
    if name in icons.GLYPHS:
        return f'<span class="emblem">{icons.draw(name, "glyph")}</span>'
    return f'<span class="emblem plain">{icons.draw(name)}</span>'


@functools.cache
def solid_cells(path: Path, size: int = 24) -> str:
    """Which cells of a coarse grid the drawing covers, so the layout check ignores empty corners."""
    with Image.open(path) as image:
        alpha = image.convert("RGBA").getchannel("A").resize((size, size), Image.Resampling.BOX)
    return "".join("1" if alpha.getpixel((x, y)) > 40 else "0" for y in range(size) for x in range(size))


def character_img(name: str | None, css: str = "") -> str:
    if name not in CHARACTERS:
        return ""
    path = CHARACTERS[name]
    css_class = f' class="{css}"' if css else ""
    return f'<img{css_class} src="{path.as_uri()}" data-solid="{solid_cells(path)}" alt="">'


def sources_html(card: dict[str, Any]) -> str:
    if not card.get("sources"):
        return ""
    entries = "".join(f"<li><b>{esc(name)}</b><i>·</i>{esc(link)}</li>" for name, link in card["sources"])
    return (f'<footer class="sources"><span class="source-chip">{esc(card.get("sources_label", "출처"))}</span>'
            f'<span class="source-bar"></span><ul>{entries}</ul></footer>')


def lead_html(text: str | None) -> str:
    if not text:
        return ""
    return f'<p class="lead" data-motion="lead" data-fit="{line_count(text)}" data-min="28">{rich(text)}</p>'


def chip_html(label: str | None) -> str:
    return f'<div class="chip-row"><span class="chip">{esc(label)}</span>{icons.marks()}</div>' if label else ""


def note_html(note: dict[str, str] | None, extra_class: str = "") -> str:
    if not note:
        return ""
    title = f'<b>{rich(note["title"])}</b><br>' if note.get("title") else ""
    text = rich(note.get("text", ""))
    lines = (1 if title else 0) + line_count(note.get("text", ""))
    bar = '<span class="bar"></span>' if note.get("bar") else ""
    slim = " slim" if not title and "\n" not in note.get("text", "") and note.get("slim") else ""
    return (f'<div class="note{slim} {extra_class}" data-motion="note">{icons.bulb()}{bar}'
            f'<p data-fit="{max(lines, 2 if not slim else 1)}" data-min="22">{title}{text}</p></div>')


def source_media_preview(spec_path: Path, spec: dict[str, Any]) -> dict[str, str] | None:
    """Resolve the first local image/video poster for a cover; remote and escaping paths are rejected."""
    values = spec.get("media")
    if not isinstance(values, list) or not values or spec.get("media_root") != "../source-media":
        return None
    item = values[0]
    if not isinstance(item, dict):
        raise ValueError("첫 source media 항목이 올바르지 않습니다")
    filename = item.get("thumbnail") if item.get("type") == "VIDEO" else item.get("file")
    if not isinstance(filename, str) or not filename or "://" in filename:
        raise ValueError("source media preview가 로컬 파일명이 아닙니다")
    relative = Path(filename)
    root = (spec_path.parent.parent / "source-media").resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root) or not path.is_file():
        raise ValueError("source media preview가 source-media 밖을 가리킵니다")
    with Image.open(path) as image:
        image.verify()
    expected_preview_hash = item.get("thumbnail_sha256") if item.get("type") == "VIDEO" else item.get("sha256")
    if expected_preview_hash:
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected_preview_hash:
                raise ValueError("source media preview 해시가 다릅니다")
    fit = item.get("fit", "contain")
    if fit not in {"contain", "cover"}:
        raise ValueError("source media preview fit이 올바르지 않습니다")
    return {"uri": path.as_uri(), "fit": fit, "label": str(item.get("label") or "원글 이미지")}


def cover(card: dict[str, Any]) -> str:
    badge = ""
    if card.get("badge"):
        badge = (f'<div class="badge-row"><span class="badge" data-motion="badge" data-fit="1" data-min="44">'
                 f'{esc(card["badge"])}</span>{icons.marks()}</div>')
    prop = ""
    if card.get("prop"):
        prop = f'<div class="cover-prop" data-motion="prop" data-overlap="1">{icons.draw(card["prop"], "prop")}</div>'
    visual = card.get("visual", "roads")
    if card.get("_source_media"):
        source = card["_source_media"]
        art = (f'<div class="cover-art-wrap source-media" data-motion="art" data-overlap="1">'
               f'<img src="{source["uri"]}" style="object-fit:{source["fit"]}" alt="">'
               f'<span>{esc(source["label"])}</span></div>')
    elif visual in CHARACTERS:
        art = (f'<div class="cover-art-wrap character" data-motion="art" data-overlap="1">'
               f'{character_img(visual)}</div>')
    else:
        art = f'<div class="cover-art-wrap" data-motion="art">{icons.draw(visual, "roads")}</div>'
    return (title_html(card["title"], marks_line=card.get("marks_line", 0), minimum=84)
            + badge + lead_html(card.get("subtitle")) + art
            + prop + note_html(card.get("note"), "has-prop" if prop else ""))


def compare(card: dict[str, Any]) -> str:
    def side(item: dict[str, str], name: str) -> str:
        return (f'<section class="side {name}" data-motion="{name}">'
                f'<span class="side-name display">{esc(item["name"])}</span>'
                f'<p class="side-text" data-fit="1" data-min="24">{rich(item["text"])}</p>'
                f'<div class="side-art">{icons.draw(item["icon"])}</div></section>')

    connector = ""
    if card.get("connector"):
        connector = f'<span class="connector"><i></i>{esc(card["connector"])}<i></i></span>'
    return (chip_html(card.get("label"))
            + title_html(card["title"], marks_line=card.get("marks_line"), minimum=60)
            + lead_html(card.get("body"))
            + f'<div class="sides">{side(card["left"], "left")}{connector}{side(card["right"], "right")}</div>'
            + note_html(card.get("note")))


def steps(card: dict[str, Any]) -> str:
    items = []
    total = len(card["steps"])
    for number, step in enumerate(card["steps"], start=1):
        before = ""
        if step.get("character") in CHARACTERS:
            before = f'<div class="step-character">{character_img(step["character"])}</div>'
        elif step.get("icon_left"):
            before = f'<div class="step-icon-left">{icons.draw(step["icon_left"])}</div>'
        after = ""
        if step.get("badge"):
            after = (f'<div class="step-badge"><span class="badge" data-fit="1" data-min="40">{esc(step["badge"])}</span>'
                     f'{icons.marks()}</div>')
        elif step.get("icon"):
            after = f'<div class="step-icon">{icons.draw(step["icon"])}</div>'
        options = ""
        if step.get("options"):
            chips = "".join(f'<span class="option">{esc(option)}</span>' for option in step["options"])
            options = (f'<div class="options">{icons.fork(len(step["options"]), 880)}'
                       f'<div class="option-row">{chips}</div></div>')
        items.append(f'<section class="step{" has-options" if options else ""}" data-motion="step{number}">'
                     f'<div class="step-main"><span class="num">{number}</span>{before}'
                     f'<div class="step-text"><span>{rich(step["lead"])}</span>'
                     f'<span class="hl">{rich(step["key"])}</span></div>{after}</div>{options}</section>')
        if number < total:
            items.append(f'<div class="step-arrow">{icons.arrow_down()}</div>')
    return (title_html(card["title"], marks_line=card.get("marks_line", -1), minimum=72)
            + f'<div class="step-list">{"".join(items)}</div>' + note_html(card.get("note")))


def flow(card: dict[str, Any]) -> str:
    columns = []
    total = len(card["steps"])
    width, column, arrow = 984, 296, 48
    for number, step in enumerate(card["steps"], start=1):
        options = {"text": step["icon_text"], "color": icons.BLUE} if step.get("icon_text") else {}
        columns.append(f'<section class="col" data-motion="col{number}"><span class="num">{number}</span>'
                       f'<span class="col-name">{esc(step["name"])}</span>'
                       f'<div class="col-art">{icons.draw(step["icon"], **options)}</div>'
                       f'<p class="col-text" data-fit="1" data-min="24">{rich(step["text"])}</p></section>')
        if number < total:
            columns.append(f'<div class="col-arrow">{icons.arrow_right()}</div>')
    loop = ""
    if card.get("loop"):
        first = column / 2
        last = width - column / 2
        loop = f'<div class="loop">{icons.loop_arrow(width, first, last)}</div>'
    return (title_html(card["title"], marks_line=card.get("marks_line", -1), minimum=60)
            + lead_html(card.get("body"))
            + f'<div class="cols">{"".join(columns)}</div>' + loop + note_html(card.get("note")))


def list_card(card: dict[str, Any]) -> str:
    rows = []
    for number, item in enumerate(card["items"], start=1):
        rows.append(f'<section class="row" data-motion="row{number}">'
                    f'<span class="row-icon">{icons.draw(item["icon"], "glyph")}{icons.rays("right")}</span>'
                    f'<span class="row-bar"></span><div class="row-text">'
                    f'<h2 class="display row-title" data-fit="1" data-min="34">{rich(item["title"])}</h2>'
                    f'<p class="row-desc" data-fit="1" data-min="24">{rich(item["text"])}</p></div></section>')
    if card.get("highlight"):
        item = card["highlight"]
        rows.append(f'<section class="row strong" data-motion="highlight">'
                    f'<span class="row-icon">{icons.bulb(icons.WHITE, icons.LIME)}</span>'
                    f'<span class="row-bar"></span><div class="row-text">'
                    f'<h2 class="display row-title" data-fit="1" data-min="40">{rich(item["title"])}</h2>'
                    f'<p class="row-desc" data-fit="1" data-min="24">{rich(item["text"])}</p></div></section>')
    return (title_html(card["title"], marks_line=card.get("marks_line", -1), minimum=60)
            + f'<div class="rows">{"".join(rows)}</div>' + sources_html(card))


def split(card: dict[str, Any]) -> str:
    def half(item: dict[str, str], tone: str) -> str:
        return (f'<section class="half {tone}" data-motion="{tone}">{emblem(item["icon"])}'
                f'<h2 class="display half-name" data-fit="1" data-min="36">{rich(item["name"])}</h2>'
                f'<p class="half-text" data-fit="{line_count(item["text"])}" data-min="22">{rich(item["text"])}</p>'
                f'</section>')

    verdict = ""
    if card.get("verdict"):
        verdict = (f'<div class="verdict" data-motion="verdict"><span class="verdict-tag">'
                   f'{esc(card.get("verdict_label", "결론"))}</span>'
                   f'<p data-fit="1" data-min="22">{rich(card["verdict"])}</p></div>')
    return (chip_html(card.get("label"))
            + title_html(card["title"], marks_line=None if card.get("label") else -1, minimum=56)
            + f'<div class="split-box">{half(card["left"], "light")}{half(card["right"], "dark")}'
              f'<span class="vs">VS</span></div>' + verdict)


def grid(card: dict[str, Any]) -> str:
    tiles = "".join(f'<section class="tile" data-motion="tile{number}">{emblem(item["icon"])}'
                    f'<h2 class="display tile-name" data-fit="1" data-min="30">{rich(item["name"])}</h2>'
                    f'<p class="tile-text" data-fit="{line_count(item["text"])}" data-min="22">{rich(item["text"])}</p>'
                    f'</section>' for number, item in enumerate(card["items"][:4], start=1))
    return (chip_html(card.get("label"))
            + title_html(card["title"], marks_line=None if card.get("label") else -1, minimum=56)
            + f'<div class="grid4">{tiles}</div>' + note_html(card.get("note")))


def ranked(card: dict[str, Any]) -> str:
    tag = ""
    if card.get("tag"):
        tag = f'<div class="addr" data-motion="tag"><i></i><span data-fit="1" data-min="22">{esc(card["tag"])}</span></div>'
    return (f'<div class="rank-head"><span class="rank display">{esc(card.get("rank", "01"))}</span>'
            + title_html(card["name"], marks_line=None, minimum=52, css="rank-name") + "</div>"
            + tag + f'<div class="rank-art" data-motion="art">{emblem(card["icon"])}</div>'
            + f'<p class="rank-text" data-fit="{line_count(card["text"])}" data-min="26">{rich(card["text"])}</p>'
            + note_html(card.get("note")))


def keyword(card: dict[str, Any]) -> str:
    kicker = f'<p class="kicker">{esc(card["kicker"])}</p>' if card.get("kicker") else ""
    sub = f'<p class="keyword-sub" data-fit="{line_count(card["sub"])}" data-min="24">{rich(card["sub"])}</p>' \
        if card.get("sub") else ""
    return (kicker + title_html(card["text"], marks_line=-1, minimum=72, css="keyword-text",
                                marks_color=icons.LIME, motion="keyword")
            + sub + character_img(card.get("character"), "keyword-character"))


def memo(card: dict[str, Any]) -> str:
    postit = f'<span class="postit">{esc(card["label"])}</span>' if card.get("label") else ""
    boxes = "".join(f'<section class="memo-box" data-motion="memo{number}">'
                    f'<h2 class="display memo-title" data-fit="1" data-min="30">{rich(item["title"])}</h2>'
                    f'<p class="memo-text" data-fit="{line_count(item["text"])}" data-min="22">{rich(item["text"])}</p>'
                    f'</section>' for number, item in enumerate(card["items"][:4], start=1))
    return (postit + title_html(card["title"], marks_line=-1, minimum=56)
            + f'<div class="memos">{boxes}</div>' + note_html(card.get("note")))


def prompt(card: dict[str, Any]) -> str:
    return (chip_html(card.get("label"))
            + title_html(card["title"], marks_line=None if card.get("label") else -1, minimum=56)
            + f'<div class="prompt-box" data-motion="prompt"><div class="prompt-bar">'
              f'<span>{esc(card.get("box_label", "프롬프트"))}</span>{icons.copy()}</div>'
              f'<div class="prompt-body"><pre class="prompt-text" data-fit="{line_count(card["prompt"])}" data-min="24">'
              f'{esc(card["prompt"])}</pre></div></div>'
            + lead_html(card.get("after")) + character_img(card.get("character"), "prompt-character")
            + note_html(card.get("note")))


def cta(card: dict[str, Any]) -> str:
    kicker = f'<p class="kicker">{esc(card["kicker"])}</p>' if card.get("kicker") else ""
    points = "".join(f'<li data-motion="point{number}"><span class="emblem">{icons.draw("check", "glyph")}</span>'
                     f'<span data-fit="1" data-min="24">{rich(point)}</span></li>'
                     for number, point in enumerate(card.get("points", [])[:3], start=1))
    return (kicker + f'<div class="cta-head">{emblem(card.get("icon", "bookmark"))}'
            + title_html(card["title"], marks_line=None, minimum=64) + "</div>"
            + f'<ul class="points">{points}</ul>'
            + character_img(card.get("character"), "cta-character") + sources_html(card))


def cover_vs(card: dict[str, Any]) -> str:
    # The icons share the "vs" row, which stays empty however long the two words get.
    floating = "".join(f'<span class="float f{number}">{emblem(name)}</span>'
                       for number, name in enumerate(card.get("icons", [])[:3], start=1))
    return (f'<div class="vs-stack" data-motion="vs">'
            f'<h1 class="display vs-word" data-fit="1" data-min="80">{rich(card["left"])}</h1>'
            f'<div class="vs-row"><span class="vs-mid">vs</span>{floating}</div>'
            f'<h1 class="display vs-word" data-fit="1" data-min="80">{rich(card["right"])}</h1></div>'
            + title_html(card["title"], marks_line=-1, minimum=44, css="vs-title")
            + lead_html(card.get("subtitle"))
            + character_img(card.get("character"), "vs-character"))


def cover_band(card: dict[str, Any]) -> str:
    visual = card.get("visual", "human")
    if card.get("_source_media"):
        source = card["_source_media"]
        art = (f'<div class="band-media-wrap"><img class="band-media" src="{source["uri"]}" '
               f'style="object-fit:{source["fit"]}" alt=""><span>{esc(source["label"])}</span></div>')
    elif visual in CHARACTERS:
        art = character_img(visual, "band-character")
    elif visual == "roads":
        art = icons.draw("roads", "band-roads")
    else:
        art = '<div class="band-icons">' + "".join(emblem(name) for name in card.get("icons", [])[:3]) + "</div>"
    number = f'<span class="band-number display">{esc(card["number"])}</span>' if card.get("number") else ""
    kicker = f'<p class="band-kicker">{esc(card["kicker"])}</p>' if card.get("kicker") else ""
    return (f'<div class="band-top" data-motion="art" data-overlap="1">{art}{icons.hand_arrow()}{number}</div>'
            f'<div class="band" data-motion="band">{kicker}'
            + title_html(card["title"], marks_line=None, minimum=64, css="band-title") + "</div>")


LAYOUTS = {"cover": cover, "cover_vs": cover_vs, "cover_band": cover_band, "compare": compare, "split": split,
           "steps": steps, "flow": flow, "grid": grid, "ranked": ranked, "keyword": keyword, "memo": memo,
           "prompt": prompt, "list": list_card, "cta": cta}
COVERS = {"cover", "cover_vs", "cover_band"}
ENDINGS = {"list", "cta"}


def font_css() -> str:
    return "".join(f'@font-face{{font-family:"{name}";src:url("{path.as_uri()}") format("truetype");'
                   f'font-weight:{weight};font-display:block{f";unicode-range:{subset}" if subset else ""}}}'
                   for name, (path, weight, subset) in FONTS.items())


def theme_css(name: str) -> str:
    """The deck palette plus the paper grain and marker brush drawn in that palette."""
    theme = THEMES[name]
    palette = ";".join(f"--{key}:{value}" for key, value in theme.items() if key != "grain")
    grain = GRAIN.replace("{grain}", theme["grain"])
    brush = BRUSH.replace("{marker}", theme["marker"])
    return (f':root{{{palette};--grain:url("data:image/svg+xml,{quote(grain)}");'
            f'--brush:url("data:image/svg+xml,{quote(brush)}")}}')


def document_html(spec: dict[str, Any], card: dict[str, Any], number: int, total: int) -> str:
    fonts = font_css()
    theme = spec.get("theme", DEFAULT_THEME)
    # Theme values come after style.css so they override its default palette.
    textures = theme_css(theme)
    style = (HERE / "style.css").read_text(encoding="utf-8")
    # Texture belongs to the background, not an inseparable multiply overlay
    # over lettering. This also keeps exact RGBA exports independently usable.
    style += ".card{isolation:isolate}.grain{z-index:-1}"
    if card.get("header"):
        label = esc(card["header"])
    else:
        label = f'{esc(spec["handle"])}<i>·</i>{esc(spec.get("series", ""))}'
    header = f'<header class="top"><span class="brand">{label}</span><span class="page">{number:02d} / {total:02d}</span></header>'
    card_view = ({**card, "_source_media": spec["_media_preview"]}
                 if number == 1 and spec.get("_media_preview") and card["layout"] in {"cover", "cover_band"}
                 else card)
    body = LAYOUTS[card["layout"]](card_view)
    header_style = spec.get("header_style", HEADER_STYLES[theme])
    type_style = spec.get("type_style", TYPE_STYLES[theme])
    variants = [card["layout"], f"header-{header_style}", f"type-{type_style}"]
    if card_view.get("_source_media"):
        variants.append("has-source")
    if card["layout"] in {"cta", "cover_vs"} and not card.get("character"):
        variants.append("no-character")
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{fonts}{style}{textures}</style>'
            f'</head><body><main class="card {" ".join(variants)}"><div class="grain"></div>{header}{body}</main>'
            f'<script>{LAYOUT_SCRIPT}</script></body></html>')


class Browser:
    """One headless Chrome driven over --remote-debugging-pipe.

    Chrome's one-shot --screenshot mode does not exit on this Mac, so the
    renderer talks DevTools directly and closes the browser itself.
    """

    def __init__(self, profile: Path):
        if not CHROME.exists():
            raise RuntimeError(f"Chrome을 찾을 수 없습니다: {CHROME} (CHROME_PATH로 지정 가능)")
        to_chrome, self._write = os.pipe()
        self._read, from_chrome = os.pipe()

        def attach_pipes() -> None:
            inbound, outbound = os.dup(to_chrome), os.dup(from_chrome)
            os.dup2(inbound, 3)
            os.dup2(outbound, 4)

        self.process = subprocess.Popen(
            [str(CHROME), *CHROME_FLAGS, f"--user-data-dir={profile}", "--remote-debugging-pipe", "about:blank"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=attach_pipes, close_fds=False)
        os.close(to_chrome)
        os.close(from_chrome)
        self._buffer = b""
        self._counter = 0
        self.events: list[dict[str, Any]] = []

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _receive(self, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while b"\0" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self._read], [], [], remaining)[0]:
                raise TimeoutError("Chrome 응답 시간이 초과됐습니다")
            chunk = os.read(self._read, 1 << 20)
            if not chunk:
                raise RuntimeError("Chrome이 예기치 않게 종료됐습니다")
            self._buffer += chunk
        raw, self._buffer = self._buffer.split(b"\0", 1)
        return json.loads(raw)

    def send(self, method: str, params: dict[str, Any] | None = None, *,
             session: str | None = None, timeout: float = 60) -> dict[str, Any]:
        self._counter += 1
        message: dict[str, Any] = {"id": self._counter, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        data = json.dumps(message).encode() + b"\0"
        while data:
            data = data[os.write(self._write, data):]
        while True:
            reply = self._receive(timeout)
            if reply.get("id") == self._counter:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error'].get('message')}")
                return reply.get("result", {})
            self.events.append(reply)

    def wait_event(self, method: str, session: str, timeout: float = 60) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            for index, event in enumerate(self.events):
                if event.get("method") == method and event.get("sessionId") == session:
                    return self.events.pop(index)
            self.events.append(self._receive(max(.1, deadline - time.monotonic())))

    def close(self) -> None:
        try:
            self.send("Browser.close", timeout=10)
        except (OSError, RuntimeError, TimeoutError):
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for descriptor in (self._write, self._read):
            try:
                os.close(descriptor)
            except OSError:
                pass


def new_page(browser: Browser, width: int, height: int) -> str:
    """Open a tab with a fixed CSS-pixel viewport and return its DevTools session id."""
    target_id = browser.send("Target.createTarget", {"url": "about:blank"})["targetId"]
    session = browser.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
    browser.send("Page.enable", session=session)
    browser.send("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, session=session)
    return session


def load(browser: Browser, session: str, page: Path, ready: str) -> Any:
    """Navigate to a local page and wait for its `ready` promise (layout checks)."""
    browser.events.clear()
    browser.send("Page.navigate", {"url": page.as_uri()}, session=session)
    browser.wait_event("Page.loadEventFired", session)
    return evaluate(browser, session, ready)


def evaluate(browser: Browser, session: str, expression: str) -> Any:
    result = browser.send("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                               "returnByValue": True}, session=session)
    if "exceptionDetails" in result:
        details = result["exceptionDetails"]
        raise RuntimeError(f"페이지 스크립트 오류: {details.get('exception', {}).get('description') or details.get('text')}")
    return result["result"].get("value")


def screenshot(browser: Browser, session: str, width: int, height: int, image_format: str = "png") -> bytes:
    """PNG for cards. Video frames use JPEG: the paper grain makes every PNG ~1 MB and ~7× slower to encode."""
    options: dict[str, Any] = {"format": image_format}
    if image_format == "jpeg":
        options["quality"] = 95
    shot = browser.send("Page.captureScreenshot", {
        **options, "captureBeyondViewport": False,
        "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}}, session=session)
    return base64.b64decode(shot["data"])


def validate(spec: dict[str, Any]) -> list[dict[str, Any]]:
    cards = spec.get("cards")
    if not isinstance(cards, list) or not 4 <= len(cards) <= 6:
        raise ValueError("카드는 4~6장이어야 합니다")
    if not spec.get("handle"):
        raise ValueError("handle이 필요합니다")
    if spec.get("theme", DEFAULT_THEME) not in THEMES:
        raise ValueError(f"테마를 알 수 없습니다: {spec.get('theme')} (가능: {', '.join(THEMES)})")
    for index, card in enumerate(cards, start=1):
        if card.get("layout") not in LAYOUTS:
            raise ValueError(f"{index}장 레이아웃을 알 수 없습니다: {card.get('layout')}")
    return cards


SOURCE_LAYER_SCRIPT = """
(() => {
  const card = document.querySelector('.card');
  const nodes = [...card.querySelectorAll('[data-motion],img,svg,h1,h2,h3,p,.top,.sources')]
    .filter(el => !el.parentElement.closest('svg'));
  nodes.forEach((el,index) => el.dataset.sourceLayer = String(index));
  const counts = new Map();
  const records = nodes.map((el, index) => {
    const staticNode = !!el.closest('.top,.sources');
    const role = staticNode ? 'text' : el.matches('h1,.badge') ? 'title'
      : el.matches('img') ? 'character' : el.matches('svg') ? 'prop'
      : el.matches('h2,h3,p') ? 'text' : el.matches('.note') ? 'bubble' : 'panel';
    const base = el.dataset.motion || role;
    const count = (counts.get(base) || 0) + 1; counts.set(base, count);
    const name = base + '-' + count;
    let z = 0;
    for (let node = el; node && node !== card; node = node.parentElement) {
      const value = getComputedStyle(node).zIndex;
      if (value !== 'auto') z += Number(value) || 0;
    }
    // Only this node's own copy: child text nodes are separately exported.
    const clone = el.cloneNode(true);
    clone.querySelectorAll('[data-source-layer]').forEach(child => child.remove());
    const text = clone.textContent.trim();
    return {index, name, role, moving: !staticNode, text, z};
  });
  records.sort((a,b) => a.z - b.z || a.index - b.index);
  return records.map((item, index) => ({...item, z_index:index}));
})()
"""


def export_source_layers(browser: Browser, session: str, target: Path,
                         output: Path, number: int) -> Path:
    """Export actual DOM pixels on transparency, including nested meaning units.

    Geometry stays in the original document. Hide paint only, never remove DOM
    nodes/reflow or substitute reconstructed text and illustrations.
    """
    records = evaluate(browser, session, SOURCE_LAYER_SCRIPT)
    folder = output / "source-layers" / f"page-{number:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    original_styles = evaluate(browser, session, """
      window.__layerNodes = [...document.querySelectorAll('[data-source-layer]')];
      window.__layerStyles = __layerNodes.map(el => el.getAttribute('style'));
      __layerNodes.forEach(el => el.style.visibility = 'hidden');
      true
    """)
    del original_styles
    background = folder / "background.png"
    Image.open(io.BytesIO(screenshot(browser, session, WIDTH, HEIGHT))).convert("RGBA").save(background)
    exported = []
    try:
        browser.send("Emulation.setDefaultBackgroundColorOverride",
                     {"color": {"r": 0, "g": 0, "b": 0, "a": 0}}, session=session)
        evaluate(browser, session, """
          window.__cardStyle = document.querySelector('.card').getAttribute('style');
          window.__bodyStyle = document.body.getAttribute('style');
          window.__htmlStyle = document.documentElement.getAttribute('style');
          document.querySelector('.card').style.visibility = 'hidden';
          document.body.style.background = 'transparent';
          document.documentElement.style.background = 'transparent';
          true
        """)
        for record in records:
            evaluate(browser, session,
                     f"__layerNodes.forEach(el => el.style.visibility = 'hidden');"
                     f"document.querySelector('[data-source-layer=\"{record['index']}\"]').style.visibility = 'visible'")
            with Image.open(io.BytesIO(screenshot(browser, session, WIDTH, HEIGHT))) as opened:
                image = opened.convert("RGBA")
            bounds = image.getchannel("A").getbbox()
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            path = folder / f"layer-{len(exported) + 1:03d}.png"
            image.crop(bounds).save(path)
            exported.append({"name": record["name"], "role": record["role"],
                             "moving": record["moving"], "text": record["text"],
                             "z_index": record["z_index"], "box": [left, top, right-left, bottom-top],
                             "file": path.relative_to(output).as_posix(),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    finally:
        evaluate(browser, session, """
          const restore = (el, value) => value === null ? el.removeAttribute('style') : el.setAttribute('style', value);
          __layerNodes.forEach((el,i) => restore(el, __layerStyles[i]));
          restore(document.querySelector('.card'), __cardStyle);
          restore(document.body, __bodyStyle); restore(document.documentElement, __htmlStyle);
          true
        """)
        browser.send("Emulation.setDefaultBackgroundColorOverride", session=session)
    metadata = output / f"{target.stem}.layers.json"
    metadata.write_text(json.dumps({
        "version": 1, "source_file": target.name, "size": [WIDTH, HEIGHT],
        "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "background": {"file": background.relative_to(output).as_posix(),
                       "sha256": hashlib.sha256(background.read_bytes()).hexdigest()},
        "layers": exported, "provenance": "browser_dom",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # A missing letter, wrong paint order, duplicate panel or opaque cutout
    # cannot be called cards_ready even when Chrome produced valid PNG files.
    import sys
    motion_path = str(HERE.parent / "card_motion")
    if motion_path not in sys.path:
        sys.path.append(motion_path)
    from source_layers import load_source_card
    load_source_card(metadata, target)
    return metadata


def render(spec_path: Path, output: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    cards = validate(spec)
    preview = source_media_preview(spec_path, spec)
    if preview:
        spec["_media_preview"] = preview
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"source": spec.get("source"), "theme": spec.get("theme", DEFAULT_THEME),
                              "source_media": bool(preview), "cards": []}
    with tempfile.TemporaryDirectory(prefix="card-render-", dir=scratch_directory("card-render")) as temporary, \
            Browser(Path(temporary) / "chrome-profile") as browser:
        work = Path(temporary)
        session = new_page(browser, WIDTH, HEIGHT)
        for number, card in enumerate(cards, start=1):
            page = work / f"{number:02d}.html"
            page.write_text(document_html(spec, card, number, len(cards)), encoding="utf-8")
            name = f"{number:02d}-{card['layout']}.png"
            target = output / name
            layout = load(browser, session, page, "window.__layout")
            target.write_bytes(screenshot(browser, session, WIDTH, HEIGHT))
            layers = export_source_layers(browser, session, target, output, number)
            with Image.open(target) as image:
                if image.size != (WIDTH, HEIGHT):
                    raise RuntimeError(f"{number}장 크기가 {image.size}입니다")
            problems = []
            if not layout["fonts"]:
                problems.append("폰트 로드 실패")
            if layout["overflow"]:
                problems.append(f"글자 넘침: {layout['overflow']}")
            if layout["collisions"]:
                problems.append(f"하단 박스와 겹침: {layout['collisions']}")
            if layout["covered"]:
                problems.append(f"그림이 글자를 가림: {layout['covered']}")
            if layout["scroll"] != [WIDTH, HEIGHT]:
                problems.append(f"카드 밖으로 넘침: {layout['scroll']}")
            report["cards"].append({"file": name, "layout": card["layout"], "boxes": layout["boxes"],
                                    "layers_file": layers.name,
                                    "problems": problems})
    prune_stale_cards(output, {card["file"] for card in report["cards"]})
    (output / "layout.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    contact_sheet(output, [card["file"] for card in report["cards"]])
    return report


def prune_stale_cards(output: Path, current: set[str]) -> None:
    """Remove only obsolete renderer-owned numbered PNGs after a full deck succeeds.

    A prior six-card attempt otherwise leaves `05-*` and `06-*` beside a new
    four-card deck, where a later motion or review step can mistake them for
    current cards. Preview images and user-provided files are never touched.
    """
    for path in output.glob("[0-9][0-9]-*.png"):
        if path.name not in current:
            path.unlink()


def contact_sheet(folder: Path, files: list[str]) -> Path:
    """One image with every card side by side, for a quick look before posting."""
    width, height, gap = 432, 540, 12
    sheet = Image.new("RGB", (len(files) * (width + gap) + gap, height + 2 * gap), "#d9d9d9")
    for index, name in enumerate(files):
        with Image.open(folder / name) as card:
            sheet.paste(card.convert("RGB").resize((width, height), Image.Resampling.LANCZOS),
                        (gap + index * (width + gap), gap))
    path = folder / "preview.png"
    sheet.save(path)
    return path


def paper_color(path: Path) -> str:
    """Average an empty margin so a panel's reveal hole matches the textured paper."""
    with Image.open(path) as image:
        red, green, blue = (round(value) for value in ImageStat.Stat(image.convert("RGB").crop((6, 6, 46, 40))).mean)
    return f"#{red:02x}{green:02x}{blue:02x}"


def motion_manifest(report: dict[str, Any], output: Path, seconds_per_card: float = 6, *,
                    manifest_dir: Path | None = None, title: str = "code-rendered cards") -> Path:
    """Turn recorded panel boxes into the existing Reel renderer's motion tiles.

    The manifest is written to `manifest_dir` (default: the card folder) with card
    paths relative to it, so a post folder can hold it where build_ready.py looks.
    """
    manifest_dir = manifest_dir or output
    prefix = Path(os.path.relpath(output, manifest_dir))
    cards = []
    for index, card in enumerate(report["cards"]):
        tiles = []
        boxes = [] if index == 0 else [item for item in card["boxes"] if item["name"] != "note"]
        for order, item in enumerate(boxes):
            x1, y1, x2, y2 = item["box"]
            crop = [max(0, x1 - 2), max(0, y1 - 2), min(WIDTH, x2 + 2), min(HEIGHT, y2 + 2)]
            vertical = card["layout"] in {"steps", "list", "memo", "cta", "prompt", "ranked"}
            direction = -1 if order % 2 == 0 else 1
            tiles.append({"crop": crop, "start": round(.34 + .44 * order, 2), "duration": .44,
                          "offset": [0, 42] if vertical else [64 * direction, 0],
                          "shapes": [{"kind": "round", "box": [x1, y1, x2, y2], "radius": item["radius"]}]})
        cards.append({"file": (prefix / card["file"]).as_posix(), "tiles": tiles})
    manifest = {"version": 1, "title": title, "reviewed": True,
                "source": (report.get("source") or {}).get("permalink", ""),
                "seconds_per_card": seconds_per_card, "fps": 30, "transition": .28,
                "palette": {"paper": paper_color(output / report["cards"][0]["file"]),
                            "accent": THEMES[report.get("theme", DEFAULT_THEME)]["accent"]},
                "audio": None, "audio_decision": "silent", "cards": cards}
    path = manifest_dir / "reel-production.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="카드 스펙 JSON을 4:5 카드 PNG로 렌더")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path, help="기본값: 스펙 옆 cards/ 폴더")
    parser.add_argument("--reel", action="store_true", help="패널 위치로 릴스 모션 설정도 만들기")
    args = parser.parse_args()
    output = args.output or args.spec.parent / "cards"
    report = render(args.spec, output)
    if args.reel:
        motion_manifest(report, output)
    problems = {card["file"]: card["problems"] for card in report["cards"] if card["problems"]}
    print(json.dumps({"output": str(output), "cards": len(report["cards"]), "problems": problems},
                     ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
