import pyautogui
from services.display import ensure_dpi_aware, clamp_to_virtual, virtual_screen

ensure_dpi_aware()
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.02


def get_cursor_position():
    return pyautogui.position()


def get_screen_dimensions():
    """Virtual desktop size (not a single 1920x1080 assumption)."""
    virt = virtual_screen()
    return virt["width"], virt["height"]


def move_cursor_absolute(x, y):
    x, y = clamp_to_virtual(x, y)
    pyautogui.moveTo(x, y, duration=0.1)


def move_cursor_relative(dx, dy):
    current_x, current_y = pyautogui.position()
    new_x, new_y = clamp_to_virtual(current_x + dx, current_y + dy)
    pyautogui.moveTo(new_x, new_y, duration=0.1)


def _refuse_overlay_click(x=None, y=None):
    try:
        from services.windows_ops import point_is_overlay
        if x is None or y is None:
            pos = pyautogui.position()
            x, y = int(pos.x), int(pos.y)
        if point_is_overlay(x, y):
            print(f"[MOUSE] Refusing click on DAVI overlay at ({int(x)},{int(y)})")
            return True
    except Exception as e:
        print(f"[MOUSE] Overlay check failed: {e}")
    return False


def click_mouse_button(button="left"):
    if _refuse_overlay_click():
        return False
    pyautogui.click(button=button)
    return True


def double_click(button="left"):
    if _refuse_overlay_click():
        return False
    pyautogui.doubleClick(button=button)
    return True


def drag_to(x, y, button="left", duration=0.5):
    x, y = clamp_to_virtual(x, y)
    if _refuse_overlay_click(x, y):
        return False
    pyautogui.dragTo(x, y, button=button, duration=duration)
    return True


def mouse_down(button="left"):
    if _refuse_overlay_click():
        return False
    pyautogui.mouseDown(button=button)
    return True


def mouse_up(button="left"):
    pyautogui.mouseUp(button=button)
    return True


def scroll(clicks):
    pyautogui.scroll(clicks)
    return True
