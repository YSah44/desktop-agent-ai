import threading
import queue
import time
import re
import numpy as np
import sounddevice as sd
import os
import tempfile
import wave
import urllib.request
import json
import concurrent.futures
from collections import deque

try:
    from config import LISTEN_MODE as _LISTEN_MODE, MIC_MUTED as _MIC_MUTED
except Exception:
    _LISTEN_MODE = "always"
    _MIC_MUTED = False

listen_mode = _LISTEN_MODE   # "always" or "ptt"
_ptt_down = False
mic_muted = bool(_MIC_MUTED)


def set_listen_mode(mode):
    """'always' = open mic, 'ptt' = only capture while the talk key is held,
    'wake' = open mic but only sentences that start with her name count."""
    global listen_mode, _ptt_down
    m = str(mode).lower()
    listen_mode = m if m in ("ptt", "wake") else "always"
    _ptt_down = False
    return listen_mode


def wake_word_required():
    """Wake-word mode, unless the talk key is held (that is explicit enough)."""
    return listen_mode == "wake" and not _ptt_down


def set_ptt_down(down):
    global _ptt_down
    _ptt_down = bool(down)


def set_mic_muted(muted):
    """Stop capturing until unmuted. Hold the talk key to speak a command anyway."""
    global mic_muted
    mic_muted = bool(muted)
    return mic_muted


def is_mic_muted():
    return bool(mic_muted)


def mic_is_open():
    if mic_muted and not _ptt_down:
        return False
    return listen_mode != "ptt" or _ptt_down


def ptt_is_down():
    return bool(_ptt_down)


def room_audio():
    try:
        from config import ROOM_AUDIO
        mode = str(ROOM_AUDIO or "speakers").lower().strip()
    except Exception:
        mode = os.environ.get("DAVI_ROOM_AUDIO", "speakers").lower().strip()
    if mode in ("headphones", "headset", "kulaklik", "kulaklık"):
        return "headphones"
    return "speakers"


def room_is_speakers():
    return room_audio() == "speakers"


def room_is_headphones():
    return room_audio() == "headphones"


def drop_speaker_media(text):
    """True if this was probably a song/video, not a command (speakers + media)."""
    if ptt_is_down() or not room_is_speakers():
        return False
    try:
        from services.busy_audio import peek_busy, command_through_media, addressed_to_davi
        if peek_busy() not in ("media", "video"):
            return False
        if addressed_to_davi(text) or command_through_media(text):
            return False
        return True
    except Exception:
        return False


def set_room_audio(mode):
    """speakers: mic hears the laptop. headphones: isolated mic."""
    global listen_mode
    chosen = "headphones" if str(mode).lower().strip() in (
        "headphones", "headset", "kulaklik", "kulaklık",
    ) else "speakers"
    os.environ["DAVI_ROOM_AUDIO"] = chosen
    try:
        import config
        config.ROOM_AUDIO = chosen
    except Exception:
        pass
    try:
        from services.speaker_tap import set_echo_cancel
        set_echo_cancel(chosen == "speakers")
    except Exception:
        pass
    return chosen


def near_field_user(energy, prev, bleed_floor, sim, headphones=False):
    """True when the mic looks like a person close to it, not speaker bleed."""
    # A block that matches what the speakers are playing is her, whatever the room setting.
    if sim > (0.52 if not headphones else 0.6):
        return False
    floor = max(float(bleed_floor or 0.0), 0.008)
    prev = float(prev or 0.0)
    energy = float(energy or 0.0)
    if headphones:
        return energy > max(0.028, floor * 1.7) and (
            energy > (prev * 1.22 + 0.006) or energy > floor * 1.35
        )
    need = max(floor * 2.35, floor + 0.035, 0.04)
    if energy < need:
        return False
    if energy > (prev * 1.4 + 0.01):
        return True
    return energy > max(floor * 1.85, floor + 0.03)


_ECHO_JUNK = re.compile(r"[^\w\s]+", re.UNICODE)
_BARGE_OK = re.compile(
    r"\b(stop|iptal|cancel|dur|kes|be quiet|shut up|stop talking)\b",
    re.I,
)
_PROMPT_LEAK = re.compile(
    r"[?.,!]?\s*(desktop voice commands?.*|masaüstü sesli komutlar.*|"
    r"desktop voice|masaüstü sesli)\s*$",
    re.I,
)
_active_processor = None
_last_heard = ""
_last_heard_at = 0.0
REPEAT_WINDOW_SEC = 8.0
TTS_TAIL_SEC = 0.04
TTS_HOLDOFF_SEC = 0.4
# Speakers/USB DAC still play her last word after the mixer reports done.
TTS_TAIL_LATENCY_SEC = 0.25
TTS_PREROLL_SEC = 3.0
TTS_PREROLL_SLOP_SEC = 0.04
# 0 = the mic never feeds STT while she is audible; barge-in and the preroll
# ring still catch a user who starts on her last word.
TTS_EARLY_LISTEN_SEC = 0.0
TTS_TAIL_GRACE_SEC = 0.3
_last_early_window = TTS_EARLY_LISTEN_SEC
ECHO_WINDOW_SEC = 5.0
_ECHO_STOP = {
    "a", "an", "the", "on", "my", "you", "your", "is", "are", "to", "and",
    "of", "for", "in", "it", "that", "this", "can", "please", "i", "me", "we",
    "bir", "bu", "şu", "mi", "mı", "mu", "mü",
}
_NEW_REQUEST = re.compile(
    r"\b((can|could|would)\s+you|please\s+|check\s+|how many|how much|"
    r"what(?:'s| is| are)|kaç tane|açar mısın|açar misin)\b",
    re.I,
)
_CAMERA_MARKERS = (
    "live streamer", "webcam", "elgato", "obs virtual", "camera",
)
_LOOPBACK_MARKERS = (
    "stereo mix", "sound mapper", "primary sound", "what u hear", "wave out",
)
_GENERIC_REALTEK = (
    "realtek usb audio", "realtek high definition audio", "realtek(r) audio",
    "realtek audio",
)
_HEADSET_MARKERS = (
    "jabra", "headset", "hands-free", "headphone", "earbuds", "airpods",
)


_BT_MARKERS = ("bluetooth", "bthhf", "bthhfenum", "hands-free", "handsfree")

_pa_lock = threading.Lock()
_pa_refresh_at = 0.0


def is_bluetooth_mic(name):
    n = (name or "").lower().replace("\n", " ")
    return any(s in n for s in _BT_MARKERS)


def mic_display_name(raw):
    name = (raw or "").replace("\n", " ").replace("\r", " ").strip()
    low = name.lower()
    if "@system32" in low or "bthhfenum" in low:
        last_open = name.rfind("(")
        last_close = name.rfind(")")
        if last_open > 0 and last_close > last_open:
            device_name = name[last_open + 1:last_close].strip().rstrip(")")
            if device_name and "System32" not in device_name:
                return f"Headset ({device_name})"
        return "Bluetooth headset"
    return name[:56].strip()


