"""Vector illustrations for code-rendered cards.

Every picture here is drawn as SVG, so a card never depends on an image model
to spell Korean text or to keep a layout aligned.
"""

from __future__ import annotations

import itertools
import math
from typing import Callable

# Theme colors come from CSS variables, so every drawing follows the card's theme.
INK = "var(--ink)"
BLUE = "var(--accent)"
LIME = "var(--marker)"
GRAY = "#8d929b"
DARK_GRAY = "#6b7079"
FOLD = "#9aa0a8"
WHITE = "#ffffff"

_ids = itertools.count(1)


def svg(view_box: str, body: str, css_class: str = "icon") -> str:
    return (f'<svg class="{css_class}" viewBox="{view_box}" xmlns="http://www.w3.org/2000/svg" '
            f'aria-hidden="true">{body}</svg>')


def _point(x: float, y: float) -> str:
    return f"{x:.1f},{y:.1f}"


def _head(end: tuple[float, float], direction: tuple[float, float], length: float, half: float) -> str:
    """Triangle whose base is centered on `end` and whose tip follows `direction`."""
    dx, dy = direction
    norm = math.hypot(dx, dy)
    dx, dy = dx / norm, dy / norm
    px, py = -dy, dx
    x, y = end
    return " ".join((_point(x + dx * length, y + dy * length),
                     _point(x + px * half, y + py * half),
                     _point(x - px * half, y - py * half)))


def marks(color: str = BLUE, css_class: str = "marks") -> str:
    """Three short strokes that point at an emphasized word."""
    body = (f'<g stroke="{color}" stroke-width="9" stroke-linecap="round" fill="none">'
            '<path d="M12 34 L30 8"/><path d="M20 53 L58 41"/><path d="M20 71 L52 85"/></g>')
    return svg("0 0 66 94", body, css_class)


def rays(side: str = "right", color: str = LIME, css_class: str = "rays") -> str:
    shapes = {
        "up": '<path d="M50 6 V32"/><path d="M18 16 L31 37"/><path d="M82 16 L69 37"/>',
        "left": '<path d="M42 8 L52 34"/><path d="M8 32 L34 46"/>',
        "right": '<path d="M50 8 L40 34"/><path d="M84 32 L58 46"/>',
    }
    view = "0 0 100 42" if side == "up" else "0 0 92 54"
    body = f'<g stroke="{color}" stroke-width="10" stroke-linecap="round" fill="none">{shapes[side]}</g>'
    return svg(view, body, css_class)


def bulb(color: str = BLUE, ray_color: str = BLUE, css_class: str = "bulb") -> str:
    body = (f'<g stroke="{ray_color}" stroke-width="7" stroke-linecap="round">'
            '<path d="M48 5 V19"/><path d="M17 15 L26 26"/><path d="M79 15 L70 26"/></g>'
            f'<path d="M48 31 C28 31 16 45 16 62 C16 75 24 83 31 91 L31 99 L65 99 L65 91 '
            f'C72 83 80 75 80 62 C80 45 68 31 48 31 Z" fill="{color}"/>'
            f'<rect x="33" y="105" width="30" height="7" rx="3.5" fill="{color}"/>'
            f'<rect x="37" y="116" width="22" height="7" rx="3.5" fill="{color}"/>')
    return svg("0 0 96 126", body, css_class)


