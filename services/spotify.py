"""Spotify: "play <song/artist/playlist>" through the desktop app.

Two paths:
  1. Web API (optional): if SPOTIFY_CLIENT_ID/SECRET are set, search → exact URI →
     the desktop app opens it and autoplays. No user login needed (client credentials).
  2. No keys (default): open spotify:search:<query> and press the first "Play"
     button in the results via UIA. Falls back to YouTube results when Spotify
     is not installed.
"""
import base64
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

_TOKEN = {"value": None, "exp": 0}
_ACCENT = str.maketrans("ıİşŞçÇğĞöÖüÜ", "iIsScCgGoOuU")


def _fold(text):
    return re.sub(r"\s+", " ", (text or "").translate(_ACCENT).lower()).strip()


def installed():
    # Classic installer
    if os.path.exists(os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe")):
        return True
    # Microsoft Store package
    try:
        import glob
        if glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "SpotifyAB.SpotifyMusic_*")):
            return True
    except Exception:
        pass
    # Any registered spotify: URL protocol
    try:
        import winreg
        for root, path in ((winreg.HKEY_CLASSES_ROOT, r"spotify"), (winreg.HKEY_CURRENT_USER, r"Software\Classes\spotify")):
            try:
                key = winreg.OpenKey(root, path)
                winreg.CloseKey(key)
                return True
            except OSError:
                continue
    except Exception:
        pass
    return False


def _open_uri(uri):
    os.startfile(uri)


def _hwnd():
    from services.windows_ops import find_hwnd
    m = find_hwnd("spotify")
    if isinstance(m, dict):
        return m.get("hwnd")
    return m


def _wait_window(timeout=12.0):
    end = time.time() + timeout
    while time.time() < end:
        h = _hwnd()
        if h:
            return h
        time.sleep(0.4)
    return None


# ── Web API (optional) ───────────────────────────────────────────

def _creds():
    cid = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    sec = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    return (cid, sec) if cid and sec else None


def _token():
    creds = _creds()
    if not creds:
        return None
    if _TOKEN["value"] and time.time() < _TOKEN["exp"] - 30:
        return _TOKEN["value"]
    auth = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=b"grant_type=client_credentials",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode())
    _TOKEN["value"] = data["access_token"]
    _TOKEN["exp"] = time.time() + int(data.get("expires_in", 3600))
    return _TOKEN["value"]


def search_uri(query, kind="track"):
    """Return (uri, label) via the Web API, or None when no credentials."""
    tok = _token()
    if not tok:
        return None
    kind = kind if kind in ("track", "album", "artist", "playlist") else "track"
    url = "https://api.spotify.com/v1/search?" + urllib.parse.urlencode({"q": query, "type": kind, "limit": 1})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode())
    items = (data.get(kind + "s") or {}).get("items") or []
    items = [i for i in items if i]
    if not items:
        return None
    it = items[0]
    label = it.get("name", "")
    artists = it.get("artists") or []
    if artists:
        label += " · " + artists[0].get("name", "")
    return it["uri"], label


# ── UIA path ─────────────────────────────────────────────────────

def _click_first_play(hwnd, timeout=10.0):
    from services.win_uia import find_controls, _invoke
    end = time.time() + timeout
    while time.time() < end:
        try:
            hits = find_controls(name="Play", control_type="Button", hwnd=hwnd, limit=8)
        except Exception:
            hits = []
        # Prefer the top-result / first track play button; skip the transport "Play" at the bottom.
        cands = [h for h in hits if (h.get("name") or "").lower().startswith("play") and h.get("y") is not None]
        cands.sort(key=lambda h: (h.get("y", 0), h.get("x", 0)))
        for h in cands:
            if h.get("rect") and h["rect"].get("height", 0) > 80:
                continue
            el = h.get("_el")
            if el is not None and _invoke(el):
                return h.get("name") or "Play"
            try:
                from services.win_uia import _mouse_click_xy
                _mouse_click_xy(h["x"], h["y"])
                return h.get("name") or "Play"
            except Exception:
                continue
        time.sleep(0.5)
    return None


def _is_playing():
    try:
        from services.busy_audio import _run, _media_session_async
        transport, _t, _a = _run(_media_session_async())
        return transport == "playing"
    except Exception:
        return False


