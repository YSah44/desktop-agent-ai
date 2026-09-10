import threading
import time
import json
import math
import os
import re
import subprocess
import ctypes
from datetime import datetime, timedelta

# ── Reminder Engine ──────────────────────────────────────────────
_reminders = []
_reminder_lock = threading.Lock()
_reminder_thread = None
_tts_func = None
_fired_alerts = []
_reminder_id_seq = 0
from services.paths import DATA_DIR as _MEMORY_DIR
_SCREENSHOTS_DIR = os.path.join(_MEMORY_DIR, "screenshots")


def set_tts_func(func):
    global _tts_func
    _tts_func = func


def _memory_io():
    from services.execute_funcs import load_memory, save_memory
    return load_memory, save_memory


def _persist_reminders_unlocked():
    try:
        load_memory, save_memory = _memory_io()
        mem = load_memory()
        now = datetime.now()
        payload = []
        for r in _reminders:
            age = (now - r["fire_at"]).total_seconds()
            if r["fired"] and age > 300:
                continue
            payload.append({
                "id": r["id"],
                "text": r["text"],
                "fire_at": r["fire_at"].isoformat(timespec="seconds"),
                "fired": bool(r["fired"]),
                "repeat": r.get("repeat") or None,
                "created": r.get("created", ""),
            })
        mem["reminders"] = payload
        save_memory(mem)
    except Exception as e:
        print(f"[REMIND] Persist error: {e}")


def load_persisted_reminders():
    """Restore unfired reminders after restart. Missed ones fire once if < 1h overdue."""
    global _reminder_id_seq
    try:
        load_memory, _save = _memory_io()
        mem = load_memory()
        rows = mem.get("reminders") or []
    except Exception:
        rows = []
    now = datetime.now()
    restored = []
    max_id = 0
    for row in rows:
        try:
            fire_at = datetime.fromisoformat(str(row.get("fire_at", "")))
        except Exception:
            continue
        rid = int(row.get("id") or 0)
        max_id = max(max_id, rid)
        fired = bool(row.get("fired"))
        repeat = row.get("repeat") or None
        overdue = (now - fire_at).total_seconds()
        if repeat:
            # Recurring ones never expire; roll them forward to the next slot.
            nxt = _next_occurrence(fire_at, repeat)
            if nxt:
                fire_at, fired = nxt, False
        elif fired:
            continue
        elif overdue > 3600:
            continue
        restored.append({
            "id": rid or (max_id + 1),
            "text": str(row.get("text") or "Reminder"),
            "fire_at": fire_at,
            "fired": False,
            "repeat": repeat,
            "created": str(row.get("created") or fire_at.strftime("%H:%M")),
        })
        max_id = max(max_id, restored[-1]["id"])
    with _reminder_lock:
        _reminders[:] = restored
        _reminder_id_seq = max(max_id, _reminder_id_seq)
    if restored:
        _ensure_reminder_thread()
    return len(restored)


def add_reminder(text, seconds, repeat=None):
    global _reminder_id_seq
    seconds = max(1, int(seconds))
    fire_at = datetime.now() + timedelta(seconds=seconds)
    with _reminder_lock:
        _reminder_id_seq += 1
        _reminders.append({
            "id": _reminder_id_seq,
            "text": (text or "Reminder").strip() or "Reminder",
            "fire_at": fire_at,
            "fired": False,
            "repeat": repeat or None,
            "created": datetime.now().strftime("%H:%M"),
        })
        _persist_reminders_unlocked()
    _ensure_reminder_thread()
    return fire_at.strftime("%H:%M")


def _next_occurrence(fire_at, repeat):
    """Advance a recurring reminder past now, so a machine that was asleep for
    days does not replay every missed occurrence on wake."""
    if not repeat:
        return None
    now = datetime.now()
    nxt = fire_at
    step = timedelta(weeks=1) if repeat == "weekly" else timedelta(days=1)
    guard = 0
    while nxt <= now and guard < 500:
        nxt += step
        guard += 1
        if repeat == "weekdays":
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
    return nxt


def cancel_reminder(rid):
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return False
    with _reminder_lock:
        before = len(_reminders)
        _reminders[:] = [r for r in _reminders if r.get("id") != rid]
        changed = len(_reminders) != before
        if changed:
            _persist_reminders_unlocked()
        return changed


def format_remaining(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds}s"


def get_reminders():
    with _reminder_lock:
        now = datetime.now()
        return [
            {
                "id": r["id"],
                "text": r["text"],
                "fire_at": r["fire_at"].strftime("%H:%M"),
                "remaining": max(0, int((r["fire_at"] - now).total_seconds())),
                "remaining_label": format_remaining(max(0, int((r["fire_at"] - now).total_seconds()))),
                "fired": r["fired"],
            }
            for r in _reminders if not r["fired"]
        ]


def consume_fired_alerts():
    with _reminder_lock:
        items = list(_fired_alerts)
        _fired_alerts.clear()
        return items


def _speak_reminder(text):
    def _go():
        try:
            from services.i18n import t
            prefix = t("reminder_alert")
        except Exception:
            prefix = "Reminder:"
        if _tts_func:
            try:
                _tts_func(f"{prefix} {text}")
            except Exception:
                pass
    threading.Thread(target=_go, daemon=True).start()


def _ensure_reminder_thread():
    global _reminder_thread
    if _reminder_thread is None or not _reminder_thread.is_alive():
        _reminder_thread = threading.Thread(target=_reminder_loop, daemon=True)
        _reminder_thread.start()


def _reminder_loop():
    while True:
        now = datetime.now()
        fired_now = []
        with _reminder_lock:
            for r in _reminders:
                if not r["fired"] and now >= r["fire_at"]:
                    fired_now.append(dict(r))
                    _fired_alerts.append({"id": r["id"], "text": r["text"]})
                    nxt = _next_occurrence(r["fire_at"], r.get("repeat"))
                    if nxt:
                        r["fire_at"] = nxt
                    else:
                        r["fired"] = True
            _reminders[:] = [
                r for r in _reminders
                if not r["fired"] or (now - r["fire_at"]).total_seconds() < 300
            ]
            if fired_now:
                _persist_reminders_unlocked()
        for r in fired_now:
            _speak_reminder(r["text"])
            try:
                safe = re.sub(r"[<>&]", "", str(r["text"]))[:80]
                show_notification("Aemyos", safe or "Reminder")
            except Exception:
                pass
        time.sleep(2)


# ── System Info (cached, background thread) ─────────────────────

_sys_cache = {"time": "--:--", "date": "", "cpu": 0, "ram_pct": 0, "ram_gb": 0, "ram_total_gb": 0, "battery": None, "charging": False}
_sys_cache_lock = threading.Lock()
_sys_thread = None


def get_system_info():
    with _sys_cache_lock:
        c = dict(_sys_cache)
    c["time"] = datetime.now().strftime("%H:%M")
    c["date"] = datetime.now().strftime("%b %d")
    return c


def start_sysinfo_monitor():
    global _sys_thread
    if _sys_thread and _sys_thread.is_alive():
        return
    _sys_thread = threading.Thread(target=_sysinfo_loop, daemon=True)
    _sys_thread.start()


def _filetime_int(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _read_cpu_times():
    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]
    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        raise OSError("GetSystemTimes failed")
    return _filetime_int(idle), _filetime_int(kernel), _filetime_int(user)


def _read_memory():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        raise OSError("GlobalMemoryStatusEx failed")
    used = stat.ullTotalPhys - stat.ullAvailPhys
    return {
        "ram_pct": int(stat.dwMemoryLoad),
        "ram_gb": round(used / (1024 ** 3), 1),
        "ram_total_gb": round(stat.ullTotalPhys / (1024 ** 3), 1),
    }


def _read_battery():
    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_byte),
            ("BatteryFlag", ctypes.c_byte),
            ("BatteryLifePercent", ctypes.c_byte),
            ("SystemStatusFlag", ctypes.c_byte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]
    status = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None, False
    pct = status.BatteryLifePercent
    if pct < 0 or pct > 100:
        return None, False
    return int(pct), status.ACLineStatus == 1


def _sysinfo_loop():
    import ctypes
    idle_prev = kern_prev = user_prev = None
    while True:
        info = {}
        try:
            idle, kern, user = _read_cpu_times()
            if idle_prev is not None:
                idle_d = idle - idle_prev
                total = (kern - kern_prev) + (user - user_prev)
                busy = total - idle_d
                info["cpu"] = int(max(0, min(100, busy * 100 / total))) if total else 0
            idle_prev, kern_prev, user_prev = idle, kern, user
        except Exception:
            info["cpu"] = _sys_cache.get("cpu", 0)

        try:
            info.update(_read_memory())
        except Exception:
            info["ram_pct"] = _sys_cache.get("ram_pct", 0)
            info["ram_gb"] = _sys_cache.get("ram_gb", 0)
            info["ram_total_gb"] = _sys_cache.get("ram_total_gb", 0)

        try:
            bat, charging = _read_battery()
            info["battery"] = bat
            info["charging"] = charging
        except Exception:
            info["battery"] = None
            info["charging"] = False

        with _sys_cache_lock:
            _sys_cache.update(info)

        time.sleep(5)


def get_running_apps():
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object -Property ProcessName,MainWindowTitle | ConvertTo-Json"],
            capture_output=True, text=True, timeout=5, creationflags=0x08000000
        )
        apps = json.loads(r.stdout) if r.stdout.strip() else []
        if isinstance(apps, dict):
            apps = [apps]
        return [{"name": a.get("ProcessName", ""), "title": a.get("MainWindowTitle", "")} for a in apps]
    except Exception:
        return []


# ── Volume Control ───────────────────────────────────────────────

def set_volume(level):
    """Set volume 0-100"""
    try:
        level = max(0, min(100, int(level)))
        ps = f"""
$vol = [math]::Round({level} / 100 * 65535)
$obj = New-Object -ComObject WScript.Shell
"""
        # Use nircmd approach or SendKeys
        # Simpler: use PowerShell with audio
        subprocess.run(
            ["powershell", "-Command",
             f"$wshell = New-Object -ComObject wscript.shell; " +
             "$wshell.SendKeys([char]173);" * 1 +  # mute first
             f"1..50 | ForEach-Object {{ $wshell.SendKeys([char]175) }};" +  # vol up 50 times (max)
             f"1..{50 - level // 2} | ForEach-Object {{ $wshell.SendKeys([char]174) }}"  # vol down to target
             ],
            capture_output=True, timeout=10, creationflags=0x08000000
        )
        return True
    except Exception:
        return False


