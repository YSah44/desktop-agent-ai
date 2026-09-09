"""Meetings: listen only unless they say "Aemyos …" or hold F9.

Music and video still take normal commands. Speaker mix is subtracted
from the mic so lyrics are not treated as speech.
"""
import asyncio
import re
import threading
import time

_CACHE = {
    "reason": None, "at": 0.0, "hold_until": 0.0,
    "title": "", "artist": "", "window": "",
    "transport": None,
}
# True only after this overlay session actually heard "playing".
# A leftover paused Spotify/YouTube at launch must not show CONTROLS.
_HAD_PLAY = False
_PRINTED = None
_CACHE_TTL = 0.45
_HOLD_AFTER = 1.6
_LOOP = None
_LOOP_LOCK = threading.Lock()

_MEETING_TITLES = (
    "zoom meeting", "zoom webinar", "zoom workplace",
    "microsoft teams meeting",
    "google meet", "meet.google",
    "webex meeting",
    "voice connected", "ongoing call",
    "slack huddle", "huddle with",
    "meeting | microsoft teams", "call | microsoft teams",
)


_WAKE = re.compile(
    r"^\s*(hey |ok |okay |hi |selam )?(aemyos|davi|dayi|dayı)\b[\s,.:-]*",
    re.IGNORECASE | re.UNICODE,
)


def addressed_to_davi(text):
    """If they said her name first, return the rest (command). Else None."""
    raw = (text or "").strip()
    if not raw:
        return None
    m = _WAKE.match(raw)
    if not m:
        return None
    rest = raw[m.end():].strip()
    return rest or raw


_LYRIC_SKIP_PLAY = frozenset({"play", "pause", "oynat", "stop"})


def hold_commands(reason=None):
    """True only on a call. Music/video must still run what they said."""
    r = peek_busy() if reason is None else reason
    return r == "meeting"


