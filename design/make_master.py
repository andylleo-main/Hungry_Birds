"""Rebuild design/logo-master.png from design/logo-source.jpg.

    pip install pillow
    python3 design/make_master.py      # then: python3 design/make_icons.py

The source is the supplied artwork on its own near-black backdrop (#15130F). The
master is that artwork with the backdrop removed, cropped and squared, and every
app icon is derived from it by make_icons.py.

Why this exists rather than a one-off edit: the first master was cut by keying on
the backdrop *colour*, and the bird's eyebrows are painted a near-black maroon
that the key could not tell apart from the backdrop. So the strip deleted them
too. On the dark backdrop nobody noticed - the hole showed the same colour the
eyebrow had been - but the icons are drawn on light surfaces and launcher masks,
where the bird came out with hollow brows and no angry expression at all. At 48px
it simply read as a blank-faced bird.

Two things fix it, and both matter:

  * The backdrop is identified by *reachability*, not colour. Only near-black
    pixels connected to the image border are background; near-black enclosed by
    artwork is paint. That alone keeps the bag's ink and the bird's inner lines.

  * The tolerance is tight (12, not 42). The backdrop is a neutral #15130F and
    the brows are a red-tinted rgb(16,0,0); a loose tolerance merges them, and
    then the flood reaches the brows through the head's silhouette edge where the
    two genuinely touch. 12 separates them while still clearing the backdrop.

Both numbers are load-bearing. Widening either brings the hollow brows back.
"""

import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "design", "logo-source.jpg")
MASTER = os.path.join(ROOT, "design", "logo-master.png")

BACKDROP = (21, 19, 15)  # #15130F
# See the module docstring: 12 separates the backdrop from the brows, 42 does not.
TOLERANCE = 12


def _backdrop_alpha(src: Image.Image) -> Image.Image:
    """Alpha that is 0 on the backdrop and 255 on the artwork."""
    w, h = src.size
    px = src.load()

    near = Image.new("L", (w, h), 0)
    np = near.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if (
                abs(r - BACKDROP[0]) <= TOLERANCE
                and abs(g - BACKDROP[1]) <= TOLERANCE
                and abs(b - BACKDROP[2]) <= TOLERANCE
            ):
                np[x, y] = 255

    # Only the near-black that reaches a border is background. Everything else -
    # the eyebrows, the bag's lettering, the bird's inner lines - is paint.
    flooded = near.copy()
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if flooded.getpixel(seed) == 255:
            ImageDraw.floodfill(flooded, seed, 128)

    alpha = flooded.point(lambda v: 0 if v == 128 else 255)
    # JPEG ringing leaves specks in the backdrop. A 3px open clears them; the
    # artwork is everywhere far thicker than that, so nothing real is lost.
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    # Soften the cut, or the silhouette is a staircase once it is scaled to 48px.
    return alpha.filter(ImageFilter.GaussianBlur(0.6))


def main() -> None:
    src = Image.open(SOURCE).convert("RGB")
    alpha = _backdrop_alpha(src)

    art = src.convert("RGBA")
    art.putalpha(alpha)

    # Crop to the artwork. Without this the bird occupies a little over half the
    # canvas and the icon is a scattering of specks at 48px.
    bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    art = art.crop(bbox)

    side = max(art.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(art, ((side - art.width) // 2, (side - art.height) // 2))
    square.save(MASTER, optimize=True)
    print(f"  design/logo-master.png: {side}x{side} from {bbox}")
    print("  now run: python3 design/make_icons.py")


if __name__ == "__main__":
    main()