def roads(css_class: str = "roads") -> str:
    """A straight blue road between two curving roads: choosing the next move."""
    left = "M234 592 C272 502 262 412 150 348"
    right = "M426 592 C388 502 398 412 510 348"
    left_head = _head((150, 348), (150 - 262, 348 - 412), 106, 100)
    right_head = _head((510, 348), (510 - 398, 348 - 412), 106, 100)
    blur = f"blur{next(_ids)}"
    body = (f'<defs><filter id="{blur}" x="-20%" y="-80%" width="140%" height="260%">'
            f'<feGaussianBlur stdDeviation="9"/></filter></defs>'
            f'<ellipse cx="330" cy="606" rx="300" ry="20" fill="{INK}" opacity=".16" filter="url(#{blur})"/>'
            f'<path d="{left}" stroke="{INK}" stroke-width="104" fill="none"/>'
            f'<polygon points="{left_head}" fill="{INK}"/>'
            f'<path d="{left}" stroke="{WHITE}" stroke-width="13" stroke-dasharray="30 26" fill="none"/>'
            f'<path d="{right}" stroke="{INK}" stroke-width="104" fill="none"/>'
            f'<polygon points="{right_head}" fill="{INK}"/>'
            f'<path d="{right}" stroke="{WHITE}" stroke-width="13" stroke-dasharray="30 26" fill="none"/>'
            f'<path d="M194 606 C262 562 276 502 276 422 L276 198 L210 198 L330 64 L450 198 L384 198 '
            f'L384 422 C384 502 398 562 466 606 Z" fill="{BLUE}"/>'
            f'<path d="M330 590 V228" stroke="{WHITE}" stroke-width="15" stroke-dasharray="36 30"/>'
            f'<g stroke="{LIME}" stroke-width="12" stroke-linecap="round">'
            '<path d="M330 6 V42"/><path d="M262 24 L284 58"/><path d="M398 24 L376 58"/></g>')
    return svg("0 0 660 624", body, css_class)


def clipboard(css_class: str = "clipboard") -> str:
    rows = []
    for index, y in enumerate((106, 192, 278)):
        box = BLUE if index == 0 else DARK_GRAY
        line = BLUE if index == 0 else GRAY
        outline = f' stroke="{INK}" stroke-width="7"' if index == 0 else ""
        rows.append(f'<rect x="56" y="{y}" width="64" height="64" rx="12" fill="{box}"{outline}/>')
        rows.append(f'<path d="M148 {y + 16} H266" stroke="{line}" stroke-width="12" stroke-linecap="round"/>')
        rows.append(f'<path d="M148 {y + 46} H232" stroke="{line}" stroke-width="12" stroke-linecap="round"'
                    f' opacity=".72"/>')
    check = (f'<path d="M70 139 L84 153 L108 122" stroke="{WHITE}" stroke-width="10" '
             'stroke-linecap="round" stroke-linejoin="round" fill="none"/>')
    body = (f'<rect x="34" y="60" width="290" height="322" rx="30" fill="{INK}"/>'
            f'<rect x="18" y="44" width="290" height="322" rx="30" fill="{WHITE}" stroke="{INK}" stroke-width="9"/>'
            f'<rect x="112" y="14" width="102" height="58" rx="16" fill="#a7acb5" stroke="{INK}" stroke-width="8"/>'
            f'<circle cx="163" cy="37" r="7" fill="{INK}" opacity=".3"/>' + "".join(rows) + check)
    return svg("0 0 340 394", body, css_class)


def document(css_class: str = "icon") -> str:
    lines = "".join(f'<path d="M58 {y} H{end}"/>' for y, end in
                    ((174, 204), (204, 204), (234, 162), (264, 204), (294, 140)))
    body = (f'<path d="M30 24 H176 L232 80 V322 H30 Z" fill="{WHITE}" stroke="{INK}" stroke-width="10" '
            'stroke-linejoin="round"/>'
            f'<path d="M176 24 V80 H232 Z" fill="{FOLD}" stroke="{INK}" stroke-width="10" stroke-linejoin="round"/>'
            f'<rect x="58" y="62" width="74" height="74" rx="4" fill="{BLUE}"/>'
            f'<g stroke="{GRAY}" stroke-width="11" stroke-linecap="round">'
            f'<path d="M154 84 H200"/><path d="M154 112 H192"/>{lines}</g>')
    return svg("0 0 262 346", body, css_class)


