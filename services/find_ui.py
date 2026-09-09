import base64
import io
import re
import time

from services.display import capture_agent_screenshot, image_to_screen, clamp_to_virtual
from services.openrouter_api import generate
from services.windows_ops import get_foreground_title, target_hwnd

TARGET_W = 1280
TARGET_H = 720


def _capture_screenshot_b64():
    img, meta = capture_agent_screenshot(draw_cursor=False)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return img_b64, meta


def get_ui_element_coordinates(screenshot_path=None, element_description=None, screen_width=None, screen_height=None):
    img_b64, meta = _capture_screenshot_b64()
    img_w = int(meta.get("img_w") or TARGET_W)
    img_h = int(meta.get("img_h") or TARGET_H)
    src_w = int(meta.get("src_w") or img_w)
    src_h = int(meta.get("src_h") or img_h)
    fg = get_foreground_title()
    _, target = target_hwnd(skip_davi=True)

    prompt_text = (
        f'Active window title: "{fg}". Automation target window: "{target}".\n'
        f'This screenshot is {img_w}x{img_h} pixels (height-scaled from {src_w}x{src_h} '
        f'on monitor "{meta.get("name", "?")}" at origin ({meta.get("left", 0)},{meta.get("top", 0)}), '
        f'mode={meta.get("mode")}).\n'
        f'Do NOT assume 1920x1080. Use the image size above.\n'
        f'Find the CENTER of: "{element_description}".\n'
        f'Reply ONLY with: x: NUMBER, y: NUMBER (in {img_w}x{img_h} image coordinates)'
    )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]
        }
    ]

    print(f"[MOUSE] Finding: '{element_description}' (window: {target})...")
    result = generate(messages, "locate_ui_element")
    print(f"[MOUSE] LLM said: {result}")

    match = re.search(r'x:\s*(-?\d+(?:\.\d+)?),?\s*y:\s*(-?\d+(?:\.\d+)?)', result, re.IGNORECASE)
    img_x = img_y = None
    if match:
        img_x = int(float(match.group(1)))
        img_y = int(float(match.group(2)))
    else:
        numbers = re.findall(r'-?\d+', result)
        if len(numbers) >= 2:
            img_x, img_y = int(numbers[-2]), int(numbers[-1])

    if img_x is None:
        print("[MOUSE] Could not parse coordinates")
        return None

    if img_x <= 0 and img_y <= 0:
        print("[MOUSE] Locator returned not-found (0,0)")
        return None

    if not (0 <= img_x <= img_w and 0 <= img_y <= img_h):
        print(f"[MOUSE] Coords out of image bounds: ({img_x},{img_y}) vs {img_w}x{img_h}")
        return None

    real_x, real_y = image_to_screen(img_x, img_y, meta)
    real_x, real_y = clamp_to_virtual(real_x, real_y)
    print(f"[MOUSE] Image ({img_x},{img_y}) in {img_w}x{img_h} → Screen ({real_x},{real_y}) "
          f"origin ({meta.get('left')},{meta.get('top')}) src {src_w}x{src_h}")
    return real_x, real_y


def move_mouse_to_ui_element(element_description, screenshot_path=None, use_uia=True):
    if use_uia:
        try:
            from services.win_uia import move_to_control
            coords = move_to_control(element_description)
            if coords:
                return coords
        except Exception as e:
            print(f"[UIA] move fallback to vision: {e}")

    # OCR before vision: a local sub-second lookup beats a paid round trip
    # whenever the target is plain text on screen.
    try:
        from services.ocr import locate_element
        hit = locate_element(element_description)
        if hit:
            x, y, text = hit
            x, y = clamp_to_virtual(x, y)
            print(f"[OCR] '{element_description}' matched '{text}' at ({x}, {y})")
            import pyautogui
            pyautogui.moveTo(x, y, duration=0.15)
            return (x, y)
    except Exception as e:
        print(f"[OCR] locate fallback to vision: {e}")

    coordinates = get_ui_element_coordinates(element_description=element_description)
    if not coordinates:
        time.sleep(0.25)
        print("[MOUSE] Retrying vision locate once...")
        coordinates = get_ui_element_coordinates(element_description=element_description)

    if coordinates:
        x, y = clamp_to_virtual(*coordinates)
        try:
            from services.windows_ops import point_is_overlay
            if point_is_overlay(x, y):
                print(f"[MOUSE] Target ({x}, {y}) is the DAVI overlay — not clicking")
                return None
        except Exception:
            pass
        print(f"[MOUSE] Moving to ({x}, {y})")
        try:
            import pyautogui
            pyautogui.moveTo(x, y, duration=0.15)
        except Exception as e:
            print(f"[MOUSE] moveTo failed: {e}")
            return None
        return (x, y)

    print("[MOUSE] Failed to find element")
    return None
