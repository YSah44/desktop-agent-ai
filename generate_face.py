"""Build circular photoreal face frames (no rings — overlay draws theme rings)."""
from PIL import Image, ImageDraw, ImageFilter
import os

SIZE = 256
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
CURSOR_SRC = os.path.join(
    os.path.expanduser("~"),
    ".cursor",
    "projects",
    "c-Users-Kabexnuf-desktop-agent",
    "assets",
)

FRAME_NAMES = ["idle", "blink", "speak_1", "speak_2", "speak_3"]

# Unprefixed outputs are the original female set, kept for backwards
# compatibility; gendered sets are written as face_<gender>_<frame>.png.
VARIANTS = {
    "": "davi_face_%s.png",
    "male": "davi_male_%s.png",
    "female": "davi_female_%s.png",
}

FRAMES = {name: "davi_face_%s.png" % name for name in FRAME_NAMES}


def _find_src(filename):
    for folder in (CURSOR_SRC, SRC_DIR):
        path = os.path.join(folder, filename)
        if os.path.isfile(path) and os.path.basename(filename).startswith("davi_"):
            return path
    path = os.path.join(SRC_DIR, filename)
    if os.path.isfile(path):
        return path
    return None


def _dest_name(variant, frame):
    return f"face_{frame}.png" if not variant else f"face_{variant}_{frame}.png"


def _square_crop(im, zoom=0.90, up_bias=0.03):
    w, h = im.size
    side = min(w, h) * zoom
    left = (w - side) / 2.0
    top = max(0.0, (h - side) / 2.0 - h * up_bias)
    if top + side > h:
        top = h - side
    return im.crop((int(left), int(top), int(left + side), int(top + side)))


def make_circle(im, size=SIZE):
    im = _square_crop(im.convert("RGB")).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((1, 1, size - 2, size - 2), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(1.1))
    out = im.convert("RGBA")
    out.putalpha(mask)
    return out


def main():
    os.makedirs(SRC_DIR, exist_ok=True)
    for variant, pattern in VARIANTS.items():
        for name in FRAME_NAMES:
            dest_name = _dest_name(variant, name)
            src = _find_src(pattern % name)
            if not src:
                local = os.path.join(SRC_DIR, dest_name)
                if os.path.isfile(local):
                    print(f"keep {local}")
                else:
                    print(f"skip {dest_name}: no source {pattern % name}")
                continue
            print(f"{dest_name}: {src}")
            circle = make_circle(Image.open(src), SIZE)
            circle.save(os.path.join(SRC_DIR, dest_name), "PNG")
            if name == "idle" and not variant:
                rgb = circle.convert("RGB")
                bg = Image.new("RGB", rgb.size, (18, 18, 22))
                bg.paste(rgb, mask=circle.split()[-1])
                bg.save(os.path.join(SRC_DIR, "face_base.jpg"), "JPEG", quality=92)
    print("done")


if __name__ == "__main__":
    main()
