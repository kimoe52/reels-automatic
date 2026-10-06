#!/usr/bin/env python3
"""Render a 9:16 Reel from a card spec: vertical scenes made for Reels, not the 4:5 cards in a frame.

The first card becomes the hook (its title is on screen from the first frame),
each middle card becomes one scene (two sides, rows that fill in, one big
phrase, a typed prompt, a ranked item), and the Reel closes on one save scene.
Short captions sit above Instagram's own caption area. Three looks share the
deck palette:

- band: paper background, the hook question pinned on top, dark caption band
- bold: dark and accent cuts, huge words, outlined captions (manual-only override)
- list: the question pinned in a dark box while a numbered list fills up

Scenes are laid out in HTML/CSS, animated with the Web Animations API and
captured frame by frame over the DevTools pipe; frames where nothing moved are
reused. FFmpeg encodes the result. The automatic route requires an explicit
approved-audio or silent decision in its spec.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import Image

import icons
from render_cards import (CHARACTERS, DEFAULT_THEME, PAGE_JS, Browser, character_img, esc, evaluate, font_css, load, scratch_directory,
                          new_page, rich, screenshot, theme_css, validate)


HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT, FPS = 1080, 1920, 30
STYLES = ("band", "bold", "list")
MIN_SECONDS = 20
MAX_SECONDS = 30
TARGET_MIN_SECONDS = 20.25
STYLE_MAX_SECONDS = {"band": 27.0, "bold": 26.0, "list": 30.0}
MAX_CAPTIONS = 2   # captions per scene; the cards keep the full text
# Every list entry is a source claim. The layout can carry sixteen at its
# smallest readable size; a larger deck must fail and be split, never truncate.
MAX_ENTRIES = 16
MEDIA_TYPES = {"IMAGE", "VIDEO"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
REEL_SCRIPT = PAGE_JS + """
window.__reel = (async () => {
  const fonts = await loadAssets();
  const videos = [...document.querySelectorAll('video[data-media-video]')];
  await Promise.all(videos.map(video => new Promise(resolve => {
    if (video.readyState >= 1) { resolve(); return; }
    let settled = false;
    const done = failed => { if (settled) return; settled = true; video.dataset.failed = failed ? '1' : ''; resolve(); };
    video.addEventListener('loadedmetadata', () => done(false), {once: true});
    video.addEventListener('error', () => done(true), {once: true});
    setTimeout(() => done(video.readyState < 1), 5000);
    video.load();
  })));
  fitText(document);
  const scenes = [...document.querySelectorAll('.scene')];
  // A block that still runs past its stage shrinks as a whole, so its proportions stay intact.
  for (const scene of scenes) {
    const stage = scene.querySelector('.stage'), block = stage && stage.querySelector('[data-shrink]');
    for (let zoom = 1; block && stage.scrollHeight > stage.clientHeight + 1 && zoom > .72; ) {
      zoom -= .03;
      block.style.zoom = zoom;
    }
  }
  const problems = [];
  for (const video of videos) if (video.dataset.failed) problems.push(`원글 영상을 열 수 없음: ${video.dataset.name}`);
  scenes.forEach((scene, index) => {
    const name = `${index + 1}장면`, stage = scene.querySelector('.stage');
    if (stage && stage.scrollHeight > stage.clientHeight + 1) problems.push(`${name}: 내용이 화면 영역을 넘침`);
    for (const el of scene.querySelectorAll('[data-fit]')) if (tooBig(el)) problems.push(`${name}: 글자 넘침 ${snippet(el)}`);
    for (const text of coveredTexts(scene, '.hook-number')) problems.push(`${name}: 그림이 글자를 가림 ${text}`);
    // Instagram draws over the top, the bottom and the right edge; text has to stay clear of them.
    for (const el of scene.querySelectorAll('[data-fit]')) {
      const r = el.getBoundingClientRect();
      if (r.width && (r.left < 40 || r.right > 1040 || r.top < 100 || r.bottom > 1530))
        problems.push(`${name}: 안전 영역 밖 ${snippet(el)}`);
    }
  });

  const FX = {
    punch: [{transform: 'scale(1.07)'}, {transform: 'none'}],
    rise: [{opacity: 0, transform: 'translateY(48px)'}, {opacity: 1, transform: 'none'}],
    cap: [{opacity: 0, transform: 'translateY(18px)'}, {opacity: 1, transform: 'none'}],
    pop: [{opacity: 0, transform: 'scale(.55)'}, {opacity: 1, transform: 'scale(1.06)', offset: .7}, {opacity: 1, transform: 'none'}],
    slideL: [{opacity: 0, transform: 'translateX(-120px)'}, {opacity: 1, transform: 'none'}],
    slideR: [{opacity: 0, transform: 'translateX(120px)'}, {opacity: 1, transform: 'none'}],
    slideU: [{opacity: 0, transform: 'translateY(90px)'}, {opacity: 1, transform: 'none'}],
    fade: [{opacity: 0}, {opacity: 1}],
    dim: [{opacity: 1}, {opacity: .36}],
    lit: [{opacity: .36}, {opacity: 1}],
    draw: [{opacity: 0, transform: 'scaleY(0)'}, {opacity: 1, transform: 'scaleY(1)'}],
    pulse: [{transform: 'none'}, {transform: 'scale(1.12)'}, {transform: 'none'}],
  };
  const MS = {punch: 320, rise: 380, cap: 220, pop: 420, slideL: 380, slideR: 380, slideU: 380, fade: 300, dim: 260,
              lit: 300, draw: 360, pulse: 620};
  // Entrances hide the element until they start; the others only act from their start on.
  const ENTRANCE = new Set(['rise', 'cap', 'pop', 'slideL', 'slideR', 'slideU', 'fade', 'draw']);
  const tracks = scenes.map(scene => {
    const track = {anims: [], shows: [], types: [], pans: [], videos: []};
    for (const el of scene.querySelectorAll('[data-fx]')) {
      for (const part of el.dataset.fx.trim().split(/\\s+/)) {
        const [name, at] = part.split('@'), delay = Number(at) * 1000, duration = MS[name];
        const anim = el.animate(FX[name], {duration, delay, fill: ENTRANCE.has(name) ? 'both' : 'forwards',
                                           easing: 'cubic-bezier(.2,.8,.2,1)'});
        anim.pause();
        track.anims.push({anim, from: delay, to: delay + duration});
      }
    }
    for (const el of scene.querySelectorAll('[data-show]')) {
      const [from, to] = el.dataset.show.split(',').map(Number);
      track.shows.push({el, from, to});
    }
    // Typed text keeps its untyped rest in place (invisible), so lines never re-wrap while typing.
    for (const el of scene.querySelectorAll('[data-type]')) {
      const [at, rate] = el.dataset.type.split(',').map(Number), text = el.textContent;
      const typed = document.createElement('span'), caret = document.createElement('i'), rest = document.createElement('span');
      caret.className = 'caret';
      rest.className = 'rest';
      el.replaceChildren(typed, caret, rest);
      track.types.push({text, typed, caret, rest, at, rate});
    }
    for (const el of scene.querySelectorAll('[data-pan]')) {
      const [from, to] = el.dataset.pan.split(',').map(Number);
      track.pans.push({el, from, to});
    }
    for (const video of scene.querySelectorAll('video[data-media-video]')) {
      const [from, to] = video.dataset.mediaTime.split(',').map(Number);
      track.videos.push({video, from, to, progress: video.parentElement.querySelector('.media-progress i')});
    }
    return track;
  });

  const seekVideo = (video, target) => new Promise(resolve => {
    if (video.dataset.failed || Math.abs(video.currentTime - target) < .012) { resolve(); return; }
    let settled = false;
    const done = () => { if (settled) return; settled = true; resolve(); };
    video.addEventListener('seeked', done, {once: true});
    video.currentTime = target;
    setTimeout(done, 800);
  });
  let current = -1;
  window.__seek = async t => {
    let index = scenes.findIndex(scene => t < Number(scene.dataset.end));
    if (index < 0) index = scenes.length - 1;
    if (index !== current) {
      scenes.forEach((scene, i) => scene.classList.toggle('on', i === index));
      current = index;
    }
    const local = t - Number(scenes[index].dataset.start), ms = local * 1000, track = tracks[index];
    let moving = 0;
    const state = [index];
    for (const item of track.anims) {
      item.anim.currentTime = ms;
      if (ms > item.from && ms < item.to) moving += 1;
    }
    for (const item of track.shows) {
      const on = local >= item.from && local < item.to;
      item.el.style.display = on ? '' : 'none';
      state.push(on ? 1 : 0);
    }
    for (const item of track.types) {
      const count = Math.max(0, Math.min(item.text.length, Math.floor((local - item.at) * item.rate)));
      item.typed.textContent = item.text.slice(0, count);
      item.rest.textContent = item.text.slice(count);
      const typing = count > 0 && count < item.text.length;
      const lit = local >= item.at && (typing || Math.floor(local * 2.4) % 2 === 0);
      item.caret.style.opacity = lit ? 1 : 0;
      if (typing) moving += 1;
      state.push(count, lit ? 1 : 0);
    }
    for (const item of track.pans) {
      const progress = Math.max(0, Math.min(1, (local - item.from) / Math.max(.01, item.to - item.from)));
      item.el.style.transform = `scale(${1.015 + .045 * progress}) translateY(${-8 * progress}px)`;
      if (progress > 0 && progress < 1) moving += 1;
      state.push(progress.toFixed(3));
    }
    const seeks = [];
    for (const item of track.videos) {
      const active = local >= item.from && local < item.to && !item.video.dataset.failed;
      const elapsed = Math.max(0, local - item.from);
      const duration = Math.max(.05, item.video.duration || 0);
      const target = Math.min(duration - .04, elapsed % duration);
      if (active) { seeks.push(seekVideo(item.video, target)); moving += 1; }
      if (item.progress) item.progress.style.transform = `scaleX(${active ? elapsed / Math.max(.01, item.to - item.from) : 0})`;
      state.push(active ? target.toFixed(3) : '-');
    }
    await Promise.all(seeks);
    return {moving, state: state.join(',')};
  };
  await window.__seek(0);
  return {fonts, problems};
})();
"""


# ---------- Copy helpers ----------

def plain(text: Any) -> str:
    return re.sub(r"[{}\[\]]", "", str(text))


def lines_of(text: Any) -> list[str]:
    return [line.strip() for line in str(text or "").split("\n") if line.strip()]


def letters(text: str) -> int:
    return len(re.sub(r"\s", "", plain(text)))


def read_seconds(text: str) -> float:
    """Time to read one caption: about ten letters a second, never a flash."""
    return min(3.4, max(1.3, .7 + .1 * letters(text)))


def merge_short(lines: list[str], limit: int = 16) -> list[str]:
    """Card copy breaks lines for a 4:5 layout; short neighbours read better as one caption."""
    merged: list[str] = []
    for line in lines:
        if merged and letters(merged[-1]) + letters(line) <= limit:
            merged[-1] = f"{merged[-1]} {line}"
        else:
            merged.append(line)
    return merged


def pick(lines: list[str], limit: int = MAX_CAPTIONS) -> list[str]:
    """At most `limit` captions, preferring lines the copy emphasized, kept in their original order."""
    lines = merge_short(lines)
    if len(lines) <= limit:
        return lines
    marked = [index for index, line in enumerate(lines) if re.search(r"[{\[]", line)]
    chosen = (marked + [index for index in range(len(lines)) if index not in marked])[:limit]
    return [lines[index] for index in sorted(chosen)]


def caption_markup(text: str) -> str:
    """Two balanced lines for a long caption.

    A break inside a {…} or […] mark closes the mark on the first line and reopens it on the second.
    """
    if letters(text) <= 17:
        return rich(text)
    opener, spaces = "", []
    for index, char in enumerate(text):
        if char in "{[":
            opener = char
        elif char in "}]":
            opener = ""
        elif char == " ":
            spaces.append((index, opener))
    if not spaces:
        return rich(text)

    def cost(space: tuple[int, str]) -> float:
        index, _ = space
        # A comma or period just before the space is a natural break, so it wins close calls.
        return abs(letters(text[:index]) - letters(text[index + 1:])) - (3 if text[index - 1] in ",." else 0)

    index, mark = min(spaces, key=cost)
    closer = {"{": "}", "[": "]"}.get(mark, "")
    return rich(f"{text[:index]}{closer}\n{mark}{text[index + 1:]}")


def note_lines(card: dict[str, Any]) -> list[str]:
    return lines_of((card.get("note") or {}).get("text"))


def _local_file(root: Path, value: Any, allowed: set[str], label: str) -> Path:
    """Resolve a manifest filename inside source-media; remote URLs and traversal are never rendered."""
    if not isinstance(value, str) or not value or "://" in value:
        raise ValueError(f"{label} 경로가 로컬 파일명이 아닙니다")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} 경로가 source-media 밖을 가리킵니다")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in allowed:
        raise ValueError(f"{label} 파일을 사용할 수 없습니다: {value}")
    return path


def _video_probe(path: Path) -> tuple[int, int, float]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    stream = (value.get("streams") or [{}])[0]
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    duration = float((value.get("format") or {}).get("duration") or 0)
    if not width or not height or duration <= 0:
        raise ValueError(f"영상 정보를 읽을 수 없습니다: {path.name}")
    return width, height, duration


def resolve_media(spec_path: Path, spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate spec media and return HTML-ready local descriptors without changing the spec."""
    values = spec.get("media", [])
    if not values:
        return []
    if not isinstance(values, list) or len(values) > 10 or not all(isinstance(item, dict) for item in values):
        raise ValueError("media는 최대 10개의 로컬 미디어 목록이어야 합니다")
    root_value = spec.get("media_root", "../source-media")
    if root_value != "../source-media":
        raise ValueError("media_root는 ../source-media만 허용합니다")
    root = (spec_path.parent / root_value).resolve()
    expected = (spec_path.parent.parent / "source-media").resolve()
    if root != expected or not root.is_dir():
        raise ValueError(f"source-media 폴더를 찾을 수 없습니다: {root}")

    resolved = []
    for index, item in enumerate(values, start=1):
        kind = str(item.get("type") or "").upper()
        if kind not in MEDIA_TYPES:
            raise ValueError(f"{index}번 media type이 올바르지 않습니다: {kind}")
        allowed = IMAGE_SUFFIXES if kind == "IMAGE" else VIDEO_SUFFIXES
        path = _local_file(root, item.get("file"), allowed, f"{index}번 media")
        if path.stat().st_size > 500 * 1024 * 1024:
            raise ValueError(f"{index}번 media가 500MB를 넘습니다")
        expected_hash = item.get("sha256")
        if expected_hash:
            with path.open("rb") as source:
                actual_hash = hashlib.file_digest(source, "sha256").hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"{index}번 media 해시가 다릅니다")
        if kind == "IMAGE":
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
            duration = 0.0
        else:
            width, height, duration = _video_probe(path)
        poster = None
        if item.get("thumbnail"):
            poster = _local_file(root, item["thumbnail"], IMAGE_SUFFIXES, f"{index}번 thumbnail")
            with Image.open(poster) as image:
                image.verify()
            expected_poster_hash = item.get("thumbnail_sha256")
            if expected_poster_hash:
                with poster.open("rb") as source:
                    if hashlib.file_digest(source, "sha256").hexdigest() != expected_poster_hash:
                        raise ValueError(f"{index}번 thumbnail 해시가 다릅니다")
        fit = item.get("fit", "contain")
        if fit not in {"contain", "cover"}:
            raise ValueError(f"{index}번 media fit은 contain/cover만 허용합니다")
        resolved.append({"type": kind, "path": path, "uri": path.as_uri(),
                         "poster_path": poster, "poster_uri": poster.as_uri() if poster else None,
                         "width": width, "height": height,
                         "duration": duration, "fit": fit, "label": str(item.get("label") or ("원글 영상" if kind == "VIDEO" else "원글 이미지")),
                         "caption": str(item.get("caption") or "")})
    return resolved


