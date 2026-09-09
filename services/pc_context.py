"""A compact snapshot of the PC, injected into every LLM turn.

Before this, the model only saw a screenshot and the primary monitor size, so it
had to guess which monitor it was looking at, what else was open, and which apps
exist. Everything here is Win32/filesystem only — no PowerShell — because it runs
on every turn and must stay under a few milliseconds after the first call.
"""
import os
import time

_APP_CACHE = {"apps": None, "at": 0.0}
_APP_TTL = 600.0

# Shortcuts that are never what the user means by "open X".
_APP_SKIP = (
    "uninstall", "readme", "release notes", "help", "documentation",
    "website", "home page", "license", "changelog", "manual",
    "command prompt for", "troubleshoot",
)


def _start_menu_dirs():
    dirs = []
    for env, tail in (
        ("PROGRAMDATA", r"Microsoft\Windows\Start Menu\Programs"),
        ("APPDATA", r"Microsoft\Windows\Start Menu\Programs"),
    ):
        base = os.environ.get(env)
        if base:
            path = os.path.join(base, tail)
            if os.path.isdir(path):
                dirs.append(path)
    return dirs


# Built-ins that often have no Start Menu shortcut but always exist on Windows.
# Protocol URIs (trailing ':') open instantly — never Win+S / click tiles.
_BUILTIN_APPS = {
    "Notepad": "notepad.exe",
    "Calculator": "calc.exe",
    "Paint": "mspaint.exe",
    "File Explorer": "explorer.exe",
    "Command Prompt": "cmd.exe",
    "PowerShell": "powershell.exe",
    "Task Manager": "taskmgr.exe",
    "Snipping Tool": "snippingtool.exe",
    "Control Panel": "control.exe",
    "WordPad": "write.exe",
    "On-Screen Keyboard": "osk.exe",
    "Windows Settings": "ms-settings:",
    "Camera": "microsoft.windows.camera:",
    "Photos": "ms-photos:",
    "Clock": "ms-clock:",
    "Microsoft Store": "ms-windows-store:",
}

# Spoken names → builtin / Start Menu name so TR "kamera" hits Camera URI.
_LAUNCH_ALIASES = {
    "camera": "Camera",
    "kamera": "Camera",
    "kamerayi": "Camera",
    "webcam": "Camera",
    "webkam": "Camera",
    "ayarlar": "Windows Settings",
    "settings": "Windows Settings",
    "calc": "Calculator",
    "hesap": "Calculator",
    "hesap makinesi": "Calculator",
    "not defteri": "Notepad",
    "gezgin": "File Explorer",
}


def installed_apps(refresh=False):
    """Start Menu shortcuts as {name: path}, cached for 10 minutes."""
    now = time.time()
    if not refresh and _APP_CACHE["apps"] is not None and now - _APP_CACHE["at"] < _APP_TTL:
        return _APP_CACHE["apps"]

    apps = {}
    for root_dir in _start_menu_dirs():
        for root, _dirs, files in os.walk(root_dir):
            for fn in files:
                if not fn.lower().endswith((".lnk", ".url")):
                    continue
                name = os.path.splitext(fn)[0].strip()
                low = name.lower()
                if any(s in low for s in _APP_SKIP):
                    continue
                # First win: ProgramData is walked before the per-user folder.
                apps.setdefault(name, os.path.join(root, fn))

    for name, target in _BUILTIN_APPS.items():
        apps.setdefault(name, target)

    _APP_CACHE["apps"] = apps
    _APP_CACHE["at"] = now
    return apps


def find_app(query):
    """Best Start Menu match for a spoken app name, or None."""
    raw = (query or "").strip()
    if not raw:
        return None
    mapped = _LAUNCH_ALIASES.get(raw.lower(), raw)
    q = mapped.lower()
    apps = installed_apps()
    for name in apps:
        if name.lower() == q:
            return name, apps[name]

    starts, contains = [], []
    for name in apps:
        low = name.lower()
        if low.startswith(q):
            starts.append(name)
        elif q in low:
            contains.append(name)

    # "settings" should reach Windows Settings, not WSL Settings — a built-in
    # beats a third-party app whose name merely contains the same word.
    def rank(name):
        return (name not in _BUILTIN_APPS, len(name))

    for bucket in (starts, contains):
        if bucket:
            best = min(bucket, key=rank)
            return best, apps[best]
    return None


def launch_app(query):
    """Open an app directly from its shortcut. Much more reliable than Win+S."""
    hit = find_app(query)
    if not hit:
        return None
    name, path = hit
    try:
        if os.path.sep in path:
            os.startfile(path)
        elif path.endswith(":"):
            os.startfile(path)          # protocol handler, e.g. ms-settings:
        else:
            import subprocess
            subprocess.Popen(path, shell=True, creationflags=0x08000000)
        return name
    except Exception:
        return None


