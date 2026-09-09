"""Optional webcam helper. Opens the Windows Camera app and feeds DAVI frames
so she can see what you're doing in front of the PC.

If the Camera app already owns the device, frames come from that window instead
of fighting OpenCV for an exclusive lock.
"""
import ctypes
import os
import threading
import time

_lock = threading.Lock()
_cap = None
_thread = None
_on = False
_frame_jpeg = None
_frame_bgr = None
_index = None

_CAM_TITLES = frozenset(("camera", "kamera", "windows camera", "camera app"))
_CAM_EXES = frozenset(("windowscamera.exe", "video.ui.exe"))


def is_on():
    return bool(_on)


def grab_jpeg_b64():
    with _lock:
        data = _frame_jpeg
    if not data:
        return None
    import base64
    return base64.b64encode(data).decode("ascii")


def grab_bgr():
    with _lock:
        frame = _frame_bgr
    if frame is None:
        return None
    return frame.copy()


def _encode_jpeg(bgr, max_w=640):
    import cv2
    h, w = bgr.shape[:2]
    if w > max_w:
        scale = max_w / float(w)
        bgr = cv2.resize(bgr, (max_w, max(1, int(h * scale))))
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
    if not ok:
        return None
    return buf.tobytes()


def _encode_pil(img, max_w=640):
    from io import BytesIO
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if w > max_w and w > 0:
        scale = max_w / float(w)
        img = img.resize((max_w, max(1, int(h * scale))))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=72)
    return buf.getvalue()


def _open_capture():
    import cv2
    for idx in range(0, 5):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap or not cap.isOpened():
            if cap:
                cap.release()
            cap = cv2.VideoCapture(idx)
        if not cap or not cap.isOpened():
            if cap:
                cap.release()
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            continue
        return cap, idx
    return None, None


def _exe_name(hwnd):
    from services.windows_ops import _pid_of, kernel32

    pid = _pid_of(hwnd)
    if not pid:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_uint32(32768)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value or "").lower()
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _is_camera_window(hwnd):
    from services.windows_ops import _title_of, user32

    if not hwnd or not user32.IsWindow(hwnd):
        return False
    exe = _exe_name(hwnd)
    if exe in _CAM_EXES:
        return True
    title = (_title_of(hwnd) or "").strip().lower()
    if not title:
        return False
    if title in _CAM_TITLES:
        return True
    if title.endswith(" camera") or title.startswith("camera "):
        return True
    if title.endswith(" kamera") or title.startswith("kamera "):
        return True
    return False


def _camera_hwnds():
    from services.windows_ops import WNDENUMPROC, user32

    hits = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            return True
        if _is_camera_window(hwnd):
            hits.append(int(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return hits


def _find_camera_hwnd():
    hits = _camera_hwnds()
    return hits[0] if hits else None


def _camera_exe_running():
    import subprocess
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,
        )
    except Exception:
        return False
    blob = (r.stdout or "").lower()
    return any(exe in blob for exe in _CAM_EXES)


def _kill_camera_exes():
    import subprocess
    for exe in ("WindowsCamera.exe", "Video.UI.exe"):
        try:
            subprocess.run(
                ["taskkill", "/IM", exe, "/F"],
                capture_output=True, timeout=5,
                creationflags=0x08000000,
            )
        except Exception:
            pass


def _close_camera_app():
    """Close the Windows Camera window — helper off is not enough."""
    from services.windows_ops import user32

    hwnds = _camera_hwnds()
    for hwnd in hwnds:
        try:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            pass
    deadline = time.time() + 1.4
    while time.time() < deadline:
        if not _camera_hwnds() and not _camera_exe_running():
            return True
        time.sleep(0.12)
    if _camera_hwnds() or _camera_exe_running():
        _kill_camera_exes()
    return True


def _grab_camera_window():
    from services.windows_ops import RECT, user32
    from PIL import ImageGrab

    hwnd = _find_camera_hwnd()
    if not hwnd:
        return None
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    if right - left < 80 or bottom - top < 80:
        return None
    img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    if img is None:
        return None
    return img


def _store_frame(jpg, bgr=None):
    with _lock:
        global _frame_jpeg, _frame_bgr
        if jpg:
            _frame_jpeg = jpg
        if bgr is not None:
            _frame_bgr = bgr


def _observe_face(bgr):
    if bgr is None:
        return
    try:
        from services.face_id import observe_frame
        observe_frame(bgr)
    except Exception:
        pass


def _pil_to_bgr(img):
    import numpy as np
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.array(img)[:, :, ::-1].copy()


def _loop(cap):
    global _on
    while _on:
        got = False
        if cap is not None:
            try:
                ok, frame = cap.read()
                if ok and frame is not None:
                    jpg = _encode_jpeg(frame)
                    if jpg:
                        _store_frame(jpg, frame)
                        _observe_face(frame)
                        got = True
            except Exception:
                pass
        if not got:
            try:
                img = _grab_camera_window()
                if img is not None:
                    jpg = _encode_pil(img)
                    bgr = _pil_to_bgr(img)
                    if jpg:
                        _store_frame(jpg, bgr)
                        _observe_face(bgr)
            except Exception:
                pass
        time.sleep(0.18)
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass


def _launch_windows_camera():
    """Open Camera via URI / AppID — never Start search or mouse."""
    import subprocess
    targets = (
        "microsoft.windows.camera:",
        r"shell:AppsFolder\Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
    )
    for target in targets:
        try:
            os.startfile(target)
            return True
        except Exception:
            pass
    try:
        subprocess.Popen(
            ["explorer.exe", "microsoft.windows.camera:"],
            creationflags=0x08000000,
        )
        return True
    except Exception:
        return False


def start():
    """Open the Camera app and start grabbing frames for the agent."""
    global _cap, _thread, _on, _index, _frame_jpeg, _frame_bgr
    if _on:
        _launch_windows_camera()
        return {"success": True}
    app_ok = _launch_windows_camera()
    cap, idx = None, None
    # Camera app usually exclusive-locks the device. Only grab with OpenCV
    # when the app did not open, so the user still gets a live helper.
    if not app_ok:
        cap, idx = _open_capture()
    if cap is None and not app_ok:
        return {"success": False, "error": "no camera"}
    with _lock:
        _frame_jpeg = None
        _frame_bgr = None
    _cap = cap
    _index = idx
    _on = True
    _thread = threading.Thread(target=_loop, args=(cap,), daemon=True, name="davi-webcam")
    _thread.start()
    if cap is not None:
        print(f"[CAM] Helper on (device {idx})")
    else:
        print("[CAM] Camera app opened — helper watches that window")
    return {"success": True}


def stop():
    global _cap, _thread, _on, _frame_jpeg, _frame_bgr
    _on = False
    t = _thread
    cap = _cap
    if t and t.is_alive():
        t.join(timeout=1.2)
    _thread = None
    _cap = None
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass
    with _lock:
        _frame_jpeg = None
        _frame_bgr = None
    try:
        _close_camera_app()
    except Exception as e:
        print(f"[CAM] Close app: {e}")
    try:
        from services.face_id import reset_session
        reset_session()
    except Exception:
        pass
    print("[CAM] Camera off")
    return {"success": True}


def toggle():
    if _on:
        stop()
        return {"success": True, "on": False}
    result = start()
    result["on"] = bool(result.get("success"))
    return result