# ---------- Plan: scenes and their timing ----------

def schedule(captions: list[str], start: float, pace: float) -> tuple[list[tuple[str, float, float]], float]:
    times, cursor = [], start
    for text in captions:
        length = read_seconds(text) * pace
        times.append((text, cursor, cursor + length))
        cursor += length
    return times, cursor


def hook_scene(card: dict[str, Any], pace: float) -> dict[str, Any]:
    times, end = schedule(pick(lines_of(card.get("subtitle"))), .35 * pace, pace)
    return {"kind": "hook", "card": card, "captions": times, "duration": max(2.4 * pace, end + .2)}


def media_scene(media: list[dict[str, Any]], pace: float) -> dict[str, Any]:
    """One evidence scene: a video or up to three carousel images, never a made-up product UI."""
    shown, cursor, captions = [], 0.0, []
    for item in media[:3]:
        raw = min(4.2, max(2.4, item["duration"])) if item["type"] == "VIDEO" else 1.8
        span = raw * pace
        shown.append({**item, "from": cursor, "to": cursor + span})
        if item["caption"]:
            captions.append((item["caption"], cursor + .15 * pace, cursor + span))
        cursor += span
        if item["type"] == "VIDEO":
            break
    return {"kind": "media", "items": shown, "captions": captions[:MAX_CAPTIONS],
            "duration": max(2.8 * pace, cursor)}


