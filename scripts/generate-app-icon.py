"""Regenerate the brand icon and multi-size ICO from master assets."""
import base64
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "apps/web/public/xya/brand"
SIZE = 256


def main():
    BRAND.mkdir(parents=True, exist_ok=True)
    png_path = BRAND / "app-icon.png"
    if not png_path.is_file():
        raise FileNotFoundError(f"Missing master brand asset: {png_path}")

    icon = Image.open(png_path).convert("RGBA")
    if icon.size != (SIZE, SIZE):
        icon = icon.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
        icon.save(png_path)

    # Multi-resolution Windows ICO: 16, 24, 32, 48, 64, 128, 256
    ico_path = ROOT / "apps/web/public/favicon.ico"
    icon.save(ico_path, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])

    # Self-contained SVG wrapper for crisp browser/web vector rendering
    png_b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
    (BRAND / "app-icon.svg").write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="100%" height="100%">
  <!-- Xianyu Pilot: Modern Obsidian Flagship Icon -->
  <defs>
    <clipPath id="squircleClip">
      <rect x="0" y="0" width="256" height="256" rx="56" ry="56"/>
    </clipPath>
  </defs>
  <image width="256" height="256" href="data:image/png;base64,{png_b64}"/>
</svg>
''', encoding="utf-8")


if __name__ == "__main__":
    main()
