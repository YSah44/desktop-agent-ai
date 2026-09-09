import edge_tts
import asyncio
import tempfile
import os
import threading
import time

VOICE = "en-US-JennyNeural"
_tts_lock = threading.Lock()
_loop = None
is_speaking = False
is_playing = False
last_ended_at = 0.0
_mixer_ready = False
_speak_gen = 0
_gen_lock = threading.Lock()
_jobs = 0
_jobs_lock = threading.Lock()
_play_started = 0.0
_play_est_sec = 0.0

try:
    from config import TTS_ENABLED, TTS_RATE, TTS_VOLUME
except Exception:
    TTS_ENABLED, TTS_RATE, TTS_VOLUME = True, 0, 100

enabled = bool(TTS_ENABLED)
rate = int(TTS_RATE)      # percent offset applied to the neural voice
volume = int(TTS_VOLUME)  # 0-100, applied at playback


def configure(enabled_=None, rate_=None, volume_=None):
    """Live-update speech settings; takes effect on the next utterance."""
    global enabled, rate, volume
    if enabled_ is not None:
        enabled = bool(enabled_)
        if not enabled:
            stop_speaking()
    if rate_ is not None:
        rate = max(-50, min(50, int(rate_)))
    if volume_ is not None:
        volume = max(0, min(100, int(volume_)))


def _current_voice():
    try:
        from services.i18n import current_tts_voice
        return current_tts_voice()
    except Exception:
        return VOICE


def _init_mixer():
    global _mixer_ready
    if _mixer_ready:
        return True
    try:
        import pygame
        pygame.mixer.init(frequency=24000)
        _mixer_ready = True
        return True
    except Exception as e:
        print(f"[TTS] Mixer init failed: {e}")
        return False


def _get_loop():
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


async def _generate_audio(text, output_path):
    communicate = edge_tts.Communicate(text, _current_voice(), rate=f"{rate:+d}%")
    await communicate.save(output_path)


def stop_speaking():
    """Barge-in: stop current TTS immediately so a new user utterance can be heard."""
    global is_speaking, is_playing, last_ended_at, _speak_gen, _jobs
    with _gen_lock:
        _speak_gen += 1
    with _jobs_lock:
        _jobs = 0
    was = is_speaking
    is_speaking = False
    is_playing = False
    if was:
        last_ended_at = time.time()
        _flush_mic_after_tts()
    try:
        import pygame
        if _mixer_ready:
            pygame.mixer.music.stop()
    except Exception:
        pass


def playback_ended_at():
    return float(last_ended_at or 0.0)


def _estimate_speech_sec(text):
    n = max(1, len((text or "").strip()))
    speed = 13.5 * (1.0 + float(rate) / 100.0)
    return max(0.9, n / max(8.0, speed))


def playback_progress():
    """How far through the current utterance we are, 0..1. Overlay uses this
    to keep the spoken line in view."""
    if not is_playing:
        return 0.0 if is_speaking else 1.0
    est = max(float(_play_est_sec or 0.0), 0.4)
    try:
        import pygame
        if _mixer_ready:
            pos = pygame.mixer.music.get_pos()
            if isinstance(pos, (int, float)) and pos >= 0:
                return min(0.99, (pos / 1000.0) / est)
    except Exception:
        pass
    if _play_started:
        return min(0.99, (time.time() - _play_started) / est)
    return 0.0


def playback_length():
    """Length of the current audible utterance in seconds. 0 when idle."""
    return float(_play_est_sec or 0.0) if is_playing else 0.0


def playback_remaining():
    """Seconds left in the current audible utterance. 0 when idle."""
    if not is_playing:
        return 9.0 if is_speaking else 0.0
    est = max(float(_play_est_sec or 0.0), 0.4)
    try:
        import pygame
        if _mixer_ready:
            pos = pygame.mixer.music.get_pos()
            if isinstance(pos, (int, float)) and pos >= 0:
                return max(0.0, est - (pos / 1000.0))
    except Exception:
        pass
    if _play_started:
        return max(0.0, est - (time.time() - _play_started))
    return est


