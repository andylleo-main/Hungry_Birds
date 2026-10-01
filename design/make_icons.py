"""Regenerate every app icon from the logo master.

Needs Pillow. Run from the repository root:

    pip install pillow
    python3 design/make_icons.py

The master is design/logo-master.png: the supplied SVG traced, stripped of its
baked-in dark backdrop, cropped to the artwork and squared up. The crop is the
part that matters - the bird occupied a little over half the original canvas,
so without it the icon is a scattering of yellow specks at 48px.

The supplied logo.svg is deliberately NOT used at runtime. It is a VTracer
auto-trace of 2,848 paths weighing 1.1MB, which is several times the size of
the whole web bundle for a mark drawn at 40 pixels.
"""

import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, "design", "logo-master.png")
BG = (21, 19, 15, 255)  # #15130F, the artwork's own backdrop

# Legacy launcher icons: dp equals px at each density bucket.
LEGACY = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
# Adaptive foregrounds are a 108dp canvas at those same buckets.
ADAPTIVE = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}
# What the web app serves.
WEB = {"favicon.png": 32, "logo.png": 96, "apple-touch-icon.png": 180,
       "icon-192.png": 192, "icon-512.png": 512}


def _rounded(image: Image.Image, radius_ratio: float) -> Image.Image:
    size = image.size[0]
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size * 4 - 1, size * 4 - 1], radius=int(size * 4 * radius_ratio), fill=255
    )
    out = image.copy()
    out.putalpha(mask.resize((size, size), Image.LANCZOS))
    return out


def legacy(master: Image.Image, size: int) -> Image.Image:
    """Opaque and rounded: launchers draw a legacy icon exactly as given, so a
    transparent one leaves the bird floating with no shape behind it."""
    icon = Image.new("RGBA", (size, size), BG)
    art = master.resize((round(size * 0.88),) * 2, Image.LANCZOS)
    icon.paste(art, ((size - art.width) // 2,) * 2, art)
    return _rounded(icon, 0.22)


def foreground(master: Image.Image, size: int) -> Image.Image:
    """Transparent, art kept inside the adaptive-icon safe zone.

    Only the inner 72 of the 108dp canvas is guaranteed visible; the launcher
    masks the rest to a circle, squircle or teardrop. 62% leaves margin.
    """
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    art = master.resize((round(size * 0.62),) * 2, Image.LANCZOS)
    canvas.paste(art, ((size - art.width) // 2,) * 2, art)
    return canvas


def main() -> None:
    master = Image.open(MASTER).convert("RGBA")

    for app in ("merchant_app", "rider_app"):
        res = os.path.join(ROOT, "apps", app, "android", "app", "src", "main", "res")
        if not os.path.isdir(res):
            continue
        for bucket, size in LEGACY.items():
            legacy(master, size).save(f"{res}/mipmap-{bucket}/ic_launcher.png", optimize=True)
        for bucket, size in ADAPTIVE.items():
            foreground(master, size).save(
                f"{res}/mipmap-{bucket}/ic_launcher_foreground.png", optimize=True
            )
        print(f"  {app}: launcher icons")

    web = os.path.join(ROOT, "apps", "web", "public")
    for name, size in WEB.items():
        master.resize((size, size), Image.LANCZOS).save(f"{web}/{name}", optimize=True)
    print("  web: favicon, logo, touch icons")

    store = Image.new("RGB", (512, 512), BG[:3])
    art = master.resize((450, 450), Image.LANCZOS)
    store.paste(art, (31, 31), art)
    store.save(os.path.join(ROOT, "design", "play-store-icon-512.png"), optimize=True)
    print("  design: play-store-icon-512.png")


if __name__ == "__main__":
    main()