def is_junk_mic(name):
    """Loopbacks, mappers, and empty onboard Realtek — not a real user mic."""
    n = (name or "").lower().replace("\n", " ")
    if is_bluetooth_mic(n):
        return False
    if any(s in n for s in _LOOPBACK_MARKERS):
        return True
    if any(s in n for s in _GENERIC_REALTEK) and not any(
        b in n for b in ("headset", "jabra", "logitech", "steelseries", "hyperx", "corsair", "razer")
    ):
        return True
    return False


def mic_fingerprint(name):
    n = (name or "").lower()
    m = re.search(r"\(([^)]+)\)", n)
    core = m.group(1) if m else n
    core = re.sub(r"^microphone\s+", "", core).strip()
    return re.sub(r"[^a-z0-9]+", "", core)


def fingerprints_match(a, b):
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 10 and longer.startswith(shorter)


def default_input_id():
    try:
        d = sd.default.device
        try:
            idx = int(d[0])
        except Exception:
            idx = int(d)
        if idx >= 0:
            return idx
    except Exception:
        pass
    try:
        info = sd.query_devices(kind="input")
        name = (info.get("name") or "") if isinstance(info, dict) else ""
        if name:
            for i, d in enumerate(sd.query_devices()):
                if d.get("name") == name and d.get("max_input_channels", 0) > 0:
                    return i
    except Exception:
        pass
    return None


def refresh_portaudio():
    """PortAudio caches WASAPI/MME. Newly connected Bluetooth mics stay invisible until this."""
    global _pa_refresh_at
    with _pa_lock:
        try:
            sd._terminate()
            sd._initialize()
            _pa_refresh_at = time.time()
            return True
        except Exception as e:
            print(f"[MIC] PortAudio refresh failed: {e}")
            return False


def _mic_row_rank(index, d, default_id, apis):
    score = 0
    if index == default_id:
        score += 50
    try:
        api = (apis[d.get("hostapi", 0)].get("name") or "").lower()
    except Exception:
        api = ""
    if "wasapi" in api:
        score += 25
    elif "wdm" in api:
        score += 8
    elif "directsound" in api:
        score += 4
    if is_bluetooth_mic(d.get("name") or ""):
        score += 6
    return score


_wasapi_enum = None


def _wasapi_enumerator_cls():
    global _wasapi_enum
    if _wasapi_enum is not None:
        return _wasapi_enum
    from ctypes import POINTER, c_void_p
    from ctypes.wintypes import DWORD, LPWSTR
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = (
            COMMETHOD([], HRESULT, "Activate",
                      (["in"], POINTER(GUID), "iid"),
                      (["in"], DWORD, "dwClsCtx"),
                      (["in"], c_void_p, "pActivationParams"),
                      (["out", "retval"], POINTER(POINTER(IUnknown)), "ppInterface")),
            COMMETHOD([], HRESULT, "OpenPropertyStore",
                      (["in"], DWORD, "stgmAccess"),
                      (["out", "retval"], POINTER(POINTER(IUnknown)), "ppProperties")),
            COMMETHOD([], HRESULT, "GetId",
                      (["out", "retval"], POINTER(LPWSTR), "ppstrId")),
            COMMETHOD([], HRESULT, "GetState",
                      (["out", "retval"], POINTER(DWORD), "pdwState")),
        )

    class IMMDeviceCollection(IUnknown):
        _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387FC4}")
        _methods_ = (
            COMMETHOD([], HRESULT, "GetCount",
                      (["out", "retval"], POINTER(DWORD), "pcDevices")),
            COMMETHOD([], HRESULT, "Item",
                      (["in"], DWORD, "nDevice"),
                      (["out", "retval"], POINTER(POINTER(IMMDevice)), "ppDevice")),
        )

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = (
            COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                      (["in"], DWORD, "dataFlow"),
                      (["in"], DWORD, "dwStateMask"),
                      (["out", "retval"], POINTER(POINTER(IMMDeviceCollection)), "ppDevices")),
            COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                      (["in"], DWORD, "dataFlow"),
                      (["in"], DWORD, "role"),
                      (["out", "retval"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
            COMMETHOD([], HRESULT, "GetDevice",
                      (["in"], LPWSTR, "pwstrId"),
                      (["out", "retval"], POINTER(POINTER(IMMDevice)), "ppDevice")),
            COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback",
                      (["in"], POINTER(IUnknown), "pClient")),
            COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback",
                      (["in"], POINTER(IUnknown), "pClient")),
        )

    _wasapi_enum = (IMMDeviceEnumerator, GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"))
    return _wasapi_enum


def active_capture_ids():
    """Live Windows capture-endpoint IDs. Changes when a Bluetooth mic comes online."""
    try:
        from comtypes import CLSCTX_ALL, CoCreateInstance
        try:
            import comtypes
            comtypes.CoInitialize()
        except OSError:
            pass
        enumerator_cls, clsid = _wasapi_enumerator_cls()
        enumerator = CoCreateInstance(clsid, interface=enumerator_cls, clsctx=CLSCTX_ALL)
        collection = enumerator.EnumAudioEndpoints(1, 0x00000001)
        count = int(collection.GetCount())
        ids = []
        for i in range(count):
            try:
                ident = collection.Item(i).GetId()
                if ident:
                    ids.append(str(ident))
            except Exception:
                continue
        return frozenset(ids)
    except Exception as e:
        print(f"[MIC] WASAPI endpoint scan failed: {e}")
        return None


def list_user_mics():
    """One row per physical mic. Drops loopbacks, empty Realtek, and API duplicates."""
    try:
        with _pa_lock:
            devices = list(sd.query_devices())
            try:
                apis = list(sd.query_hostapis())
            except Exception:
                apis = []
    except Exception:
        return []
    default_id = default_input_id()
    rows = []
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) <= 0:
            continue
        raw = d.get("name") or ""
        if is_junk_mic(raw):
            continue
        label = mic_display_name(raw)
        if not label or is_junk_mic(label):
            continue
        fp = mic_fingerprint(label)
        if not fp:
            continue
        rank = _mic_row_rank(i, d, default_id, apis)
        dup_at = None
        for j, (_id, _label, old_fp, _rank) in enumerate(rows):
            if fingerprints_match(fp, old_fp):
                dup_at = j
                break
        if dup_at is not None:
            if rank > rows[dup_at][3]:
                rows[dup_at] = (i, label, fp, rank)
            continue
        rows.append((i, label, fp, rank))
    return [(i, label) for i, label, _fp, _rank in rows]


def score_input_device(name):
    """Lower is better. Used only for tests/legacy ranking."""
    n = (name or "").lower().replace("\n", " ").replace("\r", " ")
    if is_junk_mic(n) or any(s in n for s in _LOOPBACK_MARKERS):
        return 1000
    if any(s in n for s in _CAMERA_MARKERS) or re.search(r"\bcam\d", n):
        return 800
    score = 50
    if "jabra" in n:
        score -= 40
    if any(s in n for s in _HEADSET_MARKERS):
        score -= 25
    if "bluetooth" in n or "bthhfenum" in n:
        score -= 10
    if "microphone" in n:
        score -= 8
    return score


def normalize_speech(text):
    raw = (text or "").lower()
    raw = _ECHO_JUNK.sub(" ", raw)
    return " ".join(raw.split())