def command_through_media(text):
    """Orders that should still run while a song/video is on, without 'Aemyos …'.

    Lyrics are usually long. Close/pause/volume lines are short and exact.
    Bare 'kapat' / 'stop' still do not count — those quit Aemyos.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    wake = addressed_to_davi(raw)
    if wake:
        return wake
    try:
        from services.smart_features import (
            match_fast_desktop, match_voice_quit, _fold_voice, _strip_voice_polite,
        )
    except Exception:
        return None
    n = _strip_voice_polite(_fold_voice(raw))
    if not n or len(n.split()) > 8:
        return None
    if match_voice_quit(raw):
        return None
    action = match_fast_desktop(raw)
    if action == "play_pause" and n in _LYRIC_SKIP_PLAY:
        return None
    if action in (
        "close_window", "play_pause", "next", "prev",
        "volume_up", "volume_down", "mute",
    ):
        return raw
    return None


_BROWSER_TAIL = re.compile(
    r"\s*[-–—|]\s*(?:google\s+)?(?:chrome|microsoft\s+edge|edge|firefox|brave|opera|safari)\s*$",
    re.IGNORECASE,
)

# Last " - App" segment. Longer names first so "youtube music" wins over "youtube".
_PLAYBACK_APPS = (
    ("youtube music", "media"),
    ("prime video", "video"),
    ("disney plus", "video"),
    ("disney+", "video"),
    ("windows media player", "media"),
    ("vlc media player", "media"),
    ("apple music", "media"),
    ("groove music", "media"),
    ("hbo max", "video"),
    ("youtube", "video"),
    ("netflix", "video"),
    ("twitch", "video"),
    ("crunchyroll", "video"),
    ("soundcloud", "media"),
    ("spotify", "media"),
    ("itunes", "media"),
    ("plex", "video"),
    ("hulu", "video"),
    ("media player", "media"),
    ("vlc", "media"),
)


def meeting_title(titles):
    """Window title of an active call, or None."""
    browsers = ("chrome", "edge", "firefox", "brave", "opera")
    for raw in titles or ():
        t = (raw or "").lower()
        if not t:
            continue
        if any(m in t for m in _MEETING_TITLES):
            return (raw or "").strip()
        parts = [p.strip() for p in t.replace("|", "-").split(" - ") if p.strip()]
        if "meet" in parts and any(b in t for b in browsers):
            return (raw or "").strip()
    return None


def meeting_from_titles(titles):
    """Return True if any window title looks like an active call."""
    return bool(meeting_title(titles))


def parse_playback_title(raw):
    """If this window is a playing video/music app, return kind+title."""
    t = re.sub(r"^\(\d+\)\s*", "", (raw or "").strip())
    t = _BROWSER_TAIL.sub("", t).strip()
    if not t:
        return None
    low = t.lower()
    for app, kind in _PLAYBACK_APPS:
        marker = f" - {app}"
        idx = low.rfind(marker)
        if idx < 0:
            idx = low.rfind(f" – {app}")
        if idx < 0 and low.endswith(app) and low != app:
            idx = len(t) - len(app)
            while idx > 0 and t[idx - 1] in " -–—|":
                idx -= 1
        if idx < 0:
            continue
        title = t[:idx].strip(" -–—|")
        if not title or title.lower() == app:
            return None
        return {"kind": kind, "title": title, "artist": ""}
    return None


def _loop():
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.new_event_loop()
            threading.Thread(target=_LOOP.run_forever, daemon=True, name="busy-audio").start()
    return _LOOP


def _run(coro, timeout=1.2):
    return asyncio.run_coroutine_threadsafe(coro, _loop()).result(timeout=timeout)


async def _media_session_async():
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Mgr,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    )
    mgr = await Mgr.request_async()
    playing = getattr(Status, "PLAYING", 4)
    paused = getattr(Status, "PAUSED", 5)

    async def _names(session):
        title, artist = "", ""
        try:
            props = await session.try_get_media_properties_async()
            if props:
                title = str(getattr(props, "title", "") or "").strip()
                artist = str(
                    getattr(props, "artist", None)
                    or getattr(props, "album_artist", None)
                    or ""
                ).strip()
        except Exception:
            pass
        return title, artist

    paused_hit = None
    for session in mgr.get_sessions():
        info = session.get_playback_info()
        if not info:
            continue
        st = int(info.playback_status)
        if st == int(playing):
            title, artist = await _names(session)
            return "playing", title, artist
        if st == int(paused) and paused_hit is None:
            paused_hit = session
    if paused_hit is not None:
        title, artist = await _names(paused_hit)
        return "paused", title, artist
    return None, "", ""


def media_is_playing():
    try:
        status, _title, _artist = _run(_media_session_async())
        return status == "playing"
    except Exception:
        return False


def peek_track():
    title = (_CACHE.get("title") or "").strip()
    artist = (_CACHE.get("artist") or "").strip()
    if not title and not artist:
        return ""
    if title and artist and artist.lower() not in title.lower():
        return f"{title} — {artist}"
    return title or artist


def peek_window():
    return (_CACHE.get("window") or "").strip()


def _clear_media_cache(window=""):
    _CACHE["title"] = ""
    _CACHE["artist"] = ""
    _CACHE["window"] = window or ""
    _CACHE["transport"] = None


def _window_titles():
    try:
        from services.windows_ops import list_windows, get_foreground_title
        titles = [get_foreground_title() or ""]
        for w in list_windows() or []:
            titles.append(w.get("title") or "")
        return titles
    except Exception:
        return []


def detect_busy(titles=None, media_playing=None):
    """Return 'meeting', 'media', 'video', or None. Inject titles/media in tests."""
    if titles is None:
        titles = _window_titles()
    meet = meeting_title(titles)
    if meet:
        _clear_media_cache(meet)
        return "meeting"
    playing_title, playing_artist = "", ""
    transport = None
    if media_playing is None:
        try:
            transport, playing_title, playing_artist = _run(_media_session_async())
            media_playing = transport == "playing"
        except Exception:
            media_playing = False
            transport = None
            playing_title, playing_artist = "", ""
    else:
        transport = "playing" if media_playing else None
    _CACHE["transport"] = transport
    global _HAD_PLAY
    if transport == "playing":
        _HAD_PLAY = True
    elif transport not in ("playing", "paused"):
        _HAD_PLAY = False
    fg = (titles[0] if titles else "") or ""
    if media_playing:
        parsed = parse_playback_title(fg) if not playing_title else None
        _CACHE["title"] = playing_title or ((parsed or {}).get("title") or "")
        _CACHE["artist"] = playing_artist
        _CACHE["window"] = fg
        if (parsed or {}).get("kind") == "video" and not playing_title:
            return "video"
        return "media"
    parsed = parse_playback_title(fg)
    if parsed:
        _CACHE["title"] = parsed.get("title") or ""
        _CACHE["artist"] = parsed.get("artist") or ""
        _CACHE["window"] = fg
        return "video" if parsed.get("kind") == "video" else "media"
    _CACHE["title"] = playing_title if transport == "paused" else ""
    _CACHE["artist"] = playing_artist if transport == "paused" else ""
    _CACHE["window"] = fg
    if transport != "paused":
        _CACHE["transport"] = None
    return None


def refresh_busy():
    """Poll OS state. Cached so the audio callback never talks to WinRT."""
    now = time.time()
    if now - _CACHE["at"] < _CACHE_TTL:
        return peek_busy()
    try:
        reason = detect_busy()
    except Exception:
        reason = None
    _CACHE["at"] = now
    if reason:
        _CACHE["reason"] = reason
        _CACHE["hold_until"] = now + _HOLD_AFTER
    elif now < _CACHE["hold_until"]:
        reason = _CACHE["reason"]
    else:
        _CACHE["reason"] = None
        reason = None
    global _PRINTED
    if reason != _PRINTED:
        _PRINTED = reason
        if reason:
            try:
                from services.tts import stop_speaking
                stop_speaking()
            except Exception:
                pass
            if reason == "meeting":
                print(f"[MIC] Quiet ({reason}) — listening, no talk until it ends")
            else:
                print(f"[MIC] {reason} on — still taking commands")
        else:
            print("[MIC] Listening again")
    return reason


def playback_controls_wanted(reason=None):
    """Play / next / vol only after real playback this session — not a paused leftover."""
    if reason is None:
        reason = peek_busy()
    if reason == "meeting":
        return False
    transport = _CACHE.get("transport")
    if transport == "playing":
        return True
    if transport == "paused" and _HAD_PLAY:
        return True
    return False


def peek_busy():
    """Last known reason, or None. Safe in the sounddevice callback."""
    now = time.time()
    reason = _CACHE.get("reason")
    if reason and now < _CACHE.get("hold_until", 0):
        return reason
    if reason and now - _CACHE.get("at", 0) < _CACHE_TTL + 0.2:
        return reason
    return None


def is_busy():
    return bool(peek_busy() or refresh_busy())
