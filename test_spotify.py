import unittest
from unittest import mock

from services import spotify


class SpotifyParseTests(unittest.TestCase):
    def test_named_spotify_en(self):
        self.assertEqual(spotify.parse_request("play Tarkan on Spotify"), {"query": "tarkan", "kind": "track"})
        self.assertEqual(spotify.parse_request("spotify: lofi beats")["query"], "lofi beats")
        self.assertEqual(spotify.parse_request("open spotify and play daft punk")["query"], "daft punk")

    def test_named_spotify_tr(self):
        self.assertEqual(spotify.parse_request("spotify'da Sezen Aksu çal")["query"], "sezen aksu")
        self.assertEqual(spotify.parse_request("Sezen Aksu çal")["query"], "sezen aksu")
        self.assertEqual(spotify.parse_request("spotify'dan jazz dinlet")["query"], "jazz")

    def test_kinds(self):
        self.assertEqual(spotify.parse_request("play playlist discover weekly on spotify"), {"query": "discover weekly", "kind": "playlist"})
        self.assertEqual(spotify.parse_request("play the album abbey road on spotify")["kind"], "album")

    def test_bare_play_only_when_installed(self):
        with mock.patch.object(spotify, "installed", return_value=True):
            self.assertEqual(spotify.parse_request("play despacito")["query"], "despacito")
            self.assertIsNone(spotify.parse_request("play despacito on youtube"))
            self.assertIsNone(spotify.parse_request("play the video"))
            self.assertIsNone(spotify.parse_request("play"))
            self.assertIsNone(spotify.parse_request("play music"))
        with mock.patch.object(spotify, "installed", return_value=False):
            self.assertIsNone(spotify.parse_request("play despacito"))

    def test_play_falls_back_to_youtube_when_missing(self):
        with mock.patch.object(spotify, "installed", return_value=False), \
             mock.patch("services.smart_features.open_url", return_value={"success": True}) as op:
            r = spotify.play("despacito")
        self.assertTrue(r["success"])
        self.assertEqual(r["fallback"], "youtube")
        self.assertIn("despacito", op.call_args[0][0])

    def test_web_api_path(self):
        with mock.patch.object(spotify, "installed", return_value=True), \
             mock.patch.object(spotify, "search_uri", return_value=("spotify:track:abc", "Song · Artist")), \
             mock.patch.object(spotify, "_open_uri") as op, \
             mock.patch.object(spotify, "_wait_window", return_value=1), \
             mock.patch.object(spotify, "_is_playing", return_value=True), \
             mock.patch("time.sleep"):
            r = spotify.play("song")
        self.assertTrue(r["success"])
        op.assert_called_once_with("spotify:track:abc")


if __name__ == "__main__":
    unittest.main()