def _spoken_lines(spoken=None):
    """Lines to compare for echo. Explicit `spoken=` is tests/direct; live path is last TTS only."""
    if spoken:
        n = normalize_speech(spoken)
        return [n] if n else []
    try:
        from services.daily import recent_spoken
        lines = [normalize_speech(s) for s in recent_spoken()[-3:]]
        return [n for n in lines if n]
    except Exception:
        return []


def _echo_window_open():
    """Speaker bleed only matters while she talks, or just after the speakers catch up."""
    try:
        from services.tts import is_speaking, playback_ended_at
        if is_speaking:
            return True
        ended = float(playback_ended_at() or 0.0)
        if ended and (time.time() - ended) < ECHO_WINDOW_SEC:
            return True
    except Exception:
        pass
    try:
        from services.daily import spoken_at
        at = float(spoken_at() or 0.0)
        if at and (time.time() - at) < ECHO_WINDOW_SEC:
            return True
    except Exception:
        pass
    return False


def _content_words(text):
    return [w for w in (text or "").split() if w and w not in _ECHO_STOP]


def is_own_voice_echo(heard, spoken=None):
    """True when STT looks like the line she just spoke (speaker bleed)."""
    from difflib import SequenceMatcher
    h = normalize_speech(heard)
    if not h:
        return False
    if spoken is None and not _echo_window_open():
        return False
    hw = _content_words(h)
    looks_new = bool(_NEW_REQUEST.search(h))
    for s in _spoken_lines(spoken):
        if not s:
            continue
        ratio = SequenceMatcher(None, h, s).ratio() if len(h) >= 10 and len(s) >= 10 else 0.0
        if looks_new and ratio < 0.88:
            continue
        if len(h) >= 16 and len(s) >= 16 and (h in s or s in h):
            return True
        sw = set(_content_words(s))
        extra = [w for w in hw if w not in sw]
        if len(hw) >= 2 and extra and (len(extra) / float(len(hw))) >= 0.45:
            continue
        if len(hw) >= 4 and sw:
            hits = sum(1 for w in hw if w in sw)
            if hits / len(hw) >= 0.72:
                return True
        if ratio >= 0.78:
            return True
    return False


def early_listen_sec():
    """How early before the end of TTS the mic may open. Short lines get a short window
    so a 1.3s reply is not captured almost whole."""
    try:
        from services.tts import playback_length
        length = float(playback_length() or 0.0)
    except Exception:
        length = 0.0
    global _last_early_window
    if TTS_EARLY_LISTEN_SEC <= 0:
        _last_early_window = 0.0
        return 0.0
    if length <= 0:
        return _last_early_window
    _last_early_window = min(TTS_EARLY_LISTEN_SEC, max(0.25, length * 0.3))
    return _last_early_window


def tts_capture_blocked():
    """True while her TTS body should not go to STT. Opens shortly before the end."""
    try:
        from services.tts import is_speaking, is_playing, playback_remaining
        if not is_speaking:
            return False
        if not is_playing:
            return True
        window = early_listen_sec()
        if window <= 0:
            return True
        return float(playback_remaining()) > window
    except Exception:
        return False


def is_tts_tail_capture(started_at):
    """True when the clip started in the body of her playback, not the overlap tail."""
    if not started_at:
        return False
    started = float(started_at)
    try:
        from services.tts import is_speaking, is_playing, playback_ended_at, playback_remaining
        ended = float(playback_ended_at() or 0.0)
        if ended > 0 and started <= ended + 0.05:
            return started < ended - max(_last_early_window, TTS_TAIL_GRACE_SEC) - 0.05
        if is_speaking and not is_playing:
            return True
        if is_speaking and is_playing:
            remaining_at_start = float(playback_remaining()) + max(0.0, time.time() - started)
            return remaining_at_start > early_listen_sec()
    except Exception:
        return False
    return False


def looks_like_barge_in(heard):
    return bool(_BARGE_OK.search(heard or ""))


def is_tts_tail_echo(heard, started_at):
    """A short clip right after her playback that is only her last words."""
    if not started_at:
        return False
    try:
        from services.tts import playback_ended_at
        ended = float(playback_ended_at() or 0.0)
    except Exception:
        return False
    if not ended or float(started_at) - ended > 1.0:
        return False
    hw = _content_words(normalize_speech(heard))
    if not hw or len(hw) > 3:
        return False
    for s in _spoken_lines():
        tail = _content_words(s)[-6:]
        if tail and all(w in tail for w in hw):
            return True
    return False


def strip_prompt_leak(text):
    """Groq often appends the Whisper hint ('Desktop voice…') to a real phrase."""
    cleaned = _PROMPT_LEAK.sub("", text or "").strip()
    cleaned = cleaned.strip(" ?.,!")
    return cleaned


def remember_heard(text):
    global _last_heard, _last_heard_at
    n = normalize_speech(text)
    if n:
        _last_heard = n
        _last_heard_at = time.time()


def is_repeat_command(heard):
    """True when STT is the same command we just accepted (echo / hallucination)."""
    h = normalize_speech(strip_prompt_leak(heard))
    if not h or not _last_heard:
        return False
    if time.time() - float(_last_heard_at or 0.0) > REPEAT_WINDOW_SEC:
        return False
    if h == _last_heard:
        return True
    shorter, longer = (h, _last_heard) if len(h) <= len(_last_heard) else (_last_heard, h)
    if len(shorter) >= 12 and shorter in longer:
        return True
    from difflib import SequenceMatcher
    return SequenceMatcher(None, h, _last_heard).ratio() >= 0.82


def speech_onset(energy, prev, floor, vad_threshold, sim=0.0, busy=False):
    """Start a take only when this block looks like near-field speech.

    Echo cancel being on is not enough to raise the bar — that would ignore
    a normal talking voice. Raise it when the mic still matches the speakers.
    """
    talking = energy > vad_threshold
    if sim > 0.35 or busy:
        floor = max(float(floor or 0.0), 0.004)
        jump = energy > (float(prev) * 1.55 + 0.006)
        need = max(vad_threshold, floor * (5.2 if sim > 0.48 else 2.8) + 0.012)
        talking = energy > need and jump
    return talking


def notify_tts_started():
    proc = _active_processor
    if proc is not None:
        proc.flush_after_tts(holdoff=0.0)
        proc._was_tts = True
        proc._listen_live_after_tts = False
        proc._awaiting_quiet = False


def notify_tts_ended():
    proc = _active_processor
    if proc is not None:
        proc.arm_listen_after_tts()