def decision(css_class: str = "icon") -> str:
    boxes = []
    for index, x in enumerate((8, 150, 292)):
        square = BLUE if index == 1 else DARK_GRAY
        boxes.append(f'<rect x="{x}" y="262" width="118" height="74" rx="12" fill="{WHITE}" '
                     f'stroke="{INK}" stroke-width="8"/>'
                     f'<rect x="{x + 18}" y="284" width="30" height="30" rx="4" fill="{square}"/>'
                     f'<path d="M{x + 62} 290 H{x + 98} M{x + 62} 308 H{x + 90}" stroke="{GRAY}" '
                     'stroke-width="8" stroke-linecap="round"/>')
    body = (f'<rect x="124" y="8" width="170" height="72" rx="12" fill="{WHITE}" stroke="{INK}" stroke-width="8"/>'
            f'<path d="M150 34 H266 M150 55 H236" stroke="{GRAY}" stroke-width="9" stroke-linecap="round"/>'
            f'<g stroke="{INK}" stroke-width="8" fill="none" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M209 80 V110"/><path d="M151 170 H67 V246"/><path d="M209 228 V246"/>'
            '<path d="M267 170 H351 V246"/>'
            '<path d="M53 234 L67 250 L81 234"/><path d="M195 234 L209 250 L223 234"/>'
            '<path d="M337 234 L351 250 L365 234"/></g>'
            f'<path d="M209 110 L268 169 L209 228 L150 169 Z" fill="{BLUE}" stroke="{INK}" stroke-width="8" '
            'stroke-linejoin="round"/>'
            f'<text x="209" y="194" text-anchor="middle" font-family="Pretendard" font-weight="900" '
            f'font-size="70" fill="{WHITE}">?</text>'
            f'<g stroke="{LIME}" stroke-width="9" stroke-linecap="round">'
            '<path d="M112 128 L132 144"/><path d="M104 160 L128 162"/>'
            '<path d="M306 128 L286 144"/><path d="M314 160 L290 162"/></g>' + "".join(boxes))
    return svg("0 0 418 344", body, css_class)


def alert_document(css_class: str = "icon") -> str:
    body = (f'<path d="M26 14 H124 L166 56 V214 H26 Z" fill="{WHITE}" stroke="{INK}" stroke-width="9" '
            'stroke-linejoin="round"/>'
            f'<path d="M124 14 V56 H166" fill="none" stroke="{INK}" stroke-width="9" stroke-linejoin="round"/>'
            f'<g stroke="{GRAY}" stroke-width="10" stroke-linecap="round">'
            '<path d="M52 82 H122"/><path d="M52 112 H112"/><path d="M52 142 H100"/></g>'
            f'<circle cx="156" cy="182" r="44" fill="{BLUE}"/>'
            f'<rect x="150" y="150" width="12" height="40" rx="6" fill="{WHITE}"/>'
            f'<circle cx="156" cy="206" r="7.5" fill="{WHITE}"/>'
            f'<g stroke="{BLUE}" stroke-width="8" stroke-linecap="round">'
            '<path d="M190 16 L176 38"/><path d="M210 44 L186 54"/></g>')
    return svg("0 0 214 232", body, css_class)


def _gear_path(center: float, outer: float, inner: float, teeth: int = 8) -> str:
    step = 2 * math.pi / teeth
    half = step * .21

    def polar(radius: float, angle: float) -> str:
        return _point(center + radius * math.cos(angle), center + radius * math.sin(angle))

    parts = []
    for index in range(teeth):
        angle = index * step - math.pi / 2
        start = polar(inner, angle - half * 1.45)
        parts.append(f"M{start}" if index == 0 else f"A{inner} {inner} 0 0 1 {start}")
        parts.append(f"L{polar(outer, angle - half)} A{outer} {outer} 0 0 1 {polar(outer, angle + half)} "
                     f"L{polar(inner, angle + half * 1.45)}")
    first = polar(inner, -math.pi / 2 - half * 1.45)
    parts.append(f"A{inner} {inner} 0 0 1 {first} Z")
    return " ".join(parts)


def gear(color: str = INK, text: str | None = None, css_class: str = "icon") -> str:
    path = _gear_path(110, 104, 82)
    if text:
        body = (f'<path d="{path}" fill="{color}"/>'
                f'<text x="110" y="136" text-anchor="middle" font-family="Pretendard" font-weight="900" '
                f'font-size="{max(34, 78 - 8 * len(text))}" letter-spacing="-2" fill="{WHITE}">{text}</text>')
    else:
        hole = "M144 110 A34 34 0 1 0 76 110 A34 34 0 1 0 144 110 Z"
        body = f'<path d="{path} {hole}" fill="{color}" fill-rule="evenodd"/>'
    return svg("0 0 220 220", body, css_class)


