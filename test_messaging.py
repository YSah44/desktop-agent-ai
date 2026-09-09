import unittest

from services.messaging import parse_request


class MessagingParseTests(unittest.TestCase):
    def test_short_form(self):
        p = parse_request("whatsapp Ahmet: I'm running late")
        self.assertEqual(p, {"app": "whatsapp", "who": "Ahmet", "msg": "I'm running late"})

    def test_tell_on_whatsapp(self):
        p = parse_request("tell Ahmet on WhatsApp: see you at 5")
        self.assertEqual(p["who"], "Ahmet")
        self.assertEqual(p["msg"], "see you at 5")

    def test_telegram_alias(self):
        p = parse_request("tg Yavuz: test")
        self.assertEqual(p["app"], "telegram")

    def test_turkish_keeps_characters(self):
        p = parse_request("whatsapp'ta Ahmet'e yaz: geç kalıyorum, şimdi çıkıyorum")
        self.assertEqual(p["app"], "whatsapp")
        self.assertEqual(p["who"], "Ahmet")
        self.assertEqual(p["msg"], "geç kalıyorum, şimdi çıkıyorum")

    def test_turkish_contact_first(self):
        p = parse_request("Ahmet'e whatsapp'tan mesaj at: yoldayım")
        self.assertEqual(p["who"], "Ahmet")
        self.assertEqual(p["msg"], "yoldayım")

    def test_no_colon_no_match(self):
        self.assertIsNone(parse_request("open whatsapp"))
        self.assertIsNone(parse_request("tell me a joke"))
        self.assertIsNone(parse_request("what time is it"))


if __name__ == "__main__":
    unittest.main()
