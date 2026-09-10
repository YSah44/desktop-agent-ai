import unittest
from datetime import datetime, timedelta

from services import office


class OfficeParseTests(unittest.TestCase):
    def test_word_forms(self):
        self.assertEqual(office.parse_request("type in word: Dear team, hello"), {"kind": "word", "text": "Dear team, hello"})
        self.assertEqual(office.parse_request("word: merhaba dünya"), {"kind": "word", "text": "merhaba dünya"})
        self.assertEqual(office.parse_request("word'e yaz: güzel bir gün")["text"], "güzel bir gün")

    def test_excel_forms(self):
        p = office.parse_request("add a row to excel: 2026-09-09, coffee, 4.5")
        self.assertEqual(p["kind"], "excel")
        self.assertEqual(office._split_values(p["values"]), ["2026-09-09", "coffee", "4.5"])
        self.assertEqual(office.parse_request("excel'e satır ekle: a; b; 3")["kind"], "excel")

    def test_inbox_forms(self):
        self.assertEqual(office.parse_request("read my inbox")["kind"], "inbox")
        self.assertTrue(office.parse_request("check unread emails")["unread"])
        self.assertEqual(office.parse_request("gelen kutusunu oku")["kind"], "inbox")

    def test_no_match(self):
        self.assertIsNone(office.parse_request("open word"))
        self.assertIsNone(office.parse_request("what time is it"))

    def test_coerce_and_when(self):
        self.assertEqual(office._coerce("42"), 42)
        self.assertEqual(office._coerce("4,5"), 4.5)
        self.assertEqual(office._coerce("abc"), "abc")
        tomorrow = office._parse_when("tomorrow 15:00")
        self.assertEqual((tomorrow.hour, tomorrow.minute), (15, 0))
        self.assertEqual(tomorrow.date(), (datetime.now() + timedelta(days=1)).date())
        self.assertEqual(office._parse_when("today 4pm").hour, 16)
        self.assertEqual(office._parse_when("2026-09-12 09:30").minute, 30)


if __name__ == "__main__":
    unittest.main()