def _flush_mic_after_tts():
    try:
        from services.voice_input import notify_tts_ended
        notify_tts_ended()
    except Exception:
        pass


def _mark_tts_started():
    try:
        from services.voice_input import notify_tts_started
        notify_tts_started()
    except Exception:
        pass


def speak(text):
    global is_speaking, _jobs
    if not enabled:
        return
    if not text or len(text.strip()) < 2:
        return
    try:
        from services.daily import remember_spoken
        remember_spoken(text)
    except Exception:
        pass
    try:
        from services.busy_audio import peek_busy
        from services.voice_input import ptt_is_down
        if peek_busy() == "meeting" and not ptt_is_down():
            print("[TTS] Quiet — meeting")
            return
    except Exception:
        pass

    with _gen_lock:
        my_gen = _speak_gen
    with _jobs_lock:
        _jobs += 1
        is_speaking = True
    _mark_tts_started()

    def _do_speak():
        global is_speaking, is_playing, last_ended_at, _jobs, _play_started, _play_est_sec
        with _tts_lock:
            if my_gen != _speak_gen:
                with _jobs_lock:
                    _jobs = max(0, _jobs - 1)
                return
            is_speaking = True
            is_playing = False
            tmp = os.path.join(tempfile.gettempdir(), "agent_tts.mp3")
            try:
                loop = _get_loop()
                loop.run_until_complete(_generate_audio(text, tmp))

                if my_gen != _speak_gen:
                    return

                if not os.path.exists(tmp) or os.path.getsize(tmp) < 100:
                    print("[TTS] Audio file too small or missing")
                    return

                if not _init_mixer():
                    return

                if my_gen != _speak_gen:
                    return

                import pygame
                pygame.mixer.music.load(tmp)
                pygame.mixer.music.set_volume(max(0.0, min(1.0, volume / 100.0)))
                try:
                    _play_est_sec = float(pygame.mixer.Sound(tmp).get_length() or 0.0)
                except Exception:
                    _play_est_sec = 0.0
                if _play_est_sec < 0.25:
                    _play_est_sec = _estimate_speech_sec(text)
                pygame.mixer.music.play()
                # Mouth follows audible playback, not the Edge TTS download.
                deadline = time.time() + 0.75
                while time.time() < deadline:
                    if my_gen != _speak_gen:
                        break
                    try:
                        pos = pygame.mixer.music.get_pos()
                        busy = pygame.mixer.music.get_busy()
                    except Exception:
                        pos, busy = -1, False
                    if busy and isinstance(pos, (int, float)) and pos >= 35:
                        break
                    time.sleep(0.01)
                if my_gen == _speak_gen:
                    try:
                        audible = pygame.mixer.music.get_busy()
                    except Exception:
                        audible = False
                    if audible:
                        is_playing = True
                        _play_started = time.time()
                while pygame.mixer.music.get_busy():
                    if my_gen != _speak_gen:
                        try:
                            pygame.mixer.music.stop()
                        except Exception:
                            pass
                        break
                    time.sleep(0.05)
                # Tiny mixer drain only. Mic preroll trim + 40ms slop covers BT lag.
                if my_gen == _speak_gen:
                    time.sleep(0.02)
            except Exception as e:
                print(f"[TTS] Error: {e}")
            finally:
                is_playing = False
                with _jobs_lock:
                    _jobs = max(0, _jobs - 1)
                    still = _jobs > 0
                if my_gen == _speak_gen and not still:
                    last_ended_at = time.time()
                    is_speaking = False
                    _flush_mic_after_tts()
                elif still:
                    is_speaking = True
                try:
                    import pygame
                    pygame.mixer.music.unload()
                except Exception:
                    pass
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    t = threading.Thread(target=_do_speak, daemon=True)
    t.start()
    return t


def set_voice(voice_name):
    global VOICE
    VOICE = voice_name
