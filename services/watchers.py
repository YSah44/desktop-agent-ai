"""Background watchers that wait for something to happen and then speak up.

Two kinds are supported:
  - "text": poll screen OCR until a phrase shows up (a build finishing, an
    upload completing, a name appearing in a queue).
  - "download": poll the Downloads folder for a newly finished file.

Watchers are deliberately cheap: OCR is local and only runs on a timer, and
each watcher fires once and then retires so a forgotten watcher cannot nag.
"""
import os
import re
import threading
import time
from datetime import datetime

POLL_SECONDS = 4
MAX_WATCHERS = 8
DEFAULT_TIMEOUT = 3 * 3600

_watchers = []
_lock = threading.Lock()
_thread = None
_seq = 0
_notify = None


def set_notifier(func):
    """func(message) is called when a watcher fires."""
    global _notify
    _notify = func


def _downloads_dir():
    return os.path.join(os.path.expanduser("~"), "Downloads")


def _download_snapshot():
    try:
        return {
            name for name in os.listdir(_downloads_dir())
            # Partial files mean the download is still running.
            if not name.endswith((".crdownload", ".part", ".tmp", ".partial"))
        }
    except OSError:
        return set()


def add_text_watch(query, timeout=DEFAULT_TIMEOUT):
    query = (query or "").strip()
    if not query:
        return None
    return _add({"kind": "text", "query": query, "timeout": timeout})


def add_download_watch(timeout=DEFAULT_TIMEOUT):
    return _add({"kind": "download", "baseline": _download_snapshot(), "timeout": timeout})


def _add(spec):
    global _seq
    with _lock:
        if len(_watchers) >= MAX_WATCHERS:
            return None
        _seq += 1
        spec["id"] = _seq
        spec["created"] = datetime.now()
        spec["expires"] = time.time() + max(60, int(spec.get("timeout") or DEFAULT_TIMEOUT))
        _watchers.append(spec)
    _ensure_thread()
    return spec["id"]


def list_watches():
    with _lock:
        return [
            {"id": w["id"], "kind": w["kind"], "query": w.get("query", "")}
            for w in _watchers
        ]


def clear_watches():
    with _lock:
        count = len(_watchers)
        _watchers.clear()
    return count


def cancel_watch(wid):
    try:
        wid = int(wid)
    except (TypeError, ValueError):
        return False
    with _lock:
        before = len(_watchers)
        _watchers[:] = [w for w in _watchers if w["id"] != wid]
        return len(_watchers) != before


def _ensure_thread():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, daemon=True)
        _thread.start()


def _fire(message):
    if _notify:
        try:
            _notify(message)
        except Exception as exc:
            print(f"[WATCH] notify: {exc}")
    try:
        from services.smart_features import show_notification
        show_notification("Aemyos", re.sub(r"[<>&]", "", message)[:120])
    except Exception:
        pass


def _check_text(watcher, screen_text):
    if screen_text is None:
        return None
    needle = watcher["query"].lower()
    if needle in screen_text:
        return f"{watcher['query']}"
    return None


def _check_download(watcher):
    current = _download_snapshot()
    new = current - watcher.get("baseline", set())
    if new:
        # Report the most recent arrival rather than an arbitrary one.
        try:
            newest = max(new, key=lambda n: os.path.getmtime(os.path.join(_downloads_dir(), n)))
        except (OSError, ValueError):
            newest = sorted(new)[0]
        return newest
    return None


def _loop():
    while True:
        with _lock:
            pending = list(_watchers)
        if not pending:
            time.sleep(POLL_SECONDS)
            continue

        # OCR once per pass and share it across every text watcher.
        screen_text = None
        if any(w["kind"] == "text" for w in pending):
            try:
                from services.ocr import screen_text as read_screen_text
                screen_text = (read_screen_text(limit=200) or "").lower()
            except Exception as exc:
                print(f"[WATCH] ocr: {exc}")
                screen_text = ""

        now = time.time()
        done = []
        for watcher in pending:
            try:
                if now > watcher["expires"]:
                    done.append((watcher, None))
                    continue
                if watcher["kind"] == "text":
                    hit = _check_text(watcher, screen_text)
                else:
                    hit = _check_download(watcher)
                if hit:
                    done.append((watcher, hit))
            except Exception as exc:
                print(f"[WATCH] check: {exc}")

        if done:
            with _lock:
                finished = {w["id"] for w, _ in done}
                _watchers[:] = [w for w in _watchers if w["id"] not in finished]
            for watcher, hit in done:
                if not hit:
                    continue
                try:
                    from services.i18n import t
                    key = "watch_text_hit" if watcher["kind"] == "text" else "watch_download_hit"
                    _fire(t(key).replace("{what}", str(hit)))
                except Exception:
                    _fire(f"Found: {hit}")

        time.sleep(POLL_SECONDS)
