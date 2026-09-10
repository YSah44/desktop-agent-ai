import unittest
from unittest.mock import patch

import numpy as np

from services import tts
from services.speaker_tap import cancel_echo


class TtsReferenceTests(unittest.TestCase):
    def setUp(self):
        rate = 24000
        t = np.arange(rate * 3) / rate
        # Voice-like: two tones with a slow envelope, 3 s long.
        self.samples = (0.4 * np.sin(2 * np.pi * 210 * t) + 0.2 * np.sin(2 * np.pi * 1400 * t)) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
        self.samples = self.samples.astype(np.float32)
        self._prev = (tts._play_samples, tts._play_rate, tts.is_playing)
        tts._play_samples = self.samples
        tts._play_rate = rate
        tts.is_playing = True

    def tearDown(self):
        tts._play_samples, tts._play_rate, tts.is_playing = self._prev

    def test_window_ends_at_playback_position(self):
        with patch("pygame.mixer.music.get_pos", return_value=1000):
            ref = tts.reference_window(3200, 16000)
        self.assertIsNotNone(ref)
        self.assertGreaterEqual(len(ref), 3200 + int(0.35 * 16000) - 2)

    def test_her_voice_matches_reference_and_user_does_not(self):
        with patch("pygame.mixer.music.get_pos", return_value=1000):
            ref = tts.reference_window(3200, 16000)
        # Mic hears her (attenuated, 60 ms late) — the tail of the reference minus the +50 ms margin.
        margin = int(0.05 * 16000)
        lag = int(0.06 * 16000)
        end = len(ref) - margin - lag
        heard = 0.3 * ref[end - 3200:end]
        _, sim_her = cancel_echo(heard, ref, sr=16000, max_lag_sec=0.3)
        self.assertGreater(sim_her, 0.9)
        rng = np.random.default_rng(1)
        user = (0.3 * rng.standard_normal(3200)).astype(np.float32)
        _, sim_user = cancel_echo(user, ref, sr=16000, max_lag_sec=0.3)
        self.assertLess(sim_user, 0.3)

    def test_no_reference_when_idle(self):
        tts.is_playing = False
        self.assertIsNone(tts.reference_window(3200, 16000))


if __name__ == "__main__":
    unittest.main()
