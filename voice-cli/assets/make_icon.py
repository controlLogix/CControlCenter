"""Draws assets/voicecli.ico (run: uv run --with pillow python assets/make_icon.py)."""
from pathlib import Path
from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=56, fill=(17, 20, 24, 255), outline=(60, 207, 110, 255), width=10)
d.rounded_rectangle((98, 44, 158, 150), radius=30, fill=(233, 237, 241, 255))  # capsule
d.arc((70, 90, 186, 184), start=0, end=180, fill=(233, 237, 241, 255), width=12)  # cradle
d.line((128, 184, 128, 212), fill=(233, 237, 241, 255), width=12)
d.line((96, 212, 160, 212), fill=(233, 237, 241, 255), width=12)
d.ellipse((176, 40, 212, 76), fill=(60, 207, 110, 255))  # "live" dot
out = Path(__file__).with_name("voicecli.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(out.with_suffix(".png"))
print(out)
