"""Regenerate the transparent brand icon (development only; requires Pillow)."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "apps/web/public/xya/brand"
SCALE = 4
SIZE = 256


def capsule(start, end, top, bottom):
    mask = Image.new("L", (SIZE * SCALE, SIZE * SCALE))
    draw = ImageDraw.Draw(mask)
    radius = 32 * SCALE
    points = [(x * SCALE, y * SCALE) for x, y in (start, end)]
    draw.line(points, fill=255, width=radius * 2)
    for x, y in points:
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
    gradient = Image.new("RGBA", mask.size)
    draw = ImageDraw.Draw(gradient)
    for y in range(mask.height):
        ratio = y / (mask.height - 1)
        color = tuple(round(a + (b-a) * ratio) for a, b in zip(top, bottom))
        draw.line((0, y, mask.width, y), fill=(*color, 255))
    gradient.putalpha(mask)
    return gradient


def main():
    BRAND.mkdir(parents=True, exist_ok=True)
    icon = capsule((54, 52), (202, 204), (57, 143, 255), (5, 71, 212))
    icon = Image.alpha_composite(icon, capsule((202, 52), (54, 204), (102, 177, 255), (13, 107, 255)))
    icon = icon.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    icon.save(BRAND / "app-icon.png")
    icon.save(ROOT / "apps/web/public/favicon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    (BRAND / "app-icon.svg").write_text('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="back" x2="0" y2="1"><stop stop-color="#398fff"/><stop offset="1" stop-color="#0547d4"/></linearGradient>
    <linearGradient id="front" x2="0" y2="1"><stop stop-color="#66b1ff"/><stop offset="1" stop-color="#0d6bff"/></linearGradient>
  </defs>
  <path d="M54 52 202 204" fill="none" stroke="url(#back)" stroke-width="64" stroke-linecap="round"/>
  <path d="M202 52 54 204" fill="none" stroke="url(#front)" stroke-width="64" stroke-linecap="round"/>
</svg>
''', encoding="utf-8")


if __name__ == "__main__":
    main()