class VoiceInputProcessor:
    def __init__(self, model_name="base", language=None, sample_rate=16000, device=None, vad_threshold=0.01, callback=None):
        self.language = language
        self.language = self._stt_language()
        self.whisper_prompt = self._stt_prompt()
        self.sample_rate = sample_rate

        try:
            from config import GROQ_API_KEY
            self.groq_key = GROQ_API_KEY
        except ImportError:
            self.groq_key = os.environ.get("GROQ_API_KEY", "")
        backend = self._stt_backend()
        if backend == "openrouter":
            print(f"[VOICE] Using OpenRouter for speech recognition (lang={self.language})")
        elif backend == "groq":
            print(f"[VOICE] Using Groq API for speech recognition (lang={self.language})")
        else:
            print("[VOICE] No Groq or OpenRouter key. Voice recognition is off.")

        print("\nAvailable audio devices:")
        devices = sd.query_devices()
        default_input = sd.default.device[0]
        for i, d in enumerate(devices):
            if d['max_input_channels'] > 0:
                marker = " <-- AKTIF" if i == default_input else ""
                print(f"  [{i}] {d['name']} (channels: {d['max_input_channels']}){marker}")

        self.audio_queue = queue.Queue()
        self.text_queue = queue.Queue()
        self.is_running = False
        self.thread = None

        self.vad_threshold = vad_threshold
        self.silence_duration = 1.2
        self.max_record_duration = 20.0
        self.min_speech_duration = 0.5

        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.futures = []
        self.audio_chunks = []
        self.last_speech_time = 0
        self.recording_start_time = 0
        self.is_recording = False

        self.callback = callback
        self.processing_indicator = False
        self.current_audio_level = 0.0
        self.last_transcription = ""
        self.last_stt_error = ""
        self._tts_barge_hits = 0
        self._tts_barge_cooldown = 0
        self._was_tts = False
        self._tts_holdoff_until = 0.0
        self._listen_epoch = 0
        self._tts_overlap_talk = False
        self._awaiting_quiet = False
        self._quiet_frames = 0
        self._tts_preroll = deque()
        self._listen_live_after_tts = False
        self.input_device_id = None
        self.capture_rate = sample_rate
        self._energy_floor = 0.0
        self._prev_energy = 0.0
        self._tts_bleed_floor = 0.0
        self._tts_bleed_n = 0
        self._record_sim_sum = 0.0
        self._record_sim_n = 0
        self._record_near = False
        self._io_lock = threading.Lock()

    def _sync_speaker_tap(self):
        try:
            from services.speaker_tap import start as _tap_start, stop as _tap_stop, echo_cancel_enabled
            if echo_cancel_enabled() and self.is_running:
                exclude = {self.input_device_id} if self.input_device_id is not None else set()
                _tap_start(exclude_mic=exclude)
            else:
                _tap_stop()
        except Exception as e:
            print(f"[MIC] Speaker tap: {e}")

    def mic_is_gated(self):
        if getattr(self, "_was_tts", False) and not getattr(self, "_listen_live_after_tts", False):
            return tts_capture_blocked()
        if time.time() < getattr(self, "_tts_holdoff_until", 0):
            return True
        if is_mic_muted() and not ptt_is_down():
            return True
        return tts_capture_blocked()

    def _discard_capture(self):
        self.audio_chunks = []
        self.is_recording = False
        self.current_audio_level = 0.0
        self._tts_barge_hits = 0
        self._record_sim_sum = 0.0
        self._record_sim_n = 0
        self._record_near = False

    def _drain_queue(self, q):
        if q is None:
            return
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break

    def flush_after_tts(self, holdoff=None):
        """Drop anything captured or recognized while she was talking."""
        if holdoff is None:
            holdoff = TTS_HOLDOFF_SEC
        self._listen_epoch = getattr(self, "_listen_epoch", 0) + 1
        self._was_tts = False
        self._tts_overlap_talk = False
        self._listen_live_after_tts = False
        self._awaiting_quiet = False
        self._quiet_frames = 0
        self._tts_preroll = deque()
        self._tts_holdoff_until = time.time() + max(0.0, float(holdoff))
        self._tts_bleed_floor = 0.0
        self._tts_bleed_peak = 0.0
        self._tts_bleed_n = 0
        self._tts_barge_hits = 0
        self._discard_capture()
        self._drain_queue(self.audio_queue)
        self._drain_queue(self.text_queue)

    def _ensure_preroll(self):
        buf = getattr(self, "_tts_preroll", None)
        if not isinstance(buf, deque):
            self._tts_preroll = deque(buf or ())
        return self._tts_preroll

    def _push_preroll(self, audio_data, t_end):
        """Keep the last ~3s of mic audio while she talks. Not sent to STT."""
        if audio_data is None or len(audio_data) < 1:
            return
        sr = float(getattr(self, "sample_rate", 16000) or 16000)
        samples = np.ascontiguousarray(audio_data, dtype=np.float32)
        dur = len(samples) / sr if sr else 0.0
        buf = self._ensure_preroll()
        buf.append((float(t_end) - dur, samples))
        horizon = float(t_end) - TTS_PREROLL_SEC
        while buf:
            ts, chunk = buf[0]
            end_ts = ts + (len(chunk) / sr if sr else 0.0)
            if end_ts >= horizon:
                break
            buf.popleft()

    def _cut_preroll(self, cutoff):
        """Keep only samples at/after cutoff. Returns (chunks, first_timestamp)."""
        kept = []
        first_ts = None
        sr = float(getattr(self, "sample_rate", 16000) or 16000)
        for t_start, samples in list(self._ensure_preroll()):
            if samples is None or len(samples) == 0:
                continue
            t_start = float(t_start)
            dur = len(samples) / sr if sr else 0.0
            if t_start + dur <= cutoff:
                continue
            if t_start >= cutoff:
                piece = np.ascontiguousarray(samples, dtype=np.float32)
                ts = t_start
            else:
                off = int(round((cutoff - t_start) * sr)) if sr else 0
                off = max(0, min(off, len(samples)))
                if off >= len(samples):
                    continue
                piece = np.ascontiguousarray(samples[off:], dtype=np.float32)
                ts = t_start + (off / sr if sr else 0.0)
            kept.append(piece)
            if first_ts is None:
                first_ts = ts
        return kept, first_ts

    def _preroll_has_speech(self, chunks):
        if not chunks:
            return False
        try:
            audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
            if audio is None or len(audio) < 1:
                return False
            energy = float(np.mean(np.abs(audio)))
        except Exception:
            return False
        return energy > float(getattr(self, "vad_threshold", 0.01) or 0.01)

    def arm_listen_after_tts(self):
        """TTS finished: open the mic immediately. Do not seed with her last words."""
        self._awaiting_quiet = False
        self._quiet_frames = 0
        self._was_tts = False
        self._tts_overlap_talk = False
        if getattr(self, "_listen_live_after_tts", False):
            return
        # Preroll keeps filling during the holdoff, so a user who starts on her
        # last word loses nothing; her own tail is cut at recording start.
        self._tts_holdoff_until = time.time() + TTS_HOLDOFF_SEC
        self._listen_live_after_tts = True
        self._listen_epoch = getattr(self, "_listen_epoch", 0) + 1
        self._drain_queue(getattr(self, "audio_queue", None))
        self._drain_queue(getattr(self, "text_queue", None))
        self._discard_capture()
        print("[MIC] TTS ended, listening...")

    def arm_listen_early(self):
        """Open capture on the last beat of TTS so the first user word is kept."""
        if getattr(self, "_listen_live_after_tts", False):
            return
        self._listen_live_after_tts = True
        self._tts_holdoff_until = 0.0
        self._awaiting_quiet = False
        self._quiet_frames = 0
        print("[MIC] Early listen...")

    def _apply_echo(self, audio_data):
        sim = 0.0
        sr = int(getattr(self, "sample_rate", 16000) or 16000)
        try:
            from services.speaker_tap import echo_cancel_enabled, latest as _spk_latest, cancel_echo
            # While she talks we know the exact waveform being played: match the mic
            # against it (any output device, no Stereo Mix needed). Otherwise fall back
            # to the speaker tap for music / video bleed.
            ref = None
            try:
                from services.tts import reference_window
                ref = reference_window(len(audio_data), sr)
            except Exception:
                ref = None
            if ref is not None:
                audio_data, sim = cancel_echo(audio_data, ref, sr=sr, max_lag_sec=0.3)
            elif echo_cancel_enabled():
                ref = _spk_latest(len(audio_data), sr)
                audio_data, sim = cancel_echo(audio_data, ref, sr=sr)
        except Exception:
            sim = 0.0
        energy = float(np.mean(np.abs(audio_data)))
        return audio_data, energy, sim

    def _note_bleed(self, energy):
        floor = float(getattr(self, "_tts_bleed_floor", 0.0) or 0.0)
        self._tts_bleed_floor = (0.88 * floor + 0.12 * energy) if floor else energy
        self._tts_bleed_n = int(getattr(self, "_tts_bleed_n", 0) or 0) + 1
        return self._tts_bleed_floor, self._tts_bleed_n

    def _resample_to_model_rate(self, audio_data):
        src = int(getattr(self, "capture_rate", 0) or getattr(self, "sample_rate", 16000) or 16000)
        dst = int(getattr(self, "sample_rate", 16000) or 16000)
        if src == dst or audio_data is None or len(audio_data) < 2:
            return audio_data
        src_len = len(audio_data)
        dst_len = max(2, int(round(src_len * dst / src)))
        x_old = np.linspace(0.0, 1.0, src_len, endpoint=False)
        x_new = np.linspace(0.0, 1.0, dst_len, endpoint=False)
        return np.interp(x_new, x_old, audio_data).astype(np.float32)

    def audio_callback(self, indata, frames, time_info, status):
        audio_data = indata.copy()
        if audio_data.ndim > 1 and audio_data.shape[1] > 1:
            audio_data = np.mean(audio_data, axis=1)
        else:
            audio_data = audio_data.reshape(-1)
        audio_data = self._resample_to_model_rate(audio_data)

        energy = float(np.mean(np.abs(audio_data)))
        current_time = time.time()

        # Push-to-talk: keep the level meter alive but drop everything captured
        # while the talk key is up, and flush a recording the user cut short.
        if not mic_is_open():
            self.current_audio_level = min(energy * 10, 1.0)
            if self.is_recording:
                self._finish_recording(current_time)
            return

        speaking = False
        try:
            from services.tts import is_speaking
            speaking = bool(is_speaking)
        except ImportError:
            pass

        blocked = tts_capture_blocked() if speaking else False

        # Never send the body of speaker playback to STT. Keep a last-3s ring
        # so when the last beat opens we already have the user's first word.
        if blocked:
            if getattr(self, "_listen_live_after_tts", False):
                self.current_audio_level = 0.0
                return
            if not getattr(self, "_was_tts", False):
                self._listen_epoch = getattr(self, "_listen_epoch", 0) + 1
                self._drain_queue(self.audio_queue)
                self._tts_preroll = deque()
                self._listen_live_after_tts = False
                self._discard_capture()
            self._was_tts = True
            self._awaiting_quiet = False
            self._quiet_frames = 0
            self._tts_overlap_talk = False
            self._push_preroll(audio_data, current_time)
            _, energy_b, sim_b = self._apply_echo(audio_data)
            prev_b = float(getattr(self, "_prev_energy", 0.0) or 0.0)
            floor_b = float(getattr(self, "_tts_bleed_floor", 0.0) or 0.0)
            n_b = int(getattr(self, "_tts_bleed_n", 0) or 0)
            self._prev_energy = energy_b
            self.current_audio_level = min(energy_b * 10, 1.0)
            # Her own playback sets the reference: a barge-in must clearly beat the
            # loudest thing heard so far in this utterance, block after block.
            peak_b = float(getattr(self, "_tts_bleed_peak", 0.0) or 0.0)
            louder_than_her = energy_b > max(peak_b * 1.6, 0.02)
            if n_b >= 5 and louder_than_her and near_field_user(
                energy_b, prev_b, floor_b, sim_b, headphones=room_is_headphones()
            ):
                self._tts_barge_hits = int(getattr(self, "_tts_barge_hits", 0) or 0) + 1
            else:
                self._tts_barge_hits = 0
                self._note_bleed(energy_b)
                self._tts_bleed_peak = max(peak_b * 0.97, energy_b)
            # Speakers: her own loud syllables can pass near_field twice in a row.
            need_hits = 2 if room_is_headphones() else 3
            if self._tts_barge_hits >= need_hits:
                self._tts_barge_hits = 0
                self._barge_at = current_time
                try:
                    from services.tts import stop_speaking
                    stop_speaking()
                    print("[MIC] Barge-in, stopping speech...")
                except Exception:
                    pass
            return

        if not getattr(self, "_listen_live_after_tts", False) and (
            getattr(self, "_was_tts", False)
            or getattr(self, "_tts_preroll", None)
        ):
            if speaking:
                self.arm_listen_early()
            else:
                self.arm_listen_after_tts()

        if current_time < getattr(self, "_tts_holdoff_until", 0):
            self.current_audio_level = 0.0
            self._push_preroll(audio_data, current_time)
            return

        self.current_audio_level = min(energy * 10, 1.0)

        audio_data, energy, sim = self._apply_echo(audio_data)
        if sim < 0.45:
            self._tts_barge_hits = 0

        busy = False
        try:
            from services.busy_audio import peek_busy
            busy = bool(peek_busy())
        except Exception:
            busy = False

        prev = float(getattr(self, "_prev_energy", 0.0) or 0.0)
        self._prev_energy = energy
        floor = float(getattr(self, "_energy_floor", 0.0) or 0.0)
        if (not self.is_recording) or sim > 0.4:
            self._energy_floor = (0.92 * floor + 0.08 * energy) if floor else energy
            floor = self._energy_floor

        if speaking:
            bleed = float(getattr(self, "_tts_bleed_floor", 0.0) or 0.0)
            n_b = int(getattr(self, "_tts_bleed_n", 0) or 0)
            if room_is_speakers() and n_b < 4:
                talking = False
                self._note_bleed(energy)
            else:
                talking = near_field_user(
                    energy, prev, bleed, sim, headphones=room_is_headphones()
                )
                if not talking:
                    self._note_bleed(energy)
            # Her last word is loud too; one block is not enough to start a take
            # while she is still audible.
            if talking and not self.is_recording:
                self._early_hits = int(getattr(self, "_early_hits", 0) or 0) + 1
                talking = self._early_hits >= 2
            elif not talking:
                self._early_hits = 0
        else:
            self._early_hits = 0
            talking = speech_onset(
                energy, prev, floor, self.vad_threshold, sim=sim, busy=busy,
            )

        if talking:
            if not self.is_recording:
                self.is_recording = True
                self.audio_chunks = []
                self.recording_start_time = current_time
                self._record_sim_sum = 0.0
                self._record_sim_n = 0
                self._record_near = True
                if getattr(self, "_listen_live_after_tts", False) or speaking:
                    cutoff = current_time - (0.28 if speaking else 0.55)
                    try:
                        from services.tts import playback_ended_at
                        ended = float(playback_ended_at() or 0.0)
                    except Exception:
                        ended = 0.0
                    if ended and not speaking:
                        barge_at = float(getattr(self, "_barge_at", 0.0) or 0.0)
                        if barge_at and abs(ended - barge_at) < 0.5:
                            cutoff = barge_at - 0.6
                        else:
                            cutoff = max(ended + TTS_TAIL_LATENCY_SEC, current_time - 0.70)
                        self._barge_at = 0.0
                    leftover, first_ts = self._cut_preroll(cutoff)
                    self._tts_preroll = deque()
                    if leftover:
                        self.audio_chunks = leftover
                        self.recording_start_time = float(first_ts or current_time)
                print("[MIC] Speech detected, recording...")
            self.last_speech_time = current_time

        if self.is_recording:
            self._record_sim_sum = float(getattr(self, "_record_sim_sum", 0.0) or 0.0) + float(sim or 0.0)
            self._record_sim_n = int(getattr(self, "_record_sim_n", 0) or 0) + 1
            if near_field_user(energy, prev, floor, sim, headphones=room_is_headphones()):
                self._record_near = True
            self.audio_chunks.append(np.ascontiguousarray(audio_data, dtype=np.float32))
            recording_duration = current_time - self.recording_start_time
            silence_duration = current_time - self.last_speech_time
            max_len = 3.2 if busy else self.max_record_duration
            quiet_for = 0.65 if busy else self.silence_duration

            if silence_duration >= quiet_for or recording_duration >= max_len:
                self._finish_recording(current_time)

    def _finish_recording(self, current_time):
        recording_duration = current_time - self.recording_start_time
        n_sim = int(getattr(self, "_record_sim_n", 0) or 0)
        mean_sim = (float(getattr(self, "_record_sim_sum", 0.0) or 0.0) / n_sim) if n_sim else 0.0
        near = bool(getattr(self, "_record_near", False))
        if (
            room_is_speakers()
            and n_sim >= 3
            and mean_sim > 0.58
            and not near
        ):
            print("[MIC] Dropped speaker mix (music/TTS)")
            self.audio_chunks = []
            self.is_recording = False
            return
        if recording_duration >= self.min_speech_duration and self.audio_chunks:
            audio_array = np.concatenate(self.audio_chunks)
            epoch = getattr(self, "_listen_epoch", 0)
            started = float(self.recording_start_time or current_time)
            self.audio_queue.put((audio_array, epoch, started))
            self.processing_indicator = True
            print(f"[MIC] {recording_duration:.1f}s recorded, recognizing...")
        else:
            print(f"[MIC] Too short ({recording_duration:.2f}s), skipping")
        self.audio_chunks = []
        self.is_recording = False

    def _save_wav(self, audio_data):
        tmp = os.path.join(tempfile.gettempdir(), "agent_voice.wav")
        if np.max(np.abs(audio_data)) > 0:
            audio_data = audio_data / np.max(np.abs(audio_data))
        pcm = (audio_data * 32767).astype(np.int16)
        with wave.open(tmp, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm.tobytes())
        return tmp

    def _stt_language(self):
        """Overlay language is the Whisper/Groq language. TR stays tr."""
        try:
            from services.i18n import whisper_language
            code = (whisper_language() or "").lower().strip()
            if code:
                self.language = code
                return code
        except Exception:
            pass
        code = getattr(self, "language", None) or os.environ.get("DAVI_LANGUAGE") or "en"
        code = str(code).lower().strip() or "en"
        self.language = code
        return code

    def _stt_prompt(self):
        try:
            from services.i18n import t
            prompt = t("whisper_prompt")
            if prompt:
                self.whisper_prompt = prompt
                return prompt
        except Exception:
            pass
        fallback = "Desktop voice commands: open Chrome, new tab, click, scroll, search, volume, mute, remind me."
        return getattr(self, "whisper_prompt", None) or fallback

    def _stt_model(self):
        model = os.environ.get("DAVI_WHISPER_MODEL", "whisper-large-v3-turbo") or "whisper-large-v3-turbo"
        lang = self._stt_language()
        if lang != "en" and "distil" in model and str(model).endswith("-en"):
            print(f"[VOICE] Skipping English-only {model}; using whisper-large-v3-turbo for '{lang}'")
            return "whisper-large-v3-turbo"
        return model

    def consume_stt_error(self):
        msg = getattr(self, "last_stt_error", "") or ""
        self.last_stt_error = ""
        return msg

    def _fail_stt(self, reason=""):
        """Clear processing so the overlay never freezes; surface a one-line mic error."""
        self.processing_indicator = False
        try:
            from services.i18n import t
            self.last_stt_error = t("mic_error")
        except Exception:
            self.last_stt_error = "Mic error — try again"
        if reason:
            print(f"[STT] fail: {reason}")
        return None

    def _stt_backend(self):
        try:
            import config as cfg
            if cfg.using_openrouter():
                if cfg.OPENROUTER_KEY or os.environ.get("OPENROUTER_API_KEY"):
                    return "openrouter"
                return "none"
            groq = cfg.GROQ_API_KEY or getattr(self, "groq_key", "") or os.environ.get("GROQ_API_KEY", "")
            if groq:
                return "groq"
        except Exception:
            if getattr(self, "groq_key", "") or os.environ.get("GROQ_API_KEY", ""):
                return "groq"
        return "none"

    def _finish_transcript(self, transcription, tag="STT"):
        transcription = (transcription or "").strip()
        self.processing_indicator = False
        if not transcription:
            return None
        transcription = strip_prompt_leak(transcription)
        if not transcription:
            print(f"[{tag}] Filtered hallucination: empty after prompt leak")
            return None
        lower_t = transcription.lower().strip().rstrip(".")
        hallucination_exact = {
            "thank you", "thanks", "thank you for watching",
            "thanks for watching", "please subscribe",
            "like and subscribe", "bye", "goodbye",
            "türkçe ve ingilizce sesli komutlar",
            "desktop voice commands",
            "desktop voice",
        }
        if lower_t in hallucination_exact or "desktop voice command" in lower_t:
            print(f"[{tag}] Filtered hallucination: '{transcription}'")
            return None
        if len(transcription) < 2:
            return None
        return transcription

    def _transcribe_groq(self, audio_data):
        lang = self._stt_language()
        prompt = self._stt_prompt()
        model = self._stt_model()
        print(f"[GROQ] Recognizing speech (lang={lang})...")
        start_time = time.time()
        wav_path = self._save_wav(audio_data)

        try:
            import requests
            groq_key = getattr(self, "groq_key", "") or os.environ.get("GROQ_API_KEY", "")
            try:
                import config as cfg
                groq_key = cfg.GROQ_API_KEY or groq_key
            except Exception:
                pass
            with open(wav_path, 'rb') as f:
                resp = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    files={"file": ("audio.wav", f, "audio/wav")},
                    data={
                        "model": model,
                        "language": lang,
                        "prompt": prompt,
                    },
                    timeout=10
                )
            if resp.status_code >= 400:
                detail = ""
                try:
                    body = resp.json()
                    err = body.get("error") if isinstance(body, dict) else None
                    if isinstance(err, dict):
                        detail = str(err.get("message") or "")[:200]
                    elif isinstance(body, dict):
                        detail = str(body.get("message") or "")[:200]
                except Exception:
                    detail = (resp.text or "")[:120]
                print(f"[GROQ] HTTP {resp.status_code}: {detail}")
                return self._fail_stt(f"HTTP {resp.status_code}")
            result = resp.json()
            if isinstance(result, dict) and result.get("error"):
                err = result.get("error")
                detail = err.get("message") if isinstance(err, dict) else str(err)
                print(f"[GROQ] API error: {str(detail)[:200]}")
                return self._fail_stt("api error")
            transcription = (result.get("text") or "").strip() if isinstance(result, dict) else ""
            elapsed = time.time() - start_time
            print(f"[GROQ] Recognized in {elapsed:.1f}s: '{transcription}'")
            return self._finish_transcript(transcription, "GROQ")

        except Exception as e:
            print(f"[GROQ] Error: {e}")
            return self._fail_stt(str(e)[:120])
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def _transcribe_openrouter(self, audio_data):
        import base64
        lang = self._stt_language()
        try:
            import config as cfg
            model = cfg.stt_model_id()
            key = cfg.OPENROUTER_KEY or os.environ.get("OPENROUTER_API_KEY", "")
            url = cfg.OPENROUTER_STT_URL
            headers = cfg.openrouter_headers()
        except Exception:
            model = "openai/whisper-large-v3"
            key = os.environ.get("OPENROUTER_API_KEY", "")
            url = "https://openrouter.ai/api/v1/audio/transcriptions"
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
        if not key:
            return self._fail_stt("no openrouter key")
        print(f"[OR] Recognizing speech (lang={lang})...")
        start_time = time.time()
        wav_path = self._save_wav(audio_data)
        try:
            import requests
            with open(wav_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            resp = requests.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "language": lang,
                    "input_audio": {"data": b64, "format": "wav"},
                },
                timeout=15,
            )
            if resp.status_code >= 400:
                detail = ""
                try:
                    body = resp.json()
                    err = body.get("error") if isinstance(body, dict) else None
                    if isinstance(err, dict):
                        detail = str(err.get("message") or "")[:200]
                    elif isinstance(body, dict):
                        detail = str(body.get("message") or "")[:200]
                except Exception:
                    detail = (resp.text or "")[:120]
                print(f"[OR] HTTP {resp.status_code}: {detail}")
                return self._fail_stt(f"HTTP {resp.status_code}")
            result = resp.json()
            if isinstance(result, dict) and result.get("error"):
                err = result.get("error")
                detail = err.get("message") if isinstance(err, dict) else str(err)
                print(f"[OR] API error: {str(detail)[:200]}")
                return self._fail_stt("api error")
            transcription = (result.get("text") or "").strip() if isinstance(result, dict) else ""
            elapsed = time.time() - start_time
            print(f"[OR] Recognized in {elapsed:.1f}s: '{transcription}'")
            return self._finish_transcript(transcription, "OR")
        except Exception as e:
            print(f"[OR] Error: {e}")
            return self._fail_stt(str(e)[:120])
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def _transcribe_audio(self, audio_data):
        backend = self._stt_backend()
        if backend == "openrouter":
            return self._transcribe_openrouter(audio_data)
        if backend == "groq":
            return self._transcribe_groq(audio_data)
        print("[VOICE] No Groq or OpenRouter key. Voice recognition is off.")
        return self._fail_stt("no stt key")

    def _emit_transcription(self, transcription, epoch, started_at=None):
        if not transcription:
            return
        transcription = strip_prompt_leak(transcription)
        if not transcription:
            return
        if epoch != getattr(self, "_listen_epoch", 0):
            print(f"[MIC] Dropped stale STT: '{transcription}'")
            return
        if is_own_voice_echo(transcription):
            print(f"[MIC] Dropped echo of own voice: '{transcription}'")
            return
        if is_repeat_command(transcription):
            print(f"[MIC] Dropped repeat command: '{transcription}'")
            return
        if drop_speaker_media(transcription):
            print(f"[MIC] Dropped ambient media: '{transcription}'")
            return
        if is_tts_tail_capture(started_at) and not looks_like_barge_in(transcription):
            print(f"[MIC] Dropped TTS tail: '{transcription}'")
            return
        if is_tts_tail_echo(transcription, started_at) and not looks_like_barge_in(transcription):
            print(f"[MIC] Dropped her last words: '{transcription}'")
            return
        if looks_like_barge_in(transcription):
            try:
                from services.tts import stop_speaking
                stop_speaking()
            except Exception:
                pass
        remember_heard(transcription)
        self.last_transcription = transcription
        print(f"[VOICE CMD] {transcription}")
        self.text_queue.put(transcription)
        if self.callback:
            self.callback(transcription)

    def process_audio_queue(self):
        while self.is_running:
            try:
                item = self.audio_queue.get(timeout=0.05)
                started_at = None
                if isinstance(item, tuple):
                    audio_data = item[0]
                    epoch = item[1] if len(item) > 1 else getattr(self, "_listen_epoch", 0)
                    started_at = item[2] if len(item) > 2 else None
                else:
                    audio_data = item
                    epoch = getattr(self, "_listen_epoch", 0)

                for fut in self.futures:
                    future = fut[0] if isinstance(fut, tuple) else fut
                    if not future.done():
                        future.cancel()

                future = self.executor.submit(self._transcribe_audio, audio_data)
                self.futures = [(future, epoch, started_at)]

                completed_futures = []
                for row in self.futures:
                    future, captured_epoch = row[0], row[1]
                    captured_start = row[2] if len(row) > 2 else None
                    if future.done():
                        try:
                            self._emit_transcription(future.result(), captured_epoch, captured_start)
                        except Exception as e:
                            print(f"Recognition error: {e}")
                            self._fail_stt(str(e)[:120])
                        completed_futures.append(row)
                self.futures = [f for f in self.futures if f not in completed_futures]
                self.audio_queue.task_done()

            except queue.Empty:
                completed_futures = []
                for row in list(self.futures):
                    future, captured_epoch = row[0], row[1]
                    captured_start = row[2] if len(row) > 2 else None
                    if future.done():
                        try:
                            self._emit_transcription(future.result(), captured_epoch, captured_start)
                        except Exception as e:
                            print(f"Recognition error: {e}")
                            self._fail_stt(str(e)[:120])
                        completed_futures.append(row)
                self.futures = [f for f in self.futures if f not in completed_futures]
                continue
            except Exception as e:
                print(f"Audio processing error: {e}")
                self._fail_stt(str(e)[:120])

    def start(self):
        global _active_processor
        if self.is_running:
            return

        _active_processor = self
        self.is_running = True
        self.futures = []
        self.thread = threading.Thread(target=self.process_audio_queue)
        self.thread.daemon = True
        self.thread.start()

        with self._io_lock:
            best_device = self._find_best_input_device()
            self.input_device_id = best_device
            try:
                name = sd.query_devices(best_device)["name"]
            except Exception:
                name = "?"
            print(f"[MIC] Using device [{best_device}] @ {self.capture_rate} Hz: {name}")
            try:
                self.stream = self._open_input_stream(best_device)
                self.stream.start()
            except Exception as e:
                print(f"[MIC] Failed with selected device: {e}, trying next...")
                fallback = self._find_best_input_device(exclude={best_device})
                self.input_device_id = fallback
                self.stream = self._open_input_stream(fallback)
                self.stream.start()
        self._sync_speaker_tap()
        print("[MIC] Listening... Speak now!")

    def stop(self):
        global _active_processor
        if _active_processor is self:
            _active_processor = None
        if not self.is_running:
            return
        self.is_running = False
        with getattr(self, "_io_lock", threading.Lock()):
            if hasattr(self, 'stream'):
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                try:
                    del self.stream
                except Exception:
                    pass
        try:
            from services.speaker_tap import stop as _tap_stop
            _tap_stop()
        except Exception:
            pass
        if self.executor:
            self.executor.shutdown(wait=False)
            for item in self.futures:
                future = item[0] if isinstance(item, tuple) else item
                future.cancel()
        if self.thread:
            self.thread.join(timeout=2.0)
        print("[MIC] Microphone closed.")

    def get_transcription(self, block=False, timeout=None):
        try:
            return self.text_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None

    def get_all_transcriptions(self):
        transcriptions = []
        while not self.text_queue.empty():
            transcriptions.append(self.text_queue.get())
        return transcriptions

    def is_processing(self):
        return self.processing_indicator

    def get_audio_level(self):
        return self.current_audio_level

    def get_last_transcription(self):
        return self.last_transcription

    def change_device(self, device_index):
        with self._io_lock:
            return self._change_device_locked(device_index)

    def _change_device_locked(self, device_index):
        if device_index == getattr(self, "input_device_id", None) and hasattr(self, "stream"):
            return True
        previous = getattr(self, "input_device_id", None)
        try:
            if hasattr(self, 'stream'):
                self.stream.stop()
                self.stream.close()
                del self.stream
            self.audio_chunks = []
            self.is_recording = False
            self.current_audio_level = 0.0
            time.sleep(0.1)
            self.stream = self._open_input_stream(device_index)
            if self.is_running:
                self.stream.start()
            self.input_device_id = device_index
            dev_name = sd.query_devices(device_index)['name']
            print(f"[MIC] Switched to: {dev_name} @ {self.capture_rate} Hz")
            self._sync_speaker_tap()
            return True
        except Exception as e:
            print(f"[MIC] Device switch failed: {e}")
            restore = previous if previous is not None and previous != device_index else None
            if restore is None:
                restore = self._find_best_input_device(exclude={device_index})
            try:
                self.stream = self._open_input_stream(restore)
                if self.is_running:
                    self.stream.start()
                self.input_device_id = restore
            except Exception as e2:
                print(f"[MIC] Restore failed: {e2}")
            return False

    def rescan_devices(self):
        """Re-init PortAudio so a Bluetooth mic that just connected appears. Keep the current mic if it still exists."""
        keep_fp = None
        with self._io_lock:
            try:
                if getattr(self, "input_device_id", None) is not None:
                    raw = sd.query_devices(self.input_device_id)["name"]
                    keep_fp = mic_fingerprint(mic_display_name(raw) or raw)
            except Exception:
                keep_fp = None
            try:
                if hasattr(self, "stream"):
                    try:
                        self.stream.stop()
                        self.stream.close()
                    except Exception:
                        pass
                    try:
                        del self.stream
                    except Exception:
                        pass
            except Exception:
                pass
            refresh_portaudio()
            target = None
            mics = list_user_mics()
            if keep_fp:
                for dev_id, name in mics:
                    if fingerprints_match(mic_fingerprint(name), keep_fp):
                        target = dev_id
                        break
            if target is None:
                target = self._find_best_input_device()
            try:
                self.stream = self._open_input_stream(target)
                if self.is_running:
                    self.stream.start()
                self.input_device_id = target
            except Exception as e:
                print(f"[MIC] Rescan reopen failed: {e}")
                try:
                    fallback = self._find_best_input_device(exclude={target} if target is not None else set())
                    self.stream = self._open_input_stream(fallback)
                    if self.is_running:
                        self.stream.start()
                    self.input_device_id = fallback
                except Exception as e2:
                    print(f"[MIC] Rescan restore failed: {e2}")
            return mics

    def _open_input_stream(self, dev_id):
        last_err = None
        for rate in (16000, 48000, 44100, 8000):
            try:
                stream = sd.InputStream(
                    callback=self.audio_callback,
                    channels=1,
                    samplerate=rate,
                    blocksize=int(rate * 0.2),
                    device=dev_id,
                )
                self.capture_rate = rate
                return stream
            except Exception as e:
                last_err = e
        raise last_err or RuntimeError("no input rate worked")

    def _device_opens(self, dev_id):
        for rate in (16000, 48000, 44100, 8000):
            try:
                stream = sd.InputStream(
                    device=dev_id,
                    channels=1,
                    samplerate=rate,
                    blocksize=int(rate * 0.2),
                    callback=lambda *a: None,
                )
                stream.start()
                time.sleep(0.05)
                stream.stop()
                stream.close()
                return rate
            except Exception:
                continue
        return None

    def _find_best_input_device(self, exclude=None):
        """Windows default mic first. Skip junk and duplicates."""
        exclude = set(exclude or ())
        mics = list_user_mics()
        default_id = default_input_id()
        ordered = []
        if default_id is not None:
            for dev_id, name in mics:
                if dev_id == default_id and dev_id not in exclude:
                    ordered.append((dev_id, name, True))
                    break
        for dev_id, name in mics:
            if dev_id in exclude:
                continue
            if ordered and ordered[0][0] == dev_id:
                continue
            ordered.append((dev_id, name, False))
        for dev_id, name, is_default in ordered:
            rate = self._device_opens(dev_id)
            if not rate:
                print(f"[MIC] Skip (won't open): [{dev_id}] {name}")
                continue
            self.capture_rate = rate
            tag = "Windows default" if is_default else "fallback"
            print(f"[MIC] Picked [{dev_id}] {name} @ {rate} Hz ({tag})")
            return dev_id
        fallback = default_id if default_id is not None else sd.default.device[0]
        print(f"[MIC] Falling back to [{fallback}]")
        return fallback

    @staticmethod
    def list_input_devices():
        devices = []
        for i, d in enumerate(sd.query_devices()):
            if d['max_input_channels'] > 0:
                devices.append((i, d['name']))
        return devices
