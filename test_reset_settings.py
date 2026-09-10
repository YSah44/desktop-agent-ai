import os
import tempfile
import unittest
from unittest import mock

import config


class ResetSettingsTests(unittest.TestCase):
    def test_reset_keeps_keys_and_drops_ui_values(self):
        with tempfile.TemporaryDirectory() as d:
            env = os.path.join(d, ".env")
            with open(env, "w") as f:
                f.write("ANTHROPIC_API_KEY=sk-keep\nDAVI_THEME=dark\nDAVI_OPACITY=70\n"
                        "DAVI_TELEGRAM_TOKEN=tok\nDAVI_SCREEN_BLOCKLIST=bank\nDAVI_LISTEN_MODE=wake\n")
            os.environ["DAVI_THEME"] = "dark"
            with mock.patch("services.paths.data_path", return_value=env):
                removed = config.reset_settings_env()
            self.assertEqual(sorted(removed), ["DAVI_LISTEN_MODE", "DAVI_OPACITY", "DAVI_THEME"])
            with open(env) as f:
                left = f.read()
            self.assertIn("ANTHROPIC_API_KEY=sk-keep", left)
            self.assertIn("DAVI_TELEGRAM_TOKEN=tok", left)
            self.assertIn("DAVI_SCREEN_BLOCKLIST=bank", left)
            self.assertNotIn("DAVI_THEME", left)
            self.assertNotIn("DAVI_THEME", os.environ)


if __name__ == "__main__":
    unittest.main()
