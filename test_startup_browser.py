import unittest

from services import startup
from services.chrome_router import is_chromium_title


class StartupTests(unittest.TestCase):
    def test_launch_command_has_hidden_flag(self):
        self.assertTrue(startup.launch_command(hidden=True).endswith("--hidden"))
        self.assertFalse(startup.launch_command(hidden=False).endswith("--hidden"))
        self.assertIn("main.py", startup.launch_command())


class ChromiumTitleTests(unittest.TestCase):
    def test_chromium_browsers(self):
        for t in ("YouTube - Google Chrome", "Inbox - Microsoft Edge", "GitHub - Brave", "New Tab - Chromium"):
            self.assertTrue(is_chromium_title(t), t)

    def test_other_windows(self):
        for t in ("WhatsApp", "Mozilla Firefox", "Knowledge base - Word", ""):
            self.assertFalse(is_chromium_title(t), t)


if __name__ == "__main__":
    unittest.main()