def flag(css_class: str = "icon") -> str:
    clip = f"flag{next(_ids)}"
    shape = "M60 26 C98 10 128 44 180 28 L170 124 C124 140 96 106 50 120 Z"
    squares = []
    for row in range(4):
        for column in range(5):
            if (row + column) % 2 == 0:
                squares.append(f'<rect x="{40 + column * 30}" y="{10 + row * 30}" width="30" height="30" '
                               f'fill="{INK}" transform="skewY(-6)"/>')
    body = (f'<defs><clipPath id="{clip}"><path d="{shape}"/></clipPath></defs>'
            f'<path d="M58 18 L28 204" stroke="{BLUE}" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="{shape}" fill="{WHITE}"/>'
            f'<g clip-path="url(#{clip})">{"".join(squares)}</g>'
            f'<path d="{shape}" fill="none" stroke="{INK}" stroke-width="8" stroke-linejoin="round"/>'
            f'<g stroke="{LIME}" stroke-width="9" stroke-linecap="round">'
            '<path d="M190 10 L178 32"/><path d="M204 44 L184 52"/></g>')
    return svg("0 0 214 212", body, css_class)


def list_doc(css_class: str = "icon") -> str:
    rows = []
    for index, y in enumerate((42, 102, 162)):
        fill = BLUE if index == 0 else DARK_GRAY
        rows.append(f'<rect x="36" y="{y}" width="40" height="40" rx="6" fill="{fill}"/>'
                    f'<path d="M96 {y + 10} H168 M96 {y + 30} H148" stroke="{GRAY}" stroke-width="9" '
                    'stroke-linecap="round"/>')
    body = (f'<rect x="10" y="10" width="186" height="210" rx="20" fill="{WHITE}" stroke="{INK}" stroke-width="10"/>'
            + "".join(rows)
            + f'<g stroke="{LIME}" stroke-width="9" stroke-linecap="round">'
              '<path d="M-16 4 L-2 22"/><path d="M-28 36 L-6 40"/></g>')
    return svg("-34 0 240 230", body, css_class)


def window_check(css_class: str = "icon") -> str:
    body = (f'<rect x="10" y="10" width="206" height="186" rx="18" fill="{WHITE}" stroke="{INK}" stroke-width="10"/>'
            f'<path d="M10 28 A18 18 0 0 1 28 10 H198 A18 18 0 0 1 216 28 V48 H10 Z" fill="{INK}"/>'
            f'<g fill="{WHITE}"><circle cx="36" cy="30" r="6"/><circle cx="56" cy="30" r="6"/>'
            '<circle cx="76" cy="30" r="6"/></g>'
            f'<circle cx="113" cy="122" r="54" fill="{LIME}"/>'
            f'<path d="M88 122 L106 140 L140 104" stroke="{WHITE}" stroke-width="15" stroke-linecap="round" '
            'stroke-linejoin="round" fill="none"/>'
            f'<g stroke="{LIME}" stroke-width="9" stroke-linecap="round">'
            '<path d="M226 -6 L214 16"/><path d="M244 24 L222 32"/></g>')
    return svg("0 -14 252 220", body, css_class)


def retry(css_class: str = "glyph") -> str:
    def point(angle: float) -> tuple[float, float]:
        radian = math.radians(angle)
        return 60 + 36 * math.cos(radian), 60 + 36 * math.sin(radian)

    parts = []
    for start, end in ((200, 322), (20, 142)):
        (x1, y1), (x2, y2) = point(start), point(end)
        tangent = (-math.sin(math.radians(end)), math.cos(math.radians(end)))
        parts.append(f'<path d="M{x1:.1f} {y1:.1f} A36 36 0 0 1 {x2:.1f} {y2:.1f}" stroke="{WHITE}" '
                     'stroke-width="13" fill="none" stroke-linecap="round"/>')
        parts.append(f'<polygon points="{_head((x2, y2), tangent, 20, 17)}" fill="{WHITE}" '
                     'stroke="#fff" stroke-width="3" stroke-linejoin="round"/>')
    return svg("0 0 120 120", "".join(parts), css_class)