def volume_up(steps=5):
    try:
        keys = "$wshell = New-Object -ComObject wscript.shell; " + \
               f"1..{steps} | ForEach-Object {{ $wshell.SendKeys([char]175) }}"
        subprocess.run(["powershell", "-Command", keys],
                       capture_output=True, timeout=5, creationflags=0x08000000)
        return True
    except Exception:
        return False


def volume_down(steps=5):
    try:
        keys = "$wshell = New-Object -ComObject wscript.shell; " + \
               f"1..{steps} | ForEach-Object {{ $wshell.SendKeys([char]174) }}"
        subprocess.run(["powershell", "-Command", keys],
                       capture_output=True, timeout=5, creationflags=0x08000000)
        return True
    except Exception:
        return False


def toggle_mute():
    try:
        subprocess.run(
            ["powershell", "-Command",
             "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys([char]173)"],
            capture_output=True, timeout=5, creationflags=0x08000000
        )
        return True
    except Exception:
        return False


# ── Clipboard History ────────────────────────────────────────────
_clipboard_history = []
_clipboard_lock = threading.Lock()
_clipboard_thread = None
_last_clip = ""


def get_clipboard_history():
    with _clipboard_lock:
        return list(_clipboard_history)


def read_clipboard_for_tts(limit=200):
    """Current clipboard text, truncated. Empty string if none. Never logs contents."""
    text = ""
    try:
        import pyperclip
        text = pyperclip.paste() or ""
    except Exception:
        text = ""
    if not str(text).strip():
        hist = get_clipboard_history()
        if hist:
            text = hist[0].get("text") or ""
    text = re.sub(r"\s+", " ", str(text)).strip()
    if not text:
        return ""
    limit = max(1, int(limit))
    if len(text) > limit:
        return text[:limit].rstrip()
    return text


def start_clipboard_monitor():
    global _clipboard_thread
    if _clipboard_thread and _clipboard_thread.is_alive():
        return
    _clipboard_thread = threading.Thread(target=_clipboard_loop, daemon=True)
    _clipboard_thread.start()


def _clipboard_loop():
    global _last_clip
    import pyperclip
    while True:
        try:
            current = pyperclip.paste()
            if current and current != _last_clip and len(current.strip()) > 0:
                _last_clip = current
                with _clipboard_lock:
                    _clipboard_history.insert(0, {
                        "text": current[:500],
                        "time": datetime.now().strftime("%H:%M"),
                        "full_len": len(current)
                    })
                    if len(_clipboard_history) > 20:
                        _clipboard_history.pop()
        except Exception:
            pass
        time.sleep(2)


# ── Parse reminder time from text ────────────────────────────────

