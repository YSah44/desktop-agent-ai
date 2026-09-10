"""Everyday voice actions that should never wait on the model.

These are the things a person sitting at a PC actually says to a voice
agent: undo, read this, copy the screen, what's the weather, hide, say
that again. Exact-phrase matching lives in smart_features; the work
happens here.
"""
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from urllib.parse import quote

CREATE_NO_WINDOW = 0x08000000

_last_spoken = ""
_spoken_at = 0.0
_spoken_hist = []
_hidden = False


def remember_spoken(text):
    global _last_spoken, _spoken_hist, _spoken_at
    text = (text or "").strip()
    if text and text != _last_spoken:
        _last_spoken = text
        _spoken_at = time.time()
        _spoken_hist.append(text)
        _spoken_hist = _spoken_hist[-5:]


def last_spoken():
    return _last_spoken


def spoken_at():
    return float(_spoken_at or 0.0)


def recent_spoken():
    return list(_spoken_hist)


def is_hidden():
    return _hidden


def set_hidden(value):
    global _hidden
    _hidden = bool(value)


def _hotkey(*keys):
    from services.keyboard_module import press_hotkey
    return press_hotkey(*keys)


def undo():
    return {"success": _hotkey("ctrl", "z")}


def redo():
    return {"success": _hotkey("ctrl", "y")}


def copy_keys():
    return {"success": _hotkey("ctrl", "c")}


def paste_keys():
    return {"success": _hotkey("ctrl", "v")}


def cut_keys():
    return {"success": _hotkey("ctrl", "x")}


def select_all():
    return {"success": _hotkey("ctrl", "a")}


def save_file():
    return {"success": _hotkey("ctrl", "s")}


def _clip():
    try:
        import pyperclip
        return (pyperclip.paste() or "").strip()
    except Exception:
        return ""


def _set_clip(text):
    import pyperclip
    pyperclip.copy(text or "")


def grab_selection(wait=0.18):
    """Ctrl+C the focused app, then read the clipboard."""
    before = _clip()
    _hotkey("ctrl", "c")
    time.sleep(wait)
    after = _clip()
    if after and after != before:
        return after
    return after or ""


def read_selection():
    text = grab_selection()
    return {"success": bool(text), "text": text[:800]}


def copy_screen_text(limit=80):
    try:
        from services.ocr import screen_text
        text = (screen_text(limit=limit) or "").strip()
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    if not text:
        return {"success": False, "text": ""}
    try:
        _set_clip(text)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "text": text[:400], "n": len(text)}


def search_selection():
    text = grab_selection()
    if not text:
        return {"success": False, "text": ""}
    url = "https://www.google.com/search?q=" + quote(text[:200])
    try:
        os.startfile(url)
    except Exception:
        import webbrowser
        webbrowser.open(url)
    return {"success": True, "text": text[:120]}


def type_date():
    from services.keyboard_module import type_text
    stamp = datetime.now().strftime("%Y-%m-%d")
    type_text(stamp)
    return {"success": True, "text": stamp}


def type_time():
    from services.keyboard_module import type_text
    stamp = datetime.now().strftime("%H:%M")
    type_text(stamp)
    return {"success": True, "text": stamp}


def type_once(text):
    from services.keyboard_module import type_text
    text = (text or "").strip()
    if not text:
        return {"success": False}
    type_text(text)
    return {"success": True, "text": text[:120]}


def window_action(action):
    from services.windows_ops import manage_window
    return manage_window(action)


def copy_last_reply():
    text = last_spoken()
    if not text:
        return {"success": False, "text": ""}
    try:
        _set_clip(text)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "text": text[:160]}


def stop_talking():
    try:
        from services.tts import stop_speaking
        stop_speaking()
    except Exception:
        pass
    return {"success": True}


def nudge_rate(delta):
    import services.tts as tts
    nxt = max(-50, min(50, int(tts.rate) + int(delta)))
    tts.configure(rate_=nxt)
    try:
        from config import save_env
        save_env(DAVI_TTS_RATE=str(nxt))
    except Exception:
        pass
    return {"success": True, "rate": nxt}


def set_speech(on):
    import services.tts as tts
    tts.configure(enabled_=bool(on))
    try:
        from config import save_env
        save_env(DAVI_TTS_ENABLED="1" if on else "0")
    except Exception:
        pass
    return {"success": True, "on": bool(on)}


def mute_own_mic():
    from services.voice_input import set_mic_muted
    set_mic_muted(True)
    try:
        from config import save_env
        save_env(DAVI_MIC_MUTED="1")
    except Exception:
        pass
    return {"success": True}


def unmute_own_mic():
    from services.voice_input import set_mic_muted
    set_mic_muted(False)
    try:
        from config import save_env
        save_env(DAVI_MIC_MUTED="0")
    except Exception:
        pass
    return {"success": True}


def battery_line():
    from services.smart_features import get_system_info
    info = get_system_info()
    bat = info.get("battery")
    if bat is None:
        return {"success": False, "text": ""}
    charging = info.get("charging")
    extra = "charging" if charging else "on battery"
    return {"success": True, "text": f"{int(bat)}% · {extra}"}


def wifi_line():
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, timeout=6, creationflags=CREATE_NO_WINDOW,
        )
        raw = (proc.stdout or b"").decode("utf-8", "replace")
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    ssid = _field(raw, "SSID")
    signal = _field(raw, "Signal")
    state = _field(raw, "State")
    if not ssid or ssid == "SSID":
        # Second SSID line is the network name; first is BSSID-adjacent.
        names = re.findall(r"^\s*SSID\s*:\s*(.+)$", raw, re.M)
        ssid = names[-1].strip() if names else ""
    if state and "disconnected" in state.lower():
        return {"success": True, "text": "Wi-Fi disconnected"}
    if not ssid:
        return {"success": True, "text": "Wi-Fi off or unknown"}
    bits = [ssid]
    if signal:
        bits.append(signal)
    return {"success": True, "text": " · ".join(bits)}


def _field(raw, name):
    m = re.search(rf"^\s*{name}\s*:\s*(.+)$", raw, re.M | re.I)
    if not m:
        return ""
    return m.group(1).strip()


def weather_line():
    # Open-Meteo at the location Aemyos worked out on its own (see context_facts);
    # wttr.in stays as the fallback.
    try:
        from services.context_facts import weather as _wx
        from services.i18n import get_language
        r = _wx(get_language())
        if r.get("success") and r.get("text"):
            return {"success": True, "text": r["text"][:200]}
    except Exception:
        pass
    try:
        req = urllib.request.Request(
            "https://wttr.in/?format=3",
            headers={"User-Agent": "davi-desktop-agent"},
        )
        with urllib.request.urlopen(req, timeout=7) as resp:
            text = resp.read().decode("utf-8", "replace").strip()
        text = re.sub(r"\s+", " ", text)
        return {"success": bool(text), "text": text[:160]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


_TYPE_ONCE = [
    r"^(?:type this|type that|write this|write that)\s+(.+)$",
    r"^(?:sunu yaz|bunu yaz)\s+(.+)$",
    r"^yaz\s+(.+)$",
]


def match_type_once(text):
    from services.smart_features import _fold_voice, match_dictation_start
    if match_dictation_start(text):
        return None
    folded = _fold_voice(text)
    if folded.startswith("yaz not") or folded.startswith("write note") or folded.startswith("type note"):
        return None
    for pattern in _TYPE_ONCE:
        m = re.search(pattern, folded)
        if m:
            payload = m.group(1).strip()
            if payload and payload not in ("this", "that", "it", "not"):
                from services.personal import _recover_original
                return _recover_original(text, payload)
    return None
