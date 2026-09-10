import unittest
from unittest.mock import patch

from services import updater


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class UpdaterTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updater.parse_version("v1.9"), (1, 9))
        self.assertEqual(updater.parse_version("1.9-dev"), (1, 9))
        self.assertEqual(updater.parse_version("v2.0.3"), (2, 0, 3))
        self.assertLess(updater.parse_version("1.8"), updater.parse_version("1.9"))

    def _release(self, tag):
        return {"tag_name": tag, "body": "notes", "assets": [
            {"name": "Aemyos-Setup.exe", "browser_download_url": "https://x/Aemyos-Setup.exe"},
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt"},
        ]}

    def test_newer_release_detected(self):
        with patch.object(updater, "current_version", return_value=(1, 8)), \
             patch("requests.get", return_value=_Resp(self._release("v1.9"))):
            info = updater.check()
        self.assertEqual(info["version"], "1.9")
        self.assertTrue(info["url"].endswith("Aemyos-Setup.exe"))

    def test_same_or_older_release_ignored(self):
        with patch.object(updater, "current_version", return_value=(1, 9)), \
             patch("requests.get", return_value=_Resp(self._release("v1.9"))):
            self.assertIsNone(updater.check())
        with patch.object(updater, "current_version", return_value=(2, 0)), \
             patch("requests.get", return_value=_Resp(self._release("v1.9"))):
            self.assertIsNone(updater.check())


if __name__ == "__main__":
    unittest.main()