def versus_scene(card: dict[str, Any], pace: float) -> dict[str, Any]:
    source = lines_of(card.get("body")) + note_lines(card) if card["layout"] == "compare" else lines_of(card.get("verdict"))
    cues = {"a": .35 * pace, "b": .95 * pace, "mid": 1.5 * pace}
    times, end = schedule(pick(source), .45 * pace, pace)
    return {"kind": "versus", "card": card, "cues": cues, "captions": times,
            "duration": max(cues["mid"] + 1.6 * pace, end + .2)}


def row_items(card: dict[str, Any]) -> list[dict[str, Any]]:
    layout = card["layout"]
    if layout == "steps":
        return [{"pre": step.get("lead"), "title": step.get("key", ""), "chips": step.get("options") or []}
                for step in card["steps"]]
    if layout == "flow":
        return [{"title": step["name"], "text": step.get("text")} for step in card["steps"]]
    if layout == "grid":
        return [{"title": item["name"], "text": item.get("text")} for item in card["items"][:4]]
    items = [{"title": item["title"], "text": item.get("text")} for item in card["items"][:4]]
    if layout == "list" and card.get("highlight"):
        items.append({"title": card["highlight"]["title"], "text": card["highlight"].get("text"), "strong": True})
    return items


def rows_scene(card: dict[str, Any], pace: float) -> dict[str, Any]:
    items = row_items(card)
    source = (lines_of(card.get("body")) if card["layout"] == "flow" else []) + note_lines(card)
    cues, cursor = [], .35 * pace
    for item in items:
        cues.append(cursor)
        words = " ".join(str(part) for part in (item.get("pre"), item["title"], item.get("text")) if part)
        cursor += max(.55, min(1.1, read_seconds(words) * .42)) * pace
    times, end = schedule(pick(source), .45 * pace, pace)
    return {"kind": "rows", "card": card, "items": items, "cues": cues, "captions": times,
            "duration": max(cues[-1] + 1.5 * pace, end + .2)}


