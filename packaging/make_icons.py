from pathlib import Path
import platform
import subprocess

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "icons"
OUT.mkdir(parents=True, exist_ok=True)


def render(size: int) -> Image.Image:
    scale = size / 512
    image = Image.new("RGBA", (size, size), "#09111d")
    draw = ImageDraw.Draw(image)
    margin = int(48 * scale)
    draw.rounded_rectangle((margin, margin, size - margin, size - margin), radius=int(84 * scale), fill="#09111d")
    diamond = [(size // 2, int(116 * scale)), (int(396 * scale), size // 2),
               (size // 2, int(396 * scale)), (int(116 * scale), size // 2)]
    draw.line(diamond + [diamond[0]], fill="#b7a8ff", width=max(2, int(14 * scale)), joint="curve")
    draw.ellipse((int(45 * scale), int(175 * scale), int(467 * scale), int(337 * scale)),
                 outline="#71e4ef", width=max(2, int(12 * scale)))
    draw.ellipse((int(420 * scale), int(155 * scale), int(454 * scale), int(189 * scale)), fill="#71e4ef")
    try:
        font = ImageFont.truetype("arial.ttf", int(96 * scale))
    except OSError:
        font = ImageFont.load_default()
    draw.text((size // 2, size // 2), "DD", anchor="mm", fill="#f2efff", font=font)
    return image


base = render(512)
base.save(OUT / "daydream.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
base.save(OUT / "daydream-512.png")

if platform.system() == "Darwin":
    iconset = OUT / "daydream.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        render(size).save(iconset / f"icon_{size}x{size}.png")
        render(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "daydream.icns")], check=True)
