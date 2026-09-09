"""Guards for shutdown, delete, recycle, send, and purchase actions."""
import os
import re
import time

CONFIRMED_KEYS = ("confirmed", "confirm", "user_confirmed", "explicit")

_SHELL_DESTRUCTIVE = (
    "shutdown", "restart /r", "shutdown.exe",
    "format ", "format.com",
    "del /f", "del /s", "erase /f",
    "rm -rf", "rm -r ", "rmdir /s",
    "remove-item -recurse", "remove-item -force",
    "clear-recyclebin", "empty recycle",
    "reg delete",
)

_CLICK_DESTRUCTIVE = re.compile(
    r"(?i)\b("
    r"send|g[oö]nder|submit order|"
    r"buy now|purchase|sat[iı]n al|checkout|place order|"
    r"pay now|[oö]deme|sipari[sş]i tamamla|confirm (purchase|order|payment)|"
    r"empty recycle|empty (the )?bin|g[uü]venli[gğ]i sil|"
    r"delete permanently|kal[iı]c[iı] olarak sil|"
    r"shut ?down|restart (pc|computer)|bilgisayar[iı] kapat"
    r")\b"
)

_ALWAYS = {"shutdown_pc", "empty_recycle", "delete_file"}
_CLICK_CMDS = {
    "click_ui", "find_control", "move_cursor_to_element",
    "browser_click", "mouse_button",
}


def is_confirmed(command):
    params = command.get("params") or {}
    for key in CONFIRMED_KEYS:
        val = params.get(key)
        if val is True:
            return True
        if isinstance(val, str) and val.strip().lower() in ("1", "true", "yes", "evet"):
            return True
        if val == 1:
            return True
    return False


def _blob(params):
    if not params:
        return ""
    parts = []
    for key in ("name", "text", "query", "selector", "label", "title", "path",
                "command", "url", "value"):
        if params.get(key):
            parts.append(str(params.get(key)))
    return " ".join(parts)


def is_destructive(command):
    name = (command.get("command") or "").lower()
    params = command.get("params") or {}

    if name in _ALWAYS:
        return True

    if name == "run_command":
        text = (params.get("command") or "").lower()
        return any(p in text for p in _SHELL_DESTRUCTIVE)

    if name == "enter_text":
        text = (params.get("text") or "").lower()
        return any(p in text for p in ("shutdown", "format ", "del /f", "rm -rf", "rmdir /s"))

    if name in ("click_ui", "move_cursor_to_element", "browser_click"):
        return bool(_CLICK_DESTRUCTIVE.search(_blob(params)))

    if name == "open_url":
        url = (params.get("url") or "").lower()
        return any(k in url for k in ("checkout", "payment", "purchase", "buy-now"))

    return False


_refuse_hook = None
_last_refuse_ts = 0.0


def set_refuse_hook(fn):
    global _refuse_hook
    _refuse_hook = fn


def _announce_refuse(command_name):
    """TTS + overlay toast so the user hears WHY a command was blocked."""
    global _last_refuse_ts
    now = time.time()
    if now - _last_refuse_ts < 2.5:
        return
    _last_refuse_ts = now
    try:
        from services.i18n import t
        spoken = t("destructive_refused")
    except Exception:
        spoken = (
            "Stopped. That looks destructive — shutdown, delete, empty recycle, "
            "send, or purchase. Say it clearly if you really want it."
        )
    try:
        from services.tts import speak
        speak(spoken)
    except Exception:
        pass
    hook = _refuse_hook
    if hook:
        try:
            hook(spoken)
        except Exception as e:
            print(f"[SAFETY] refuse hook: {e}")
    try:
        from services.smart_features import show_notification
        show_notification("Aemyos", spoken[:120])
    except Exception:
        pass


def trim_crash_log(path, max_bytes=2 * 1024 * 1024, keep_bytes=200 * 1024):
    """If crash.log is huge, keep the last keep_bytes. Never deletes .env or secrets files."""
    try:
        if not path or not os.path.isfile(path):
            return False
        size = os.path.getsize(path)
        if size <= max_bytes:
            return False
        keep = max(1024, int(keep_bytes))
        with open(path, "rb") as f:
            f.seek(max(0, size - keep))
            data = f.read()
        nl = data.find(b"\n")
        if nl != -1:
            data = data[nl + 1:]
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def refuse_if_destructive(command):
    """Return a result dict to append, or None if the command may run."""
    if not is_destructive(command):
        return None
    if is_confirmed(command):
        return None
    pretty = command.get("command")
    _announce_refuse(pretty)
    return {
        "command": pretty,
        "success": False,
        "message": (
            "REFUSED: this looks destructive (shutdown / delete / empty recycle / "
            "send / purchase). Only retry with params.confirmed=true if the user "
            "explicitly asked for that exact action in this request. Otherwise ask them."
        ),
    }