def _fold_voice(text):
    table = str.maketrans({
        "ı": "i", "İ": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u",
        "ş": "s", "Ş": "s", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
        "â": "a", "î": "i", "û": "u",
    })
    s = (text or "").strip().lower().translate(table)
    s = re.sub(r"[^\w\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_voice_polite(n):
    n = re.sub(r"^(please|lutfen)\s+", "", n or "").strip()
    return re.sub(r"\s+(please|lutfen)$", "", n).strip()


def _fold_request(n):
    n = _strip_voice_polite(n)
    n = re.sub(r"^(can you|could you|would you|will you|abi|davi)\s+", "", n)
    n = re.sub(r"\s+(right now|for me|now)$", "", n)
    return n.strip()


def _unit_seconds(amount, unit):
    unit = (unit or "").lower()
    if unit in ("hour", "hours", "hr", "hrs", "saat"):
        return amount * 3600
    if unit in ("sec", "secs", "second", "seconds", "saniye", "sn"):
        return amount
    return amount * 60


def parse_reminder(text):
    """Parse 'remind me in 30 minutes to check email' style commands.
    Returns (reminder_text, seconds) or None."""
    folded = _fold_voice(text)
    if not folded:
        return None
    unit = r"(min(?:ute)?s?|mins?|dk|dakika|sec(?:ond)?s?|secs?|sn|saniye|hours?|hrs?|saat)"
    patterns = [
        rf"(?:remind|hatirlat|timer|alarm)\s+(?:me\s+)?(?:bana\s+)?(?:in\s+)?(\d+)\s*{unit}\s+(?:sonra\s+)?(?:to\s+)?(.+)",
        rf"(?:in\s+)?(\d+)\s*{unit}\s+(?:sonra\s+)?(?:remind|hatirlat|timer)\s+(?:me\s+)?(?:bana\s+)?(?:to\s+)?(.+)",
        rf"(?:set\s+)?(?:a\s+)?(?:timer|alarm|reminder)\s+(?:for\s+|in\s+)?(\d+)\s*{unit}\s*(?:sonra\s+)?(?:for\s+|to\s+)?(.+)",
        rf"(\d+)\s*{unit}\s+(?:sonra|later)\s+(?:bana\s+)?(?:hatirlat\s+)?(?:to\s+)?(.+)",
        rf"(?:bana\s+)?(\d+)\s*{unit}\s+(?:sonra\s+)?hatirlat\s+(?:to\s+)?(.+)",
        rf"(?:remind|hatirlat)\s+(?:me\s+)?(?:to\s+)?(.+?)\s+(?:in|in\s+)\s*(\d+)\s*{unit}",
        rf"(.+?)\s+(?:in|icin)?\s*(\d+)\s*{unit}\s+(?:sonra\s+)?(?:hatirlat|remind)",
    ]
    # Groups: most patterns are (amount, unit, text). Last two are (text, amount, unit).
    flipped = {5, 6}

    for i, pattern in enumerate(patterns):
        m = re.search(pattern, folded)
        if not m:
            continue
        if i in flipped:
            reminder_text = m.group(1).strip().rstrip(".")
            amount = int(m.group(2))
            unit_s = m.group(3)
        else:
            amount = int(m.group(1))
            unit_s = m.group(2)
            reminder_text = m.group(3).strip().rstrip(".")
        reminder_text = re.sub(r"^(to|bana|beni)\s+", "", reminder_text).strip()
        reminder_text = re.sub(r"\s+(hatirlat|remind|timer|alarm)$", "", reminder_text).strip()
        if not reminder_text or reminder_text in ("hatirlat", "remind", "me"):
            continue
        return (reminder_text, _unit_seconds(amount, unit_s))
    return None


# Folding strips punctuation, so "21:30" arrives as "21 30" and the separator
# has to allow whitespace as well as a literal colon.
_CLOCK = r"(\d{1,2})(?:\s*[:\.]\s*|\s+)?(\d{2})?"
_MERIDIEM = r"(am|pm|a m|p m)?"
_REPEAT_WORDS = {
    "every day": "daily", "everyday": "daily", "each day": "daily",
    "daily": "daily", "her gun": "daily", "hergun": "daily",
    "every weekday": "weekdays", "weekdays": "weekdays",
    "hafta ici": "weekdays", "her hafta ici": "weekdays",
    "every week": "weekly", "weekly": "weekly", "her hafta": "weekly",
}


def _detect_repeat(folded):
    for phrase, kind in sorted(_REPEAT_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", folded):
            return kind, re.sub(rf"\b{re.escape(phrase)}\b", " ", folded)
    return None, folded


def _resolve_clock(hour, minute, meridiem, day_shift, folded):
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    mer = (meridiem or "").replace(" ", "")
    if mer == "pm" and hour < 12:
        hour += 12
    elif mer == "am" and hour == 12:
        hour = 0
    elif not mer and hour <= 12:
        # "at 9" with no am/pm: use the Turkish word if present, else assume
        # the next time that clock reading actually occurs.
        if re.search(r"\b(aksam|gece|ogleden sonra)\b", folded) and hour < 12:
            hour += 12
        elif re.search(r"\b(sabah|morning)\b", folded) and hour == 12:
            hour = 0

    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target += timedelta(days=day_shift)
    if target <= now:
        if day_shift == 0 and not mer and hour < 12:
            evening = target + timedelta(hours=12)
            if evening > now:
                return evening
        target += timedelta(days=1)
    return target


def parse_scheduled_reminder(text):
    """Parse clock-time reminders: 'remind me at 9am to call mum',
    'her gun 9 da beni uyandir', 'tomorrow at 7 wake me up'.
    Returns (text, seconds, repeat) or None."""
    folded = _fold_voice(text)
    if not folded:
        return None
    if not re.search(r"\b(remind|hatirlat|alarm|wake me|uyandir|timer)\b", folded):
        return None
    # 'in 10 minutes' style belongs to parse_reminder, not here.
    if re.search(r"\b(in|icinde)?\s*\d+\s*(min(ute)?s?|dk|dakika|sec|saniye|sn|hours?|saat)\b", folded):
        return None

    repeat, folded = _detect_repeat(folded)

    day_shift = 0
    if re.search(r"\b(tomorrow|yarin)\b", folded):
        day_shift = 1
        folded = re.sub(r"\b(tomorrow|yarin)\b", " ", folded)

    m = re.search(rf"\b(?:at|saat)\s+{_CLOCK}\s*{_MERIDIEM}", folded)
    if not m:
        m = re.search(rf"\b{_CLOCK}\s*(?:da|de|te|ta)?\s*{_MERIDIEM}\b", folded)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    target = _resolve_clock(hour, minute, m.group(3), day_shift, folded)
    if target is None:
        return None

    body = (folded[:m.start()] + " " + folded[m.end():]).strip()
    body = re.sub(r"\b(remind|hatirlat|bana|beni|me|to|alarm|timer|set|a|an|the|please|lutfen"
                  r"|on|at|saat|kur|da|de|te|ta|icin|for)\b", " ", body)
    body = re.sub(r"\s+", " ", body).strip(" .,")
    if not body:
        body = "Wake up" if re.search(r"\b(uyandir|wake)\b", _fold_voice(text)) else "Reminder"

    # Round up so a 09:00 alarm reports 09:00 rather than 08:59.
    seconds = max(1, int(math.ceil((target - datetime.now()).total_seconds())))
    return (body, seconds, repeat)


_DICTATION_START = {
    "start dictation", "dictation mode", "dictate", "start dictating",
    "take dictation", "type what i say", "type for me", "start typing",
    "dikte", "dikte modu", "dikte moduna gec", "dikte baslat", "dikteye basla",
    "yazmaya basla", "soyledigimi yaz", "dediklerimi yaz", "benim icin yaz",
}

_DICTATION_STOP = {
    "stop dictation", "end dictation", "stop dictating", "stop typing",
    "exit dictation", "dictation off", "done dictating",
    "dikte kapat", "dikteyi kapat", "dikte modunu kapat", "dikte bitir",
    "dikteyi bitir", "yazmayi birak", "yazmayi kes", "yeter",
}

_WATCH_TEXT_PATTERNS = [
    r"(?:tell|let)\s+me\s+(?:know\s+)?when\s+(?:the\s+)?(?:screen\s+)?(?:says|shows)\s+(.+)",
    r"(?:notify|alert|warn)\s+me\s+when\s+(?:you\s+see\s+)?(.+)",
    r"watch\s+(?:the\s+)?screen\s+for\s+(.+)",
    r"(?:ekranda\s+)?(.+?)\s+(?:yazisi\s+)?(?:cikinca|gorununce|belirince)\s+(?:bana\s+)?(?:haber\s+ver|soyle)",
    r"(?:haber\s+ver|soyle)\s+(?:ekranda\s+)?(.+?)\s+(?:cikinca|gorununce)",
]

_WATCH_DOWNLOAD = {
    "tell me when the download is done", "tell me when the download finishes",
    "notify me when the download is done", "let me know when the download finishes",
    "watch my downloads", "watch the download",
    "indirme bitince soyle", "indirme bitince haber ver",
    "indirme tamamlaninca haber ver", "indirmeyi izle",
}


def match_dictation_start(text):
    return _fold_voice(text) in _DICTATION_START


def match_dictation_stop(text):
    return _fold_voice(text) in _DICTATION_STOP


def match_watch_download(text):
    return _fold_voice(text) in _WATCH_DOWNLOAD


def match_watch_text(text):
    folded = _fold_voice(text)
    for pattern in _WATCH_TEXT_PATTERNS:
        m = re.search(pattern, folded)
        if m:
            target = m.group(1).strip(" .,")
            target = re.sub(r"^(the|a|an|bir)\s+", "", target).strip()
            if target and len(target) >= 2:
                return target
    return None


_CONTINUE_PHRASES = {
    "continue", "continue that", "continue please", "keep going",
    "resume", "resume that", "resume task", "continue the task",
    "devam", "devam et", "devam et lutfen", "devam eder misin",
    "kaldigin yerden devam", "kaldigin yerden devam et",
    "surdur", "devam et oradan",
}

_FAV_MAX = 12


def match_continue(text):
    return _fold_voice(text) in _CONTINUE_PHRASES


_SCREEN_QUESTION_EXACT = {
    "whats on my screen", "what is on my screen", "what s on my screen",
    "whats on the screen", "what is on the screen", "what s on the screen",
    "what do you see", "what can you see", "what do you see on my screen",
    "what do you see on the screen", "describe my screen", "describe the screen",
    "describe this screen", "describe the desktop", "look at my screen",
    "read my screen", "read the screen", "whats on my desktop",
    "whats on screen", "what is on screen", "what s on screen",
    "ekranda ne var", "ekranda ne gorunuyor", "ekranda ne goruyorsun",
    "ekrani anlat", "ekrani tarif et", "ekrani oku", "ne goruyorsun",
    "ekrana bak", "ekrana bakar misin", "ekranimda ne var", "ekrimde ne var",
}

_SCREEN_QUESTION_SUB = (
    "on my screen", "on the screen", "on my desktop",
    "ekranda ne var", "ekranda ne gor", "ekrani anlat", "ekrani tarif",
    "describe my screen", "describe the screen", "what do you see",
    "ekranimda ne",
)

_DESKTOP_TASK_HINTS = (
    "open", "click", "tikla", "type", "yaz", "search", "google", "ara",
    "scroll", "kaydir", "tab", "sekme", "download", "indir", "chrome",
    "youtube", "press", "enter", "copy", "paste", "save", "kaydet",
    "switch", "focus", "ac", "baslat", "launch", "kapat", "close",
    "git", "go to", "navigate", "find", "bul", "click",
)


def match_screen_question(text):
    """True for 'what's on my screen' / 'ekranda ne var' — describe, don't click."""
    n = _fold_voice(text)
    if not n:
        return False
    if "kilitle" in n or n.startswith("lock"):
        return False
    if n in _SCREEN_QUESTION_EXACT:
        return True
    if any(s in n for s in _SCREEN_QUESTION_SUB):
        return True
    return match_camera_look(text)


def looks_like_desktop_task(text):
    """True when listen-only on the first turn is probably premature."""
    if match_screen_question(text) or match_continue(text):
        return False
    n = _fold_voice(text)
    if not n or len(n.split()) < 2:
        return False
    if n in ("hello there", "hey davi", "selam davi", "merhaba davi", "hi davi"):
        return False
    return any(re.search(rf"\b{re.escape(h)}\b", n) for h in _DESKTOP_TASK_HINTS)


def save_last_task(text, status="unfinished"):
    text = (text or "").strip()
    if not text or match_continue(text):
        return
    try:
        load_memory, save_memory = _memory_io()
        mem = load_memory()
        mem["last_task"] = {
            "text": text[:400],
            "status": status,
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        save_memory(mem)
    except Exception as e:
        print(f"[TASK] last_task save: {e}")


def get_unfinished_task():
    try:
        load_memory, _save = _memory_io()
        mem = load_memory()
        lt = mem.get("last_task") or {}
        if lt.get("status") != "unfinished":
            return None
        text = (lt.get("text") or "").strip()
        if text and not match_continue(text):
            return text
    except Exception:
        pass
    return None


def remember_favorite_app(name):
    name = (name or "").strip()
    if not name:
        return
    try:
        load_memory, save_memory = _memory_io()
        mem = load_memory()
        prefs = mem.setdefault("preferences", {})
        apps = [str(a).strip() for a in (prefs.get("favorite_apps") or []) if str(a).strip()]
        lower = name.lower()
        apps = [a for a in apps if a.lower() != lower]
        apps.insert(0, name)
        prefs["favorite_apps"] = apps[:_FAV_MAX]
        save_memory(mem)
    except Exception as e:
        print(f"[APP] favorite save: {e}")


def resolve_favorite_app(name):
    name = (name or "").strip()
    if not name:
        return name
    try:
        load_memory, _save = _memory_io()
        mem = load_memory()
        apps = (mem.get("preferences") or {}).get("favorite_apps") or []
        n = name.lower()
        for a in apps:
            if str(a).lower() == n:
                return str(a)
        for a in apps:
            al = str(a).lower()
            if n in al or al in n:
                return str(a)
    except Exception:
        pass
    return name


def open_app_via_start(name):
    """Open an app through Start search (Win+S) and remember it in favorite_apps."""
    name = (name or "").strip()
    if not name:
        return {"success": False, "message": "open_app requires params.name"}
    resolved = resolve_favorite_app(name)
    # A Start Menu shortcut launches instantly and can't mistype into the search box.
    try:
        from services.pc_context import launch_app
        launched = launch_app(resolved) or launch_app(name)
        if launched:
            remember_favorite_app(launched)
            return {"success": True, "message": f"Opened '{launched}' from the Start Menu"}
    except Exception as e:
        print(f"[APP] shortcut launch failed, falling back to Start search: {e}")

    try:
        _hotkey_vks([VK_LWIN, VK_S])
        time.sleep(0.5)
        import pyautogui
        pyautogui.write(resolved, interval=0.02)
        time.sleep(0.25)
        pyautogui.press("enter")
        remember_favorite_app(resolved)
        return {"success": True, "message": f"Opened '{resolved}' via Start search"}
    except Exception as e:
        return {"success": False, "message": f"open_app failed: {e}"}


# ── Shell Command Execution ─────────────────────────────────────

def run_shell_command(command, timeout=15, cwd=None):
    BLOCKED = ['format ', 'del /s', 'del /f', 'rm -rf', 'rmdir /s',
               'shutdown', 'restart', '::{', 'reg delete',
               'Remove-Item -Recurse -Force C:', 'Remove-Item -Recurse -Force /']
    cmd_lower = command.lower().strip()
    for b in BLOCKED:
        if b.lower() in cmd_lower:
            return {"success": False, "output": f"BLOCKED: dangerous command pattern '{b}'"}
    try:
        timeout = max(1, min(int(timeout or 15), 300))
    except (TypeError, ValueError):
        timeout = 15
    workdir = None
    if cwd:
        workdir = os.path.expanduser(str(cwd))
        if not os.path.isdir(workdir):
            return {"success": False, "output": f"cwd not found: {workdir}"}
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000, cwd=workdir,
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        # Build/test tools print progress to stdout and the error to stderr; the model needs both.
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append("[stderr]\n" + err)
        parts.append(f"[exit code {r.returncode}]")
        return {"success": r.returncode == 0, "output": "\n".join(parts)[:6000]}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "output": str(e)}


# ── File Operations ─────────────────────────────────────────────

def read_file(path, max_chars=5000):
    try:
        path = os.path.expanduser(path)
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read(max_chars)
        truncated = os.path.getsize(path) > max_chars
        return {"success": True, "content": content, "truncated": truncated,
                "size": os.path.getsize(path)}
    except Exception as e:
        return {"success": False, "content": "", "error": str(e)}


def write_file(path, content, append=False):
    BLOCKED_PATHS = ['C:\\Windows', 'C:\\Program Files', 'C:\\Program Files (x86)']
    path = os.path.expanduser(path)
    for bp in BLOCKED_PATHS:
        if os.path.abspath(path).lower().startswith(bp.lower()):
            return {"success": False, "error": f"BLOCKED: cannot write to {bp}"}
    try:
        mode = 'a' if append else 'w'
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, mode, encoding='utf-8') as f:
            f.write(content)
        return {"success": True, "path": os.path.abspath(path), "bytes": len(content.encode('utf-8'))}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_files(path=".", show_hidden=False):
    try:
        path = os.path.expanduser(path)
        entries = []
        for name in os.listdir(path):
            if not show_hidden and name.startswith('.'):
                continue
            full = os.path.join(path, name)
            is_dir = os.path.isdir(full)
            try:
                size = os.path.getsize(full) if not is_dir else 0
            except OSError:
                size = 0
            entries.append({"name": name, "type": "dir" if is_dir else "file", "size": size})
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        return {"success": True, "path": os.path.abspath(path), "entries": entries[:50],
                "total": len(entries)}
    except Exception as e:
        return {"success": False, "entries": [], "error": str(e)}


# ── Window Management ───────────────────────────────────────────

def manage_window(action, title=None):
    import ctypes
    user32 = ctypes.windll.user32

    SW_MINIMIZE = 6
    SW_MAXIMIZE = 3
    SW_RESTORE = 9

    def find_window(title_query):
        import ctypes
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        results = []
        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                if buf.value and title_query.lower() in buf.value.lower():
                    results.append((hwnd, buf.value))
            return True
        user32.EnumWindows(EnumWindowsProc(cb), 0)
        return results

    try:
        if title:
            matches = find_window(title)
            if not matches:
                return {"success": False, "error": f"No window matching '{title}'"}
            hwnd = matches[0][0]
            win_title = matches[0][1]
        else:
            hwnd = user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            win_title = buf.value

        if action == "minimize":
            user32.ShowWindow(hwnd, SW_MINIMIZE)
        elif action == "maximize":
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
        elif action == "restore":
            user32.ShowWindow(hwnd, SW_RESTORE)
        elif action == "close":
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        elif action == "focus":
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

        return {"success": True, "window": win_title, "action": action}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Process Management ──────────────────────────────────────────

def kill_process(name):
    PROTECTED = ['csrss', 'wininit', 'services', 'lsass', 'smss', 'system', 'dwm',
                 'svchost', 'explorer', 'winlogon']
    if name.lower().replace('.exe', '') in PROTECTED:
        return {"success": False, "error": f"BLOCKED: cannot kill system process '{name}'"}
    try:
        r = subprocess.run(
            ["taskkill", "/IM", name if '.exe' in name else name + '.exe', "/F"],
            capture_output=True, text=True, timeout=5, creationflags=0x08000000
        )
        return {"success": r.returncode == 0, "output": (r.stdout or r.stderr or "").strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Open URL ────────────────────────────────────────────────────

def open_url(url):
    """Open a site in the already-running Chrome. Never spawn a second Chrome
    (that hits the Windows profile picker)."""
    url = (url or "").strip()
    if not url:
        return {"success": False, "error": "no url"}
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    try:
        from services.browser_bridge import is_bridge_connected
        if is_bridge_connected():
            from services.chrome_router import reuse_or_open_url
            r = reuse_or_open_url(url) or {}
            if r.get("success"):
                return {"success": True, "url": url, "message": r.get("message")}
    except Exception:
        pass
    chrome = _chrome_exe()
    if chrome:
        try:
            subprocess.Popen(
                [chrome, "--new-tab", url],
                creationflags=0x08000000,
            )
            return {"success": True, "url": url}
        except Exception as e:
            return {"success": False, "error": str(e)}
    try:
        os.startfile(url)
        return {"success": True, "url": url}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _chrome_exe():
    """First installed Chromium browser: Chrome, then Edge, then Brave (same flags, same extension)."""
    for path in (
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ):
        if path and os.path.isfile(path):
            return path
    return None


# ── WiFi / Network Info ────────────────────────────────────────

def get_network_info():
    try:
        r = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=5, creationflags=0x08000000
        )
        info = {"connected": False, "ssid": "", "signal": "", "speed": ""}
        for line in r.stdout.split('\n'):
            line = line.strip()
            if 'SSID' in line and 'BSSID' not in line:
                info["ssid"] = line.split(':', 1)[1].strip()
                info["connected"] = True
            elif 'Signal' in line:
                info["signal"] = line.split(':', 1)[1].strip()
            elif 'Receive rate' in line:
                info["speed"] = line.split(':', 1)[1].strip()
        # Get public IP
        try:
            ip_r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Invoke-WebRequest -Uri 'https://api.ipify.org' -TimeoutSec 3).Content"],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000
            )
            info["public_ip"] = ip_r.stdout.strip() if ip_r.returncode == 0 else "N/A"
        except Exception:
            info["public_ip"] = "N/A"
        return info
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ── Brightness Control ──────────────────────────────────────────

