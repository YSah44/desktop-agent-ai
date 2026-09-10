"""Capture what the speakers are playing so the mic can ignore it.

Uses Stereo Mix / loopback when Windows exposes it. Voice input subtracts
that mix from the microphone so lyrics do not become commands.
"""
import threading
import time

import numpy as np

_REF_MARKERS = (
    "stereo mix", "what u hear", "wave out", "loopback",
    "mixed output", "mix (realtek",
)

_lock = threading.Lock()
_stream = None
_thread_ok = False
_ring = np.zeros(0, dtype=np.float32)
_rate = 48000
_device = None
_on = False


def echo_cancel_enabled():
    try:
        from config import ECHO_CANCEL
        return bool(ECHO_CANCEL)
    except Exception:
        import os
        return os.environ.get("DAVI_ECHO_CANCEL", "1") != "0"


def set_echo_cancel(on):
    import os
    os.environ["DAVI_ECHO_CANCEL"] = "1" if on else "0"
    try:
        import config
        config.ECHO_CANCEL = bool(on)
    except Exception:
        pass
    if on:
        start()
    else:
        stop()
    return bool(on)


def _is_ref_name(name):
    n = (name or "").lower().replace("\n", " ")
    return any(m in n for m in _REF_MARKERS)


def find_ref_device(exclude=None):
    """WASAPI Stereo Mix / loopback, never the user's chosen mic."""
    import sounddevice as sd
    exclude = set(exclude or ())
    try:
        devices = list(sd.query_devices())
        hostapis = list(sd.query_hostapis())
    except Exception:
        return None
    scored = []
    for i, d in enumerate(devices):
        if i in exclude:
            continue
        if int(d.get("max_input_channels") or 0) < 1:
            continue
        if not _is_ref_name(d.get("name") or ""):
            continue
        host = hostapis[int(d.get("hostapi") or 0)]["name"] if hostapis else ""
        score = 2 if "wasapi" in host.lower() else 1
        scored.append((score, i, d.get("name") or ""))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def _resample(audio, src, dst):
    if audio is None or len(audio) < 2 or src == dst:
        return audio
    src_len = len(audio)
    dst_len = max(2, int(round(src_len * dst / float(src))))
    x_old = np.linspace(0.0, 1.0, src_len, endpoint=False)
    x_new = np.linspace(0.0, 1.0, dst_len, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def cancel_echo(mic, ref, sr=16000, max_lag_sec=0.12):
    """Subtract a delayed/scaled speaker mix from a mic block. Returns (out, similarity)."""
    mic = np.asarray(mic, dtype=np.float32).reshape(-1)
    if ref is None:
        return mic, 0.0
    ref = np.asarray(ref, dtype=np.float32).reshape(-1)
    n = len(mic)
    if n < 32 or len(ref) < n:
        return mic, 0.0
    max_lag = min(len(ref) - n, max(1, int(sr * float(max_lag_sec))))
    step = max(1, int(sr * 0.004))
    mic_n = float(np.linalg.norm(mic)) + 1e-8

    def _corr(lag):
        end = len(ref) - lag
        start = end - n
        if start < 0:
            return 0.0, None
        chunk = ref[start:end]
        denom = (mic_n * (float(np.linalg.norm(chunk)) + 1e-8))
        return float(np.dot(mic, chunk)) / denom, chunk

    best_c, best_lag, best_chunk = 0.0, 0, None
    for lag in range(0, max_lag, step):
        c, chunk = _corr(lag)
        if chunk is None:
            break
        if abs(c) > abs(best_c):
            best_c, best_lag, best_chunk = c, lag, chunk
    lo = max(0, best_lag - step)
    hi = min(max_lag, best_lag + step)
    for lag in range(lo, hi + 1):
        c, chunk = _corr(lag)
        if chunk is None:
            continue
        if abs(c) > abs(best_c):
            best_c, best_lag, best_chunk = c, lag, chunk
    chunk = best_chunk
    if chunk is None:
        return mic, 0.0
    energy = float(np.dot(chunk, chunk)) + 1e-8
    gain = float(np.dot(mic, chunk)) / energy
    if abs(best_c) < 0.22 or gain < 0.04:
        return mic, abs(best_c)
    gain = float(np.clip(gain, 0.0, 1.7))
    out = mic - gain * chunk
    return out.astype(np.float32), abs(best_c)


def _callback(indata, frames, time_info, status):
    global _ring
    audio = indata.copy()
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    audio = audio.reshape(-1).astype(np.float32)
    with _lock:
        if _ring.size == 0:
            return
        n = len(audio)
        if n >= len(_ring):
            _ring[:] = audio[-len(_ring):]
        else:
            _ring[:-n] = _ring[n:]
            _ring[-n:] = audio


def start(exclude_mic=None):
    global _stream, _thread_ok, _ring, _rate, _device, _on
    if not echo_cancel_enabled():
        stop()
        return False
    import sounddevice as sd
    dev = find_ref_device(exclude=exclude_mic)
    if dev is None:
        print("[MIC] No speaker mix device — louder-voice filter still on")
        stop()
        return False
    if _on and _device == dev and _stream is not None:
        return True
    stop()
    last_err = None
    for rate in (48000, 44100, 16000):
        try:
            extra = None
            try:
                extra = sd.WasapiSettings(auto_convert=True)
            except Exception:
                extra = None
            kwargs = dict(
                callback=_callback,
                channels=1,
                samplerate=rate,
                blocksize=int(rate * 0.2),
                device=dev,
            )
            try:
                stream = sd.InputStream(extra_settings=extra, **kwargs) if extra else sd.InputStream(**kwargs)
            except Exception:
                stream = sd.InputStream(**kwargs)
            stream.start()
            with _lock:
                _rate = rate
                _ring = np.zeros(int(rate * 0.28), dtype=np.float32)
                _device = dev
                _stream = stream
                _on = True
            try:
                name = sd.query_devices(dev)["name"]
            except Exception:
                name = str(dev)
            print(f"[MIC] Ignoring speakers via [{dev}] {name}")
            return True
        except Exception as e:
            last_err = e
    print(f"[MIC] Speaker mix open failed: {last_err}")
    return False


def stop():
    global _stream, _on, _device
    stream = None
    with _lock:
        stream = _stream
        _stream = None
        _on = False
        _device = None
    if stream is not None:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass


def latest(n, rate):
    """Last n samples resampled to `rate`, or None."""
    with _lock:
        if not _on or _ring.size == 0 or n < 8:
            return None
        src = _ring.copy()
        src_rate = int(_rate or 48000)
    if src_rate != rate:
        src = _resample(src, src_rate, rate)
    if src is None or len(src) < n:
        return None
    return src[-n:]