def branch(css_class: str = "glyph") -> str:
    body = (f'<circle cx="60" cy="28" r="15" fill="{WHITE}"/>'
            f'<path d="M60 42 V58 M30 58 H90 M30 58 V72 M90 58 V72" stroke="{WHITE}" stroke-width="9" '
            'stroke-linecap="round" fill="none"/>'
            f'<rect x="14" y="72" width="32" height="30" rx="6" fill="{WHITE}"/>'
            f'<rect x="74" y="72" width="32" height="30" rx="6" fill="{WHITE}"/>')
    return svg("0 0 120 120", body, css_class)


def search_doc(css_class: str = "glyph") -> str:
    body = (f'<rect x="18" y="14" width="62" height="84" rx="9" fill="{WHITE}"/>'
            f'<path d="M30 34 H66 M30 50 H66 M30 66 H50" stroke="{BLUE}" stroke-width="8" stroke-linecap="round"/>'
            f'<circle cx="78" cy="80" r="19" fill="{BLUE}" stroke="{WHITE}" stroke-width="9"/>'
            f'<path d="M92 94 L106 108" stroke="{WHITE}" stroke-width="11" stroke-linecap="round"/>')
    return svg("0 0 120 120", body, css_class)


def arrow_down(css_class: str = "arrow-down") -> str:
    return svg("0 0 90 70", f'<polygon points="30,0 60,0 60,28 86,28 45,68 4,28 30,28" fill="{BLUE}"/>', css_class)


def arrow_right(css_class: str = "arrow-right") -> str:
    return svg("0 0 92 80", f'<polygon points="0,24 46,24 46,2 90,40 46,78 46,56 0,56" fill="{BLUE}"/>', css_class)


def loop_arrow(width: float, left: float, right: float, css_class: str = "loop-svg") -> str:
    """U-turn from the last column back into the first one."""
    body = (f'<path d="M{right:.1f} 0 V70 Q{right:.1f} 100 {right - 30:.1f} 100 H{left + 30:.1f} '
            f'Q{left:.1f} 100 {left:.1f} 70 V46" stroke="{BLUE}" stroke-width="26" fill="none" '
            'stroke-linejoin="round"/>'
            f'<polygon points="{left:.1f},2 {left - 40:.1f},50 {left + 40:.1f},50" fill="{BLUE}"/>')
    return svg(f"0 0 {width:.0f} 116", body, css_class)


def fork(count: int, width: float, css_class: str = "fork-svg") -> str:
    """A bracket that fans one decision out to `count` option chips."""
    gap = 20
    chip = (width - gap * (count - 1)) / count
    centers = [chip / 2 + index * (chip + gap) for index in range(count)]
    middle = width / 2
    first, last = centers[0], centers[-1]
    lines = [f'M{first:.1f} 50 V26 Q{first:.1f} 14 {first + 12:.1f} 14 H{middle - 12:.1f} '
             f'Q{middle:.1f} 14 {middle:.1f} 2 Q{middle:.1f} 14 {middle + 12:.1f} 14 H{last - 12:.1f} '
             f'Q{last:.1f} 14 {last:.1f} 26 V50']
    lines += [f"M{center:.1f} 14 V50" for center in centers[1:-1]]
    heads = "".join(f'<path d="M{center - 11:.1f} 40 L{center:.1f} 52 L{center + 11:.1f} 40"/>' for center in centers)
    body = (f'<g stroke="{BLUE}" stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="{" ".join(lines)}"/>{heads}</g>')
    return svg(f"0 0 {width:.0f} 56", body, css_class)


def _glyph(body: str, css_class: str) -> str:
    """White pictogram meant to sit on an accent-colored circle."""
    return svg("0 0 120 120", body, css_class)


