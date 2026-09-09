"""Win32 window management, Explorer/Start search, and guarded file ops."""
import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from urllib.parse import quote

from services.display import ensure_dpi_aware

ensure_dpi_aware()

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9
SW_SHOWDEFAULT = 10

HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
SWP_FRAMECHANGED = 0x0020
MONITOR_DEFAULTTONEAREST = 2
GA_ROOT = 2
CREATE_NO_WINDOW = 0x08000000

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def _title_of(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""


def _class_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value or ""


def is_davi_title(title):
    t = (title or "").strip().lower()
    if not t:
        return False
    if t in ("aemyos", "davi", "dayi"):
        return True
    if t.startswith("aemyos -") or t.startswith("davi -") or t.startswith("dayi -"):
        return True
    if "desktop agent" in t and "chrome" not in t and "google" not in t:
        return True
    return False


def is_davi_hwnd(hwnd):
    if _class_of(hwnd) == "TkTopLevel":
        return True
    return is_davi_title(_title_of(hwnd))


def get_foreground_hwnd():
    return user32.GetForegroundWindow()


def get_foreground_title():
    return _title_of(get_foreground_hwnd()) or "(unknown)"


def window_from_point(x, y):
    pt = POINT(int(x), int(y))
    hwnd = user32.WindowFromPoint(pt)
    if not hwnd:
        return 0
    root = user32.GetAncestor(hwnd, GA_ROOT)
    return root or hwnd


def point_is_overlay(x, y):
    """True if screen point (x,y) is on the Aemyos overlay."""
    hwnd = window_from_point(int(x), int(y))
    return bool(hwnd and is_davi_hwnd(hwnd))


def _pid_of(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _rect_of(hwnd):
    rc = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return None
    return {
        "left": rc.left, "top": rc.top,
        "right": rc.right, "bottom": rc.bottom,
        "width": rc.right - rc.left, "height": rc.bottom - rc.top,
    }


def _state_of(hwnd):
    if user32.IsIconic(hwnd):
        return "minimized"
    if user32.IsZoomed(hwnd):
        return "maximized"
    return "normal"


def list_windows(include_empty=False):
    """Z-order visible top-level windows (closest to Alt+Tab)."""
    results = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _title_of(hwnd)
        if not title and not include_empty:
            return True
        # Skip tool windows without a title already handled; skip owned popups with no title.
        results.append({
            "hwnd": int(hwnd),
            "title": title,
            "pid": _pid_of(hwnd),
            "state": _state_of(hwnd),
            "rect": _rect_of(hwnd),
            "is_davi": is_davi_hwnd(hwnd),
        })
        return True

    proc = WNDENUMPROC(cb)
    user32.EnumWindows(proc, 0)
    return results


def format_window_list(windows=None, limit=25):
    windows = windows if windows is not None else list_windows()
    lines = []
    for i, w in enumerate(windows[:limit], 1):
        mark = " [Aemyos — do not close]" if w.get("is_davi") else ""
        lines.append(f"  {i}. {w['title'][:80]} ({w['state']}){mark}")
    extra = f"\n  … {len(windows) - limit} more" if len(windows) > limit else ""
    return f"[WINDOWS] {len(windows)} visible:\n" + "\n".join(lines) + extra


def find_hwnd(title_query, skip_davi=True):
    if not title_query:
        return None
    q = str(title_query).lower()
    for w in list_windows():
        if skip_davi and w.get("is_davi") and "davi" not in q and "dayi" not in q and "aemyos" not in q:
            continue
        if q in (w.get("title") or "").lower():
            return w
    return None


def target_hwnd(skip_davi=True):
    """Window we should automate: not the Aemyos overlay if it stole focus."""
    hwnd = get_foreground_hwnd()
    title = _title_of(hwnd)
    if hwnd and title and not (skip_davi and is_davi_title(title)):
        return int(hwnd), title
    try:
        import pyautogui
        x, y = int(pyautogui.position().x), int(pyautogui.position().y)
    except Exception:
        x, y = 0, 0
    under = window_from_point(x, y)
    if under and not (skip_davi and is_davi_hwnd(under)):
        return int(under), _title_of(under)
    for w in list_windows():
        if skip_davi and w.get("is_davi"):
            continue
        if w.get("title"):
            return int(w["hwnd"]), w["title"]
    return int(hwnd or 0), title or "(unknown)"


def focus_hwnd(hwnd):
    hwnd = int(hwnd)
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    try:
        user32.AllowSetForegroundWindow(-1)
    except Exception:
        pass
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    this_tid = kernel32.GetCurrentThreadId()
    attached = False
    try:
        if fg_tid and this_tid and fg_tid != this_tid:
            attached = bool(user32.AttachThreadInput(this_tid, fg_tid, True))
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        return True
    finally:
        if attached:
            user32.AttachThreadInput(this_tid, fg_tid, False)


def _work_area(hwnd):
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        virt = RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(virt), 0)  # SPI_GETWORKAREA
        return virt
    return mi.rcWork


def snap_hwnd(hwnd, where):
    hwnd = int(hwnd)
    if not hwnd:
        return False
    if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.05)
    work = _work_area(hwnd)
    left, top, right, bottom = work.left, work.top, work.right, work.bottom
    width = right - left
    height = bottom - top
    where = (where or "").lower().replace("snap_", "")
    if where in ("left", "snapleft"):
        x, y, w, h = left, top, width // 2, height
    elif where in ("right", "snapright"):
        x, y, w, h = left + width // 2, top, width - width // 2, height
    elif where in ("top", "up"):
        x, y, w, h = left, top, width, height // 2
    elif where in ("bottom", "down"):
        x, y, w, h = left, top + height // 2, width, height - height // 2
    else:
        return False
    user32.SetWindowPos(hwnd, HWND_TOP, int(x), int(y), int(w), int(h),
                        SWP_SHOWWINDOW | SWP_FRAMECHANGED)
    return True


