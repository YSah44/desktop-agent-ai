import base64
import os

from services.display import capture_agent_screenshot
from services.paths import data_path

SCREENSHOT_PATH = data_path("screenshots", "fullscreen.jpg")


def save_screenshot():
    """Capture the monitor under the cursor (or virtual/primary) for the agent."""
    os.makedirs(os.path.dirname(SCREENSHOT_PATH), exist_ok=True)
    img, meta = capture_agent_screenshot(draw_cursor=True)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(SCREENSHOT_PATH, "JPEG", quality=65)
    print(
        f"[SHOT] {meta.get('name')} mode={meta.get('mode')} "
        f"{meta.get('src_w')}x{meta.get('src_h')} → {meta.get('img_w')}x{meta.get('img_h')} "
        f"origin ({meta.get('left')},{meta.get('top')})"
    )
    return SCREENSHOT_PATH


def screenshot_file_ok(path=SCREENSHOT_PATH):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 200
    except OSError:
        return False


def _read_b64(path):
    # The file is already the JPEG we want; re-encoding it only adds time and bytes.
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return ""


def ensure_screenshot_b64(path=SCREENSHOT_PATH):
    """Return JPEG base64, recapturing once if the file is missing or unreadable."""
    if not screenshot_file_ok(path):
        print(f"[SHOT] Missing or empty '{path}' — recapturing")
        save_screenshot()
    b64 = _read_b64(path)
    if not b64:
        print(f"[SHOT] Unreadable '{path}' — recapturing")
        save_screenshot()
        b64 = _read_b64(path)
        if not b64:
            print("[SHOT] Recapture still failed — screenshot unavailable")
    return b64 or ""
