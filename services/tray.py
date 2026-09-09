"""System tray icon so Hide can restore Aemyos with a click."""
import os
import threading

_icon = None
_lock = threading.Lock()


def _image():
    from PIL import Image, ImageDraw

    from services.paths import res_path
    for name in ("tray.png", "tray-64.png", "icon.png"):
        path = res_path("assets", name)
        try:
            face = Image.open(path).convert("RGBA")
            face.thumbnail((32, 32), Image.LANCZOS)
            canvas = Image.new("RGBA", (32, 32), (5, 5, 5, 255))
            canvas.paste(face, ((32 - face.width) // 2, (32 - face.height) // 2), face)
            return canvas
        except Exception:
            continue
    img = Image.new("RGBA", (32, 32), (5, 8, 10, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((1, 1, 30, 30), radius=8, outline=(46, 230, 214, 255), width=2)
    draw.ellipse((12, 12, 20, 20), fill=(46, 230, 214, 255))
    return img


def start(on_show, on_hide=None, on_quit=None):
    """Show a tray icon. Left-click / Show brings the overlay back."""
    global _icon
    try:
        import pystray
        from pystray import MenuItem as Item
    except ImportError:
        print("[TRAY] pystray missing — Hide still works if you say come back")
        return False

    from services.i18n import t as _t

    def _show(icon=None, item=None):
        if on_show:
            on_show()

    def _hide(icon=None, item=None):
        if on_hide:
            on_hide()

    def _quit(icon=None, item=None):
        if on_quit:
            on_quit()

    menu = pystray.Menu(
        Item(_t("tray_show"), _show, default=True),
        Item(_t("tray_hide"), _hide),
        pystray.Menu.SEPARATOR,
        Item(_t("tray_quit"), _quit),
    )
    icon = pystray.Icon("Aemyos", _image(), "Aemyos", menu)
    with _lock:
        old = _icon
        _icon = icon
    if old is not None:
        try:
            old.stop()
        except Exception:
            pass
    try:
        icon.run_detached()
    except Exception:
        threading.Thread(target=icon.run, daemon=True, name="davi-tray").start()
    print("[TRAY] Icon in the notification area")
    return True


def stop():
    global _icon
    with _lock:
        icon = _icon
        _icon = None
    if icon is None:
        return
    try:
        icon.stop()
    except Exception:
        pass