def chat(css_class: str = "glyph") -> str:
    return _glyph(f'<path d="M24 26 H96 A12 12 0 0 1 108 38 V74 A12 12 0 0 1 96 86 H56 L34 104 V86 H24 '
                  f'A12 12 0 0 1 12 74 V38 A12 12 0 0 1 24 26 Z" fill="{WHITE}"/>'
                  f'<g fill="{BLUE}"><circle cx="40" cy="56" r="7"/><circle cx="60" cy="56" r="7"/>'
                  '<circle cx="80" cy="56" r="7"/></g>', css_class)


def image(css_class: str = "glyph") -> str:
    return _glyph(f'<rect x="16" y="24" width="88" height="72" rx="12" fill="none" stroke="{WHITE}" stroke-width="9"/>'
                  f'<path d="M24 88 L50 58 L66 74 L78 62 L98 88 Z" fill="{WHITE}"/>'
                  f'<circle cx="82" cy="44" r="9" fill="{WHITE}"/>', css_class)


def video(css_class: str = "glyph") -> str:
    return _glyph(f'<rect x="14" y="26" width="92" height="68" rx="16" fill="{WHITE}"/>'
                  f'<polygon points="52,44 52,76 80,60" fill="{BLUE}"/>', css_class)


def code(css_class: str = "glyph") -> str:
    return _glyph(f'<g stroke="{WHITE}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" fill="none">'
                  '<path d="M42 38 L20 60 L42 82"/><path d="M78 38 L100 60 L78 82"/><path d="M68 30 L52 90"/></g>',
                  css_class)


def bolt(css_class: str = "glyph") -> str:
    return _glyph(f'<polygon points="68,10 28,66 56,66 46,110 92,50 64,50 76,10" fill="{WHITE}"/>', css_class)


def lock(css_class: str = "glyph") -> str:
    return _glyph(f'<path d="M40 56 V42 A20 20 0 0 1 80 42 V56" stroke="{WHITE}" stroke-width="10" fill="none"/>'
                  f'<rect x="28" y="54" width="64" height="50" rx="12" fill="{WHITE}"/>'
                  f'<circle cx="60" cy="74" r="7" fill="{BLUE}"/><rect x="56" y="76" width="8" height="14" rx="3" fill="{BLUE}"/>',
                  css_class)


def folder(css_class: str = "glyph") -> str:
    return _glyph(f'<path d="M14 38 A10 10 0 0 1 24 28 H48 L60 40 H96 A10 10 0 0 1 106 50 V88 A10 10 0 0 1 96 98 '
                  f'H24 A10 10 0 0 1 14 88 Z" fill="{WHITE}"/>', css_class)


def star(css_class: str = "glyph") -> str:
    points = []
    for index in range(10):
        radius = 48 if index % 2 == 0 else 20
        angle = math.radians(-90 + index * 36)
        points.append(_point(60 + radius * math.cos(angle), 64 + radius * math.sin(angle)))
    return _glyph(f'<polygon points="{" ".join(points)}" fill="{WHITE}" stroke="{WHITE}" stroke-width="4" '
                  'stroke-linejoin="round"/>', css_class)


def clock(css_class: str = "glyph") -> str:
    return _glyph(f'<circle cx="60" cy="60" r="40" stroke="{WHITE}" stroke-width="10" fill="none"/>'
                  f'<path d="M60 60 V36 M60 60 L78 70" stroke="{WHITE}" stroke-width="9" stroke-linecap="round"/>',
                  css_class)


def pencil(css_class: str = "glyph") -> str:
    return _glyph(f'<polygon points="26,94 32,74 80,26 94,40 46,88" fill="{WHITE}" stroke="{WHITE}" stroke-width="4" '
                  f'stroke-linejoin="round"/><path d="M70 36 L84 50" stroke="{BLUE}" stroke-width="6"/>', css_class)


def globe(css_class: str = "glyph") -> str:
    return _glyph(f'<g stroke="{WHITE}" fill="none"><circle cx="60" cy="60" r="40" stroke-width="9"/>'
                  '<ellipse cx="60" cy="60" rx="18" ry="40" stroke-width="7"/><path d="M20 60 H100" stroke-width="7"/></g>',
                  css_class)


