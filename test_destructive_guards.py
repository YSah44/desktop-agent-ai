"""Slice 6 guards: destructive OS actions must never run in tests.

Live empty_recycle / delete_file / shutdown_pc require confirmed=True.
Native APIs are mocked. Slice 5 emptied the Recycle Bin by calling the live
confirm path — this file must not repeat that.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ["DAVI_DISABLE_DESTRUCTIVE"] = "1"


class DestructiveGuardTests(unittest.TestCase):
    def setUp(self):
        os.environ["DAVI_DISABLE_DESTRUCTIVE"] = "1"
        import services.smart_features as sf
        sf._empty_recycle_pending_until = 0.0
        sf._restart_pc_pending_until = 0.0

    def tearDown(self):
        os.environ["DAVI_DISABLE_DESTRUCTIVE"] = "1"

    def test_unconfirmed_ops_refuse_without_native(self):
        from services.windows_ops import empty_recycle, delete_file, shutdown_pc
        with patch("services.windows_ops.ctypes.windll.shell32.SHEmptyRecycleBinW") as bin_m, \
                patch("services.windows_ops.subprocess.Popen") as pop_m, \
                patch("services.windows_ops.subprocess.run") as run_m:
            for fn, args in (
                (empty_recycle, ()),
                (delete_file, ("C:\\nope.txt",)),
                (shutdown_pc, ()),
            ):
                r = fn(*args)
                self.assertFalse(r.get("success"), fn.__name__)
                msg = (r.get("message") or "").lower()
                self.assertTrue("confirmed" in msg or "disabled" in msg, msg)
            bin_m.assert_not_called()
            pop_m.assert_not_called()
            run_m.assert_not_called()

    def test_unconfirmed_without_disable_env_still_refuses(self):
        os.environ.pop("DAVI_DISABLE_DESTRUCTIVE", None)
        from services.windows_ops import empty_recycle, delete_file, shutdown_pc
        with patch("services.windows_ops.ctypes.windll.shell32.SHEmptyRecycleBinW") as bin_m, \
                patch("services.windows_ops.subprocess.Popen") as pop_m, \
                patch("services.windows_ops.subprocess.run") as run_m:
            er = empty_recycle()
            df = delete_file("C:\\nope.txt")
            sd = shutdown_pc()
            self.assertFalse(er.get("success"))
            self.assertIn("confirmed", (er.get("message") or "").lower())
            self.assertFalse(df.get("success"))
            self.assertIn("confirmed", (df.get("message") or "").lower())
            self.assertFalse(sd.get("success"))
            self.assertIn("confirmed", (sd.get("message") or "").lower())
            bin_m.assert_not_called()
            pop_m.assert_not_called()
            run_m.assert_not_called()

    def test_desktop_commands_refuse_without_confirmed(self):
        from services.desktop_commands import handle
        for name in ("empty_recycle", "shutdown_pc", "delete_file"):
            r = handle({"command": name, "params": {}})
            self.assertFalse(r.get("success"), name)
            self.assertIn("confirmed", (r.get("message") or "").lower())

    def test_desktop_commands_confirmed_calls_mocked_ops(self):
        from services import desktop_commands as dc
        with patch.object(dc, "empty_recycle", return_value={"success": True, "message": "mocked"}) as m:
            r = dc.handle({"command": "empty_recycle", "params": {"confirmed": True}})
            self.assertTrue(r.get("success"))
            m.assert_called_once_with(confirmed=True)
        with patch.object(dc, "delete_file", return_value={"success": True, "message": "mocked"}) as m:
            r = dc.handle({"command": "delete_file", "params": {"path": "x", "confirmed": True}})
            self.assertTrue(r.get("success"))
            m.assert_called_once()
            self.assertTrue(m.call_args.kwargs.get("confirmed"))
        with patch.object(dc, "shutdown_pc", return_value={"success": True, "message": "mocked"}) as m:
            r = dc.handle({"command": "shutdown_pc", "params": {"confirmed": True, "mode": "shutdown"}})
            self.assertTrue(r.get("success"))
            m.assert_called_once()
            self.assertTrue(m.call_args.kwargs.get("confirmed"))

    def test_voice_empty_recycle_confirm_is_mocked(self):
        from services.smart_features import handle_empty_recycle_voice, match_empty_recycle, match_fast_desktop
        self.assertTrue(match_empty_recycle("empty recycle"))
        self.assertTrue(match_empty_recycle("geri donusumu bosalt"))
        self.assertFalse(match_empty_recycle("open recycle bin"))
        self.assertIsNone(match_fast_desktop("empty recycle"))
        ask = handle_empty_recycle_voice("empty recycle")
        self.assertEqual(ask[0], "ask")
        with patch("services.windows_ops.empty_recycle", return_value={"success": True, "message": "mocked"}) as m:
            kind, payload = handle_empty_recycle_voice("confirm")
            self.assertEqual(kind, "do")
            self.assertEqual(payload.get("message"), "mocked")
            m.assert_called_once_with(confirmed=True)

    def test_confirmed_empty_recycle_hits_mock_not_real_bin(self):
        os.environ.pop("DAVI_DISABLE_DESTRUCTIVE", None)
        from services.windows_ops import empty_recycle
        with patch("services.windows_ops.ctypes.windll.shell32.SHEmptyRecycleBinW", return_value=0) as m:
            r = empty_recycle(confirmed=True)
            self.assertTrue(r.get("success"))
            m.assert_called_once()

    def test_confirmed_shutdown_hits_popen_mock(self):
        os.environ.pop("DAVI_DISABLE_DESTRUCTIVE", None)
        from services.windows_ops import shutdown_pc
        with patch("services.windows_ops.subprocess.Popen", return_value=MagicMock()) as m:
            r = shutdown_pc(confirmed=True)
            self.assertTrue(r.get("success"))
            m.assert_called_once()


class FastFolderVoiceTests(unittest.TestCase):
    def test_documents_and_desktop_folder(self):
        from services.smart_features import match_fast_desktop, match_fast_open_app
        self.assertEqual(match_fast_desktop("open documents"), "documents")
        self.assertEqual(match_fast_desktop("documents folder"), "documents")
        self.assertEqual(match_fast_desktop("belgeler"), "documents")
        self.assertEqual(match_fast_desktop("belgeleri ac"), "documents")
        self.assertEqual(match_fast_desktop("open desktop folder"), "desktop_folder")
        self.assertEqual(match_fast_desktop("desktop folder"), "desktop_folder")
        self.assertEqual(match_fast_desktop("open desktop"), "desktop_folder")
        self.assertEqual(match_fast_desktop("masaustu klasoru"), "desktop_folder")
        self.assertEqual(match_fast_desktop("show desktop"), "desktop")
        self.assertIsNone(match_fast_open_app("open documents"))
        self.assertIsNone(match_fast_open_app("belgeler"))
        self.assertIsNone(match_fast_open_app("open desktop folder"))

    def test_pictures_and_music_folder(self):
        from services.smart_features import match_fast_desktop, match_fast_open_app
        self.assertEqual(match_fast_desktop("open pictures"), "pictures")
        self.assertEqual(match_fast_desktop("pictures folder"), "pictures")
        self.assertEqual(match_fast_desktop("resimler"), "pictures")
        self.assertEqual(match_fast_desktop("resimleri ac"), "pictures")
        self.assertEqual(match_fast_desktop("fotograflar"), "pictures")
        self.assertEqual(match_fast_desktop("open music"), "music")
        self.assertEqual(match_fast_desktop("music folder"), "music")
        self.assertEqual(match_fast_desktop("muzik"), "music")
        self.assertEqual(match_fast_desktop("muzik klasoru"), "music")
        self.assertEqual(match_fast_desktop("play music"), "play_pause")
        self.assertIsNone(match_fast_open_app("open pictures"))
        self.assertIsNone(match_fast_open_app("resimler"))
        self.assertIsNone(match_fast_open_app("open music"))
        self.assertIsNone(match_fast_open_app("muzik klasoru"))


class FastSleepVoiceTests(unittest.TestCase):
    def setUp(self):
        os.environ["DAVI_DISABLE_DESTRUCTIVE"] = "1"

    def tearDown(self):
        os.environ["DAVI_DISABLE_DESTRUCTIVE"] = "1"

    def test_sleep_phrases_not_shutdown_or_quit(self):
        from services.smart_features import match_fast_desktop, match_sleep_pc, match_fast_open_app
        self.assertTrue(match_sleep_pc("sleep pc"))
        self.assertTrue(match_sleep_pc("bilgisayarı uyut"))
        self.assertEqual(match_fast_desktop("sleep pc"), "sleep")
        self.assertEqual(match_fast_desktop("Sleep PC"), "sleep")
        self.assertEqual(match_fast_desktop("bilgisayarı uyut"), "sleep")
        self.assertEqual(match_fast_desktop("bilgisayari uyut lutfen"), "sleep")
        self.assertFalse(match_sleep_pc("shutdown pc"))
        self.assertFalse(match_sleep_pc("shut down"))
        self.assertFalse(match_sleep_pc("bilgisayarı kapat"))
        self.assertIsNone(match_fast_desktop("shutdown pc"))
        self.assertEqual(match_fast_desktop("stop"), "stop_talking")
        self.assertEqual(match_fast_desktop("dur"), "stop_talking")
        self.assertIsNone(match_fast_desktop("kapat"))
        self.assertIsNone(match_fast_open_app("sleep pc"))
        self.assertIsNone(match_fast_open_app("bilgisayarı uyut"))

    def test_fast_sleep_calls_sleep_mode_mocked(self):
        from services.smart_features import run_fast_desktop
        with patch("services.windows_ops.shutdown_pc", return_value={"success": True, "message": "Sleep requested"}) as m:
            ok, key, extra = run_fast_desktop("sleep")
            self.assertTrue(ok)
            self.assertEqual(key, "sleep_done")
            m.assert_called_once()
            kwargs = m.call_args.kwargs
            args = m.call_args.args
            mode = kwargs.get("mode") if "mode" in kwargs else (args[0] if args else "")
            self.assertEqual(mode, "sleep")
            self.assertTrue(kwargs.get("confirmed", False))

    def test_confirmed_sleep_is_powrprof_not_shutdown_s(self):
        os.environ.pop("DAVI_DISABLE_DESTRUCTIVE", None)
        from services.windows_ops import shutdown_pc
        with patch("services.windows_ops.subprocess.Popen", return_value=MagicMock()) as m:
            r = shutdown_pc(mode="sleep", confirmed=True)
            self.assertTrue(r.get("success"))
            cmd = m.call_args[0][0]
            joined = " ".join(str(x) for x in cmd).lower()
            self.assertIn("powrprof", joined)
            self.assertNotIn("/s", joined)


class FastRestartVoiceTests(unittest.TestCase):
    def setUp(self):
        os.environ["DAVI_DISABLE_DESTRUCTIVE"] = "1"
        import services.smart_features as sf
        sf._restart_pc_pending_until = 0.0
        sf._empty_recycle_pending_until = 0.0

    def tearDown(self):
        os.environ["DAVI_DISABLE_DESTRUCTIVE"] = "1"
        import services.smart_features as sf
        sf._restart_pc_pending_until = 0.0

    def test_restart_davi_is_not_windows_reboot(self):
        from services.smart_features import (
            match_restart_davi, match_restart_pc, match_fast_desktop,
            match_fast_open_app, handle_restart_pc_voice, match_sleep_pc,
        )
        for phrase in (
            "restart davi", "restart davı", "Restart DAVI", "restart aemyos",
            "daviyi yeniden başlat", "davi yi yeniden baslat",
            "reboot davi", "restart davey",
        ):
            self.assertTrue(match_restart_davi(phrase), phrase)
            self.assertFalse(match_restart_pc(phrase), phrase)
            self.assertIsNone(match_fast_desktop(phrase), phrase)
            self.assertIsNone(match_fast_open_app(phrase), phrase)
            self.assertFalse(match_sleep_pc(phrase), phrase)
        with patch("services.windows_ops.shutdown_pc") as m:
            self.assertIsNone(handle_restart_pc_voice("restart davi"))
            self.assertIsNone(handle_restart_pc_voice("restart davı"))
            m.assert_not_called()

    def test_restart_computer_needs_confirm_mocked(self):
        from services.smart_features import (
            match_restart_pc, match_restart_davi, match_fast_desktop,
            handle_restart_pc_voice,
        )
        self.assertTrue(match_restart_pc("restart the computer"))
        self.assertTrue(match_restart_pc("bilgisayarı yeniden başlat"))
        self.assertTrue(match_restart_pc("Restart the computer please"))
        self.assertFalse(match_restart_davi("restart the computer"))
        self.assertFalse(match_restart_davi("bilgisayarı yeniden başlat"))
        self.assertIsNone(match_fast_desktop("restart the computer"))
        ask = handle_restart_pc_voice("restart the computer")
        self.assertEqual(ask[0], "ask")
        with patch("services.windows_ops.shutdown_pc", return_value={"success": True, "message": "mocked"}) as m:
            kind, payload = handle_restart_pc_voice("confirm")
            self.assertEqual(kind, "do")
            self.assertEqual(payload.get("message"), "mocked")
            m.assert_called_once()
            self.assertEqual(m.call_args.kwargs.get("mode"), "restart")
            self.assertTrue(m.call_args.kwargs.get("confirmed"))

    def test_restart_pc_confirm_not_empty_recycle_word(self):
        from services.smart_features import handle_restart_pc_voice
        handle_restart_pc_voice("bilgisayarı yeniden başlat")
        with patch("services.windows_ops.shutdown_pc") as m:
            self.assertIsNone(handle_restart_pc_voice("bosalt"))
            m.assert_not_called()

    def test_confirmed_restart_hits_shutdown_r_mock(self):
        os.environ.pop("DAVI_DISABLE_DESTRUCTIVE", None)
        from services.windows_ops import shutdown_pc
        with patch("services.windows_ops.subprocess.Popen", return_value=MagicMock()) as m:
            r = shutdown_pc(mode="restart", confirmed=True)
            self.assertTrue(r.get("success"))
            cmd = m.call_args[0][0]
            joined = " ".join(str(x) for x in cmd).lower()
            self.assertIn("/r", joined)
            self.assertNotIn("/s", joined)


class FastClipboardReadTests(unittest.TestCase):
    def test_read_clipboard_not_win_v(self):
        from services.smart_features import match_read_clipboard, match_fast_desktop
        self.assertTrue(match_read_clipboard("read clipboard"))
        self.assertTrue(match_read_clipboard("read the clipboard"))
        self.assertTrue(match_read_clipboard("panoyu oku"))
        self.assertTrue(match_read_clipboard("pano oku"))
        self.assertFalse(match_read_clipboard("clipboard"))
        self.assertFalse(match_read_clipboard("pano"))
        self.assertFalse(match_read_clipboard("open clipboard"))
        self.assertEqual(match_fast_desktop("clipboard"), "clipboard")
        self.assertEqual(match_fast_desktop("pano"), "clipboard")
        self.assertIsNone(match_fast_desktop("read clipboard"))
        self.assertIsNone(match_fast_desktop("panoyu oku"))

    def test_clipboard_tts_truncates_to_200(self):
        from services.smart_features import read_clipboard_for_tts
        long = "A" * 500
        with patch("pyperclip.paste", return_value=long):
            out = read_clipboard_for_tts(200)
        self.assertEqual(len(out), 200)
        with patch("pyperclip.paste", return_value="   "):
            with patch("services.smart_features.get_clipboard_history", return_value=[]):
                self.assertEqual(read_clipboard_for_tts(200), "")


class CrashLogTrimTests(unittest.TestCase):
    def test_trim_keeps_tail_drops_head(self):
        import tempfile
        from services.safety import trim_crash_log
        fd, path = tempfile.mkstemp(suffix=".log")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(b"HEAD_DROP\n")
                f.write(b"x" * (2 * 1024 * 1024))
                f.write(b"\nTAIL_KEEP")
            self.assertTrue(trim_crash_log(path, max_bytes=2 * 1024 * 1024, keep_bytes=200 * 1024))
            with open(path, "rb") as f:
                data = f.read()
            self.assertLessEqual(len(data), 200 * 1024)
            self.assertIn(b"TAIL_KEEP", data)
            self.assertNotIn(b"HEAD_DROP", data)
        finally:
            for p in (path, path + ".tmp"):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def test_small_log_not_trimmed(self):
        import tempfile
        from services.safety import trim_crash_log
        fd, path = tempfile.mkstemp(suffix=".log")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(b"small")
            self.assertFalse(trim_crash_log(path, max_bytes=2 * 1024 * 1024, keep_bytes=200 * 1024))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"small")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


class TtsBargeInTests(unittest.TestCase):
    def test_stop_speaking_clears_flag(self):
        import services.tts as tts
        tts.is_speaking = True
        tts.is_playing = True
        tts.stop_speaking()
        self.assertFalse(tts.is_speaking)
        self.assertFalse(tts.is_playing)
        tts.is_speaking = False
        tts.is_playing = False
        self.assertEqual(tts.playback_progress(), 1.0)

    def test_mouth_waits_until_audio_plays(self):
        import services.tts as tts
        tts.is_speaking = True
        tts.is_playing = False
        self.assertEqual(tts.playback_progress(), 0.0)
        tts.is_speaking = False
        tts.is_playing = False
        self.assertEqual(tts.playback_progress(), 1.0)

    def test_loud_speech_does_not_interrupt_tts(self):
        import queue
        import numpy as np
        from collections import deque
        from services.voice_input import VoiceInputProcessor
        dummy = VoiceInputProcessor.__new__(VoiceInputProcessor)
        dummy.sample_rate = 16000
        dummy.capture_rate = 16000
        dummy.vad_threshold = 0.01
        dummy.audio_chunks = ["keep"]
        dummy.is_recording = True
        dummy.current_audio_level = 0.9
        dummy.last_speech_time = 0
        dummy.recording_start_time = 0
        dummy._tts_barge_hits = 0
        dummy._tts_barge_cooldown = 0
        dummy._was_tts = False
        dummy._tts_holdoff_until = 0.0
        dummy._tts_overlap_talk = False
        dummy._awaiting_quiet = False
        dummy._quiet_frames = 0
        dummy._listen_epoch = 0
        dummy._tts_preroll = deque()
        dummy._listen_live_after_tts = False
        dummy.audio_queue = queue.Queue()
        dummy.silence_duration = 2.5
        dummy.max_record_duration = 20.0
        dummy.min_speech_duration = 0.5
        loud = np.ones((3200, 1), dtype=np.float32) * 0.5
        with patch("services.tts.is_speaking", True), \
                patch("services.tts.stop_speaking") as stop:
            for _ in range(12):
                dummy.audio_callback(loud, 3200, None, None)
        stop.assert_not_called()
        self.assertFalse(dummy.is_recording)
        self.assertEqual(dummy.audio_chunks, [])
        self.assertTrue(dummy.audio_queue.empty())
        self.assertGreater(len(dummy._tts_preroll), 0)

    def test_near_field_barge_stops_tts(self):
        import numpy as np
        dummy = self._mic_dummy()
        dummy._was_tts = False
        quiet = np.ones((3200, 1), dtype=np.float32) * 0.08
        loud = np.ones((3200, 1), dtype=np.float32) * 0.45
        with patch("services.tts.is_speaking", True), \
                patch("services.tts.is_playing", False), \
                patch("services.speaker_tap.echo_cancel_enabled", return_value=False), \
                patch("services.tts.stop_speaking") as stop:
            for _ in range(5):
                dummy.audio_callback(quiet, 3200, None, None)
            for _ in range(4):
                dummy.audio_callback(loud, 3200, None, None)
        stop.assert_called()

    def test_prompt_leak_and_repeat_command(self):
        from services import voice_input as vi
        prev = vi._last_heard, vi._last_heard_at
        try:
            vi._last_heard = ""
            vi._last_heard_at = 0.0
            self.assertEqual(
                vi.strip_prompt_leak("What you are seeing in camera right now? Desktop voice"),
                "What you are seeing in camera right now",
            )
            vi.remember_heard("What you are seeing in camera right now.")
            self.assertTrue(vi.is_repeat_command(
                "What you are seeing in camera right now? Desktop voice"))
            self.assertFalse(vi.is_repeat_command("open chrome"))
        finally:
            vi._last_heard, vi._last_heard_at = prev

    def test_echo_of_own_voice_is_detected(self):
        from services.voice_input import is_own_voice_echo, score_input_device
        spoken = "Your desktop has several windows open including Chrome and Cursor."
        self.assertTrue(is_own_voice_echo(
            "desktop has several windows open including Chrome", spoken))
        self.assertFalse(is_own_voice_echo("open chrome", spoken))
        self.assertFalse(is_own_voice_echo(
            "Can you check how many files have on my desktop?", spoken))
        self.assertTrue(is_own_voice_echo("opened whatsapp", "Opened WhatsApp"))
        self.assertFalse(is_own_voice_echo("tamam chrome aç", "Tamam."))
        self.assertLess(
            score_input_device("Headset (Jabra Elite 85h)"),
            score_input_device("Microphone (Live Streamer CAM313 Microphone)"),
        )
        self.assertGreaterEqual(score_input_device("Live Streamer CAM313"), 800)

    def test_tts_tail_capture_is_dropped(self):
        from services.voice_input import is_tts_tail_capture, looks_like_barge_in
        import services.tts as tts
        prev = tts.last_ended_at, tts.is_speaking, getattr(tts, "is_playing", False)
        try:
            tts.is_speaking = False
            tts.is_playing = False
            tts.last_ended_at = 1000.0
            self.assertTrue(is_tts_tail_capture(998.7))
            self.assertTrue(is_tts_tail_capture(999.5))
            self.assertFalse(is_tts_tail_capture(999.8))
            self.assertFalse(is_tts_tail_capture(1000.2))
            tts.is_speaking = True
            tts.is_playing = False
            self.assertTrue(looks_like_barge_in("stop talking"))
            self.assertFalse(looks_like_barge_in("open whatsapp"))
            self.assertTrue(is_tts_tail_capture(2000.0))
        finally:
            tts.last_ended_at, tts.is_speaking = prev[0], prev[1]
            tts.is_playing = prev[2]

    def _mic_dummy(self):
        import queue
        from collections import deque
        from services.voice_input import VoiceInputProcessor
        dummy = VoiceInputProcessor.__new__(VoiceInputProcessor)
        dummy.sample_rate = 16000
        dummy.capture_rate = 16000
        dummy.vad_threshold = 0.01
        dummy.audio_chunks = []
        dummy.is_recording = False
        dummy.current_audio_level = 0.0
        dummy.last_speech_time = 0
        dummy.recording_start_time = 0
        dummy._tts_barge_hits = 0
        dummy._tts_barge_cooldown = 0
        dummy._was_tts = False
        dummy._tts_holdoff_until = 0.0
        dummy._tts_overlap_talk = False
        dummy._awaiting_quiet = False
        dummy._quiet_frames = 0
        dummy._listen_epoch = 0
        dummy._energy_floor = 0.0
        dummy._tts_preroll = deque()
        dummy._listen_live_after_tts = False
        dummy.audio_queue = queue.Queue()
        dummy.text_queue = queue.Queue()
        dummy.silence_duration = 2.5
        dummy.max_record_duration = 20.0
        dummy.min_speech_duration = 0.5
        return dummy

    def test_audio_before_ended_at_is_discarded(self):
        import time
        import numpy as np
        import services.tts as tts
        dummy = self._mic_dummy()
        loud = np.ones(3200, dtype=np.float32) * 0.5
        ended = time.time()
        dummy._tts_preroll.append((ended - 2.0, loud.copy()))
        dummy._tts_preroll.append((ended - 0.2, loud.copy()))
        dummy._was_tts = True
        prev = tts.last_ended_at, tts.is_speaking, getattr(tts, "is_playing", False)
        try:
            tts.is_speaking = False
            tts.is_playing = False
            tts.last_ended_at = ended
            dummy.arm_listen_after_tts()
            self.assertFalse(dummy._awaiting_quiet)
            self.assertLessEqual(dummy._tts_holdoff_until, time.time() + 0.5)
            self.assertFalse(dummy.is_recording)
            self.assertTrue(dummy.audio_queue.empty())
        finally:
            tts.last_ended_at, tts.is_speaking = prev[0], prev[1]
            tts.is_playing = prev[2]

    def test_listening_live_without_quiet_frames(self):
        import time
        import numpy as np
        import services.tts as tts
        dummy = self._mic_dummy()
        dummy._was_tts = True
        dummy._awaiting_quiet = True
        dummy._quiet_frames = 0
        quiet = np.zeros((3200, 1), dtype=np.float32)
        prev = tts.last_ended_at, tts.is_speaking
        try:
            tts.last_ended_at = time.time() - 0.05
            with patch("services.tts.is_speaking", False):
                dummy.audio_callback(quiet, 3200, None, None)
            self.assertFalse(dummy._awaiting_quiet)
            self.assertTrue(dummy._listen_live_after_tts)
            self.assertFalse(dummy.is_recording)
            self.assertLessEqual(dummy._tts_holdoff_until, time.time() + 0.5)
        finally:
            tts.last_ended_at, tts.is_speaking = prev

    def test_loud_frame_after_ended_at_starts_recording(self):
        import time
        import numpy as np
        import services.tts as tts
        dummy = self._mic_dummy()
        loud = np.ones((3200, 1), dtype=np.float32) * 0.5
        ended = time.time() - 0.05
        dummy._tts_preroll.append((ended + 0.05, np.ones(3200, dtype=np.float32) * 0.5))
        dummy._was_tts = True
        prev = tts.last_ended_at, tts.is_speaking
        try:
            tts.last_ended_at = ended
            dummy.arm_listen_after_tts()
            self.assertFalse(dummy._awaiting_quiet)
            self.assertFalse(dummy.is_recording)
            dummy2 = self._mic_dummy()
            dummy2._was_tts = True
            tts.last_ended_at = time.time() - 0.05
            with patch("services.tts.is_speaking", False):
                dummy2.audio_callback(loud, 3200, None, None)
                # Holdoff right after her last word: no take yet, preroll keeps filling.
                self.assertFalse(dummy2.is_recording)
                self.assertTrue(dummy2._tts_preroll)
                dummy2._tts_holdoff_until = 0.0
                dummy2.audio_callback(loud, 3200, None, None)
            self.assertTrue(dummy2.is_recording)
            self.assertFalse(dummy2._awaiting_quiet)
        finally:
            tts.last_ended_at, tts.is_speaking = prev

    def test_tts_capture_blocked_while_audible(self):
        from services.voice_input import tts_capture_blocked
        import services.tts as tts
        prev = tts.is_speaking, getattr(tts, "is_playing", False)
        try:
            tts.is_speaking = False
            tts.is_playing = False
            self.assertFalse(tts_capture_blocked())
            tts.is_speaking = True
            tts.is_playing = False
            self.assertTrue(tts_capture_blocked())
            tts.is_playing = True
            with patch("services.tts.playback_remaining", return_value=2.0):
                self.assertTrue(tts_capture_blocked())
            with patch("services.tts.playback_remaining", return_value=0.2):
                self.assertTrue(tts_capture_blocked())
        finally:
            tts.is_speaking, tts.is_playing = prev

    def test_no_capture_while_tts_audible(self):
        import numpy as np
        import services.tts as tts
        dummy = self._mic_dummy()
        dummy._was_tts = True
        quiet = np.ones((3200, 1), dtype=np.float32) * 0.08
        loud = np.ones((3200, 1), dtype=np.float32) * 0.45
        prev = tts.is_speaking, getattr(tts, "is_playing", False)
        try:
            tts.is_speaking = True
            tts.is_playing = True
            with patch("services.tts.playback_remaining", return_value=0.2):
                for _ in range(5):
                    dummy.audio_callback(quiet, 3200, None, None)
                for _ in range(3):
                    dummy.audio_callback(loud, 3200, None, None)
            # Loud near-field frames barge in (stop her), but never feed STT mid-playback.
            self.assertFalse(dummy.is_recording)
            self.assertTrue(dummy.audio_queue.empty())
        finally:
            tts.is_speaking, tts.is_playing = prev


class MicListTests(unittest.TestCase):
    def test_junk_realtek_and_loopback(self):
        from services.voice_input import is_junk_mic, mic_fingerprint, fingerprints_match
        self.assertTrue(is_junk_mic("Stereo Mix (Realtek USB Audio)"))
        self.assertTrue(is_junk_mic("Microphone (Realtek USB Audio)"))
        self.assertTrue(is_junk_mic("Microsoft Sound Mapper - Input"))
        self.assertFalse(is_junk_mic("Microphone (Live Streamer CAM313 Microphone)"))
        self.assertFalse(is_junk_mic("Headset (Jabra Elite 85h)"))
        self.assertFalse(is_junk_mic("Headset Microphone (Bluetooth Hands-free Audio)"))
        self.assertFalse(is_junk_mic("Microphone (Jabra Elite 85h Hands-Free)"))
        from services.voice_input import mic_display_name
        self.assertEqual(
            mic_display_name(r"Headset (@System32\drivers\bthhfenum.sys,#2;(Jabra Elite 85h))"),
            "Headset (Jabra Elite 85h)",
        )
        self.assertEqual(mic_display_name("bthhfenum"), "Bluetooth headset")
        self.assertTrue(fingerprints_match(
            mic_fingerprint("Microphone (Live Streamer CAM31"),
            mic_fingerprint("Microphone (Live Streamer CAM313 Microphone)"),
        ))
        self.assertFalse(fingerprints_match(
            mic_fingerprint("Headset (Jabra Elite 85h)"),
            mic_fingerprint("Headset (Jabra Evolve2 85)"),
        ))


class BusyAudioTests(unittest.TestCase):
    def test_meeting_titles_pause_listen(self):
        from services.busy_audio import detect_busy, meeting_from_titles
        self.assertTrue(meeting_from_titles(["Weekly standup - Meet - Google Chrome"]))
        self.assertTrue(meeting_from_titles(["Zoom Meeting"]))
        self.assertTrue(meeting_from_titles(["Voice Connected"]))
        self.assertFalse(meeting_from_titles(["How to meet people - YouTube - Google Chrome"]))
        self.assertFalse(meeting_from_titles(["Inbox - Gmail - Google Chrome"]))
        self.assertEqual(
            detect_busy(titles=["Zoom Meeting"], media_playing=False), "meeting")
        self.assertEqual(
            detect_busy(titles=["Notepad"], media_playing=True), "media")
        self.assertEqual(
            detect_busy(
                titles=["Turkish Afro House - YouTube - Google Chrome"],
                media_playing=False,
            ),
            "video",
        )
        self.assertEqual(
            detect_busy(titles=["Lose Yourself - Spotify"], media_playing=False),
            "media",
        )
        self.assertIsNone(detect_busy(titles=["Notepad"], media_playing=False))
        self.assertIsNone(
            detect_busy(titles=["YouTube - Google Chrome"], media_playing=False))

    def test_playback_controls_follow_media_not_meetings(self):
        from services.busy_audio import detect_busy, playback_controls_wanted
        from services import busy_audio as ba
        prev = dict(ba._CACHE)
        prev_play = ba._HAD_PLAY
        try:
            ba._HAD_PLAY = False
            ba._CACHE.update(reason=None, transport=None, hold_until=0.0, at=0.0)
            self.assertFalse(playback_controls_wanted(None))
            self.assertTrue(playback_controls_wanted(
                detect_busy(titles=["Notepad"], media_playing=True)))
            ba._HAD_PLAY = False
            self.assertFalse(playback_controls_wanted(
                detect_busy(titles=["Zoom Meeting"], media_playing=True)))
            ba._HAD_PLAY = False
            self.assertFalse(playback_controls_wanted(
                detect_busy(
                    titles=["Turkish Afro House - YouTube - Google Chrome"],
                    media_playing=False,
                )))
            ba._HAD_PLAY = False
            ba._CACHE.update(reason=None, transport="paused")
            self.assertFalse(playback_controls_wanted(None))
            ba._HAD_PLAY = True
            ba._CACHE.update(reason="media", transport="paused")
            self.assertTrue(playback_controls_wanted(None))
        finally:
            ba._HAD_PLAY = prev_play
            ba._CACHE.clear()
            ba._CACHE.update(prev)

    def test_parse_playback_title(self):
        from services.busy_audio import parse_playback_title
        parsed = parse_playback_title(
            "Turkish Afro House 2026 - YouTube - Google Chrome")
        self.assertEqual(parsed["kind"], "video")
        self.assertIn("Turkish Afro House", parsed["title"])
        self.assertIsNone(parse_playback_title("YouTube - Google Chrome"))
        self.assertIsNone(parse_playback_title("Inbox - Gmail - Google Chrome"))

    def test_addressed_to_davi(self):
        from services.busy_audio import addressed_to_davi
        self.assertEqual(addressed_to_davi("davi volume down"), "volume down")
        self.assertEqual(addressed_to_davi("hey DAVI mute"), "mute")
        self.assertIsNone(addressed_to_davi("never gonna give you up"))
        self.assertIsNone(addressed_to_davi("open chrome"))

    def test_command_through_media(self):
        from services.busy_audio import command_through_media
        self.assertEqual(command_through_media("bunu kapat"), "bunu kapat")
        self.assertEqual(command_through_media("close this"), "close this")
        self.assertEqual(command_through_media("videoyu kapat"), "videoyu kapat")
        self.assertEqual(command_through_media("duraklat"), "duraklat")
        self.assertEqual(command_through_media("DAVI volume down"), "volume down")
        self.assertIsNone(command_through_media("kapat"))
        self.assertIsNone(command_through_media("never gonna give you up"))
        self.assertIsNone(command_through_media("play"))
        self.assertIsNone(command_through_media("open chrome"))

    def test_drop_speaker_media_allows_wake_and_ptt(self):
        from services import voice_input as vi
        from services import busy_audio
        prev_room = os.environ.get("DAVI_ROOM_AUDIO")
        prev_ptt = vi._ptt_down
        prev_cache = dict(busy_audio._CACHE)
        try:
            vi.set_room_audio("speakers")
            vi.set_ptt_down(False)
            busy_audio._CACHE.update({"reason": "media", "at": 0, "hold_until": 10**12})
            self.assertTrue(vi.drop_speaker_media("open chrome"))
            self.assertFalse(vi.drop_speaker_media("aemyos chrome ac"))
            self.assertFalse(vi.drop_speaker_media("duraklat"))
            vi.set_ptt_down(True)
            self.assertFalse(vi.drop_speaker_media("open chrome"))
            vi.set_ptt_down(False)
            vi.set_room_audio("headphones")
            self.assertFalse(vi.drop_speaker_media("open chrome"))
        finally:
            vi.set_ptt_down(prev_ptt)
            busy_audio._CACHE.clear()
            busy_audio._CACHE.update(prev_cache)
            if prev_room is None:
                os.environ.pop("DAVI_ROOM_AUDIO", None)
            else:
                os.environ["DAVI_ROOM_AUDIO"] = prev_room
            try:
                import config
                config.ROOM_AUDIO = "headphones" if str(prev_room or "").lower() in (
                    "headphones", "headset", "kulaklik", "kulaklık",
                ) else "speakers"
            except Exception:
                pass

    def test_hold_commands_only_in_meetings(self):
        from services.busy_audio import hold_commands
        self.assertTrue(hold_commands("meeting"))
        self.assertFalse(hold_commands("media"))
        self.assertFalse(hold_commands("video"))
        self.assertFalse(hold_commands(None))

    def test_mic_stays_open_while_busy(self):
        from services import voice_input as vi
        from services import busy_audio
        prev_mode, prev_ptt = vi.listen_mode, vi._ptt_down
        prev_cache = dict(busy_audio._CACHE)
        try:
            vi.listen_mode = "always"
            vi.set_ptt_down(False)
            busy_audio._CACHE.update({"reason": "media", "at": 0, "hold_until": 10**12})
            self.assertTrue(vi.mic_is_open())
        finally:
            vi.listen_mode = prev_mode
            vi.set_ptt_down(prev_ptt)
            busy_audio._CACHE.clear()
            busy_audio._CACHE.update(prev_cache)

    def test_ambient_note_does_not_persist(self):
        from unittest.mock import patch
        from services import personal
        calls = []
        with patch.object(personal, "add_note", side_effect=lambda t: calls.append(t) or t):
            self.assertIsNone(personal.add_ambient_note(
                "let us review the budget numbers now", kind="meeting"))
            self.assertIsNone(personal.note_now_playing("Lose Yourself", "Eminem"))
        self.assertEqual(calls, [])


class LifeMemoryTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        from services import personal
        self.personal = personal
        self.mem = {
            "user": {},
            "notes": [
                {"text": "▶ Turkish Afro House", "date": "2026-09-08"},
                {"text": "buy milk", "date": "2026-09-08"},
            ],
            "life": {
                "music": [{"title": "Lose Yourself"}],
                "video": [{"title": "Turkish Afro House"}],
                "meetings": [{"title": "Zoom", "notes": ["budget"]}],
                "facts": [{"text": "Likes jazz"}],
            },
        }
        def load():
            return self.mem
        def save(data):
            self.mem = data
            return True
        self.patcher = patch.object(personal, "_memory_io", lambda: (load, save))
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_observe_media_never_writes(self):
        p = self.personal
        self.assertIsNone(p.observe_media("music", "Lose Yourself", "Eminem"))
        self.assertIsNone(p.observe_meeting("Zoom Meeting", "let us review the budget numbers now"))
        self.assertEqual(self.mem["life"]["music"][0]["title"], "Lose Yourself")

    def test_strip_media_keeps_facts(self):
        p = self.personal
        p.strip_media_from_memory()
        self.assertEqual(self.mem["life"], {"facts": [{"text": "Likes jazz"}]})
        self.assertEqual([n["text"] for n in self.mem["notes"]], ["buy milk"])
        self.assertEqual(p.startup_recall(), "")
        self.assertNotIn("Lose Yourself", " ".join(p.life_prompt_lines(self.mem)))
        self.assertIn("Likes jazz", " ".join(p.life_prompt_lines(self.mem)))

    def test_harvest_personal_facts(self):
        p = self.personal
        p.strip_media_from_memory()
        p.harvest_personal("I like Turkish music")
        p.harvest_personal("I live in Istanbul")
        facts = [r["text"] for r in self.mem["life"]["facts"]]
        self.assertTrue(any("Turkish music" in f for f in facts))
        self.assertEqual(self.mem["user"].get("location"), "Istanbul")
        self.assertEqual(p.startup_recall(), "")

    def test_known_user_name_from_profile_and_history(self):
        p = self.personal
        self.assertEqual(p.known_user_name(), "")
        from services.i18n import greeting
        anon = greeting("")
        self.assertTrue(any(anon.startswith(s) for s in ("Hi.", "Selam.", "Hola.", "Salut.")))
        self.assertIn("Ada", greeting("Ada"))
        self.mem["user"] = {"name": "Ada"}
        self.assertEqual(p.known_user_name(), "Ada")
        self.mem["user"] = {}
        self.mem["history"] = [{"role": "you", "text": "my name is Can"}]
        self.assertEqual(p.known_user_name(), "Can")
        self.assertEqual(self.mem["user"].get("name"), "Can")

    def test_own_mic_mute_closes_capture(self):
        from services import voice_input as vi
        prev = vi.mic_muted, vi._ptt_down, vi.listen_mode
        try:
            vi.listen_mode = "always"
            vi.set_ptt_down(False)
            vi.set_mic_muted(True)
            self.assertTrue(vi.is_mic_muted())
            self.assertFalse(vi.mic_is_open())
            vi.set_ptt_down(True)
            self.assertTrue(vi.mic_is_open())
            vi.set_mic_muted(False)
            vi.set_ptt_down(False)
            self.assertTrue(vi.mic_is_open())
        finally:
            vi.mic_muted, vi._ptt_down, vi.listen_mode = prev


class GroqSttErrorTests(unittest.TestCase):
    def test_fail_stt_sets_one_line_and_clears_processing(self):
        from services.voice_input import VoiceInputProcessor
        dummy = VoiceInputProcessor.__new__(VoiceInputProcessor)
        dummy.processing_indicator = True
        dummy.last_stt_error = ""
        dummy._fail_stt("HTTP 429")
        self.assertFalse(dummy.processing_indicator)
        msg = dummy.last_stt_error
        self.assertTrue(msg)
        self.assertEqual(dummy.consume_stt_error(), msg)
        self.assertEqual(dummy.consume_stt_error(), "")

    def test_groq_http_error_does_not_raise(self):
        from services.voice_input import VoiceInputProcessor

        class FakeResp:
            status_code = 503
            text = "unavailable"

            def json(self):
                return {"error": {"message": "unavailable"}}

        dummy = VoiceInputProcessor.__new__(VoiceInputProcessor)
        dummy.groq_key = "test-not-a-real-key"
        dummy.language = "en"
        dummy.whisper_prompt = "x"
        dummy.processing_indicator = True
        dummy.last_stt_error = ""
        dummy.last_transcription = ""
        wav = os.path.join(os.environ.get("TEMP", "."), "davi_stt_test.wav")
        dummy._save_wav = lambda audio: wav
        try:
            open(wav, "wb").close()
            with patch("requests.post", return_value=FakeResp()):
                out = dummy._transcribe_groq(None)
            self.assertIsNone(out)
            self.assertFalse(dummy.processing_indicator)
            self.assertTrue(dummy.last_stt_error)
        finally:
            try:
                os.remove(wav)
            except OSError:
                pass


class FastOpenAppCollisionTests(unittest.TestCase):
    def test_chrome_alone_still_opens(self):
        from services.smart_features import match_fast_open_app, match_fast_desktop
        for phrase in ("chrome", "open chrome", "google chrome", "open google chrome", "krom", "chrome ac"):
            self.assertEqual(match_fast_open_app(phrase), "Chrome", phrase)
            self.assertIsNone(match_fast_desktop(phrase), phrase)

    def test_chrome_compound_not_open_app(self):
        from services.smart_features import match_fast_open_app, match_fast_desktop, match_fast_switch_app
        for phrase in (
            "open chrome and go to youtube",
            "open chrome youtube",
            "open chrome downloads",
            "open chrome settings",
            "chrome da youtube ac",
            "ac chrome da youtube",
            "start chrome then go to gmail",
            "open chrome and search for cats",
        ):
            self.assertIsNone(match_fast_open_app(phrase), phrase)
            self.assertIsNone(match_fast_desktop(phrase), phrase)
        self.assertEqual(match_fast_switch_app("switch to chrome"), ("focus", "Chrome"))
        self.assertIsNone(match_fast_switch_app("switch to chrome youtube"))


class FastSiteOpenTests(unittest.TestCase):
    def test_youtube_is_a_site_not_an_app(self):
        from services.smart_features import match_fast_site, match_fast_open_app, match_fast_desktop
        self.assertEqual(match_fast_site("open youtube"), "https://www.youtube.com")
        self.assertEqual(match_fast_site("youtube aç"), "https://www.youtube.com")
        self.assertIsNone(match_fast_open_app("open youtube"))
        self.assertIsNone(match_fast_desktop("open youtube"))
        self.assertIsNone(match_fast_site("pause youtube"))
        self.assertIsNone(match_fast_site("close youtube"))

    def test_browser_suffix_is_not_a_search(self):
        from services.smart_features import match_fast_site, match_fast_site_search
        for phrase in (
            "can you open youtube on browser",
            "open youtube in the browser",
            "open youtube on chrome please",
            "youtube ac tarayicida",
        ):
            self.assertEqual(match_fast_site(phrase), "https://www.youtube.com", phrase)
            self.assertIsNone(match_fast_site_search(phrase), phrase)
        url = match_fast_site_search("play turkish music on youtube in chrome")
        self.assertIn("search_query=turkish+music", url)

    def test_collapse_drops_open_url_when_bridge_navigates(self):
        from services.execute_funcs import _collapse_url_opens
        cmds = [
            {"command": "browser_navigate", "params": {"url": "https://www.youtube.com"}},
            {"command": "open_url", "params": {"url": "https://www.youtube.com"}},
            {"command": "open_app", "params": {"name": "Chrome"}},
        ]
        out = _collapse_url_opens(cmds)
        names = [c["command"] for c in out]
        self.assertEqual(names, ["browser_navigate"])

    def test_simple_apps_still_open(self):
        from services.smart_features import match_fast_open_app
        self.assertEqual(match_fast_open_app("open discord"), "Discord")
        self.assertEqual(match_fast_open_app("open photoshop"), "photoshop")
        self.assertEqual(match_fast_open_app("open visual studio code"), "Visual Studio Code")
        self.assertEqual(match_fast_open_app("spotify ac"), "Spotify")

    def test_open_lock_does_not_lock(self):
        from services.smart_features import match_fast_desktop, match_fast_open_app
        self.assertEqual(match_fast_desktop("lock"), "lock")
        self.assertIsNone(match_fast_desktop("open lock"))
        self.assertIsNone(match_fast_open_app("open lock"))
        self.assertIsNone(match_fast_desktop("open mute"))
        self.assertIsNone(match_fast_desktop("open play"))
        self.assertIsNone(match_fast_desktop("open time"))
        self.assertEqual(match_fast_desktop("open settings"), "settings")
        self.assertEqual(match_fast_desktop("open calculator"), "calculator")


class YoutubeSearchRewriteTests(unittest.TestCase):
    def test_click_search_plus_type_becomes_results_url(self):
        from services.chrome_router import rewrite_chrome_commands
        cmds = [
            {"command": "browser_click", "params": {"selector": "input[id='search']"}},
            {"command": "wait", "params": {"seconds": 0.3}},
            {"command": "enter_text", "params": {"text": "Turkish music"}},
            {"command": "press_key", "params": {"key": "enter"}},
        ]
        out = rewrite_chrome_commands(cmds, bridge_connected=False)
        self.assertEqual([c["command"] for c in out], ["browser_navigate"])
        url = out[0]["params"]["url"]
        self.assertIn("youtube.com/results", url)
        self.assertIn("search_query=", url)
        self.assertTrue("Turkish" in url or "turkish" in url.lower())

    def test_tab_match_youtube_alias(self):
        from services.chrome_router import tab_matches
        self.assertTrue(tab_matches({"title": "YouTube", "url": "https://www.youtube.com/"}, "youtube"))
        self.assertTrue(tab_matches({"title": "Music", "url": "https://www.youtube.com/watch?v=x"}, "yt"))
        self.assertFalse(tab_matches({"title": "GitHub", "url": "https://github.com"}, "youtube"))

    def test_format_tabs_mentions_already_open(self):
        from services.chrome_router import format_tabs_message
        msg = format_tabs_message([
            {"id": 1, "title": "YouTube", "url": "https://www.youtube.com/", "active": False},
            {"id": 2, "title": "GitHub", "url": "https://github.com", "active": True},
        ])
        self.assertIn("Already open", msg)
        self.assertIn("YouTube", msg)
        self.assertIn("id=1", msg)

    def test_find_tab_falls_back_when_extension_is_old(self):
        from services.chrome_router import bridge_find_tab
        tabs = [{"id": 9, "title": "YouTube", "url": "https://www.youtube.com/"}]
        calls = []

        def bridge(cmd, params=None):
            calls.append(cmd)
            if cmd == "find_tab":
                return {"success": False, "error": "Unknown command: find_tab"}
            if cmd == "get_tabs":
                return {"success": True, "tabs": tabs}
            if cmd == "switch_tab":
                self.assertEqual(params["tab_id"], 9)
                return {"success": True, "message": "Switched"}
            return {"success": False, "error": "nope"}

        r = bridge_find_tab(bridge, {"query": "youtube"})
        self.assertTrue(r["success"])
        self.assertIn("find_tab", calls)
        self.assertIn("switch_tab", calls)

    def test_ctrl_l_becomes_navigate_when_extension_connected(self):
        from services.chrome_router import rewrite_chrome_commands
        cmds = [
            {"command": "press_hotkey", "params": {"keys": ["ctrl", "l"]}},
            {"command": "wait", "params": {"seconds": 0.2}},
            {"command": "enter_text", "params": {"text": "google flights istanbul"}},
            {"command": "press_key", "params": {"key": "enter"}},
        ]
        out = rewrite_chrome_commands(cmds, bridge_connected=True, chrome_front=True)
        self.assertEqual([c["command"] for c in out], ["browser_navigate"])
        self.assertIn("google.com/search", out[0]["params"]["url"])

    def test_ctrl_t_becomes_new_tab(self):
        from services.chrome_router import rewrite_chrome_commands
        cmds = [{"command": "press_hotkey", "params": {"keys": ["ctrl", "t"]}}]
        out = rewrite_chrome_commands(cmds, bridge_connected=True, chrome_front=True)
        self.assertEqual(out[0]["command"], "browser_new_tab")

    def test_page_link_click_becomes_browser_click(self):
        from services.chrome_router import rewrite_chrome_commands
        cmds = [
            {"command": "move_cursor_to_element", "params": {"name": "Subscribe"}},
            {"command": "mouse_button", "params": {"button": "left"}},
        ]
        out = rewrite_chrome_commands(cmds, bridge_connected=True, chrome_front=True)
        self.assertEqual(out, [{"command": "browser_click", "params": {"text": "Subscribe"}}])

    def test_native_yes_stays_click_ui(self):
        from services.chrome_router import rewrite_chrome_commands
        cmds = [{"command": "click_ui", "params": {"name": "Yes", "type": "Button"}}]
        out = rewrite_chrome_commands(cmds, bridge_connected=True, chrome_front=True)
        self.assertEqual(out[0]["command"], "click_ui")

    def test_reuse_existing_youtube_tab(self):
        from services.chrome_router import reuse_or_open_url
        calls = []
        tabs = [{"id": 4, "title": "YouTube", "url": "https://www.youtube.com/", "active": False}]

        def bridge(cmd, params=None):
            calls.append((cmd, params))
            if cmd == "get_tabs":
                return {"success": True, "tabs": tabs}
            if cmd == "switch_tab":
                return {"success": True, "message": "Switched"}
            if cmd == "new_tab":
                return {"success": True, "message": "Opened"}
            return {"success": False, "error": cmd}

        r = reuse_or_open_url("https://www.youtube.com", bridge_command=bridge)
        self.assertTrue(r["success"])
        self.assertTrue(any(c[0] == "switch_tab" for c in calls))
        self.assertFalse(any(c[0] == "new_tab" for c in calls))

    def test_fast_youtube_search_phrase(self):
        from services.smart_features import match_fast_site, match_fast_site_search
        self.assertIsNone(match_fast_site("play turkish music on youtube"))
        url = match_fast_site_search("play turkish music on youtube")
        self.assertIn("youtube.com/results", url)
        self.assertIsNone(match_fast_site_search("open youtube"))
        self.assertIsNone(match_fast_site_search("pause youtube"))
        tr = match_fast_site_search("youtube da turkce muzik")
        self.assertIn("youtube.com/results", tr)


class VoiceQuitCancelTests(unittest.TestCase):
    def test_stop_quits_cancel_does_not(self):
        from services.smart_features import (
            match_voice_quit, match_voice_cancel, match_fast_desktop, match_fast_open_app,
        )
        for phrase in ("quit", "exit", "kapat"):
            self.assertTrue(match_voice_quit(phrase), phrase)
            self.assertFalse(match_voice_cancel(phrase), phrase)
            self.assertIsNone(match_fast_desktop(phrase), phrase)
            self.assertIsNone(match_fast_open_app(phrase), phrase)
        for phrase in ("stop", "Stop.", "STOP!", "dur", "sus", "shut up"):
            self.assertFalse(match_voice_quit(phrase), phrase)
            self.assertFalse(match_voice_cancel(phrase), phrase)
            self.assertEqual(match_fast_desktop(phrase), "stop_talking", phrase)
        for phrase in ("cancel", "Cancel!", "please cancel", "iptal", "vazgeç", "vazgec"):
            self.assertTrue(match_voice_cancel(phrase), phrase)
            self.assertFalse(match_voice_quit(phrase), phrase)
            self.assertIsNone(match_fast_desktop(phrase), phrase)
            self.assertIsNone(match_fast_open_app(phrase), phrase)
        self.assertFalse(match_voice_quit("stop chrome"))
        self.assertFalse(match_voice_cancel("cancel task"))
        self.assertFalse(match_voice_quit("cancel"))
        self.assertFalse(match_voice_cancel("stop"))


class DailyVoiceTests(unittest.TestCase):
    def test_daily_phrases(self):
        from services.smart_features import match_fast_desktop, match_voice_quit, match_fast_open_app
        self.assertEqual(match_fast_desktop("undo"), "undo")
        self.assertEqual(match_fast_desktop("geri al"), "undo")
        self.assertEqual(match_fast_desktop("copy"), "copy")
        self.assertEqual(match_fast_desktop("copy that"), "copy_reply")
        self.assertEqual(match_fast_desktop("paste"), "paste")
        self.assertEqual(match_fast_desktop("snap left"), "snap_left")
        self.assertEqual(match_fast_desktop("bu pencereyi kapat"), "close_window")
        self.assertEqual(match_fast_desktop("screenshot"), "screenshot")
        self.assertEqual(match_fast_desktop("kamera aç"), "camera_on")
        self.assertEqual(match_fast_desktop("open camera"), "camera_on")
        self.assertEqual(match_fast_desktop("kamera"), "camera_on")
        self.assertEqual(match_fast_desktop("kamerayı açar mısın"), "camera_on")
        self.assertEqual(match_fast_desktop("can you open the camera"), "camera_on")
        self.assertIsNone(match_fast_desktop("What you are seeing in camera right now."))
        self.assertIsNone(match_fast_desktop(
            "What you are seeing in camera right now? Desktop voice"))
        self.assertIsNone(match_fast_desktop("Can you check the camera once have it?"))
        from services.smart_features import match_screen_question
        self.assertTrue(match_screen_question("What you are seeing in camera right now."))
        self.assertTrue(match_screen_question("Can you check the camera once have it?"))
        self.assertTrue(match_screen_question("kamerada ne var"))
        self.assertFalse(match_screen_question("open the camera"))
        self.assertEqual(match_fast_desktop("kamerayı kapat"), "camera_off")
        self.assertEqual(match_fast_desktop("Can you close the camera"), "camera_off")
        self.assertEqual(match_fast_desktop("close the camera"), "camera_off")
        self.assertIsNone(match_fast_open_app("kamera"))
        self.assertIsNone(match_fast_open_app("open camera"))
        self.assertEqual(match_fast_desktop("remember my face"), "face_enroll")
        self.assertEqual(match_fast_desktop("yüzümü kaydet"), "face_enroll")
        self.assertEqual(match_fast_desktop("forget my face"), "face_forget")
        self.assertEqual(match_fast_desktop("yüzümü unut"), "face_forget")
        self.assertEqual(match_fast_desktop("do you recognize me"), "face_query")
        self.assertEqual(match_fast_desktop("beni tanıyor musun"), "face_query")
        self.assertEqual(match_fast_desktop("open camera"), "camera_on")
        self.assertIsNone(match_fast_open_app("kamera aç"))
        self.assertIsNone(match_fast_desktop("kapat"))
        self.assertEqual(match_fast_desktop("bunu kapat"), "close_window")
        self.assertEqual(match_fast_desktop("videoyu kapat"), "close_window")
        self.assertTrue(match_voice_quit("kapat"))
        self.assertIsNone(match_fast_desktop("kapat"))
        self.assertFalse(match_voice_quit("bunu kapat"))
        self.assertEqual(match_fast_desktop("read this"), "read_selection")
        self.assertEqual(match_fast_desktop("oku bunu"), "read_selection")
        self.assertEqual(match_fast_desktop("weather"), "weather")
        self.assertEqual(match_fast_desktop("hava durumu"), "weather")
        self.assertEqual(match_fast_desktop("say that again"), "say_again")
        self.assertEqual(match_fast_desktop("hide yourself"), "hide_davi")
        self.assertEqual(match_fast_desktop("gizlen"), "hide_davi")
        self.assertFalse(match_voice_quit("gizlen"))
        self.assertFalse(match_voice_quit("bu pencereyi kapat"))
        self.assertEqual(match_fast_desktop("come back"), "show_davi")
        self.assertEqual(match_fast_desktop("shut up"), "stop_talking")
        self.assertEqual(match_fast_desktop("stop listening"), "mute_mic")
        self.assertEqual(match_fast_desktop("Can you stop listening right now?"), "mute_mic")
        self.assertEqual(match_fast_desktop("mikrofonu kapat"), "mute_mic")
        self.assertEqual(match_fast_desktop("start listening"), "unmute_mic")
        self.assertEqual(match_fast_desktop("mikrofonu aç"), "unmute_mic")
        self.assertEqual(match_fast_desktop("mute"), "mute")
        self.assertEqual(match_fast_desktop("speak slower"), "speak_slower")
        self.assertIsNone(match_fast_open_app("open copy"))
        self.assertIsNone(match_fast_open_app("open weather"))

    def test_camera_builtin_is_protocol(self):
        from services.pc_context import find_app
        hit = find_app("camera")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1], "microsoft.windows.camera:")
        hit_tr = find_app("kamera")
        self.assertIsNotNone(hit_tr)
        self.assertEqual(hit_tr[1], "microsoft.windows.camera:")

    def test_type_once(self):
        from services.daily import match_type_once
        self.assertEqual(match_type_once("type this: hello world").lower(), "hello world")
        self.assertEqual(match_type_once("yaz: merhaba"), "merhaba")
        self.assertIsNone(match_type_once("type what i say"))
        self.assertIsNone(match_type_once("open chrome"))

    def test_last_spoken(self):
        from services.daily import remember_spoken, last_spoken, copy_last_reply
        remember_spoken("hello there")
        self.assertEqual(last_spoken(), "hello there")
        r = copy_last_reply()
        self.assertTrue(r["success"])


class ProviderRoutingTests(unittest.TestCase):
    def test_openrouter_model_slugs(self):
        import config
        prev_p, prev_m, prev_w = config.PROVIDER, config.MODEL, config.WHISPER_MODEL
        prev_env_w = os.environ.get("DAVI_WHISPER_MODEL")
        try:
            config.PROVIDER = "openrouter"
            config.MODEL = "claude-sonnet-5"
            self.assertEqual(config.llm_model_id(), "anthropic/claude-sonnet-5")
            config.MODEL = "anthropic/claude-sonnet-5"
            self.assertEqual(config.llm_model_id(), "anthropic/claude-sonnet-5")
            os.environ["DAVI_WHISPER_MODEL"] = "whisper-large-v3-turbo"
            self.assertEqual(config.stt_model_id(), "openai/whisper-large-v3-turbo")
            config.PROVIDER = "anthropic"
            config.MODEL = "claude-sonnet-5"
            self.assertEqual(config.llm_model_id(), "claude-sonnet-5")
            self.assertEqual(config.stt_model_id(), "whisper-large-v3-turbo")
        finally:
            config.PROVIDER, config.MODEL, config.WHISPER_MODEL = prev_p, prev_m, prev_w
            if prev_env_w is None:
                os.environ.pop("DAVI_WHISPER_MODEL", None)
            else:
                os.environ["DAVI_WHISPER_MODEL"] = prev_env_w

    def test_generate_posts_to_openrouter(self):
        import config
        from services import openrouter_api
        prev = config.PROVIDER, config.OPENROUTER_KEY, config.MODEL
        captured = {}

        class FakeResp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            return FakeResp()

        try:
            config.PROVIDER = "openrouter"
            config.OPENROUTER_KEY = "sk-or-test"
            config.MODEL = "claude-sonnet-5"
            with patch("services.openrouter_api.requests.post", side_effect=fake_post):
                out = openrouter_api.generate(
                    [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                    "default",
                )
            self.assertEqual(out, "ok")
            self.assertIn("openrouter.ai", captured["url"])
            self.assertEqual(captured["json"]["model"], "anthropic/claude-sonnet-5")
            self.assertEqual(captured["json"]["messages"][0]["role"], "system")
        finally:
            config.PROVIDER, config.OPENROUTER_KEY, config.MODEL = prev

    def test_generate_posts_to_anthropic(self):
        import config
        from services import openrouter_api
        prev = config.PROVIDER, config.ANTHROPIC_KEY, config.MODEL
        captured = {}

        class FakeResp:
            status_code = 200

            def json(self):
                return {"content": [{"type": "text", "text": "hello"}]}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            return FakeResp()

        try:
            config.PROVIDER = "anthropic"
            config.ANTHROPIC_KEY = "sk-ant-test"
            config.MODEL = "claude-sonnet-5"
            with patch("services.openrouter_api.requests.post", side_effect=fake_post):
                out = openrouter_api.generate(
                    [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                    "default",
                )
            self.assertEqual(out, "hello")
            self.assertIn("api.anthropic.com", captured["url"])
            self.assertEqual(captured["json"]["model"], "claude-sonnet-5")
        finally:
            config.PROVIDER, config.ANTHROPIC_KEY, config.MODEL = prev

    def test_stt_uses_openrouter_when_selected(self):
        import config
        from services.voice_input import VoiceInputProcessor
        dummy = VoiceInputProcessor.__new__(VoiceInputProcessor)
        dummy.groq_key = "gsk_should_not_use"
        dummy.local_model = object()
        prev = config.PROVIDER, config.OPENROUTER_KEY, config.GROQ_API_KEY
        try:
            config.PROVIDER = "openrouter"
            config.OPENROUTER_KEY = "sk-or-test"
            dummy._transcribe_openrouter = lambda audio: "OR"
            dummy._transcribe_groq = lambda audio: "GROQ"
            self.assertEqual(dummy._stt_backend(), "openrouter")
            self.assertEqual(dummy._transcribe_audio(None), "OR")
            config.PROVIDER = "anthropic"
            config.GROQ_API_KEY = "gsk_test"
            self.assertEqual(dummy._stt_backend(), "groq")
            self.assertEqual(dummy._stt_backend(), "groq")
            self.assertEqual(dummy._transcribe_audio(None), "GROQ")
        finally:
            config.PROVIDER, config.OPENROUTER_KEY, config.GROQ_API_KEY = prev

    def test_stt_ready_requires_cloud_key(self):
        import config
        prev = config.PROVIDER, config.GROQ_API_KEY, config.OPENROUTER_KEY
        try:
            config.PROVIDER = "anthropic"
            config.GROQ_API_KEY = ""
            config.OPENROUTER_KEY = ""
            self.assertFalse(config.stt_ready())
            config.GROQ_API_KEY = "gsk_test"
            self.assertTrue(config.stt_ready())
            config.PROVIDER = "openrouter"
            config.GROQ_API_KEY = ""
            config.OPENROUTER_KEY = "sk-or-test"
            self.assertTrue(config.stt_ready())
            config.OPENROUTER_KEY = ""
            self.assertFalse(config.stt_ready())
        finally:
            config.PROVIDER, config.GROQ_API_KEY, config.OPENROUTER_KEY = prev


class LoopGuardTests(unittest.TestCase):
    def test_double_click_streak_stops_after_five(self):
        from services.loop_guard import bump_streak, stuck_decision, SAME_LIMIT
        cmds = [{"command": "double_click", "params": {"button": "left"}}]
        fp, n = None, 0
        thought = None
        decisions = []
        for _ in range(7):
            fp, n = bump_streak(fp, n, cmds)
            d = stuck_decision(n, fp, thought)
            decisions.append((n, d))
            if d == "think":
                thought = fp
        self.assertEqual(SAME_LIMIT, 5)
        self.assertEqual(decisions[4], (5, "think"))
        self.assertEqual(decisions[5], (6, "stop"))

    def test_new_method_resets_streak(self):
        from services.loop_guard import bump_streak, fingerprint
        a = [{"command": "double_click", "params": {"button": "left"}}]
        b = [{"command": "click_ui", "params": {"name": "Include Folder", "type": "Button"}}]
        fp, n = bump_streak(None, 0, a)
        fp, n = bump_streak(fp, n, a)
        self.assertEqual(n, 2)
        self.assertNotEqual(fingerprint(a), fingerprint(b))
        fp, n = bump_streak(fp, n, b)
        self.assertEqual(n, 1)

    def test_listen_does_not_count(self):
        from services.loop_guard import fingerprint
        self.assertEqual(fingerprint([{"command": "listen"}]), ())


class FaceIdTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from unittest.mock import patch
        from services import face_id
        self.face_id = face_id
        self.tmp = tempfile.TemporaryDirectory()
        self.prev_dir = os.environ.get("DAVI_FACES_DIR")
        os.environ["DAVI_FACES_DIR"] = self.tmp.name
        face_id.reload_store()
        face_id.reset_session()
        self.patcher = patch.object(face_id, "_memory_face")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.face_id.reload_store()
        self.face_id.reset_session()
        if self.prev_dir is None:
            os.environ.pop("DAVI_FACES_DIR", None)
        else:
            os.environ["DAVI_FACES_DIR"] = self.prev_dir
        self.tmp.cleanup()

    def _pattern(self, kind):
        import numpy as np
        if kind == "h":
            return np.tile(np.arange(96, dtype=np.uint8), (96, 1))
        if kind == "v":
            return np.tile(np.arange(96, dtype=np.uint8).reshape(-1, 1), (1, 96))
        img = np.tile(np.arange(96, dtype=np.uint8), (96, 1))
        img[36:60, 36:60] = 10
        return img

    def test_same_face_matches_different_does_not(self):
        f = self.face_id
        a = f.embed_face(self._pattern("h"))
        close = f.embed_face(self._pattern("close"))
        other = f.embed_face(self._pattern("v"))
        self.assertGreater(f.cosine(a, a), 0.99)
        self.assertGreater(f.cosine(a, close), f.cosine(a, other))
        self.assertLess(f.cosine(a, other), f._MATCH)

    def test_needs_two_samples_before_calling_it_you(self):
        f = self.face_id
        f.enroll_crops([self._pattern("h"), self._pattern("close")], replace=True)
        self.assertIsNotNone(f.match_embed(f.embed_face(self._pattern("h"))))
        self.assertIsNone(f.match_embed(f.embed_face(self._pattern("v"))))

    def test_crowd_does_not_pick_a_face(self):
        f = self.face_id
        box, n = f._pick_face([(10, 10, 90, 90), (200, 10, 88, 88)])
        self.assertIsNone(box)
        self.assertEqual(n, 2)
        box, n = f._pick_face([(10, 10, 160, 160), (200, 10, 80, 80)])
        self.assertIsNotNone(box)
        self.assertEqual(n, 2)

    def test_enroll_and_forget(self):
        f = self.face_id
        self.assertFalse(f.is_enrolled())
        self.assertTrue(f.enroll_crops([self._pattern("h")], replace=True))
        self.assertTrue(f.is_enrolled())
        self.assertIsNotNone(f.match_embed(f.embed_face(self._pattern("h"))))
        self.assertIsNone(f.match_embed(f.embed_face(self._pattern("v"))))
        f.forget_face()
        self.assertFalse(f.is_enrolled())
        self.assertFalse(os.path.isfile(f._npz_path()))


class SpeakerTapTests(unittest.TestCase):
    def test_cancel_echo_drops_delayed_mix(self):
        import numpy as np
        from services.speaker_tap import cancel_echo
        sr = 16000
        n = 1600
        t = np.arange(n, dtype=np.float32) / sr
        signal = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        pad = np.zeros(400, dtype=np.float32)
        ref = np.concatenate([pad, signal, pad])
        mic = (0.75 * signal).astype(np.float32)
        out, sim = cancel_echo(mic, ref, sr=sr)
        self.assertGreater(sim, 0.9)
        before = float(np.mean(np.abs(mic)))
        after = float(np.mean(np.abs(out)))
        self.assertLess(after, before * 0.35)

    def test_cancel_echo_unrelated_noise_stays(self):
        import numpy as np
        from services.speaker_tap import cancel_echo
        rng = np.random.default_rng(3)
        mic = rng.normal(0, 0.2, 800).astype(np.float32)
        ref = np.random.default_rng(9).normal(0, 0.2, 1600).astype(np.float32)
        out, sim = cancel_echo(mic, ref, sr=16000)
        self.assertLess(sim, 0.35)
        self.assertLess(float(np.mean(np.abs(out - mic))), 0.05)


class VoiceVadTests(unittest.TestCase):
    def test_echo_setting_alone_does_not_block_speech(self):
        from services.voice_input import speech_onset
        self.assertTrue(speech_onset(0.04, 0.01, 0.01, 0.01, sim=0.0, busy=False))
        self.assertFalse(speech_onset(0.02, 0.018, 0.02, 0.01, sim=0.55, busy=False))
        self.assertTrue(speech_onset(0.12, 0.02, 0.02, 0.01, sim=0.2, busy=False))


if __name__ == "__main__":
    unittest.main()
