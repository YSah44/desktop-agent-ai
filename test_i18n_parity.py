"""Slice 10: i18n tables stay in sync; no live OS side effects."""
import os
import unittest

os.environ["DAVI_DISABLE_DESTRUCTIVE"] = "1"


class I18nParityTests(unittest.TestCase):
    def test_all_languages_share_keys(self):
        from services.i18n import LANGUAGES, _STRINGS
        en_keys = set(_STRINGS["en"])
        self.assertTrue(en_keys)
        for lang in LANGUAGES:
            self.assertEqual(set(_STRINGS[lang]), en_keys, lang)

    def test_overlay_polish_keys_translated(self):
        from services.i18n import _STRINGS
        keys = (
            "starting", "chrome_off", "keys_saved", "no_key_changes",
            "mic_silent", "model_saved", "whisper_saved", "step",
            "stopping", "error_status", "shot_done",
            "busy_media", "busy_video", "busy_meeting", "mic_off", "mic_on",
            "provider_saved", "provider_hint_anthropic", "openrouter_key",
            "setup_keys_title", "setup_keys_save", "setup_keys_need",
            "face_min", "face_min_hint", "stuck_think", "stuck_stop", "stg_sub",
            "face_saved", "face_known", "face_forgot", "face_learning", "face_crowd",
            "echo_cancel", "echo_hint", "room_audio", "dash_donate", "busy_voice_hint",
        )
        tr = _STRINGS["tr"]
        en = _STRINGS["en"]
        for key in keys:
            self.assertIn(key, tr)
            self.assertIn(key, en)
            if key != "error_status":
                self.assertNotEqual(tr[key], en[key], key)

    def test_whisper_language_stays_tr_with_overlay(self):
        from services.i18n import whisper_language, get_language
        from services.voice_input import VoiceInputProcessor
        prev_lang = os.environ.get("DAVI_LANGUAGE")
        prev_model = os.environ.get("DAVI_WHISPER_MODEL")
        try:
            os.environ["DAVI_LANGUAGE"] = "tr"
            os.environ["DAVI_WHISPER_MODEL"] = "distil-whisper-large-v3-en"
            self.assertEqual(get_language(), "tr")
            self.assertEqual(whisper_language(), "tr")
            dummy = VoiceInputProcessor.__new__(VoiceInputProcessor)
            dummy.language = "en"
            self.assertEqual(dummy._stt_language(), "tr")
            self.assertEqual(dummy._stt_model(), "whisper-large-v3-turbo")
        finally:
            if prev_lang is None:
                os.environ.pop("DAVI_LANGUAGE", None)
            else:
                os.environ["DAVI_LANGUAGE"] = prev_lang
            if prev_model is None:
                os.environ.pop("DAVI_WHISPER_MODEL", None)
            else:
                os.environ["DAVI_WHISPER_MODEL"] = prev_model


if __name__ == "__main__":
    unittest.main()
