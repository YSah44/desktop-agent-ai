"""Windows UI Automation: find/click controls by name and type.

Uses comtypes + UIAutomationCore. Optional pywinauto fallback.
Falls back to vision (find_ui) at the call site, not here.
"""
import time
import ctypes
import re

from services.display import ensure_dpi_aware, clamp_to_virtual
from services.windows_ops import (
    target_hwnd, is_davi_title, get_foreground_title, _title_of,
)

ensure_dpi_aware()

UIA_NamePropertyId = 30005
UIA_ControlTypePropertyId = 30003
UIA_AutomationIdPropertyId = 30011
UIA_ClassNamePropertyId = 30012
UIA_IsEnabledPropertyId = 30010
UIA_IsOffscreenPropertyId = 30022
UIA_BoundingRectanglePropertyId = 30001

UIA_InvokePatternId = 10000
UIA_TogglePatternId = 10015
UIA_SelectionItemPatternId = 10010
UIA_ExpandCollapsePatternId = 10005
UIA_ValuePatternId = 10002
UIA_LegacyIAccessiblePatternId = 10018

TreeScope_Element = 1
TreeScope_Children = 2
TreeScope_Descendants = 4
TreeScope_Subtree = 7

PropertyConditionFlags_IgnoreCase = 0x1
PropertyConditionFlags_MatchSubstring = 0x2

CONTROL_TYPES = {
    "button": 50000,
    "calendar": 50001,
    "checkbox": 50002,
    "combobox": 50003,
    "edit": 50004,
    "hyperlink": 50005,
    "link": 50005,
    "image": 50006,
    "listitem": 50007,
    "list": 50008,
    "menu": 50009,
    "menubar": 50010,
    "menuitem": 50011,
    "progressbar": 50012,
    "radiobutton": 50013,
    "radio": 50013,
    "scrollbar": 50014,
    "slider": 50015,
    "spinner": 50016,
    "statusbar": 50017,
    "tab": 50018,
    "tabitem": 50019,
    "text": 50020,
    "toolbar": 50021,
    "tooltip": 50022,
    "tree": 50023,
    "treeitem": 50024,
    "custom": 50025,
    "group": 50026,
    "thumb": 50027,
    "datagrid": 50028,
    "dataitem": 50029,
    "document": 50030,
    "splitbutton": 50031,
    "window": 50032,
    "pane": 50033,
    "header": 50034,
    "headeritem": 50035,
    "table": 50036,
    "titlebar": 50037,
    "separator": 50038,
}

CONTROL_NAMES = {v: k for k, v in CONTROL_TYPES.items()}

_uia = None
_mod = None
_init_error = None


def uia_available():
    return _get_uia() is not None


def _get_uia():
    global _uia, _mod, _init_error
    if _uia is not None:
        return _uia
    if _init_error:
        return None
    try:
        import comtypes
        import comtypes.client
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        _mod = comtypes.client.GetModule("UIAutomationCore.dll")
        _uia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=_mod.IUIAutomation,
        )
        return _uia
    except Exception as e:
        _init_error = str(e)
        print(f"[UIA] Init failed: {e}")
        return None


def _type_id(control_type):
    if control_type is None or control_type == "":
        return None
    if isinstance(control_type, int):
        return control_type
    key = str(control_type).lower().replace(" ", "").replace("_", "")
    aliases = {
        "btn": "button",
        "textbox": "edit",
        "input": "edit",
        "combo": "combobox",
        "dropdown": "combobox",
        "check": "checkbox",
        "item": "listitem",
    }
    key = aliases.get(key, key)
    return CONTROL_TYPES.get(key)


def _safe_name(el):
    try:
        return el.CurrentName or ""
    except Exception:
        return ""


def _safe_type(el):
    try:
        return int(el.CurrentControlType)
    except Exception:
        return 0


def _safe_enabled(el):
    try:
        return bool(el.CurrentIsEnabled)
    except Exception:
        return True


def _safe_offscreen(el):
    try:
        return bool(el.CurrentIsOffscreen)
    except Exception:
        return False


