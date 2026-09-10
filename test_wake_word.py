import unittest

from services import voice_input as vi
from services.busy_audio import addressed_to_davi


class WakeWordTests(unittest.TestCase):
    def tearDown(self):
        vi.set_listen_mode("always")

    def test_modes(self):
        self.assertEqual(vi.set_listen_mode("wake"), "wake")
        self.assertTrue(vi.wake_word_required())
        self.assertTrue(vi.mic_is_open())
        vi.set_ptt_down(True)
        self.assertFalse(vi.wake_word_required())
        vi.set_ptt_down(False)
        self.assertEqual(vi.set_listen_mode("bogus"), "always")
        self.assertFalse(vi.wake_word_required())

    def test_wake_phrases(self):
        self.assertEqual(addressed_to_davi("Hey Aemyos, open Chrome"), "open Chrome")
        self.assertEqual(addressed_to_davi("aemyos what time is it"), "what time is it")
        self.assertEqual(addressed_to_davi("Selam Aemyos hava nasıl"), "hava nasıl")
        self.assertIsNone(addressed_to_davi("open chrome"))
        self.assertIsNone(addressed_to_davi("I told aemyos yesterday"))


if __name__ == "__main__":
    unittest.main()
