"""Generate extension icons from the Aemyos brand mark."""
from PIL import Image
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "icon.png")
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
os.makedirs(ICON_DIR, exist_ok=True)

src = Image.open(SRC).convert("RGBA")
for size in (16, 48, 128):
    img = src.resize((size, size), Image.LANCZOS)
    img.save(os.path.join(ICON_DIR, f"icon{size}.png"))
    print(f"Created icon{size}.png")

print("Done!")