def _rect(el):
    try:
        r = el.CurrentBoundingRectangle
        left = int(getattr(r, "left", 0))
        top = int(getattr(r, "top", 0))
        right = int(getattr(r, "right", 0))
        bottom = int(getattr(r, "bottom", 0))
        w, h = right - left, bottom - top
        if w <= 1 or h <= 1:
            return None
        return {"left": left, "top": top, "right": right, "bottom": bottom,
                "width": w, "height": h, "cx": left + w // 2, "cy": top + h // 2}
    except Exception:
        return None


def _element_from_hwnd(hwnd):
    uia = _get_uia()
    if not uia or not hwnd:
        return None
    try:
        return uia.ElementFromHandle(int(hwnd))
    except Exception:
        try:
            return uia.ElementFromHandle(ctypes.c_void_p(int(hwnd)))
        except Exception:
            return None


def _name_condition(uia, name, substring=True):
    flags = PropertyConditionFlags_IgnoreCase
    if substring:
        flags |= PropertyConditionFlags_MatchSubstring
    try:
        return uia.CreatePropertyConditionEx(UIA_NamePropertyId, str(name), flags)
    except Exception:
        return uia.CreatePropertyCondition(UIA_NamePropertyId, str(name))


def _and(uia, a, b):
    if a is None:
        return b
    if b is None:
        return a
    return uia.CreateAndCondition(a, b)


def _collect(arr, limit=12):
    out = []
    if arr is None:
        return out
    try:
        n = int(arr.Length)
    except Exception:
        return out
    for i in range(min(n, limit)):
        try:
            out.append(arr.GetElement(i))
        except Exception:
            continue
    return out


def _info(el, window_title=""):
    rect = _rect(el)
    ctype = _safe_type(el)
    aid = ""
    cls = ""
    try:
        aid = el.CurrentAutomationId or ""
    except Exception:
        pass
    try:
        cls = el.CurrentClassName or ""
    except Exception:
        pass
    return {
        "name": _safe_name(el),
        "type": CONTROL_NAMES.get(ctype, str(ctype)),
        "type_id": ctype,
        "automation_id": aid,
        "class_name": cls,
        "enabled": _safe_enabled(el),
        "offscreen": _safe_offscreen(el),
        "rect": rect,
        "x": rect["cx"] if rect else None,
        "y": rect["cy"] if rect else None,
        "window": window_title,
    }


def _name_acceptable(name, query):
    """Reject paragraph-length substring hits like 'start' inside Discord channel text."""
    if not query:
        return True
    n = (name or "").strip()
    q = str(query).strip()
    if not n:
        return False
    nl, ql = n.lower(), q.lower()
    if nl == ql:
        return True
    if len(n) > max(48, len(q) * 5):
        return False
    if nl.startswith(ql) and (len(nl) == len(ql) or not nl[len(ql)].isalnum()):
        return True
    return bool(re.search(r'(^|[^a-z0-9])' + re.escape(ql) + r'([^a-z0-9]|$)', nl))


def _score(info, query):
    q = (query or "").strip().lower()
    name = (info.get("name") or "").strip().lower()
    score = 0
    if not name:
        return -1
    if not _name_acceptable(name, query):
        return -1
    if name == q:
        score += 100
    elif name.startswith(q):
        score += 70
    elif q in name:
        score += 40
    else:
        return -1
    if info.get("enabled"):
        score += 10
    if not info.get("offscreen"):
        score += 10
    if info.get("rect"):
        score += 5
    if info.get("type") in ("button", "menuitem", "hyperlink", "listitem", "tabitem", "splitbutton"):
        score += 12
    if info.get("type") in ("text", "document") and name != q:
        score -= 20
    return score


def _search_tree(root, name, type_id=None, automation_id=None, limit=12):
    uia = _get_uia()
    if not uia or root is None:
        return []
    if automation_id:
        cond = uia.CreatePropertyCondition(UIA_AutomationIdPropertyId, str(automation_id))
        if type_id:
            cond = _and(uia, cond, uia.CreatePropertyCondition(UIA_ControlTypePropertyId, int(type_id)))
        try:
            return _collect(root.FindAll(TreeScope_Descendants, cond), limit=limit)
        except Exception:
            return []

    found = []
    if name:
        try:
            cond = _name_condition(uia, name, substring=False)
            if type_id:
                cond = _and(uia, cond, uia.CreatePropertyCondition(UIA_ControlTypePropertyId, int(type_id)))
            found = _collect(root.FindAll(TreeScope_Descendants, cond), limit=limit)
        except Exception:
            found = []
        if found:
            return found
        try:
            cond = _name_condition(uia, name, substring=True)
            if type_id:
                cond = _and(uia, cond, uia.CreatePropertyCondition(UIA_ControlTypePropertyId, int(type_id)))
            return _collect(root.FindAll(TreeScope_Descendants, cond), limit=limit)
        except Exception:
            return []
    cond = uia.CreateTrueCondition()
    if type_id:
        cond = _and(uia, cond, uia.CreatePropertyCondition(UIA_ControlTypePropertyId, int(type_id)))
    try:
        return _collect(root.FindAll(TreeScope_Descendants, cond), limit=limit)
    except Exception:
        return []


def _pywinauto_find(name, control_type=None, hwnd=None):
    try:
        from pywinauto import Desktop
    except Exception:
        return []
    try:
        desk = Desktop(backend="uia")
        kwargs = {"title_re": f"(?i).*{name}.*"}
        if control_type:
            pretty = str(control_type).replace("_", " ").title()
            kwargs["control_type"] = pretty
        if hwnd:
            win = desk.window(handle=int(hwnd))
            ctrls = win.descendants(**kwargs)
        else:
            ctrls = desk.windows(**kwargs)
        hits = []
        for c in ctrls[:8]:
            try:
                rect = c.rectangle()
                hits.append({
                    "name": c.window_text(),
                    "type": control_type or "",
                    "enabled": True,
                    "offscreen": False,
                    "rect": {
                        "left": rect.left, "top": rect.top,
                        "right": rect.right, "bottom": rect.bottom,
                        "width": rect.width(), "height": rect.height(),
                        "cx": rect.mid_point().x, "cy": rect.mid_point().y,
                    },
                    "x": rect.mid_point().x,
                    "y": rect.mid_point().y,
                    "window": "",
                    "_pwa": c,
                })
            except Exception:
                continue
        return hits
    except Exception:
        return []


def find_controls(name=None, control_type=None, automation_id=None, hwnd=None, limit=8):
    """Return a list of control info dicts (best matches first)."""
    type_id = _type_id(control_type)
    window_title = ""
    root_hwnd = hwnd
    if not root_hwnd:
        root_hwnd, window_title = target_hwnd(skip_davi=True)
    else:
        window_title = _title_of(root_hwnd)

    hits = []
    uia = _get_uia()
    if uia:
        root = _element_from_hwnd(root_hwnd) if root_hwnd else uia.GetRootElement()
        if root is not None:
            for el in _search_tree(root, name, type_id, automation_id, limit=limit * 2):
                info = _info(el, window_title)
                info["_el"] = el
                info["_score"] = _score(info, name) if name else 50
                if name and info["_score"] < 0:
                    continue
                hits.append(info)

        # If the target window missed, search the desktop (taskbar, Start, other apps).
        if not hits and name:
            try:
                desktop = uia.GetRootElement()
                for el in _search_tree(desktop, name, type_id, automation_id, limit=limit * 2):
                    info = _info(el, window_title)
                    if is_davi_title(info.get("name") or ""):
                        continue
                    info["_el"] = el
                    info["_score"] = _score(info, name)
                    if info["_score"] >= 0:
                        hits.append(info)
            except Exception:
                pass

    if not hits:
        hits.extend(_pywinauto_find(name, control_type, root_hwnd))

    hits.sort(key=lambda h: h.get("_score", 0), reverse=True)
    return hits[:limit]


def _window_name(el):
    try:
        return el.CurrentName or ""
    except Exception:
        return ""


def find_control(name=None, control_type=None, automation_id=None):
    hits = find_controls(name=name, control_type=control_type,
                         automation_id=automation_id, limit=5)
    if not hits:
        return {"success": False, "message": f"UIA: no control named '{name}'", "hits": []}
    best = hits[0]
    lines = []
    for h in hits:
        r = h.get("rect") or {}
        lines.append(
            f"  {h.get('name','')} [{h.get('type','')}] "
            f"at ({h.get('x')},{h.get('y')}) {r.get('width','?')}x{r.get('height','?')}"
        )
    return {
        "success": True,
        "message": f"[UIA] {len(hits)} match(es) in '{best.get('window','')}':\n" + "\n".join(lines),
        "hits": [{k: v for k, v in h.items() if not k.startswith('_')} for h in hits],
        "x": best.get("x"),
        "y": best.get("y"),
        "name": best.get("name"),
        "type": best.get("type"),
        "_el": best.get("_el"),
        "_pwa": best.get("_pwa"),
    }


def _invoke(el):
    if el is None:
        return False
    uia = _get_uia()
    for pid, iface_name, method in (
        (UIA_InvokePatternId, "IUIAutomationInvokePattern", "Invoke"),
        (UIA_TogglePatternId, "IUIAutomationTogglePattern", "Toggle"),
        (UIA_SelectionItemPatternId, "IUIAutomationSelectionItemPattern", "Select"),
        (UIA_ExpandCollapsePatternId, "IUIAutomationExpandCollapsePattern", "Expand"),
    ):
        try:
            unk = el.GetCurrentPattern(pid)
            if not unk:
                continue
            iface = getattr(_mod, iface_name)
            pat = unk.QueryInterface(iface)
            getattr(pat, method)()
            return True
        except Exception:
            continue
    try:
        unk = el.GetCurrentPattern(UIA_LegacyIAccessiblePatternId)
        if unk:
            pat = unk.QueryInterface(_mod.IUIAutomationLegacyIAccessiblePattern)
            pat.DoDefaultAction()
            return True
    except Exception:
        pass
    return False


def _mouse_click_xy(x, y, button="left"):
    import pyautogui
    x, y = clamp_to_virtual(x, y)
    pyautogui.moveTo(x, y, duration=0.12)
    time.sleep(0.05)
    pyautogui.click(button=button)
    return x, y


def move_to_control(name, control_type=None):
    """Move the mouse onto a UIA control. Returns (x, y) or None."""
    found = find_control(name=name, control_type=control_type)
    if not found.get("success") or found.get("x") is None:
        return None
    x, y = clamp_to_virtual(found["x"], found["y"])
    try:
        import pyautogui
        pyautogui.moveTo(x, y, duration=0.12)
        print(f"[UIA] Moved to '{found.get('name')}' at ({x},{y})")
        return x, y
    except Exception as e:
        print(f"[UIA] Move failed: {e}")
        return None


def click_control(name, control_type=None, button="left", retries=1):
    """Click by UIA (invoke or mouse). Retry once on failure."""
    last = {"success": False, "message": f"UIA click failed: '{name}'"}
    for attempt in range(retries + 1):
        found = find_control(name=name, control_type=control_type)
        if not found.get("success"):
            last = found
            time.sleep(0.2)
            continue
        el = found.get("_el")
        pwa = found.get("_pwa")
        invoked = False
        if button == "left":
            invoked = _invoke(el)
            if not invoked and pwa is not None:
                try:
                    pwa.click_input()
                    invoked = True
                except Exception:
                    pass
        if not invoked:
            if found.get("x") is None:
                last = {"success": False, "message": f"UIA found '{name}' but no clickable point"}
                time.sleep(0.2)
                continue
            try:
                _mouse_click_xy(found["x"], found["y"], button=button)
            except Exception as e:
                last = {"success": False, "message": f"UIA mouse click failed: {e}"}
                time.sleep(0.2)
                continue
        retry_note = f" (retry {attempt})" if attempt else ""
        last = {
            "success": True,
            "message": (
                f"UIA clicked '{found.get('name')}' [{found.get('type')}] "
                f"in '{found.get('hits')[0].get('window','') if found.get('hits') else ''}'"
                f"{retry_note}"
            ),
            "x": found.get("x"),
            "y": found.get("y"),
        }
        return last
    return last


def describe_status():
    ok = uia_available()
    hwnd, title = target_hwnd(skip_davi=True)
    return {
        "available": ok,
        "init_error": _init_error,
        "target_window": title,
        "target_hwnd": hwnd,
        "foreground": get_foreground_title(),
    }
