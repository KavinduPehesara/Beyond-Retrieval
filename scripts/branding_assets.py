"""Derive the interface's brand images from the two source files.

    python scripts/branding_assets.py

The source art is dark teal on transparency, which reads well on the light
palette and almost disappears on the dark one (#141d20). Rather than ship a
second hand-made file that can drift from the first, the dark variant is
computed: hue and saturation are kept, and lightness is lifted into the top
of the range so the mark stays legible without changing colour.

Everything here is written into assets/branding/ and is reproducible from
beyond-retrieval-logo-v1.png and beyond-retrieval-icon-v1.png alone.
"""

from __future__ import annotations

import colorsys
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "assets" / "branding"

LOGO_SRC = BRANDING / "beyond-retrieval-logo-v1.png"
ICON_SRC = BRANDING / "beyond-retrieval-icon-v1.png"

#: Lightness of the darkest ink in the dark-mode variant, and of the
#: lightest. The source runs roughly 0.13 to 0.75; mapping into this range
#: keeps the accent arc distinguishable from the body of the mark instead of
#: flattening both to one tone.
DARK_FLOOR, DARK_CEILING = 0.62, 0.90

#: Saturation is pulled down as lightness goes up. Keeping the source
#: saturation at the new lightness turns the mark mint-neon, which is not a
#: colour that appears anywhere else in this interface; the dark palette's
#: teal is #a4d7c3, and this lands next to it.
DARK_SATURATION = 0.5

#: Favicons are drawn at 16-32 px. 256 is enough for every tab and bookmark
#: size a browser asks for, and about 4% of the source file.
FAVICON = 256
#: The top bar draws the wordmark at roughly 210 px wide on a normal screen;
#: twice that keeps it sharp on a high-density display.
LOGO_WIDTH = 440


def trim(im: Image.Image) -> Image.Image:
    """Crop the transparent margin so a width in CSS means the ink's width."""
    box = im.getbbox()
    return im.crop(box) if box else im


def lighten(im: Image.Image) -> Image.Image:
    """Lift lightness into the dark-mode range, keeping hue and saturation.

    Works per pixel rather than by replacing one colour with another, so the
    anti-aliased edges stay smooth: a threshold would leave the mark jagged
    at the sizes it is actually drawn.
    """
    im = im.convert("RGBA")
    out = []
    for r, g, b, a in im.getdata():
        if a == 0:
            out.append((r, g, b, a))
            continue
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        l = DARK_FLOOR + (DARK_CEILING - DARK_FLOOR) * l
        nr, ng, nb = colorsys.hls_to_rgb(h, min(l, 1.0), s * DARK_SATURATION)
        out.append((round(nr * 255), round(ng * 255), round(nb * 255), a))
    lit = Image.new("RGBA", im.size)
    lit.putdata(out)
    return lit


def scaled(im: Image.Image, width: int) -> Image.Image:
    height = max(1, round(im.height * width / im.width))
    return im.resize((width, height), Image.LANCZOS)


def square(im: Image.Image, size: int) -> Image.Image:
    """Fit the mark inside a transparent square: a browser scales a favicon
    to a square box, and a non-square source would be squashed into it."""
    art = scaled(trim(im), size)
    if art.height > size:
        art = art.resize((max(1, round(art.width * size / art.height)), size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(art, ((size - art.width) // 2, (size - art.height) // 2), art)
    return canvas


def main() -> int:
    missing = [p.name for p in (LOGO_SRC, ICON_SRC) if not p.exists()]
    if missing:
        print("missing source art: " + ", ".join(missing), file=sys.stderr)
        return 1

    logo = trim(Image.open(LOGO_SRC).convert("RGBA"))
    icon = trim(Image.open(ICON_SRC).convert("RGBA"))

    written = [
        ("logo-light.png", scaled(logo, LOGO_WIDTH)),
        ("logo-dark.png", scaled(lighten(logo), LOGO_WIDTH)),
        ("icon-light.png", square(icon, FAVICON)),
        ("icon-dark.png", square(lighten(icon), FAVICON)),
    ]
    for name, im in written:
        path = BRANDING / name
        im.save(path, optimize=True)
        print(f"  {name:16} {im.width}x{im.height}  {path.stat().st_size / 1024:5.0f} KB")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