def manage_window(action, title=None):
    action = (action or "").lower().strip()
    if action in ("list", "list_windows"):
        return {"success": True, "message": format_window_list(), "action": "list"}

    if title:
        match = find_hwnd(title, skip_davi=not is_davi_title(title))
        if not match:
            return {"success": False, "error": f"No window matching '{title}'"}
        hwnd, win_title = int(match["hwnd"]), match["title"]
    else:
        hwnd, win_title = target_hwnd(skip_davi=True)

    if not hwnd:
        return {"success": False, "error": "No target window"}

    if action == "close" and is_davi_title(win_title):
        return {"success": False, "error": "BLOCKED: Cannot close the Aemyos overlay"}

    try:
        if action in ("minimize", "min"):
            user32.ShowWindow(hwnd, SW_MINIMIZE)
        elif action in ("maximize", "max"):
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
        elif action in ("restore", "unminimize"):
            user32.ShowWindow(hwnd, SW_RESTORE)
        elif action == "close":
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        elif action in ("focus", "activate", "foreground", "show"):
            if not focus_hwnd(hwnd):
                return {"success": False, "error": f"Could not focus '{win_title}'"}
        elif action in ("snap_left", "left", "snapleft"):
            snap_hwnd(hwnd, "left")
        elif action in ("snap_right", "right", "snapright"):
            snap_hwnd(hwnd, "right")
        elif action in ("snap_top", "top"):
            snap_hwnd(hwnd, "top")
        elif action in ("snap_bottom", "bottom"):
            snap_hwnd(hwnd, "bottom")
        else:
            return {"success": False, "error": (
                f"Unknown action: {action}. "
                "Use: minimize, maximize, restore, close, focus, "
                "snap_left, snap_right, snap_top, snap_bottom, list"
            )}
        return {"success": True, "window": win_title, "action": action}
    except Exception as e:
        return {"success": False, "error": str(e)}


def focus_window(title):
    match = find_hwnd(title, skip_davi=not is_davi_title(title or ""))
    if not match:
        return {"success": False, "message": f"No window matching '{title}'"}
    ok = focus_hwnd(match["hwnd"])
    return {
        "success": bool(ok),
        "message": f"Focused '{match['title']}'" if ok else f"Failed to focus '{match['title']}'",
        "window": match["title"],
    }


def switch_app(title=None, mode="focus"):
    """Bring a window forward by title substring, or Alt+Tab / Win+Tab."""
    title = (title or "").strip()
    mode = (mode or "focus").strip().lower()
    if title:
        match = find_hwnd(title, skip_davi=True)
        if match:
            ok = focus_hwnd(match["hwnd"])
            return {
                "success": bool(ok),
                "message": f"Switched to '{match['title']}'" if ok else f"Failed to focus '{match['title']}'",
                "window": match["title"],
            }
        return {
            "success": False,
            "message": f"No window matching '{title}'.\n{format_window_list()}",
        }
    try:
        import pyautogui
        if mode in ("win_tab", "wintab", "task_view", "taskview"):
            pyautogui.hotkey("win", "tab")
            return {"success": True, "message": "Opened Task View (Win+Tab)"}
        pyautogui.hotkey("alt", "tab")
        time.sleep(0.2)
        hwnd, win_title = target_hwnd(skip_davi=True)
        if hwnd and is_davi_title(win_title):
            pyautogui.hotkey("alt", "tab")
            time.sleep(0.15)
            hwnd, win_title = target_hwnd(skip_davi=True)
        if hwnd:
            focus_hwnd(hwnd)
        return {"success": True, "message": f"Alt+Tab → {win_title}"}
    except Exception as e:
        return {"success": False, "message": f"switch_app failed: {e}"}


def find_files(query, scope="explorer", path=None):
    """Open Explorer search or Start-menu search for a query."""
    query = (query or "").strip()
    if not query:
        return {"success": False, "message": "Missing search query"}
    scope = (scope or "explorer").lower()
    if scope in ("start", "startmenu", "win", "search"):
        return _start_menu_search(query)
    return _explorer_search(query, path)


