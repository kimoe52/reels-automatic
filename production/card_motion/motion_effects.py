"""Deterministic, source-pixel-safe entrance effects for card elements.

The effects in this module describe how an already-extracted raster element is
revealed.  They never describe text reconstruction, character deformation, or
continuous motion: every effect ends at the source pixels' native transform.
"""
from __future__ import annotations

from typing import Sequence


# Keep the legacy spellings first: saved plans may contain any of them.
EFFECTS = (
    "", "settle_fade", "rise_fade", "slide_left", "slide_right", "scale_pop",
    "reveal", "fade", "wipe_up", "wipe_down", "iris_reveal", "spring_settle",
    "bounce_settle", "path_arc", "gentle_tilt", "stepped_reveal",
)

_DURATIONS_MS = {
    "": 300, "settle_fade": 320, "rise_fade": 360, "slide_left": 340,
    "slide_right": 340, "scale_pop": 300, "reveal": 360, "fade": 240,
    "wipe_up": 360, "wipe_down": 360, "iris_reveal": 380,
    "spring_settle": 440, "bounce_settle": 420, "path_arc": 440,
    "gentle_tilt": 400, "stepped_reveal": 400,
}

_TEXT_ROLES = {"title", "text", "body", "copy", "caption", "headline", "label", "step"}
_PANEL_ROLES = {"panel", "layout", "card", "container", "list"}
_CHARACTER_ROLES = {"character", "person", "figure", "illustration", "art", "mascot"}
_PROP_ROLES = {"prop", "icon", "badge", "arrow", "chart", "graph", "decoration", "object"}


def duration_ms(effect: str) -> int:
    """Return an effect's bounded entrance duration in milliseconds.

    Unknown values deliberately fall back to the conservative settle fade, so
    a malformed plan cannot create a long or perpetual animation.
    """
    return min(600, _DURATIONS_MS.get(str(effect or ""), _DURATIONS_MS["settle_fade"]))


def _normalise_box(box: Sequence[int | float], canvas_size: Sequence[int | float]) -> tuple[float, float, float, float, float, float]:
    if len(box) != 4 or len(canvas_size) != 2:
        raise ValueError("box must be [x, y, width, height] and canvas_size must be [width, height]")
    x, y, width, height = (float(value) for value in box)
    canvas_width, canvas_height = (float(value) for value in canvas_size)
    if width <= 0 or height <= 0 or canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("box and canvas_size dimensions must be positive")
    return x, y, width, height, canvas_width, canvas_height


def choose_effect(role: str, box: Sequence[int | float], canvas_size: Sequence[int | float],
                  page_number: int = 1, index: int = 0) -> str:
    """Choose a stable, geometry-aware entrance effect without randomness.

    ``page_number`` and ``index`` only select among equivalently safe entries;
    they make an identical plan reproduce exactly and avoid a single repeated
    gesture across a card.
    """
    x, y, width, height, canvas_width, canvas_height = _normalise_box(box, canvas_size)
    key = str(role or "").strip().lower().replace("-", "_")
    variant = (int(page_number) * 17 + int(index) * 7 + int(x) + int(y)) % 3
    center_x = x + width / 2
    wide = width / canvas_width >= .48
    tall = height / canvas_height >= .24

    # Raster type remains a raster crop.  A clip-path reveal exposes its
    # existing pixels, rather than pretending to type/OCR/recompose glyphs.
    if key in _TEXT_ROLES:
        return ("reveal", "wipe_up", "stepped_reveal")[variant]
    if key in _PANEL_ROLES:
        if wide:
            return ("wipe_up", "wipe_down", "reveal")[variant]
        return "slide_left" if center_x < canvas_width / 2 else "slide_right"
    # People and character art are always a rigid body.  No bounce, elastic,
    # non-uniform scale, or large rotation is selected for them.
    if key in _CHARACTER_ROLES:
        if tall and variant == 2:
            return "gentle_tilt"
        if variant == 0:
            return "rise_fade"
        return "slide_left" if center_x < canvas_width / 2 else "slide_right"
    if key in _PROP_ROLES:
        return ("bounce_settle", "path_arc", "iris_reveal")[variant]
    return ("settle_fade", "rise_fade", "fade")[variant]


__all__ = ["EFFECTS", "choose_effect", "duration_ms"]