# Dev/admin shortcuts that are real apps but never what a voice user asks for.
_APP_DEMOTE = (
    "administrative tools", "application verifier", "component services",
    "developer powershell", "developer command prompt", "odbc", "dfrgui",
    "system configuration", "system information", "resource monitor",
    "registry editor", "performance monitor", "recovery drive",
    "debuggable package", "windows memory diagnostic", "iscsi",
    "print management", "services", "event viewer", "disk cleanup",
    "character map", "sdk", "vs 20", "faq", "quick start", "docs",
)


def _favorite_app_names():
    try:
        from services.execute_funcs import load_memory
        favs = (load_memory().get("preferences") or {}).get("favorite_apps") or []
        return [str(f) for f in favs]
    except Exception:
        return []


def _rank_apps(apps, limit):
    """Favourites and currently-open apps first; system tools last."""
    names = list(apps.keys())
    lowered = {n: n.lower() for n in names}

    open_titles = ""
    try:
        from services.windows_ops import list_windows
        open_titles = " ".join((w.get("title") or "") for w in list_windows()).lower()
    except Exception:
        pass
    favs = [f.lower() for f in _favorite_app_names()]

    def score(name):
        low = lowered[name]
        if any(low in f or f in low for f in favs):
            return 0
        if low in open_titles:
            return 1
        if any(d in low for d in _APP_DEMOTE):
            return 3
        return 2

    names.sort(key=lambda n: (score(n), lowered[n]))
    return names[:limit]


def _monitor_lines():
    from services.display import virtual_screen, list_monitors, LAST
    virt = virtual_screen()
    mons = list_monitors()
    lines = [f"Virtual desktop: origin ({virt['left']},{virt['top']}) {virt['width']}x{virt['height']}"]
    for i, m in enumerate(mons, 1):
        tag = " (primary)" if m.is_primary else ""
        lines.append(f"  monitor {i}{tag}: origin ({m.left},{m.top}) {m.width}x{m.height}")

    if LAST.get("src_w"):
        lines.append(
            f"Screenshot shows: {LAST['name']} at origin ({LAST['left']},{LAST['top']}), "
            f"{LAST['src_w']}x{LAST['src_h']} scaled to {LAST['img_w']}x{LAST['img_h']}."
        )
        lines.append(
            "Coordinates you read off the screenshot are IMAGE coordinates. "
            "click_ui / move_cursor_to_element handle the mapping for you — "
            "only use move_cursor_absolute with real screen coordinates."
        )
    return lines


def _window_lines(limit=8):
    from services.windows_ops import list_windows, get_foreground_title
    lines = [f'Active window: "{get_foreground_title()}"']
    try:
        wins = [w for w in list_windows() if not w.get("is_davi")]
    except Exception:
        wins = []
    if wins:
        lines.append(f"Open windows ({len(wins)}):")
        for w in wins[:limit]:
            lines.append(f"  - {w['title'][:70]} [{w['state']}]")
        if len(wins) > limit:
            lines.append(f"  … {len(wins) - limit} more (use list_windows)")
    return lines


def _bridge_line():
    try:
        from services.browser_bridge import is_bridge_connected
        if is_bridge_connected():
            from services.chrome_router import tab_context_lines
            return tab_context_lines()
        return ["Chrome extension: not connected — control the browser with keyboard/vision."]
    except Exception:
        return []


def context_block(include_apps=True, app_limit=40):
    """The '=== THIS PC ===' text prepended to each turn's user message."""
    lines = ["=== THIS PC (live, do not guess) ==="]
    for part in (_monitor_lines(), _window_lines()):
        lines.extend(part)

    for line in _bridge_line():
        lines.append(line)
    try:
        from services.webcam import is_on
        if is_on():
            lines.append("Webcam helper: ON — a live camera frame is attached. Use it to see what the user is doing in front of the PC.")
            try:
                from services.face_id import prompt_line
                face_line = prompt_line()
                if face_line:
                    lines.append(face_line)
            except Exception:
                pass
    except Exception:
        pass

    if include_apps:
        try:
            names = installed_apps()
            shown = _rank_apps(names, app_limit)
        except Exception:
            names, shown = {}, []
        if shown:
            lines.append(f"Installed apps ({len(names)} indexed, open with open_app):")
            lines.append("  " + ", ".join(shown))
            lines.append("  open_app also finds apps not listed here — just use the name.")
    return "\n".join(lines)