def _explorer_search(query, path=None):
    location = os.path.abspath(os.path.expanduser(path or "~"))
    if not os.path.isdir(location):
        location = os.path.expanduser("~")
    uri = (
        f"search-ms:query={quote(query)}"
        f"&crumb=location:{quote(location)}"
        f"&displayname={quote('Aemyos search')}"
    )
    try:
        os.startfile(uri)
        return {"success": True, "message": f"Explorer search for '{query}' in {location}"}
    except Exception:
        try:
            subprocess.Popen(
                ["explorer.exe", uri],
                creationflags=CREATE_NO_WINDOW,
            )
            return {"success": True, "message": f"Explorer search for '{query}' in {location}"}
        except Exception as e:
            return {"success": False, "message": f"Explorer search failed: {e}"}


def _start_menu_search(query):
    try:
        import pyautogui
        import pyperclip
        pyautogui.hotkey("win", "s")
        time.sleep(0.4)
        pyperclip.copy(query)
        pyautogui.hotkey("ctrl", "v")
        return {"success": True, "message": f"Start menu search typed: '{query}' (press Enter to open)"}
    except Exception as e:
        return {"success": False, "message": f"Start search failed: {e}"}


_BLOCKED_DELETE_PREFIXES = (
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\programdata",
)


def _blocked_path(path):
    ap = os.path.abspath(os.path.expanduser(path)).lower()
    return any(ap.startswith(p) for p in _BLOCKED_DELETE_PREFIXES)


def _flag_confirmed(confirmed):
    if confirmed is True or confirmed == 1:
        return True
    if isinstance(confirmed, str) and confirmed.strip().lower() in ("1", "true", "yes", "evet"):
        return True
    return False


def _destructive_disabled():
    """Tests set DAVI_DISABLE_DESTRUCTIVE=1 so native delete/empty/shutdown never run."""
    return os.environ.get("DAVI_DISABLE_DESTRUCTIVE", "").strip().lower() in ("1", "true", "yes")


def _refuse_destructive(name):
    if _destructive_disabled():
        return {"success": False, "message": "BLOCKED: destructive actions disabled"}
    return {"success": False, "message": f"REFUSED: {name} needs confirmed=true"}


def delete_file(path, confirmed=False):
    """Send a file or folder to the Recycle Bin. Requires confirmed=True. Never call from tests."""
    if _destructive_disabled() or not _flag_confirmed(confirmed):
        return _refuse_destructive("delete_file")
    path = os.path.abspath(os.path.expanduser(path or ""))
    if not path or not os.path.exists(path):
        return {"success": False, "message": f"Path not found: {path}"}
    if _blocked_path(path):
        return {"success": False, "message": f"BLOCKED: cannot delete system path {path}"}
    is_dir = os.path.isdir(path)
    method = "DeleteDirectory" if is_dir else "DeleteFile"
    escaped = path.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        f"[Microsoft.VisualBasic.FileIO.FileSystem]::{method}("
        f"'{escaped}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "failed").strip()
            return {"success": False, "message": f"Delete failed: {err[:300]}"}
        return {"success": True, "message": f"Sent to Recycle Bin: {path}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def empty_recycle(confirmed=False):
    """Empty Recycle Bin. Requires confirmed=True. Unit tests must mock this — never call live."""
    if _destructive_disabled() or not _flag_confirmed(confirmed):
        return _refuse_destructive("empty_recycle")
    # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    flags = 0x00000001 | 0x00000002 | 0x00000004
    try:
        hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
        code = int(hr) & 0xFFFFFFFF
        # 0 = S_OK, 1 = S_FALSE, 0x80070057 often means the bin was already empty
        if code in (0, 1, 0x80070057):
            return {"success": True, "message": "Recycle Bin emptied"}
        return {"success": False, "message": f"Empty Recycle Bin HRESULT=0x{code:08X}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def shutdown_pc(mode="shutdown", confirmed=False):
    """Shutdown / restart / sleep. Requires confirmed=True. Never call from tests."""
    if _destructive_disabled() or not _flag_confirmed(confirmed):
        return _refuse_destructive("shutdown_pc")
    mode = (mode or "shutdown").lower()
    if mode in ("restart", "reboot"):
        args = ["shutdown", "/r", "/t", "15", "/c", "Aemyos restart requested"]
        msg = "Restart in 15s (shutdown /a to abort)"
    elif mode in ("sleep", "suspend"):
        args = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
        msg = "Sleep requested"
    else:
        args = ["shutdown", "/s", "/t", "15", "/c", "Aemyos shutdown requested"]
        msg = "Shutdown in 15s (shutdown /a to abort)"
    try:
        subprocess.Popen(args, creationflags=CREATE_NO_WINDOW)
        return {"success": True, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}
