"""Multi-monitor geometry, screenshots, and click-coordinate mapping.

Never assume 1920x1080. Captures the monitor under the cursor by default
(or the virtual desktop / primary via DAVI_SCREENSHOT_MONITOR).
"""
import os
import ctypes
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageGrab

SCREENSHOT_HEIGHT = 720
MODE = os.environ.get("DAVI_SCREENSHOT_MONITOR", "cursor").strip().lower()

# Last capture used to map vision (image) coords back to virtual-screen pixels.
LAST = {
    "left": 0,
    "top": 0,
    "src_w": 0,
    "src_h": 0,
    "img_w": 0,
    "img_h": 0,
    "mode": MODE,
    "name": "unknown",
    "is_primary": True,
    "virtual": {"left": 0, "top": 0, "width": 0, "height": 0},
    "monitors": [],
}

_dpi_set = False


def ensure_dpi_aware():
    """Per-monitor DPI so UIA/win32 rects match pyautogui coordinates."""
    global _dpi_set
    if _dpi_set:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        _dpi_set = True
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        _dpi_set = True
    except Exception:
        pass


ensure_dpi_aware()


@dataclass
class Monitor:
    left: int
    top: int
    width: int
    height: int
    name: str
    is_primary: bool

    @property
    def right(self):
        return self.left + self.width

    @property
    def bottom(self):
        return self.top + self.height

    def contains(self, x, y):
        return self.left <= x < self.right and self.top <= y < self.bottom


def virtual_screen():
    user32 = ctypes.windll.user32
    return {
        "left": int(user32.GetSystemMetrics(76)),   # SM_XVIRTUALSCREEN
        "top": int(user32.GetSystemMetrics(77)),    # SM_YVIRTUALSCREEN
        "width": int(user32.GetSystemMetrics(78)),  # SM_CXVIRTUALSCREEN
        "height": int(user32.GetSystemMetrics(79)), # SM_CYVIRTUALSCREEN
    }


def _from_screeninfo():
    try:
        from screeninfo import get_monitors
        out = []
        for i, m in enumerate(get_monitors()):
            out.append(Monitor(
                left=int(m.x),
                top=int(m.y),
                width=int(m.width),
                height=int(m.height),
                name=getattr(m, "name", None) or f"DISPLAY{i + 1}",
                is_primary=bool(getattr(m, "is_primary", False)),
            ))
        if out:
            return out
    except Exception:
        pass
    return []


def list_monitors():
    monitors = _from_screeninfo()
    if monitors:
        return monitors
    virt = virtual_screen()
    try:
        import pyautogui
        w, h = pyautogui.size()
    except Exception:
        w, h = virt["width"] or 1920, virt["height"] or 1080
    return [Monitor(0, 0, int(w), int(h), "PRIMARY", True)]


def monitor_under_point(x, y):
    monitors = list_monitors()
    for m in monitors:
        if m.contains(x, y):
            return m
    # Nearest center (gaps / DPI rounding).
    best, best_d = monitors[0], 10 ** 18
    for m in monitors:
        cx = m.left + m.width / 2
        cy = m.top + m.height / 2
        d = (cx - x) ** 2 + (cy - y) ** 2
        if d < best_d:
            best, best_d = m, d
    return best


def cursor_pos():
    try:
        import pyautogui
        p = pyautogui.position()
        return int(p.x), int(p.y)
    except Exception:
        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = _POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)


def primary_monitor():
    mons = list_monitors()
    for m in mons:
        if m.is_primary:
            return m
    return mons[0]


def set_mode(mode):
    """Change which display the agent watches, without a restart."""
    global MODE
    MODE = (mode or "cursor").strip().lower()
    return MODE


def select_capture_region(mode=None):
    """Return (Monitor-like region, mode_name)."""
    mode = (mode or MODE or "cursor").lower()
    virt = virtual_screen()
    if mode in ("virtual", "all", "desktop"):
        region = Monitor(
            left=virt["left"], top=virt["top"],
            width=max(1, virt["width"]), height=max(1, virt["height"]),
            name="VIRTUAL", is_primary=False,
        )
        return region, "virtual"
    if mode in ("primary", "main"):
        return primary_monitor(), "primary"
    if mode.isdigit():
        mons = list_monitors()
        idx = int(mode) - 1
        if 0 <= idx < len(mons):
            return mons[idx], mode
    x, y = cursor_pos()
    return monitor_under_point(x, y), "cursor"


