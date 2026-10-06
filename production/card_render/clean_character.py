#!/usr/bin/env python3
"""Make a card-ready copy of the human character cutout.

The shared cutout in content/character has a see-through smudge at the bottom
of the shirt, and the rest of the figure is 254/255 opaque, so a colored card
shows through. This paints the smudge with the shirt's white, makes the drawn
figure fully opaque, and keeps the cutout's soft outline. The shared files are
left untouched.

    python3 clean_character.py   # writes assets/character-human.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
CUTOUT = HERE.parents[1] / "content" / "character" / "character-human-cutout.png"
OUTPUT = HERE / "assets" / "character-human.png"
EDGE = 3                 # outline pixels (from the outside) that keep the cutout's soft alpha
SHIRT = (253, 253, 253)  # the shirt's white, sampled next to the smudge
SMUDGE_ALPHA = 250       # inside the figure, anything more see-through than this is the smudge


def threshold(image: Image.Image, test) -> Image.Image:
    return image.point(lambda value: 255 if test(value) else 0)


def clean(cutout_path: Path = CUTOUT, output: Path = OUTPUT) -> Path:
    cutout = Image.open(cutout_path).convert("RGBA")
    width, height = cutout.size
    alpha = cutout.getchannel("A")

    # The figure is cropped at the bottom, so the smudge touches the bottom edge. Bottom-edge
    # pixels between the figure's outermost lines belong to the figure, not to the outside.
    bottom = [x for x in range(width) if alpha.getpixel((x, height - 1)) >= 128]
    first, last = (bottom[0], bottom[-1]) if bottom else (width, -1)
    seeds = [(x, 0) for x in range(width)]
    seeds += [(x, height - 1) for x in range(width) if not first <= x <= last]
    seeds += [(x, y) for y in range(height) for x in (0, width - 1)]
    clear = threshold(alpha, lambda value: value < 128)
    for point in seeds:
        if clear.getpixel(point) == 255:
            ImageDraw.floodfill(clear, point, 128)
    outside = threshold(clear, lambda value: value == 128)
    inside = ImageChops.invert(outside.filter(ImageFilter.MaxFilter(2 * EDGE + 1)))

    # The smudge: the see-through patch inside the figure that reaches the bottom edge.
    patch = ImageChops.multiply(inside, threshold(alpha, lambda value: value < SMUDGE_ALPHA))
    for x in range(first, last + 1):
        if patch.getpixel((x, height - 1)) == 255:
            ImageDraw.floodfill(patch, (x, height - 1), 128)
    smudge = threshold(patch, lambda value: value == 128).filter(ImageFilter.MaxFilter(5))
    # Its faint rim is a little grey too; repaint only light pixels so nearby lines stay intact.
    on_white = Image.new("RGBA", cutout.size, "white")
    on_white.alpha_composite(cutout)
    light = threshold(on_white.convert("L"), lambda value: value > 200)
    smudge = ImageChops.multiply(ImageChops.multiply(smudge, inside), light)

    result = cutout.copy()
    result.paste(Image.new("RGBA", cutout.size, (*SHIRT, 255)), mask=smudge)
    drawn = ImageChops.multiply(inside, threshold(alpha, lambda value: value >= 128))
    result.putalpha(ImageChops.lighter(result.getchannel("A"), drawn))
    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output, optimize=True)
    return output


if __name__ == "__main__":
    print(clean())