def keyword_scene(card: dict[str, Any], pace: float) -> dict[str, Any]:
    count = len(lines_of(card.get("text")))
    cues = [(.08 + .2 * index) * pace for index in range(count)]
    times, end = schedule(pick(lines_of(card.get("sub"))), (.3 + .2 * count) * pace, pace)
    return {"kind": "keyword", "card": card, "cues": cues, "captions": times, "duration": max(2.4 * pace, end + .2)}


def prompt_scene(card: dict[str, Any], pace: float) -> dict[str, Any]:
    start, rate = .55 * pace, 18 / pace
    finish = start + len(str(card["prompt"])) / rate
    times, end = schedule(pick(lines_of(card.get("after")) + note_lines(card)), (start + finish) / 2, pace)
    return {"kind": "prompt", "card": card, "typing": (start, rate), "captions": times,
            "duration": max(finish + 1.4 * pace, end + .2)}


def rank_scene(card: dict[str, Any], pace: float) -> dict[str, Any]:
    cues = {"name": .12 * pace, "tag": .4 * pace, "art": .55 * pace}
    times, end = schedule(pick(lines_of(card.get("text")) + note_lines(card)), .5 * pace, pace)
    return {"kind": "rank", "card": card, "cues": cues, "captions": times, "duration": max(2.6 * pace, end + .2)}


def cta_scene(card: dict[str, Any], pace: float) -> dict[str, Any]:
    cues = [(.7 + .45 * index) * pace for index in range(len(card.get("points", [])[:3]))]
    return {"kind": "cta", "card": card, "cues": cues, "captions": [],
            "duration": max((cues[-1] if cues else .6 * pace) + 2.0 * pace, 3.0 * pace)}


def deck_character(cards: list[dict[str, Any]]) -> str | None:
    """Reuse a character only when the deck deliberately introduced one."""
    for card in cards:
        for name in (card.get("character"), card.get("visual"), *(step.get("character") for step in card.get("steps", []))):
            if name in CHARACTERS:
                return name
    return None