def _grab(left, top, width, height):
    bbox = (int(left), int(top), int(left + width), int(top + height))
    try:
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        if img and img.size[0] > 0:
            return img
    except TypeError:
        # Older Pillow: no all_screens
        img = ImageGrab.grab(bbox=bbox)
        if img and img.size[0] > 0:
            return img
    except Exception:
        pass
    try:
        import pyautogui
        return pyautogui.screenshot(region=(int(left), int(top), int(width), int(height)))
    except Exception:
        import pyautogui
        return pyautogui.screenshot()


def _resize_for_agent(img):
    src_w, src_h = img.size
    new_h = SCREENSHOT_HEIGHT
    new_w = max(1, int(src_w * (new_h / src_h)))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return resized, src_w, src_h, new_w, new_h


def _remember(region, mode, src_w, src_h, img_w, img_h):
    LAST.update({
        "left": int(region.left),
        "top": int(region.top),
        "src_w": int(src_w),
        "src_h": int(src_h),
        "img_w": int(img_w),
        "img_h": int(img_h),
        "mode": mode,
        "name": region.name,
        "is_primary": region.is_primary,
        "virtual": virtual_screen(),
        "monitors": [
            {"left": m.left, "top": m.top, "width": m.width, "height": m.height,
             "name": m.name, "is_primary": m.is_primary}
            for m in list_monitors()
        ],
    })
    return dict(LAST)


def capture_raw(mode=None):
    """Full-resolution capture of the selected region (no resize)."""
    ensure_dpi_aware()
    region, mode_name = select_capture_region(mode)
    img = _grab(region.left, region.top, region.width, region.height)
    _remember(region, mode_name, img.size[0], img.size[1], img.size[0], img.size[1])
    return img, dict(LAST)


def capture_agent_screenshot(mode=None, draw_cursor=True):
    """Height-scaled screenshot for the LLM, plus mapping metadata."""
    ensure_dpi_aware()
    region, mode_name = select_capture_region(mode)
    raw = _grab(region.left, region.top, region.width, region.height)
    if raw.mode != "RGB":
        raw = raw.convert("RGB")
    resized, src_w, src_h, img_w, img_h = _resize_for_agent(raw)
    meta = _remember(region, mode_name, src_w, src_h, img_w, img_h)

    if draw_cursor:
        try:
            cx, cy = cursor_pos()
            rx = int((cx - region.left) * (img_w / src_w))
            ry = int((cy - region.top) * (img_h / src_h))
            if 0 <= rx < img_w and 0 <= ry < img_h:
                draw = ImageDraw.Draw(resized)
                r = 5
                draw.ellipse((rx - r, ry - r, rx + r, ry + r), fill=(255, 0, 0))
        except Exception:
            pass
    return resized, meta


def image_to_screen(img_x, img_y, meta=None):
    """Map coordinates from the agent screenshot onto the virtual desktop."""
    meta = meta or LAST
    img_w = max(1, int(meta.get("img_w") or 1))
    img_h = max(1, int(meta.get("img_h") or 1))
    src_w = max(1, int(meta.get("src_w") or img_w))
    src_h = max(1, int(meta.get("src_h") or img_h))
    x = int(meta.get("left", 0) + float(img_x) * src_w / img_w)
    y = int(meta.get("top", 0) + float(img_y) * src_h / img_h)
    return x, y


def clamp_to_virtual(x, y):
    virt = virtual_screen()
    left, top = virt["left"], virt["top"]
    right = left + max(1, virt["width"]) - 1
    bottom = top + max(1, virt["height"]) - 1
    return max(left, min(int(x), right)), max(top, min(int(y), bottom))


def describe_layout():
    virt = virtual_screen()
    mons = list_monitors()
    lines = [
        f"Virtual screen: origin ({virt['left']},{virt['top']}) "
        f"{virt['width']}x{virt['height']}"
    ]
    for i, m in enumerate(mons, 1):
        tag = " primary" if m.is_primary else ""
        lines.append(f"  {i}. {m.name}{tag}: ({m.left},{m.top}) {m.width}x{m.height}")
    last = LAST if LAST.get("src_w") else None
    if last:
        lines.append(
            f"Last screenshot: {last['name']} mode={last['mode']} "
            f"origin ({last['left']},{last['top']}) src {last['src_w']}x{last['src_h']} "
            f"image {last['img_w']}x{last['img_h']}"
        )
    return "\n".join(lines)