def set_brightness(level):
    try:
        level = max(0, min(100, int(level)))
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {level})"],
            capture_output=True, timeout=5, creationflags=0x08000000
        )
        return {"success": True, "level": level}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Virtual Desktop ─────────────────────────────────────────────

def virtual_desktop(action):
    try:
        if action == "create":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys('^#{RIGHT}')"],
                capture_output=True, timeout=5, creationflags=0x08000000
            )
            # Win+Ctrl+D creates new desktop
            import ctypes
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win down
            ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
            ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)  # D down
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)  # D up
            ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)  # Ctrl up
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)  # Win up
            return {"success": True, "action": "created new virtual desktop"}
        elif action == "next":
            import ctypes
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x27, 0, 0, 0)  # Right
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(0x27, 0, 2, 0)
            ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)
            return {"success": True, "action": "switched to next desktop"}
        elif action == "prev":
            import ctypes
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x25, 0, 0, 0)  # Left
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(0x25, 0, 2, 0)
            ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)
            return {"success": True, "action": "switched to previous desktop"}
        elif action == "close":
            import ctypes
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x73, 0, 0, 0)  # F4
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(0x73, 0, 2, 0)
            ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)
            return {"success": True, "action": "closed current virtual desktop"}
        else:
            return {"success": False, "error": f"Unknown action: {action}. Use: create, next, prev, close"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Keyboard helpers ─────────────────────────────────────────────

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
VK_LWIN = 0x5B
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_ESCAPE = 0x1B
VK_D = 0x44
VK_E = 0x45
VK_L = 0x4C
VK_S = 0x53
VK_V = 0x56
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3


def _keybd(vk, flags=0):
    ctypes.windll.user32.keybd_event(vk, 0, flags, 0)


def _tap_vk(vk, extended=False):
    ext = KEYEVENTF_EXTENDEDKEY if extended else 0
    _keybd(vk, ext)
    time.sleep(0.04)
    _keybd(vk, ext | KEYEVENTF_KEYUP)


def _hotkey_vks(vks, extended_last=False):
    try:
        for vk in vks:
            _keybd(vk, 0)
            time.sleep(0.02)
        last = vks[-1]
        extra = KEYEVENTF_EXTENDEDKEY if extended_last else 0
        time.sleep(0.04)
        _keybd(last, extra | KEYEVENTF_KEYUP)
        for vk in reversed(vks[:-1]):
            _keybd(vk, KEYEVENTF_KEYUP)
        return True
    except Exception:
        return False


# ── Lock Screen ─────────────────────────────────────────────────

def lock_screen():
    try:
        ctypes.windll.user32.LockWorkStation()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def sleep_pc():
    """Sleep (not shutdown). Fast voice is the explicit ask; still mocked in tests."""
    from services.windows_ops import shutdown_pc
    return shutdown_pc(mode="sleep", confirmed=True)


def media_play_pause():
    try:
        _tap_vk(VK_MEDIA_PLAY_PAUSE, extended=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def media_next():
    try:
        _tap_vk(VK_MEDIA_NEXT_TRACK, extended=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def media_prev():
    try:
        _tap_vk(VK_MEDIA_PREV_TRACK, extended=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def show_desktop():
    try:
        _hotkey_vks([VK_LWIN, VK_D])
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def open_explorer():
    try:
        subprocess.Popen(["explorer"], creationflags=0x08000000)
        return {"success": True}
    except Exception as e:
        try:
            _hotkey_vks([VK_LWIN, VK_E])
            return {"success": True}
        except Exception:
            return {"success": False, "error": str(e)}


def open_task_manager():
    try:
        subprocess.Popen(["taskmgr"], creationflags=0x08000000)
        return {"success": True}
    except Exception as e:
        try:
            _hotkey_vks([VK_CONTROL, VK_SHIFT, VK_ESCAPE])
            return {"success": True}
        except Exception:
            return {"success": False, "error": str(e)}


def open_calculator():
    try:
        subprocess.Popen(["calc.exe"], creationflags=0x08000000)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def open_notepad():
    try:
        subprocess.Popen(["notepad.exe"], creationflags=0x08000000)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def open_windows_settings():
    try:
        os.startfile("ms-settings:")
        return {"success": True}
    except Exception:
        try:
            subprocess.Popen(["explorer.exe", "ms-settings:"], creationflags=0x08000000)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}


def open_recycle_bin():
    """Open Recycle Bin. Never empties it."""
    try:
        subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"], creationflags=0x08000000)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _known_folder_path(data1, data2, data3, data4, fallbacks):
    """Resolve a Windows Known Folder GUID, then name fallbacks under the user profile."""
    try:
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]
        fid = GUID(data1, data2, data3, (ctypes.c_ubyte * 8)(*data4))
        ptr = ctypes.c_void_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(fid), 0, None, ctypes.byref(ptr)
        )
        if hr == 0 and ptr.value:
            try:
                path = ctypes.wstring_at(ptr.value)
            finally:
                ctypes.windll.ole32.CoTaskMemFree(ptr)
            if path and os.path.isdir(path):
                return path
    except Exception:
        pass
    home = os.path.expanduser("~")
    for name in fallbacks:
        candidate = os.path.join(home, name)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(home, fallbacks[0] if fallbacks else "")


def _open_user_folder(path):
    try:
        os.startfile(path)
        return {"success": True, "path": path}
    except Exception:
        try:
            subprocess.Popen(["explorer.exe", path], creationflags=0x08000000)
            return {"success": True, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}


def _downloads_path():
    """User Downloads folder (localized Windows name via Known Folder)."""
    return _known_folder_path(
        0x374DE290, 0x123F, 0x4565,
        (0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B),
        ("Downloads", "İndirilenler"),
    )


def _documents_path():
    """User Documents folder (EN Documents / TR Belgeler)."""
    return _known_folder_path(
        0xFDD39AD0, 0x238F, 0x46AF,
        (0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
        ("Documents", "Belgeler", "My Documents"),
    )


def _desktop_folder_path():
    """User Desktop folder (Explorer), not Win+D show-desktop."""
    return _known_folder_path(
        0xB4BFCC3B, 0x52DA, 0x11D0,
        (0xB8, 0xC6, 0x08, 0x00, 0x2B, 0x30, 0x30, 0x9D),
        ("Desktop", "Masaüstü", "Masaustu"),
    )


def open_downloads_folder():
    """Open the current user's Downloads folder. Never downloads a file."""
    return _open_user_folder(_downloads_path())


def open_documents_folder():
    """Open the current user's Documents / Belgeler folder."""
    return _open_user_folder(_documents_path())


def open_desktop_folder():
    """Open the current user's Desktop folder in Explorer."""
    return _open_user_folder(_desktop_folder_path())


def _pictures_path():
    """User Pictures folder (EN Pictures / TR Resimler)."""
    return _known_folder_path(
        0x33E28130, 0x4E1E, 0x4676,
        (0x83, 0x5A, 0x98, 0x39, 0x5C, 0x3B, 0xC3, 0xBB),
        ("Pictures", "Resimler", "My Pictures"),
    )


def _music_path():
    """User Music folder (EN Music / TR Müzik)."""
    return _known_folder_path(
        0x4BD8D571, 0x6D19, 0x48D3,
        (0xBE, 0x97, 0x42, 0x22, 0x20, 0x08, 0x0E, 0x43),
        ("Music", "Müzik", "Muzik", "My Music"),
    )


def open_pictures_folder():
    """Open the current user's Pictures / Resimler folder."""
    return _open_user_folder(_pictures_path())


def open_music_folder():
    """Open the current user's Music / Müzik folder. Does not play media."""
    return _open_user_folder(_music_path())


def open_clipboard_history():
    """Win+V clipboard history overlay (Windows 10+)."""
    try:
        _hotkey_vks([VK_LWIN, VK_V])
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def snip_screenshot():
    """Open Windows Snipping Tool overlay (Win+Shift+S)."""
    try:
        _hotkey_vks([VK_LWIN, VK_SHIFT, VK_S])
        return {"success": True, "mode": "snip"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def save_desktop_screenshot():
    """Save a fullscreen PNG under screenshots/ and return the path."""
    try:
        os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
        except Exception:
            import pyautogui
            img = pyautogui.screenshot()
        name = f"shot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(_SCREENSHOTS_DIR, name)
        img.save(path)
        return {"success": True, "path": path, "mode": "save"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def take_quick_screenshot():
    """Save fullscreen PNG, then open the snipping overlay."""
    saved = save_desktop_screenshot()
    snip_screenshot()
    return saved


# ── Fast voice matcher (no LLM) ─────────────────────────────────

_FAST_OPEN_PREFIX = re.compile(r"^(please |lutfen )*(open |start |launch |run |ac )+(the )?")
_OPEN_APP_SUFFIX = re.compile(
    r"^(?P<name>.+?)(?:\s+(?:yu|yi|ya|ye|u|i|a|e))?\s+"
    r"(?:ac|aci|acarmisin|acabilir misin|lutfen ac)$"
)
_SWITCH_PREFIX = re.compile(
    r"^(please |lutfen )*(switch to|switch|alt tab(?: to)?|alttab(?: to)?|"
    r"win tab(?: to)?|wintab|focus window|go to window)\s+"
)
_SWITCH_SUFFIX = re.compile(
    r"^(?P<name>.+?)(?:\s+(?:ya|ye|na|ne|a|e))?\s+(?:gec|gecis|odaklan)$"
)
_OPEN_VERB_BLOCK = re.compile(
    r"\b(click|tikla|scroll|kaydir|type|yaz|send|gonder|delete|sil|remind|hatirlat)\b"
)

_APP_ALIASES = {
    "chrome": "Chrome",
    "google chrome": "Chrome",
    "googlechrome": "Chrome",
    "krom": "Chrome",
    "edge": "Microsoft Edge",
    "microsoft edge": "Microsoft Edge",
    "brave": "Brave",
    "brave browser": "Brave",
    "firefox": "Firefox",
    "mozilla": "Firefox",
    "edge": "Microsoft Edge",
    "microsoft edge": "Microsoft Edge",
    "discord": "Discord",
    "spotify": "Spotify",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "slack": "Slack",
    "steam": "Steam",
    "zoom": "Zoom",
    "teams": "Microsoft Teams",
    "microsoft teams": "Microsoft Teams",
    "outlook": "Outlook",
    "word": "Word",
    "excel": "Excel",
    "paint": "Paint",
    "notepad plus": "Notepad++",
    "notepadplusplus": "Notepad++",
}

_APP_ALIASES_LONGEST = tuple(sorted(_APP_ALIASES, key=len, reverse=True))

_OPEN_APP_BLOCK = {
    "calculator", "calc", "hesap", "hesap makinesi", "hesap makinesini",
    "notepad", "note pad", "not defteri", "not defterini",
    "settings", "windows settings", "pc settings", "system settings",
    "ms settings", "ayarlar", "windows ayarlari", "sistem ayarlari",
    "explorer", "file explorer", "files", "gezgin", "dosya gezgini",
    "recycle", "recycle bin", "trash", "geri donusum", "geri donusum kutusu",
    "cop kutusu", "clipboard", "clipboard history", "pano", "pano gecmisi",
    "task manager", "taskmgr", "gorev yoneticisi",
    "screenshot", "snip", "snipping tool", "desktop", "masaustu",
    "lock", "new tab", "yeni sekme", "tab", "sekme",
    "downloads", "download folder", "downloads folder", "my downloads",
    "indirmeler", "indirmeleri", "indirilenler", "indirilenleri",
    "documents", "document", "documents folder", "my documents",
    "belgeler", "belgeleri", "belgeler klasoru", "dokumanlar", "dokumanlari",
    "desktop folder", "masaustu klasoru", "open desktop",
    "pictures", "picture", "pictures folder", "my pictures", "resimler",
    "resimleri", "resimler klasoru", "fotograflar", "fotograflari",
    "music", "music folder", "my music", "muzik", "muzik klasoru",
    "the", "it", "app", "this", "that", "window", "file", "menu",
    "mute", "play", "pause", "time", "saat", "next", "prev", "previous",
        "volume", "unmute",
        "undo", "copy", "paste", "cut", "weather", "battery", "wifi",
        "redo", "save",
        "camera", "kamera", "kamerayi", "kameram", "kamerami",
        "webcam", "webkam", "webkami",
    }

_OPEN_APP_TASK_WORDS = {
    "and", "then", "ve", "sonra", "ile", "youtube", "gmail", "search",
    "download", "downloads", "indir", "settings", "ayarlar", "http", "www",
    "click", "tikla", "navigate", "url", "website",
}


def _fast_app_candidate_ok(raw):
    """True for a simple app name. False for 'chrome youtube' / 'chrome and ...'."""
    raw = (raw or "").strip()
    if not raw:
        return False
    if raw in _OPEN_APP_BLOCK or raw in ("ac", "open", "start", "launch", "run"):
        return False
    if len(raw) < 2 or len(raw) > 40:
        return False
    padded = f" {raw} "
    if " tab" in padded or raw.endswith(" sekme") or "sekme" in raw:
        return False
    if raw in _APP_ALIASES:
        return True
    tokens = raw.split()
    for alias in _APP_ALIASES_LONGEST:
        if raw.startswith(alias + " ") or raw.endswith(" " + alias) or f" {alias} " in padded:
            return False
        if len(alias.split()) == 1 and alias in tokens:
            return False
    if len(tokens) > 3:
        return False
    if any(tok in _OPEN_APP_TASK_WORDS for tok in tokens):
        return False
    return True


_SITE_PHRASES = (
    (("youtube", "open youtube", "open youtube.com", "go to youtube", "youtube com",
      "youtube ac", "youtubu ac", "youtubeu ac", "youtube u ac"),
     "https://www.youtube.com"),
    (("gmail", "open gmail", "gmail ac", "go to gmail"),
     "https://mail.google.com"),
    (("google", "open google", "google ac", "go to google"),
     "https://www.google.com"),
)


_BROWSER_SUFFIX = re.compile(
    r"\s+(?:on|in|from|via|using|with)\s+(?:the\s+|a\s+|my\s+)?"
    r"(?:browser|web browser|chrome|google chrome|edge|web|internet|tarayici|krom)$"
    r"|\s+(?:tarayicida|tarayicidan|chrome da|chrome de|krom da|kromda)$"
)


def _strip_browser_suffix(n):
    """'open youtube on browser' → 'open youtube'. The browser is implied."""
    prev = None
    while n and n != prev:
        prev = n
        n = _BROWSER_SUFFIX.sub("", n).strip()
    return n


def match_fast_site(text):
    """Open a well-known site in the existing browser. Not an app launch."""
    n = _strip_browser_suffix(_fold_request(_fold_voice(text)))
    if not n:
        return None
    if match_fast_desktop(text):
        return None
    for phrases, url in _SITE_PHRASES:
        if n in phrases:
            return url
    return None


def match_fast_site_search(text):
    """YouTube/Google search phrases → results URL. Not a bare 'open youtube'."""
    n = _strip_browser_suffix(_fold_request(_fold_voice(text)))
    if not n:
        return None
    if match_fast_desktop(text) or match_fast_site(text):
        return None
    if re.search(r"\b(pause|close|durdur|kapat|stop)\b", n) and re.search(r"\byoutube\b", n):
        return None
    from services.chrome_router import google_search_url, youtube_results_url

    m = re.search(
        r"(?:play|search|find|izle|cal|dinle|open|ara)\s+(.+?)\s+(?:on\s+|from\s+)?youtube\b",
        n,
    )
    if m:
        q = m.group(1).strip()
        if q:
            return youtube_results_url(q)
    m = re.search(r"youtube(?: da| de)?\s+(.+)", n)
    if m:
        q = m.group(1).strip()
        q = re.sub(r"^(ac|open|play|search|ara|izle)\s+", "", q).strip()
        if q:
            return youtube_results_url(q)
    m = re.search(r"(?:google(?: da| de)?|search google|google ara)\s+(.+)", n)
    if m:
        q = m.group(1).strip()
        q = re.sub(r"^(ac|open|search|ara)\s+", "", q).strip()
        if q and q not in ("com",):
            return google_search_url(q)
    return None


_FAST_PHRASES = [
    ("calculator", (
        "calculator", "calc", "open calculator", "open calc",
        "hesap makinesi", "hesap makinesini ac", "hesap ac",
    )),
    ("notepad", (
        "notepad", "open notepad", "note pad",
        "not defteri", "not defterini ac", "not defteri ac",
    )),
    ("settings", (
        "windows settings", "open settings", "open windows settings",
        "pc settings", "system settings", "ms settings", "settings",
        "windows ayarlari", "ayarlar", "ayarlari ac", "sistem ayarlari",
    )),
    ("recycle", (
        "recycle bin", "open recycle bin", "open recycle", "recycle",
        "open trash", "trash", "recycling bin",
        "geri donusum kutusu", "geri donusum kutusunu ac", "geri donusum",
        "cop kutusu", "cop kutusunu ac",
    )),
    ("downloads", (
        "downloads", "open downloads", "open download folder", "download folder",
        "downloads folder", "my downloads", "open my downloads",
        "indirmeler", "indirmeleri ac", "indirmeler klasoru", "indirmeler klasorunu ac",
        "indirilenler", "indirilenleri ac", "indirilenler klasoru",
        "downloads klasoru", "downloads klasorunu ac",
    )),
    ("documents", (
        "documents", "open documents", "documents folder", "open documents folder",
        "my documents", "open my documents", "document folder",
        "belgeler", "belgeleri ac", "belgeler klasoru", "belgeler klasorunu ac",
        "belgelerimi ac", "dokumanlar", "dokumanlari ac", "dokumanlar klasoru",
    )),
    ("desktop_folder", (
        "open desktop folder", "desktop folder", "open my desktop folder",
        "my desktop folder", "open desktop",
        "masaustu klasoru", "masaustu klasorunu ac", "masaustu klasoru ac",
    )),
    ("pictures", (
        "pictures", "open pictures", "pictures folder", "open pictures folder",
        "my pictures", "open my pictures", "picture folder", "open picture folder",
        "resimler", "resimleri ac", "resimler klasoru", "resimler klasorunu ac",
        "resimler klasoru ac", "fotograflar", "fotograflari ac", "fotograf klasoru",
    )),
    ("music", (
        "music", "open music", "music folder", "open music folder",
        "my music", "open my music",
        "muzik", "muzik klasoru", "muzik klasorunu ac", "muzik klasoru ac",
    )),
    ("clipboard", (
        "clipboard history", "clipboard", "open clipboard", "win v",
        "windows clipboard", "clip history",
        "pano gecmisi", "pano gecmisini ac", "pano", "panoyu ac",
    )),
    ("taskmgr", (
        "task manager", "open task manager", "gorev yoneticisi",
        "gorev yoneticisini ac", "taskmgr",
    )),
    ("snip", (
        "snip", "snipping tool", "kesit al", "ekran kesiti", "win shift s",
    )),
    ("screenshot", (
        "screenshot", "take screenshot", "take a screenshot", "screen shot",
        "ekran goruntusu", "ekran goruntusu al", "ss al", "screenshot al",
    )),
    ("camera_on", (
        "open camera", "open the camera", "start camera", "turn on the camera",
        "turn on camera", "camera on", "open webcam", "start webcam",
        "camera", "webcam",
        "kamera", "kamera ac", "kamerayi ac", "kamerayi acar misin", "kamerayi acsana",
        "kamerami ac", "webkami ac", "webkami acar misin",
    )),
    ("camera_off", (
        "close camera", "close the camera", "stop camera", "turn off the camera",
        "turn off camera", "camera off", "close webcam",
        "kamerayi kapat", "kamerayi kapa", "kamerayi durdur", "webkami kapat",
        "kamerayi kapat", "kamerayi kapatir misin",
    )),
    ("desktop", (
        "show desktop", "go to desktop", "minimize all",
        "masaustunu goster", "masaustu goster", "masaustune git",
    )),
    ("explorer", (
        "file explorer", "open explorer", "open file explorer", "open files",
        "explorer", "gezgin", "dosya gezgini", "gezgini ac", "explorer ac",
    )),
    ("lock", (
        "lock", "lock pc", "lock computer", "lock the computer", "lock screen",
        "kilitle", "bilgisayari kilitle", "pc kilitle", "ekrani kilitle",
    )),
    ("sleep", (
        "sleep pc", "sleep the pc", "sleep computer", "sleep the computer",
        "put pc to sleep", "put the pc to sleep", "put computer to sleep",
        "put the computer to sleep", "pc to sleep", "computer to sleep",
        "bilgisayari uyut", "pc yi uyut", "pcyi uyut", "pc uyut",
        "bilgisayari uykuya al", "uykuya al", "uyut",
    )),
    ("play_pause", (
        "play", "pause", "play pause", "playpause", "toggle play",
        "play music", "pause music", "oynat", "duraklat",
        "muzigi duraklat", "muzigi oynat", "videoyu durdur", "filmi durdur",
        "pause the video", "pause youtube",
    )),
    ("next", (
        "next track", "next song", "skip song", "skip track",
        "sonraki sarki", "sonraki parca", "sarkiyi gec",
    )),
    ("prev", (
        "previous", "previous track", "previous song", "prev track", "last song",
        "onceki sarki", "onceki parca", "onceki",
    )),
    ("mute", (
        "mute", "unmute", "toggle mute", "sessiz", "sesi kapat", "sesi ac kapat",
    )),
    ("volume_up", (
        "volume up", "louder", "sesi ac", "sesi yukselt", "ses ac", "ses yukselt",
    )),
    ("volume_down", (
        "volume down", "quieter", "sesi kis", "sesi azalt", "ses kis", "ses azalt",
    )),
    ("time", (
        "what time is it", "whats the time", "what's the time", "time",
        "saat kac", "saat",
    )),
    ("undo", (
        "undo", "undo that", "undo this", "geri al", "geri al onu",
    )),
    ("redo", (
        "redo", "redo that", "yinele", "ileri al",
    )),
    ("copy", (
        "copy", "copy this", "kopyala", "bunu kopyala", "kopyala bunu",
    )),
    ("paste", (
        "paste", "paste this", "yapistir", "bunu yapistir", "yapistir bunu",
    )),
    ("cut", (
        "cut", "cut this", "kes", "bunu kes", "kes bunu",
    )),
    ("select_all", (
        "select all", "select all text", "hepsini sec", "tumunu sec",
    )),
    ("save", (
        "save this", "save the file", "save file", "kaydet", "dosyayi kaydet",
    )),
    ("snap_left", (
        "snap left", "snap this left", "snap left side",
        "sola yasla", "sola hizala", "sola al",
    )),
    ("snap_right", (
        "snap right", "snap this right", "snap right side",
        "saga yasla", "saga hizala", "saga al",
    )),
    ("maximize", (
        "maximize", "maximize this", "maximize window", "maximise",
        "pencereyi buyut", "buyut bu pencereyi",
    )),
    ("minimize_win", (
        "minimize this", "minimize window", "minimize this window",
        "bu pencereyi kucult", "pencereyi kucult",
    )),
    ("close_window", (
        "close this window", "close the window", "close this", "close it",
        "close the video", "close video", "close the movie", "close youtube",
        "bu pencereyi kapat", "pencereyi kapat", "bunu kapat", "sunu kapat",
        "videoyu kapat", "filmi kapat", "youtube u kapat", "youtube kapat",
    )),
    ("insert_date", (
        "type the date", "insert date", "todays date", "today s date",
        "today's date", "tarihi yaz", "bugunun tarihi", "bugunun tarihini yaz",
    )),
    ("insert_time", (
        "type the time", "insert time", "saati yaz", "saati buraya yaz",
    )),
    ("wifi", (
        "wifi", "wi fi", "wifi status", "internet", "internet status",
        "wifi durumu", "internet durumu", "internete baglimiyim",
        "internete bagli miyim",
    )),
    ("battery", (
        "battery", "battery level", "how much battery", "battery percent",
        "sarj", "sarj durumu", "batarya", "batarya durumu", "sarjim ne",
    )),
    ("weather", (
        "weather", "whats the weather", "what is the weather",
        "what s the weather", "whats the weather like", "what is the weather like",
        "hows the weather", "how is the weather", "how s the weather",
        "hows the weather today", "whats the weather today", "what is the weather today",
        "weather today", "todays weather", "weather outside", "is it cold outside",
        "is it hot outside", "is it raining", "will it rain today", "whats the temperature",
        "what s the temperature", "what is the temperature", "temperature outside",
        "hava durumu", "hava nasil", "hava nasil disarda", "havalar nasil",
        "bugun hava nasil", "hava nasil bugun", "bugun hava", "bugun havalar nasil",
        "disarisi nasil", "disarda hava nasil", "hava durumu nasil", "hava kac derece",
        "kac derece", "disarisi kac derece", "yagmur yagacak mi", "yagmur var mi",
        "disarisi soguk mu", "hava soguk mu", "hava sicak mi",
    )),
    ("hide_davi", (
        "hide yourself", "hide davi", "go away", "disappear",
        "gizlen", "kaybol", "kendini gizle", "ortadan kaybol",
    )),
    ("show_davi", (
        "come back", "show yourself", "show davi", "unhide",
        "geri gel", "gorun", "cik ortaya",
    )),
    ("stop_talking", (
        "shut up", "stop talking", "be quiet", "stop speaking", "stop", "quiet",
        "sus", "konusma", "kes sesini", "sus artik", "dur", "sessiz ol",
    )),
    ("say_again", (
        "say that again", "what did you say", "repeat that", "repeat",
        "tekrar soyle", "ne dedin", "bir daha soyle", "tekrar et",
    )),
    ("copy_reply", (
        "copy that", "copy your answer", "copy last answer", "copy your last answer",
        "cevabi kopyala", "onu kopyala", "son cevabi kopyala",
    )),
    ("read_selection", (
        "read this", "read that", "read the selection", "read selection",
        "oku bunu", "bunu oku", "secimi oku", "sunu oku",
    )),
    ("copy_screen", (
        "copy the screen", "copy screen text", "copy whats on screen",
        "copy what's on screen", "copy the text on screen",
        "ekrandaki yaziyi kopyala", "ekrani kopyala", "ekrandaki yaziyi al",
    )),
    ("search_this", (
        "search this", "search for this", "google this", "google that",
        "bunu ara", "sunu google la", "google da ara", "bunu google la",
    )),
    ("speak_slower", (
        "speak slower", "slower", "talk slower",
        "yavas konus", "daha yavas", "daha yavas konus",
    )),
    ("speak_faster", (
        "speak faster", "faster", "talk faster",
        "hizli konus", "daha hizli", "daha hizli konus",
    )),
    ("mute_speech", (
        "dont speak", "don't speak", "no voice", "voice off",
        "konusma artik", "sesli yanit kapat",
    )),
    ("unmute_speech", (
        "speak again", "voice on", "you can talk",
        "konus", "sesli yanit ac",
    )),
    ("mute_mic", (
        "stop listening", "stop listening right now", "can you stop listening",
        "can you stop listening right now", "dont listen", "do not listen",
        "stop hearing me", "disable your mic", "disable the mic",
        "disable microphone", "turn off your mic", "turn off the mic",
        "turn off microphone", "mute your mic", "mute the mic",
        "mic off", "microphone off", "pause listening",
        "dinlemeyi durdur", "dinlemeyi kes", "dinleme", "beni dinleme",
        "mikrofonu kapat", "mikrofonunu kapat", "kendi mikini kapat",
        "kendi mikrofonunu kapat", "mikini kapat", "mic kapat",
    )),
    ("unmute_mic", (
        "start listening", "listen again", "resume listening",
        "enable your mic", "unmute your mic", "turn on your mic",
        "turn on the mic", "mic on", "microphone on",
        "dinlemeye basla", "tekrar dinle", "mikrofonu ac", "mikrofonunu ac",
        "mikini ac", "mic ac", "dinlemeye devam", "dinlemeye basla tekrar",
    )),
]

# "open lock" must not lock the PC — only these actions accept an open/ac prefix strip.
_FAST_STRIP_OK = {
    "calculator", "notepad", "settings", "recycle", "downloads", "documents",
    "desktop_folder", "pictures", "music", "clipboard", "taskmgr", "snip",
    "screenshot", "explorer", "camera_on",
}

_FAST_SKIP_NEXT = {
    "next tab", "sonraki sekme", "new tab", "yeni sekme", "next window",
}

_EMPTY_RECYCLE_EXACT = {
    "empty recycle", "empty recycle bin", "empty the recycle", "empty the recycle bin",
    "empty bin", "empty the bin", "clear recycle", "clear recycle bin",
    "empty trash", "clear trash", "empty recycling bin",
    "geri donusumu bosalt", "geri donusum kutusunu bosalt", "geri donusumu temizle",
    "cop kutusunu bosalt", "cop kutusunu temizle", "geri donusum bosalt",
}
_EMPTY_RECYCLE_EMPTY = ("empty", "bosalt", "temizle", "clear")
_EMPTY_RECYCLE_BIN = ("recycle", "geri donusum", "cop kutusu", "trash")
_CONFIRM_YES = {
    "yes", "yeah", "yep", "confirm", "confirmed", "do it", "ok confirm",
    "evet", "onayla", "onay", "eminim", "bosalt", "empty it",
    "si", "ja", "oui",
}
_empty_recycle_pending_until = 0.0


def match_empty_recycle(text):
    """True for empty/clear Recycle Bin — never auto-runs; needs confirm."""
    n = _fold_voice(text)
    if not n:
        return False
    if n in _EMPTY_RECYCLE_EXACT:
        return True
    has_empty = any(x in n for x in _EMPTY_RECYCLE_EMPTY)
    has_bin = any(x in n for x in _EMPTY_RECYCLE_BIN)
    return has_empty and has_bin


def handle_empty_recycle_voice(text):
    """First utterance asks confirm; second empty-recycle or yes actually empties.

    Returns ('ask', None), ('do', result_dict), or None.
    """
    global _empty_recycle_pending_until
    n = _fold_voice(text)
    if not n:
        return None
    now = time.time()
    pending = now < _empty_recycle_pending_until
    if match_empty_recycle(text):
        if pending:
            _empty_recycle_pending_until = 0.0
            from services.windows_ops import empty_recycle
            return ("do", empty_recycle(confirmed=True))
        _empty_recycle_pending_until = now + 45.0
        return ("ask", None)
    if pending and n in _CONFIRM_YES:
        _empty_recycle_pending_until = 0.0
        from services.windows_ops import empty_recycle
        return ("do", empty_recycle(confirmed=True))
    if pending:
        _empty_recycle_pending_until = 0.0
    return None


_restart_pc_pending_until = 0.0
_DAVI_NAME_RE = re.compile(r"\b(aemyos|davi|dayi|davey|davy|david|davie)")
_PC_RESTART_EXACT = {
    "restart the computer", "restart computer",
    "reboot the computer", "reboot computer",
    "restart the pc", "restart pc",
    "reboot the pc", "reboot pc",
    "bilgisayari yeniden baslat", "bilgisayari yeniden baslatin",
    "pc yi yeniden baslat", "pcyi yeniden baslat", "pc yeniden baslat",
    "bilgisayari restart et", "pc yi restart et",
}
_CONFIRM_YES_RESTART = {
    "yes", "yeah", "yep", "confirm", "confirmed", "do it", "ok confirm",
    "evet", "onayla", "onay", "eminim",
    "si", "ja", "oui",
}
_READ_CLIP_EXACT = {
    "read clipboard", "read the clipboard", "read clip board",
    "read my clipboard", "whats on the clipboard", "what s on the clipboard",
    "whats on clipboard", "read clip",
    "clipboard oku", "clip board oku",
    "panoyu oku", "pano oku", "panoyu okur musun",
    "panodaki yazi", "panodaki yaziyi oku", "panoyu sesli oku",
}


def _mentions_davi(n):
    return bool(_DAVI_NAME_RE.search(n or ""))


def match_restart_davi(text):
    """True for restart overlay (never Windows reboot)."""
    n = _strip_voice_polite(_fold_voice(text))
    if not n or not _mentions_davi(n):
        return False
    return bool(re.search(r"\b(restart|reboot)\b", n) or "yeniden baslat" in n)


def match_restart_pc(text):
    """True only for explicit PC restart. Never matches restart davi/davı."""
    n = _strip_voice_polite(_fold_voice(text))
    if not n or _mentions_davi(n):
        return False
    if n in _PC_RESTART_EXACT:
        return True
    has_restart = bool(re.search(r"\b(restart|reboot)\b", n) or "yeniden baslat" in n)
    has_machine = bool(re.search(r"\b(computer|pc)\b", n) or "bilgisayar" in n)
    return has_restart and has_machine


def handle_restart_pc_voice(text):
    """First utterance asks confirm; confirm/repeat then shutdown_pc restart.

    Returns ('ask', None), ('do', result_dict), or None.
    """
    global _restart_pc_pending_until
    n = _strip_voice_polite(_fold_voice(text))
    if not n:
        return None
    now = time.time()
    pending = now < _restart_pc_pending_until
    if match_restart_pc(text):
        if pending:
            _restart_pc_pending_until = 0.0
            from services.windows_ops import shutdown_pc
            return ("do", shutdown_pc(mode="restart", confirmed=True))
        _restart_pc_pending_until = now + 45.0
        return ("ask", None)
    if pending and n in _CONFIRM_YES_RESTART:
        _restart_pc_pending_until = 0.0
        from services.windows_ops import shutdown_pc
        return ("do", shutdown_pc(mode="restart", confirmed=True))
    if pending:
        _restart_pc_pending_until = 0.0
    return None


def match_read_clipboard(text):
    """True for 'read clipboard' / 'panoyu oku' — TTS, do not open Win+V."""
    n = _strip_voice_polite(_fold_voice(text))
    if not n:
        return False
    if n in _READ_CLIP_EXACT:
        return True
    has_clip = "clipboard" in n or "pano" in n
    has_read = bool(re.search(r"\b(read|oku)\b", n))
    return has_clip and has_read


# "stop" / "dur" silence her (stop_talking); only these close the overlay.
_QUIT_PHRASES = frozenset({"quit", "exit", "kapat"})
_CANCEL_PHRASES = frozenset({"cancel", "iptal", "vazgec"})


def match_voice_quit(text):
    """True for overlay quit. Punctuation/please ignored. Never matches cancel."""
    n = _strip_voice_polite(_fold_voice(text))
    return n in _QUIT_PHRASES


def match_voice_cancel(text):
    """True for cancel-task. Does not quit the overlay."""
    n = _strip_voice_polite(_fold_voice(text))
    return n in _CANCEL_PHRASES


def match_sleep_pc(text):
    """True for sleep-pc voice. Never matches shutdown / kapat / stop."""
    n = _fold_voice(text)
    if not n:
        return False
    n = re.sub(r"^(please|lutfen)\s+", "", n).strip()
    n = re.sub(r"\s+(please|lutfen)$", "", n).strip()
    if match_voice_quit(text) or match_voice_cancel(text):
        return False
    if any(b in n for b in ("shutdown", "shut down", "restart", "reboot")):
        return False
    if "kapat" in n:
        return False
    if n in (
        "sleep pc", "sleep the pc", "sleep computer", "sleep the computer",
        "put pc to sleep", "put the pc to sleep", "put computer to sleep",
        "put the computer to sleep", "pc to sleep", "computer to sleep",
        "go to sleep", "sleep now",
        "bilgisayari uyut", "pc yi uyut", "pcyi uyut", "pc uyut",
        "bilgisayari uykuya al", "pc yi uykuya al", "uykuya al",
        "bilgisayari uykuya gecir", "uykuya gec", "uyut",
    ):
        return True
    has_sleep = bool(re.search(r"\bsleep\b", n))
    has_uyut = bool(re.search(r"\buyut\b", n) or "uykuya" in n)
    has_machine = bool(re.search(r"\bpc\b", n) or "bilgisayar" in n or "computer" in n)
    return (has_sleep or has_uyut) and has_machine


_CAM_WORD = re.compile(
    r"\b(kamerayi|kamerami|kameram|kamerada|kameraya|kamera|webkami|webkam|webcam|camera)\b"
)
_CAM_OFF = re.compile(r"\b(kapat|kapa|durdur|close|stop|off)\b|turn off")
_CAM_OPEN = re.compile(r"\b(open|start|turn on|ac|acsana|acar)\b")
_CAM_LOOK = re.compile(
    r"\b(what|whats|see|seeing|seen|look|looking|check|describe|"
    r"ne var|ne gor|goruyor|anlat|tarif|bak)\b"
)
_CAM_SHORT = frozenset(("camera", "the camera", "kamera", "webcam", "webkam"))
_FACE_ENROLL = re.compile(
    r"(remember|save|learn|enroll)\s+(my\s+)?face|"
    r"yuzum[u]?\s+(kaydet|ogren|hatirla)"
)
_FACE_FORGET = re.compile(
    r"(forget|delete|remove)\s+(my\s+)?face|"
    r"yuzum[u]?\s+(unut|sil)"
)
_FACE_QUERY = re.compile(
    r"(do you )?(recognize|know)\s+(me|my face)|who do you see|"
    r"beni taniyor musun|yuzumu taniyor|beni tanidin"
)
_last_fast_action = ""
_last_fast_at = 0.0


def match_face_voice(text):
    """Save / forget / query the local owner face. Camera stays a separate action."""
    n = _fold_voice(text)
    if not n:
        return None
    if _FACE_FORGET.search(n):
        return "face_forget"
    if _FACE_ENROLL.search(n):
        return "face_enroll"
    if _FACE_QUERY.search(n):
        return "face_query"
    return None


def _enroll_owner_face():
    from services.face_id import enroll_from_camera
    return enroll_from_camera()


def _forget_owner_face():
    from services.face_id import forget_face
    return forget_face()


def _query_owner_face():
    from services.face_id import query_now
    return query_now()


def match_camera_look(text):
    """True when they want what's on the camera, not the Camera app opened."""
    n = _fold_voice(text)
    if not n or not _CAM_WORD.search(n):
        return False
    req = _fold_request(n)
    if _CAM_OPEN.search(req) or _CAM_OFF.search(req):
        return False
    return bool(_CAM_LOOK.search(n) or _CAM_LOOK.search(req))


def match_camera_voice(text):
    """Open/close Camera via URI — never Start search or clicks."""
    n = _fold_request(_fold_voice(text))
    if not n or not _CAM_WORD.search(n):
        return None
    if _CAM_OFF.search(n):
        return "camera_off"
    if n in _CAM_SHORT:
        return "camera_on"
    if _CAM_LOOK.search(n) and not _CAM_OPEN.search(n):
        return None
    if _CAM_OPEN.search(n):
        return "camera_on"
    return None


def same_fast_recently(action, sec=8.0):
    if not action or action != _last_fast_action:
        return False
    return (time.time() - float(_last_fast_at or 0.0)) < float(sec)


def mark_fast(action):
    global _last_fast_action, _last_fast_at
    _last_fast_action = action or ""
    _last_fast_at = time.time()


def match_fast_desktop(text):
    """Return an action name or None. Does not handle reminders."""
    n = _fold_voice(text)
    if not n:
        return None
    if match_empty_recycle(text):
        return None
    if match_restart_pc(text) or match_restart_davi(text) or match_read_clipboard(text):
        return None
    if n in _FAST_SKIP_NEXT or "sekme" in n or n.endswith(" tab"):
        if n in ("next", "next track", "next song"):
            return "next"
        return None
    if match_voice_quit(text) or match_voice_cancel(text):
        return None
    face = match_face_voice(text)
    if face:
        return face
    cam = match_camera_voice(text)
    if cam:
        return cam
    req = _fold_request(n)
    for action in ("mute_mic", "unmute_mic"):
        phrases = dict(_FAST_PHRASES).get(action) or ()
        if n in phrases or req in phrases:
            return action
    if match_sleep_pc(text):
        return "sleep"
    candidates = [n]
    stripped = _FAST_OPEN_PREFIX.sub("", n).strip()
    if stripped and stripped not in candidates:
        candidates.append(stripped)
    for cand in candidates:
        stripped_cand = cand != n
        for action, phrases in _FAST_PHRASES:
            if stripped_cand and action not in _FAST_STRIP_OK:
                continue
            if action == "recycle" and any(x in cand for x in ("empty", "bosalt", "clear")):
                continue
            if cand in phrases:
                return action
    # short standalone next/prev after phrase pass
    if n == "next":
        return "next"
    if n in ("prev", "previous"):
        return "prev"
    return None


def _canonicalize_app_name(name):
    name = (name or "").strip()
    if not name:
        return ""
    name = re.sub(r"\s+(please|lutfen)$", "", name).strip()
    key = name.lower()
    if key in _APP_ALIASES:
        return _APP_ALIASES[key]
    return name


def match_fast_open_app(text):
    """Return an app name for open_app, or None. Calculator/notepad/etc. stay on match_fast_desktop."""
    n = _fold_voice(text)
    if not n or _OPEN_VERB_BLOCK.search(n):
        return None
    if match_voice_quit(text) or match_voice_cancel(text):
        return None
    if match_restart_pc(text) or match_restart_davi(text) or match_read_clipboard(text):
        return None
    if n in _CONTINUE_PHRASES or match_continue(text):
        return None
    names = []
    stripped = _FAST_OPEN_PREFIX.sub("", n).strip()
    stripped = re.sub(r"\s+(please|lutfen)$", "", stripped).strip()
    if stripped and stripped != n:
        names.append(stripped)
    suf = _OPEN_APP_SUFFIX.match(n)
    if suf:
        names.append((suf.group("name") or "").strip())
    if n in _APP_ALIASES:
        names.append(n)
    seen = set()
    for raw in names:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        if not _fast_app_candidate_ok(raw):
            continue
        return _canonicalize_app_name(raw)
    return None


def match_fast_switch_app(text):
    """Return ('focus', title), ('alt_tab', None), ('win_tab', None), or None."""
    n = _fold_voice(text)
    if not n:
        return None
    if n in ("alt tab", "alttab", "pencere degistir", "sonraki pencere"):
        return ("alt_tab", None)
    if n in ("win tab", "wintab", "gorev gorunumu", "task view"):
        return ("win_tab", None)
    if "sekme" in n or n.endswith(" tab") or "new tab" in n:
        return None
    stripped = _SWITCH_PREFIX.sub("", n).strip()
    if stripped and stripped != n:
        title = re.sub(r"\s+(please|lutfen)$", "", stripped).strip()
        if title and title not in ("it", "this", "that", "app", "window"):
            if not _fast_app_candidate_ok(title):
                return None
            return ("focus", _canonicalize_app_name(title))
    suf = _SWITCH_SUFFIX.match(n)
    if suf:
        title = (suf.group("name") or "").strip()
        if title:
            if not _fast_app_candidate_ok(title):
                return None
            return ("focus", _canonicalize_app_name(title))
    return None


def start_camera_helper():
    from services.webcam import start
    return start()


def stop_camera_helper():
    from services.webcam import stop
    return stop()


def run_fast_desktop(action):
    """Execute a match_fast_desktop action. Returns (ok, i18n_key)."""
    mapping = {
        "play_pause": (media_play_pause, "playpause_done"),
        "next": (media_next, "next_done"),
        "prev": (media_prev, "prev_done"),
        "screenshot": (save_desktop_screenshot, "shot_done"),
        "camera_on": (start_camera_helper, "camera_opened"),
        "camera_off": (stop_camera_helper, "camera_closed"),
        "face_enroll": (_enroll_owner_face, "face_saved"),
        "face_forget": (_forget_owner_face, "face_forgot"),
        "face_query": (_query_owner_face, "face_known"),
        "snip": (snip_screenshot, "snip_done"),
        "lock": (lock_screen, "lock_done"),
        "sleep": (sleep_pc, "sleep_done"),
        "explorer": (open_explorer, "explorer_done"),
        "desktop": (show_desktop, "desktop_done"),
        "taskmgr": (open_task_manager, "taskmgr_done"),
        "calculator": (open_calculator, "calc_done"),
        "notepad": (open_notepad, "notepad_done"),
        "settings": (open_windows_settings, "settings_done"),
        "recycle": (open_recycle_bin, "recycle_done"),
        "downloads": (open_downloads_folder, "downloads_done"),
        "documents": (open_documents_folder, "documents_done"),
        "desktop_folder": (open_desktop_folder, "desktop_folder_done"),
        "pictures": (open_pictures_folder, "pictures_done"),
        "music": (open_music_folder, "music_done"),
        "clipboard": (open_clipboard_history, "clipboard_done"),
        "mute": (toggle_mute, "mute_toggled"),
        "volume_up": (lambda: volume_up(5), "volume_up"),
        "volume_down": (lambda: volume_down(5), "volume_down"),
    }
    if action == "time":
        now = datetime.now().strftime("%H:%M")
        return True, "time_now", now

    from services import daily
    daily_map = {
        "undo": (daily.undo, "undo_done"),
        "redo": (daily.redo, "redo_done"),
        "copy": (daily.copy_keys, "copy_done"),
        "paste": (daily.paste_keys, "paste_done"),
        "cut": (daily.cut_keys, "cut_done"),
        "select_all": (daily.select_all, "select_all_done"),
        "save": (daily.save_file, "save_done"),
        "snap_left": (lambda: daily.window_action("snap_left"), "snap_left_done"),
        "snap_right": (lambda: daily.window_action("snap_right"), "snap_right_done"),
        "maximize": (lambda: daily.window_action("maximize"), "maximize_done"),
        "minimize_win": (lambda: daily.window_action("minimize"), "minimize_done"),
        "close_window": (lambda: daily.window_action("close"), "close_window_done"),
        "insert_date": (daily.type_date, "date_typed"),
        "insert_time": (daily.type_time, "time_typed"),
        "wifi": (daily.wifi_line, "wifi_line"),
        "battery": (daily.battery_line, "battery_line"),
        "weather": (daily.weather_line, "weather_line"),
        "hide_davi": (lambda: {"success": True}, "hidden"),
        "show_davi": (lambda: {"success": True}, "shown"),
        "stop_talking": (daily.stop_talking, "stopped_talking"),
        "say_again": (lambda: {"success": bool(daily.last_spoken()), "text": daily.last_spoken()}, "say_again"),
        "copy_reply": (daily.copy_last_reply, "copied_reply"),
        "read_selection": (daily.read_selection, "read_selection"),
        "copy_screen": (daily.copy_screen_text, "screen_copied"),
        "search_this": (daily.search_selection, "searching_for"),
        "speak_slower": (lambda: daily.nudge_rate(-10), "slower"),
        "speak_faster": (lambda: daily.nudge_rate(10), "faster"),
        "mute_speech": (lambda: daily.set_speech(False), "speech_muted"),
        "unmute_speech": (lambda: daily.set_speech(True), "speech_unmuted"),
        "mute_mic": (daily.mute_own_mic, "mic_off"),
        "unmute_mic": (daily.unmute_own_mic, "mic_on"),
    }
    if action in daily_map:
        fn, key = daily_map[action]
        try:
            result = fn() or {}
        except Exception as e:
            return False, str(e), ""
        ok = bool(result.get("success", True)) if isinstance(result, dict) else bool(result)
        extra = ""
        if isinstance(result, dict):
            extra = result.get("text") or ""
            if not ok and not extra:
                extra = result.get("error") or ""
        return ok, key, extra

    fn_key = mapping.get(action)
    if not fn_key:
        return False, "", ""
    fn, key = fn_key
    try:
        result = fn()
        extra = ""
        if isinstance(result, dict):
            ok = bool(result.get("success", False) if "success" in result else True)
            if result.get("path"):
                extra = os.path.basename(result["path"])
            if result.get("key"):
                key = result["key"]
            if result.get("text") and action.startswith("face_"):
                extra = result.get("text") or extra
            if not ok and action == "camera_on":
                key = "camera_fail"
                extra = result.get("error") or extra
        else:
            ok = bool(result)
        return ok, key, extra
    except Exception as e:
        return False, str(e), ""


# ── Notification Toast ──────────────────────────────────────────

def show_notification(title, message):
    try:
        ps_cmd = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title}</text>
      <text>{message}</text>
    </binding>
  </visual>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Aemyos").Show($toast)
'''
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, timeout=5, creationflags=0x08000000
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