def closing_card(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """A deck that ends on a summary still gets one save scene, carrying the deck's sources."""
    last = cards[-1]
    return {"layout": "cta", "title": "저장해두고\n{필요할 때} 꺼내보세요", "icon": "bookmark", "points": [],
            "character": deck_character(cards), "sources_label": last.get("sources_label", "원문"),
            "sources": last.get("sources", [])}


def entries_of(card: dict[str, Any]) -> list[dict[str, Any]]:
    """List style: every item in the deck becomes one numbered row, explained by its caption."""
    layout = card["layout"]
    if layout in {"compare", "split"}:
        return [{"title": side["name"], "lines": lines_of(side.get("text"))} for side in (card["left"], card["right"])]
    if layout == "steps":
        return [{"title": step["key"], "lines": [f'{step.get("lead", "")} {step["key"]}'.strip()]}
                for step in card["steps"]]
    if layout == "keyword":
        return [{"title": " ".join(lines_of(card["text"])), "lines": lines_of(card.get("sub"))}]
    if layout == "prompt":
        return [{"title": " ".join(lines_of(card["title"])), "lines": lines_of(card["prompt"])}]
    if layout == "ranked":
        return [{"title": card["name"], "lines": lines_of(card.get("text"))}]
    return [{"title": item["title"], "lines": lines_of(item.get("text"))} for item in row_items(card)]


def entry_scene(index: int, entries: list[dict[str, Any]], pace: float) -> dict[str, Any]:
    times, end = schedule(pick(entries[index]["lines"]), .2 * pace, pace)
    return {"kind": "entry", "index": index, "entries": entries, "captions": times,
            "duration": max(1.5 * pace, end + .15)}


BODY = {"compare": versus_scene, "split": versus_scene, "steps": rows_scene, "flow": rows_scene,
        "grid": rows_scene, "memo": rows_scene, "list": rows_scene, "keyword": keyword_scene,
        "prompt": prompt_scene, "ranked": rank_scene}


def plan(spec: dict[str, Any], style: str, pace: float = 1.0,
         media: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    cards = spec["cards"]
    scenes = [hook_scene(cards[0], pace)]
    if media:
        scenes.append(media_scene(media, pace))
    middle = [card for card in cards[1:] if card["layout"] != "cta"]
    if style == "list":
        entries = [entry for card in middle for entry in entries_of(card)]
        if len(entries) > MAX_ENTRIES:
            raise ValueError(f"목록 항목이 {len(entries)}개입니다. {MAX_ENTRIES}개 이하로 나누어야 원문을 빼지 않고 읽을 수 있습니다")
        scenes += [entry_scene(index, entries, pace) for index in range(len(entries))]
    else:
        scenes += [BODY.get(card["layout"], hook_scene)(card, pace) for card in middle]
    scenes.append(cta_scene(cards[-1] if cards[-1]["layout"] == "cta" else closing_card(cards), pace))
    start = 0.0
    for scene in scenes:
        scene["start"], scene["end"] = start, start + scene["duration"]
        start = scene["end"]
    return scenes


def timed_plan(spec: dict[str, Any], style: str,
               media: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Keep the finished Reel brisk: 20 seconds minimum and a style-specific upper bound."""
    pace = 1.0
    limit = STYLE_MAX_SECONDS[style]
    target_max = limit - .25
    scenes = plan(spec, style, pace, media)
    for _ in range(5):
        duration = scenes[-1]["end"]
        target = TARGET_MIN_SECONDS if duration < MIN_SECONDS else target_max if duration > limit else duration
        if target == duration:
            break
        pace *= target / duration
        scenes = plan(spec, style, pace, media)
    duration = scenes[-1]["end"]
    if not MIN_SECONDS <= duration <= limit:
        raise ValueError(f"릴스 길이를 20~{limit:g}초로 맞추지 못했습니다: {duration:.2f}초")
    return scenes


# ---------- Scene markup ----------

def fx(*parts: tuple[str, float]) -> str:
    return " ".join(f"{name}@{at:.3f}" for name, at in parts)


def icon_badge(name: str, effects: str = "", css: str = "") -> str:
    """Same drawing rules as the cards' emblem, with an optional animation."""
    moving = f' data-fx="{effects}"' if effects else ""
    if name in icons.GLYPHS:
        return f'<span class="emblem {css}"{moving}>{icons.draw(name, "glyph")}</span>'
    return f'<span class="emblem plain {css}"{moving}>{icons.draw(name)}</span>'


def title_lines(text: str, css: str, effects: list[str], minimum: int, marks: str | None) -> str:
    """A display title with one animated span per line; marks point at the last line."""
    lines = lines_of(text)
    spans = []
    for index, line in enumerate(lines):
        effect = effects[min(index, len(effects) - 1)]
        tail = icons.marks(marks) if marks and index == len(lines) - 1 else ""
        spans.append(f'<span class="ln" data-fx="{effect}">{rich(line)}{tail}</span>')
    return f'<h1 class="display {css}" data-fit="{len(lines)}" data-min="{minimum}">{"<br>".join(spans)}</h1>'


# A cut lands on content: the heading is already there ("punch"), the rest of the scene arrives after it.
HIT = fx(("punch", 0))


def heading(card: dict[str, Any], marks: str) -> str:
    chip = f'<span class="chip" data-fx="{HIT}">{esc(card["label"])}</span>' if card.get("label") else ""
    return chip + title_lines(card["title"], "heading", [HIT], 56, marks)


def art(name: str | None, effects: str) -> str:
    image = character_img(name)
    return f'<div class="art" data-fx="{effects}">{image}</div>' if image else ""


def hook_html(scene: dict[str, Any], style: str, marks: str) -> str:
    card = scene["card"]
    layout = card.get("layout")
    # The first frame already shows the whole hook: lines "punch" in place instead of fading in.
    # In the bold look each line takes its own beat.
    lines = [fx(("punch", .14 * index)) for index in range(4)] if style == "bold" else [fx(("punch", 0))]
    parts = []
    if card.get("kicker"):
        parts.append(f'<p class="kicker" data-fx="{fx(("punch", 0))}">{esc(card["kicker"])}</p>')
    if layout == "cover_vs":
        chips = "".join(icon_badge(name, fx(("pop", .1 + .08 * index))) for index, name in enumerate(card.get("icons", [])[:3]))
        parts.append(f'<h1 class="display hook-words" data-fit="1" data-min="90" data-fx="{fx(("punch", 0))}">'
                     f'{rich(card["left"])}</h1><div class="hook-row"><span class="hook-vs">vs</span>{chips}</div>'
                     f'<h1 class="display hook-words" data-fit="1" data-min="90" data-fx="{fx(("punch", 0))}">'
                     f'{rich(card["right"])}</h1>')
        parts.append(title_lines(card["title"], "hook-sub", [fx(("rise", .2))], 48, marks))
    else:
        parts.append(title_lines(card["title"], "hook-title", lines, 84, marks))
    if card.get("badge"):
        parts.append(f'<span class="hook-chip" data-fx="{fx(("punch", 0))}">{esc(card["badge"])}</span>')
    visual = card.get("character") or card.get("visual")
    if card.get("number"):
        parts.append(f'<span class="hook-number display" data-fx="{fx(("pop", .25))}">{esc(card["number"])}</span>')
    if visual == "roads":
        parts.append(f'<div class="art roads-art" data-fx="{fx(("punch", 0))}">{icons.draw("roads", "roads")}</div>')
    elif visual == "icons" or (layout == "cover_band" and card.get("icons") and not character_img(visual)):
        parts.append('<div class="hook-icons">' + "".join(icon_badge(name, fx(("pop", .15 + .1 * index)))
                                                        for index, name in enumerate(card.get("icons", [])[:3])) + "</div>")
    else:
        parts.append(art(visual if layout != "cover_vs" else card.get("character"), fx(("punch", 0))))
    return "".join(parts)


def versus_html(scene: dict[str, Any], style: str, marks: str) -> str:
    card, cues = scene["card"], scene["cues"]
    moves = {"a": "slideU", "b": "slideU"} if style == "bold" else {"a": "slideL", "b": "slideR"}
    sides = []
    for tag, key in (("a", "left"), ("b", "right")):
        item = card[key]
        text = item.get("text", "")
        sides.append(f'<section class="side {tag}" data-fx="{fx((moves[tag], cues[tag]))}">{icon_badge(item["icon"])}'
                     f'<div class="side-copy"><h2 class="display side-name" data-fit="1" data-min="40">{rich(item["name"])}</h2>'
                     f'<p class="side-text" data-fit="{len(lines_of(text)) or 1}" data-min="24">{rich(text)}</p></div></section>')
    middle = esc(card.get("connector") or "VS")
    return (heading(card, marks)
            + f'<div class="duel">{"".join(sides)}<div class="duel-mid">'
              f'<span class="duel-vs" data-fx="{fx(("pop", cues["mid"]))}">{middle}</span></div></div>')


def rows_html(scene: dict[str, Any], style: str, marks: str) -> str:
    items, cues = scene["items"], scene["cues"]
    rows = []
    settled = cues[-1] + .9
    for number, (item, at) in enumerate(zip(items, cues), start=1):
        effects = [("rise", at)]
        if style == "bold" and number < len(items):
            # The bold look keeps the newest row lit while they arrive, then lights them all.
            effects += [("dim", cues[number]), ("lit", settled)]
        pre = f'<p class="row-pre" data-fit="1" data-min="22">{rich(item["pre"])}</p>' if item.get("pre") else ""
        text = (f'<p class="row-text" data-fit="{len(lines_of(item["text"]))}" data-min="22">{rich(item["text"])}</p>'
                if item.get("text") else "")
        chips = ('<div class="row-chips">' + "".join(f"<span>{esc(chip)}</span>" for chip in item["chips"]) + "</div>"
                 if item.get("chips") else "")
        mark = icons.draw("check", "glyph") if item.get("strong") else str(number)
        rows.append(f'<section class="row{" strong" if item.get("strong") else ""}" data-fx="{fx(*effects)}">'
                    f'<span class="num" data-fx="{fx(("pulse", at + .28))}">{mark}</span><div class="row-body">{pre}'
                    f'<h2 class="display row-title" data-fit="1" data-min="30">{rich(item["title"])}</h2>{text}{chips}'
                    f'</div></section>')
        if scene["card"]["layout"] in {"steps", "flow"} and number < len(items):
            rows.append(f'<span class="row-link" data-fx="{fx(("draw", at + .34))}"><i></i></span>')
    linked = scene["card"]["layout"] in {"steps", "flow"}
    return heading(scene["card"], marks) + f'<div class="row-stack{" linked" if linked else ""}" data-shrink>{"".join(rows)}</div>'


def keyword_html(scene: dict[str, Any], style: str, marks: str) -> str:
    card = scene["card"]
    kicker = f'<p class="kicker" data-fx="{HIT}">{esc(card["kicker"])}</p>' if card.get("kicker") else ""
    effects = [HIT] + [fx(("pop", at)) for at in scene["cues"][1:]]
    return (kicker + title_lines(card["text"], "kw-text", effects, 80, icons.LIME if style != "bold" else icons.BLUE)
            + art(card.get("character"), fx(("pop", .35))))


def prompt_html(scene: dict[str, Any], style: str, marks: str) -> str:
    card = scene["card"]
    start, rate = scene["typing"]
    text = str(card["prompt"])
    return (heading(card, marks)
            + f'<div class="prompt-box" data-fx="{fx(("rise", .15))}"><div class="prompt-bar">'
              f'<span>{esc(card.get("box_label", "프롬프트"))}</span>{icons.copy()}</div>'
              f'<pre class="prompt-text" data-fit="{len(text.splitlines()) or 1}" data-min="26" '
              f'data-type="{start:.3f},{rate:.3f}">{esc(text)}</pre></div>')


def rank_html(scene: dict[str, Any], style: str, marks: str) -> str:
    card, cues = scene["card"], scene["cues"]
    tag = (f'<div class="rank-tag" data-fx="{fx(("rise", cues["tag"]))}"><i></i>'
           f'<span data-fit="1" data-min="24">{esc(card["tag"])}</span></div>' if card.get("tag") else "")
    return (f'<div class="rank-top"><span class="display rank-num" data-fx="{HIT}">'
            f'{esc(card.get("rank", "01"))}</span>'
            + title_lines(card["name"], "rank-name", [fx(("rise", cues["name"]))], 52, None) + "</div>"
            + tag + f'<div class="rank-art">{icon_badge(card["icon"], fx(("pop", cues["art"])))}</div>')


def cta_html(scene: dict[str, Any], style: str, marks: str) -> str:
    card = scene["card"]
    kicker = f'<p class="kicker" data-fx="{HIT}">{esc(card["kicker"])}</p>' if card.get("kicker") else ""
    points = "".join(f'<li data-fx="{fx(("rise", at))}">{icon_badge("check")}'
                     f'<span data-fit="1" data-min="26">{rich(point)}</span></li>'
                     for point, at in zip(card.get("points", [])[:3], scene["cues"]))
    source = ""
    if card.get("sources"):
        entries = "  ·  ".join(f"{name} {link}" for name, link in card["sources"])
        source = (f'<footer class="source" data-fx="{fx(("fade", .9))}"><b>{esc(card.get("sources_label", "원문"))}</b>'
                  f'<span>{esc(entries)}</span></footer>')
    return (kicker + f'<div class="cta-head">{icon_badge(card.get("icon", "bookmark"), fx(("pop", .1), ("pulse", 1.3)))}'
            + title_lines(card["title"], "cta-title", [HIT], 60, None) + "</div>"
            + (f'<ul class="points">{points}</ul>' if points else "")
            + art(card.get("character"), fx(("pop", .45))) + source)


def media_html(scene: dict[str, Any], style: str, marks: str) -> str:
    slots = []
    for item in scene["items"]:
        window = f'{item["from"]:.3f},{item["to"]:.3f}'
        object_style = f'object-fit:{item["fit"]}'
        if item["type"] == "VIDEO":
            poster = f' poster="{item["poster_uri"]}"' if item.get("poster_uri") else ""
            visual = (f'<video class="media-visual" src="{item["uri"]}"{poster} muted playsinline preload="auto" '
                      f'data-media-video data-name="{esc(item["path"].name)}" data-media-time="{window}" '
                      f'style="{object_style}"></video><span class="media-progress"><i></i></span>')
        else:
            visual = (f'<img class="media-visual" src="{item["uri"]}" data-pan="{window}" '
                      f'style="{object_style}" alt="">')
        slots.append(f'<figure class="media-card" data-show="{window}">{visual}'
                     f'<figcaption><span>{esc(item["label"])}</span><b>실제 원글 미디어</b></figcaption></figure>')
    return f'<div class="media-stack">{"".join(slots)}</div>'


def board_html(scene: dict[str, Any], style: str, marks: str) -> str:
    """Every entry scene draws the whole board, so rows keep their places from cut to cut."""
    entries, now = scene["entries"], scene["index"]
    two = len(entries) > 6
    rows = []
    for number, entry in enumerate(entries, start=1):
        state = "done" if number - 1 < now else "now" if number - 1 == now else "todo"
        effect = f' data-fx="{fx(("pop", .02))}"' if state == "now" else ""
        rows.append(f'<li class="{state}"{effect}><b>{number}</b>'
                    f'<p data-fit="2" data-min="24">{rich(entry["title"])}</p></li>')
    layout = f' style="grid-template-rows:repeat({math.ceil(len(entries) / 2)},auto)"' if two else ""
    return f'<ol class="board{" two" if two else ""}"{layout} data-shrink>{"".join(rows)}</ol>'


KINDS = {"hook": hook_html, "media": media_html, "versus": versus_html, "rows": rows_html, "keyword": keyword_html,
         "prompt": prompt_html, "rank": rank_html, "cta": cta_html, "entry": board_html}


def captions_html(scene: dict[str, Any]) -> str:
    slots = []
    for number, (text, start, end) in enumerate(scene["captions"]):
        # The last caption stays up until the cut.
        until = scene["duration"] + 1 if number == len(scene["captions"]) - 1 else end
        slots.append(f'<div class="cap-slot" data-show="{start:.3f},{until:.3f}">'
                     f'<p class="cap" data-fit="2" data-min="30" data-fx="{fx(("cap", start))}">'
                     f'{caption_markup(text)}</p></div>')
    return f'<div class="caps">{"".join(slots)}</div>' if slots else ""


def document_html(spec: dict[str, Any], scenes: list[dict[str, Any]], style: str) -> str:
    cover = spec["cards"][0]
    pin_text = " ".join(lines_of(cover.get("title")))
    pin = f'<div class="pin display" data-fit="2" data-min="44">{rich(pin_text)}</div>'
    handle = (f'<header class="handle"><i></i>{esc(spec["handle"])}'
              f'<span>· {esc(spec.get("series", ""))}</span></header>')
    marks = icons.LIME if style == "bold" else icons.BLUE
    sections = []
    for index, scene in enumerate(scenes):
        classes = ["scene", scene["kind"]]
        if style == "bold" and index % 2:
            classes.append("alt")
        if scene["kind"] == "cta" and not scene["card"].get("points"):
            classes.append("empty")
        pinned = scene["kind"] not in {"hook", "cta"}
        sections.append(f'<section class="{" ".join(classes)}" data-start="{scene["start"]:.3f}" '
                        f'data-end="{scene["end"]:.3f}"><div class="grain"></div>{handle}{pin if pinned else ""}'
                        f'<div class="stage">{KINDS[scene["kind"]](scene, style, marks)}</div>'
                        f'{captions_html(scene)}</section>')
    style_css = (HERE / "reel.css").read_text(encoding="utf-8")
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{font_css()}{style_css}'
            f'{theme_css(spec.get("theme", DEFAULT_THEME))}</style></head><body class="reel-{style}">'
            f'{"".join(sections)}<script>{REEL_SCRIPT}</script></body></html>')


# ---------- Capture and encode ----------

def contact_sheet(frames: list[Image.Image], path: Path, columns: int = 6) -> Path:
    width, height, gap = 216, 384, 10
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGB", (min(len(frames), columns) * (width + gap) + gap, rows * (height + gap) + gap), "#d9d9d9")
    for index, frame in enumerate(frames):
        thumb = frame.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (gap + (index % columns) * (width + gap), gap + (index // columns) * (height + gap)))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path


def video_still(video: Path, moment: float) -> Image.Image:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{moment:.3f}", "-i", str(video),
                             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                            capture_output=True, check=True)
    return Image.open(io.BytesIO(result.stdout)).convert("RGB")


def proof_times(scenes: list[dict[str, Any]]) -> list[float]:
    """The first frame, each source-media item, then every other scene once it has settled."""
    moments = [0.0]
    for scene in scenes:
        if scene["kind"] == "media":
            moments.extend(scene["start"] + (item["from"] + item["to"]) / 2 for item in scene["items"])
        else:
            moments.append(max(scene["start"], scene["end"] - .12))
    return moments


def encode(browser: Browser, session: str, duration: float, output: Path, audio: Path | None) -> dict[str, int]:
    temporary = output.with_name(f".{output.stem}.partial-{os.getpid()}.mp4")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS),
               "-c:v", "mjpeg", "-i", "pipe:0"]
    if audio:
        command += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2"]
    command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-t", f"{duration:.3f}", "-movflags", "+faststart", str(temporary)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    frames = round(duration * FPS)
    captured, previous, image = 0, None, b""
    try:
        assert process.stdin is not None
        for number in range(frames):
            step = evaluate(browser, session, f"window.__seek({number / FPS:.4f})")
            # A still frame is reused only when nothing moves now and nothing moved in the last frame.
            if step["moving"] or step["state"] != previous or not image:
                image = screenshot(browser, session, WIDTH, HEIGHT, "jpeg")
                captured += 1
            previous = None if step["moving"] else step["state"]
            process.stdin.write(image)
    except BrokenPipeError:
        pass
    finally:
        if process.stdin:
            process.stdin.close()
    if process.wait() != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg가 릴스를 만들지 못했습니다")
    os.replace(temporary, output)
    return {"frames": frames, "captured": captured}


def inspect_video(path: Path, duration: float, has_audio: bool) -> dict[str, Any]:
    """Verify the encoded file, not just FFmpeg's exit code."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,r_frame_rate,nb_frames", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video or (video.get("width"), video.get("height")) != (WIDTH, HEIGHT):
        raise RuntimeError(f"릴스 해상도가 1080×1920이 아닙니다: {path}")
    rate = float(Fraction(video.get("r_frame_rate", "0/1")))
    actual = float(data.get("format", {}).get("duration", 0))
    if abs(rate - FPS) > .01 or abs(actual - duration) > .08:
        raise RuntimeError(f"릴스 길이 또는 FPS가 다릅니다: {actual:.3f}초, {rate:.3f}fps")
    if bool(audio) != has_audio:
        raise RuntimeError("릴스 오디오 스트림이 요청과 다릅니다")
    return {"width": WIDTH, "height": HEIGHT, "encoded_duration": actual, "encoded_fps": rate,
            "encoded_frames": int(video.get("nb_frames") or round(actual * rate)), "has_audio": bool(audio)}


def render(spec_path: Path, output: Path, style: str | None = None, *, stills_only: bool = False,
           audio: Path | None = None) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    validate(spec)
    style = style or spec.get("reel_style") or STYLES[0]
    if style not in STYLES:
        raise ValueError(f"릴스 스타일을 알 수 없습니다: {style} (가능: {', '.join(STYLES)})")
    media = resolve_media(spec_path, spec)
    scenes = timed_plan(spec, style, media)
    duration = round(scenes[-1]["end"], 3)
    output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"style": style, "theme": spec.get("theme", DEFAULT_THEME), "duration": duration,
                              "fps": FPS, "audio": str(audio) if audio else None, "source_media": len(media),
                              "scenes": [{"kind": scene["kind"], "start": round(scene["start"], 3),
                                          "end": round(scene["end"], 3),
                                          "captions": [plain(text) for text, _, _ in scene["captions"]]}
                                         for scene in scenes]}
    with tempfile.TemporaryDirectory(prefix="card-render-", dir=scratch_directory("reel-render")) as temporary, \
            Browser(Path(temporary) / "chrome-profile") as browser:
        page = Path(temporary) / "reel.html"
        page.write_text(document_html(spec, scenes, style), encoding="utf-8")
        session = new_page(browser, WIDTH, HEIGHT)
        layout = load(browser, session, page, "window.__reel")
        report["problems"] = ([] if layout["fonts"] else ["폰트 로드 실패"]) + layout["problems"]
        sheet = output.with_name(f"{output.stem}-proof.png")
        if stills_only:
            frames = []
            for moment in proof_times(scenes):
                evaluate(browser, session, f"window.__seek({moment:.4f})")
                frames.append(Image.open(io.BytesIO(screenshot(browser, session, WIDTH, HEIGHT))))
            report["proof"] = str(contact_sheet(frames, sheet))
        else:
            report.update(encode(browser, session, duration, output, audio))
            report.update(inspect_video(output, duration, bool(audio)))
            report["video"] = str(output)
    if not stills_only:
        report["proof"] = str(contact_sheet([video_still(output, moment) for moment in proof_times(scenes)], sheet))
    output.with_name(f"{output.stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                        encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="카드 스펙 JSON으로 9:16 릴스 MP4 만들기")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--style", choices=STYLES, help="기본값: 스펙의 reel_style, 없으면 band")
    parser.add_argument("--output", type=Path, help="기본값: 스펙 옆 reel-<스타일>.mp4")
    parser.add_argument("--stills", action="store_true", help="영상 없이 장면별 정지 화면만 빠르게 확인")
    parser.add_argument("--audio", type=Path, help="배경 음원 (기본은 무음)")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    style = args.style or spec.get("reel_style") or STYLES[0]
    output = args.output or args.spec.parent / f"reel-{style}.mp4"
    report = render(args.spec, output, style, stills_only=args.stills, audio=args.audio)
    print(json.dumps({key: report[key] for key in ("style", "duration", "problems", "proof")}
                     | ({"video": report["video"], "captured": report["captured"], "frames": report["frames"]}
                        if "video" in report else {}), ensure_ascii=False))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
