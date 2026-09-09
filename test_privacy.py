import os
import unittest
from unittest.mock import patch

from services import privacy


class PrivacyBlocklistTests(unittest.TestCase):
    def test_empty_list_blocks_nothing(self):
        with patch.dict(os.environ, {privacy.ENV_KEY: ""}):
            self.assertFalse(privacy.is_blocked("Wells Fargo - Google Chrome"))

    def test_substring_match_is_case_insensitive(self):
        with patch.dict(os.environ, {privacy.ENV_KEY: "wells fargo, 1Password"}):
            self.assertTrue(privacy.is_blocked("Wells Fargo - Google Chrome"))
            self.assertTrue(privacy.is_blocked("1password — Vault"))
            self.assertFalse(privacy.is_blocked("YouTube - Google Chrome"))

    def test_set_blocklist_dedupes_and_persists(self):
        saved = {}
        with patch("config.save_env", lambda **kw: saved.update(kw)):
            items = privacy.set_blocklist(" bank ,Bank, Signal ,, ")
        self.assertEqual(items, ["bank", "Signal"])
        self.assertEqual(saved[privacy.ENV_KEY], "bank, Signal")


if __name__ == "__main__":
    unittest.main()
