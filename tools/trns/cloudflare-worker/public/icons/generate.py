"""Generate trns PWA icons (192 + 512 + maskable 512).

Design: rounded-square gradient (Inpriv primary #cbbeff → #8a7adf) with a
white "T" monogram. Uses Pillow only (already on the Inpriv tooling box).
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path

OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)

PRIMARY = (203, 190, 255)
PRIMARY_DEEP = (138, 122, 223)
WHITE = (244, 238, 250)


def gradient(size: int) -> Image.Image:
    """Diagonal linear gradient from PRIMARY to PRIMARY_DEEP."""
    g = Image.new("RGB", (size, size), PRIMARY)
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            r = int(PRIMARY[0] * (1 - t) + PRIMARY_DEEP[0] * t)
            gg = int(PRIMARY[1] * (1 - t) + PRIMARY_DEEP[1] * t)
            b = int(PRIMARY[2] * (1 - t) + PRIMARY_DEEP[2] * t)
            px[x, y] = (r, gg, b)
    return g


def round_mask(size: int, radius_frac: float = 0.22) -> Image.Image:
    """Rounded-square alpha mask, the shape used for Android adaptive icons."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    r = int(size * radius_frac)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=255)
    return m


def render_mono(draw: ImageDraw.ImageDraw, size: int, glyph: str = "T",
                weight: str = "bold") -> None:
    """Draw centred 'T' monogram. Falls back to a manual glyph if the bold
    font is unavailable on this box."""
    target_h = int(size * 0.50)
    font = None
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf",  # Segoe UI Bold
        r"C:\Windows\Fonts\arialbd.ttf",   # Arial Bold
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        try:
            font = ImageFont.truetype(path, target_h)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    # measure via textbbox
    bbox = draw.textbbox((0, 0), glyph, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (size - w) // 2 - bbox[0]
    y = int(size * 0.30) - bbox[1]
    draw.text((x, y), glyph, fill=WHITE, font=font)


def write(size: int, maskable: bool = False) -> Path:
    """Compose icon at `size`. Maskable variant uses a safe-zone radius."""
    radius_frac = 0.42 if maskable else 0.22  # adaptive safe zone
    img = gradient(size)
    draw = ImageDraw.Draw(img)

    # subtle inner glow ring
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(
        (size * 0.06, size * 0.06, size * 0.94, size * 0.94),
        radius=int(size * (radius_frac - 0.06)),
        outline=(255, 255, 255, 28),
        width=max(1, int(size * 0.008)),
    )
    img = Image.alpha_composite(img.convert("RGBA"), glow)

    # mono
    draw = ImageDraw.Draw(img)
    render_mono(draw, size)

    # apply rounded mask
    mask = round_mask(size, radius_frac=radius_frac)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)

    suffix = "-maskable" if maskable else ""
    path = OUT / (f"icon-{size}{suffix}.png")
    out.save(path, "PNG", optimize=True)
    return path


if __name__ == "__main__":
    p192 = write(192)
    p512 = write(512)
    p512m = write(512, maskable=True)
    print(f"wrote {p192}")
    print(f"wrote {p512}")
    print(f"wrote {p512m}")
