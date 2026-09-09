import os
import tempfile
import time
import unittest

from services import file_index as fi


class FileIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aemyos_fi_")
        self.downloads = os.path.join(self.tmp, "Downloads")
        self.docs = os.path.join(self.tmp, "Documents")
        os.makedirs(self.downloads)
        os.makedirs(self.docs)
        now = time.time()
        self.files = {
            "invoice.pdf": (self.downloads, now - 3 * 86400),
            "old-report.pdf": (self.downloads, now - 40 * 86400),
            "holiday.jpg": (self.downloads, now - 86400),
            "notes.txt": (self.docs, now - 2 * 86400),
        }
        for name, (folder, mtime) in self.files.items():
            p = os.path.join(folder, name)
            with open(p, "w") as f:
                f.write("x")
            os.utime(p, (mtime, mtime))
        self._home = os.path.expanduser("~")
        self._patch_roots = fi._roots
        fi._roots = lambda: [self.downloads, self.docs]
        self._patch_home = os.path.expanduser
        os.path.expanduser = lambda p: self.tmp if p == "~" else self._patch_home(p)
        fi.rebuild()

    def tearDown(self):
        fi._roots = self._patch_roots
        os.path.expanduser = self._patch_home

    def test_kind_and_days_filter(self):
        r = fi.search(kind="pdf", days=14)
        self.assertEqual([x["name"] for x in r], ["invoice.pdf"])

    def test_query_words_and_folder(self):
        r = fi.search(query="notes", folder="Documents")
        self.assertEqual(r[0]["name"], "notes.txt")
        self.assertEqual(fi.search(query="notes", folder="Downloads"), [])

    def test_parse_english(self):
        p = fi.parse_request("open the pdf I downloaded last week")
        self.assertEqual(p["kind"], "pdf")
        self.assertEqual(p["days"], 14)
        self.assertEqual(p["folder"], "Downloads")

    def test_parse_turkish(self):
        p = fi.parse_request("gecen hafta indirdigim pdf'i ac")
        self.assertEqual(p["kind"], "pdf")
        self.assertEqual(p["days"], 14)
        self.assertEqual(p["folder"], "Downloads")

    def test_parse_requires_recent_or_time(self):
        self.assertIsNone(fi.parse_request("open chrome"))
        self.assertIsNone(fi.parse_request("open the pdf"))
        self.assertIsNotNone(fi.parse_request("open my latest photo"))

    def test_open_recent_picks_newest_match(self):
        opened = []
        orig = os.startfile
        os.startfile = lambda p: opened.append(p)
        try:
            r = fi.open_recent(kind="pdf", folder="Downloads")
        finally:
            os.startfile = orig
        self.assertTrue(r["success"])
        self.assertEqual(r["name"], "invoice.pdf")
        self.assertEqual(len(opened), 1)


if __name__ == "__main__":
    unittest.main()