def mic(css_class: str = "glyph") -> str:
    return _glyph(f'<rect x="44" y="14" width="32" height="56" rx="16" fill="{WHITE}"/>'
                  f'<g stroke="{WHITE}" stroke-width="9" stroke-linecap="round" fill="none">'
                  '<path d="M30 58 A30 30 0 0 0 90 58"/><path d="M60 88 V104 M44 104 H76"/></g>', css_class)


def bookmark(css_class: str = "glyph") -> str:
    return _glyph(f'<path d="M34 16 H86 A6 6 0 0 1 92 22 V106 L60 84 L28 106 V22 A6 6 0 0 1 34 16 Z" fill="{WHITE}"/>',
                  css_class)


def check(css_class: str = "glyph") -> str:
    return _glyph(f'<path d="M28 62 L50 84 L92 38" stroke="{WHITE}" stroke-width="14" stroke-linecap="round" '
                  'stroke-linejoin="round" fill="none"/>', css_class)


def moon(css_class: str = "glyph") -> str:
    return _glyph(f'<path d="M74 16 A44 44 0 1 0 104 80 A36 36 0 1 1 74 16 Z" fill="{WHITE}"/>', css_class)


def drop(css_class: str = "glyph") -> str:
    return _glyph(f'<path d="M60 12 C60 12 26 52 26 76 A34 34 0 0 0 94 76 C94 52 60 12 60 12 Z" fill="{WHITE}"/>'
                  f'<path d="M44 78 A16 16 0 0 0 58 94" stroke="{BLUE}" stroke-width="6" stroke-linecap="round" fill="none"/>',
                  css_class)


def shapes(css_class: str = "glyph") -> str:
    return _glyph(f'<g fill="{WHITE}"><circle cx="38" cy="40" r="20"/><rect x="64" y="20" width="38" height="38" rx="6"/>'
                  '<polygon points="60,62 96,106 24,106"/></g>', css_class)


def cloud(css_class: str = "glyph") -> str:
    return _glyph(f'<path d="M34 92 A22 22 0 0 1 32 48 A28 28 0 0 1 86 40 A26 26 0 0 1 90 92 Z" fill="{WHITE}"/>',
                  css_class)


def copy(css_class: str = "copy-icon") -> str:
    return svg("0 0 48 48", '<g stroke="currentColor" stroke-width="4" fill="none" stroke-linejoin="round">'
                            '<rect x="14" y="14" width="26" height="28" rx="5"/>'
                            '<path d="M8 32 V10 A4 4 0 0 1 12 6 H30"/></g>', css_class)


def hand_arrow(css_class: str = "hand-arrow") -> str:
    """A hand-drawn marker arrow, the pointing device seen on reference covers."""
    return svg("0 0 200 170", f'<g stroke="{LIME}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round" '
                              'fill="none"><path d="M18 26 C80 6 150 34 158 122"/>'
                              '<path d="M130 108 L158 132 L178 98"/></g>', css_class)


GLYPHS = {"retry", "branch", "search_doc", "chat", "image", "video", "code", "bolt", "lock", "folder", "star",
          "clock", "pencil", "globe", "mic", "bookmark", "check", "moon", "drop", "shapes", "cloud"}

DRAWINGS: dict[str, Callable[..., str]] = {
    "chat": chat, "image": image, "video": video, "code": code, "bolt": bolt, "lock": lock,
    "folder": folder, "star": star, "clock": clock, "pencil": pencil, "globe": globe, "mic": mic,
    "bookmark": bookmark, "check": check, "moon": moon, "drop": drop, "shapes": shapes, "cloud": cloud,
    "copy": copy, "hand_arrow": hand_arrow,
    "document": document,
    "decision": decision,
    "alert_document": alert_document,
    "gear": gear,
    "flag": flag,
    "list_doc": list_doc,
    "window_check": window_check,
    "retry": retry,
    "branch": branch,
    "search_doc": search_doc,
    "clipboard": clipboard,
    "roads": roads,
}


def draw(name: str, css_class: str = "icon", **options: str) -> str:
    try:
        drawing = DRAWINGS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown illustration: {name}") from exc
    return drawing(css_class=css_class, **options)
