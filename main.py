import warnings
warnings.filterwarnings("ignore")
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
import sys
import traceback

from services.paths import FROZEN as _FROZEN, data_path as _data_path, res_path as _res_path

_CRASH_LOG_PATH = _data_path("crash.log")

if _FROZEN:
    # Windowed exe has no console: keep print() output in a log for support.
    try:
        _log = open(_data_path("aemyos.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = _log
        sys.stderr = _log
    except Exception:
        pass


def _global_exception_handler(exc_type, exc_value, exc_tb):
    """Prevent silent crashes — log to file"""
    try:
        try:
            from services.safety import trim_crash_log
            trim_crash_log(_CRASH_LOG_PATH)
        except Exception:
            pass
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"CRASH at {__import__('datetime').datetime.now()}\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        traceback.print_exception(exc_type, exc_value, exc_tb)
    except Exception:
        pass
sys.excepthook = _global_exception_handler

def _enable_dpi_awareness():
    """Use this PC's real pixels so clicks match any resolution / DPI scale."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()

_CHANNEL = (os.environ.get("DAVI_CHANNEL") or "").strip().lower()
_APP_USER_MODEL_ID = "Aemyos.DesktopAgent" + (f".{_CHANNEL}" if _CHANNEL else "")
_ICON_HANDLES = []


def _set_windows_app_id():
    """Stop Windows grouping this with python.exe and using the Python snake icon."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)
    except Exception:
        pass


def _hwnd_set_icon(hwnd, ico_path):
    if not hwnd or not ico_path or not os.path.isfile(ico_path):
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_SMALL, ICON_BIG = 0, 1
        GCLP_HICON, GCLP_HICONSM = -14, -34
        LoadImageW = user32.LoadImageW
        LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        LoadImageW.restype = wintypes.HANDLE
        h_big = LoadImageW(None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        h_sm = LoadImageW(None, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if not h_big and not h_sm:
            return
        if h_big:
            _ICON_HANDLES.append(h_big)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
        if h_sm:
            _ICON_HANDLES.append(h_sm)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_sm)
        icon = h_big or h_sm
        sm = h_sm or h_big
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            user32.SetClassLongPtrW(hwnd, GCLP_HICON, icon)
            user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, sm)
        else:
            user32.SetClassLongW(hwnd, GCLP_HICON, icon)
            user32.SetClassLongW(hwnd, GCLP_HICONSM, sm)
    except Exception:
        pass


_set_windows_app_id()


def _desktop_work_area():
    """Usable desktop rectangle, excluding the Windows taskbar."""
    try:
        import ctypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        pass
    return 0, 0, 1920, 1080


_INSTANCE_MUTEX_NAME = "Local\\DAVI_DesktopAgent" + (f"_{_CHANNEL}" if _CHANNEL else "")
_PID_PATH = _data_path("davi.pid")
_instance_mutex = None
_pid_lock_file = None


def acquire_single_instance():
    """Named mutex + exclusive pid lock so a second start cannot stack overlays."""
    global _instance_mutex, _pid_lock_file
    replacing = os.environ.pop("DAVI_RESTARTING", "") == "1"
    attempts = 25 if replacing else 1
    try:
        import time as _time
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.SetLastError.argtypes = [wintypes.DWORD]
        for i in range(attempts):
            kernel32.SetLastError(0)
            handle = kernel32.CreateMutexW(None, False, _INSTANCE_MUTEX_NAME)
            err = ctypes.get_last_error()
            if not handle:
                print(f"[MAIN] Mutex create failed (err={err})")
                if i + 1 < attempts:
                    _time.sleep(0.2)
                    continue
                return False
            if err == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                if i + 1 < attempts:
                    _time.sleep(0.2)
                    continue
                print("[MAIN] Aemyos already running - not opening a second overlay.")
                return False
            _instance_mutex = handle
            break
        else:
            return False
    except Exception as e:
        print(f"[MAIN] Mutex error: {e}")
        _instance_mutex = None

    try:
        import msvcrt
        import time as _time
        lock = None
        for i in range(attempts):
            lock = open(_PID_PATH, "a+", encoding="utf-8")
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                lock.close()
                lock = None
                if i + 1 < attempts:
                    _time.sleep(0.2)
                    continue
                print("[MAIN] Aemyos already running - pid lock held.")
                return False
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        _pid_lock_file = lock
    except Exception as e:
        print(f"[MAIN] PID file: {e}")
        return False
    atexit.register(_release_single_instance)
    return True


def _release_single_instance():
    global _instance_mutex, _pid_lock_file
    lock = _pid_lock_file
    _pid_lock_file = None
    if lock is not None:
        try:
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        try:
            lock.close()
        except Exception:
            pass
    try:
        if os.path.isfile(_PID_PATH):
            with open(_PID_PATH, "r", encoding="utf-8") as f:
                old = (f.read() or "").strip()
            if old == str(os.getpid()):
                os.remove(_PID_PATH)
    except Exception:
        pass
    handle = _instance_mutex
    _instance_mutex = None
    if handle:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


def restart_overlay_process():
    """Restart this Python overlay. Never reboots Windows. No-op on failure."""
    try:
        import subprocess
        root = os.path.dirname(os.path.abspath(__file__))
        env = os.environ.copy()
        env["DAVI_RESTARTING"] = "1"
        exe = sys.executable
        if _FROZEN:
            cmd = [exe]
            root = os.path.dirname(exe)
        else:
            if exe.lower().endswith("python.exe"):
                pyw = exe[:-10] + "pythonw.exe"
                if os.path.isfile(pyw):
                    exe = pyw
            cmd = [exe, "-u", os.path.join(root, "main.py")]
        create_new_process_group = 0x00000200
        detached = 0x00000008
        subprocess.Popen(
            cmd,
            cwd=root,
            env=env,
            close_fds=False,
            creationflags=detached | create_new_process_group,
        )
        print("[MAIN] Overlay restart spawned — exiting this instance.")
        _release_single_instance()
        os._exit(0)
    except Exception as e:
        print(f"[MAIN] Overlay restart ignored: {e}")
        return False


THEMES = {
    "dark": {
        "BG": "#0c0d12",
        "BG2": "#12141b",
        "BG3": "#1c1e28",
        "CARD": "#16181f",
        "BORDER": "#2a2d38",
        "BORDER_LIGHT": "#3d4150",
        "TEXT": "#f3f4f8",
        "DIM": "#8b93a3",
        "ACCENT": "#9b8cff",
        "ACCENT2": "#b4a8ff",
        "GREEN": "#4ade80",
        "YELLOW": "#f0c14b",
        "RED": "#f07178",
        "PURPLE": "#a8b0c4",
        "CYAN": "#7eb0ff",
        "ON_FG": "#ffffff",
        "CHIP_OK": "#173528",
        "BTN_SOFT": "#3d4456",
        "HEART": "#ff6b8a",
    },
    "light": {
        "BG": "#e6e9f0",
        "BG2": "#fafbfd",
        "BG3": "#eaedf4",
        "CARD": "#ffffff",
        "BORDER": "#c6ccd9",
        "BORDER_LIGHT": "#b3bac8",
        "TEXT": "#161821",
        "DIM": "#5c6370",
        "ACCENT": "#5b4de8",
        "ACCENT2": "#7a6ef0",
        "GREEN": "#178a50",
        "YELLOW": "#b8860b",
        "RED": "#c53d3d",
        "PURPLE": "#5a6172",
        "CYAN": "#1d6fd8",
        "ON_FG": "#ffffff",
        "CHIP_OK": "#d8f3e4",
        "BTN_SOFT": "#d4dae6",
        "HEART": "#e23d62",
    },
}

from services.openrouter_api import generate
from services.execute_funcs import extract_json, process_commands, set_listening, set_cancel_flag, get_cancel_flag
from services.screenshot_utils import save_screenshot, ensure_screenshot_b64
from config import SYSTEM_PROMPT, DAVI_VERSION
from services.tts import speak as tts_speak
from services.i18n import t, apply_runtime_language, get_language, whisper_language
import os
import json
import time
import argparse
import threading
import asyncio
import queue
import sys
import atexit
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from pynput import keyboard
import sounddevice as sd

agent_running = True
agent_status = "Starting"
status_window = None
stop_event = threading.Event()
voice_processor_ref = None
_user_quit = False
task_queue = []
task_queue_lock = threading.Lock()
cancel_requested = False
voice_backlog = []
_reply_sinks = []
_task_id_seq = 0


def request_quit(reason=""):
    """Kill the whole Aemyos process. Overlay ×, Alt+F4, voice 'kapat', Ctrl+Shift+Q.

    Hide ('gizlen') must not use this. Closing the overlay is not withdraw —
    it must not leave the agent loop running so a later utterance can deiconify.
    """
    global agent_running, _user_quit, status_window
    if _user_quit:
        os._exit(0)
    _user_quit = True
    print(f"[MAIN] Quit requested ({reason or 'unknown'})")
    agent_running = False
    stop_event.set()
    status_window = None
    try:
        from services.tts import stop_speaking
        stop_speaking()
    except Exception:
        pass
    vp = voice_processor_ref
    if vp is not None:
        try:
            vp.stop()
        except Exception:
            pass
    _release_single_instance()
    try:
        from services.tray import stop as stop_tray
        stop_tray()
    except Exception:
        pass
    os._exit(0)


TASK_KEEP = 24
TASK_SHOW = 24
TQ_HEIGHT_OPEN = 220
try:
    from services.voice_input import VoiceInputProcessor
    VOICE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Voice input functionality not available: {e}")
    print("Running without voice input support.")
    VOICE_AVAILABLE = False

_last_cursor_position = None
_last_screen_dimensions = None
_cursor_position_lock = threading.Lock()
_screen_dimensions_lock = threading.Lock()
_screenshot_queue = queue.Queue()
_command_results_queue = queue.Queue()


def _persist_tasks_unlocked():
    try:
        from services.execute_funcs import load_memory, save_memory
        mem = load_memory()
        slim = []
        for t in task_queue[-TASK_KEEP:]:
            slim.append({
                "id": t.get("id"),
                "text": t.get("text", ""),
                "status": t.get("status", "done"),
                "progress": t.get("progress", "") if t.get("status") == "running" else "",
                "ts": t.get("ts", ""),
            })
        mem["tasks"] = slim
        save_memory(mem)
    except Exception as e:
        print(f"[TASK] Persist error: {e}")


def load_persisted_tasks():
    global _task_id_seq
    try:
        from services.execute_funcs import load_memory
        mem = load_memory()
        rows = mem.get("tasks") or []
    except Exception:
        rows = []
    cleaned = []
    max_id = 0
    for row in rows:
        status = row.get("status") or "done"
        if status == "running":
            status = "done"
        try:
            tid = int(row.get("id") or 0)
        except (TypeError, ValueError):
            tid = 0
        if tid <= 0:
            max_id += 1
            tid = max_id
        max_id = max(max_id, tid)
        cleaned.append({
            "id": tid,
            "text": str(row.get("text") or ""),
            "status": status if status in ("pending", "running", "done", "cancelled") else "done",
            "progress": "",
            "ts": str(row.get("ts") or ""),
        })
    with task_queue_lock:
        task_queue[:] = cleaned[-TASK_KEEP:]
        _task_id_seq = max(max_id, _task_id_seq)


def add_task(task_text):
    global _task_id_seq
    text = (task_text or "").strip()
    if not text:
        return
    with task_queue_lock:
        for t in task_queue:
            if t["status"] == "running":
                t["status"] = "done"
                t["progress"] = ""
        _task_id_seq += 1
        task_queue.append({
            "id": _task_id_seq,
            "text": text,
            "status": "running",
            "progress": "",
            "ts": datetime.now().isoformat(timespec="seconds"),
        })
        if len(task_queue) > TASK_KEEP:
            task_queue[:] = task_queue[-TASK_KEEP:]
        _persist_tasks_unlocked()


def cancel_task(task_id):
    global cancel_requested
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return False
    with task_queue_lock:
        for t in task_queue:
            if t.get("id") == task_id and t["status"] in ("pending", "running"):
                was_running = t["status"] == "running"
                t["status"] = "cancelled"
                t["progress"] = ""
                _persist_tasks_unlocked()
                if was_running:
                    cancel_requested = True
                    try:
                        set_cancel_flag(True)
                    except Exception:
                        pass
                return True
    return False


def complete_current_task():
    with task_queue_lock:
        for t in task_queue:
            if t["status"] == "running":
                t["status"] = "done"
                t["progress"] = ""
                _persist_tasks_unlocked()
                return


def cancel_current_task():
    with task_queue_lock:
        for t in task_queue:
            if t["status"] == "running":
                t["status"] = "cancelled"
                t["progress"] = ""
                _persist_tasks_unlocked()
                return


def set_task_progress(text):
    if not text:
        return
    with task_queue_lock:
        for t in task_queue:
            if t["status"] == "running":
                t["progress"] = str(text)[:48]
                return


def _status_chip_text(status):
    """Keep the overlay chip on one short line (Step N must not wrap)."""
    s = (status or "").strip()
    parts = s.split()
    step_word = "Step"
    try:
        from services.i18n import t as _t
        step_word = _t("step")
    except Exception:
        pass
    if len(parts) >= 2 and parts[0].lower() in {
        "step", "adım", "adim", "schritt", "étape", "etape", "paso", (step_word or "step").lower(),
    }:
        num = parts[1].replace("...", "").rstrip(".")
        if num.isdigit():
            s = f"{step_word} {num}"
    if len(s) > 16:
        s = s[:15] + "…"
    return s


def update_agent_status(status):
    global agent_status
    status = _status_chip_text(status)
    agent_status = status
    set_task_progress(status)
    if status_window:
        try:
            status_window.root.after_idle(status_window.update_status, status)
        except Exception:
            pass


def update_agent_response(text, speak=True):
    if text:
        try:
            from services.daily import remember_spoken
            remember_spoken(text)
        except Exception:
            pass
    if status_window and text:
        try:
            status_window.root.after_idle(status_window.update_response, text)
            status_window.root.after_idle(status_window.set_last_action, text)
        except Exception:
            pass
    if text and speak:
        try:
            update_agent_status(t("speaking"))
        except Exception:
            pass
        tts_speak(text)
    if text:
        for sink in list(_reply_sinks):
            try:
                sink(text)
            except Exception:
                pass


def enqueue_remote_command(text):
    """A command that arrived by text (Telegram etc.): same queue as speech."""
    text = (text or "").strip()
    if not text:
        return
    voice_backlog.append(text)
    win = status_window
    if win is not None:
        try:
            win.root.after_idle(win._set_bubble, win.trans_text, "_trans_ph", text)
        except Exception:
            pass


def _wait_until_tts_idle(tail=0.0):
    """Stay ready for the next command while she talks; don't park the mic after.

    Playback itself still gates the microphone so her voice is not transcribed.
    """
    try:
        import services.tts as tts
    except Exception:
        return
    if not tts.is_speaking:
        return
    t0 = time.time()
    while agent_running and time.time() - t0 < 90:
        if not tts.is_speaking:
            break
        time.sleep(0.05)
    if tail:
        time.sleep(tail)


class StatusOverlay:
    BG = "#08090d"
    BG2 = "#101218"
    BG3 = "#1a1d27"
    CARD = "#12151c"
    BORDER = "#2a2f3a"
    BORDER_LIGHT = "#3d4352"
    TEXT = "#eef0f4"
    DIM = "#8d93a0"
    ACCENT = "#7c93ff"
    ACCENT2 = "#9aa8ff"
    GREEN = "#3ee08f"
    YELLOW = "#f0c14b"
    RED = "#f07178"
    PURPLE = "#a8b0c4"
    CYAN = "#7eb0ff"

    def __init__(self, root):
        self.root = root
        from services.i18n import t as _t
        theme_name = os.environ.get("DAVI_THEME", "dark").lower().strip()
        if theme_name not in THEMES:
            theme_name = "dark"
        self._set_palette(theme_name)
        from config import OPACITY, ALWAYS_ON_TOP
        self._always_top = bool(ALWAYS_ON_TOP)
        self.root.configure(bg=self.BG)
        self.root.title("Aemyos")
        self.root.overrideredirect(True)
        self.root.protocol("WM_DELETE_WINDOW", self._close_app)
        self.root.attributes('-topmost', bool(ALWAYS_ON_TOP))
        self.root.attributes('-alpha', max(0.6, min(1.0, OPACITY / 100.0)))
        self._set_taskbar_icon()
        self.root.bind("<Map>", self._on_root_map)
        self.root.bind("<Unmap>", self._on_root_unmap)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self._screen_w = screen_w
        self._screen_h = screen_h
        wx, wy, ww, wh = _desktop_work_area()
        self._work = (wx, wy, ww, wh)
        self._win_width = max(340, min(420, int(ww * 0.20)))
        self._full_width = self._win_width
        self._compact_width = 300
        self._min_width = 300
        self._min_height = 320
        self._compact = False
        self._auto_height = True
        self._margin = max(10, int(ww * 0.008))
        init_h = min(640, max(self._min_height, int(wh * 0.62)))
        x = wx + ww - self._win_width - self._margin
        y = wy + self._margin
        self.root.geometry(f"{self._win_width}x{init_h}+{x}+{y}")
        self.root.after(100, self._apply_app_window_style)
        self.root.after(120, self._set_taskbar_icon)
        self.root.after(400, self._assert_topmost)

        # Single source of truth: a second copy here used to re-run
        # theme_use('clam'), which wipes styles registered afterwards.
        self._apply_ttk()

        shell = tk.Frame(self.root, bg=self.BORDER, bd=0, highlightthickness=0)
        shell.pack(fill=tk.BOTH, expand=True)
        outer = tk.Frame(shell, bg=self.BG, bd=0, highlightthickness=0)
        outer.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self._main_canvas = tk.Canvas(outer, bg=self.BG, highlightthickness=0, bd=0)
        self._main_vsb = ttk.Scrollbar(
            outer, orient="vertical", command=self._main_canvas.yview,
            style="Overlay.Vertical.TScrollbar",
        )
        self._main_canvas.configure(yscrollcommand=self._main_vsb.set)
        self._main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.frame = tk.Frame(self._main_canvas, bg=self.BG)
        self._frame_id = self._main_canvas.create_window((0, 0), window=self.frame, anchor="nw")
        self.frame.bind("<Configure>", self._on_frame_configure)
        self._main_canvas.bind("<Configure>", self._on_canvas_configure)

        def _on_mousewheel(event):
            return self._on_overlay_wheel(event)
        self._main_canvas.bind("<MouseWheel>", _on_mousewheel)
        self.frame.bind("<MouseWheel>", _on_mousewheel)

        # Resize edges (all 4 sides + corners)
        EDGE = 5
        HDR = 40
        BTN_STRIP = 120
        self._edge_r = tk.Frame(self.root, bg=self.BG, width=EDGE, cursor="sb_h_double_arrow")
        self._edge_r.place(relx=1.0, y=HDR, anchor="ne", relheight=1.0, height=-HDR, width=EDGE)
        self._edge_b = tk.Frame(self.root, bg=self.BG, height=EDGE, cursor="sb_v_double_arrow")
        self._edge_b.place(x=0, rely=1.0, anchor="sw", relwidth=1.0, height=EDGE)
        self._edge_l = tk.Frame(self.root, bg=self.BG, width=EDGE, cursor="sb_h_double_arrow")
        self._edge_l.place(x=0, y=HDR, anchor="nw", relheight=1.0, height=-HDR, width=EDGE)
        self._edge_t = tk.Frame(self.root, bg=self.BG, height=EDGE, cursor="sb_v_double_arrow")
        self._edge_t.place(x=0, y=0, anchor="nw", relwidth=1.0, width=-BTN_STRIP, height=EDGE)

        self._resize_grip = tk.Canvas(self.root, width=12, height=12, bg=self.BG, highlightthickness=0, cursor="size_nw_se")
        self._resize_grip.place(relx=1.0, rely=1.0, anchor="se")
        self._resize_grip.create_line(3, 12, 12, 3, fill=self.DIM, width=1)
        self._resize_grip.create_line(7, 12, 12, 7, fill=self.DIM, width=1)
        self._resize_grip.create_line(11, 12, 12, 11, fill=self.DIM, width=1)

        for widget, mode in [(self._edge_r, "r"), (self._edge_b, "b"),
                             (self._edge_l, "l"), (self._edge_t, "t"),
                             (self._resize_grip, "br")]:
            widget.bind("<Button-1>", lambda e, m=mode: self._start_resize(e, m))
            widget.bind("<B1-Motion>", lambda e, m=mode: self._do_resize(e, m))

        P = 12
        self._pad = P
        GAP = (8, 0)
        INNER = dict(padx=12, pady=10)

        # ═══ HEADER ═══
        header_wrap = tk.Frame(self.frame, bg=self.BG2)
        header_wrap.pack(fill=tk.X)
        accent_bar = tk.Frame(header_wrap, bg=self.ACCENT, width=3)
        accent_bar.pack(side=tk.LEFT, fill=tk.Y)
        header = tk.Frame(header_wrap, bg=self.BG2)
        self._header_wrap = header_wrap
        header.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        hdr_left = tk.Frame(header, bg=self.BG2)
        hdr_left.pack(side=tk.LEFT, fill=tk.Y)
        title_col = tk.Frame(hdr_left, bg=self.BG2)
        title_col.pack(side=tk.LEFT, padx=(14, 0), pady=10)
        name_row = tk.Frame(title_col, bg=self.BG2)
        name_row.pack(anchor="w")
        self._hdr_title = tk.Label(name_row, text="", bg=self.BG2, bd=0, highlightthickness=0)
        self._hdr_title.pack(side=tk.LEFT)
        self._set_header_logo()
        self._ver_pill = tk.Frame(name_row, bg=self.ACCENT)
        self._ver_pill.pack(side=tk.LEFT, padx=(8, 0))
        self._ver_lbl = tk.Label(self._ver_pill, text=DAVI_VERSION, fg=getattr(self, "ON_FG", "#ffffff"), bg=self.ACCENT,
                                 font=("Segoe UI", 7, "bold"))
        self._ver_lbl.pack(padx=6, pady=1)
        self._dictation_badge = tk.Label(name_row, text="", fg=getattr(self, "ON_FG", "#ffffff"),
                                         bg=self.ACCENT, font=("Segoe UI", 7, "bold"))
        hdr_right = tk.Frame(header, bg=self.BG2)
        hdr_right.pack(side=tk.RIGHT, padx=(0, 4))
        self.status_dot = tk.Label(hdr_right, text="●", fg=self.GREEN, bg=self.BG2, font=("Segoe UI", 9))
        self.status_dot.pack(side=tk.LEFT, padx=(0, 2), pady=8)
        self._min_btn = tk.Button(hdr_right, text="—", fg=self.DIM, bg=self.BG2, font=("Segoe UI", 10),
                            bd=0, padx=8, pady=0, cursor="hand2", activebackground=self.BG3, activeforeground=self.YELLOW,
                            command=self._minimize_app)
        self._min_btn.pack(side=tk.LEFT, padx=1, pady=8)
        self._attach_tooltip(self._min_btn, lambda: _t("minimize"))
        self._close_btn = tk.Button(hdr_right, text="×", fg=self.DIM, bg=self.BG2, font=("Segoe UI", 12),
                              bd=0, padx=8, pady=0, cursor="hand2", activebackground="#3b1520", activeforeground=self.RED,
                              command=self._close_app)
        self._close_btn.pack(side=tk.LEFT, padx=(1, 8), pady=8)

        tk.Frame(self.frame, bg=self.BORDER, height=1).pack(fill=tk.X)

        # ═══ FACE + STATUS ═══
        face_card = tk.Frame(self.frame, bg=self.CARD, highlightthickness=1, highlightbackground=self.BORDER)
        face_card.pack(fill=tk.X, padx=P, pady=GAP)
        self._face_card = face_card

        face_inner = tk.Frame(face_card, bg=self.CARD)
        face_inner.pack(fill=tk.X, **INNER)

        # Canvas is drawn larger than the resting face so she can grow into the
        # headroom while speaking without resizing the card around her.
        self._orb_size_full = 148
        self._orb_size_compact = 256
        self._orb_size = self._orb_size_full
        self._orb_tick = 0
        self._orb_energy = 0.0
        self._orb_scale = 1.0
        self._orb_photo = None
        self._orb_ok = True
        self._face_images = {}
        self._face_pil = {}
        self._current_face = None
        self._blink_until = 0
        self._next_blink_tick = 28
        self._face_inner = face_inner
        self._face_col = tk.Frame(face_inner, bg=self.CARD)
        self._face_col.pack(side=tk.LEFT, anchor="n")
        self.face_label = tk.Label(self._face_col, bg=self.CARD, bd=0, highlightthickness=0)
        self.face_label.pack()
        self.face_label.bind("<Double-Button-1>", lambda e: self._toggle_compact())
        self._update_agent_orb(speaking=False)

        info_right = tk.Frame(face_inner, bg=self.CARD)
        info_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))
        self._info_right = info_right

        # Stop button + status chip share one row so Stop sits right beside "Listening…".
        self._status_row = tk.Frame(info_right, bg=self.CARD)
        self._status_chip = tk.Frame(self._status_row, bg=getattr(self, "CHIP_OK", self.BG3))
        chip_inner = tk.Frame(self._status_chip, bg=getattr(self, "CHIP_OK", self.BG3))
        chip_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self._status_icon = tk.Label(chip_inner, text="∿", fg=self.GREEN, bg=getattr(self, "CHIP_OK", self.BG3),
                                     font=("Segoe UI", 10))
        self._status_icon.pack(side=tk.LEFT, padx=(0, 6))
        self.status_label = tk.Label(chip_inner, text=_t("starting"), fg=self.GREEN, bg=getattr(self, "CHIP_OK", self.BG3),
                                      font=("Segoe UI Semibold", 9), anchor="w",
                                      wraplength=0, height=1)
        self.status_label.pack(side=tk.LEFT)
        self._status_chip_inner = chip_inner

        self._face_actions = tk.Frame(info_right, bg=self.CARD)
        self._face_mode_btn = tk.Button(
            self._face_actions, text=_t("compact"), fg=getattr(self, "ON_FG", "#ffffff"),
            bg=self.ACCENT, font=("Segoe UI", 8, "bold"), bd=0, padx=12, pady=5,
            cursor="hand2", activebackground=self.ACCENT2, activeforeground="#ffffff",
            command=self._toggle_compact,
        )
        self._bind_hover(self._face_mode_btn, self.ACCENT, "#ffffff", self.ACCENT2, "#ffffff")
        self._face_mute_btn = tk.Button(
            self._face_actions, text=_t("mic_btn_mute"), fg=self.TEXT, bg=self.BG3,
            font=("Segoe UI", 8, "bold"), bd=0, padx=12, pady=5, cursor="hand2",
            activebackground=self.BG2, command=self._toggle_own_mic,
        )
        self._bind_hover(self._face_mute_btn, self.BG3, self.TEXT, self.ACCENT, "#ffffff")
        self._face_hide_btn = tk.Button(
            self._face_actions, text=_t("face_min"), fg=self.TEXT, bg=getattr(self, "BTN_SOFT", self.BORDER),
            font=("Segoe UI", 8, "bold"), bd=0, padx=12, pady=5, cursor="hand2",
            activebackground=self.BORDER_LIGHT, command=self.hide_until_shown,
        )
        self._bind_hover(self._face_hide_btn, getattr(self, "BTN_SOFT", self.BORDER), self.TEXT, self.ACCENT, "#ffffff")
        self._attach_tooltip(self._face_hide_btn, lambda: _t("face_min_hint"))
        self._face_stop_btn = tk.Button(
            self._status_row, text=_t("face_stop"), fg=getattr(self, "RED", "#ff6b6b"), bg=self.BG3,
            font=("Segoe UI", 8, "bold"), bd=0, padx=12, pady=5, cursor="hand2",
            activebackground=self.BG2, command=self._face_stop,
        )
        self._bind_hover(self._face_stop_btn, self.BG3, getattr(self, "RED", "#ff6b6b"), self.ACCENT, "#ffffff")
        self._attach_tooltip(self._face_stop_btn, lambda: _t("face_stop_hint"))
        self._face_stop_btn.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=(0, 4))
        self._status_chip.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        self._sync_face_action_buttons()

        self.sys_time_label = tk.Label(info_right, text="", fg=self.TEXT, bg=self.CARD,
                                        font=("Segoe UI", 18, "bold"), anchor="w")
        self.sys_time_label.pack(anchor="w", pady=(12, 0))
        self.sys_date_label = tk.Label(info_right, text="", fg=self.DIM, bg=self.CARD,
                                        font=("Segoe UI", 8), anchor="w")
        self.sys_date_label.pack(anchor="w", pady=(2, 4))
        try:
            now = datetime.now()
            self.sys_time_label.config(text=now.strftime("%I:%M:%S %p").lstrip("0"))
            self.sys_date_label.config(text=now.strftime("%A, %B %d, %Y"))
        except Exception:
            pass

        bridge_row = tk.Frame(info_right, bg=self.CARD)
        bridge_row.pack(anchor="w", pady=(8, 0), fill=tk.X)
        self._bridge_row = bridge_row
        self.bridge_label = tk.Label(bridge_row, text=_t("chrome_off"), fg=self.DIM, bg=self.CARD,
                                      font=("Segoe UI", 8), anchor="w")
        self._ext_btn = tk.Button(bridge_row, text=_t("setup"), fg=self.ACCENT, bg=self.BG3,
                                   font=("Segoe UI", 7, "bold"), bd=0, padx=8, pady=2, cursor="hand2",
                                   activebackground=self.BG2, command=self._open_extension_setup)
        # Pack Setup on the right first so "Chrome Disconnected" cannot clip it off.
        self._ext_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.bridge_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.face_id_label = tk.Label(info_right, text="", fg=self.DIM, bg=self.CARD,
                                      font=("Segoe UI", 8), anchor="w")
        self._last_face_id_sig = None

        self._last_action_raw = ""

        self._sys_info_counter = 0

        qa_card = tk.Frame(self.frame, bg=self.CARD, highlightthickness=1, highlightbackground=self.BORDER)
        self._qa_card = qa_card
        qa_inner = tk.Frame(qa_card, bg=self.CARD)
        qa_inner.pack(fill=tk.X, padx=10, pady=10)
        self._lbl_controls = tk.Label(qa_inner, text=_t("controls"), fg=self.DIM, bg=self.CARD,
                                       font=("Segoe UI", 7, "bold"))
        self._lbl_controls.pack(anchor="w", pady=(0, 6))
        self._qa_caps = []
        self._qa_tiles = []
        qa_media = tk.Frame(qa_inner, bg=self.CARD)
        qa_media.pack(fill=tk.X)
        self._qa_media_row = qa_media
        self._qa_play_btn, cap = self._make_qa_tile(qa_media, "▶", "play_pause", lambda: self._qa_desktop("play_pause"))
        self._qa_caps.append((cap, "play_pause"))
        self._qa_next_btn, cap = self._make_qa_tile(qa_media, "⏭", "next_track", lambda: self._qa_desktop("next"))
        self._qa_caps.append((cap, "next_track"))
        self._qa_voldn_btn, cap = self._make_qa_tile(qa_media, "🔉", "vol_down", lambda: self._vol_change("down"))
        self._qa_caps.append((cap, "vol_down"))
        self._qa_volup_btn, cap = self._make_qa_tile(qa_media, "🔊", "vol_up", lambda: self._vol_change("up"))
        self._qa_caps.append((cap, "vol_up"))
        self._qa_always_row = None
        self._qa_cam_btn = None
        self._qa_lock_btn = None
        self._qa_explorer_btn = None
        self._qa_buttons = (
            self._qa_play_btn, self._qa_next_btn, self._qa_voldn_btn, self._qa_volup_btn,
        )
        self._media_qa_on = False
        # Built off-screen; _sync_media_qa packs it only after real playback.

        # ═══ MIC ═══
        mic_card = tk.Frame(self.frame, bg=self.CARD, highlightthickness=1, highlightbackground=self.BORDER)
        mic_card.pack(fill=tk.X, padx=P, pady=GAP)
        self._mic_card = mic_card
        mic_inner = tk.Frame(mic_card, bg=self.CARD)
        mic_inner.pack(fill=tk.X, **INNER)

        mic_hdr = tk.Frame(mic_inner, bg=self.CARD)
        mic_hdr.pack(fill=tk.X)
        self._lbl_mic = tk.Label(mic_hdr, text=_t("mic"), fg=self.ACCENT, bg=self.CARD, font=("Segoe UI", 8, "bold"))
        self._lbl_mic.pack(side=tk.LEFT, padx=(0, 8))
        self._mic_mute_btn = tk.Button(
            mic_hdr, text=_t("mic_btn_mute"), fg=self.TEXT, bg=self.BG3,
            font=("Segoe UI", 7, "bold"), bd=0, padx=10, pady=3, cursor="hand2",
            activebackground=self.BG2, command=self._toggle_own_mic,
        )
        self._mic_mute_btn.pack(side=tk.RIGHT)
        self._bind_hover(self._mic_mute_btn, self.BG3, self.TEXT, self.ACCENT, "#ffffff")
        self._sync_mic_mute_btn()

        self.mic_devices = []
        self.mic_names = []
        self._mic_ignore = False
        self._mic_armed = False
        from services.voice_input import list_user_mics, default_input_id
        for i, name in list_user_mics():
            self.mic_devices.append(i)
            self.mic_names.append(name)

        self.mic_var = tk.StringVar()
        default_id = default_input_id()
        if default_id in self.mic_devices:
            self.mic_var.set(self.mic_names[self.mic_devices.index(default_id)])
        elif self.mic_names:
            self.mic_var.set(self.mic_names[0])

        self.mic_combo = ttk.Combobox(mic_hdr, textvariable=self.mic_var, values=self.mic_names,
                                       state="readonly", font=("Segoe UI", 8), width=1)
        self.mic_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.mic_combo.bind("<<ComboboxSelected>>", self.on_mic_change)
        self.mic_combo.bind("<MouseWheel>", lambda e: "break")
        self.mic_combo.bind("<ButtonPress-1>", self._on_mic_combo_press)
        self._mic_capture_ids = None
        self._mic_rescan_at = 0.0
        try:
            from services.voice_input import active_capture_ids
            self._mic_capture_ids = active_capture_ids()
        except Exception:
            pass

        # Waveform panel; "silent" sits on the canvas instead of an extra row.
        self._wave_height = 64
        self._wave_wrap = tk.Frame(mic_inner, bg=self.CARD)
        self._wave_wrap.pack(fill=tk.X, pady=(10, 0))
        self._wave_canvas = tk.Canvas(
            self._wave_wrap, height=self._wave_height, bg=self.BG3,
            highlightthickness=1, highlightbackground=self.BORDER, highlightcolor=self.BORDER,
        )
        self._wave_canvas.pack(fill=tk.X)
        self._wave_history = [0.0] * 96
        self._wave_line = None
        self._wave_rms_label = tk.Label(
            self._wave_wrap, text="", fg=self.DIM, bg=self.BG3,
            font=("Segoe UI", 7),
        )
        self._wave_rms_label.place(relx=1.0, rely=1.0, anchor="se", x=-8, y=-6)

        # ═══ YOU ═══
        you_card = tk.Frame(self.frame, bg=self.CARD, highlightthickness=1, highlightbackground=self.BORDER)
        you_card.pack(fill=tk.X, padx=P, pady=GAP)
        self._you_card = you_card
        self._conv_card = you_card
        you_inner = tk.Frame(you_card, bg=self.CARD)
        you_inner.pack(fill=tk.X, **INNER)

        you_hdr = tk.Frame(you_inner, bg=self.CARD)
        you_hdr.pack(fill=tk.X)
        self._lbl_you = tk.Label(you_hdr, text=_t("you"), fg=self.ACCENT, bg=self.CARD, font=("Segoe UI", 8, "bold"))
        self._lbl_you.pack(side=tk.LEFT)
        self._you_chevron = tk.Label(you_hdr, text="▾", fg=self.DIM, bg=self.CARD, font=("Segoe UI", 8), cursor="hand2")
        self._you_chevron.pack(side=tk.RIGHT)
        self._you_time = tk.Label(you_hdr, text="", fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._you_time.pack(side=tk.RIGHT, padx=(0, 6))

        self.trans_text = self._make_bubble(you_inner, self.ACCENT, pady=(8, 0), lines=3)
        self._you_body = self.trans_text.master.master
        self._init_placeholder(self.trans_text, "_trans_ph", _t("you_hint"))
        # Typed commands: same path as speech, also works with the mic muted.
        cmd_row = tk.Frame(you_inner, bg=self.CARD)
        cmd_row.pack(fill=tk.X, pady=(6, 0))
        self._cmd_row = cmd_row
        self.cmd_var = tk.StringVar()
        self.cmd_entry = tk.Entry(
            cmd_row, textvariable=self.cmd_var, font=("Segoe UI", 9), bg=self.BG3, fg=self.DIM,
            insertbackground=self.TEXT, bd=0, highlightthickness=1,
            highlightbackground=self.BORDER, highlightcolor=self.ACCENT,
        )
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 6))
        self._cmd_ph = True
        self.cmd_var.set(_t("type_hint"))
        self.cmd_entry.bind("<FocusIn>", self._cmd_focus_in)
        self.cmd_entry.bind("<FocusOut>", self._cmd_focus_out)
        self.cmd_entry.bind("<Return>", self._submit_typed)
        self.cmd_entry.bind("<Escape>", lambda e: self.root.focus_set())
        self._cmd_send = tk.Button(
            cmd_row, text="➤", fg=getattr(self, "ON_FG", "#ffffff"), bg=self.ACCENT,
            font=("Segoe UI", 9, "bold"), bd=0, padx=10, pady=3, cursor="hand2",
            activebackground=self.ACCENT2, activeforeground="#ffffff", command=self._submit_typed,
        )
        self._cmd_send.pack(side=tk.LEFT)
        self._bind_hover(self._cmd_send, self.ACCENT, "#ffffff", self.ACCENT2, "#ffffff")
        self._you_hdr = you_hdr
        for w in (you_hdr, self._lbl_you, self._you_chevron):
            w.bind("<Button-1>", lambda e: self._toggle_chat_collapsed())

        # ═══ Aemyos ═══
        davi_card = tk.Frame(self.frame, bg=self.CARD, highlightthickness=1, highlightbackground=self.BORDER)
        davi_card.pack(fill=tk.X, padx=P, pady=GAP)
        self._davi_card = davi_card
        davi_inner = tk.Frame(davi_card, bg=self.CARD)
        davi_inner.pack(fill=tk.X, **INNER)

        davi_hdr = tk.Frame(davi_inner, bg=self.CARD)
        davi_hdr.pack(fill=tk.X)
        self._lbl_davi = tk.Label(davi_hdr, text=_t("davi"), fg=self.ACCENT, bg=self.CARD, font=("Segoe UI", 8, "bold"))
        self._lbl_davi.pack(side=tk.LEFT)
        self._davi_chevron = tk.Label(davi_hdr, text="▾", fg=self.DIM, bg=self.CARD, font=("Segoe UI", 8), cursor="hand2")
        self._davi_chevron.pack(side=tk.RIGHT)
        self._davi_time = tk.Label(davi_hdr, text="", fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._davi_time.pack(side=tk.RIGHT, padx=(0, 6))

        self.response_text = self._make_bubble(davi_inner, self.ACCENT, pady=(8, 0), lines=6)
        self._davi_body = self.response_text.master.master
        self._init_placeholder(self.response_text, "_resp_ph", _t("davi_hint"))
        self._davi_hdr = davi_hdr
        self._chat_collapsed = False
        for w in (davi_hdr, self._lbl_davi, self._davi_chevron):
            w.bind("<Button-1>", lambda e: self._toggle_chat_collapsed())
        self._last_response = ""
        self._was_following_tts = False

        # ═══ DASHBOARD tiles — lists open in a side table ═══
        rt_card = tk.Frame(self.frame, bg=self.CARD, highlightthickness=1, highlightbackground=self.BORDER)
        rt_card.pack(fill=tk.X, padx=P, pady=(12, 0))
        self._rt_card = rt_card
        rt_inner = tk.Frame(rt_card, bg=self.CARD)
        rt_inner.pack(fill=tk.X, padx=10, pady=10)
        self._board_open = False
        self._board_kind = None
        self._last_rem_sig = None
        self._rem_alert_until = 0
        self._rem_text_labels = []
        self.reminders_label = None

        dash_row = tk.Frame(rt_inner, bg=self.CARD)
        dash_row.pack(fill=tk.X)
        self._dash_row = dash_row
        self._dash_qa_tiles = []
        self._rem_tile, self._lbl_rem, self._rem_count = self._make_dash_qa(
            dash_row, "⏰", "reminders", lambda: self._toggle_board("reminders"))
        self._task_tile, self._lbl_tasks, self._task_count = self._make_dash_qa(
            dash_row, "☰", "tasks", lambda: self._toggle_board("tasks"))
        self._stg_tile, self._lbl_stg_dash, self._stg_count = self._make_dash_qa(
            dash_row, "⚙", "settings", self._toggle_settings, show_count=False)
        self._lbl_rem_sub = None
        self._lbl_task_sub = None
        self._lbl_stg_sub = None
        self._build_dash_donate(rt_inner)

        self._clip_label = None
        self._last_clip_sig = None

        self._build_board_window()

        # ═══ SETTINGS (separate window, opens beside the overlay) ═══
        self._settings_open = False
        self._stg_win = tk.Toplevel(self.root)
        self._stg_win.withdraw()
        self._stg_win.overrideredirect(True)
        self._stg_win.attributes("-topmost", bool(ALWAYS_ON_TOP))
        self._stg_win.attributes("-alpha", max(0.6, min(1.0, OPACITY / 100.0)))
        self._stg_win.configure(bg=self.BORDER)

        stg_shell = tk.Frame(self._stg_win, bg=self.BG)
        stg_shell.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        stg_head_wrap = tk.Frame(stg_shell, bg=self.BG2)
        stg_head_wrap.pack(fill=tk.X)
        self._stg_head = stg_head_wrap
        tk.Frame(stg_head_wrap, bg=self.ACCENT, width=3).pack(side=tk.LEFT, fill=tk.Y)
        self._lbl_settings = tk.Label(stg_head_wrap, text=_t("settings"), fg=self.TEXT, bg=self.BG2,
                                       font=("Segoe UI", 11, "bold"))
        self._lbl_settings.pack(side=tk.LEFT, padx=(12, 0), pady=10)
        self._stg_close_btn = tk.Button(stg_head_wrap, text="×", fg=self.DIM, bg=self.BG2,
                                         font=("Segoe UI", 12), bd=0, padx=8, pady=0, cursor="hand2",
                                         activebackground="#3b1520", activeforeground=self.RED,
                                         command=self._close_settings)
        self._stg_close_btn.pack(side=tk.RIGHT, padx=(1, 8), pady=8)
        tk.Frame(stg_shell, bg=self.BORDER, height=1).pack(fill=tk.X)
        for w in (stg_head_wrap, self._lbl_settings):
            w.bind("<Button-1>", self._start_stg_drag)
            w.bind("<B1-Motion>", self._do_stg_drag)

        self._settings_body = tk.Frame(stg_shell, bg=self.CARD)
        self._settings_body.pack(fill=tk.BOTH, expand=True)
        self._settings_body.pack_propagate(False)

        stg_scroll_wrap = tk.Frame(self._settings_body, bg=self.CARD)
        stg_scroll_wrap.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._stg_canvas = tk.Canvas(stg_scroll_wrap, bg=self.CARD, highlightthickness=0, bd=0, height=220)
        self._stg_vsb = ttk.Scrollbar(stg_scroll_wrap, orient="vertical",
                                       command=self._stg_canvas.yview, style="Overlay.Vertical.TScrollbar")
        self._stg_canvas.configure(yscrollcommand=self._stg_vsb.set)
        self._stg_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        stg_body_inner = tk.Frame(self._stg_canvas, bg=self.CARD)
        self._stg_inner = stg_body_inner
        self._stg_inner_id = self._stg_canvas.create_window((0, 0), window=stg_body_inner, anchor="nw")

        def _on_stg_inner_cfg(_e=None):
            self._stg_canvas.configure(scrollregion=self._stg_canvas.bbox("all"))
            cw = self._stg_canvas.winfo_width()
            if cw > 1:
                self._stg_canvas.itemconfig(self._stg_inner_id, width=cw)
            self._sync_settings_scroll()

        stg_body_inner.bind("<Configure>", _on_stg_inner_cfg)
        self._stg_canvas.bind("<Configure>", lambda e: self._stg_canvas.itemconfig(self._stg_inner_id, width=e.width))

        from services.i18n import LANGUAGES, get_language
        self._stg_meta = tk.Label(
            stg_body_inner,
            text=f"Aemyos {DAVI_VERSION}",
            fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7),
        )
        self._stg_meta.pack(anchor="w", pady=(8, 0), padx=8)
        self._lbl_language = tk.Label(stg_body_inner, text=_t("language"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._lbl_language.pack(anchor="w", pady=(8, 0), padx=8)
        lang_names = list(LANGUAGES.values())
        lang_keys = list(LANGUAGES.keys())
        self._lang_var = tk.StringVar(value=LANGUAGES.get(get_language(), "English"))
        self._lang_combo = ttk.Combobox(stg_body_inner, textvariable=self._lang_var, values=lang_names,
                                         state="readonly", font=("Segoe UI", 8))
        self._lang_combo.pack(fill=tk.X, pady=(1, 0), padx=8)
        self._lang_combo.bind("<<ComboboxSelected>>", lambda e: self._on_language_change(lang_keys, lang_names))
        self._lang_combo.bind("<MouseWheel>", lambda e: "break")

        self._lbl_theme = tk.Label(stg_body_inner, text=_t("theme"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._lbl_theme.pack(anchor="w", pady=(8, 0), padx=8)
        theme_row = tk.Frame(stg_body_inner, bg=self.CARD)
        theme_row.pack(fill=tk.X, pady=(2, 0), padx=8)
        self._theme_dark_btn = tk.Button(theme_row, text=_t("theme_dark"), font=("Segoe UI", 8, "bold"),
                                          bd=0, padx=8, pady=5, cursor="hand2",
                                          command=lambda: self._apply_theme("dark"))
        self._theme_dark_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))
        self._theme_light_btn = tk.Button(theme_row, text=_t("theme_light"), font=("Segoe UI", 8, "bold"),
                                           bd=0, padx=8, pady=5, cursor="hand2",
                                           command=lambda: self._apply_theme("light"))
        self._theme_light_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self._refresh_theme_buttons()

        from services.i18n import get_voice_gender
        self._lbl_voice_gender = tk.Label(stg_body_inner, text=_t("voice_gender"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._lbl_voice_gender.pack(anchor="w", pady=(8, 0), padx=8)
        gender_row = tk.Frame(stg_body_inner, bg=self.CARD)
        gender_row.pack(fill=tk.X, pady=(2, 0), padx=8)
        self._gender_female_btn = tk.Button(gender_row, text=_t("voice_female"), font=("Segoe UI", 8, "bold"),
                                             bd=0, padx=8, pady=5, cursor="hand2",
                                             command=lambda: self._apply_voice_gender("female"))
        self._gender_female_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))
        self._gender_male_btn = tk.Button(gender_row, text=_t("voice_male"), font=("Segoe UI", 8, "bold"),
                                           bd=0, padx=8, pady=5, cursor="hand2",
                                           command=lambda: self._apply_voice_gender("male"))
        self._gender_male_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self._voice_gender = get_voice_gender()
        self._refresh_gender_buttons()

        # AI Model
        self._lbl_model = tk.Label(stg_body_inner, text=_t("ai_model"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._lbl_model.pack(anchor="w", pady=(6, 0), padx=8)
        from config import AVAILABLE_MODELS, MODEL, WHISPER_MODELS, WHISPER_MODEL
        model_names = list(AVAILABLE_MODELS.values())
        model_keys = list(AVAILABLE_MODELS.keys())
        self._model_var = tk.StringVar(value=AVAILABLE_MODELS.get(MODEL, model_names[0]))
        self._model_combo = ttk.Combobox(stg_body_inner, textvariable=self._model_var, values=model_names,
                                          state="readonly", font=("Segoe UI", 8))
        self._model_combo.pack(fill=tk.X, pady=(1, 0), padx=8)
        self._model_combo.bind("<<ComboboxSelected>>", lambda e: self._on_model_change(model_keys))
        self._model_combo.bind("<MouseWheel>", lambda e: "break")

        # Whisper Model
        self._lbl_whisper = tk.Label(stg_body_inner, text=_t("voice_model"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._lbl_whisper.pack(anchor="w", pady=(6, 0), padx=8)
        whisper_names = list(WHISPER_MODELS.values())
        whisper_keys = list(WHISPER_MODELS.keys())
        self._whisper_var = tk.StringVar(value=WHISPER_MODELS.get(WHISPER_MODEL, whisper_names[0]))
        self._whisper_combo = ttk.Combobox(stg_body_inner, textvariable=self._whisper_var, values=whisper_names,
                                            state="readonly", font=("Segoe UI", 8))
        self._whisper_combo.pack(fill=tk.X, pady=(1, 0), padx=8)
        self._whisper_combo.bind("<<ComboboxSelected>>", lambda e: self._on_whisper_change(whisper_keys))
        self._whisper_combo.bind("<MouseWheel>", lambda e: "break")

        from config import PROVIDER as _PROVIDER
        self._provider = "openrouter" if _PROVIDER == "openrouter" else "anthropic"
        self._lbl_provider = tk.Label(stg_body_inner, text=_t("provider"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._lbl_provider.pack(anchor="w", pady=(8, 0), padx=8)
        self._provider_btns = self._stg_segmented(
            stg_body_inner,
            (("anthropic", _t("provider_anthropic")), ("openrouter", _t("provider_openrouter"))),
            self._provider,
            self._on_provider_change,
        )
        self._provider_hint = tk.Label(
            stg_body_inner, text="", fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7),
            wraplength=240, justify="left",
        )
        self._provider_hint.pack(anchor="w", pady=(3, 0), padx=8)

        # API Keys
        self._lbl_anth = tk.Label(stg_body_inner, text=_t("anth_key"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._lbl_anth.pack(anchor="w", pady=(8, 0), padx=8)
        self._anth_key_var = tk.StringVar(value=self._mask_key(os.environ.get('ANTHROPIC_API_KEY', '')))
        self._anth_key_entry = tk.Entry(stg_body_inner, textvariable=self._anth_key_var, font=("Consolas", 8),
                                         bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT, bd=0,
                                         highlightthickness=0)
        self._anth_key_entry.pack(fill=tk.X, pady=(1, 0), ipady=3, padx=8)
        self._anth_key_entry.bind("<FocusIn>", lambda e: self._on_key_focus('anthropic'))
        self._anth_key_entry.bind("<Return>", lambda e: self._save_key('anthropic'))

        self._lbl_groq = tk.Label(stg_body_inner, text=_t("groq_key"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._lbl_groq.pack(anchor="w", pady=(6, 0), padx=8)
        self._groq_key_var = tk.StringVar(value=self._mask_key(os.environ.get('GROQ_API_KEY', '')))
        self._groq_key_entry = tk.Entry(stg_body_inner, textvariable=self._groq_key_var, font=("Consolas", 8),
                                         bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT, bd=0,
                                         highlightthickness=0)
        self._groq_key_entry.pack(fill=tk.X, pady=(1, 0), ipady=3, padx=8)
        self._groq_key_entry.bind("<FocusIn>", lambda e: self._on_key_focus('groq'))
        self._groq_key_entry.bind("<Return>", lambda e: self._save_key('groq'))

        self._lbl_or = tk.Label(stg_body_inner, text=_t("openrouter_key"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._or_key_var = tk.StringVar(value=self._mask_key(os.environ.get('OPENROUTER_API_KEY', '')))
        self._or_key_entry = tk.Entry(stg_body_inner, textvariable=self._or_key_var, font=("Consolas", 8),
                                      bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT, bd=0,
                                      highlightthickness=0)
        self._or_key_entry.bind("<FocusIn>", lambda e: self._on_key_focus('openrouter'))
        self._or_key_entry.bind("<Return>", lambda e: self._save_key('openrouter'))

        self._key_save_btn = tk.Button(stg_body_inner, text=_t("save_keys"), fg=self.ACCENT,
                                        bg=self.BG3, font=("Segoe UI", 7), bd=0, padx=6, pady=2,
                                        cursor="hand2", activebackground=self.ACCENT, activeforeground="white",
                                        command=self._save_all_keys)
        self._key_save_btn.pack(fill=tk.X, pady=(4, 0), padx=8)
        self._sync_provider_ui()

        self._stg_status = tk.Label(stg_body_inner, text="", fg=self.GREEN, bg=self.CARD, font=("Segoe UI", 7))
        self._stg_status.pack(anchor="w", pady=(2, 0), padx=8)

        self._build_agent_screen_setting(stg_body_inner)
        self._build_listen_setting(stg_body_inner)
        self._build_speech_setting(stg_body_inner)
        self._build_appearance_setting(stg_body_inner)
        self._build_memory_setting(stg_body_inner)
        self._build_notes_setting(stg_body_inner)
        self._build_routines_setting(stg_body_inner)
        self._build_watches_setting(stg_body_inner)
        self._build_history_setting(stg_body_inner)

        tk.Frame(stg_body_inner, bg=self.BORDER, height=1).pack(fill=tk.X, pady=(4, 3))
        self._lbl_donate = tk.Label(stg_body_inner, text=_t("donate_blurb"), fg=self.DIM, bg=self.CARD,
                                    font=("Segoe UI", 7), wraplength=360, justify=tk.LEFT, anchor="w")
        self._lbl_donate.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._donate_btn = tk.Button(stg_body_inner, text=_t("donate_btn"), fg=getattr(self, "ON_FG", "#ffffff"),
                                      bg=self.ACCENT, font=("Segoe UI", 7), bd=0, padx=6, pady=4,
                                      cursor="hand2", activebackground=self.ACCENT2,
                                      activeforeground=getattr(self, "ON_FG", "#ffffff"),
                                      command=self._open_donate)
        self._donate_btn.pack(fill=tk.X, padx=8, pady=(0, 6))
        self._install_ext_btn = tk.Button(stg_body_inner, text=_t("install_ext"), fg=self.CYAN,
                                           bg=self.BG3, font=("Segoe UI", 7), bd=0, padx=6, pady=2,
                                           cursor="hand2", activebackground=self.CYAN, activeforeground="black",
                                           command=self._open_extension_setup)
        self._install_ext_btn.pack(fill=tk.X, padx=8, pady=(0, 8))

        self._bind_settings_wheel(stg_body_inner)
        self._stg_canvas.bind("<MouseWheel>", self._on_settings_wheel)

        # ═══ FOOTER ═══
        footer = tk.Frame(self.frame, bg=self.BG)
        footer.pack(fill=tk.X, padx=P, pady=(8, 10))
        self._footer = footer
        self._footer_lbl = tk.Label(footer, text="", fg=self.DIM, bg=self.BG,
                 font=("Segoe UI", 7))
        self._footer_lbl.pack()
        self._refresh_footer()

        self._last_transcription = ""
        self._drag_data = {"x": 0, "y": 0}
        def _bind_drag_tree(w):
            if isinstance(w, tk.Button):
                return
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            for child in w.winfo_children():
                _bind_drag_tree(child)
        _bind_drag_tree(header_wrap)
        self._close_btn.bind("<ButtonRelease-1>", lambda e: self._close_app(), add="+")

        self._last_task_sig = None
        self._wave_idle_ticks = 0
        self._last_bridge_ok = None
        self.root.after(80, lambda: self._bind_overlay_wheel(self.frame))
        self.root.after(150, self._fit_window)
        self.root.after(120, self.update_loop)
        self.root.after(200, self._start_tray)
        self.root.after(250, self._kick_overlay_visible)
        self.root.after(400, self._maybe_ask_api_keys)

    def _set_palette(self, name):
        pal = dict(THEMES.get(name, THEMES["dark"]))
        self._theme_name = name if name in THEMES else "dark"
        self._palette = pal
        for key, value in pal.items():
            setattr(self, key, value)

    def _apply_ttk(self):
        style = ttk.Style()
        try:
            if str(style.theme_use()) != "clam":
                style.theme_use("clam")
        except Exception:
            style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=self.BG3, background=self.BG3,
                        foreground=self.TEXT, arrowcolor=self.DIM, borderwidth=0,
                        lightcolor=self.BG3, darkcolor=self.BG3)
        style.map("TCombobox", fieldbackground=[("readonly", self.BG3)],
                  selectbackground=[("readonly", self.BG3)], selectforeground=[("readonly", self.TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", self.BG3)
        self.root.option_add("*TCombobox*Listbox.foreground", self.TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", getattr(self, "ON_FG", "#ffffff"))
        style.configure(
            "Overlay.Vertical.TScrollbar",
            background=self.BG3,
            troughcolor=self.BG,
            borderwidth=0,
            arrowcolor=self.DIM,
            lightcolor=self.BG3,
            darkcolor=self.BG3,
        )
        style.map("Overlay.Vertical.TScrollbar", background=[("active", self.ACCENT)])
        style.configure(
            "Board.Treeview",
            background=self.BG3,
            foreground=self.TEXT,
            fieldbackground=self.BG3,
            rowheight=28,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Board.Treeview.Heading",
            background=self.BG2,
            foreground=self.DIM,
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Board.Treeview",
            background=[("selected", self.ACCENT)],
            foreground=[("selected", getattr(self, "ON_FG", "#ffffff"))],
        )
        style.map("Board.Treeview.Heading", background=[("active", self.BG3)])
        # tk.Scale paints its knob in the widget bg, which reads as a gap in the
        # trough; ttk gives us a knob we can colour independently.
        style.configure("Overlay.Horizontal.TScale",
                        background=self.ACCENT, troughcolor=self.BORDER,
                        bordercolor=self.BORDER, lightcolor=self.ACCENT,
                        darkcolor=self.ACCENT, borderwidth=0, gripcount=0,
                        sliderlength=16)
        style.map("Overlay.Horizontal.TScale",
                  background=[("active", self.ACCENT)],
                  troughcolor=[("active", self.BORDER)])

    def _remap_widget_colors(self, widget, cmap):
        # ttk internals break if we rewrite their colors; restyle them via _apply_ttk.
        if isinstance(widget, ttk.Widget):
            return
        for opt in (
            "bg", "fg", "activebackground", "activeforeground",
            "insertbackground", "highlightbackground", "highlightcolor",
        ):
            try:
                cur = str(widget.cget(opt))
            except tk.TclError:
                continue
            mapped = cmap.get(cur) or cmap.get(cur.lower())
            if mapped:
                try:
                    widget.config(**{opt: mapped})
                except tk.TclError:
                    pass
        if isinstance(widget, tk.Canvas):
            try:
                for item in widget.find_all():
                    for opt in ("fill", "outline"):
                        try:
                            cur = str(widget.itemcget(item, opt))
                        except tk.TclError:
                            continue
                        mapped = cmap.get(cur) or cmap.get(cur.lower())
                        if mapped:
                            widget.itemconfig(item, **{opt: mapped})
            except tk.TclError:
                pass
        try:
            children = widget.winfo_children()
        except tk.TclError:
            return
        for child in children:
            try:
                self._remap_widget_colors(child, cmap)
            except Exception:
                pass

    def _snapshot_combos(self):
        snaps = {}
        for attr in ("mic_combo", "_lang_combo", "_model_combo", "_whisper_combo"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                snaps[attr] = (w.get(), int(w.current()))
            except Exception:
                try:
                    snaps[attr] = (w.get(), -1)
                except Exception:
                    pass
        return snaps

    def _restore_combos(self, snaps):
        for attr, pair in (snaps or {}).items():
            w = getattr(self, attr, None)
            if w is None:
                continue
            value, idx = pair
            try:
                values = w.cget("values") or ()
                if attr == "mic_combo":
                    self._mic_ignore = True
                if 0 <= idx < len(values):
                    w.current(idx)
                    continue
            except Exception:
                pass
            finally:
                if attr == "mic_combo":
                    self.root.after_idle(lambda: setattr(self, "_mic_ignore", False))
            if value:
                try:
                    w.set(value)
                except Exception:
                    pass

    def _combo_index(self, combo, keys, names=None):
        try:
            idx = combo.current()
            if 0 <= idx < len(keys):
                return idx
        except Exception:
            pass
        if names is not None:
            try:
                name = combo.get()
                for i, n in enumerate(names):
                    if n == name:
                        return i
            except Exception:
                pass
        return -1

    # ── Settings sections ────────────────────────────────────────────
    def _stg_heading(self, parent, text, first=False):
        from services.i18n import t as _t
        lbl = tk.Label(parent, text=text, fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        lbl.pack(anchor="w", pady=((6 if first else 8), 0), padx=8)
        return lbl

    def _stg_segmented(self, parent, options, current, on_pick):
        """A row of mutually exclusive buttons; returns {value: button}."""
        row = tk.Frame(parent, bg=self.CARD)
        row.pack(fill=tk.X, pady=(2, 0), padx=8)
        buttons = {}
        for i, (value, label) in enumerate(options):
            btn = tk.Button(row, text=label, font=("Segoe UI", 8, "bold"),
                            bd=0, padx=6, pady=5, cursor="hand2",
                            command=lambda v=value: on_pick(v))
            btn.pack(side=tk.LEFT, expand=True, fill=tk.X,
                     padx=(0, 3) if i < len(options) - 1 else 0)
            buttons[value] = btn
        self._paint_segmented(buttons, current)
        return buttons

    def _paint_segmented(self, buttons, current):
        on_bg, on_fg = self.ACCENT, getattr(self, "ON_FG", "#ffffff")
        for value, btn in buttons.items():
            if value == current:
                btn.config(bg=on_bg, fg=on_fg, activebackground=on_bg, activeforeground=on_fg)
            else:
                btn.config(bg=self.BG3, fg=self.TEXT, activebackground=on_bg, activeforeground=on_fg)

    def _stg_divider(self, parent):
        tk.Frame(parent, bg=self.BORDER, height=1).pack(fill=tk.X, pady=(12, 0), padx=8)

    def _stg_slider(self, parent, label, from_, to, value, fmt, on_change):
        """Labelled slider. The current value lives in the heading instead of
        Tk's floating value box, which renders as a gap in the trough."""
        head = tk.Frame(parent, bg=self.CARD)
        head.pack(fill=tk.X, padx=8, pady=(8, 0))
        name = tk.Label(head, text=label, fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        name.pack(side=tk.LEFT)
        readout = tk.Label(head, text=fmt(value), fg=self.TEXT, bg=self.CARD, font=("Segoe UI", 7, "bold"))
        readout.pack(side=tk.RIGHT)

        scale = ttk.Scale(parent, from_=from_, to=to, orient=tk.HORIZONTAL,
                          style="Overlay.Horizontal.TScale",
                          command=lambda v: self._on_slider(readout, fmt, on_change, v))
        scale.set(int(value))
        scale.pack(fill=tk.X, padx=8, pady=(3, 0))
        scale.bind("<MouseWheel>", lambda e: "break")
        return scale, None, name

    def _on_slider(self, readout, fmt, on_change, raw):
        # ttk.Scale is continuous; snap so the readout never shows 63.7%.
        value = int(round(float(raw)))
        readout.config(text=fmt(value))
        on_change(value)

    def _stg_flash(self, message, color=None):
        try:
            self._stg_status.config(text=message, fg=color or self.GREEN)
            self.root.after(2500, lambda: self._stg_status.config(text=""))
        except Exception:
            pass

    def _build_agent_screen_setting(self, parent):
        from services.i18n import t as _t
        from config import SCREENSHOT_MONITOR
        self._stg_divider(parent)
        self._lbl_screen_mon = self._stg_heading(parent, _t("screen_monitor"))
        self._screen_mode = (SCREENSHOT_MONITOR or "cursor").lower()
        self._screen_btns = self._stg_segmented(
            parent,
            [("cursor", _t("monitor_cursor")), ("primary", _t("monitor_primary")), ("virtual", _t("monitor_all"))],
            self._screen_mode,
            self._apply_screen_mode,
        )

    def _apply_screen_mode(self, mode):
        from config import save_env
        import config
        from services.display import set_mode
        self._screen_mode = set_mode(mode)
        config.SCREENSHOT_MONITOR = self._screen_mode
        os.environ["DAVI_SCREENSHOT_MONITOR"] = self._screen_mode
        save_env(DAVI_SCREENSHOT_MONITOR=self._screen_mode)
        self._paint_segmented(self._screen_btns, self._screen_mode)
        from services.i18n import t as _t
        self._stg_flash(_t("settings_saved"))

    def _build_listen_setting(self, parent):
        from services.i18n import t as _t
        from config import LISTEN_MODE, PTT_KEY
        self._lbl_listen = self._stg_heading(parent, _t("listen_mode"))
        self._listen_mode = "ptt" if LISTEN_MODE == "ptt" else "always"
        self._listen_btns = self._stg_segmented(
            parent,
            [("always", _t("listen_always")), ("ptt", f"{_t('listen_ptt')} · {PTT_KEY.upper()}")],
            self._listen_mode,
            self._apply_listen_mode,
        )
        # Stays packed in place; re-packing after pack_forget would send it to
        # the bottom of the panel, far from the buttons it explains.
        self._ptt_hint = tk.Label(parent, fg=self.CYAN, bg=self.CARD, font=("Segoe UI", 7),
                                  anchor="w", justify=tk.LEFT, wraplength=360)
        self._ptt_hint.pack(fill=tk.X, padx=8, pady=(3, 0))
        self._refresh_ptt_hint()
        self._lbl_echo = tk.Label(parent, text=_t("room_audio"), fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7))
        self._lbl_echo.pack(anchor="w", pady=(10, 2), padx=8)
        try:
            from services.voice_input import room_audio
            room = room_audio()
        except Exception:
            room = "speakers"
        self._room_audio = room
        self._echo_btns = self._stg_segmented(
            parent,
            [("speakers", _t("room_speakers")), ("headphones", _t("room_headphones"))],
            self._room_audio,
            self._apply_room_audio,
        )
        self._echo_hint = tk.Label(parent, text=_t("room_speakers_hint" if room == "speakers" else "room_headphones_hint"),
                                   fg=self.DIM, bg=self.CARD,
                                   font=("Segoe UI", 7), anchor="w", justify=tk.LEFT, wraplength=360)
        self._echo_hint.pack(fill=tk.X, padx=8, pady=(3, 0))
        self._busy_voice_hint = tk.Label(parent, fg=self.DIM, bg=self.CARD, font=("Segoe UI", 7),
                                         anchor="w", justify=tk.LEFT, wraplength=360)
        self._busy_voice_hint.pack(fill=tk.X, padx=8, pady=(6, 0))
        self._refresh_busy_voice_hint()

    def _apply_listen_mode(self, mode):
        from config import save_env
        import config
        from services.voice_input import set_listen_mode
        from services.i18n import t as _t
        self._listen_mode = set_listen_mode(mode)
        config.LISTEN_MODE = self._listen_mode
        os.environ["DAVI_LISTEN_MODE"] = self._listen_mode
        save_env(DAVI_LISTEN_MODE=self._listen_mode)
        self._paint_segmented(self._listen_btns, self._listen_mode)
        self._refresh_ptt_hint()
        self._stg_flash(_t("settings_saved"))
        self._position_settings_window()

    def _apply_room_audio(self, mode):
        from config import save_env
        import config
        from services.i18n import t as _t
        from services.voice_input import set_room_audio
        self._room_audio = set_room_audio(mode)
        config.ROOM_AUDIO = self._room_audio
        config.ECHO_CANCEL = self._room_audio == "speakers"
        save_env(
            DAVI_ROOM_AUDIO=self._room_audio,
            DAVI_ECHO_CANCEL="1" if config.ECHO_CANCEL else "0",
        )
        try:
            if voice_processor_ref:
                voice_processor_ref._sync_speaker_tap()
        except Exception:
            pass
        self._paint_segmented(self._echo_btns, self._room_audio)
        hint = getattr(self, "_echo_hint", None)
        if hint is not None:
            key = "room_speakers_hint" if self._room_audio == "speakers" else "room_headphones_hint"
            hint.config(text=_t(key))
        self._stg_flash(_t("settings_saved"))
        self._position_settings_window()

    def _apply_echo_cancel(self, on):
        from config import save_env
        import config
        from services.i18n import t as _t
        from services.speaker_tap import set_echo_cancel
        self._echo_on = set_echo_cancel(bool(on))
        config.ECHO_CANCEL = self._echo_on
        save_env(DAVI_ECHO_CANCEL="1" if self._echo_on else "0")
        try:
            if voice_processor_ref:
                voice_processor_ref._sync_speaker_tap()
        except Exception:
            pass
        self._stg_flash(_t("settings_saved"))
        self._position_settings_window()

    def _refresh_ptt_hint(self):
        from services.i18n import t as _t
        from config import PTT_KEY
        hint = getattr(self, "_ptt_hint", None)
        if hint is None:
            return
        if self._listen_mode == "ptt":
            hint.config(text=_t("ptt_hint").replace("{key}", PTT_KEY.upper()), fg=self.CYAN)
        else:
            hint.config(text=_t("always_hint"), fg=self.DIM)
        self._refresh_busy_voice_hint()

    def _refresh_busy_voice_hint(self):
        from services.i18n import t as _t
        from config import PTT_KEY
        hint = getattr(self, "_busy_voice_hint", None)
        if hint is None:
            return
        hint.config(text=_t("busy_voice_hint").replace("{key}", PTT_KEY.upper()))

    def _build_speech_setting(self, parent):
        from services.i18n import t as _t
        import services.tts as tts
        self._stg_divider(parent)
        self._lbl_speech = self._stg_heading(parent, _t("speech"))
        self._speech_on = bool(tts.enabled)
        self._speech_btns = self._stg_segmented(
            parent,
            [(True, _t("speech_on")), (False, _t("speech_off"))],
            self._speech_on,
            self._apply_speech_enabled,
        )
        _, _, self._lbl_speech_rate = self._stg_slider(
            parent, _t("speech_rate"), -50, 50, tts.rate,
            lambda v: _t("speed_normal") if v == 0 else f"{v:+d}%", self._apply_speech_rate)

    def _apply_speech_enabled(self, on):
        import services.tts as tts
        from config import save_env
        from services.i18n import t as _t
        tts.configure(enabled_=on)
        self._speech_on = bool(on)
        save_env(DAVI_TTS_ENABLED="1" if on else "0")
        self._paint_segmented(self._speech_btns, self._speech_on)
        self._stg_flash(_t("settings_saved"))

    def _apply_speech_rate(self, value):
        import services.tts as tts
        tts.configure(rate_=value)
        self._debounced_save(DAVI_TTS_RATE=str(value))

    def _debounced_save(self, **kwargs):
        """Sliders fire on every pixel; only write .env once the user settles."""
        pending = getattr(self, "_pending_env", None) or {}
        pending.update(kwargs)
        self._pending_env = pending
        job = getattr(self, "_env_save_job", None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass

        def flush():
            from config import save_env
            data = getattr(self, "_pending_env", None) or {}
            self._pending_env = None
            self._env_save_job = None
            if data:
                save_env(**data)
        self._env_save_job = self.root.after(600, flush)

    def _build_appearance_setting(self, parent):
        from services.i18n import t as _t
        from config import OPACITY, ALWAYS_ON_TOP
        self._stg_divider(parent)
        self._lbl_appearance = self._stg_heading(parent, _t("appearance"))
        _, _, self._lbl_opacity = self._stg_slider(
            parent, _t("opacity"), 60, 100, OPACITY, lambda v: f"{v}%", self._apply_opacity)
        self._always_top = bool(ALWAYS_ON_TOP)
        self._top_btns = self._stg_segmented(
            parent,
            [(True, _t("always_on_top")), (False, _t("speech_off"))],
            self._always_top,
            self._apply_always_on_top,
        )
        self._reset_pos_btn = tk.Button(parent, text=_t("reset_position"), fg=self.TEXT, bg=self.BG3,
                                        font=("Segoe UI", 7), bd=0, padx=6, pady=3, cursor="hand2",
                                        activebackground=self.ACCENT, activeforeground=getattr(self, "ON_FG", "#ffffff"),
                                        command=self._reset_overlay_position)
        self._reset_pos_btn.pack(fill=tk.X, padx=8, pady=(4, 0))

    def _apply_opacity(self, value):
        try:
            self.root.attributes("-alpha", max(0.6, min(1.0, value / 100.0)))
            self._stg_win.attributes("-alpha", max(0.6, min(1.0, value / 100.0)))
        except Exception:
            pass
        self._debounced_save(DAVI_OPACITY=str(value))

    def _apply_always_on_top(self, on):
        from config import save_env
        from services.i18n import t as _t
        self._always_top = bool(on)
        try:
            self.root.attributes("-topmost", self._always_top)
            self._stg_win.attributes("-topmost", self._always_top)
            self._apply_app_window_style()
        except Exception:
            pass
        save_env(DAVI_ALWAYS_ON_TOP="1" if on else "0")
        self._paint_segmented(self._top_btns, self._always_top)
        self._stg_flash(_t("settings_saved"))

    def _reset_overlay_position(self):
        self._auto_height = True
        self._fit_window()
        if getattr(self, "_settings_open", False):
            self._position_settings_window()
        from services.i18n import t as _t
        self._stg_flash(_t("settings_saved"))

    def _build_memory_setting(self, parent):
        from services.i18n import t as _t
        self._stg_divider(parent)
        self._lbl_memory = self._stg_heading(parent, _t("memory_title"))
        self._mem_list = tk.Frame(parent, bg=self.CARD)
        self._mem_list.pack(fill=tk.X, padx=8, pady=(2, 0))
        self._mem_clear_btn = tk.Button(parent, text=_t("memory_clear"), fg=self.RED, bg=self.BG3,
                                        font=("Segoe UI", 7), bd=0, padx=6, pady=3, cursor="hand2",
                                        activebackground=self.RED, activeforeground="#ffffff",
                                        command=self._clear_memory)
        self._mem_clear_btn.pack(fill=tk.X, padx=8, pady=(4, 0))
        self._refresh_memory_list()

    def _refresh_memory_list(self):
        from services.i18n import t as _t
        for w in self._mem_list.winfo_children():
            w.destroy()
        learned = []
        life_rows = []
        try:
            from services.execute_funcs import load_memory
            from services.personal import list_life_rows
            learned = (load_memory().get("learned") or [])[-8:]
            life_rows = list_life_rows(12)
        except Exception:
            pass
        entries = []
        for line in life_rows:
            entries.append(line)
        for item in reversed(learned):
            text = item.get("text") if isinstance(item, dict) else str(item)
            if text:
                entries.append(text)
        if not entries:
            tk.Label(self._mem_list, text=_t("memory_empty"), fg=self.DIM, bg=self.CARD,
                     font=("Segoe UI", 7), anchor="w").pack(fill=tk.X)
            return
        for text in entries:
            row = tk.Frame(self._mem_list, bg=self.BG3)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=text[:70], fg=self.TEXT, bg=self.BG3, font=("Segoe UI", 7),
                     anchor="w", justify=tk.LEFT).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0), pady=3)
            tk.Button(row, text="×", fg=self.RED, bg=self.BG3, font=("Segoe UI", 8), bd=0,
                      padx=6, pady=0, cursor="hand2", activebackground=self.BG,
                      command=lambda t=text: self._forget_memory(t)).pack(side=tk.RIGHT)

    def _forget_memory(self, text):
        try:
            from services.execute_funcs import load_memory, save_memory
            from services.personal import forget_life_line
            mem = load_memory()
            mem["learned"] = [
                i for i in (mem.get("learned") or [])
                if (i.get("text") if isinstance(i, dict) else str(i)) != text
            ]
            save_memory(mem)
            forget_life_line(text)
        except Exception as e:
            print(f"[MEM] forget: {e}")
        self._refresh_memory_list()
        self._position_settings_window()

    def _clear_memory(self):
        from services.i18n import t as _t
        try:
            from services.execute_funcs import load_memory, save_memory
            mem = load_memory()
            mem["learned"] = []
            from services.personal import clear_life
            save_memory(mem)
            clear_life()
        except Exception as e:
            print(f"[MEM] clear: {e}")
        self._refresh_memory_list()
        self._stg_flash(_t("memory_cleared"), self.YELLOW)
        self._position_settings_window()

    def _stg_list_section(self, parent, title_key, clear_key, clear_cmd):
        """Heading + a rows container + a clear button, shared by the
        notes / routines / watchers / history panels."""
        from services.i18n import t as _t
        self._stg_divider(parent)
        title = self._stg_heading(parent, _t(title_key))
        rows = tk.Frame(parent, bg=self.CARD)
        rows.pack(fill=tk.X, padx=8, pady=(2, 0))
        btn = tk.Button(parent, text=_t(clear_key), fg=self.DIM, bg=self.BG3,
                        font=("Segoe UI", 7), bd=0, padx=6, pady=3, cursor="hand2",
                        activebackground=self.RED, activeforeground="#ffffff",
                        command=clear_cmd)
        btn.pack(fill=tk.X, padx=8, pady=(4, 0))
        return title, rows, btn

    def _fill_rows(self, container, entries, empty_text, on_delete=None, on_run=None):
        for w in container.winfo_children():
            w.destroy()
        if not entries:
            tk.Label(container, text=empty_text, fg=self.DIM, bg=self.CARD,
                     font=("Segoe UI", 7), anchor="w").pack(fill=tk.X)
            return
        for label, key in entries:
            row = tk.Frame(container, bg=self.BG3)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=label[:78], fg=self.TEXT, bg=self.BG3, font=("Segoe UI", 7),
                     anchor="w", justify=tk.LEFT).pack(side=tk.LEFT, fill=tk.X, expand=True,
                                                       padx=(6, 0), pady=3)
            if on_delete is not None:
                tk.Button(row, text="×", fg=self.RED, bg=self.BG3, font=("Segoe UI", 8), bd=0,
                          padx=6, pady=0, cursor="hand2", activebackground=self.BG,
                          command=lambda k=key: on_delete(k)).pack(side=tk.RIGHT)
            if on_run is not None:
                tk.Button(row, text="▶", fg=self.GREEN, bg=self.BG3, font=("Segoe UI", 8), bd=0,
                          padx=6, pady=0, cursor="hand2", activebackground=self.BG,
                          command=lambda k=key: on_run(k)).pack(side=tk.RIGHT)

    def _build_notes_setting(self, parent):
        self._lbl_notes, self._notes_rows, self._notes_clear_btn = self._stg_list_section(
            parent, "notes_title", "notes_clear", self._clear_notes)
        self.refresh_notes()

    def refresh_notes(self):
        from services.i18n import t as _t
        from services.personal import list_notes
        try:
            entries = [(n["text"], n["text"]) for n in list_notes(12)][::-1]
        except Exception:
            entries = []
        self._fill_rows(self._notes_rows, entries, _t("notes_empty"), self._forget_note)

    def _forget_note(self, text):
        from services.personal import delete_note
        delete_note(text)
        self.refresh_notes()
        self._position_settings_window()

    def _clear_notes(self):
        from services.personal import clear_notes
        clear_notes()
        self.refresh_notes()
        self._position_settings_window()

    def _build_routines_setting(self, parent):
        from services.i18n import t as _t
        self._lbl_routines, self._routines_rows, self._routines_clear_btn = self._stg_list_section(
            parent, "routines_title", "notes_clear", self._clear_routines)
        self.refresh_routines()
        # New-routine form: a name and one step per line; saved routines run by voice
        # ("run my morning routine"), by typing, or with the ▶ button.
        form = tk.Frame(parent, bg=self.CARD)
        form.pack(fill=tk.X, padx=8, pady=(8, 0))
        self._routine_name_var = tk.StringVar()
        self._routine_name = tk.Entry(
            form, textvariable=self._routine_name_var, font=("Segoe UI", 8), bg=self.BG3, fg=self.TEXT,
            insertbackground=self.TEXT, bd=0, highlightthickness=1, highlightbackground=self.BORDER,
            highlightcolor=self.ACCENT,
        )
        self._routine_name.pack(fill=tk.X, ipady=3)
        self._routine_name_hint = tk.Label(form, text=_t("routine_name_hint"), fg=self.DIM, bg=self.CARD,
                                           font=("Segoe UI", 7), anchor="w")
        self._routine_name_hint.pack(fill=tk.X)
        self._routine_steps = tk.Text(
            form, height=3, font=("Segoe UI", 8), bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT,
            bd=0, highlightthickness=1, highlightbackground=self.BORDER, highlightcolor=self.ACCENT,
            wrap=tk.WORD, padx=4, pady=3,
        )
        self._routine_steps.pack(fill=tk.X, pady=(4, 0))
        self._routine_steps_hint = tk.Label(form, text=_t("routine_steps_hint"), fg=self.DIM, bg=self.CARD,
                                            font=("Segoe UI", 7), anchor="w")
        self._routine_steps_hint.pack(fill=tk.X)
        self._routine_save_btn = tk.Button(
            form, text=_t("routine_save"), fg=getattr(self, "ON_FG", "#ffffff"), bg=self.ACCENT,
            font=("Segoe UI", 7, "bold"), bd=0, padx=8, pady=4, cursor="hand2",
            activebackground=self.ACCENT2, activeforeground="#ffffff", command=self._save_routine_from_form,
        )
        self._routine_save_btn.pack(fill=tk.X, pady=(4, 0))
        self._bind_settings_wheel(self._routine_steps)

    def _save_routine_from_form(self):
        from services.i18n import t as _t
        from services.personal import save_routine
        name = self._routine_name_var.get().strip()
        raw = self._routine_steps.get("1.0", tk.END)
        steps = [s.strip(" -•\t") for s in raw.replace(";", "\n").splitlines() if s.strip(" -•\t")]
        if not name or not steps:
            self._stg_flash(_t("routine_need_both"), color=self.RED)
            return
        save_routine(name, steps)
        self._routine_name_var.set("")
        self._routine_steps.delete("1.0", tk.END)
        self.refresh_routines()
        self._position_settings_window()
        self._stg_flash(_t("routine_saved"))

    def _run_routine(self, name):
        enqueue_remote_command(f"run routine {name}")
        try:
            self._close_settings()
        except Exception:
            pass

    def refresh_routines(self):
        from services.i18n import t as _t
        from services.personal import list_routines
        try:
            entries = [(f"{r['name']} — {len(r['steps'])}", r["name"]) for r in list_routines()]
        except Exception:
            entries = []
        self._fill_rows(self._routines_rows, entries, _t("routines_empty"), self._forget_routine,
                        on_run=self._run_routine)

    def _forget_routine(self, name):
        from services.personal import delete_routine
        delete_routine(name)
        self.refresh_routines()
        self._position_settings_window()

    def _clear_routines(self):
        from services.personal import list_routines, delete_routine
        for row in list_routines():
            delete_routine(row["name"])
        self.refresh_routines()
        self._position_settings_window()

    def _build_watches_setting(self, parent):
        self._lbl_watches, self._watches_rows, self._watches_clear_btn = self._stg_list_section(
            parent, "watches_title", "watches_clear", self._clear_watches)
        self.refresh_watches()

    def refresh_watches(self):
        from services.i18n import t as _t
        try:
            from services import watchers
            entries = [(w["query"] or w["kind"], w["id"]) for w in watchers.list_watches()]
        except Exception:
            entries = []
        self._fill_rows(self._watches_rows, entries, _t("watches_empty"), self._cancel_watch)

    def _cancel_watch(self, wid):
        from services import watchers
        watchers.cancel_watch(wid)
        self.refresh_watches()
        self._position_settings_window()

    def _clear_watches(self):
        from services import watchers
        watchers.clear_watches()
        self.refresh_watches()
        self._position_settings_window()

    def _build_history_setting(self, parent):
        self._lbl_history, self._history_rows, self._history_clear_btn = self._stg_list_section(
            parent, "history_title", "history_clear", self._clear_history)
        self.refresh_history()

    def refresh_history(self):
        from services.i18n import t as _t
        from services.personal import list_history
        try:
            rows = list_history(14)
        except Exception:
            rows = []
        who = {"you": _t("you"), "davi": _t("davi")}
        entries = [(f"{who.get(r['role'], r['role'])}: {r['text']}", None) for r in rows][::-1]
        self._fill_rows(self._history_rows, entries, _t("history_empty"))

    def _clear_history(self):
        from services.personal import clear_history
        clear_history()
        self.refresh_history()
        self._position_settings_window()

    def set_dictation(self, on):
        """Dictation silently swallows every utterance, so the overlay has to
        say so loudly or the user will think Aemyos stopped responding."""
        from services.i18n import t as _t
        badge = getattr(self, "_dictation_badge", None)
        if badge is None:
            return
        if on:
            badge.config(text=f"  {_t('dictation_badge')}  ")
            badge.pack(side=tk.LEFT, padx=(8, 0))
        else:
            badge.pack_forget()

    def _refresh_theme_buttons(self):
        if not hasattr(self, "_theme_dark_btn"):
            return
        on_bg, on_fg = self.ACCENT, getattr(self, "ON_FG", "#ffffff")
        off_bg, off_fg = self.BG3, self.TEXT
        if self._theme_name == "dark":
            self._theme_dark_btn.config(bg=on_bg, fg=on_fg, activebackground=on_bg, activeforeground=on_fg)
            self._theme_light_btn.config(bg=off_bg, fg=off_fg, activebackground=self.ACCENT, activeforeground=on_fg)
        else:
            self._theme_light_btn.config(bg=on_bg, fg=on_fg, activebackground=on_bg, activeforeground=on_fg)
            self._theme_dark_btn.config(bg=off_bg, fg=off_fg, activebackground=self.ACCENT, activeforeground=on_fg)

    def _refresh_gender_buttons(self):
        if not hasattr(self, "_gender_female_btn"):
            return
        on_bg, on_fg = self.ACCENT, getattr(self, "ON_FG", "#ffffff")
        off_bg, off_fg = self.BG3, self.TEXT
        gender = getattr(self, "_voice_gender", None)
        if not gender:
            from services.i18n import get_voice_gender
            gender = get_voice_gender()
            self._voice_gender = gender
        if gender == "male":
            self._gender_male_btn.config(bg=on_bg, fg=on_fg, activebackground=on_bg, activeforeground=on_fg)
            self._gender_female_btn.config(bg=off_bg, fg=off_fg, activebackground=self.ACCENT, activeforeground=on_fg)
        else:
            self._gender_female_btn.config(bg=on_bg, fg=on_fg, activebackground=on_bg, activeforeground=on_fg)
            self._gender_male_btn.config(bg=off_bg, fg=off_fg, activebackground=self.ACCENT, activeforeground=on_fg)

    def _apply_voice_gender(self, gender):
        from services.i18n import set_voice_gender, t as _t
        self._voice_gender = set_voice_gender(gender)
        self._refresh_gender_buttons()
        # The face should match the voice, so swap the avatar set too.
        try:
            self._load_face_images()
            self._current_face = None
            self._update_agent_orb(speaking=False)
        except Exception as exc:
            print(f"[FACE] gender swap: {exc}")
        try:
            self._stg_status.config(text=_t("voice_gender_saved"), fg=self.GREEN)
            self.root.after(2500, lambda: self._stg_status.config(text=""))
        except Exception:
            pass

    def _apply_theme(self, name, persist=True):
        if name not in THEMES:
            name = "dark"
        old = dict(getattr(self, "_palette", THEMES["dark"]))
        self._set_palette(name)
        cmap = {}
        for key, old_v in old.items():
            if key == "ON_FG":
                continue
            cmap[old_v] = self._palette[key]
            cmap[old_v.lower()] = self._palette[key]
        snaps = self._snapshot_combos()
        try:
            self._remap_widget_colors(self.root, cmap)
        except Exception as exc:
            print(f"[THEME] remap: {exc}")
        self.root.configure(bg=self.BG)
        self._apply_ttk()
        self._restore_combos(snaps)
        self._set_header_logo()
        for cell, ic, cap in getattr(self, "_qa_tiles", []):
            try:
                cell.config(bg=self.BG3)
                ic.config(bg=self.BG3, fg=self.ACCENT)
                cap.config(bg=self.BG3, fg=self.TEXT)
            except tk.TclError:
                pass
        for cell, ic, cap, pill in getattr(self, "_dash_qa_tiles", []):
            try:
                cell.config(bg=self.BG3)
                ic.config(bg=self.BG3, fg=self.ACCENT)
                cap.config(bg=self.BG3, fg=self.TEXT)
                if pill is not None:
                    pill.config(bg=self.BG3, fg=self.ACCENT)
            except tk.TclError:
                pass
        self._paint_dash_donate()
        self._refresh_theme_buttons()
        self._refresh_gender_buttons()
        self._sync_face_action_buttons()
        for attr, current in (("_screen_btns", "_screen_mode"), ("_listen_btns", "_listen_mode"),
                              ("_speech_btns", "_speech_on"), ("_top_btns", "_always_top"),
                              ("_provider_btns", "_provider"), ("_echo_btns", "_room_audio")):
            btns = getattr(self, attr, None)
            if btns:
                self._paint_segmented(btns, getattr(self, current, None))
        if persist:
            try:
                from config import save_env
                save_env(DAVI_THEME=name)
                os.environ["DAVI_THEME"] = name
            except Exception:
                os.environ["DAVI_THEME"] = name
            try:
                from services.i18n import t as _t
                self._stg_status.config(text=_t("theme_saved"), fg=self.GREEN)
                self.root.after(2500, lambda: self._stg_status.config(text=""))
            except Exception:
                pass

    def _on_settings_wheel(self, event):
        try:
            cls = str(event.widget.winfo_class())
        except Exception:
            cls = ""
        if cls in ("TCombobox", "Combobox"):
            return "break"
        if getattr(self, "_stg_canvas", None) is None:
            return
        self._stg_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _bind_settings_wheel(self, widget):
        widget.bind("<MouseWheel>", self._on_settings_wheel)
        for child in widget.winfo_children():
            self._bind_settings_wheel(child)

    def _attach_tooltip(self, widget, text):
        """Hover label for icon-only buttons. `text` may be a callable so the
        tooltip follows the UI language without rebuilding the widget."""
        def show(_e=None):
            self._hide_tooltip()
            try:
                label = text() if callable(text) else text
                tip = tk.Toplevel(self.root)
                tip.overrideredirect(True)
                tip.attributes("-topmost", True)
                tip.configure(bg=self.BORDER)
                tk.Label(tip, text=label, fg=self.TEXT, bg=self.BG2,
                         font=("Segoe UI", 8), padx=8, pady=3).pack(padx=1, pady=1)
                tip.update_idletasks()
                x = widget.winfo_rootx() + widget.winfo_width() // 2 - tip.winfo_width() // 2
                y = widget.winfo_rooty() + widget.winfo_height() + 4
                tip.geometry(f"+{x}+{y}")
                self._tooltip = tip
            except Exception:
                self._tooltip = None

        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", lambda e: self._hide_tooltip(), add="+")
        widget.bind("<Button-1>", lambda e: self._hide_tooltip(), add="+")

    def _hide_tooltip(self):
        tip = getattr(self, "_tooltip", None)
        if tip is not None:
            try:
                tip.destroy()
            except Exception:
                pass
            self._tooltip = None

    def _toggle_settings(self, _e=None):
        if getattr(self, "_settings_open", False):
            self._close_settings()
        else:
            self._open_settings()

    def _open_settings(self):
        self._close_board()
        self._settings_open = True
        for refresh in (self._refresh_memory_list, self.refresh_notes,
                        self.refresh_routines, self.refresh_watches, self.refresh_history):
            try:
                refresh()
            except Exception as exc:
                print(f"[SETTINGS] refresh: {exc}")
        try:
            self._stg_win.deiconify()
            self._stg_win.lift()
            self._stg_win.attributes("-topmost", True)
            self._position_settings_window()
        except Exception as e:
            print(f"[UI] settings open: {e}")

    def _close_settings(self):
        self._settings_open = False
        try:
            self._stg_win.withdraw()
        except Exception:
            pass

    def _position_settings_window(self):
        """Dock the settings window next to the overlay, sized to its own content."""
        if not getattr(self, "_settings_open", False):
            return
        win = getattr(self, "_stg_win", None)
        if win is None:
            return
        win.update_idletasks()
        wx, wy, ww, wh = _desktop_work_area()
        margin = getattr(self, "_margin", 10)
        w = max(self._min_width, self._win_width)
        head_h = self._stg_head.winfo_reqheight() + 1
        wanted = self._stg_inner.winfo_reqheight() + head_h + 8
        h = max(280, min(wanted, wh - 2 * margin))
        self._stg_canvas.configure(height=max(200, h - head_h - 8))
        self._stg_canvas.configure(scrollregion=self._stg_canvas.bbox("all"))
        self._sync_settings_scroll()

        # Prefer the left side of the overlay; fall back to the right if there is no room.
        ox, oy = self.root.winfo_x(), self.root.winfo_y()
        x = ox - w - 8
        if x < wx + margin:
            x = ox + self.root.winfo_width() + 8
            if x + w > wx + ww - margin:
                x = max(wx + margin, wx + ww - w - margin)
        y = oy
        if y + h > wy + wh - margin:
            y = max(wy + margin, wy + wh - margin - h)
        win.geometry(f"{w}x{h}+{x}+{y}")
        self._position_board_window()

    def _start_stg_drag(self, event):
        self._stg_drag = {"x": event.x_root, "y": event.y_root,
                          "wx": self._stg_win.winfo_x(), "wy": self._stg_win.winfo_y()}

    def _do_stg_drag(self, event):
        d = getattr(self, "_stg_drag", None)
        if not d:
            return
        self._stg_win.geometry(
            f"+{d['wx'] + event.x_root - d['x']}+{d['wy'] + event.y_root - d['y']}")

    def _fit_window(self):
        self.root.update_idletasks()
        wx, wy, ww, wh = _desktop_work_area()
        self._work = (wx, wy, ww, wh)
        margin = getattr(self, "_margin", 10)
        max_h = max(self._min_height, wh - 2 * margin)
        max_w = min(max(self._win_width, self._min_width), ww - 2 * margin)

        if getattr(self, "_auto_height", True):
            content_h = self.frame.winfo_reqheight() + 8
            h = min(max(content_h, self._min_height), max_h)
        else:
            h = min(max(self.root.winfo_height(), self._min_height), max_h)

        w = min(max(self.root.winfo_width() if self.root.winfo_width() > 1 else max_w, self._win_width), max_w)
        if getattr(self, "_compact", False):
            w = min(self._win_width, max_w)

        # Auto height: stay top-right in the work area. Never slide down under the taskbar.
        if getattr(self, "_auto_height", True):
            x = wx + ww - w - margin
            y = wy + margin
        else:
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            if x < wx + margin:
                x = wx + margin
            if x + w > wx + ww - margin:
                x = max(wx + margin, wx + ww - w - margin)
            if y < wy + margin:
                y = wy + margin
            if y + h > wy + wh - margin:
                y = wy + wh - h - margin

        if y + h > wy + wh - margin:
            y = wy + wh - h - margin
        if y < wy + margin:
            y = wy + margin
            h = min(h, wh - 2 * margin)
        h = min(h, max_h)
        if y + h > wy + wh - margin:
            h = max(self._min_height, wy + wh - margin - y)

        geo = f"{w}x{h}+{x}+{y}"
        if geo != getattr(self, "_last_geo", None):
            self._last_geo = geo
            self.root.geometry(geo)
            self.root.update_idletasks()
        self._sync_main_scroll()
        self._apply_overlay_density()
        self._position_board_window()

    def _schedule_fit(self):
        job = getattr(self, "_fit_job", None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        try:
            self._fit_job = self.root.after(90, self._fit_window)
        except Exception:
            pass

    def _make_qa_tile(self, parent, icon, i18n_key, command, expand=True):
        """Square shortcut: purple icon on top, label under it."""
        from services.i18n import t as _t
        cell = tk.Frame(parent, bg=self.BG3, cursor="hand2")
        cell.pack(side=tk.LEFT, expand=expand, fill=tk.BOTH, padx=3)
        ic = tk.Label(cell, text=icon, fg=self.ACCENT, bg=self.BG3,
                      font=("Segoe UI Symbol", 13), cursor="hand2")
        ic.pack(pady=(10, 0))
        cap = tk.Label(cell, text=_t(i18n_key), fg=self.TEXT, bg=self.BG3,
                       font=("Segoe UI", 7), cursor="hand2")
        cap.pack(pady=(2, 10))

        def click(_e=None):
            command()

        def enter(_e=None):
            for w in (cell, ic, cap):
                try:
                    w.config(bg=self.BORDER)
                except tk.TclError:
                    pass
            try:
                ic.config(fg=self.ACCENT2)
            except tk.TclError:
                pass

        def leave(_e=None):
            for w in (cell, ic, cap):
                try:
                    w.config(bg=self.BG3)
                except tk.TclError:
                    pass
            try:
                ic.config(fg=self.ACCENT)
            except tk.TclError:
                pass

        for w in (cell, ic, cap):
            w.bind("<Button-1>", click)
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
        getattr(self, "_qa_tiles", []).append((cell, ic, cap))
        return cell, cap

    def _make_dash_qa(self, parent, icon, title_key, command, show_count=True):
        """Same square shortcut as Camera, so Reminders/Tasks/Settings
        shrink and grow with the window instead of stacking into a scrollbar."""
        from services.i18n import t as _t
        cell = tk.Frame(parent, bg=self.BG3, cursor="hand2")
        cell.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=3)
        ic = tk.Label(cell, text=icon, fg=self.ACCENT, bg=self.BG3,
                      font=("Segoe UI Symbol", 13), cursor="hand2")
        ic.pack(pady=(10, 0))
        cap = tk.Label(cell, text=_t(title_key), fg=self.TEXT, bg=self.BG3,
                       font=("Segoe UI", 7), cursor="hand2")
        cap.pack(pady=(2, 0))
        pill = None
        if show_count:
            pill = tk.Label(cell, text="0", fg=self.ACCENT, bg=self.BG3,
                            font=("Segoe UI", 8, "bold"), cursor="hand2")
            pill.pack(pady=(0, 8))
        else:
            tk.Label(cell, text="", fg=self.BG3, bg=self.BG3,
                     font=("Segoe UI", 8), cursor="hand2").pack(pady=(0, 8))

        def click(_e=None):
            command()

        def enter(_e=None):
            for w in (cell, ic, cap, pill):
                if w is None:
                    continue
                try:
                    w.config(bg=self.BORDER)
                except tk.TclError:
                    pass
            try:
                ic.config(fg=self.ACCENT2)
            except tk.TclError:
                pass

        def leave(_e=None):
            for w in (cell, ic, cap, pill):
                if w is None:
                    continue
                try:
                    w.config(bg=self.BG3)
                except tk.TclError:
                    pass
            try:
                ic.config(fg=self.ACCENT)
                if pill is not None:
                    pill.config(fg=self.ACCENT)
            except tk.TclError:
                pass

        widgets = [cell, ic, cap]
        if pill is not None:
            widgets.append(pill)
        for w in widgets:
            w.bind("<Button-1>", click)
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
        getattr(self, "_dash_qa_tiles", []).append((cell, ic, cap, pill))
        return cell, cap, pill

    def _build_dash_donate(self, parent):
        from services.i18n import t as _t
        fire = "#ff4a1a"
        row = tk.Frame(parent, bg=self.BG3, cursor="hand2",
                       highlightthickness=1, highlightbackground=fire)
        row.pack(fill=tk.X, pady=(8, 0))
        inner = tk.Frame(row, bg=self.BG3, cursor="hand2")
        inner.pack(anchor="center", pady=5)
        cv_l = tk.Canvas(inner, width=42, height=42, bg=self.BG3, highlightthickness=0, cursor="hand2")
        cv_l.pack(side=tk.LEFT, padx=(2, 4))
        col = tk.Frame(inner, bg=self.BG3, cursor="hand2")
        col.pack(side=tk.LEFT)
        cap = tk.Label(col, text=_t("dash_donate"), fg=self.TEXT, bg=self.BG3,
                       font=("Segoe UI", 9, "bold"), cursor="hand2",
                       anchor="center", justify="center")
        cap.pack()
        sub = tk.Label(col, text="Amir · Adem · Yousef", fg=self.DIM, bg=self.BG3,
                       font=("Segoe UI", 7), cursor="hand2",
                       anchor="center", justify="center")
        sub.pack()
        cv_r = tk.Canvas(inner, width=42, height=42, bg=self.BG3, highlightthickness=0, cursor="hand2")
        cv_r.pack(side=tk.LEFT, padx=(4, 2))
        self._dash_donate = row
        self._dash_donate_inner = inner
        self._dash_donate_cv = cv_l
        self._dash_donate_cv2 = cv_r
        self._lbl_dash_donate = cap
        self._lbl_dash_donate_sub = sub
        self._dash_donate_col = col
        self._donate_pulse_t = 0.0
        self._donate_click_lock = False
        self._donate_particles = []

        def click(_e=None):
            self._on_dash_donate_click()

        hover_widgets = (row, inner, cv_l, cv_r, col, cap, sub)

        def enter(_e=None):
            for w in hover_widgets:
                try:
                    w.config(bg=self.BORDER)
                except tk.TclError:
                    pass
            try:
                row.config(highlightbackground=fire)
            except tk.TclError:
                pass

        def leave(_e=None):
            try:
                x, y = row.winfo_pointerxy()
                rx, ry = row.winfo_rootx(), row.winfo_rooty()
                if rx <= x <= rx + row.winfo_width() and ry <= y <= ry + row.winfo_height():
                    return
            except tk.TclError:
                pass
            self._paint_dash_donate()

        for w in hover_widgets:
            w.bind("<Button-1>", click)
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
        self._start_donate_pulse()

    def _heart_color(self):
        return "#ff4a1a"

    def _heart_poly(self, cx, cy, scale):
        import math
        pts = []
        for i in range(0, 360, 5):
            t = math.radians(i)
            x = 16 * (math.sin(t) ** 3)
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            pts.extend((cx + x * scale, cy + y * scale))
        return pts

    def _draw_fire_heart(self, cv, t, phase=0.0):
        """Layered heart plus rising embers — looks like it is on fire."""
        import math
        if cv is None:
            return
        try:
            cv.delete("fire")
        except tk.TclError:
            return
        beat = abs(math.sin(t * 1.2 + phase)) ** 0.5
        flick = 0.05 * math.sin(t * 9.4 + phase * 2.7)
        scale = 0.58 + 0.22 * beat + flick
        if getattr(self, "_donate_click_lock", False):
            scale = 0.86
        cx, cy = 21, 23
        layers = (
            (scale * 1.18, "#5a0c08"),
            (scale * 1.04, "#c41410"),
            (scale * 0.86, "#ff4a12"),
            (scale * 0.62, "#ffb020"),
            (scale * 0.34, "#fff2b0"),
        )
        try:
            glow_r = 16 + 5 * beat
            cv.create_oval(
                cx - glow_r, cy - glow_r + 2, cx + glow_r, cy + glow_r + 4,
                fill="#3a0806", outline="", tags="fire",
            )
            for sc, color in layers:
                cv.create_polygon(*self._heart_poly(cx, cy, sc), fill=color, outline="", tags="fire")
            for i in range(5):
                wobble = math.sin(t * (4.2 + i * 0.7) + phase + i)
                fx = cx + (i - 2) * 3.4 + wobble * 2.2
                rise = (t * 22 + i * 13 + phase * 9) % 28
                fy = cy + 10 - rise
                h = 5.5 + 2.4 * abs(math.sin(t * 3 + i)) * (1.0 - rise / 28.0)
                w = 1.6 + 0.5 * abs(wobble)
                if rise < 6:
                    col = "#ffef9a"
                elif rise < 14:
                    col = "#ff8a1a"
                else:
                    col = "#ff3a12"
                cv.create_oval(fx - w, fy - h, fx + w, fy + 1.2, fill=col, outline="", tags="fire")
            for i in range(4):
                spark_t = (t * 1.7 + i * 0.9 + phase) % 1.0
                sx = cx + math.sin(t * 2.4 + i * 1.8 + phase) * (6 + i)
                sy = cy - 6 - spark_t * 16
                r = 1.1 + 0.6 * (1.0 - spark_t)
                cv.create_oval(sx - r, sy - r, sx + r, sy + r, fill="#ffe680", outline="", tags="fire")
        except tk.TclError:
            pass

    def _draw_donate_heart(self, scale):
        t = float(getattr(self, "_donate_pulse_t", 0.0) or 0.0)
        self._draw_fire_heart(getattr(self, "_dash_donate_cv", None), t, 0.0)
        self._draw_fire_heart(getattr(self, "_dash_donate_cv2", None), t, 1.15)

    def _start_donate_pulse(self):
        job = getattr(self, "_donate_pulse_job", None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._tick_donate_heart()

    def _tick_donate_heart(self):
        left = getattr(self, "_dash_donate_cv", None)
        right = getattr(self, "_dash_donate_cv2", None)
        if left is None and right is None:
            return
        try:
            if left is not None and not left.winfo_exists():
                return
        except tk.TclError:
            return
        self._donate_pulse_t = float(getattr(self, "_donate_pulse_t", 0.0)) + 0.16
        self._draw_donate_heart(0.0)
        self._donate_pulse_job = self.root.after(40, self._tick_donate_heart)

    def _on_dash_donate_click(self):
        if getattr(self, "_donate_click_lock", False):
            return
        self._donate_click_lock = True
        self._burst_donate_hearts()
        self.root.after(420, self._finish_dash_donate_click)

    def _finish_dash_donate_click(self):
        self._donate_click_lock = False
        try:
            self._open_donate()
        except Exception:
            pass

    def _burst_donate_hearts(self):
        import math
        import random
        self._clear_donate_floaters()
        host = getattr(self, "_rt_card", None) or getattr(self, "frame", None)
        col = getattr(self, "_dash_donate_col", None)
        if host is None or col is None:
            return
        try:
            hx = host.winfo_rootx()
            hy = host.winfo_rooty()
            cx = col.winfo_rootx() - hx + col.winfo_width() // 2
            cy = col.winfo_rooty() - hy + col.winfo_height() // 2
        except tk.TclError:
            return
        pink = self._heart_color()
        particles = []
        for i in range(9):
            ang = math.radians(-125 + i * 18 + random.uniform(-10, 10))
            speed = random.uniform(2.6, 5.0)
            size = random.choice((11, 13, 15, 17, 20))
            lbl = tk.Label(host, text="♥", fg=pink, bg=self.CARD, bd=0,
                           font=("Segoe UI Symbol", size))
            x, y = cx - size // 2, cy - size // 2
            try:
                lbl.place(x=x, y=y)
            except tk.TclError:
                continue
            particles.append({
                "w": lbl, "x": float(x), "y": float(y),
                "vx": math.cos(ang) * speed,
                "vy": math.sin(ang) * speed - 1.4,
                "life": 16 + i,
            })
        self._donate_particles = particles
        self._tick_donate_burst()

    def _tick_donate_burst(self):
        parts = getattr(self, "_donate_particles", None) or []
        live = []
        for p in parts:
            p["life"] -= 1
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vy"] -= 0.18
            w = p["w"]
            if p["life"] <= 0:
                try:
                    w.destroy()
                except tk.TclError:
                    pass
                continue
            try:
                w.place(x=int(p["x"]), y=int(p["y"]))
                live.append(p)
            except tk.TclError:
                pass
        self._donate_particles = live
        if live:
            self._donate_burst_job = self.root.after(28, self._tick_donate_burst)

    def _clear_donate_floaters(self):
        job = getattr(self, "_donate_burst_job", None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
            self._donate_burst_job = None
        for p in getattr(self, "_donate_particles", None) or []:
            try:
                p["w"].destroy()
            except Exception:
                pass
        self._donate_particles = []

    def _paint_dash_donate(self):
        row = getattr(self, "_dash_donate", None)
        if row is None:
            return
        cv = getattr(self, "_dash_donate_cv", None)
        cv2 = getattr(self, "_dash_donate_cv2", None)
        inner = getattr(self, "_dash_donate_inner", None)
        col = getattr(self, "_dash_donate_col", None)
        cap = getattr(self, "_lbl_dash_donate", None)
        sub = getattr(self, "_lbl_dash_donate_sub", None)
        fire = self._heart_color()
        for w in (row, inner, cv, cv2, col, cap, sub):
            if w is None:
                continue
            try:
                w.config(bg=self.BG3)
            except tk.TclError:
                pass
        try:
            if row is not None:
                row.config(highlightbackground=fire, highlightthickness=1)
            if cap is not None:
                cap.config(fg=self.TEXT)
            if sub is not None:
                sub.config(fg=self.DIM)
        except tk.TclError:
            pass

    def _bind_hover(self, widget, bg, fg, bg_h, fg_h):
        widget.bind("<Enter>", lambda e: widget.config(bg=bg_h, fg=fg_h))
        widget.bind("<Leave>", lambda e: widget.config(bg=bg, fg=fg))

    def _refresh_footer(self):
        from services.i18n import t as _t
        self._footer_lbl.config(text=_t("footer"))

    def _make_bubble(self, parent, accent, pady=(6, 0), lines=2):
        """Fixed-height speech bubble. Long replies scroll inside instead of
        stretching the overlay and shoving TASKS down the panel."""
        lines = max(2, int(lines or 2))
        wrap = tk.Frame(parent, bg=self.BG3)
        wrap.pack(fill=tk.X, pady=pady)
        tk.Frame(wrap, bg=accent, width=2).pack(side=tk.LEFT, fill=tk.Y)
        shell = tk.Frame(wrap, bg=self.BG3, height=lines * 18 + 16)
        shell.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        shell.pack_propagate(False)
        txt = tk.Text(shell, height=lines, bg=self.BG3, fg=self.TEXT, font=("Segoe UI", 9),
                      wrap=tk.WORD, bd=0, highlightthickness=0, padx=10, pady=6)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.bind("<MouseWheel>", lambda e: txt.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        return txt

    def _set_bubble(self, widget, flag, text):
        """Replace the bubble contents. Never append — appending grew the
        widget and the rest of the dashboard slid down with it."""
        try:
            widget.config(state=tk.NORMAL)
            self._drop_placeholder(widget, flag)
            widget.delete("1.0", tk.END)
            snippet = (text or "").replace("\n", " ").strip()
            widget.insert("1.0", snippet)
            widget.see("1.0")
            widget.config(state=tk.DISABLED)
            if widget is getattr(self, "response_text", None):
                self._was_following_tts = False
            stamp = datetime.now().strftime("%I:%M %p").lstrip("0")
            if widget is getattr(self, "trans_text", None) and getattr(self, "_you_time", None):
                self._you_time.config(text=stamp)
            elif widget is getattr(self, "response_text", None) and getattr(self, "_davi_time", None):
                self._davi_time.config(text=stamp)
        except Exception:
            pass

    def _scroll_response_to_frac(self, p):
        widget = getattr(self, "response_text", None)
        if widget is None:
            return
        try:
            content = widget.get("1.0", "end-1c")
        except Exception:
            return
        if not content:
            return
        total = len(content)
        idx = int(total * max(0.0, min(1.0, float(p))))
        ahead = min(total, idx + 16)
        try:
            widget.see(f"1.0+{ahead}c")
        except Exception:
            pass

    def _scroll_response_with_speech(self):
        self._was_following_tts = True
        try:
            from services.tts import playback_progress
            p = float(playback_progress() or 0.0)
        except Exception:
            return
        self._scroll_response_to_frac(p)

    def _scroll_response_to_end(self):
        widget = getattr(self, "response_text", None)
        if widget is None:
            return
        try:
            widget.see("end")
        except Exception:
            pass

    def _init_placeholder(self, widget, flag, text):
        """Show a dim hint inside an empty conversation bubble."""
        try:
            widget.tag_configure("placeholder", foreground=self.DIM)
            widget.config(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            widget.insert("1.0", text, "placeholder")
            widget.config(state=tk.DISABLED)
            setattr(self, flag, True)
        except Exception:
            setattr(self, flag, False)

    def _drop_placeholder(self, widget, flag):
        """Clear the hint the first time real content arrives."""
        if getattr(self, flag, False):
            try:
                widget.delete("1.0", tk.END)
            except Exception:
                pass
            setattr(self, flag, False)

    def _hex_rgb(self, color):
        h = str(color).lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) < 6:
            return (128, 128, 128)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def _mix_rgb(self, a, b, t):
        t = max(0.0, min(1.0, t))
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    def _circularize_face(self, img, size=160):
        from PIL import Image, ImageChops, ImageDraw, ImageFilter
        try:
            img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((1, 1, size - 2, size - 2), fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(0.9))
            img.putalpha(ImageChops.multiply(mask, img.split()[-1]))
            return img
        except Exception:
            try:
                return img.convert("RGBA").resize((size, size), Image.LANCZOS)
            except Exception:
                return None

    def _placeholder_face(self, size=168):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            fill = (*self._hex_rgb(self.BG3), 255)
            ring = (*self._hex_rgb(self.ACCENT), 255)
        except Exception:
            fill, ring = (26, 29, 39, 255), (124, 147, 255, 255)
        pad = 2
        draw.ellipse((pad, pad, size - pad - 1, size - pad - 1), fill=fill, outline=ring, width=4)
        cx = cy = size / 2.0
        hr = size * 0.18
        draw.ellipse((cx - hr, cy - hr * 1.4, cx + hr, cy - hr * 0.2), fill=ring)
        draw.ellipse((cx - hr * 1.55, cy + hr * 0.25, cx + hr * 1.55, size - pad * 4), fill=ring)
        return img

    def _try_open_face(self, path, size=168):
        from PIL import Image
        try:
            if not os.path.isfile(path):
                return None
            return self._circularize_face(Image.open(path), size)
        except Exception as exc:
            print(f"[FACE] skip {os.path.basename(path)}: {exc}")
            return None

    def _face_variant(self):
        try:
            from services.i18n import get_voice_gender
            return "male" if get_voice_gender() == "male" else "female"
        except Exception:
            return "female"

    def _load_face_images(self):
        from PIL import Image, ImageTk
        face_dir = _res_path("assets")
        variant = self._face_variant()
        self._face_pil = {}
        self._face_images = {}
        self._face_loaded_variant = variant
        for name in ["idle", "blink", "speak_1", "speak_2", "speak_3"]:
            # Gendered set first; the unprefixed files are the original female
            # frames and stay as the fallback so nothing breaks without assets.
            candidates = [f"face_{variant}_{name}.png", f"face_{variant}_{name}.jpg"]
            if variant == "female":
                candidates += [f"face_{name}.png", f"face_{name}.jpg", f"davi_face_{name}.png"]
            for fname in candidates:
                img = self._try_open_face(os.path.join(face_dir, fname))
                if img is not None:
                    self._face_pil[name] = img
                    break
        if "idle" not in self._face_pil:
            for fname in ("face_base.jpg", "face_base.png", "face_idle.jpg"):
                img = self._try_open_face(os.path.join(face_dir, fname))
                if img is not None:
                    self._face_pil["idle"] = img
                    break
        if "idle" not in self._face_pil:
            try:
                self._face_pil["idle"] = self._placeholder_face(168)
                print("[FACE] using placeholder (assets missing)")
            except Exception as exc:
                print(f"[FACE] placeholder failed: {exc}")
        idle = self._face_pil.get("idle")
        if idle is not None:
            try:
                self._face_images["idle"] = ImageTk.PhotoImage(
                    idle.resize((self._orb_size, self._orb_size), Image.LANCZOS)
                )
            except Exception as exc:
                print(f"[FACE] photo idle: {exc}")

    def _show_face(self, name):
        if name in self._face_images and name != self._current_face:
            try:
                self.face_label.config(image=self._face_images[name], bg=self.CARD)
                self._current_face = name
            except Exception:
                pass

    def _fallback_face(self):
        try:
            if not getattr(self, "_face_pil", None):
                self._load_face_images()
            idle = getattr(self, "_face_images", {}).get("idle")
            if idle is not None:
                self.face_label.config(image=idle, bg=self.CARD, text="")
                self._current_face = "idle"
                return
            self.face_label.config(image="", text="Aemyos", fg=self.ACCENT, bg=self.CARD)
        except Exception as exc:
            print(f"[FACE] fallback failed: {exc}")

    def _pick_face_frame(self, mode, tick, energy):
        if mode == "speak" and any(k in self._face_pil for k in ("speak_1", "speak_2", "speak_3")):
            cycle = []
            for key in ("speak_1", "speak_2", "speak_3", "speak_2"):
                if key in self._face_pil:
                    cycle.append(key)
            if cycle:
                speed = 0.28 + energy * 0.55
                return cycle[int(tick * speed) % len(cycle)]
        blinking = tick < getattr(self, "_blink_until", 0)
        if blinking and "blink" in self._face_pil and mode != "speak":
            return "blink"
        return "idle" if "idle" in self._face_pil else next(iter(self._face_pil), None)

    def _update_agent_orb(self, speaking=False):
        """Photoreal talking head + thin theme ring (never a lens/orb)."""
        try:
            import math
            from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageTk

            if not getattr(self, "_face_pil", None):
                self._load_face_images()
            if not self._face_pil:
                try:
                    self._face_pil["idle"] = self._placeholder_face(168)
                except Exception:
                    self._fallback_face()
                    return

            self._orb_tick += 1
            tick = self._orb_tick
            status = ""
            try:
                status = (self.status_label.cget("text") or "").lower()
            except Exception:
                pass

            if speaking:
                mode = "speak"
            elif any(k in status for k in ("think", "düşün", "pensa", "denke", "réfléch", "analyz", "execut", "uygul", "step", "adım", "schritt", "étape", "paso")):
                mode = "think"
            elif any(k in status for k in ("listen", "dinli", "escuch", "höre", "écoute", "jecoute")):
                mode = "listen"
            else:
                mode = "idle"

            if mode == "speak":
                raw = 0.48 + 0.32 * abs(math.sin(tick * 0.37)) + 0.18 * abs(math.sin(tick * 0.91))
            elif mode == "listen" and voice_processor_ref:
                raw = min(1.0, 0.22 + voice_processor_ref.get_audio_level() * 2.2)
            elif mode == "think":
                raw = 0.22 + 0.10 * abs(math.sin(tick * 0.11))
            else:
                raw = 0.12

            self._orb_energy = self._orb_energy * 0.64 + raw * 0.36
            energy = self._orb_energy

            next_blink = getattr(self, "_next_blink_tick", 28)
            if mode != "speak" and tick >= next_blink:
                self._blink_until = tick + 2
                self._next_blink_tick = tick + 32 + int(18 * abs(math.sin(tick * 0.17)))
            frame_name = self._pick_face_frame(mode, tick, energy)
            face = self._face_pil.get(frame_name) or self._face_pil.get("idle")
            if face is None:
                return

            if mode == "think":
                face = ImageEnhance.Brightness(face).enhance(0.78)
                face = ImageEnhance.Color(face).enhance(0.88)
            elif mode == "listen":
                face = ImageEnhance.Contrast(face).enhance(1.06)

            size = self._orb_size
            hi = 2
            canvas_s = size * hi
            img = Image.new("RGBA", (canvas_s, canvas_s), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            cx = cy = canvas_s / 2.0

            accent = self._hex_rgb(self.ACCENT)
            cyan = self._hex_rgb(self.CYAN)
            dim = self._hex_rgb(self.DIM)
            white = (255, 255, 255)

            if mode == "listen":
                ring = cyan
                glow = cyan
            elif mode == "speak":
                ring = self._mix_rgb(accent, cyan, 0.25)
                glow = ring
            elif mode == "think":
                ring = self._mix_rgb(dim, accent, 0.35)
                glow = accent
            else:
                ring = dim
                glow = accent

            compact = getattr(self, "_compact", False)
            fill = 0.86 if compact else 0.62
            ring_k = 0.455 if compact else 0.34
            if mode == "speak":
                target_scale = (1.14 + 0.05 * energy) if compact else (1.33 + 0.07 * energy)
            else:
                target_scale = 1.0
            self._orb_scale += (target_scale - self._orb_scale) * 0.22
            scale = self._orb_scale

            breathe = 1.0 + 0.016 * math.sin(tick * 0.048)
            face_d = int(canvas_s * fill * scale * breathe)
            ring_r = int(canvas_s * ring_k * scale)
            # Keep the blurred halo inside the canvas at full zoom, or it clips flat.
            glow_r = min(ring_r + (7 if mode == "speak" else 5), int(canvas_s / 2) - 5)

            if mode in ("speak", "listen"):
                glow_a = 40 + int(energy * (70 if mode == "speak" else 50))
                glow_layer = Image.new("RGBA", (canvas_s, canvas_s), (0, 0, 0, 0))
                gdraw = ImageDraw.Draw(glow_layer)
                gdraw.ellipse(
                    [cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r],
                    fill=(*glow, max(0, min(255, glow_a))),
                )
                img = Image.alpha_composite(img, glow_layer.filter(ImageFilter.GaussianBlur(3.2)))
                draw = ImageDraw.Draw(img)

            fx = int(cx - face_d / 2)
            fy = int(cy - face_d / 2)
            face_scaled = face.resize((face_d, face_d), Image.LANCZOS)
            img.paste(face_scaled, (fx, fy), face_scaled)

            ring_w = 3 if mode == "idle" else 4
            draw.ellipse(
                [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
                outline=(*ring, 230 if mode != "idle" else 170),
                width=ring_w,
            )
            if mode == "listen":
                draw.ellipse(
                    [cx - ring_r - 3, cy - ring_r - 3, cx + ring_r + 3, cy + ring_r + 3],
                    outline=(*self._mix_rgb(cyan, white, 0.25), 90 + int(energy * 80)),
                    width=2,
                )

            img = img.resize((size, size), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._orb_photo = photo
            self.face_label.config(image=photo, bg=self.CARD)
            self._current_face = frame_name
        except Exception as exc:
            print(f"[FACE] fallback: {exc}")
            self._fallback_face()

    def _apply_ui_language(self):
        from services.i18n import t as _t
        pairs = [
            ("_lbl_mic", "mic"),
            ("_lbl_controls", "controls"),
            ("_lbl_you", "you"),
            ("_lbl_davi", "davi"),
            ("_lbl_rem", "reminders"),
            ("_lbl_tasks", "tasks"),
            ("_lbl_stg_dash", "settings"),
            ("_lbl_dash_donate", "dash_donate"),
            ("_lbl_rem_sub", "rem_sub"),
            ("_lbl_task_sub", "task_sub"),
            ("_lbl_stg_sub", "stg_sub"),
            ("_lbl_settings", "settings"),
            ("_lbl_language", "language"),
            ("_lbl_theme", "theme"),
            ("_lbl_voice_gender", "voice_gender"),
            ("_lbl_echo", "room_audio"),
            ("_lbl_model", "ai_model"),
            ("_lbl_whisper", "voice_model"),
            ("_lbl_provider", "provider"),
            ("_lbl_anth", "anth_key"),
            ("_lbl_groq", "groq_key"),
            ("_lbl_or", "openrouter_key"),
        ]
        for attr, key in pairs:
            w = getattr(self, attr, None)
            if w is not None:
                w.config(text=_t(key))
        self._refresh_footer()
        self._theme_dark_btn.config(text=_t("theme_dark"))
        self._theme_light_btn.config(text=_t("theme_light"))
        if hasattr(self, "_gender_female_btn"):
            self._gender_female_btn.config(text=_t("voice_female"))
            self._gender_male_btn.config(text=_t("voice_male"))
            self._refresh_gender_buttons()
        if getattr(self, "_provider_btns", None):
            try:
                self._provider_btns["anthropic"].config(text=_t("provider_anthropic"))
                self._provider_btns["openrouter"].config(text=_t("provider_openrouter"))
            except Exception:
                pass
            self._paint_segmented(self._provider_btns, getattr(self, "_provider", "anthropic"))
        self._sync_provider_ui()
        for cap, key in getattr(self, "_qa_caps", []):
            try:
                cap.config(text=_t(key))
            except tk.TclError:
                pass
        if getattr(self, "_trans_ph", False):
            self._init_placeholder(self.trans_text, "_trans_ph", _t("you_hint"))
        if getattr(self, "_resp_ph", False):
            self._init_placeholder(self.response_text, "_resp_ph", _t("davi_hint"))
        self._key_save_btn.config(text=_t("save_keys"))
        self._install_ext_btn.config(text=_t("install_ext"))
        if getattr(self, "_donate_btn", None):
            self._donate_btn.config(text=_t("donate_btn"))
        if getattr(self, "_lbl_donate", None):
            self._lbl_donate.config(text=_t("donate_blurb"))
        if getattr(self, "_stg_meta", None) is not None:
            self._stg_meta.config(text=f"{DAVI_VERSION}  ·  {_t('single_instance')}")
        self._ext_btn.config(text=_t("setup"))
        self._sync_chrome_bridge_ui()
        self._sync_face_id_ui(force=True)
        if getattr(self, "_last_action_raw", ""):
            self.set_last_action(self._last_action_raw)
        self._last_rem_sig = None
        self._refresh_reminders(force=True)
        self._last_task_sig = None
        self._refresh_tasks()
        self._sync_board_headings()
        self._sync_mic_mute_btn()
        if getattr(self, "_face_hide_btn", None) is not None:
            self._face_hide_btn.config(text=_t("face_min"))
        if getattr(self, "_face_stop_btn", None) is not None:
            self._face_stop_btn.config(text=_t("face_stop"))
        self._sync_face_action_buttons()
        if getattr(self, "_echo_hint", None) is not None:
            room = getattr(self, "_room_audio", "speakers")
            key = "room_speakers_hint" if room == "speakers" else "room_headphones_hint"
            self._echo_hint.config(text=_t(key))
        if getattr(self, "_echo_btns", None):
            try:
                self._echo_btns["speakers"].config(text=_t("room_speakers"))
                self._echo_btns["headphones"].config(text=_t("room_headphones"))
            except Exception:
                pass
            self._paint_segmented(self._echo_btns, getattr(self, "_room_audio", "speakers"))
        self._refresh_ptt_hint()

    def _on_language_change(self, lang_keys, lang_names):
        idx = self._combo_index(self._lang_combo, lang_keys, lang_names)
        if idx < 0:
            name = self._lang_var.get()
            code = next((k for k, v in zip(lang_keys, lang_names) if v == name), "en")
        else:
            code = lang_keys[idx]
        from services.i18n import apply_runtime_language, t as _t
        apply_runtime_language(code, voice_processor_ref)
        try:
            from services.execute_funcs import load_memory, save_memory
            mem = load_memory()
            mem.setdefault("preferences", {})["language"] = code
            save_memory(mem)
        except Exception:
            pass
        self._apply_ui_language()
        self._stg_status.config(text=_t("lang_saved"), fg=self.GREEN)
        update_agent_response(_t("lang_saved"))
        self.root.after(3000, lambda: self._stg_status.config(text=""))

    def _vol_change(self, direction):
        try:
            from services.smart_features import volume_up, volume_down
            if direction == "up":
                threading.Thread(target=volume_up, args=(5,), daemon=True).start()
            else:
                threading.Thread(target=volume_down, args=(5,), daemon=True).start()
        except Exception:
            pass

    def _sync_media_qa(self, force=False):
        """Play / next / vol only while music or a video is actually playing."""
        try:
            from services.busy_audio import playback_controls_wanted
            want = bool(playback_controls_wanted())
        except Exception:
            want = False
        was = bool(getattr(self, "_media_qa_on", False))
        if not force and want == was:
            return
        self._media_qa_on = want
        card = getattr(self, "_qa_card", None)
        if card is None:
            return
        try:
            if want:
                P = getattr(self, "_pad", 12)
                kw = dict(fill=tk.X, padx=P, pady=(8, 0))
                if not getattr(self, "_compact", False):
                    mic = getattr(self, "_mic_card", None)
                    if mic is not None:
                        kw["before"] = mic
                card.pack(**kw)
            else:
                card.pack_forget()
        except tk.TclError:
            return
        if want and not was and not getattr(self, "_compact", False):
            self._set_chat_collapsed(True)
        elif not want and was:
            self._set_chat_collapsed(False)
        self._schedule_fit()

    def _toggle_chat_collapsed(self):
        self._set_chat_collapsed(not getattr(self, "_chat_collapsed", False))

    def _set_chat_collapsed(self, collapsed):
        """Fold YOU / Aemyos bubbles so CONTROLS does not stack into them."""
        collapsed = bool(collapsed)
        self._chat_collapsed = collapsed
        mark = "▸" if collapsed else "▾"
        for chev in (getattr(self, "_you_chevron", None), getattr(self, "_davi_chevron", None)):
            if chev is not None:
                try:
                    chev.config(text=mark)
                except tk.TclError:
                    pass
        for body in (getattr(self, "_you_body", None), getattr(self, "_davi_body", None)):
            if body is None:
                continue
            try:
                if collapsed:
                    body.pack_forget()
                elif not body.winfo_ismapped():
                    body.pack(fill=tk.X, pady=(8, 0))
            except tk.TclError:
                pass
        self._schedule_fit()

    def _qa_camera(self):
        try:
            from services.webcam import is_on
            action = "camera_off" if is_on() else "camera_on"
        except Exception:
            action = "camera_on"
        self._qa_desktop(action)

    def _qa_desktop(self, action):
        def _run():
            try:
                from services.smart_features import run_fast_desktop
                from services.i18n import t as _t
                ok, key, extra = run_fast_desktop(action)
                msg = _t(key) if key else action
                if extra:
                    msg = f"{msg} · {extra}"
                if ok:
                    add_task(msg)
                    complete_current_task()
                update_agent_response(msg, speak=False)
            except Exception as e:
                print(f"[QA] {action}: {e}")
        threading.Thread(target=_run, daemon=True).start()

    def _open_donate(self):
        import webbrowser
        webbrowser.open("https://aemyos.ai/donate.html")

    def _open_extension_setup(self):
        """Chrome setup on the public site (download + extension steps)."""
        import webbrowser
        webbrowser.open("https://aemyos.ai/download.html#chrome-ext")

    def _mask_key(self, key):
        if not key or len(key) < 12:
            return key or ''
        return key[:8] + '•' * 16 + key[-4:]

    def _on_key_focus(self, which):
        if which == 'anthropic':
            real = os.environ.get('ANTHROPIC_API_KEY', '')
            if real:
                self._anth_key_var.set(real)
        elif which == 'groq':
            real = os.environ.get('GROQ_API_KEY', '')
            if real:
                self._groq_key_var.set(real)
        elif which == 'openrouter':
            real = os.environ.get('OPENROUTER_API_KEY', '')
            if real:
                self._or_key_var.set(real)

    def _save_key(self, which):
        self._save_all_keys()

    def _save_all_keys(self):
        from config import save_env
        from services.i18n import t as _t
        updates = {}
        anth = self._anth_key_var.get().strip()
        groq = self._groq_key_var.get().strip()
        or_key = self._or_key_var.get().strip() if getattr(self, "_or_key_var", None) else ""
        if anth and '•' not in anth:
            updates['ANTHROPIC_API_KEY'] = anth
            os.environ['ANTHROPIC_API_KEY'] = anth
        if groq and '•' not in groq:
            updates['GROQ_API_KEY'] = groq
            os.environ['GROQ_API_KEY'] = groq
        if or_key and '•' not in or_key:
            updates['OPENROUTER_API_KEY'] = or_key
            os.environ['OPENROUTER_API_KEY'] = or_key
        if updates:
            save_env(**updates)
            self._stg_status.config(text=_t("keys_saved"), fg=self.GREEN)
            self._anth_key_var.set(self._mask_key(os.environ.get('ANTHROPIC_API_KEY', '')))
            self._groq_key_var.set(self._mask_key(os.environ.get('GROQ_API_KEY', '')))
            if getattr(self, "_or_key_var", None):
                self._or_key_var.set(self._mask_key(os.environ.get('OPENROUTER_API_KEY', '')))
        else:
            self._stg_status.config(text=_t("no_key_changes"), fg=self.DIM)
        self.root.after(4000, lambda: self._stg_status.config(text=""))

    def _on_provider_change(self, value):
        from config import save_env
        from services.i18n import t as _t
        self._provider = "openrouter" if value == "openrouter" else "anthropic"
        save_env(DAVI_PROVIDER=self._provider)
        self._paint_segmented(self._provider_btns, self._provider)
        self._sync_provider_ui()
        self._stg_flash(_t("provider_saved"))
        self._position_settings_window()

    def _sync_provider_ui(self):
        from services.i18n import t as _t
        using_or = getattr(self, "_provider", "anthropic") == "openrouter"
        hint = _t("provider_hint_openrouter") if using_or else _t("provider_hint_anthropic")
        if getattr(self, "_provider_hint", None) is not None:
            self._provider_hint.config(text=hint)
        if getattr(self, "_lbl_whisper", None) is not None:
            self._lbl_whisper.config(text=_t("voice_model_or") if using_or else _t("voice_model"))
        direct = (
            getattr(self, "_lbl_anth", None),
            getattr(self, "_anth_key_entry", None),
            getattr(self, "_lbl_groq", None),
            getattr(self, "_groq_key_entry", None),
        )
        or_ws = (
            getattr(self, "_lbl_or", None),
            getattr(self, "_or_key_entry", None),
        )
        show, hide = (or_ws, direct) if using_or else (direct, or_ws)
        for w in hide:
            if w is not None:
                w.pack_forget()
        save_btn = getattr(self, "_key_save_btn", None)
        if save_btn is None:
            return
        for w in show:
            if w is None:
                continue
            is_label = w in (
                getattr(self, "_lbl_anth", None),
                getattr(self, "_lbl_groq", None),
                getattr(self, "_lbl_or", None),
            )
            kwargs = {"fill": tk.X, "padx": 8, "before": save_btn}
            if is_label:
                kwargs["anchor"] = "w"
                kwargs["pady"] = (8, 0) if w in (self._lbl_anth, self._lbl_or) else (6, 0)
            else:
                kwargs["pady"] = (1, 0)
                kwargs["ipady"] = 3
            w.pack(**kwargs)

    def _on_model_change(self, model_keys):
        names = None
        try:
            names = list(self._model_combo.cget("values") or ())
        except Exception:
            pass
        idx = self._combo_index(self._model_combo, model_keys, names)
        if 0 <= idx < len(model_keys):
            new_model = model_keys[idx]
            from config import save_env
            from services.i18n import t as _t
            save_env(DAVI_MODEL=new_model)
            os.environ['DAVI_MODEL'] = new_model
            import config
            config.MODEL = new_model
            self._stg_status.config(text=f"{_t('model_saved')} · {new_model}", fg=self.GREEN)
            self.root.after(3000, lambda: self._stg_status.config(text=""))

    def _on_whisper_change(self, whisper_keys):
        names = None
        try:
            names = list(self._whisper_combo.cget("values") or ())
        except Exception:
            pass
        idx = self._combo_index(self._whisper_combo, whisper_keys, names)
        if 0 <= idx < len(whisper_keys):
            new_wm = whisper_keys[idx]
            from config import save_env
            from services.i18n import t as _t
            save_env(DAVI_WHISPER_MODEL=new_wm)
            os.environ['DAVI_WHISPER_MODEL'] = new_wm
            self._stg_status.config(text=f"{_t('whisper_saved')} · {new_wm}", fg=self.YELLOW)
            self.root.after(3000, lambda: self._stg_status.config(text=""))

    def _take_screenshot(self):
        try:
            save_screenshot()
            from services.i18n import t as _t
            update_agent_response(_t("shot_done"), speak=False)
        except Exception:
            pass

    def _toggle_compact(self):
        self._apply_compact(not getattr(self, "_compact", False))

    def _cmd_focus_in(self, _e=None):
        if getattr(self, "_cmd_ph", False):
            self._cmd_ph = False
            self.cmd_var.set("")
            self.cmd_entry.config(fg=self.TEXT)

    def _cmd_focus_out(self, _e=None):
        if not self.cmd_var.get().strip():
            from services.i18n import t as _t
            self._cmd_ph = True
            self.cmd_var.set(_t("type_hint"))
            self.cmd_entry.config(fg=self.DIM)

    def _submit_typed(self, _e=None):
        """Typed command → same queue the voice loop drains (voice_backlog)."""
        if getattr(self, "_cmd_ph", False):
            return "break"
        text = self.cmd_var.get().strip()
        if not text:
            return "break"
        self.cmd_var.set("")
        voice_backlog.append(text)
        self._set_bubble(self.trans_text, "_trans_ph", text)
        try:
            from services.tts import stop_speaking
            stop_speaking()
        except Exception:
            pass
        print(f"[TYPED] {text}")
        return "break"

    def _face_stop(self):
        """Stop button: silence her now and drop whatever task is running."""
        try:
            from services.tts import stop_speaking
            stop_speaking()
        except Exception:
            pass
        try:
            from services.execute_funcs import set_cancel_flag
            set_cancel_flag(True)
        except Exception:
            pass
        try:
            from services.i18n import t as _t
            self.update_status(_t("cancelled"))
        except Exception:
            pass

    def _sync_face_action_buttons(self):
        """Full dashboard: Face mode + Hide on top, Listening under them."""
        from services.i18n import t as _t
        actions = getattr(self, "_face_actions", None)
        mode_btn = getattr(self, "_face_mode_btn", None)
        mute_btn = getattr(self, "_face_mute_btn", None)
        hide_btn = getattr(self, "_face_hide_btn", None)
        chip = getattr(self, "_status_row", None) or getattr(self, "_status_chip", None)
        if actions is None or mode_btn is None or hide_btn is None:
            return
        compact = bool(getattr(self, "_compact", False))
        for w in (mode_btn, mute_btn, hide_btn, actions, chip):
            if w is not None:
                try:
                    w.pack_forget()
                except Exception:
                    pass
        soft = getattr(self, "BTN_SOFT", self.BORDER)
        hide_btn.config(bg=soft, fg=self.TEXT, activebackground=self.BORDER_LIGHT,
                        activeforeground=self.TEXT)
        self._bind_hover(hide_btn, soft, self.TEXT, self.ACCENT, "#ffffff")
        mode_btn.config(text=_t("expand") if compact else _t("compact"))
        before = None
        time_lbl = getattr(self, "sys_time_label", None)
        try:
            if time_lbl is not None and time_lbl.winfo_ismapped():
                before = time_lbl
        except Exception:
            before = None
        if compact:
            mode_btn.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=(0, 4))
            if mute_btn is not None:
                mute_btn.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=(0, 4))
            hide_btn.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
            kw = dict(fill=tk.X, pady=(4, 6), padx=8)
            if before is not None:
                kw["before"] = before
            actions.pack(**kw)
            if chip is not None:
                ckw = dict(fill=tk.X, pady=(0, 4))
                if before is not None:
                    ckw["before"] = before
                chip.pack(**ckw)
                self._pack_status_pair()
        else:
            mode_btn.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=(0, 4))
            hide_btn.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
            akw = dict(fill=tk.X, pady=(0, 6))
            if before is not None:
                akw["before"] = before
            actions.pack(**akw)
            if chip is not None:
                ckw = dict(fill=tk.X, pady=(0, 0))
                if before is not None:
                    ckw["before"] = before
                chip.pack(**ckw)
                self._pack_status_pair()

    def _pack_status_pair(self):
        """Stop and Listening share the row 50/50 so neither looks like a leftover chip."""
        stop = getattr(self, "_face_stop_btn", None)
        inner = getattr(self, "_status_chip", None)
        if stop is not None:
            try:
                stop.pack_forget()
            except Exception:
                pass
            stop.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=(0, 4))
        if inner is not None:
            try:
                inner.pack_forget()
            except Exception:
                pass
            inner.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

    def _full_card_order(self):
        seen = []
        for w in (
            getattr(self, "_qa_card", None),
            getattr(self, "_mic_card", None),
            getattr(self, "_you_card", None),
            getattr(self, "_davi_card", None),
            getattr(self, "_rt_card", None),
            getattr(self, "_footer", None),
        ):
            if w is not None and w not in seen:
                seen.append(w)
        return seen

    def _pack_full_cards(self):
        P = getattr(self, "_pad", 12)
        GAP = (8, 0)
        cards = self._full_card_order()
        for w in cards:
            try:
                w.pack_forget()
            except Exception:
                pass
        for w in cards:
            if w is getattr(self, "_footer", None):
                w.pack(fill=tk.X, padx=P, pady=(8, 10))
            elif w is getattr(self, "_rt_card", None):
                w.pack(fill=tk.X, padx=P, pady=(12, 0))
            elif w is getattr(self, "_qa_card", None):
                continue
            else:
                w.pack(fill=tk.X, padx=P, pady=GAP)
        self._sync_media_qa(force=True)

    def _apply_compact(self, on):
        """Face-only overlay vs the full dashboard. Compact keeps a large
        talking head (about apple-sized) plus status, and hides the rest."""
        on = bool(on)
        if on == bool(getattr(self, "_compact", False)) and getattr(self, "_compact_ready", False):
            return
        self._compact = on
        self._compact_ready = True
        if getattr(self, "_settings_open", False):
            self._close_settings()
        self._close_board()

        if on:
            for w in self._full_card_order():
                try:
                    w.pack_forget()
                except Exception:
                    pass
            try:
                self._resize_grip.place_forget()
            except Exception:
                pass
            self._face_col.pack_forget()
            self._info_right.pack_forget()
            self._face_col.pack(anchor="center", pady=(8, 0))
            self._info_right.pack(fill=tk.X, pady=(4, 6))
            self.sys_time_label.pack_forget()
            if getattr(self, "sys_date_label", None) is not None:
                self.sys_date_label.pack_forget()
            self._bridge_row.pack_forget()
            if getattr(self, "face_id_label", None) is not None:
                self.face_id_label.pack_forget()
            if getattr(self, "_face_actions", None) is not None:
                self._sync_face_action_buttons()
            self._orb_size = self._orb_size_compact
            self._win_width = self._compact_width
            self._min_width = 220
            self._min_height = 360
        else:
            self._face_col.pack_forget()
            self._info_right.pack_forget()
            self._face_col.pack(side=tk.LEFT, anchor="n")
            self._info_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))
            if getattr(self, "_face_actions", None) is not None:
                self._sync_face_action_buttons()
            self.sys_time_label.pack(anchor="w", pady=(12, 0))
            if getattr(self, "sys_date_label", None) is not None:
                self.sys_date_label.pack(anchor="w", pady=(2, 4))
            self._bridge_row.pack(anchor="w", pady=(8, 0), fill=tk.X)
            self._sync_face_id_ui(force=True)
            self._pack_full_cards()
            try:
                self._resize_grip.place(relx=1.0, rely=1.0, anchor="se")
            except Exception:
                pass
            self._orb_size = self._orb_size_full
            self._win_width = self._full_width
            self._min_width = 320
            self._min_height = 520

        self._sync_media_qa(force=True)
        self._orb_scale = 1.0
        try:
            self._update_agent_orb(speaking=False)
        except Exception:
            pass
        self._auto_height = True
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        self._fit_window()
        try:
            self.root.after(40, self._fit_window)
        except Exception:
            pass

    def _minimize_app(self):
        """Send the overlay to the taskbar like a normal app."""
        if getattr(self, "_settings_open", False):
            self._close_settings()
        self._close_board()
        self._minimized = True
        self._user_hidden = False
        self._iconifying = True
        try:
            self.root.overrideredirect(False)
            self.root.iconify()
        except Exception:
            try:
                self.root.iconify()
            except Exception:
                pass
        self.root.after(80, lambda: setattr(self, "_iconifying", False))

    def hide_until_shown(self):
        """Hide the overlay into the tray. Click the Aemyos icon (or say come back)."""
        if getattr(self, "_settings_open", False):
            self._close_settings()
        self._close_board()
        self._minimized = False
        self._user_hidden = True
        try:
            from services.daily import set_hidden
            set_hidden(True)
        except Exception:
            pass
        self.root.withdraw()

    def show_overlay(self):
        if _user_quit or not agent_running:
            return
        self._minimized = False
        self._user_hidden = False
        try:
            from services.daily import set_hidden
            set_hidden(False)
        except Exception:
            pass
        try:
            self.root.deiconify()
            self._restore_frameless()
            self.root.lift()
            if getattr(self, "_always_top", True):
                self.root.attributes("-topmost", True)
                self._assert_topmost()
        except Exception:
            pass

    def _kick_overlay_visible(self):
        try:
            self._user_hidden = False
            self._minimized = False
            self.root.deiconify()
            self._restore_frameless()
            self.root.lift()
            if getattr(self, "_always_top", True):
                self.root.attributes("-topmost", True)
                self._assert_topmost()
            self._fit_window()
        except Exception as e:
            print(f"[UI] show overlay: {e}")

    def _maybe_ask_api_keys(self):
        try:
            from config import keys_ready
            if keys_ready():
                return
        except Exception:
            return
        self._show_setup_keys_popup()

    def _open_key_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    def _show_setup_keys_popup(self):
        from services.i18n import t as _t
        win = getattr(self, "_setup_keys_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.deiconify()
                    win.lift()
                    win.attributes("-topmost", True)
                    win.focus_force()
                    return
            except tk.TclError:
                pass

        win = tk.Toplevel(self.root)
        self._setup_keys_win = win
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=self.BORDER)

        shell = tk.Frame(win, bg=self.BG)
        shell.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        head = tk.Frame(shell, bg=self.BG2)
        head.pack(fill=tk.X)
        tk.Frame(head, bg=self.ACCENT, width=3).pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(head, text=_t("setup_keys_title"), fg=self.TEXT, bg=self.BG2,
                 font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT, padx=(12, 0), pady=10)
        def _close_popup(_e=None):
            try:
                win.grab_release()
            except Exception:
                pass
            win.withdraw()

        close = tk.Button(
            head, text="×", fg=self.DIM, bg=self.BG2, font=("Segoe UI", 12),
            bd=0, padx=8, pady=0, cursor="hand2",
            activebackground="#3b1520", activeforeground=self.RED,
            command=_close_popup,
        )
        win.bind("<Escape>", _close_popup)
        close.pack(side=tk.RIGHT, padx=(1, 8), pady=8)
        tk.Frame(shell, bg=self.BORDER, height=1).pack(fill=tk.X)

        body = tk.Frame(shell, bg=self.CARD)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Label(
            body, text=_t("setup_keys_body"), fg=self.DIM, bg=self.CARD,
            font=("Segoe UI", 8), wraplength=300, justify="left",
        ).pack(anchor="w")

        tk.Label(body, text=_t("openrouter_key"), fg=self.ACCENT, bg=self.CARD,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(12, 0))
        or_var = tk.StringVar()
        or_entry = tk.Entry(
            body, textvariable=or_var, font=("Consolas", 8),
            bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT, bd=0,
            highlightthickness=0,
        )
        or_entry.pack(fill=tk.X, pady=(4, 0), ipady=5)
        or_link = tk.Label(
            body, text=_t("setup_keys_get") + " · openrouter.ai",
            fg=self.ACCENT, bg=self.CARD, font=("Segoe UI", 7), cursor="hand2",
        )
        or_link.pack(anchor="w", pady=(4, 0))
        or_link.bind("<Button-1>", lambda e: self._open_key_url("https://openrouter.ai/keys"))

        tk.Label(body, text=_t("setup_keys_or"), fg=self.DIM, bg=self.CARD,
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", pady=(12, 0))

        tk.Label(body, text=_t("anth_key"), fg=self.DIM, bg=self.CARD,
                 font=("Segoe UI", 7)).pack(anchor="w", pady=(8, 0))
        anth_var = tk.StringVar()
        tk.Entry(
            body, textvariable=anth_var, font=("Consolas", 8),
            bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT, bd=0,
            highlightthickness=0,
        ).pack(fill=tk.X, pady=(2, 0), ipady=4)
        anth_link = tk.Label(
            body, text=_t("setup_keys_get") + " · console.anthropic.com",
            fg=self.ACCENT, bg=self.CARD, font=("Segoe UI", 7), cursor="hand2",
        )
        anth_link.pack(anchor="w", pady=(3, 0))
        anth_link.bind("<Button-1>", lambda e: self._open_key_url("https://console.anthropic.com/"))

        tk.Label(body, text=_t("groq_key"), fg=self.DIM, bg=self.CARD,
                 font=("Segoe UI", 7)).pack(anchor="w", pady=(8, 0))
        groq_var = tk.StringVar()
        tk.Entry(
            body, textvariable=groq_var, font=("Consolas", 8),
            bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT, bd=0,
            highlightthickness=0,
        ).pack(fill=tk.X, pady=(2, 0), ipady=4)
        groq_link = tk.Label(
            body, text=_t("setup_keys_get") + " · console.groq.com",
            fg=self.ACCENT, bg=self.CARD, font=("Segoe UI", 7), cursor="hand2",
        )
        groq_link.pack(anchor="w", pady=(3, 0))
        groq_link.bind("<Button-1>", lambda e: self._open_key_url("https://console.groq.com/"))

        status = tk.Label(body, text="", fg=self.RED, bg=self.CARD, font=("Segoe UI", 7))
        status.pack(anchor="w", pady=(8, 0))
        self._setup_keys_status = status
        self._setup_or_var = or_var
        self._setup_anth_var = anth_var
        self._setup_groq_var = groq_var

        save = tk.Button(
            body, text=_t("setup_keys_save"), fg=getattr(self, "ON_FG", "#ffffff"),
            bg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=0, padx=12, pady=8,
            cursor="hand2", activebackground=self.ACCENT2, activeforeground="#ffffff",
            command=self._save_setup_keys,
        )
        save.pack(fill=tk.X, pady=(10, 2))

        def _start_drag(event):
            self._setup_drag = {
                "x": event.x_root, "y": event.y_root,
                "wx": win.winfo_x(), "wy": win.winfo_y(),
            }

        def _do_drag(event):
            d = getattr(self, "_setup_drag", None)
            if not d:
                return
            win.geometry(
                f"+{d['wx'] + event.x_root - d['x']}+{d['wy'] + event.y_root - d['y']}")

        for w in (head,):
            w.bind("<Button-1>", _start_drag)
            w.bind("<B1-Motion>", _do_drag)

        win.update_idletasks()
        w = 340
        h = max(360, shell.winfo_reqheight() + 4)
        try:
            ox, oy = self.root.winfo_x(), self.root.winfo_y()
            x = max(8, ox - w - 10)
            y = oy
        except Exception:
            x, y = 80, 80
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.deiconify()
        win.lift()
        # Not modal: the user may skip keys for now and still use settings / hide / quit.
        or_entry.focus_set()

    def _save_setup_keys(self):
        from config import save_env, keys_ready
        from services.i18n import t as _t
        or_key = (getattr(self, "_setup_or_var", None) and self._setup_or_var.get() or "").strip()
        anth = (getattr(self, "_setup_anth_var", None) and self._setup_anth_var.get() or "").strip()
        groq = (getattr(self, "_setup_groq_var", None) and self._setup_groq_var.get() or "").strip()
        updates = {}
        if or_key and "•" not in or_key:
            updates["OPENROUTER_API_KEY"] = or_key
            updates["DAVI_PROVIDER"] = "openrouter"
        if anth and "•" not in anth:
            updates["ANTHROPIC_API_KEY"] = anth
        if groq and "•" not in groq:
            updates["GROQ_API_KEY"] = groq
        if anth and groq and "OPENROUTER_API_KEY" not in updates:
            updates["DAVI_PROVIDER"] = "anthropic"
        status = getattr(self, "_setup_keys_status", None)
        if not updates:
            if status is not None:
                status.config(text=_t("setup_keys_need"), fg=self.RED)
            return
        save_env(**updates)
        if not keys_ready():
            if status is not None:
                status.config(text=_t("setup_keys_need"), fg=self.RED)
            return
        if status is not None:
            status.config(text=_t("keys_saved"), fg=self.GREEN)
        try:
            win = getattr(self, "_setup_keys_win", None)
            if win is not None:
                win.grab_release()
                win.withdraw()
        except Exception:
            pass
        self.root.after(400, restart_overlay_process)

    def _start_tray(self):
        try:
            from services.tray import start as start_tray
            start_tray(
                on_show=lambda: self.root.after(0, self.show_overlay),
                on_hide=lambda: self.root.after(0, self.hide_until_shown),
                on_quit=lambda: self.root.after(0, lambda: request_quit("tray")),
            )
        except Exception as e:
            print(f"[TRAY] {e}")

    def _restore_app(self):
        if _user_quit or not agent_running:
            return
        if getattr(self, "_user_hidden", False):
            return
        if getattr(self, '_minimized', False):
            self.show_overlay()

    def _close_app(self, _event=None):
        request_quit("overlay-x")

    def _on_frame_configure(self, event):
        self._sync_main_scroll()

    def _on_canvas_configure(self, event):
        try:
            cur = int(float(self._main_canvas.itemcget(self._frame_id, "width") or 0))
        except Exception:
            cur = 0
        if event.width > 1 and event.width != cur:
            self._main_canvas.itemconfig(self._frame_id, width=event.width)
        self._sync_main_scroll()

    def _main_overflows(self):
        try:
            return int(self.frame.winfo_reqheight() or 0) > int(self._main_canvas.winfo_height() or 0) + 6
        except Exception:
            return False

    def _sync_main_scroll(self):
        """Size the inner column to the window. Never show a page scrollbar —
        shrinking the overlay should tighten tiles, not add a strip."""
        if getattr(self, "_syncing_scroll", False):
            return
        canvas = getattr(self, "_main_canvas", None)
        vsb = getattr(self, "_main_vsb", None)
        if canvas is None:
            return
        self._syncing_scroll = True
        try:
            if vsb is not None:
                try:
                    vsb.pack_forget()
                except Exception:
                    pass
            canvas.update_idletasks()
            req_h = int(self.frame.winfo_reqheight() or 0)
            view_h = int(canvas.winfo_height() or 0)
            view_w = int(canvas.winfo_width() or 0)
            if view_w > 1:
                canvas.itemconfig(self._frame_id, width=view_w)
            if req_h > 1:
                canvas.itemconfig(self._frame_id, height=req_h)
            canvas.configure(scrollregion=(0, 0, max(view_w, 1), max(req_h, view_h, 1)))
            canvas.yview_moveto(0)
        except Exception:
            pass
        finally:
            self._syncing_scroll = False

    def _sync_settings_scroll(self):
        canvas = getattr(self, "_stg_canvas", None)
        vsb = getattr(self, "_stg_vsb", None)
        inner = getattr(self, "_stg_inner", None)
        if canvas is None or vsb is None or inner is None:
            return
        try:
            canvas.update_idletasks()
            req = int(inner.winfo_reqheight() or 0)
            view = int(canvas.winfo_height() or 0)
            view_w = int(canvas.winfo_width() or 0)
            if view_w > 1:
                canvas.itemconfig(self._stg_inner_id, width=view_w)
            canvas.configure(scrollregion=(0, 0, max(view_w, 1), max(req, 1)))
            need = req > view + 10 and view > 1
            shown = bool(vsb.winfo_ismapped())
            if need and not shown:
                canvas.pack_forget()
                vsb.pack(side=tk.RIGHT, fill=tk.Y)
                canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            elif not need and shown:
                vsb.pack_forget()
                canvas.yview_moveto(0)
        except Exception:
            pass

    def _apply_overlay_density(self):
        """When the user shortens the window, tuck chat/mic instead of scrolling."""
        if getattr(self, "_compact", False):
            return
        try:
            h = int(self.root.winfo_height() or 0)
        except Exception:
            return
        auto = bool(getattr(self, "_auto_height", True))
        show_chat = auto or h >= 640
        show_mic = auto or h >= 520
        P = getattr(self, "_pad", 12)
        GAP = (8, 0)
        mic = getattr(self, "_mic_card", None)
        you = getattr(self, "_you_card", None)
        davi = getattr(self, "_davi_card", None)
        rt = getattr(self, "_rt_card", None)

        def mapped(w):
            try:
                return bool(w is not None and w.winfo_ismapped())
            except Exception:
                return False

        if mic is not None:
            if show_mic:
                if not mapped(mic):
                    before = you if mapped(you) else (davi if mapped(davi) else rt)
                    kw = dict(fill=tk.X, padx=P, pady=GAP)
                    if before is not None:
                        kw["before"] = before
                    mic.pack(**kw)
            elif mapped(mic):
                mic.pack_forget()
        if show_chat:
            if you is not None and not mapped(you):
                kw = dict(fill=tk.X, padx=P, pady=GAP)
                if mapped(davi):
                    kw["before"] = davi
                elif rt is not None:
                    kw["before"] = rt
                you.pack(**kw)
            if davi is not None and not mapped(davi):
                kw = dict(fill=tk.X, padx=P, pady=GAP)
                if rt is not None:
                    kw["before"] = rt
                davi.pack(**kw)
        else:
            if mapped(you):
                you.pack_forget()
            if mapped(davi):
                davi.pack_forget()
        footer = getattr(self, "_footer", None)
        if rt is not None and not mapped(rt):
            kw = dict(fill=tk.X, padx=P, pady=(12, 0))
            if footer is not None and mapped(footer):
                kw["before"] = footer
            rt.pack(**kw)

    def _finish_scroll_sync(self):
        self._syncing_scroll = False
        self._sync_main_scroll()

    def _bind_overlay_wheel(self, widget):
        skip = (getattr(self, "_stg_win", None), getattr(self, "_board_win", None))
        if widget in skip or widget is None:
            return
        try:
            cls = str(widget.winfo_class())
        except Exception:
            cls = ""
        if cls not in ("TCombobox", "Combobox", "Text"):
            widget.bind("<MouseWheel>", self._on_overlay_wheel, add="+")
        try:
            children = list(widget.winfo_children())
        except Exception:
            children = []
        for child in children:
            if child in skip:
                continue
            self._bind_overlay_wheel(child)

    def _on_overlay_wheel(self, event):
        try:
            top = event.widget.winfo_toplevel()
        except Exception:
            return
        if top is not self.root:
            return
        return "break"

    def _start_resize(self, event, mode="br"):
        self._resize_data = {
            "x": event.x_root, "y": event.y_root,
            "w": self.root.winfo_width(), "h": self.root.winfo_height(),
            "wx": self.root.winfo_x(), "wy": self.root.winfo_y(),
            "mode": mode
        }

    def _do_resize(self, event, mode="br"):
        d = self._resize_data
        m = d["mode"]
        dx = event.x_root - d["x"]
        dy = event.y_root - d["y"]
        x, y, w, h = d["wx"], d["wy"], d["w"], d["h"]

        if "r" in m:
            w = max(self._min_width, d["w"] + dx)
        if "b" in m:
            h = max(self._min_height, d["h"] + dy)
        if "l" in m:
            new_w = max(self._min_width, d["w"] - dx)
            x = d["wx"] + (d["w"] - new_w)
            w = new_w
        if "t" in m:
            new_h = max(self._min_height, d["h"] - dy)
            y = d["wy"] + (d["h"] - new_h)
            h = new_h

        self._auto_height = False
        self._win_width = w
        wx, wy, ww, wh = _desktop_work_area()
        margin = getattr(self, "_margin", 10)
        w = min(max(w, self._min_width), ww - 2 * margin)
        h = min(max(h, self._min_height), wh - 2 * margin)
        if x < wx + margin:
            x = wx + margin
        if y < wy + margin:
            y = wy + margin
        if x + w > wx + ww - margin:
            x = wx + ww - w - margin
        if y + h > wy + wh - margin:
            y = wy + wh - h - margin
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._last_geo = f"{w}x{h}+{x}+{y}"
        self._sync_main_scroll()
        self._apply_overlay_density()
        self._position_board_window()
        if getattr(self, "_settings_open", False):
            self._position_settings_window()

    def _overlay_hwnd(self):
        try:
            import ctypes
            return ctypes.windll.user32.GetParent(self.root.winfo_id())
        except Exception:
            return 0

    def _set_header_logo(self):
        lbl = getattr(self, "_hdr_title", None)
        if lbl is None:
            return
        path = _res_path("assets", "header-logo.png")
        try:
            from PIL import Image, ImageTk
            if os.path.isfile(path):
                img = Image.open(path).convert("RGBA")
                try:
                    import numpy as np
                    arr = np.array(img)
                    mx = arr[:, :, :3].max(axis=2).astype(np.float32)
                    alpha = np.clip((mx - 16.0) * (255.0 / 28.0), 0, 255).astype(np.uint8)
                    arr[:, :, 3] = np.minimum(arr[:, :, 3], alpha)
                    ys, xs = np.where(arr[:, :, 3] > 10)
                    if xs.size:
                        pad = 2
                        img = Image.fromarray(arr, "RGBA").crop((
                            max(0, int(xs.min()) - pad),
                            max(0, int(ys.min()) - pad),
                            min(arr.shape[1], int(xs.max()) + 1 + pad),
                            min(arr.shape[0], int(ys.max()) + 1 + pad),
                        ))
                    else:
                        img = Image.fromarray(arr, "RGBA")
                except Exception:
                    pass
                h = 26
                w = max(1, int(img.width * h / max(1, img.height)))
                img = img.resize((w, h), Image.LANCZOS)
                # Tk on Windows paints PNG alpha as black — bake the header color in.
                bg = Image.new("RGBA", img.size, (*self._hex_rgb(self.BG2), 255))
                img = Image.alpha_composite(bg, img)
                self._hdr_logo_photo = ImageTk.PhotoImage(img.convert("RGB"))
                lbl.config(image=self._hdr_logo_photo, text="", bg=self.BG2,
                           bd=0, highlightthickness=0)
                return
        except Exception:
            pass
        lbl.config(image="", text="Aemyos", fg=self.TEXT, bg=self.BG2,
                   font=("Segoe UI", 13, "bold"), anchor="w")

    def _set_taskbar_icon(self):
        root_dir = _res_path()
        ico = os.path.join(root_dir, "assets", "icon.ico")
        png = os.path.join(root_dir, "assets", "icon.png")
        try:
            if os.path.isfile(ico):
                self.root.iconbitmap(default=ico)
        except Exception:
            try:
                if os.path.isfile(ico):
                    self.root.iconbitmap(ico)
            except Exception:
                pass
        try:
            from PIL import Image, ImageTk
            path = png if os.path.isfile(png) else os.path.join(root_dir, "assets", "face_idle.png")
            if os.path.isfile(path):
                img = Image.open(path).convert("RGBA")
                img.thumbnail((64, 64), Image.LANCZOS)
                self._icon_photo = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self._icon_photo)
        except Exception:
            pass
        try:
            hwnds = [self.root.winfo_id(), self._overlay_hwnd()]
            for hwnd in hwnds:
                _hwnd_set_icon(hwnd, ico)
        except Exception:
            pass

    def _apply_app_window_style(self):
        try:
            import ctypes
            hwnd = self._overlay_hwnd()
            if not hwnd:
                return
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            new_style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            if new_style != style:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
                # The shell only re-reads APPWINDOW on show: a frameless window that
                # is already visible gets no taskbar button until hidden and shown.
                # Must go through Tk (not ShowWindow via ctypes): a synchronous Win32
                # call re-entering Tk callbacks without the GIL is a fatal error.
                if user32.IsWindowVisible(hwnd) and not getattr(self, "_user_hidden", False):
                    self.root.withdraw()

                    def _reshow():
                        try:
                            self.root.deiconify()
                            self._assert_topmost()
                        except Exception:
                            pass

                    self.root.after(10, _reshow)
            self._set_taskbar_icon()
        except Exception:
            pass

    def _restore_frameless(self):
        """Keep the custom header only — native min/max/X is a restore glitch."""
        if getattr(self, "_iconifying", False) or getattr(self, "_user_hidden", False):
            return
        if getattr(self, "_stripping_frame", False):
            return
        self._stripping_frame = True
        try:
            self.root.overrideredirect(True)
            self._apply_app_window_style()
        except Exception:
            pass
        finally:
            self._stripping_frame = False

    def _on_root_map(self, _e=None):
        if getattr(self, "_user_hidden", False):
            return
        if getattr(self, "_iconifying", False):
            return
        self._minimized = False
        try:
            if getattr(self, "_always_top", True):
                self.root.attributes("-topmost", True)
                self._assert_topmost()
        except Exception:
            pass
        try:
            if not self.root.overrideredirect():
                self.root.after(1, self._restore_frameless)
        except Exception:
            pass

    def _on_root_unmap(self, _e=None):
        return

    def _assert_topmost(self):
        """WS_EX_TOPMOST via SetWindowLong does not restack — SetWindowPos does."""
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = self._overlay_hwnd()
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            swp_nomove, swp_nosize, swp_noactivate = 0x0002, 0x0001, 0x0010
            user32.SetWindowPos(
                hwnd, wintypes.HWND(-1), 0, 0, 0, 0,
                swp_nomove | swp_nosize | swp_noactivate,
            )
        except Exception:
            pass

    def _make_noactivate(self):
        try:
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOPMOST = 0x00000008
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
        except Exception:
            pass
        self._assert_topmost()

    def _start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _do_drag(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_data["x"])
        y = self.root.winfo_y() + (event.y - self._drag_data["y"])
        self.root.geometry(f"+{x}+{y}")
        if getattr(self, "_settings_open", False):
            self._position_settings_window()

    def _on_mic_combo_press(self, event=None):
        self._refresh_mic_devices(force=True)

    def _apply_mic_list(self, rows):
        ids = [i for i, _ in rows]
        names = [n for _, n in rows]
        if ids == getattr(self, "mic_devices", None) and names == getattr(self, "mic_names", None):
            return False
        prev = (self.mic_var.get() or "").strip()
        self.mic_devices = ids
        self.mic_names = names
        self._mic_ignore = True
        try:
            self.mic_combo["values"] = self.mic_names
            if prev in self.mic_names:
                self.mic_var.set(prev)
                self.mic_combo.current(self.mic_names.index(prev))
            elif self.mic_names:
                self.mic_var.set(self.mic_names[0])
        except Exception:
            pass
        finally:
            self._mic_ignore = False
        return True

    def _refresh_mic_devices(self, force=False):
        """Pick up Bluetooth mics that connected after PortAudio started."""
        global voice_processor_ref
        now = time.time()
        if getattr(self, "_mic_refreshing", False):
            return
        if now - getattr(self, "_mic_rescan_at", 0) < 0.8:
            return
        from services.voice_input import active_capture_ids, list_user_mics, refresh_portaudio
        ids = None
        try:
            ids = active_capture_ids()
        except Exception:
            ids = None
        known = getattr(self, "_mic_capture_ids", None)
        if ids is not None and ids == known:
            return
        if not force and ids is None:
            return
        self._mic_refreshing = True
        self._mic_rescan_at = now
        try:
            vp = voice_processor_ref
            rows = None
            if vp is not None and hasattr(vp, "rescan_devices"):
                rows = vp.rescan_devices()
            else:
                refresh_portaudio()
                rows = list_user_mics()
            if rows is None:
                rows = list_user_mics()
            changed = self._apply_mic_list(rows)
            self._mic_capture_ids = ids
            if changed:
                print(f"[MIC] Device list updated ({len(rows)} mics)")
            self._sync_mic_combo()
        except Exception as e:
            print(f"[MIC] Device list refresh failed: {e}")
        finally:
            self._mic_refreshing = False

    def _sync_mic_combo(self):
        global voice_processor_ref
        vp = voice_processor_ref
        if not vp:
            return
        actual = getattr(vp, "input_device_id", None)
        if actual is None or actual not in getattr(self, "mic_devices", []):
            self._mic_armed = True
            return
        idx = self.mic_devices.index(actual)
        self._mic_ignore = True
        try:
            self.mic_combo.current(idx)
            self.mic_var.set(self.mic_names[idx])
        except Exception:
            pass
        finally:
            self._mic_ignore = False
            self._mic_armed = True

    def _sync_mic_mute_btn(self):
        from services.i18n import t as _t
        muted = False
        try:
            from services.voice_input import is_mic_muted
            muted = bool(is_mic_muted())
        except Exception:
            pass
        btn = getattr(self, "_mic_mute_btn", None)
        face_btn = getattr(self, "_face_mute_btn", None)
        try:
            label = _t("mic_btn_listen") if muted else _t("mic_btn_mute")
            color = self.YELLOW if muted else self.TEXT
            for w in (btn, face_btn):
                if w is not None:
                    w.config(text=label, fg=color)
        except Exception:
            pass

    def _toggle_own_mic(self):
        from services.daily import mute_own_mic, unmute_own_mic
        from services.voice_input import is_mic_muted
        from services.i18n import t as _t
        if is_mic_muted():
            unmute_own_mic()
            update_agent_response(_t("mic_on"), speak=True)
        else:
            mute_own_mic()
            update_agent_response(_t("mic_off"), speak=True)
        self._sync_mic_mute_btn()

    def on_mic_change(self, event=None):
        global voice_processor_ref
        if not getattr(self, "_mic_armed", False) or getattr(self, "_mic_ignore", False):
            return
        vp = voice_processor_ref
        if not vp:
            return
        displayed = (self.mic_var.get() or "").strip()
        idx = -1
        if displayed in self.mic_names:
            idx = self.mic_names.index(displayed)
        else:
            try:
                idx = int(self.mic_combo.current())
            except Exception:
                idx = -1
        if idx < 0 or idx >= len(self.mic_devices):
            return
        device_id = self.mic_devices[idx]
        if device_id == getattr(vp, "input_device_id", None):
            return
        try:
            self._mic_ignore = True
            ok = vp.change_device(device_id)
            if ok:
                print(f"[MIC] Overlay using [{device_id}] {self.mic_names[idx]}")
                self.mic_combo.config(foreground=self.GREEN)
                self.root.after(1500, lambda: self.mic_combo.config(foreground=""))
            else:
                print(f"[MIC] Could not open [{device_id}] {self.mic_names[idx]}")
                self._sync_mic_combo()
        except Exception as e:
            print(f"Mic switch error: {e}")
            self._sync_mic_combo()
        finally:
            self._mic_ignore = False
            self._mic_armed = True

    def cancel_task_by_index(self, task_id):
        if cancel_task(task_id):
            self._last_task_sig = None
            print(f"Task #{task_id} cancelled.")
            try:
                msg = t("cancelled")
                self.update_status(msg)
                self.update_response(msg)
                self.set_last_action(msg)
            except Exception:
                pass

    def update_response(self, text):
        if text and text != self._last_response:
            self._last_response = text
            try:
                from services.personal import add_history
                add_history("davi", text)
            except Exception:
                pass
            self._set_bubble(self.response_text, "_resp_ph", text)

    def set_last_action(self, text):
        """Kept for callers that report progress; the row itself is no longer shown."""
        snippet = (text or "").replace("\n", " ").strip()
        if snippet:
            self._last_action_raw = snippet

    def _sync_chrome_bridge_ui(self, ok=None):
        """Show Setup whenever the Chrome extension is disconnected."""
        try:
            from services.i18n import t as _t
            if ok is None:
                try:
                    from services.browser_bridge import is_bridge_connected
                    ok = bool(is_bridge_connected())
                except Exception:
                    ok = False
            ok = bool(ok)
            self._last_bridge_ok = ok
            if ok:
                self.bridge_label.config(text=_t("chrome_on"), fg=self.GREEN)
                self._ext_btn.pack_forget()
            else:
                self.bridge_label.config(text=_t("chrome_off"), fg=self.DIM)
                mapped = False
                try:
                    mapped = bool(self._ext_btn.winfo_ismapped())
                except Exception:
                    mapped = False
                if not mapped:
                    self._ext_btn.pack(side=tk.RIGHT, padx=(4, 0))
        except Exception:
            pass

    def _sync_face_id_ui(self, force=False):
        label = getattr(self, "face_id_label", None)
        if label is None:
            return
        from services.i18n import t as _t
        cam_on = False
        try:
            from services.webcam import is_on
            cam_on = bool(is_on())
        except Exception:
            cam_on = False
        compact = bool(getattr(self, "_compact", False))
        if (not cam_on) or compact:
            sig = ("off", compact)
            if force or sig != getattr(self, "_last_face_id_sig", None):
                self._last_face_id_sig = sig
                label.config(text="")
                try:
                    label.pack_forget()
                except Exception:
                    pass
            return
        try:
            from services.face_id import ui_state
            state = ui_state() or {}
        except Exception:
            state = {}
        key = state.get("key") or "face_no_enroll"
        name = state.get("name") or ""
        tone = state.get("tone") or "dim"
        text = _t(key)
        if name and "{name}" in text:
            try:
                text = text.format(name=name)
            except Exception:
                pass
        color = {"ok": self.GREEN, "warn": self.YELLOW}.get(tone, self.DIM)
        sig = (key, name, tone, True)
        if (not force) and sig == getattr(self, "_last_face_id_sig", None):
            return
        self._last_face_id_sig = sig
        label.config(text=text, fg=color)
        try:
            if not label.winfo_ismapped():
                label.pack(anchor="w", pady=(2, 0))
        except Exception:
            pass

    def _consume_face_event(self):
        try:
            from services.tts import is_speaking
            if is_speaking():
                return
        except Exception:
            pass
        try:
            from services.face_id import consume_event
            ev = consume_event()
        except Exception:
            ev = None
        if not ev:
            return
        from services.i18n import t as _t
        kind = ev.get("kind")
        name = ev.get("name") or ""
        if kind == "enrolled":
            key = "face_saved_named" if name else "face_saved"
        elif kind == "recognized":
            key = "face_known_named" if name else "face_known"
        else:
            return
        msg = _t(key)
        if name and "{name}" in msg:
            try:
                msg = msg.format(name=name)
            except Exception:
                pass
        try:
            update_agent_response(msg, speak=True)
        except Exception:
            pass
        self._sync_face_id_ui(force=True)

    def show_safety_toast(self, text):
        self.set_last_action(text)
        try:
            self.update_response(text)
        except Exception:
            pass
        try:
            self.status_label.config(text=(text or "")[:42], fg=self.RED)
            if getattr(self, "_conv_card", None):
                self._conv_card.config(highlightbackground=self.RED, highlightthickness=2)
            self.root.after(7000, self._restore_safety_toast)
        except Exception:
            pass

    def _show_mic_error(self, text):
        """One-line Groq/STT failure — keep listening, do not freeze the overlay."""
        line = (text or "").replace("\n", " ").strip()[:60]
        if not line:
            return
        self._mic_error_line = line
        try:
            self._wave_rms_label.config(text=line, fg=self.RED)
        except Exception:
            pass
        try:
            self.status_label.config(text=line, fg=self.RED)
            self.status_dot.config(fg=self.RED)
        except Exception:
            pass
        try:
            self.root.after(4500, self._clear_mic_error)
        except Exception:
            pass

    def _set_mic_silent(self):
        from services.i18n import t as _t
        try:
            self._wave_rms_label.config(text=_t("mic_silent"), fg=self.DIM)
        except Exception:
            pass

    def _clear_mic_error(self):
        line = getattr(self, "_mic_error_line", "")
        self._mic_error_line = ""
        try:
            cur = str(self._wave_rms_label.cget("text") or "")
            if line and cur == line:
                self._set_mic_silent()
        except Exception:
            pass

    def _restore_safety_toast(self):
        try:
            if getattr(self, "_conv_card", None):
                self._conv_card.config(highlightbackground=self.BORDER, highlightthickness=1)
        except Exception:
            pass

    def update_status(self, status):
        s = (status or "").lower()
        if any(k in s for k in ("cancel", "iptal", "annul", "abbruch", "abort")):
            dot_color = self.RED
        elif any(k in s for k in (
            "mic off", "mikrofon kapalı", "mikrofon kapali", "micrófono apagado",
            "mikrofon aus", "micro coupé",
        )):
            dot_color = self.DIM
        elif any(k in s for k in (
            "pause", "duraklat", "busy", "medya", "toplant", "meeting",
            "medien", "média", "reunión", "réunion", "noting", "not al",
            "anotando", "notiere", "je note",
        )):
            dot_color = self.DIM
        elif any(k in s for k in ("listen", "wait", "dinli", "escuch", "höre", "écoute", "jecoute")):
            dot_color = self.CYAN
        elif any(k in s for k in ("speak", "konuş", "konus", "habl", "sprech", "parle")):
            dot_color = self.ACCENT
        elif any(k in s for k in ("think", "düşün", "pensa", "denke", "réfléch")):
            dot_color = self.ACCENT
        elif any(k in s for k in ("execut", "uygul", "ejecut", "führe", "exécute", "step", "adım", "schritt", "étape", "paso")):
            dot_color = self.GREEN
        elif any(k in s for k in ("stop", "error", "hata", "fehler", "erreur", "duruyor")):
            dot_color = self.RED
        else:
            dot_color = self.PURPLE
        self.status_label.config(text=_status_chip_text(status), fg=dot_color, wraplength=0, height=1)
        self.status_dot.config(fg=dot_color)
        listening = any(k in s for k in ("listen", "wait", "dinli", "escuch", "höre", "écoute", "jecoute"))
        chip_bg = getattr(self, "CHIP_OK", self.BG3) if listening else self.BG3
        try:
            self._status_chip.config(bg=chip_bg)
            if getattr(self, "_status_chip_inner", None) is not None:
                self._status_chip_inner.config(bg=chip_bg)
            self.status_label.config(bg=chip_bg)
            if getattr(self, "_status_icon", None) is not None:
                self._status_icon.config(bg=chip_bg, fg=dot_color)
        except tk.TclError:
            pass

    def _make_dash_tile(self, parent, icon, title_key, sub_key, on_click, last=False, show_count=True):
        from services.i18n import t as _t
        cell = tk.Frame(parent, bg=self.BG3, cursor="hand2",
                        highlightthickness=1, highlightbackground=self.BORDER)
        cell.pack(fill=tk.X, pady=(0, 0 if last else 8))
        bar = tk.Frame(cell, bg=self.ACCENT, width=3)
        bar.pack(side=tk.LEFT, fill=tk.Y)
        body = tk.Frame(cell, bg=self.BG3)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=8)
        top = tk.Frame(body, bg=self.BG3)
        top.pack(fill=tk.X)
        ic = tk.Label(top, text=icon, fg=self.ACCENT, bg=self.BG3,
                      font=("Segoe UI Symbol", 12), cursor="hand2")
        ic.pack(side=tk.LEFT)
        title = tk.Label(top, text=_t(title_key), fg=self.TEXT, bg=self.BG3,
                         font=("Segoe UI", 9, "bold"), cursor="hand2")
        title.pack(side=tk.LEFT, padx=(8, 0))
        chev = tk.Label(top, text="›", fg=self.DIM, bg=self.BG3,
                        font=("Segoe UI", 14), cursor="hand2")
        chev.pack(side=tk.RIGHT)
        pill = None
        if show_count:
            pill = tk.Label(top, text="0", fg=self.ACCENT, bg=self.CARD,
                            font=("Segoe UI", 8, "bold"), cursor="hand2", padx=8, pady=1)
            pill.pack(side=tk.RIGHT, padx=(0, 6))
        sub = tk.Label(body, text=_t(sub_key), fg=self.DIM, bg=self.BG3,
                       font=("Segoe UI", 8), anchor="w", cursor="hand2")
        sub.pack(fill=tk.X, pady=(4, 0))

        def click(_e=None):
            on_click()

        widgets = [cell, bar, body, top, ic, title, chev, sub]
        if pill is not None:
            widgets.append(pill)
        for w in widgets:
            w.bind("<Button-1>", click)
        return cell, title, pill, sub

    def _set_fold_meta(self, chev, count_lbl, open_, n, hot=None):
        try:
            if count_lbl is not None:
                count_lbl.config(text=str(int(n)), fg=(hot or self.ACCENT) if n else self.DIM)
        except (tk.TclError, TypeError, ValueError):
            pass

    def _build_board_window(self):
        from services.i18n import t as _t
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", bool(getattr(self, "_always_top", True)))
        win.configure(bg=self.BORDER)
        self._board_win = win
        shell = tk.Frame(win, bg=self.BG)
        shell.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        head = tk.Frame(shell, bg=self.BG2)
        head.pack(fill=tk.X)
        tk.Frame(head, bg=self.ACCENT, width=3).pack(side=tk.LEFT, fill=tk.Y)
        self._lbl_board = tk.Label(head, text=_t("tasks"), fg=self.TEXT, bg=self.BG2,
                                   font=("Segoe UI", 11, "bold"))
        self._lbl_board.pack(side=tk.LEFT, padx=(12, 0), pady=10)
        close = tk.Button(head, text="×", fg=self.DIM, bg=self.BG2, font=("Segoe UI", 12),
                          bd=0, padx=8, pady=0, cursor="hand2",
                          activebackground="#3b1520", activeforeground=self.RED,
                          command=self._close_board)
        close.pack(side=tk.RIGHT, padx=(1, 8), pady=8)
        for w in (head, self._lbl_board):
            w.bind("<Button-1>", self._start_board_drag)
            w.bind("<B1-Motion>", self._do_board_drag)
        body = tk.Frame(shell, bg=self.CARD)
        body.pack(fill=tk.BOTH, expand=True)
        table_wrap = tk.Frame(body, bg=self.CARD)
        table_wrap.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        cols = ("status", "item", "when", "action")
        tree = ttk.Treeview(table_wrap, columns=cols, show="headings", style="Board.Treeview",
                            selectmode="browse", height=12)
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=tree.yview,
                            style="Overlay.Vertical.TScrollbar")
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree.bind("<Button-1>", self._on_board_click)
        tree.bind("<MouseWheel>", lambda e: tree.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self._board_tree = tree
        self._board_head = head
        self._sync_board_headings()
        empty = tk.Label(body, text="", fg=self.DIM, bg=self.CARD, font=("Segoe UI", 9))
        empty.pack(fill=tk.X, padx=12, pady=(0, 10))
        self._board_empty = empty

    def _sync_board_headings(self):
        from services.i18n import t as _t
        tree = getattr(self, "_board_tree", None)
        if tree is None:
            return
        kind = getattr(self, "_board_kind", "tasks")
        try:
            if kind == "reminders":
                self._lbl_board.config(text=_t("reminders"))
                tree.heading("status", text=_t("col_when"))
                tree.heading("item", text=_t("reminders"))
                tree.heading("when", text="")
            else:
                self._lbl_board.config(text=_t("tasks"))
                tree.heading("status", text=_t("col_status"))
                tree.heading("item", text=_t("col_item"))
                tree.heading("when", text=_t("col_time"))
            tree.heading("action", text=_t("col_action"))
            tree.column("status", width=90, minwidth=70, stretch=False, anchor="w")
            tree.column("item", width=220, minwidth=120, stretch=True, anchor="w")
            tree.column("when", width=70, minwidth=50, stretch=False, anchor="center")
            tree.column("action", width=36, minwidth=32, stretch=False, anchor="center")
        except tk.TclError:
            pass

    def _toggle_board(self, kind):
        if getattr(self, "_board_open", False) and getattr(self, "_board_kind", None) == kind:
            self._close_board()
            return
        self._open_board(kind)

    def _open_board(self, kind):
        self._close_settings()
        self._board_kind = kind
        self._board_open = True
        self._last_task_sig = None
        self._last_rem_sig = None
        self._sync_board_headings()
        self._fill_board_table()
        try:
            self._board_win.deiconify()
            self._board_win.lift()
            self._board_win.attributes("-topmost", True)
            self._position_board_window()
        except Exception as e:
            print(f"[UI] board open: {e}")

    def _close_board(self):
        self._board_open = False
        self._board_kind = None
        try:
            self._board_win.withdraw()
        except Exception:
            pass

    def _position_board_window(self):
        if not getattr(self, "_board_open", False):
            return
        win = getattr(self, "_board_win", None)
        if win is None:
            return
        try:
            win.update_idletasks()
            wx, wy, ww, wh = _desktop_work_area()
            margin = getattr(self, "_margin", 10)
            w = 440
            h = min(420, max(280, wh - 2 * margin))
            ox, oy = self.root.winfo_x(), self.root.winfo_y()
            x = ox - w - 8
            if x < wx + margin:
                x = ox + self.root.winfo_width() + 8
                if x + w > wx + ww - margin:
                    x = max(wx + margin, wx + ww - w - margin)
            y = oy
            if y + h > wy + wh - margin:
                y = max(wy + margin, wy + wh - margin - h)
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _start_board_drag(self, event):
        self._board_drag = {"x": event.x_root, "y": event.y_root,
                            "wx": self._board_win.winfo_x(), "wy": self._board_win.winfo_y()}

    def _do_board_drag(self, event):
        d = getattr(self, "_board_drag", None)
        if not d:
            return
        self._board_win.geometry(
            f"+{d['wx'] + event.x_root - d['x']}+{d['wy'] + event.y_root - d['y']}")

    def _on_board_click(self, event):
        tree = getattr(self, "_board_tree", None)
        if tree is None:
            return
        if tree.identify_region(event.x, event.y) != "cell":
            return
        col = tree.identify_column(event.x)
        row = tree.identify_row(event.y)
        if not row or col != "#4":
            return
        tags = tree.item(row, "tags") or ()
        if len(tags) < 2:
            return
        kind, sid = tags[0], tags[1]
        if kind == "task":
            try:
                self.cancel_task_by_index(int(sid))
            except (TypeError, ValueError):
                pass
        elif kind == "rem":
            self.cancel_reminder_by_id(sid)
        self.root.after(50, self._fill_board_table)

    def _fill_board_table(self):
        from services.i18n import t as _t
        tree = getattr(self, "_board_tree", None)
        if tree is None or not getattr(self, "_board_open", False):
            return
        for item in tree.get_children():
            tree.delete(item)
        kind = getattr(self, "_board_kind", "tasks")
        rows = 0
        if kind == "reminders":
            try:
                from services.smart_features import get_reminders
                rems = get_reminders() or []
            except Exception:
                rems = []
            for r in rems:
                rid = str(r.get("id") or "")
                when = str(r.get("remaining_label") or "")
                text = str(r.get("text") or "")[:80]
                tree.insert("", "end", values=(when, text, "", "✕"), tags=("rem", rid))
                rows += 1
            empty = _t("no_reminders") if not rows else _t("reminders_hint")
            if rows:
                empty = ""
            else:
                empty = _t("reminders_hint")
        else:
            with task_queue_lock:
                snapshot = list(task_queue[-TASK_SHOW:])
            status_map = {
                "pending": _t("status_pending"),
                "running": _t("status_running"),
                "done": _t("status_done"),
                "cancelled": _t("status_cancelled"),
            }
            for tsk in reversed(snapshot):
                status = tsk.get("status") or "done"
                text = str(tsk.get("text") or "")[:80]
                ts = str(tsk.get("ts") or "")
                when = ts[11:16] if len(ts) >= 16 else ts
                action = "✕" if status in ("pending", "running") else ""
                tree.insert(
                    "", "end",
                    values=(status_map.get(status, status), text, when, action),
                    tags=("task", str(tsk.get("id") or "")),
                )
                rows += 1
            empty = "" if rows else _t("no_tasks")
        try:
            self._board_empty.config(text=empty)
        except tk.TclError:
            pass

    def _refresh_tasks(self):
        with task_queue_lock:
            snapshot = [
                (t.get("id"), t["status"], t["text"][:40], t.get("progress") or "")
                for t in task_queue[-TASK_SHOW:]
            ]
        sig = tuple(snapshot)
        n = len(snapshot)
        running = any(s == "running" for _, s, _, _ in snapshot)
        self._set_fold_meta(None, getattr(self, "_task_count", None), False, n,
                            self.ACCENT if running else None)
        if sig == self._last_task_sig:
            return
        self._last_task_sig = sig
        if getattr(self, "_board_open", False) and getattr(self, "_board_kind", None) == "tasks":
            self._fill_board_table()

    def _flash_reminder_card(self):
        try:
            self._open_board("reminders")
            self._rt_card.config(highlightbackground=self.YELLOW, highlightthickness=2)
            self._rem_alert_until = time.time() + 8
            self.root.after(8000, self._restore_reminder_card)
        except Exception:
            pass

    def _restore_reminder_card(self):
        if time.time() < getattr(self, "_rem_alert_until", 0):
            return
        try:
            self._rt_card.config(highlightbackground=self.BORDER, highlightthickness=1)
        except Exception:
            pass

    def cancel_reminder_by_id(self, rid):
        try:
            from services.smart_features import cancel_reminder
            if cancel_reminder(rid):
                self._last_rem_sig = None
                self._refresh_reminders(force=True)
        except Exception as e:
            print(f"[REMIND] cancel: {e}")

    def _refresh_reminders(self, force=False):
        from services.i18n import t as _t
        try:
            from services.smart_features import get_reminders
            rems = get_reminders()
        except Exception:
            rems = []
        id_sig = tuple(r.get("id") for r in (rems or [])) + (len(rems), _t("reminders_hint"))
        n = len(rems or [])
        self._set_fold_meta(None, getattr(self, "_rem_count", None), False, n,
                            self.YELLOW if n else None)
        if not force and id_sig == getattr(self, "_last_rem_sig", None):
            if getattr(self, "_board_open", False) and getattr(self, "_board_kind", None) == "reminders":
                self._fill_board_table()
            return
        self._last_rem_sig = id_sig
        if getattr(self, "_board_open", False) and getattr(self, "_board_kind", None) == "reminders":
            self._fill_board_table()

    def _refresh_clip_snippet(self):
        return

    def _update_waveform(self, vp):
        gated = False
        try:
            gated = bool(vp.mic_is_gated())
        except Exception:
            gated = False
        if gated:
            self._wave_history.append(0.0)
            if len(self._wave_history) > 96:
                self._wave_history.pop(0)
            self._set_mic_silent()
            try:
                self._wave_canvas.delete("all")
                w = self._wave_canvas.winfo_width() or 300
                h = self._wave_height
                mid = h // 2
                self._wave_canvas.create_line(0, mid, w, mid, fill=self.BORDER, width=1)
            except Exception:
                pass
            return

        level = vp.get_audio_level()
        self._wave_history.append(level)
        if len(self._wave_history) > 96:
            self._wave_history.pop(0)

        peak = max(self._wave_history[-10:]) if self._wave_history else 0
        if peak < 0.02:
            self._wave_idle_ticks += 1
            if self._wave_idle_ticks > 2 and self._wave_idle_ticks % 8 != 0:
                if level <= 0.01:
                    self._set_mic_silent()
                return
        else:
            self._wave_idle_ticks = 0

        self._wave_canvas.delete("all")
        w = self._wave_canvas.winfo_width() or 300
        h = self._wave_height
        mid = h // 2
        n = len(self._wave_history)
        step = max(1, w / n)

        # Draw center line
        self._wave_canvas.create_line(0, mid, w, mid, fill=self.BORDER, width=1)

        # Draw waveform
        points = []
        for i, val in enumerate(self._wave_history):
            x = int(i * step)
            amp = min(val * 2.5, 1.0)
            y_top = mid - int(amp * (mid - 2))
            points.append((x, y_top))

        mirror = []
        for x, y_top in reversed(points):
            y_bot = mid + (mid - y_top)
            mirror.append((x, y_bot))

        if len(points) >= 2:
            poly = []
            for p in points:
                poly.extend(p)
            for p in mirror:
                poly.extend(p)

            if peak > 0.35:
                fill_color = self.RED
                outline_color = "#ffb4b8"
            else:
                fill_color = self.ACCENT
                outline_color = self.ACCENT2

            self._wave_canvas.create_polygon(poly, fill=fill_color, outline=outline_color, width=1, smooth=True)

        # RMS indicator
        if level > 0.01:
            db = max(-60, int(20 * __import__('math').log10(max(level, 0.0001))))
            self._wave_rms_label.config(text=f"{db:+d} dB", fg=self.GREEN if level < 0.3 else self.RED)
        else:
            self._set_mic_silent()

    def update_loop(self):
        global voice_processor_ref
        if _user_quit or not agent_running:
            request_quit("overlay-loop")
            return

        try:
            from services.tts import is_playing as _playing
        except ImportError:
            _playing = False

        self._update_agent_orb(speaking=bool(_playing))
        if _playing:
            self._scroll_response_with_speech()
        elif getattr(self, "_was_following_tts", False):
            self._was_following_tts = False
            self._scroll_response_to_end()

        if voice_processor_ref:
            try:
                stt_err = voice_processor_ref.consume_stt_error()
            except Exception:
                stt_err = ""
            if stt_err:
                self._show_mic_error(stt_err)
            heard = voice_processor_ref.get_last_transcription()
            if heard and heard != self._last_transcription:
                self._last_transcription = heard
                ambient = False
                try:
                    from services.busy_audio import peek_busy, command_through_media, hold_commands
                    from services.voice_input import ptt_is_down
                    ambient = hold_commands(peek_busy()) and not ptt_is_down() and not command_through_media(heard)
                except Exception:
                    ambient = False
                if not ambient:
                    try:
                        from services.personal import add_history
                        add_history("you", heard)
                    except Exception:
                        pass
                    if getattr(self, '_minimized', False):
                        self._restore_app()
                    self._set_bubble(self.trans_text, "_trans_ph", heard)
            elif getattr(self, '_minimized', False):
                try:
                    if voice_processor_ref.get_audio_level() > 0.07:
                        self._restore_app()
                except Exception:
                    pass

        self._refresh_tasks()

        try:
            from services.busy_audio import refresh_busy
            if self._sys_info_counter % 3 == 0:
                refresh_busy()
            self._sync_media_qa()
            if self._sys_info_counter % 4 == 0:
                self._sync_mic_mute_btn()
        except Exception:
            pass

        try:
            from services.smart_features import consume_fired_alerts
            fired = consume_fired_alerts()
            if fired:
                self._flash_reminder_card()
                self._last_rem_sig = None
                self._refresh_reminders(force=True)
        except Exception:
            pass

        self._sys_info_counter += 1
        try:
            from services.browser_bridge import is_bridge_connected
            ok = bool(is_bridge_connected())
            mapped = False
            try:
                mapped = bool(self._ext_btn.winfo_ismapped())
            except Exception:
                pass
            if ok != self._last_bridge_ok or (ok and mapped) or ((not ok) and (not mapped)):
                self._sync_chrome_bridge_ui(ok)
        except Exception:
            pass
        self._consume_face_event()
        if self._sys_info_counter % 4 == 0:
            self._sync_face_id_ui()
        if self._sys_info_counter % 16 == 0:
            try:
                self._refresh_mic_devices(force=False)
            except Exception:
                pass
        if self._sys_info_counter % 8 == 0:
            self._refresh_reminders()
            self._refresh_clip_snippet()
            try:
                now = datetime.now()
                self.sys_time_label.config(text=now.strftime("%I:%M:%S %p").lstrip("0"))
                if getattr(self, "sys_date_label", None) is not None:
                    self.sys_date_label.config(text=now.strftime("%A, %B %d, %Y"))
            except Exception:
                pass

        if voice_processor_ref:
            self._update_waveform(voice_processor_ref)

        self.root.after(120, self.update_loop)


def run_status_overlay():
    global status_window
    root = tk.Tk()
    try:
        status_window = StatusOverlay(root)
    except Exception:
        print("[UI] Overlay failed to start:")
        traceback.print_exc()
        try:
            root.destroy()
        except Exception:
            pass
        return
    try:
        root.mainloop()
    finally:
        if not _user_quit:
            request_quit("overlay-closed")


_ctrl_held = False
_shift_held = False


def _ptt_key():
    from config import PTT_KEY
    return getattr(keyboard.Key, (PTT_KEY or "f9").lower(), keyboard.Key.f9)


def _set_ptt(down):
    try:
        from services.voice_input import set_ptt_down
        set_ptt_down(down)
    except Exception:
        pass


def on_esc_press(key):
    global _ctrl_held, _shift_held
    try:
        if key == _ptt_key():
            _set_ptt(True)
        elif key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
            _ctrl_held = True
        elif key == keyboard.Key.shift or key == keyboard.Key.shift_r:
            _shift_held = True
        elif hasattr(key, 'char') and key.char == 'q' and _ctrl_held and _shift_held:
            print("Ctrl+Shift+Q pressed. Stopping agent...")
            request_quit("hotkey")
            return False
    except Exception as e:
        print(f"Key error: {e}")

def on_key_release(key):
    global _ctrl_held, _shift_held
    try:
        if key == _ptt_key():
            _set_ptt(False)
        elif key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
            _ctrl_held = False
        elif key == keyboard.Key.shift or key == keyboard.Key.shift_r:
            _shift_held = False
    except Exception:
        pass


def start_key_listener():
    listener = keyboard.Listener(on_press=on_esc_press, on_release=on_key_release)
    listener.start()
    return listener


_dictation_on = False


def dictation_active():
    return _dictation_on


def _set_dictation(on):
    global _dictation_on
    _dictation_on = bool(on)
    if status_window:
        try:
            status_window.root.after_idle(status_window.set_dictation, _dictation_on)
        except Exception:
            pass


def _handle_personal_voice(voice_text):
    """Dictation, notes, profile, clock reminders and watchers.

    Returns True when the utterance was fully handled and the agent loop
    should go straight back to listening.
    """
    from services.smart_features import (
        match_dictation_start, match_dictation_stop, parse_scheduled_reminder,
        add_reminder, match_watch_text, match_watch_download,
    )
    from services.personal import (
        match_add_note, match_list_notes, match_set_name, add_note, list_notes,
        set_profile,
    )

    try:
        # ── Dictation ────────────────────────────────────────────
        if dictation_active():
            if match_dictation_stop(voice_text):
                _set_dictation(False)
                update_agent_response(t("dictation_off"), speak=True)
                print("[DICTATE] off")
                return True
            from services.keyboard_module import type_text
            type_text(voice_text)
            update_agent_response(voice_text, speak=False)
            print(f"[DICTATE] typed {len(voice_text)} chars")
            return True

        if match_dictation_start(voice_text):
            _set_dictation(True)
            add_task(voice_text)
            complete_current_task()
            update_agent_response(t("dictation_on"), speak=True)
            print("[DICTATE] on")
            return True

        # ── Clock-time and recurring reminders ───────────────────
        scheduled = parse_scheduled_reminder(voice_text)
        if scheduled:
            r_text, r_secs, repeat = scheduled
            fire = add_reminder(r_text, r_secs, repeat=repeat)
            label = t(f"repeat_{repeat}") if repeat else ""
            resp = f"{fire} · {r_text}" + (f" ({label})" if label else "")
            add_task(voice_text)
            complete_current_task()
            update_agent_response(resp)
            print(f"[FAST] scheduled {resp}")
            return True

        # ── Notes ────────────────────────────────────────────────
        note = match_add_note(voice_text)
        if note:
            add_note(note)
            add_task(voice_text)
            complete_current_task()
            update_agent_response(f"{t('note_saved')} · {note}", speak=True)
            print(f"[NOTE] + {note}")
            if status_window:
                status_window.root.after_idle(status_window.refresh_notes)
            return True

        if match_list_notes(voice_text):
            notes = list_notes(10)
            add_task(voice_text)
            complete_current_task()
            if not notes:
                update_agent_response(t("notes_empty"), speak=True)
            else:
                update_agent_response(". ".join(n["text"] for n in notes), speak=True)
            print(f"[NOTE] read {len(notes)}")
            return True

        from services.daily import match_type_once, type_once
        typed = match_type_once(voice_text)
        if typed:
            type_once(typed)
            add_task(voice_text)
            complete_current_task()
            update_agent_response(typed, speak=False)
            print(f"[TYPE] {typed[:80]}")
            return True

        # ── Who the user is ──────────────────────────────────────
        name = match_set_name(voice_text)
        if name:
            set_profile("name", name)
            add_task(voice_text)
            complete_current_task()
            update_agent_response(f"{t('name_saved')} {name}", speak=True)
            print(f"[PROFILE] name={name}")
            return True

        # ── Watchers ─────────────────────────────────────────────
        from services import watchers
        if match_watch_download(voice_text):
            watchers.add_download_watch()
            add_task(voice_text)
            complete_current_task()
            update_agent_response(t("watch_download_set"), speak=True)
            print("[WATCH] downloads")
            return True

        target = match_watch_text(voice_text)
        if target:
            watchers.add_text_watch(target)
            add_task(voice_text)
            complete_current_task()
            update_agent_response(f"{t('watch_text_set')} · {target}", speak=True)
            print(f"[WATCH] text '{target}'")
            return True
    except Exception as exc:
        print(f"[PERSONAL] {exc}")
    return False


_VERBOSE_RESULT_CMDS = {
    "run_command", "read_file", "list_files", "search_files", "get_running_apps",
    "clipboard_read", "read_screen", "find_text", "get_system_info", "list_windows",
    "network_info", "web_search", "browser_get_summary", "browser_read_page",
}


def _clip_middle(text, head=700, tail=1100):
    """Keep the start and the end — build/test errors live at the end of shell output."""
    text = str(text or "")
    if len(text) <= head + tail:
        return text
    return text[:head] + "\n…[snip]…\n" + text[-tail:]


def _command_results_text(results):
    if not results:
        return "No command results."
    lines = []
    for r in results:
        mark = "OK" if r.get("success") else "FAIL"
        cmd = r.get("command", "?")
        raw = str(r.get("message", ""))
        msg = _clip_middle(raw) if cmd in _VERBOSE_RESULT_CMDS else raw[:200]
        lines.append(f"{mark} {cmd}: {msg}")
    return "\n".join(lines)


def _pc_context(include_apps=True):
    """Live monitor/window/app awareness for the model. Never fatal."""
    try:
        from services.pc_context import context_block
        return context_block(include_apps=include_apps)
    except Exception as e:
        print(f"[CTX] pc_context: {e}")
        return f'Active window: "{_active_window_title()}"'


def _site_label(url):
    """'youtube.com · turkish music' — never a raw URL, TTS would spell it out."""
    try:
        from urllib.parse import urlparse, parse_qs
        p = urlparse(url or "")
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        qs = parse_qs(p.query)
        q = (qs.get("search_query") or qs.get("q") or [""])[0].strip()
        return f"{host} · {q}" if q else host
    except Exception:
        return (url or "").replace("https://", "").replace("www.", "")


def _active_window_title():
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return "(unknown)"
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or "(unknown)"
    except Exception:
        return "(unknown)"


def _trim_conversation(messages, keep=16):
    if len(messages) > keep:
        return messages[-keep:]
    return messages


def parse_response_text(generated_text):
    import re
    match = re.search(r'\[Response\]\s*(.+?)(?:\n\[|\Z)', generated_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    for line in generated_text.split('\n'):
        line = line.strip()
        if line and not line.startswith('[') and not line.startswith('{') and not line.startswith('```'):
            return line[:200]
    return ""


_GEN_ERROR_PREFIXES = (
    "error generating response",
    "error: no text in response",
)
_NON_DESKTOP_CMDS = {"listen", "answer", "remember", "notify"}


def _generation_failed(text):
    if not text or not str(text).strip():
        return True
    s = str(text).strip().lower()
    return any(s.startswith(p) for p in _GEN_ERROR_PREFIXES)


def _clean_generated(text):
    return (text or "").replace("```json", "").replace("```", "").strip()


def _llm_generate(messages):
    """Call generate(); retry once on error text or empty JSON."""
    generated_text = _clean_generated(generate(list(messages), SYSTEM_PROMPT))
    commands, text = extract_json(generated_text)
    if _generation_failed(generated_text):
        print("[LLM] generate() returned error/empty — already retried inside API helper")
        return generated_text, commands, text
    if not commands:
        print("[LLM] Empty JSON — retrying generate() once")
        generated_text = _clean_generated(generate(list(messages), SYSTEM_PROMPT))
        commands, text = extract_json(generated_text)
        if not commands:
            print("[LLM] Retry still has empty JSON")
        else:
            print("[LLM] Retry recovered JSON commands")
    return generated_text, commands, text


def _capture_screen_b64():
    save_screenshot()
    b64 = ensure_screenshot_b64()
    if not b64:
        print("[SHOT] Screenshot still missing after recapture")
    return b64


def _camera_vision_parts():
    try:
        from services.webcam import grab_jpeg_b64, is_on
        if not is_on():
            return []
        cam = grab_jpeg_b64()
        if not cam:
            return []
        note = "Live webcam (what the user is doing in front of the PC). Use this as a helper along with the screenshot:"
        try:
            from services.face_id import prompt_line
            face_line = prompt_line()
            if face_line:
                note = f"{note} {face_line}"
        except Exception:
            pass
        return [
            {"type": "text", "text": note},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{cam}"}},
        ]
    except Exception:
        return []


def _answer_screen_question(voice_text):
    """One screenshot + spoken description. No mouse or extra commands."""
    add_task(voice_text)
    update_agent_status(t("thinking"))
    fullscreen_img = _capture_screen_b64()
    if not fullscreen_img:
        update_agent_response(t("screen_unknown"), speak=True)
        complete_current_task()
        return
    try:
        import pyautogui
        sw, sh = pyautogui.size()
    except Exception:
        sw, sh = 0, 0
    messages = [{
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    f'User said: "{voice_text}". Answer from this screenshot in ONE short spoken '
                    "sentence (max 20 words): name the main apps/windows, nothing else. "
                    "Do not click, move the mouse, type, or open apps. "
                    "Return [Commands] with only "
                    '[{"command":"answer","params":{"text":"your description"}}].'
                ),
            },
            {"type": "text", "text": f"Current screenshot ({sw}x{sh}, height-scaled to 720px):"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{fullscreen_img}"}},
            *_camera_vision_parts(),
        ],
    }]
    generated_text, commands, _ = _llm_generate(messages)
    spoken = ""
    for c in commands or []:
        if c.get("command") == "answer":
            spoken = str((c.get("params") or {}).get("text") or "").strip()
            if spoken:
                break
    if not spoken:
        spoken = parse_response_text(generated_text)
    if not spoken or _generation_failed(generated_text):
        spoken = t("screen_unknown")
    update_agent_response(spoken, speak=True)
    complete_current_task()
    print(f"[FAST] screen_question {spoken[:80]}")


def run_desktop_agent(task, max_iterations=15, use_voice=True, voice_model="tiny", voice_language="en"):
    global _last_cursor_position, _last_screen_dimensions, agent_running, voice_processor_ref
    global cancel_requested, voice_backlog

    voice_processor = None
    if use_voice and VOICE_AVAILABLE:
        try:
            voice_processor = VoiceInputProcessor(
                model_name=voice_model,
                language=voice_language,
                callback=lambda text: print(f"[Voice] Detected: {text}")
            )
            voice_processor.start()
            voice_processor_ref = voice_processor
            if status_window:
                try:
                    status_window.root.after_idle(status_window._sync_mic_combo)
                except Exception:
                    pass
            print("Voice control active. Speak to give commands.")
        except Exception as e:
            print(f"Voice init error: {e}")
            print("Continuing without voice.")
            use_voice = False
    else:
        if use_voice and not VOICE_AVAILABLE:
            print("Voice module not available. Continuing without voice.")
        use_voice = False

    voice_processor_ref = voice_processor

    if task:
        add_task(task)

    conversation_messages = []

    try:
        while agent_running:
            _wait_until_tts_idle()
            voice_text = None
            busy_reason = None
            try:
                from services.busy_audio import refresh_busy, hold_commands
                from services.voice_input import ptt_is_down as _ptt, is_mic_muted
                # Typed commands bypass the mic gates (muted mic, meeting hold).
                if is_mic_muted() and not _ptt() and not voice_backlog:
                    update_agent_status(t("mic_off"))
                    time.sleep(0.25)
                    continue
                busy_reason = refresh_busy()
                if hold_commands(busy_reason) and not _ptt() and not voice_backlog:
                    update_agent_status(t("busy_meeting"))
                    if use_voice and voice_processor:
                        from services.busy_audio import command_through_media
                        from services.voice_input import is_own_voice_echo
                        command = None
                        for uttered in voice_processor.get_all_transcriptions():
                            if not uttered or not uttered.strip():
                                continue
                            uttered = uttered.strip()
                            if is_own_voice_echo(uttered):
                                continue
                            pierce = command_through_media(uttered)
                            if pierce:
                                command = pierce
                                break
                        if command:
                            voice_text = command
                        else:
                            time.sleep(0.25)
                            continue
                    else:
                        time.sleep(0.25)
                        continue
            except Exception:
                pass
            if not voice_text:
                update_agent_status(t("listening"))
                pending = []
                if use_voice and voice_processor and not voice_backlog:
                    first = voice_processor.get_transcription(block=True, timeout=0.3)
                    if first is not None:
                        pending.append(first)
                else:
                    time.sleep(0.3)

                from services.smart_features import match_voice_quit, match_voice_cancel
                if voice_backlog:
                    voice_text = voice_backlog.pop(0)
                    if match_voice_quit(voice_text):
                        request_quit("voice")
                        break
                    if match_voice_cancel(voice_text):
                        print("[CANCEL] Nothing running.")
                        continue
                elif use_voice and voice_processor:
                    from services.voice_input import is_own_voice_echo
                    transcriptions = pending + voice_processor.get_all_transcriptions()
                    for uttered in transcriptions:
                        if uttered and uttered.strip():
                            if is_own_voice_echo(uttered):
                                print(f"[MIC] Ignored echo: {uttered}")
                                continue
                            if match_voice_quit(uttered):
                                request_quit("voice")
                                break
                            if match_voice_cancel(uttered):
                                print("[CANCEL] Nothing running.")
                                continue
                            voice_text = uttered.strip()

            if not agent_running:
                break

            if not voice_text:
                continue

            try:
                from services.personal import harvest_personal
                harvest_personal(voice_text)
            except Exception:
                pass

            try:
                from services.smart_features import match_fast_desktop as _peek_fast
                peek = _peek_fast(voice_text)
            except Exception:
                peek = None
            if peek != "hide_davi" and status_window and not _user_quit and agent_running:
                try:
                    status_window.root.after_idle(status_window.show_overlay)
                except Exception:
                    pass

            try:
                from services.tts import stop_speaking as _stop_tts
                _stop_tts()
            except Exception:
                pass

            try:
                cancel_requested = False
                set_cancel_flag(False)
                original_voice_text = voice_text

                # Personal features (dictation, notes, schedules, watchers) get
                # first refusal, then the original media/app fast paths.
                if _handle_personal_voice(voice_text):
                    continue

                # Pre-LLM fast handling: reminders, media, lock, screenshot, volume
                fast_handled = False
                try:
                    from services.smart_features import (
                        parse_reminder, add_reminder, match_fast_desktop, run_fast_desktop,
                        match_continue, get_unfinished_task, save_last_task,
                        match_fast_open_app, match_fast_switch_app, open_app_via_start,
                        match_fast_site, match_fast_site_search, open_url,
                        match_screen_question, handle_empty_recycle_voice,
                        handle_restart_pc_voice, match_restart_davi, match_read_clipboard,
                        read_clipboard_for_tts, same_fast_recently, mark_fast,
                    )

                    reminder_parsed = parse_reminder(voice_text)
                    if reminder_parsed:
                        r_text, r_secs = reminder_parsed
                        fire = add_reminder(r_text, r_secs)
                        mins = max(1, r_secs // 60) if r_secs >= 60 else 0
                        if r_secs < 60:
                            resp = f"{fire} · {r_text} ({r_secs}s)"
                        else:
                            resp = f"{fire} · {r_text} ({mins}m)"
                        add_task(voice_text)
                        complete_current_task()
                        update_agent_response(resp)
                        print(f"[FAST] reminder {resp}")
                        fast_handled = True
                    else:
                        empty_recycle_voice = handle_empty_recycle_voice(voice_text)
                        if empty_recycle_voice:
                            kind, payload = empty_recycle_voice
                            add_task(voice_text)
                            complete_current_task()
                            if kind == "ask":
                                msg = t("empty_recycle_need_confirm")
                            else:
                                ok = bool((payload or {}).get("success")) if isinstance(payload, dict) else False
                                msg = t("empty_recycle_done") if ok else (
                                    (payload or {}).get("message") if isinstance(payload, dict) else t("empty_recycle_need_confirm")
                                )
                            update_agent_response(msg, speak=True)
                            print(f"[FAST] empty_recycle {kind} {msg}")
                            fast_handled = True
                        else:
                            restart_pc_voice = handle_restart_pc_voice(voice_text)
                            if restart_pc_voice:
                                kind, payload = restart_pc_voice
                                add_task(voice_text)
                                complete_current_task()
                                if kind == "ask":
                                    msg = t("restart_pc_need_confirm")
                                else:
                                    ok = bool((payload or {}).get("success")) if isinstance(payload, dict) else False
                                    msg = t("restart_pc_done") if ok else (
                                        (payload or {}).get("message") if isinstance(payload, dict) else t("restart_pc_need_confirm")
                                    )
                                update_agent_response(msg, speak=True)
                                print(f"[FAST] restart_pc {kind}")
                                fast_handled = True
                            elif match_restart_davi(voice_text):
                                add_task(voice_text)
                                complete_current_task()
                                update_agent_response(t("restart_davi_done"), speak=True)
                                print("[FAST] restart_davi overlay")
                                fast_handled = True
                                restart_overlay_process()
                            elif match_read_clipboard(voice_text):
                                clip = read_clipboard_for_tts(200)
                                add_task(voice_text)
                                complete_current_task()
                                msg = clip if clip else t("clipboard_empty")
                                update_agent_response(msg, speak=True)
                                print(f"[FAST] read_clipboard n={len(clip)}")
                                fast_handled = True
                            elif match_screen_question(voice_text):
                                if same_fast_recently("screen_question"):
                                    print("[FAST] skip repeat screen_question")
                                else:
                                    mark_fast("screen_question")
                                    _answer_screen_question(voice_text)
                                fast_handled = True
                            else:
                                action = match_fast_desktop(voice_text)
                                if action == "time":
                                    now = datetime.now().strftime("%H:%M")
                                    update_agent_response(now)
                                    add_task(voice_text)
                                    complete_current_task()
                                    fast_handled = True
                                elif action and same_fast_recently(action):
                                    print(f"[FAST] skip repeat {action}")
                                    fast_handled = True
                                elif action:
                                    mark_fast(action)
                                    ok, key, extra = run_fast_desktop(action)
                                    msg = t(key) if key else action
                                    if key and extra and "{name}" in msg:
                                        try:
                                            msg = msg.format(name=extra)
                                            extra = ""
                                        except Exception:
                                            pass
                                    if extra and key in (
                                        "weather_line", "battery_line", "wifi_line",
                                        "read_selection", "say_again", "searching_for",
                                        "screen_copied", "copied_reply", "date_typed",
                                        "time_typed",
                                    ):
                                        if key == "say_again":
                                            msg = extra
                                        elif key in ("weather_line", "battery_line", "wifi_line", "read_selection"):
                                            msg = extra or t(key)
                                        else:
                                            msg = f"{t(key)} · {extra}" if extra else t(key)
                                    elif extra:
                                        msg = f"{msg} · {extra}"
                                    if not ok:
                                        fallback = {
                                            "read_selection": "selection_empty",
                                            "say_again": "nothing_to_repeat",
                                            "copy_screen": "no_screen_text",
                                            "search_this": "selection_empty",
                                            "copy_reply": "nothing_to_repeat",
                                            "weather": "weather_fail",
                                            "battery": "battery_unknown",
                                        }.get(action)
                                        if fallback:
                                            msg = t(fallback)
                                    add_task(voice_text)
                                    complete_current_task()
                                    if action == "hide_davi" and status_window:
                                        status_window.root.after_idle(status_window.hide_until_shown)
                                    elif action == "show_davi" and status_window:
                                        status_window.root.after_idle(status_window.show_overlay)
                                    speak = action not in (
                                        "play_pause", "next", "prev", "mute",
                                        "volume_up", "volume_down", "desktop",
                                        "copy", "paste", "cut", "undo", "redo",
                                        "select_all", "save", "stop_talking",
                                    )
                                    if key == "say_again":
                                        speak = True
                                    update_agent_response(msg, speak=speak)
                                    print(f"[FAST] {action} {msg}")
                                    fast_handled = True
                                if not fast_handled:
                                    from services.file_index import parse_request as _parse_file_req, open_recent as _open_recent
                                    req = _parse_file_req(voice_text)
                                    if req:
                                        r = _open_recent(**req)
                                        if r.get("success"):
                                            msg = f"{t('app_opened')} · {r.get('name')}"
                                        else:
                                            msg = t("no_file_found")
                                        add_task(voice_text)
                                        complete_current_task()
                                        update_agent_response(msg, speak=True)
                                        print(f"[FAST] open_recent {req} -> {r.get('name') or r.get('message')}")
                                        fast_handled = True
                                if not fast_handled:
                                    site = match_fast_site(voice_text) or match_fast_site_search(voice_text)
                                    if site:
                                        r = open_url(site)
                                        msg = t("app_opened") + f" · {_site_label(site)}"
                                        if not r.get("success"):
                                            msg = r.get("error") or msg
                                        add_task(voice_text)
                                        complete_current_task()
                                        update_agent_response(msg, speak=True)
                                        print(f"[FAST] site {site}")
                                        fast_handled = True
                                if not fast_handled:
                                    # "run routine X" is a routine, not an app called "routine X".
                                    from services.personal import match_run_routine as _is_routine
                                    app_name = None if _is_routine(voice_text) else match_fast_open_app(voice_text)
                                    if app_name:
                                        r = open_app_via_start(app_name)
                                        msg = f"{t('app_opened')} · {app_name}"
                                        if not r.get("success"):
                                            msg = r.get("message") or msg
                                        add_task(voice_text)
                                        complete_current_task()
                                        update_agent_response(msg, speak=True)
                                        print(f"[FAST] open_app {msg}")
                                        fast_handled = True
                                    else:
                                        sw = match_fast_switch_app(voice_text)
                                        if sw is not None:
                                            from services.windows_ops import switch_app as _switch_app
                                            mode, title = sw
                                            r = _switch_app(title, mode=mode)
                                            extra = r.get("window") or title or mode
                                            msg = f"{t('switch_done')} · {extra}"
                                            if not r.get("success"):
                                                msg = r.get("message") or msg
                                            add_task(voice_text)
                                            complete_current_task()
                                            update_agent_response(msg, speak=True)
                                            print(f"[FAST] switch_app {msg}")
                                            fast_handled = True
                except Exception as e:
                    print(f"[FAST] Error: {e}")

                if fast_handled:
                    continue

                task_seed = original_voice_text
                user_utterance = original_voice_text
                try:
                    from services.personal import match_run_routine, find_routine
                    routine_name = match_run_routine(voice_text)
                    if routine_name:
                        routine = find_routine(routine_name)
                        if not routine:
                            update_agent_response(f"{t('routine_missing')} · {routine_name}")
                            add_task(voice_text)
                            complete_current_task()
                            continue
                        steps = "; ".join(f"{i+1}) {s}" for i, s in enumerate(routine["steps"]))
                        update_agent_response(f"{t('routine_running')} · {routine['name']}")
                        print(f"[ROUTINE] {routine['name']}: {steps}")
                        task_seed = f"{routine['name']}: {steps}"
                        user_utterance = task_seed
                        original_voice_text = task_seed
                        voice_text = (
                            f"Run the user's saved routine \"{routine['name']}\". "
                            f"Do these steps in order, then stop: {steps}"
                        )
                except Exception as e:
                    print(f"[ROUTINE] {e}")

                try:
                    from services.smart_features import match_continue, get_unfinished_task, save_last_task
                    if match_continue(voice_text):
                        prev = get_unfinished_task()
                        if not prev:
                            update_agent_response(t("nothing_to_continue"))
                            add_task(voice_text)
                            complete_current_task()
                            continue
                        update_agent_response(t("continue_task"))
                        task_seed = prev
                        user_utterance = prev
                        original_voice_text = prev
                        voice_text = (
                            f'Continue and finish this unfinished desktop task from where you left off: "{prev}". '
                            "Do not start a different task."
                        )
                except Exception as e:
                    print(f"[CONTINUE] {e}")

                add_task(task_seed)
                print(f"\n[You] {user_utterance}")
                update_agent_status(t("thinking"))

                fullscreen_img = _capture_screen_b64()

                try:
                    import pyautogui
                    sw, sh = pyautogui.size()
                except Exception:
                    sw, sh = 0, 0
                message_content = [
                    {"type": "text", "text": f"User said: {voice_text}"},
                    {"type": "text", "text": _pc_context(include_apps=True)},
                    {"type": "text", "text": "Current screenshot (height-scaled to 720px):"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{fullscreen_img}"}},
                ]
                message_content.extend(_camera_vision_parts())

                conversation_messages.append({'role': 'user', 'content': message_content})
                conversation_messages = _trim_conversation(conversation_messages)

                generated_text, commands, text = _llm_generate(conversation_messages)

                response_text = parse_response_text(generated_text)
                conversation_messages.append({'role': 'assistant', 'content': [{"type": "text", "text": generated_text}]})

                # If answer command present, don't TTS the response text (answer handles its own TTS)
                has_answer = any(c.get('command') == 'answer' for c in commands) if commands else False

                if response_text:
                    update_agent_response(response_text, speak=not has_answer)
                    print(f"[Agent] {response_text}")

                if not commands:
                    print("[Agent] No commands, back to listening.")
                    if response_text and not has_answer:
                        # Already spoken via update_agent_response.
                        pass
                    continue

                if commands:
                    action_commands = [c for c in commands if c.get('command') != 'listen']
                    desktop_actions = [
                        c for c in action_commands
                        if c.get('command') not in _NON_DESKTOP_CMDS
                    ]
                    last_results = []
                    need_verify = bool(desktop_actions)
                    task_stuck = False
                    if not need_verify and not has_answer:
                        try:
                            from services.smart_features import looks_like_desktop_task
                            if looks_like_desktop_task(user_utterance):
                                need_verify = True
                                print("[FOLLOW] Listen too early — verifying on screenshot")
                        except Exception:
                            pass

                    if need_verify:
                        try:
                            from services.smart_features import save_last_task
                            save_last_task(user_utterance, "unfinished")
                        except Exception:
                            pass

                    if action_commands:
                        update_agent_status(t("executing"))
                        last_results = process_commands(action_commands)
                        for result in last_results:
                            s = "+" if result["success"] else "-"
                            print(f"  {s} {result['command']}: {result['message']}")
                        if get_cancel_flag() or any(r.get("command") == "cancelled" for r in last_results):
                            cancel_requested = True

                    # Ignore listen on the first turn if we already acted — screenshot
                    # has not been verified yet. Q&A (answer only) does not follow up.
                    # Listen-only on a desktop request also verifies once (premature listen).
                    if need_verify and not cancel_requested:
                        time.sleep(0.6)
                        from services.loop_guard import (
                            SAME_LIMIT, bump_streak, fingerprint as _action_fp,
                            stuck_decision, think_prompt,
                        )
                        act_fp, act_streak = bump_streak(None, 0, action_commands)
                        thought_for = None
                        # Shell/file work (build → read error → fix → rebuild) needs more turns than UI clicking.
                        deep = any(c.get("command") in _VERBOSE_RESULT_CMDS for c in action_commands)
                        follow_cap = max(1, min(int(max_iterations or SAME_LIMIT), 25 if deep else 12))
                        for step in range(follow_cap):
                            if not agent_running or cancel_requested or get_cancel_flag():
                                if get_cancel_flag():
                                    cancel_requested = True
                                break

                            if use_voice and voice_processor:
                                new_input = voice_processor.get_all_transcriptions()
                                if new_input:
                                    new_voice = None
                                    from services.smart_features import match_voice_quit, match_voice_cancel
                                    for ni in new_input:
                                        if not ni or not str(ni).strip():
                                            continue
                                        if match_voice_quit(ni):
                                            request_quit("voice")
                                            break
                                        if match_voice_cancel(ni):
                                            cancel_requested = True
                                            set_cancel_flag(True)
                                            print("[CANCEL] Task cancelled.")
                                            update_agent_status(t("cancelled"))
                                            update_agent_response(t("cancelled"), speak=False)
                                            break
                                        new_voice = ni.strip()
                                    if not agent_running or cancel_requested:
                                        break
                                    if new_voice:
                                        print(f"\n[You] {new_voice}")
                                        update_agent_response("Switching to new request.", speak=False)
                                        voice_backlog.append(new_voice)
                                        voice_text = new_voice
                                        break

                            if voice_backlog:
                                break

                            try:
                                stuck_mode = stuck_decision(act_streak, act_fp, thought_for)
                                if stuck_mode == "stop":
                                    print(f"[STUCK] Same action {act_streak}x — stopping")
                                    task_stuck = True
                                    update_agent_response(t("stuck_stop"), speak=True)
                                    break

                                fullscreen_img = _capture_screen_b64()
                                follow_text = (
                                    f'Task: "{original_voice_text}". NOT done unless the full request is satisfied.\n'
                                    f"{_pc_context(include_apps=False)}\n"
                                    f"Last command results:\n{_command_results_text(last_results)}\n"
                                )
                                if stuck_mode == "think":
                                    thought_for = act_fp
                                    follow_text += think_prompt(act_fp, act_streak)
                                    update_agent_response(t("stuck_think"), speak=False)
                                    print(f"[STUCK] Rethink after {act_streak}x {act_fp}")
                                elif act_streak >= 3:
                                    follow_text += (
                                        "Look at the screenshot. The last action already ran "
                                        f"{act_streak} times. If the screen did not change, "
                                        "do NOT repeat it — switch method or listen.\n"
                                    )
                                else:
                                    follow_text += (
                                        "Look at the screenshot. If the task is complete, send listen. "
                                        "Otherwise send the NEXT commands. If the last action did not "
                                        "change the screen, do not send it again."
                                    )
                                follow_content = [
                                    {"type": "text", "text": follow_text},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{fullscreen_img}"}}
                                ]
                                conversation_messages.append({'role': 'user', 'content': follow_content})
                                conversation_messages = _trim_conversation(conversation_messages)

                                update_agent_status(f"{t('step')} {step+2}")
                                generated_text, commands, _ = _llm_generate(conversation_messages)
                                conversation_messages.append({'role': 'assistant', 'content': [{"type": "text", "text": generated_text}]})

                                resp = parse_response_text(generated_text)
                                if resp:
                                    update_agent_response(resp, speak=False)
                                    print(f"[Agent] {resp}")

                                if not commands:
                                    break
                                action_commands = [c for c in commands if c.get('command') != 'listen']
                                has_listen = any(c.get('command') == 'listen' for c in commands)
                                if action_commands:
                                    next_fp = _action_fp(action_commands)
                                    if stuck_mode == "think" and next_fp and next_fp == act_fp:
                                        print("[STUCK] Same action after rethink — not executing")
                                        task_stuck = True
                                        update_agent_response(t("stuck_stop"), speak=True)
                                        break
                                    update_agent_status(t("executing"))
                                    last_results = process_commands(action_commands)
                                    for result in last_results:
                                        s = "+" if result["success"] else "-"
                                        print(f"  {s} {result['command']}: {result['message']}")
                                    act_fp, act_streak = bump_streak(act_fp, act_streak, action_commands)
                                    if get_cancel_flag() or any(r.get("command") == "cancelled" for r in last_results):
                                        cancel_requested = True
                                        break
                                    # Mixed listen+actions: they have not verified the new actions yet.
                                    time.sleep(0.6)
                                    continue
                                if has_listen:
                                    break
                                break
                            except Exception as e:
                                print(f"[ERROR] Step {step+2} failed: {e}")
                                break

                    if cancel_requested:
                        cancel_requested = False
                        try:
                            set_cancel_flag(False)
                        except Exception:
                            pass
                        if need_verify:
                            try:
                                from services.smart_features import save_last_task
                                save_last_task(user_utterance, "cancelled")
                            except Exception:
                                pass
                        cancel_current_task()
                        msg = t("cancelled")
                        update_agent_status(msg)
                        update_agent_response(msg, speak=False)
                        time.sleep(1.15)
                        continue

                if not voice_backlog:
                    try:
                        from services.smart_features import save_last_task
                        if desktop_actions or need_verify:
                            save_last_task(user_utterance, "unfinished" if task_stuck else "done")
                    except Exception:
                        pass
                complete_current_task()
                if voice_backlog:
                    continue

            except Exception as e:
                print(f"[ERROR] {e}")
                complete_current_task()
                import traceback
                traceback.print_exc()
                update_agent_status(t("listening"))
                time.sleep(1)

    finally:
        update_agent_status(t("stopping"))
        agent_running = False
        if voice_processor:
            voice_processor.stop()
        print("Agent stopped.")


def _run_desktop_agent_supervised(task, max_iterations, use_voice, voice_model, voice_language):
    """Run the agent on a worker thread. If that thread dies, Error + TTS, restart once."""
    global agent_running
    kwargs = {
        "task": task,
        "max_iterations": max_iterations,
        "use_voice": use_voice,
        "voice_model": voice_model,
        "voice_language": voice_language,
    }
    restarted = False
    while True:
        crash = []

        def _agent_worker():
            try:
                run_desktop_agent(**kwargs)
            except Exception as exc:
                crash.append(exc)
                print(f"[WATCHDOG] Agent thread crashed: {exc}")
                traceback.print_exc()

        agent_thread = threading.Thread(target=_agent_worker, name="davi-agent", daemon=True)
        agent_thread.start()
        agent_thread.join()
        if _user_quit or stop_event.is_set() or not agent_running or not crash:
            return
        update_agent_status(t("error_status"))
        if restarted:
            print("[WATCHDOG] Agent died again — not restarting.")
            return
        restarted = True
        print("[WATCHDOG] Agent thread died — restarting loop once.")
        try:
            tts_speak(t("crashed_restart"))
        except Exception:
            try:
                tts_speak("I crashed, restarting loop")
            except Exception:
                pass
        if _user_quit or stop_event.is_set():
            return
        agent_running = True
        kwargs["task"] = None


if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description="Desktop Agent - Voice-Controlled Desktop Automation")
    parser.add_argument("task", nargs="?", default=None,
                        help="Initial task (optional - leave empty for standby mode)")
    parser.add_argument("--no-voice", action="store_true", help="Disable voice input")
    parser.add_argument("--voice-model", default="base", choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper model size")
    parser.add_argument("--voice-language", default="en", help="Voice recognition language (default: en)")
    parser.add_argument("--max-iterations", type=int, default=15,
                        help="Max iterations per task")

    args = parser.parse_args()

    try:
        from services.safety import trim_crash_log
        trim_crash_log(_CRASH_LOG_PATH)
    except Exception:
        pass

    if not acquire_single_instance():
        print("[MAIN] Aemyos already running - not opening a second overlay.")
        print("[MAIN] Use Ctrl+Shift+Q in the existing window, or close the old process.")
        sys.exit(0)

    if args.task:
        print(f"Desktop Agent starting with task: {args.task}")
    else:
        print("Desktop Agent starting in standby mode. Speak to give commands.")
    print(f"Voice control: {'off' if args.no_voice else 'on'}")

    try:
        load_persisted_tasks()
        print(f"[MAIN] Restored {len(task_queue)} tasks from memory")
    except Exception as e:
        print(f"[MAIN] Task restore: {e}")

    try:
        from services.personal import strip_media_from_memory, life_briefing
        strip_media_from_memory()
        brief = life_briefing()
        if brief:
            print(f"[LIFE] {brief}")
    except Exception as e:
        print(f"[LIFE] restore: {e}")

    status_thread = threading.Thread(target=run_status_overlay, daemon=True)
    status_thread.start()

    key_listener = start_key_listener()

    # The cmd/python console uses the Python snake icon. Hide it so the
    # taskbar button is the overlay with assets/icon.ico.
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

    update_agent_status(t("starting"))

    # Start browser bridge for Chrome extension
    try:
        from services.browser_bridge import get_bridge
        bridge = get_bridge()
        print("[MAIN] Browser bridge started. Install Aemyos extension in Chrome to enable browser commands.")
    except Exception as e:
        print(f"[MAIN] Browser bridge failed to start: {e}")

    # Start smart features
    try:
        from services.smart_features import set_tts_func, start_clipboard_monitor, start_sysinfo_monitor, load_persisted_reminders
        set_tts_func(tts_speak)
        from services.watchers import set_notifier
        set_notifier(lambda msg: update_agent_response(msg, speak=True))
        start_clipboard_monitor()
        start_sysinfo_monitor()
        n = load_persisted_reminders()
        print(f"[MAIN] Smart features loaded (clipboard, sysinfo, reminders={n}, desktop)")
    except Exception as e:
        print(f"[MAIN] Smart features error: {e}")

    try:
        from services.file_index import start_indexer
        start_indexer()
    except Exception as e:
        print(f"[FILES] indexer: {e}")

    try:
        _tg_token = (os.environ.get("DAVI_TELEGRAM_TOKEN") or "").strip()
        if _tg_token:
            from services import telegram_bot
            _code = telegram_bot.start(
                _tg_token, os.environ.get("DAVI_TELEGRAM_CHAT_ID", ""), enqueue=enqueue_remote_command,
            )
            _reply_sinks.append(telegram_bot.notify)
            print("[TG] bot started (paired)" if not _code else f"[TG] bot started — pairing code: {_code}")
    except Exception as e:
        print(f"[TG] start failed: {e}")

    try:
        from services.safety import set_refuse_hook

        def _on_destructive_refuse(spoken):
            win = status_window
            if win is not None:
                try:
                    win.root.after_idle(win.show_safety_toast, spoken)
                except Exception:
                    pass

        set_refuse_hook(_on_destructive_refuse)
    except Exception as e:
        print(f"[MAIN] Safety hook error: {e}")

    apply_runtime_language(os.environ.get("DAVI_LANGUAGE", "en"))
    from services.i18n import set_voice_gender, get_voice_gender
    set_voice_gender(get_voice_gender())

    def _get_startup_greeting():
        from services.i18n import greeting
        name = ""
        try:
            from services.personal import known_user_name
            name = known_user_name()
        except Exception:
            name = ""
        return greeting(name)

    greeting = _get_startup_greeting()
    try:
        from services.busy_audio import refresh_busy
        refresh_busy()
    except Exception:
        pass
    update_agent_response(greeting)

    try:
        _run_desktop_agent_supervised(
            task=args.task,
            max_iterations=args.max_iterations,
            use_voice=not args.no_voice,
            voice_model=args.voice_model,
            voice_language=whisper_language(),
        )
    except Exception as e:
        print(f"Agent error: {e}")
    finally:
        agent_running = False
        if key_listener.is_alive():
            key_listener.stop()
        print("Program ended.")
