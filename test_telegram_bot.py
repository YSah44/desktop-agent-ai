import unittest
from unittest.mock import patch

from services import telegram_bot as tg


class TelegramBotTests(unittest.TestCase):
    def setUp(self):
        tg._token = "t"
        tg._owner = None
        tg._pair_code = "123456"
        tg._active_until = 0.0
        self.queued = []
        tg._enqueue = self.queued.append
        self.sent = []
        self.patch_send = patch.object(tg, "send", lambda text, chat_id=None: self.sent.append((chat_id, text)))
        self.patch_send.start()
        self.patch_env = patch("config.save_env", lambda **kw: None)
        self.patch_env.start()

    def tearDown(self):
        self.patch_send.stop()
        self.patch_env.stop()
        tg._owner = None
        tg._enqueue = None

    def msg(self, text, cid=42):
        return {"chat": {"id": cid}, "text": text}

    def test_unpaired_wrong_code_is_rejected(self):
        tg._handle(self.msg("/start 000000"))
        self.assertIsNone(tg._owner)
        self.assertEqual(self.queued, [])
        self.assertIn("Not paired", self.sent[-1][1])

    def test_pairing_with_code_then_commands_flow(self):
        tg._handle(self.msg("/start 123456"))
        self.assertEqual(tg._owner, 42)
        tg._handle(self.msg("open chrome"))
        self.assertEqual(self.queued, ["open chrome"])
        self.assertTrue(tg.is_active())
        self.assertEqual(self.sent[-1], (None, "▶ open chrome"))

    def test_other_chat_is_ignored_once_paired(self):
        tg._owner = 42
        tg._handle(self.msg("shutdown", cid=99))
        self.assertEqual(self.queued, [])
        self.assertEqual(self.sent, [])

    def test_notify_only_while_active(self):
        tg._owner = 42
        tg.notify("hello")
        self.assertEqual(self.sent, [])
        tg._handle(self.msg("what time is it"))
        tg.notify("17:00")
        self.assertEqual(self.sent[-1][1], "17:00")

    def test_status_does_not_enqueue(self):
        tg._owner = 42
        tg._handle(self.msg("/status"))
        self.assertEqual(self.queued, [])
        self.assertIn("running", self.sent[-1][1])


if __name__ == "__main__":
    unittest.main()
