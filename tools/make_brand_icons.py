"""Build Aemyos brand assets from the source logo JPEGs."""
from __future__ import annotations

import os
import shutil

from PIL import Image, ImageEnhance

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(os.path.dirname(ROOT), "davi-site")
BRAND = os.path.join(ROOT, "assets", "brand")
CACHE = os.path.join(
    os.path.expanduser("~"),
    ".cursor",
    "projects",
    "c-Users-Kabexnuf-desktop-agent",
    "assets",
)

SQUARE_SRC = os.path.join(
    CACHE,
    "c__Users_Kabexnuf_AppData_Roaming_Cursor_User_workspaceStorage_"
    "a1c8e88153ec26f1aa392ba860aee1ca_images_icon__2_-43e9ddc4-894d-46d3-9d1c-b4fea673ba9f.jpg",
)
WORDMARK_SRC = os.path.join(
    CACHE,
    "c__Users_Kabexnuf_AppData_Roaming_Cursor_User_workspaceStorage_"
    "a1c8e88153ec26f1aa392ba860aee1ca_images_ChatGPT_Image_Sep_8__2026__"
    "08_53_53_PM-adb6c960-ec97-45ff-ba68-b50189683dde.jpg",
)


def crop_content(im: Image.Image, thresh: int = 18, pad: int = 12) -> Image.Image:
    import numpy as np

    rgb = np.array(im.convert("RGB"))
    mask = rgb.max(axis=2) > thresh
    ys, xs = np.where(mask)
    if xs.size == 0:
        return im
    minx, maxx = int(xs.min()), int(xs.max())
    miny, maxy = int(ys.min()), int(ys.max())
    minx = max(0, minx - pad)
    miny = max(0, miny - pad)
    maxx = min(im.width, maxx + 1 + pad)
    maxy = min(im.height, maxy + 1 + pad)
    return im.crop((minx, miny, maxx, maxy))


def make_square(im: Image.Image, size: int, fill=(0, 0, 0, 255)) -> Image.Image:
    im = im.convert("RGBA")
    side = max(im.width, im.height)
    canvas = Image.new("RGBA", (side, side), fill)
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    return canvas.resize((size, size), Image.LANCZOS)


def save(im: Image.Image, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, optimize=True)
    print("wrote", path, im.size)


def main() -> None:
    os.makedirs(BRAND, exist_ok=True)
    shutil.copy2(SQUARE_SRC, os.path.join(BRAND, "icon-source.jpg"))
    shutil.copy2(WORDMARK_SRC, os.path.join(BRAND, "logo-source.jpg"))

    square = crop_content(Image.open(SQUARE_SRC), thresh=16, pad=8)
    word = crop_content(Image.open(WORDMARK_SRC), thresh=14, pad=10)

    icon_512 = make_square(square, 512)
    icon_256 = make_square(square, 256)
    save(icon_512, os.path.join(ROOT, "assets", "icon.png"))
    save(icon_256, os.path.join(BRAND, "icon-256.png"))

    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    ico_images = [make_square(square, s) for s in ico_sizes]
    ico_path = os.path.join(ROOT, "assets", "icon.ico")
    ico_images[0].save(
        ico_path,
        sizes=[(s, s) for s in ico_sizes],
        format="ICO",
    )
    print("wrote", ico_path)

    tray = make_square(square, 32)
    tray = ImageEnhance.Contrast(tray).enhance(1.25)
    tray = ImageEnhance.Color(tray).enhance(1.2)
    save(tray, os.path.join(ROOT, "assets", "tray.png"))
    save(make_square(square, 64), os.path.join(ROOT, "assets", "tray-64.png"))

    site_img = os.path.join(SITE, "img")
    os.makedirs(site_img, exist_ok=True)
    save(icon_512, os.path.join(site_img, "icon.png"))
    save(make_square(square, 180), os.path.join(site_img, "apple-touch.png"))
    save(make_square(square, 32), os.path.join(site_img, "favicon-32.png"))
    save(make_square(square, 16), os.path.join(site_img, "favicon-16.png"))
    ico_images[0].save(
        os.path.join(site_img, "favicon.ico"),
        sizes=[(16, 16), (32, 32), (48, 48)],
        format="ICO",
    )
    print("wrote", os.path.join(site_img, "favicon.ico"))

    logo = word.convert("RGBA")
    # Keep the pill wide; cap height for the header.
    max_w = 1400
    if logo.width > max_w:
        h = int(logo.height * max_w / logo.width)
        logo = logo.resize((max_w, h), Image.LANCZOS)
    save(logo, os.path.join(site_img, "logo.png"))
    save(logo, os.path.join(BRAND, "logo.png"))

    # Chrome extension icons
    ext = os.path.join(ROOT, "chrome-extension", "icons")
    os.makedirs(ext, exist_ok=True)
    for s in (16, 48, 128):
        save(make_square(square, s), os.path.join(ext, f"icon{s}.png"))


if __name__ == "__main__":
    main()
