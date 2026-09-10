import json
import os
import tempfile
import unittest
from unittest import mock

from services import context_facts as cf


_IP = {"status": "success", "country": "United States", "countryCode": "US", "regionName": "New York",
       "city": "The Bronx", "lat": 40.85, "lon": -73.87, "timezone": "America/New_York"}
_WX = {"current": {"temperature_2m": 22.4, "weather_code": 2, "wind_speed_10m": 10},
       "daily": {"temperature_2m_max": [26.1], "temperature_2m_min": [18.2], "precipitation_probability_max": [45]}}


class ContextFactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "context.json")
        cf._CACHE.update({"data": None, "loaded": False})
        self.patches = [
            mock.patch.object(cf, "_path", return_value=self.path),
            mock.patch.object(cf, "_windows_location", return_value=None),
            mock.patch.object(cf, "_user_said_location", return_value=""),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        cf._CACHE.update({"data": None, "loaded": False})
        self.tmp.cleanup()

    def test_refresh_from_ip_and_prompt_line(self):
        with mock.patch.object(cf, "_get_json", return_value=_IP):
            loc = cf.refresh()
        self.assertEqual(loc["city"], "The Bronx")
        self.assertEqual(loc["source"], "ip")
        self.assertTrue(os.path.exists(self.path))
        line = cf.prompt_lines()[0]
        self.assertIn("The Bronx, New York, US", line)
        self.assertIn("America/New_York", line)
        self.assertIn("without asking", line)

    def test_cache_is_reused(self):
        with mock.patch.object(cf, "_get_json", return_value=_IP) as g:
            cf.refresh()
            cf.refresh()
        self.assertEqual(g.call_count, 1)

    def test_user_told_location_wins(self):
        geo = {"results": [{"name": "Istanbul", "admin1": "Istanbul", "country": "Turkey", "country_code": "TR",
                            "latitude": 41.01, "longitude": 28.95, "timezone": "Europe/Istanbul"}]}
        with mock.patch.object(cf, "_user_said_location", return_value="Istanbul"), \
             mock.patch.object(cf, "_get_json", return_value=geo):
            loc = cf.refresh()
        self.assertEqual(loc["source"], "user")
        self.assertEqual(loc["city"], "Istanbul")
        self.assertIn("the user told you", cf.prompt_lines()[0])

    def test_weather_tr_and_en(self):
        with mock.patch.object(cf, "_get_json", return_value=_IP):
            cf.refresh()
        with mock.patch.object(cf, "_get_json", return_value=_WX):
            tr = cf.weather("tr")["text"]
            en = cf.weather("en")["text"]
        self.assertIn("The Bronx: 72°F (22°C) parçalı bulutlu", tr)
        self.assertIn("yağış ihtimali %45", tr)
        self.assertIn("partly cloudy", en)
        self.assertIn("45% chance of rain", en)

    def test_no_location_no_lines(self):
        self.assertEqual(cf.prompt_lines(), [])


if __name__ == "__main__":
    unittest.main()