def play(query, kind="track"):
    query = (query or "").strip()
    if not query:
        return {"success": False, "message": "What should I play?"}
    if not installed():
        from services.chrome_router import youtube_results_url
        from services.smart_features import open_url
        url = youtube_results_url(query)
        r = open_url(url)
        return {"success": r.get("success", True), "message": f"Spotify is not installed, searched YouTube for '{query}'", "fallback": "youtube"}

    # 1. exact URI via Web API
    try:
        hit = search_uri(query, kind)
    except Exception as e:
        print(f"[SPOTIFY] web api failed: {e}")
        hit = None
    if hit:
        uri, label = hit
        _open_uri(uri)
        _wait_window()
        time.sleep(1.2)
        if not _is_playing():
            from services.smart_features import media_play_pause
            media_play_pause()
        return {"success": True, "message": f"Playing on Spotify: {label}", "uri": uri}

    # 2. search page + first Play button
    was_open = bool(_hwnd())
    _open_uri("spotify:search:" + urllib.parse.quote(query))
    hwnd = _wait_window()
    if not hwnd:
        return {"success": False, "message": "Spotify did not open"}
    time.sleep(1.0 if was_open else 3.0)
    try:
        from services.windows_ops import focus_window
        focus_window("spotify")
    except Exception:
        pass
    name = _click_first_play(hwnd)
    if name:
        return {"success": True, "message": f"Playing on Spotify: {query}", "clicked": name}
    return {"success": False, "message": f"Opened Spotify search for '{query}' but could not find a Play button — press play in Spotify"}


# ── Parsing ──────────────────────────────────────────────────────

_NOT_MUSIC = re.compile(r"\b(youtube|video|film|movie|netflix|browser|chrome|edge|tarayici|it|that|this|the song|the music|music|muzik|sarkiyi|onu|bunu)\b")
_KIND_WORDS = {"playlist": "playlist", "album": "album", "artist": "artist", "sanatci": "artist", "albüm": "album", "albumu": "album"}

_EN = [
    re.compile(r"^(?:play|put on|listen to|start)\s+(?P<q>.+?)\s+(?:on|in|from|via)\s+spotify$"),
    re.compile(r"^(?:open\s+)?spotify\s*(?:and\s+)?(?:play|put on)?\s*:?\s*(?P<q>.+)$"),
]
_TR = [
    re.compile(r"^spotify(?:'?d[ae]n?)?\s+(?P<q>.+?)\s+(?:cal|ac|oynat|dinle(?:t)?|baslat)$"),
    re.compile(r"^(?P<q>.+?)\s+(?:spotify(?:'?d[ae]n?)?\s+)?(?:cal|dinlet)(?:\s+spotify(?:'?d[ae]n?)?)?$"),
]
_BARE = re.compile(r"^(?:play|put on)\s+(?P<q>.{2,})$")


def parse_request(text):
    """→ {"query", "kind"} or None. Bare 'play X' only when Spotify is installed."""
    n = _fold(text).rstrip(".!?")
    if not n or n in ("play", "cal", "oynat"):
        return None
    for pat in _TR + _EN:
        m = pat.match(n)
        if m and m.group("q").strip():
            return _finish(m.group("q"), spotify_named=True)
    m = _BARE.match(n)
    if m and not _NOT_MUSIC.search(n) and installed():
        return _finish(m.group("q"), spotify_named=False)
    return None


def _finish(q, spotify_named):
    q = q.strip()
    q = re.sub(r"^(?:the\s+)?(?:song|track|sarki(?:si)?)\s+", "", q)
    kind = "track"
    for w, k in _KIND_WORDS.items():
        m = re.match(rf"^(?:the\s+)?{w}\s+(.+)$", q) or re.match(rf"^(.+?)\s+{w}(?:u|unu|ini)?$", q)
        if m:
            kind, q = k, m.group(1).strip()
            break
    if re.search(r"\b(by|from)\b", q) and kind == "track":
        pass  # "song X by Y" — leave as the search text, Spotify ranks it fine
    if not q or (not spotify_named and _NOT_MUSIC.search(q)):
        return None
    return {"query": q, "kind": kind}
